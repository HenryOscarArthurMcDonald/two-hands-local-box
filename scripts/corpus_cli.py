#!/usr/bin/env python3
"""Unified Single-Entry CLI (`corpus_cli.py`) for the Epistemic Corpus Kernel.

Subcommands:
  corpus status                      DB counts, open flags, digest watermark, pending handoffs
  corpus sync                        Delta closed-loop sync or Stage 0 ingestion
  corpus verify                      PRAGMA integrity/FK checks, test_pilot_harness, all 3 PDF SHA-256s
  corpus build --vol 1|2|3|all       Re-render selected publication volume + verify .sha256
  corpus queue [list|enqueue|approve|update|run]
                                     Inspect, approve, update, or execute handoff_queue tasks

Path-agnostic: honors CORPUS_HOME (defaulting to repo root derived from __file__).
Pure Python stdlib so it runs cleanly under both `.venv/bin/python3` and system `python3`.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from db_utils import (
    DEFAULT_DB_PATH,
    VALID_HANDOFF_STATUSES,
    WORKSPACE_ROOT,
    enqueue_handoff,
    get_connection,
    list_handoffs,
    update_handoff_status,
)

PDF_CHECKSUMS: dict[str, str] = {
    "1": "two_hands_decentralized_whitepaper.pdf.sha256",
    "2": "corpus_history_companion_volume.pdf.sha256",
    "3": "corpus_verbatim_dialogue_complete.pdf.sha256",
    "parables": "corpus_failures_and_parables.pdf.sha256",
}


def _open_ro(db_path: Path) -> sqlite3.Connection:
    resolved = db_path.expanduser().resolve()
    if not resolved.exists():
        raise FileNotFoundError(f"Corpus DB not found: {resolved}")
    conn = sqlite3.connect(f"file:{resolved}?mode=ro", uri=True, timeout=10.0)
    conn.row_factory = sqlite3.Row
    return conn


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    return bool(
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type IN ('table', 'view') AND name = ?",
            (table_name,),
        ).fetchone()
    )


def _find_python_with_module(module_name: str, prefer_venv: bool = False) -> str:
    """Select an interpreter capable of importing `module_name` across .venv and system Python."""
    venv_py = WORKSPACE_ROOT / ".venv" / "bin" / "python3"
    candidates: list[str] = []
    if prefer_venv and venv_py.exists():
        candidates.append(str(venv_py))
    candidates.append(sys.executable)
    for extra in (
        shutil.which("python3"),
        "/Library/Frameworks/Python.framework/Versions/3.14/bin/python3",
        str(venv_py) if venv_py.exists() else None,
    ):
        if extra and extra not in candidates:
            candidates.append(extra)
    for py in candidates:
        try:
            proc = subprocess.run(
                [py, "-c", f"import {module_name}"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=10,
                check=False,
            )
            if proc.returncode == 0:
                return py
        except OSError:
            continue
    return sys.executable


def collect_status(db_path: Path = DEFAULT_DB_PATH) -> dict[str, Any]:
    """Read-only status summary across corpus.db, core_digest.md, and handoff_queue."""
    resolved = db_path.expanduser().resolve()
    conn = _open_ro(resolved)
    try:
        tiers = {
            r["epistemic_tier"]: int(r["cnt"])
            for r in conn.execute(
                "SELECT epistemic_tier, COUNT(*) AS cnt FROM nodes GROUP BY epistemic_tier ORDER BY epistemic_tier"
            ).fetchall()
        }
        chunks = int(conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0])
        edges = int(conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0])
        bridges = (
            int(conn.execute("SELECT COUNT(*) FROM concept_bridges").fetchone()[0])
            if _table_exists(conn, "concept_bridges")
            else 0
        )
        open_flags = (
            int(conn.execute("SELECT COUNT(*) FROM node_audit_flags WHERE resolved = 0").fetchone()[0])
            if _table_exists(conn, "node_audit_flags")
            else 0
        )
        total_flags = (
            int(conn.execute("SELECT COUNT(*) FROM node_audit_flags").fetchone()[0])
            if _table_exists(conn, "node_audit_flags")
            else 0
        )
        digest_wm = None
        if _table_exists(conn, "digest_state"):
            row = conn.execute(
                "SELECT section_key, last_compiled_node_id, last_compiled_turn_id, "
                "substr(section_sha256, 1, 12) AS sha_prefix, updated_at "
                "FROM digest_state WHERE section_key = 'CORE_DIGEST'"
            ).fetchone()
            digest_wm = dict(row) if row else None

        handoffs = list_handoffs(conn, limit=500)
        by_status: dict[str, int] = {}
        for h in handoffs:
            by_status[h["status"]] = by_status.get(h["status"], 0) + 1

        core_path = WORKSPACE_ROOT / "chapters" / "core_digest.md"
        core_bytes = core_path.stat().st_size if core_path.exists() else 0

        return {
            "corpus_home": str(WORKSPACE_ROOT),
            "db_path": str(resolved),
            "db_bytes": resolved.stat().st_size,
            "nodes_total": sum(tiers.values()),
            "node_tiers": tiers,
            "chunks": chunks,
            "edges": edges,
            "concept_bridges": bridges,
            "open_audit_flags": open_flags,
            "total_audit_flags": total_flags,
            "core_digest": {
                "path": str(core_path),
                "bytes": core_bytes,
                "kb": round(core_bytes / 1024.0, 2),
                "watermark": digest_wm,
            },
            "handoff_queue": {
                "total": len(handoffs),
                "pending": by_status.get("PENDING", 0) + by_status.get("NEEDS_APPROVAL", 0),
                "approved": by_status.get("APPROVED", 0),
                "by_status": by_status,
            },
        }
    finally:
        conn.close()


def cmd_status(args: argparse.Namespace) -> int:
    data = collect_status(args.db)
    if args.json:
        print(json.dumps(data, indent=2, ensure_ascii=False))
        return 0
    print(f"CORPUS_HOME : {data['corpus_home']}")
    print(f"Database    : {data['db_path']} ({data['db_bytes'] / (1024 * 1024):.2f} MB)")
    print(
        f"Graph       : {data['nodes_total']} nodes | {data['edges']} edges | "
        f"{data['chunks']} chunks | {data['concept_bridges']} bridges"
    )
    tiers_str = ", ".join(f"{k}={v}" for k, v in data["node_tiers"].items())
    print(f"Tiers       : {tiers_str}")
    print(f"Audit Flags : {data['open_audit_flags']} open / {data['total_audit_flags']} total")
    wm = data["core_digest"]["watermark"]
    if wm:
        print(
            f"Core Digest : {data['core_digest']['kb']:.2f} KB "
            f"(max_node=#{wm['last_compiled_node_id']}, max_turn={wm['last_compiled_turn_id']}, sha={wm['sha_prefix']})"
        )
    else:
        print(f"Core Digest : {data['core_digest']['kb']:.2f} KB (no CORE_DIGEST watermark)")
    hq = data["handoff_queue"]
    print(f"Handoff Q   : {hq['total']} total ({hq['pending']} pending/needs_approval, {hq['approved']} approved)")
    return 0


def cmd_sync(args: argparse.Namespace) -> int:
    if args.mode == "stage0":
        py = _find_python_with_module("sqlite3")
        cmd = [py, str(WORKSPACE_ROOT / "scripts" / "stage0_ingest.py"), "--db", str(args.db)]
        if args.input:
            cmd.extend(["--input", str(args.input)])
        if args.build_physics_slice:
            cmd.append("--build-physics-slice")
        return subprocess.run(cmd, cwd=str(WORKSPACE_ROOT), check=False).returncode

    py = _find_python_with_module("sklearn")
    cmd = [py, str(WORKSPACE_ROOT / "scripts" / "sync_and_ingest.py"), "--db", str(args.db)]
    if args.force:
        cmd.append("--force")
    if args.skip_scrape:
        cmd.append("--skip-scrape")
    if args.dry_run:
        cmd.append("--dry-run")
    return subprocess.run(cmd, cwd=str(WORKSPACE_ROOT), check=False).returncode


def verify_pdf_checksums(vols: list[str] | None = None) -> list[dict[str, Any]]:
    out_dir = WORKSPACE_ROOT / "output"
    target_vols = vols or ["1", "2", "3"]
    results: list[dict[str, Any]] = []
    for v in target_vols:
        sha_file = PDF_CHECKSUMS[v]
        sha_path = out_dir / sha_file
        if not sha_path.exists():
            results.append({"volume": v, "file": sha_file, "ok": False, "detail": "missing .sha256 file"})
            continue
        proc = subprocess.run(
            ["shasum", "-a", "256", "-c", sha_file],
            cwd=str(out_dir),
            capture_output=True,
            text=True,
            check=False,
        )
        detail = (proc.stdout or proc.stderr or "").strip()
        results.append({"volume": v, "file": sha_file, "ok": proc.returncode == 0, "detail": detail})
    return results


def cmd_verify(args: argparse.Namespace) -> int:
    report: dict[str, Any] = {"db_path": str(args.db.expanduser().resolve()), "checks": {}}
    all_ok = True

    # 1. Read-only SQLite integrity_check, foreign_key_check, and open audit flags
    conn = _open_ro(args.db)
    try:
        ic_rows = [str(r[0]) for r in conn.execute("PRAGMA integrity_check;").fetchall()]
        ic_ok = ic_rows == ["ok"]
        fk_rows = [tuple(r) for r in conn.execute("PRAGMA foreign_key_check;").fetchall()]
        fk_ok = len(fk_rows) == 0
        nodes_cnt = int(conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0])
        open_flags = (
            int(conn.execute("SELECT COUNT(*) FROM node_audit_flags WHERE resolved = 0").fetchone()[0])
            if _table_exists(conn, "node_audit_flags")
            else 0
        )
        report["checks"]["sqlite_integrity"] = {"ok": ic_ok, "result": ic_rows}
        report["checks"]["foreign_keys"] = {"ok": fk_ok, "violations": len(fk_rows)}
        report["checks"]["audit_flags"] = {"ok": open_flags == 0, "nodes": nodes_cnt, "open_flags": open_flags}
        if not (ic_ok and fk_ok and open_flags == 0):
            all_ok = False
    finally:
        conn.close()

    # 2. Full unittest suite (scripts/test_pilot_harness.py)
    if not args.skip_tests:
        py = _find_python_with_module("sklearn")
        proc = subprocess.run(
            [py, "-m", "unittest", "scripts/test_pilot_harness.py", "-v"],
            cwd=str(WORKSPACE_ROOT),
            capture_output=True,
            text=True,
            check=False,
        )
        t_ok = proc.returncode == 0
        tail = "\n".join((proc.stderr or proc.stdout or "").strip().splitlines()[-4:])
        report["checks"]["unittest_harness"] = {"ok": t_ok, "python": py, "summary": tail}
        if not t_ok:
            all_ok = False

    # 3. SHA-256 verification on all published PDFs (Vols 1, 2, 3 + Failures & Parables)
    if not args.skip_pdfs:
        pdf_res = verify_pdf_checksums(["1", "2", "3", "parables"])
        p_ok = all(r["ok"] for r in pdf_res)
        report["checks"]["pdf_checksums"] = {"ok": p_ok, "volumes": pdf_res}
        if not p_ok:
            all_ok = False

    report["ok"] = all_ok
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        for name, detail in report["checks"].items():
            badge = "PASS" if detail["ok"] else "FAIL"
            print(f"[{badge}] {name}")
            if name == "audit_flags":
                print(f"       nodes={detail['nodes']} | open_flags={detail['open_flags']}")
            elif name == "unittest_harness":
                for ln in detail["summary"].splitlines():
                    print(f"       {ln}")
            elif name == "pdf_checksums":
                for r in detail["volumes"]:
                    print(f"       Vol {r['volume']}: {r['detail']}")
        print(f"\nOVERALL VERIFY: {'PASS' if all_ok else 'FAIL'}")
    return 0 if all_ok else 1


def cmd_build(args: argparse.Namespace) -> int:
    vols = ["1", "2", "parables", "3"] if args.vol == "all" else [args.vol]
    py = _find_python_with_module("reportlab", prefer_venv=True)
    builders = {
        "1": [py, str(WORKSPACE_ROOT / "scripts" / "build_whitepaper_pdf.py")],
        "2": [py, str(WORKSPACE_ROOT / "scripts" / "build_history_volume_pdf.py")],
        "parables": [py, str(WORKSPACE_ROOT / "scripts" / "build_failures_parables_pdf.py")],
        "3": [py, str(WORKSPACE_ROOT / "scripts" / "build_dialogue_pdf.py"), "--resume"],
    }
    for v in vols:
        print(f"=== Building Volume {v} ({builders[v][1]}) ===")
        proc = subprocess.run(builders[v], cwd=str(WORKSPACE_ROOT), check=False)
        if proc.returncode != 0:
            return proc.returncode
        chk = verify_pdf_checksums([v])[0]
        print(f"Checksum Vol {v}: {chk['detail']}")
        if not chk["ok"]:
            return 1
    return 0


def cmd_queue(args: argparse.Namespace) -> int:
    action = args.queue_action or "list"
    if action == "list":
        conn = _open_ro(args.db)
        try:
            rows = list_handoffs(conn, status=args.status, limit=args.limit)
        finally:
            conn.close()
        if args.json:
            print(json.dumps({"count": len(rows), "tasks": rows}, indent=2, ensure_ascii=False))
            return 0
        if not rows:
            print("handoff_queue is empty.")
            return 0
        for r in rows:
            print(
                f"#{r['task_id']:3d} [{r['status']:14s}] {r['title']} "
                f"(exit={r['exit_code']} | updated={r['updated_at']})"
            )
            if r["summary"]:
                print(f"      summary: {r['summary'][:120]}")
        return 0

    conn = get_connection(args.db)
    try:
        if action == "enqueue":
            row = enqueue_handoff(
                conn,
                title=args.title,
                spec=args.spec,
                constraints=args.constraints or "",
                status=args.status or "PENDING",
            )
            print(json.dumps(row, indent=2, ensure_ascii=False))
            return 0

        if action == "approve":
            row = update_handoff_status(conn, args.task_id, "APPROVED", summary=args.summary)
            print(json.dumps(row, indent=2, ensure_ascii=False))
            return 0

        if action == "update":
            row = update_handoff_status(
                conn,
                args.task_id,
                args.status,
                exit_code=args.exit_code,
                sha256_diff=args.sha256_diff,
                summary=args.summary,
            )
            print(json.dumps(row, indent=2, ensure_ascii=False))
            return 0

        if action == "run":
            rows = list_handoffs(conn, limit=500)
            target = next((r for r in rows if int(r["task_id"]) == int(args.task_id)), None)
            if target is None:
                print(f"Error: handoff task #{args.task_id} not found", file=sys.stderr)
                return 1
            if target["status"] not in ("APPROVED", "PENDING") and not args.force:
                print(
                    f"Error: task #{args.task_id} has status={target['status']}; pass --force or approve first.",
                    file=sys.stderr,
                )
                return 1
            if target["status"] == "PENDING" and not args.force:
                print(
                    f"Task #{args.task_id} is PENDING. Approve with `corpus queue approve {args.task_id}` or pass --force.",
                    file=sys.stderr,
                )
                return 1

            if args.dry_run or not args.cmd:
                packet = {
                    "task_id": target["task_id"],
                    "title": target["title"],
                    "status": target["status"],
                    "spec": target["spec"],
                    "constraints": target["constraints"],
                    "note": "Dry-run / spec handoff preview (supply --cmd to execute and record receipt).",
                }
                print(json.dumps(packet, indent=2, ensure_ascii=False))
                return 0

            update_handoff_status(conn, args.task_id, "RUNNING")
            proc = subprocess.run(
                args.cmd,
                shell=True,
                cwd=str(WORKSPACE_ROOT),
                capture_output=True,
                text=True,
                check=False,
            )
            combined = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
            receipt_sha = hashlib.sha256(combined.encode("utf-8")).hexdigest()
            final_status = "COMPLETED" if proc.returncode == 0 else "FAILED"
            summary_txt = args.summary or (combined.strip().splitlines()[-1][:240] if combined.strip() else f"exit={proc.returncode}")
            updated = update_handoff_status(
                conn,
                args.task_id,
                final_status,
                exit_code=proc.returncode,
                sha256_diff=receipt_sha,
                summary=summary_txt,
            )
            print(json.dumps(updated, indent=2, ensure_ascii=False))
            return proc.returncode

        raise ValueError(f"Unknown queue action: {action}")
    finally:
        conn.close()


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="corpus", description="Unified Corpus CLI (status, sync, verify, build, queue)")
    p.add_argument("--db", type=Path, default=DEFAULT_DB_PATH, help="Path to SQLite corpus.db")
    sub = p.add_subparsers(dest="command", required=True)

    p_st = sub.add_parser("status", help="Show read-only DB counts, open flags, digest watermark & handoff queue")
    p_st.add_argument("--json", action="store_true")
    p_st.set_defaults(func=cmd_status)

    p_sy = sub.add_parser("sync", help="Run closed-loop delta sync or Stage 0 ingestion")
    p_sy.add_argument("--mode", choices=["delta", "stage0"], default="delta")
    p_sy.add_argument("--input", type=Path, default=None, help="Input path for stage0 mode")
    p_sy.add_argument("--build-physics-slice", action="store_true")
    p_sy.add_argument("--force", action="store_true")
    p_sy.add_argument("--skip-scrape", action="store_true")
    p_sy.add_argument("--dry-run", action="store_true")
    p_sy.set_defaults(func=cmd_sync)

    p_vf = sub.add_parser("verify", help="Run PRAGMA integrity/FK checks, test_pilot_harness, and 3-PDF SHA-256 checks")
    p_vf.add_argument("--skip-tests", action="store_true")
    p_vf.add_argument("--skip-pdfs", action="store_true")
    p_vf.add_argument("--json", action="store_true")
    p_vf.set_defaults(func=cmd_verify)

    p_bd = sub.add_parser("build", help="Rebuild Volume 1, 2, 3, parables, or all PDFs + verify .sha256")
    p_bd.add_argument("--vol", choices=["1", "2", "3", "parables", "all"], required=True)
    p_bd.set_defaults(func=cmd_build)

    p_q = sub.add_parser("queue", help="Manage structured PR-style handoff_queue entries")
    qsub = p_q.add_subparsers(dest="queue_action")

    q_list = qsub.add_parser("list", help="List handoff_queue entries (read-only)")
    q_list.add_argument("--status", choices=list(VALID_HANDOFF_STATUSES), default=None)
    q_list.add_argument("--limit", type=int, default=50)
    q_list.add_argument("--json", action="store_true")

    q_enq = qsub.add_parser("enqueue", help="Add a structured handoff task")
    q_enq.add_argument("--title", required=True)
    q_enq.add_argument("--spec", required=True)
    q_enq.add_argument("--constraints", default="")
    q_enq.add_argument("--status", choices=list(VALID_HANDOFF_STATUSES), default="PENDING")

    q_app = qsub.add_parser("approve", help="Approve a handoff task")
    q_app.add_argument("task_id", type=int)
    q_app.add_argument("--summary", default=None)

    q_upd = qsub.add_parser("update", help="Update a handoff task status/receipt")
    q_upd.add_argument("task_id", type=int)
    q_upd.add_argument("--status", choices=list(VALID_HANDOFF_STATUSES), required=True)
    q_upd.add_argument("--exit-code", type=int, default=None)
    q_upd.add_argument("--sha256-diff", default=None)
    q_upd.add_argument("--summary", default=None)

    q_run = qsub.add_parser("run", help="Preview or execute an approved handoff task")
    q_run.add_argument("task_id", type=int)
    q_run.add_argument("--cmd", default=None, help="Optional shell command to execute and hash into sha256_diff")
    q_run.add_argument("--summary", default=None)
    q_run.add_argument("--dry-run", action="store_true")
    q_run.add_argument("--force", action="store_true")

    p_q.add_argument("--status", choices=list(VALID_HANDOFF_STATUSES), default=None)
    p_q.add_argument("--limit", type=int, default=50)
    p_q.add_argument("--json", action="store_true")
    p_q.set_defaults(func=cmd_queue)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
