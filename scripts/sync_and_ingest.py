#!/usr/bin/env python3
"""Autonomous 3x/Day Closed-Loop Sync & Ingest Runner (`sync_and_ingest.py`).

Safely connects GeminiScraper (headless=False Chrome profile GUI session),
archive.db (?mode=ro), data/corpus.db, and chapters/core_digest.md:
  1. Concurrency lock (/tmp/corpus_closedloop.lock via fcntl.flock, non-blocking).
  2. Cooldown guard (< 4h since data/closedloop_state.json last_run_utc unless --force).
  3. Online check (socket.create_connection(("gemini.google.com", 443), timeout=5)) unless --skip-scrape.
  4. One-shot scrape: sync_gemini.py + capture_spark_chat.py per non-comment URL in config/spark_watchlist.txt.
  5. Delta compare (archive.db?mode=ro vs corpus.db by rowid watermark / turn_id / sha256):
     - If zero new turns exist: update last_run_utc and exit 0 with ZERO DB writes to corpus.db.
     - If new turns exist: ingest ONLY delta turns as RAW_CLAIM / PROVENANCE_LOG via
       scripts/ingest_session.py and run scripts/compile_digest.py to refresh core_digest.md.
"""

from __future__ import annotations

import argparse
import datetime as dt
import fcntl
import hashlib
import json
import os
import re
import socket
import sqlite3
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from arachne_bridge import open_archive_ro
from compile_digest import compile_digest, resolve_digest_targets
from db_utils import (
    DEFAULT_DB_PATH,
    WORKSPACE_ROOT,
    classify_text_to_section_key,
    get_connection,
    init_db,
)
from ingest_session import clean_gemini_turn_text, ingest_artifact
from stage0_ingest import chunk_text, normalize_whitespace

_SCRAPER_DIR = Path(
    os.environ.get("SCRAPER_DIR", str(WORKSPACE_ROOT / "scraper"))
).expanduser()
_ENV_ARCHIVE_DB = os.environ.get("ARCHIVE_DB", "").strip() or os.environ.get("ARCHIVE_DB_PATH", "").strip()
DEFAULT_ARCHIVE_DB = Path(
    _ENV_ARCHIVE_DB if _ENV_ARCHIVE_DB else str(WORKSPACE_ROOT / "data" / "archive.db")
).expanduser()
DEFAULT_SCRAPER_PY = (
    _SCRAPER_DIR / ".venv" / "bin" / "python"
    if (_SCRAPER_DIR / ".venv" / "bin" / "python").exists()
    else (
        WORKSPACE_ROOT / ".venv" / "bin" / "python3"
        if (WORKSPACE_ROOT / ".venv" / "bin" / "python3").exists()
        else Path(sys.executable)
    )
)
DEFAULT_SYNC_GEMINI = _SCRAPER_DIR / "sync_gemini.py"
DEFAULT_CAPTURE_SPARK = _SCRAPER_DIR / "capture_spark_chat.py"
DEFAULT_WATCHLIST = WORKSPACE_ROOT / "config" / "spark_watchlist.txt"
DEFAULT_STATE_FILE = WORKSPACE_ROOT / "data" / "closedloop_state.json"
DEFAULT_LOG_FILE = WORKSPACE_ROOT / "logs" / "closedloop.log"
DEFAULT_DELTAS_DIR = WORKSPACE_ROOT / "data" / "closedloop_deltas"
DEFAULT_LOCK_FILE = Path("/tmp/corpus_closedloop.lock")
COOLDOWN_SECONDS = 4 * 3600

CHAT_URL_ID_RE = re.compile(r"/(?:app|chat)/([a-zA-Z0-9_-]{8,})")
TURN_ID_REF_RE = re.compile(r"turn_id=([A-Za-z0-9_:-]+)")


def _utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _utc_iso(ts: dt.datetime | None = None) -> str:
    return (ts or _utc_now()).isoformat()


def _log_event(log_file: Path, event: str, payload: dict[str, Any] | None = None) -> None:
    log_file.parent.mkdir(parents=True, exist_ok=True)
    rec = {"ts_utc": _utc_iso(), "event": event, **(payload or {})}
    with log_file.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")


def load_state(state_file: Path) -> dict[str, Any]:
    if not state_file.exists():
        return {}
    try:
        return json.loads(state_file.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_state(state_file: Path, state: dict[str, Any]) -> None:
    state_file.parent.mkdir(parents=True, exist_ok=True)
    tmp = state_file.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(state_file)


def read_watchlist(watchlist_path: Path) -> list[str]:
    if not watchlist_path.exists():
        return []
    urls: list[str] = []
    for raw in watchlist_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        urls.append(line)
    return urls


def extract_chat_ids_from_watchlist(urls: list[str]) -> list[str]:
    cids: list[str] = []
    for u in urls:
        m = CHAT_URL_ID_RE.search(u)
        if m and m.group(1) not in cids:
            cids.append(m.group(1))
    return cids


def check_online(host: str = "gemini.google.com", port: int = 443, timeout_s: float = 5.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout_s):
            return True
    except OSError:
        return False


def _open_corpus_ro(db_path: Path) -> sqlite3.Connection | None:
    if not db_path.exists():
        return None
    conn = sqlite3.connect(f"file:{db_path.expanduser().resolve()}?mode=ro", uri=True, timeout=10.0)
    conn.row_factory = sqlite3.Row
    return conn


def _initial_watermarks(corpus_ro: sqlite3.Connection | None, state: dict[str, Any]) -> tuple[int, set[str], set[str]]:
    """Read high-water archive turn rowid, known chunk sha256s, and known turn_ids without mutating DB."""
    wm = int(state.get("last_archive_turn_rowid") or 0)
    known_shas: set[str] = set()
    known_turn_ids: set[str] = set(str(x) for x in (state.get("ingested_turn_ids") or []) if x)

    if corpus_ro is None:
        return wm, known_shas, known_turn_ids

    if wm == 0:
        has_ds = bool(
            corpus_ro.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='digest_state'").fetchone()
        )
        if has_ds:
            row = corpus_ro.execute("SELECT COALESCE(MAX(last_compiled_turn_id), 0) FROM digest_state").fetchone()
            wm = max(wm, int(row[0] or 0))

    for r in corpus_ro.execute("SELECT sha256, source_ref FROM chunks").fetchall():
        known_shas.add(str(r["sha256"]))
        m = TURN_ID_REF_RE.search(str(r["source_ref"] or ""))
        if m:
            known_turn_ids.add(m.group(1))

    return wm, known_shas, known_turn_ids


def merge_turn_non_regressive(
    existing: dict[str, Any] | None,
    incoming: dict[str, Any],
) -> dict[str, Any]:
    """Idempotent non-regression guard: an empty DOM stub can never overwrite a populated turn."""
    merged = dict(incoming)
    if not existing:
        return merged
    for field in ("user_prompt", "user_html", "model_response", "model_html", "model_thoughts"):
        inc_val = str(merged.get(field) or "")
        ext_val = str(existing.get(field) or "")
        if not inc_val.strip() and ext_val.strip():
            merged[field] = ext_val
    return merged


def audit_archive_hydration(archive_db: Path) -> dict[str, Any]:
    """Read-only (?mode=ro) DOM virtualization completeness audit over archive.db."""
    arch_conn, arch_err = open_archive_ro(archive_db)
    if arch_conn is None:
        return {
            "archive_available": False,
            "error": arch_err,
            "total_dom_slots": 0,
            "hydrated_turns": 0,
            "empty_stub_turns": 0,
            "hydration_pct": 0.0,
            "partial_virtualization_chats": [],
        }
    try:
        rows = arch_conn.execute(
            """
            SELECT c.rowid AS conv_rowid, c.chat_id, COALESCE(c.title, '') AS title,
                   COUNT(t.id) AS total_slots,
                   SUM(
                       CASE
                           WHEN trim(coalesce(t.user_prompt, '')) != ''
                             OR trim(coalesce(t.model_response, '')) != ''
                           THEN 1 ELSE 0
                       END
                   ) AS hydrated_turns
            FROM conversations c
            LEFT JOIN turns t ON t.chat_id = c.chat_id
            GROUP BY c.chat_id
            ORDER BY (COUNT(t.id) - SUM(
                CASE
                    WHEN trim(coalesce(t.user_prompt, '')) != ''
                      OR trim(coalesce(t.model_response, '')) != ''
                    THEN 1 ELSE 0
                END
            )) DESC, c.rowid ASC
            """
        ).fetchall()
        total_slots = 0
        hydrated_total = 0
        partial_chats: list[dict[str, Any]] = []
        for r in rows:
            tot = int(r["total_slots"] or 0)
            hyd = int(r["hydrated_turns"] or 0)
            total_slots += tot
            hydrated_total += hyd
            if tot > 0 and hyd < tot:
                partial_chats.append(
                    {
                        "conv_rowid": int(r["conv_rowid"]),
                        "chat_id": str(r["chat_id"]),
                        "title": str(r["title"]),
                        "hydrated_turns": hyd,
                        "total_dom_slots": tot,
                        "empty_stubs": tot - hyd,
                        "status": "PARTIAL_VIRTUALIZATION",
                    }
                )
        empty_total = total_slots - hydrated_total
        pct = round((hydrated_total / total_slots * 100.0), 2) if total_slots else 100.0
        return {
            "archive_available": True,
            "total_conversations": len(rows),
            "total_dom_slots": total_slots,
            "hydrated_turns": hydrated_total,
            "empty_stub_turns": empty_total,
            "hydration_pct": pct,
            "partial_virtualization_count": len(partial_chats),
            "partial_virtualization_chats": partial_chats[:25],
        }
    finally:
        arch_conn.close()


def detect_archive_deltas(
    *,
    db_path: Path,
    archive_db: Path,
    state: dict[str, Any],
    watchlist_chat_ids: list[str],
) -> dict[str, Any]:
    """Compare archive.db (?mode=ro) against corpus.db (?mode=ro) for unseen turns."""
    arch_conn, arch_err = open_archive_ro(archive_db)
    if arch_conn is None:
        return {"archive_available": False, "error": arch_err, "max_archive_rowid": 0, "delta_by_chat": {}, "delta_turn_count": 0}

    corpus_ro = _open_corpus_ro(db_path)
    try:
        wm_rowid, known_shas, known_turn_ids = _initial_watermarks(corpus_ro, state)
        max_arch_rowid = int(arch_conn.execute("SELECT COALESCE(MAX(id), 0) FROM turns").fetchone()[0])

        # Fetch turns newer than watermark OR belonging to actively watched Spark/Gemini chats
        params: list[Any] = [wm_rowid]
        where_clauses = ["t.id > ?"]
        if watchlist_chat_ids:
            placeholders = ",".join("?" for _ in watchlist_chat_ids)
            where_clauses.append(f"t.chat_id IN ({placeholders})")
            params.extend(watchlist_chat_ids)

        sql = f"""
            SELECT t.id, t.chat_id, t.turn_index, t.turn_id, t.parent_turn_id,
                   t.user_prompt, t.user_html, t.model_response, t.model_html,
                   t.timestamp_hint, t.sha256, COALESCE(c.title, '') AS chat_title
            FROM turns t
            LEFT JOIN conversations c ON c.chat_id = t.chat_id
            WHERE {' OR '.join(where_clauses)}
            ORDER BY t.chat_id, t.turn_index ASC, t.id ASC
        """
        candidates = arch_conn.execute(sql, tuple(params)).fetchall()

        delta_by_chat: dict[str, list[dict[str, Any]]] = {}
        seen_turn_ids_in_batch: set[str] = set()
        delta_turn_count = 0
        empty_stub_turns_skipped = 0
        partial_stub_chats: set[str] = set()

        for row in candidates:
            cid = str(row["chat_id"])
            tidx = int(row["turn_index"] or 0)
            tid = str(row["turn_id"] or "").strip() or None
            turn_rowid = int(row["id"])
            ts_hint = str(row["timestamp_hint"] or "") or None
            turn_sha = str(row["sha256"] or "")

            # Skip if exact turn_id is already recorded in corpus.db or state
            if tid and (tid in known_turn_ids or tid in seen_turn_ids_in_batch):
                continue

            u_txt = clean_gemini_turn_text(row["user_prompt"], row["user_html"], is_user=True)
            m_txt = clean_gemini_turn_text(row["model_response"], row["model_html"], is_user=False)

            # Non-regression guard: never commit empty DOM virtualization stubs or advance their turn_id watermark
            if not u_txt and not m_txt:
                empty_stub_turns_skipped += 1
                partial_stub_chats.add(cid)
                continue

            turn_records: list[dict[str, Any]] = []
            for author, body in (("user", u_txt), ("assistant", m_txt)):
                if not body or len(body) < 10:
                    continue
                for ch in chunk_text(body):
                    norm = normalize_whitespace(ch)
                    if len(norm) < 10:
                        continue
                    ch_sha = hashlib.sha256(norm.encode("utf-8")).hexdigest()
                    if ch_sha in known_shas:
                        continue
                    known_shas.add(ch_sha)
                    turn_records.append(
                        {
                            "chat_id": cid,
                            "chat_title": str(row["chat_title"] or "").strip(),
                            "turn_rowid": turn_rowid,
                            "turn_index": tidx,
                            "turn_id": tid or f"rowid:{turn_rowid}",
                            "parent_turn_id": str(row["parent_turn_id"] or "") or None,
                            "turn_sha256": turn_sha or None,
                            "author": author,
                            "created_at": ts_hint,
                            "content": norm,
                        }
                    )

            if turn_records:
                delta_by_chat.setdefault(cid, []).extend(turn_records)
                delta_turn_count += 1
                if tid:
                    seen_turn_ids_in_batch.add(tid)

        return {
            "archive_available": True,
            "watermark_rowid": wm_rowid,
            "max_archive_rowid": max_arch_rowid,
            "candidates_scanned": len(candidates),
            "empty_stub_turns_skipped": empty_stub_turns_skipped,
            "partial_virtualization_chats": sorted(partial_stub_chats),
            "delta_chat_count": len(delta_by_chat),
            "delta_turn_count": delta_turn_count,
            "delta_chunk_count": sum(len(v) for v in delta_by_chat.values()),
            "delta_by_chat": delta_by_chat,
        }
    finally:
        if corpus_ro is not None:
            corpus_ro.close()
        arch_conn.close()


def _run_scraper_step(cmd: list[str], timeout_s: int) -> dict[str, Any]:
    t0 = time.monotonic()
    try:
        proc = subprocess.run(
            cmd,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
        )
        return {
            "cmd": cmd,
            "returncode": proc.returncode,
            "elapsed_s": round(time.monotonic() - t0, 2),
            "stdout_tail": proc.stdout.splitlines()[-6:],
            "stderr_tail": proc.stderr.splitlines()[-4:],
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "cmd": cmd,
            "returncode": -1,
            "timeout_s": timeout_s,
            "elapsed_s": round(time.monotonic() - t0, 2),
            "error": f"TimeoutExpired after {timeout_s}s: {exc}",
        }
    except Exception as exc:
        return {
            "cmd": cmd,
            "returncode": -1,
            "elapsed_s": round(time.monotonic() - t0, 2),
            "error": f"{type(exc).__name__}: {exc}",
        }


def run_closedloop(
    *,
    db_path: Path = DEFAULT_DB_PATH,
    archive_db: Path = DEFAULT_ARCHIVE_DB,
    watchlist_path: Path = DEFAULT_WATCHLIST,
    state_file: Path = DEFAULT_STATE_FILE,
    log_file: Path = DEFAULT_LOG_FILE,
    deltas_dir: Path = DEFAULT_DELTAS_DIR,
    lock_file: Path = DEFAULT_LOCK_FILE,
    scraper_python: Path = DEFAULT_SCRAPER_PY,
    sync_gemini_script: Path = DEFAULT_SYNC_GEMINI,
    capture_spark_script: Path = DEFAULT_CAPTURE_SPARK,
    dry_run: bool = False,
    force: bool = False,
    skip_scrape: bool = False,
    cooldown_seconds: int = COOLDOWN_SECONDS,
    scrape_timeout_s: int = 240,
    sync_timeout_s: int = 300,
) -> dict[str, Any]:
    lock_file.parent.mkdir(parents=True, exist_ok=True)
    lock_fh = lock_file.open("a+", encoding="utf-8")
    try:
        try:
            fcntl.flock(lock_fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            res = {"status": "lock_held", "lock_file": str(lock_file), "dry_run": dry_run}
            _log_event(log_file, "lock_held", res)
            return res

        now_utc = _utc_now()
        state = load_state(state_file)

        # Cooldown check (< 4 hours since last_run_utc unless --force)
        if not force and state.get("last_run_utc"):
            try:
                prev_dt = dt.datetime.fromisoformat(str(state["last_run_utc"]))
                if prev_dt.tzinfo is None:
                    prev_dt = prev_dt.replace(tzinfo=dt.timezone.utc)
                elapsed = (now_utc - prev_dt).total_seconds()
                if elapsed < cooldown_seconds:
                    res = {
                        "status": "cooldown_active",
                        "elapsed_s": round(elapsed, 1),
                        "cooldown_s": cooldown_seconds,
                        "last_run_utc": state["last_run_utc"],
                        "dry_run": dry_run,
                    }
                    _log_event(log_file, "cooldown_active", res)
                    return res
            except ValueError:
                pass

        # Network reachability check unless --skip-scrape
        online = True
        if not skip_scrape:
            online = check_online("gemini.google.com", 443, timeout_s=5.0)
            if not online and not dry_run:
                res = {"status": "offline_skip", "host": "gemini.google.com:443", "dry_run": dry_run}
                _log_event(log_file, "offline_skip", res)
                return res

        watchlist_urls = read_watchlist(watchlist_path)
        watchlist_chat_ids = extract_chat_ids_from_watchlist(watchlist_urls)
        scrape_runs: list[dict[str, Any]] = []

        if not skip_scrape and not dry_run and online:
            if scraper_python.exists() and sync_gemini_script.exists():
                r_sync = _run_scraper_step([str(scraper_python), str(sync_gemini_script)], sync_timeout_s)
                scrape_runs.append(r_sync)
                _log_event(log_file, "scrape_sync_gemini", r_sync)
            for url in watchlist_urls:
                if scraper_python.exists() and capture_spark_script.exists():
                    r_sp = _run_scraper_step([str(scraper_python), str(capture_spark_script), url], scrape_timeout_s)
                    scrape_runs.append(r_sp)
                    _log_event(log_file, "scrape_spark_url", {"url": url, **r_sp})

        # Delta compare (strictly read-only against archive.db & pre-commit corpus.db)
        delta_info = detect_archive_deltas(
            db_path=db_path,
            archive_db=archive_db,
            state=state,
            watchlist_chat_ids=watchlist_chat_ids,
        )
        if not delta_info["archive_available"]:
            res = {
                "status": "archive_unavailable",
                "error": delta_info.get("error"),
                "dry_run": dry_run,
                "online": online,
            }
            _log_event(log_file, "archive_unavailable", res)
            return res

        if dry_run:
            preview = {
                cid: {
                    "delta_chunks": len(recs),
                    "turn_indices": sorted({int(r["turn_index"]) for r in recs}),
                }
                for cid, recs in delta_info["delta_by_chat"].items()
            }
            res = {
                "status": "dry_run_offline_skip" if (not skip_scrape and not online) else "dry_run_ok",
                "lock_acquired": True,
                "cooldown_active": False,
                "online": online,
                "skip_scrape": skip_scrape,
                "watchlist_urls": watchlist_urls,
                "watermark_rowid": delta_info["watermark_rowid"],
                "max_archive_rowid": delta_info["max_archive_rowid"],
                "delta_chat_count": delta_info["delta_chat_count"],
                "delta_turn_count": delta_info["delta_turn_count"],
                "delta_chunk_count": delta_info["delta_chunk_count"],
                "delta_preview": preview,
            }
            _log_event(log_file, "dry_run", res)
            return res

        # Zero-delta fast path: zero writes to corpus.db; update last_run_utc in state
        if delta_info["delta_turn_count"] == 0:
            new_state = {
                **state,
                "last_run_utc": _utc_iso(now_utc),
                "last_archive_turn_rowid": max(
                    int(state.get("last_archive_turn_rowid") or 0),
                    int(delta_info["max_archive_rowid"]),
                ),
                "last_sync_status": "up_to_date",
                "last_delta_chunks_inserted": 0,
            }
            save_state(state_file, new_state)
            res = {
                "status": "up_to_date",
                "corpus_db_writes": 0,
                "watermark_rowid": delta_info["watermark_rowid"],
                "max_archive_rowid": delta_info["max_archive_rowid"],
                "scrape_runs": scrape_runs,
                "last_run_utc": new_state["last_run_utc"],
            }
            _log_event(log_file, "up_to_date", res)
            return res

        # Non-zero delta: serialize cleaned JSON delta manifests per chat_id & ingest via ingest_session.py
        deltas_dir.mkdir(parents=True, exist_ok=True)
        ts_stamp = now_utc.strftime("%Y%m%dT%H%M%SZ")
        ingested_reports: list[dict[str, Any]] = []
        affected_keys: set[str] = set()
        new_turn_ids: list[str] = []
        total_inserted = 0

        for cid, recs in delta_info["delta_by_chat"].items():
            manifest = {
                "chat_id": cid,
                "source": "archive.db",
                "captured_at_utc": _utc_iso(now_utc),
                "epistemic_tier": "RAW_CLAIM",
                "turns": recs,
            }
            manifest_path = deltas_dir / f"{cid}_delta_{ts_stamp}.json"
            manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

            ing_res = ingest_artifact(
                db_path=db_path,
                source_path=manifest_path,
                source_tag="PROVENANCE_LOG",
                chat_id=cid,
                sync_digest=False,
                archive_db=archive_db,
            )
            ingested_reports.append(
                {
                    "chat_id": cid,
                    "status": ing_res["status"],
                    "chunks_inserted": ing_res["chunks_inserted"],
                    "duplicates_skipped": ing_res["duplicates_skipped"],
                    "epistemic_tier": ing_res["epistemic_tier"],
                    "nodes_auto_promoted": ing_res["nodes_auto_promoted"],
                    "section_key": ing_res.get("section_key"),
                    "manifest_path": str(manifest_path),
                }
            )
            total_inserted += int(ing_res["chunks_inserted"])
            if ing_res.get("section_key"):
                affected_keys.add(str(ing_res["section_key"]))
            for rec in recs:
                if rec.get("turn_id") and not str(rec["turn_id"]).startswith("rowid:"):
                    new_turn_ids.append(str(rec["turn_id"]))
                affected_keys.add(classify_text_to_section_key(rec["content"][:1500]))

        # Targeted delta digest recompile -> refreshes chapters/core_digest.md + changed # KEYWORD: slices
        init_db(db_path)
        conn = get_connection(db_path)
        try:
            core_path, slices_dir = resolve_digest_targets(db_path)
            digest_res = compile_digest(
                conn,
                archive_db=archive_db,
                core_path=core_path,
                slices_dir=slices_dir,
                only_section_keys=affected_keys or None,
                force_all=False,
                sync_ouroboros=True,
            )
        finally:
            conn.close()

        prev_ids = [str(x) for x in (state.get("ingested_turn_ids") or []) if x]
        merged_ids = list(dict.fromkeys(prev_ids + new_turn_ids))[-2000:]
        new_state = {
            **state,
            "last_run_utc": _utc_iso(now_utc),
            "last_archive_turn_rowid": max(
                int(state.get("last_archive_turn_rowid") or 0),
                int(delta_info["max_archive_rowid"]),
            ),
            "last_sync_status": "ingested",
            "last_delta_chunks_inserted": total_inserted,
            "ingested_turn_ids": merged_ids,
        }
        save_state(state_file, new_state)

        res = {
            "status": "ingested",
            "scrape_runs": scrape_runs,
            "delta_turns": delta_info["delta_turn_count"],
            "chunks_inserted": total_inserted,
            "epistemic_tier": "RAW_CLAIM",
            "nodes_auto_promoted": 0,
            "ingested_reports": ingested_reports,
            "digest_delta": digest_res,
            "last_run_utc": new_state["last_run_utc"],
            "last_archive_turn_rowid": new_state["last_archive_turn_rowid"],
        }
        _log_event(log_file, "ingested", res)
        return res
    finally:
        try:
            fcntl.flock(lock_fh.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        lock_fh.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Autonomous 3x/day closed-loop Gemini/Spark -> Corpus delta sync")
    parser.add_argument("--dry-run", action="store_true", help="Inspect lock, cooldown, network, and delta without writing")
    parser.add_argument("--force", action="store_true", help="Bypass the 4-hour wake-from-sleep cooldown")
    parser.add_argument("--skip-scrape", action="store_true", help="Skip browser scraping and run archive.db -> corpus.db delta only")
    parser.add_argument("--audit-hydration", action="store_true", help="Run read-only (?mode=ro) DOM virtualization completeness audit on archive.db")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--archive-db", type=Path, default=DEFAULT_ARCHIVE_DB)
    parser.add_argument("--watchlist", type=Path, default=DEFAULT_WATCHLIST)
    parser.add_argument("--state-file", type=Path, default=DEFAULT_STATE_FILE)
    parser.add_argument("--log-file", type=Path, default=DEFAULT_LOG_FILE)
    parser.add_argument("--deltas-dir", type=Path, default=DEFAULT_DELTAS_DIR)
    parser.add_argument("--lock-file", type=Path, default=DEFAULT_LOCK_FILE)
    args = parser.parse_args()

    if args.audit_hydration:
        res = audit_archive_hydration(args.archive_db)
        print(json.dumps(res, indent=2, ensure_ascii=False))
        return

    res = run_closedloop(
        db_path=args.db,
        archive_db=args.archive_db,
        watchlist_path=args.watchlist,
        state_file=args.state_file,
        log_file=args.log_file,
        deltas_dir=args.deltas_dir,
        lock_file=args.lock_file,
        dry_run=args.dry_run,
        force=args.force,
        skip_scrape=args.skip_scrape,
    )
    print(json.dumps(res, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
