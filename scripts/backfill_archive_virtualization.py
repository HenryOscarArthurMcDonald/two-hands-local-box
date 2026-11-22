#!/usr/bin/env python3
"""Safe, Timestamp-Backed-Up Backfill for Browser DOM Virtualization Data Loss.

Recovers plaintext `user_prompt` and `model_response` on `archive.db` turn rows
where Angular's off-screen CSS virtualization (`content-visibility: auto`) caused
`el.innerText` to return "" while `el.innerHTML` (`user_html` / `model_html`) still
preserved the complete DOM subtree.

Safety guarantees:
  1. Takes a timestamped SQLite online backup (`archive.db.bak.YYYYMMDDTHHMMSSZ`)
     and runs `PRAGMA integrity_check` on the backup BEFORE any write.
  2. Enforces an idempotent non-regression guard (`merge_turn_non_regressive`) so
     an empty stub can NEVER overwrite an already-populated turn field.
  3. Never fabricates or interpolates missing prose: any turn remaining empty after
     local HTML/export inspection is explicitly logged as `UNRECOVERABLE_REMOTE`.
  4. Rebuilds `turns_fts` cleanly and recomputes `conversations` char counters.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import html as html_lib
import html.parser
import json
import os
import re
import sqlite3
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from db_utils import WORKSPACE_ROOT

_ENV_ARCHIVE_DB = os.environ.get("ARCHIVE_DB", "").strip() or os.environ.get("ARCHIVE_DB_PATH", "").strip()
DEFAULT_ARCHIVE_DB = Path(
    _ENV_ARCHIVE_DB if _ENV_ARCHIVE_DB else str(WORKSPACE_ROOT / "data" / "archive.db")
).expanduser()
DEFAULT_REPORT_PATH = WORKSPACE_ROOT / "data" / "archive_backfill_report.json"

DATA_URI_RE = re.compile(
    r"data:[a-z0-9.+_-]+/[a-z0-9.+_-]+(?:;[a-z0-9=._-]+)*;base64,[a-z0-9+/=\r\n]+",
    re.IGNORECASE,
)


class _CleanHTMLParser(html.parser.HTMLParser):
    """Strip HTML/Angular DOM tags while skipping style/script/button/hidden blocks."""

    _SKIP_TAGS = {"script", "style", "noscript", "svg", "template", "button", "mat-icon", "gem-icon"}
    _SKIP_CLASSES = (
        "cdk-visually-hidden",
        "screen-reader-user-query-label",
        "luminous-toggle-container",
        "code-block-decoration",
    )
    _BLOCK_TAGS = {
        "p", "div", "section", "article", "header", "footer", "main",
        "aside", "nav", "br", "hr", "li", "ul", "ol", "blockquote",
        "pre", "tr", "td", "th", "h1", "h2", "h3", "h4", "h5", "h6",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip_stack: list[str] = []
        self._math_stack: list[str] = []
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        low = tag.lower()
        amap = {k.lower(): (v or "") for k, v in attrs}
        cls = amap.get("class", "").lower()
        if self._skip_stack:
            self._skip_stack.append(low)
            return
        if low in self._SKIP_TAGS or any(sc in cls for sc in self._SKIP_CLASSES):
            self._skip_stack.append(low)
            return
        if self._math_stack:
            self._math_stack.append(low)
            return
        if ("math-inline" in cls or "math-block" in cls) and "data-math" in amap:
            self._parts.append(f" {amap['data-math'].strip()} ")
            self._math_stack.append(low)
            return
        if low in self._BLOCK_TAGS:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        low = tag.lower()
        if self._skip_stack:
            self._skip_stack.pop()
            return
        if self._math_stack:
            self._math_stack.pop()
            return
        if low in self._BLOCK_TAGS:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip_stack and not self._math_stack and data:
            self._parts.append(data)

    def get_text(self) -> str:
        return "".join(self._parts)


def _normalize_ws(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def clean_gemini_turn_text(plain_text: str | None, html_text: str | None, *, is_user: bool = False) -> str:
    raw = (plain_text or "").strip()
    html_raw = (html_text or "").strip()
    if raw and not re.search(r"<(?:span|div|p|h[1-6]|user-query|mat-icon|button|code|pre)\b|_ngcontent", raw, re.IGNORECASE):
        text = _normalize_ws(DATA_URI_RE.sub(" ", html_lib.unescape(raw)))
    elif html_raw:
        parser = _CleanHTMLParser()
        parser.feed(DATA_URI_RE.sub(" ", html_raw))
        parser.close()
        text = _normalize_ws(DATA_URI_RE.sub(" ", parser.get_text()))
    elif raw:
        parser = _CleanHTMLParser()
        parser.feed(DATA_URI_RE.sub(" ", raw))
        parser.close()
        text = _normalize_ws(DATA_URI_RE.sub(" ", parser.get_text()))
    else:
        return ""

    if is_user:
        lines = text.splitlines()
        if lines and lines[0].startswith("You said "):
            preview = lines[0][len("You said ") :].strip()
            rest = "\n".join(lines[1:]).lstrip()
            if "…" in preview or preview.endswith("...") or rest.startswith(preview):
                lines = rest.splitlines()
        elif lines and lines[0].strip() == "You said":
            lines = lines[1:]
        text = _normalize_ws("\n".join(lines))
    return text


def merge_turn_non_regressive(existing: dict[str, Any] | None, incoming: dict[str, Any]) -> dict[str, Any]:
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


def _utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    return bool(conn.execute("SELECT 1 FROM sqlite_master WHERE name = ?", (name,)).fetchone())


def snapshot_hydration_metrics(conn: sqlite3.Connection) -> dict[str, Any]:
    """Compute exact global, Row-262, S1.7 (rowids 137..158), and S2.2 (rowids 91..113) hydration stats."""
    rows = conn.execute(
        """
        SELECT c.rowid AS conv_rowid, c.chat_id, COALESCE(c.title, '') AS title,
               COUNT(t.id) AS total_turns,
               SUM(
                   CASE
                       WHEN trim(coalesce(t.user_prompt, '')) != ''
                         OR trim(coalesce(t.model_response, '')) != ''
                       THEN 1 ELSE 0
                   END
               ) AS active_turns,
               SUM(length(coalesce(t.user_prompt, '')) + length(coalesce(t.model_response, ''))) AS total_chars
        FROM conversations c
        LEFT JOIN turns t ON t.chat_id = c.chat_id
        GROUP BY c.chat_id
        ORDER BY c.rowid ASC
        """
    ).fetchall()

    total_turns = sum(int(r["total_turns"] or 0) for r in rows)
    active_turns = sum(int(r["active_turns"] or 0) for r in rows)
    empty_turns = total_turns - active_turns
    total_chars = sum(int(r["total_chars"] or 0) for r in rows)

    def _slice_stats(pred) -> dict[str, Any]:
        sub = [r for r in rows if pred(r)]
        tot = sum(int(r["total_turns"] or 0) for r in sub)
        act = sum(int(r["active_turns"] or 0) for r in sub)
        return {
            "conversations": len(sub),
            "active_turns": act,
            "total_turns": tot,
            "empty_turns": tot - act,
            "hydration_pct": round((act / tot * 100.0), 2) if tot else 100.0,
        }

    row_262 = next((r for r in rows if int(r["conv_rowid"]) == 262), None)
    return {
        "total_conversations": len(rows),
        "active_turns": active_turns,
        "total_turns": total_turns,
        "empty_turns": empty_turns,
        "hydration_pct": round((active_turns / total_turns * 100.0), 2) if total_turns else 100.0,
        "total_chars": total_chars,
        "conversations_with_empty_turns": sum(1 for r in rows if int(r["total_turns"] or 0) > int(r["active_turns"] or 0)),
        "row_262": (
            {
                "conv_rowid": 262,
                "chat_id": str(row_262["chat_id"]),
                "title": str(row_262["title"]),
                "active_turns": int(row_262["active_turns"] or 0),
                "total_turns": int(row_262["total_turns"] or 0),
                "empty_turns": int(row_262["total_turns"] or 0) - int(row_262["active_turns"] or 0),
            }
            if row_262
            else None
        ),
        "stratum_S1_7_rowids_137_158": _slice_stats(lambda r: 137 <= int(r["conv_rowid"]) <= 158),
        "stratum_S2_2_rowids_91_113": _slice_stats(lambda r: 91 <= int(r["conv_rowid"]) <= 113),
        "per_conversation": {
            str(r["chat_id"]): {
                "conv_rowid": int(r["conv_rowid"]),
                "title": str(r["title"]),
                "active_turns": int(r["active_turns"] or 0),
                "total_turns": int(r["total_turns"] or 0),
            }
            for r in rows
        },
    }


def backup_sqlite_db(src_db: Path) -> Path:
    """Create a timestamped SQLite online backup and verify PRAGMA integrity_check."""
    ts = _utc_now().strftime("%Y%m%dT%H%M%SZ")
    bak_path = src_db.with_name(f"{src_db.name}.bak.{ts}")
    src_conn = sqlite3.connect(f"file:{src_db.expanduser().resolve()}?mode=ro", uri=True)
    dst_conn = sqlite3.connect(str(bak_path))
    try:
        src_conn.backup(dst_conn)
        chk = dst_conn.execute("PRAGMA integrity_check").fetchone()[0]
        if chk != "ok":
            raise RuntimeError(f"Backup integrity_check failed: {chk}")
    finally:
        dst_conn.close()
        src_conn.close()
    return bak_path


def run_backfill(
    archive_db: Path = DEFAULT_ARCHIVE_DB,
    *,
    report_out: Path | None = DEFAULT_REPORT_PATH,
    dry_run: bool = False,
    skip_backup: bool = False,
) -> dict[str, Any]:
    archive_db = archive_db.expanduser().resolve()
    if not archive_db.exists():
        raise FileNotFoundError(f"archive.db not found at {archive_db}")

    # 1. Read-only BEFORE snapshot
    ro_conn = sqlite3.connect(f"file:{archive_db}?mode=ro", uri=True)
    ro_conn.row_factory = sqlite3.Row
    try:
        before_full = snapshot_hydration_metrics(ro_conn)
    finally:
        ro_conn.close()

    backup_path: Path | None = None
    if not dry_run and not skip_backup:
        backup_path = backup_sqlite_db(archive_db)

    conn = sqlite3.connect(f"file:{archive_db}?mode=ro", uri=True) if dry_run else sqlite3.connect(str(archive_db), timeout=30.0)
    conn.row_factory = sqlite3.Row
    try:
        candidates = conn.execute(
            """
            SELECT id, chat_id, turn_index, turn_id, user_prompt, user_html,
                   model_response, model_html, model_thoughts, sha256
            FROM turns
            WHERE (trim(coalesce(user_prompt, '')) = '' AND trim(coalesce(user_html, '')) != '')
               OR (trim(coalesce(model_response, '')) = '' AND trim(coalesce(model_html, '')) != '')
               OR (trim(coalesce(user_prompt, '')) = '' AND trim(coalesce(model_response, '')) = '')
            ORDER BY chat_id, turn_index, id
            """
        ).fetchall()

        recovered_turns = 0
        recovered_words = 0
        recovered_chars = 0
        unrecoverable_turns: list[dict[str, Any]] = []
        affected_chats: set[str] = set()
        updates: list[tuple[str, str, int, int, str, int]] = []

        for r in candidates:
            existing = {
                "user_prompt": r["user_prompt"] or "",
                "user_html": r["user_html"] or "",
                "model_response": r["model_response"] or "",
                "model_html": r["model_html"] or "",
                "model_thoughts": r["model_thoughts"] or "",
            }
            new_u = existing["user_prompt"]
            new_m = existing["model_response"]

            if not new_u.strip() and existing["user_html"].strip():
                new_u = clean_gemini_turn_text("", existing["user_html"], is_user=True)
            if not new_m.strip() and existing["model_html"].strip():
                new_m = clean_gemini_turn_text("", existing["model_html"], is_user=False)

            merged = merge_turn_non_regressive(
                existing,
                {
                    **existing,
                    "user_prompt": new_u,
                    "model_response": new_m,
                },
            )
            final_u = merged["user_prompt"]
            final_m = merged["model_response"]

            if not final_u.strip() and not final_m.strip():
                unrecoverable_turns.append(
                    {
                        "turn_rowid": int(r["id"]),
                        "chat_id": str(r["chat_id"]),
                        "turn_index": int(r["turn_index"] or 0),
                        "status": "UNRECOVERABLE_REMOTE",
                    }
                )
                continue

            changed = (final_u != existing["user_prompt"]) or (final_m != existing["model_response"])
            if changed:
                recovered_turns += 1
                added_u = final_u if not existing["user_prompt"].strip() else ""
                added_m = final_m if not existing["model_response"].strip() else ""
                recovered_words += len(added_u.split()) + len(added_m.split())
                recovered_chars += len(added_u) + len(added_m)
                affected_chats.add(str(r["chat_id"]))
                u_tok = max(1, len(final_u) // 4) if final_u else 0
                m_tok = max(1, len(final_m) // 4) if final_m else 0
                cur_sha = str(r["sha256"] or "").strip()
                if not cur_sha:
                    cur_sha = hashlib.sha256(
                        json.dumps([r["turn_index"], final_u, final_m], ensure_ascii=False).encode("utf-8")
                    ).hexdigest()
                updates.append((final_u, final_m, u_tok, m_tok, cur_sha, int(r["id"])))

        unrecoverable_chat_ids = sorted({u["chat_id"] for u in unrecoverable_turns})

        if not dry_run:
            with conn:
                if updates:
                    conn.executemany(
                        """
                        UPDATE turns
                        SET user_prompt = ?,
                            model_response = ?,
                            user_token_estimate = ?,
                            model_token_estimate = ?,
                            sha256 = ?
                        WHERE id = ?
                        """,
                        updates,
                    )

                # Recompute conversations char totals and mark recovered/unrecoverable status cleanly
                for cid in sorted(affected_chats | set(unrecoverable_chat_ids)):
                    agg = conn.execute(
                        """
                        SELECT COUNT(*) AS tot,
                               SUM(CASE WHEN trim(coalesce(user_prompt,''))!='' OR trim(coalesce(model_response,''))!='' THEN 1 ELSE 0 END) AS act,
                               COALESCE(SUM(length(coalesce(user_prompt,''))), 0) AS u_chars,
                               COALESCE(SUM(length(coalesce(model_response,''))), 0) AS m_chars
                        FROM turns WHERE chat_id = ?
                        """,
                        (cid,),
                    ).fetchone()
                    tot = int(agg["tot"] or 0)
                    act = int(agg["act"] or 0)
                    if act < tot:
                        new_status = "UNRECOVERABLE_REMOTE"
                        note = f"UNRECOVERABLE_REMOTE: {act}/{tot} turns hydrated after local HTML backfill."
                    else:
                        new_status = "backfilled_from_dom_html"
                        note = f"Hydrated {act}/{tot} turns via non-regressive DOM HTML backfill."
                    conn.execute(
                        """
                        UPDATE conversations
                        SET total_user_chars = ?,
                            total_model_chars = ?,
                            status = ?,
                            error_message = ?
                        WHERE chat_id = ?
                        """,
                        (int(agg["u_chars"]), int(agg["m_chars"]), new_status, note, cid),
                    )

                # Rebuild turns_fts cleanly so all recovered prose is immediately searchable
                if updates and _table_exists(conn, "turns_fts"):
                    conn.execute("DELETE FROM turns_fts")
                    conn.execute(
                        """
                        INSERT INTO turns_fts (rowid, chat_id, title, user_prompt, model_response)
                        SELECT t.id, t.chat_id, COALESCE(c.title, ''),
                               COALESCE(t.user_prompt, ''), COALESCE(t.model_response, '')
                        FROM turns t
                        LEFT JOIN conversations c ON c.chat_id = t.chat_id
                        """
                    )

            integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
            if integrity != "ok":
                raise RuntimeError(f"Post-backfill integrity_check failed: {integrity}")
            after_full = snapshot_hydration_metrics(conn)
        else:
            integrity = "dry_run_not_written"
            after_full = before_full

        # Build compact per-affected-conversation diff
        before_map = before_full.pop("per_conversation")
        after_map = after_full.pop("per_conversation") if after_full is not before_full else before_map
        conv_diffs = []
        for cid in sorted(affected_chats | set(unrecoverable_chat_ids), key=lambda c: before_map.get(c, {}).get("conv_rowid", 0)):
            b = before_map.get(cid, {})
            a = after_map.get(cid, b)
            conv_diffs.append(
                {
                    "conv_rowid": b.get("conv_rowid"),
                    "chat_id": cid,
                    "title": b.get("title", ""),
                    "before_active": b.get("active_turns", 0),
                    "after_active": a.get("active_turns", 0) if not dry_run else b.get("total_turns", 0) - sum(1 for u in unrecoverable_turns if u["chat_id"] == cid),
                    "total_turns": b.get("total_turns", 0),
                    "status": "UNRECOVERABLE_REMOTE" if cid in unrecoverable_chat_ids else "RECOVERED_LOCAL_DOM_HTML",
                }
            )

        report = {
            "generated_at_utc": _utc_now().isoformat(),
            "archive_db": str(archive_db),
            "dry_run": dry_run,
            "backup_path": str(backup_path) if backup_path else None,
            "post_backfill_integrity_check": integrity,
            "before": before_full,
            "after": after_full,
            "recovery_summary": {
                "candidates_inspected": len(candidates),
                "turns_recovered_from_dom_html": recovered_turns,
                "conversations_recovered": len(affected_chats),
                "recovered_words_est": recovered_words,
                "recovered_chars": recovered_chars,
                "unrecoverable_remote_turns": len(unrecoverable_turns),
                "unrecoverable_remote_chats": unrecoverable_chat_ids,
            },
            "affected_conversations": conv_diffs,
        }

        if report_out is not None and not dry_run:
            report_out.parent.mkdir(parents=True, exist_ok=True)
            report_out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

        return report
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Safe timestamp-backed-up backfill for archive.db DOM virtualization stubs")
    parser.add_argument("--archive-db", type=Path, default=DEFAULT_ARCHIVE_DB, help="Path to archive.db")
    parser.add_argument("--report-out", type=Path, default=DEFAULT_REPORT_PATH, help="JSON backfill log output path")
    parser.add_argument("--dry-run", action="store_true", help="Inspect recoverable turns without writing to archive.db")
    parser.add_argument("--skip-backup", action="store_true", help="Skip timestamped backup (for isolated unit tests only)")
    args = parser.parse_args()

    rep = run_backfill(
        args.archive_db,
        report_out=args.report_out,
        dry_run=args.dry_run,
        skip_backup=args.skip_backup,
    )
    compact = {k: v for k, v in rep.items() if k != "affected_conversations"}
    compact["affected_conversations_count"] = len(rep["affected_conversations"])
    print(json.dumps(compact, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
