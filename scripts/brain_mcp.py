#!/usr/bin/env python3
"""Unified JSON-RPC 2.0 stdio MCP bus (`brain_mcp`) for Levi / Corpus.

Exposes compact, truth-gated access over `data/corpus.db`, read-only
`archive.db` (?mode=ro), and `chapters/core_digest.md`.
All epistemic/archive queries open strictly read-only (?mode=ro); only explicit
`handoff_queue` write actions (`enqueue` / `update` / `approve`) write to the
`handoff_queue` coordination table in `data/corpus.db`.

Tools:
  - corpus_status(): Live DB counts, tiers, open audit flags, handoff counts, watermarks, archive status
  - get_packet(query, max_tokens=2200, domain=None): Bounded <= 2200-token truth-gated hybrid packet
  - corpus_query(query, max_tokens=2200, domain=None): Backward-compatible alias for get_packet
  - corpus_node(node_id): Exact node + FALSIFIED/PIVOTED_TO edges + source chunks (?mode=ro)
  - query_nodes(query=None, tier=None, domain=None, limit=20): Filter/search epistemic nodes (?mode=ro)
  - check_flags(include_resolved=False, flag_type=None, limit=50): Inspect node_audit_flags (?mode=ro)
  - handoff_queue(action="list"|"enqueue"|"update"|"approve", ...): Structured PR-style task bus
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from arachne_bridge import (
    filter_query_text,
    open_archive_ro,
    parse_archive_ref,
    resolve_archive_db,
    retrieve_hybrid_and_gated,
)
from compile_digest import extract_core_anchor_block, resolve_digest_targets
from db_utils import (
    DEFAULT_DB_PATH,
    VALID_HANDOFF_STATUSES,
    VALID_TIERS,
    classify_text_to_section_key,
    enqueue_handoff,
    get_connection,
    list_handoffs,
    update_handoff_status,
)

DB_PATH = Path(os.environ.get("CORPUS_DB_PATH", str(DEFAULT_DB_PATH))).expanduser()
_ENV_ARCHIVE = os.environ.get("ARCHIVE_DB_PATH", "").strip()
ARCHIVE_DB_PATH = (
    Path(_ENV_ARCHIVE).expanduser()
    if _ENV_ARCHIVE
    else (resolve_archive_db() or Path.home() / "Desktop" / "GeminiAccountArchive" / "archive.db")
)

TOOLS: list[dict[str, Any]] = [
    {
        "name": "corpus_status",
        "description": "Read-only summary of corpus.db counts, epistemic tiers, open audit flags, pending handoff_queue count, digest_state watermarks, core_digest.md bytes, chapter_slices queues, and archive.db (?mode=ro) status.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "slice_name": {"type": "string", "default": "bio_neuro_psych"},
            },
        },
    },
    {
        "name": "get_packet",
        "description": "Assemble a bounded <= 2200-token truth-gated working-memory packet (FTS5 + TF-IDF RRF + concept_bridges + archive.db?mode=ro parent DAG + NEGATIVE CONSTRAINTS + core_digest anchor).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "max_tokens": {"type": "integer", "default": 2200, "maximum": 2200},
                "domain": {"type": "string"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "corpus_query",
        "description": "Truth-gated hybrid retrieval (FTS5 + TF-IDF RRF + concept_bridges + parent_turn_id DAG backtracking) capped strictly at <= 2200 tokens with node_id/chunk_id/turn_id provenance and NEGATIVE CONSTRAINTS.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "max_tokens": {"type": "integer", "default": 2200, "maximum": 2200},
                "domain": {"type": "string"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "corpus_node",
        "description": "Inspect one exact epistemic node_id read-only (?mode=ro), including summary, dsl_expr, epistemic_tier, verifications, FALSIFIED/PIVOTED_TO/supports edges, provenance chunks, and research_branches.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "node_id": {"type": "integer"},
            },
            "required": ["node_id"],
        },
    },
    {
        "name": "query_nodes",
        "description": "Read-only (?mode=ro) structured search and filtering over epistemic nodes by keyword, epistemic_tier, and/or domain.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "tier": {"type": "string", "enum": list(VALID_TIERS)},
                "domain": {"type": "string"},
                "limit": {"type": "integer", "default": 20, "maximum": 100},
            },
        },
    },
    {
        "name": "check_flags",
        "description": "Read-only (?mode=ro) audit of node_audit_flags reporting open/resolved totals, breakdown by flag_type, and matching flagged nodes.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "include_resolved": {"type": "boolean", "default": False},
                "flag_type": {"type": "string"},
                "limit": {"type": "integer", "default": 50, "maximum": 200},
            },
        },
    },
    {
        "name": "handoff_queue",
        "description": "Structured PR-style task coordination bus in corpus.db (list read-only, enqueue new task spec, approve, or update status/exit_code/sha256_diff/summary).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["list", "enqueue", "approve", "update"], "default": "list"},
                "task_id": {"type": "integer"},
                "title": {"type": "string"},
                "spec": {"type": "string"},
                "constraints": {"type": "string", "default": ""},
                "status": {"type": "string", "enum": list(VALID_HANDOFF_STATUSES)},
                "exit_code": {"type": "integer"},
                "sha256_diff": {"type": "string"},
                "summary": {"type": "string"},
                "limit": {"type": "integer", "default": 50, "maximum": 200},
            },
        },
    },
]


def _open_corpus_ro(db_path: Path) -> sqlite3.Connection:
    resolved = db_path.expanduser().resolve()
    if not resolved.exists():
        raise FileNotFoundError(f"Corpus DB not found: {resolved}")
    conn = sqlite3.connect(f"file:{resolved}?mode=ro", uri=True, timeout=10.0)
    conn.row_factory = sqlite3.Row
    return conn


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    return bool(
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type IN ('table', 'view') AND name = ?",
            (name,),
        ).fetchone()
    )


def _archive_info(archive_path: Path | None) -> dict[str, Any]:
    arch_conn, err = open_archive_ro(archive_path)
    if arch_conn is None:
        return {"available": False, "path": str(archive_path or ""), "reason": err or "unavailable"}
    try:
        convs = int(arch_conn.execute("SELECT COUNT(*) FROM conversations").fetchone()[0])
        turns = int(arch_conn.execute("SELECT COUNT(*) FROM turns").fetchone()[0])
        ouro = arch_conn.execute(
            "SELECT COUNT(*), COALESCE(MAX(id), 0) FROM turns WHERE chat_id = 'levi_recursive_memory'"
        ).fetchone()
        latest = arch_conn.execute(
            "SELECT id, chat_id, turn_index, turn_id FROM turns WHERE turn_id IS NOT NULL ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return {
            "available": True,
            "mode": "ro",
            "path": str(resolve_archive_db(archive_path) or archive_path),
            "conversations": convs,
            "turns": turns,
            "ouroboros_turns": int(ouro[0]),
            "max_ouroboros_turn_id": int(ouro[1]),
            "latest_turn": dict(latest) if latest else None,
        }
    except sqlite3.Error as exc:
        return {"available": False, "path": str(archive_path or ""), "reason": str(exc)}
    finally:
        arch_conn.close()


def corpus_status(
    *,
    db_path: Path = DB_PATH,
    archive_path: Path = ARCHIVE_DB_PATH,
    slice_name: str = "bio_neuro_psych",
) -> dict[str, Any]:
    conn = _open_corpus_ro(db_path)
    core_path, _ = resolve_digest_targets(db_path)
    try:
        tiers = {
            r["epistemic_tier"]: int(r["cnt"])
            for r in conn.execute("SELECT epistemic_tier, COUNT(*) AS cnt FROM nodes GROUP BY epistemic_tier").fetchall()
        }
        slices: dict[str, dict[str, int]] = {}
        for r in conn.execute(
            "SELECT slice_name, status, COUNT(*) AS cnt FROM chapter_slices GROUP BY slice_name, status ORDER BY slice_name, status"
        ).fetchall():
            slices.setdefault(r["slice_name"], {})[r["status"]] = int(r["cnt"])

        watermarks: list[dict[str, Any]] = []
        if _table_exists(conn, "digest_state"):
            watermarks = [
                dict(r)
                for r in conn.execute(
                    "SELECT section_key, last_compiled_node_id, last_compiled_turn_id, "
                    "substr(section_sha256, 1, 12) AS sha_prefix, updated_at "
                    "FROM digest_state ORDER BY section_key"
                ).fetchall()
            ]
        open_audit_flags = (
            int(conn.execute("SELECT COUNT(*) FROM node_audit_flags WHERE resolved = 0").fetchone()[0])
            if _table_exists(conn, "node_audit_flags")
            else 0
        )
        handoff_counts: dict[str, int] = {}
        if _table_exists(conn, "handoff_queue"):
            handoff_counts = {
                r["status"]: int(r["cnt"])
                for r in conn.execute(
                    "SELECT status, COUNT(*) AS cnt FROM handoff_queue GROUP BY status ORDER BY status"
                ).fetchall()
            }
        core_bytes = len(core_path.read_bytes()) if core_path.exists() else 0
        return {
            "corpus_db": str(db_path.resolve()),
            "mode": "ro",
            "nodes_total": sum(tiers.values()),
            "node_tiers": tiers,
            "chunks": int(conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]),
            "edges": int(conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0]),
            "concept_bridges": int(conn.execute("SELECT COUNT(*) FROM concept_bridges").fetchone()[0]),
            "open_audit_flags": open_audit_flags,
            "handoff_queue": {
                "total": sum(handoff_counts.values()),
                "pending": handoff_counts.get("PENDING", 0) + handoff_counts.get("NEEDS_APPROVAL", 0),
                "by_status": handoff_counts,
            },
            "ingested_artifacts": (
                int(conn.execute("SELECT COUNT(*) FROM ingested_artifacts").fetchone()[0])
                if _table_exists(conn, "ingested_artifacts")
                else 0
            ),
            "target_slice": slice_name,
            "chapter_slices": slices,
            "core_digest": {
                "path": str(core_path),
                "bytes": core_bytes,
                "kb": round(core_bytes / 1024.0, 2),
                "in_15_30kb_window": 15 * 1024 <= core_bytes <= 30 * 1024,
            },
            "digest_state_count": len(watermarks),
            "digest_state": watermarks,
            "archive_db": _archive_info(archive_path),
        }
    finally:
        conn.close()


def corpus_query(
    query: str,
    *,
    max_tokens: int = 2200,
    domain: str | None = None,
    db_path: Path = DB_PATH,
    archive_path: Path = ARCHIVE_DB_PATH,
) -> dict[str, Any]:
    budget = max(200, min(2200, int(max_tokens or 2200)))
    cleaned = filter_query_text(query) or query.strip()
    if not cleaned:
        raise ValueError("query must not be empty")
    conn = _open_corpus_ro(db_path)
    arch_conn, arch_err = open_archive_ro(archive_path)
    core_path, _ = resolve_digest_targets(db_path)
    try:
        packet = retrieve_hybrid_and_gated(
            conn,
            cleaned,
            domain=domain,
            archive_conn=arch_conn,
            top_k_chunks=8,
            top_k_nodes=10,
            token_budget=budget,
            expand_bridges=True,
            backtrack_parents=True,
        )
        core_text = core_path.read_text(encoding="utf-8") if core_path.exists() else ""
        return {
            "raw_query": query,
            "cleaned_query": cleaned,
            "target_section_key": classify_text_to_section_key(cleaned),
            "archive_db_status": "connected" if arch_err is None else arch_err,
            "token_budget": budget,
            "estimated_tokens": packet["estimated_tokens"],
            "core_anchor_excerpt": "\n".join(extract_core_anchor_block(core_text).splitlines()[:18]),
            "citations": {
                "verified_node_ids": [v["node_id"] for v in packet.get("verified_invariants", [])],
                "provisional_node_ids": [p["node_id"] for p in packet.get("provisional_claims", [])],
                "falsified_pivots": [
                    {
                        "falsified_node_id": f["falsified_node_id"],
                        "pivoted_to_node_id": f["pivoted_to_node_id"],
                    }
                    for f in packet.get("falsified_constraints", [])
                ],
                "chunks_and_turns": [
                    {
                        "source": s.get("source"),
                        "chunk_id": s.get("chunk_id"),
                        "chat_id": s.get("chat_id"),
                        "turn_index": s.get("turn_index"),
                        "turn_id": s.get("turn_id"),
                        "parent_turn_id": s.get("parent_turn_id"),
                        "sha256": s.get("sha256"),
                    }
                    for s in list(packet.get("dynamic_slices", [])) + list(packet.get("parent_dag_backtrack", []))
                ],
            },
            "rendered_markdown": packet["rendered_markdown"],
        }
    finally:
        if arch_conn is not None:
            arch_conn.close()
        conn.close()


def corpus_node(node_id: int, *, db_path: Path = DB_PATH) -> dict[str, Any]:
    nid = int(node_id)
    conn = _open_corpus_ro(db_path)
    try:
        row = conn.execute("SELECT * FROM nodes WHERE node_id = ?", (nid,)).fetchone()
        if row is None:
            raise KeyError(f"Node #{nid} not found")
        provenance = []
        for p in conn.execute(
            """
            SELECT np.chunk_id, np.quote_span, c.source_type, c.source_ref, c.sha256,
                   substr(c.content, 1, 260) AS snippet
            FROM node_provenance np
            JOIN chunks c ON c.chunk_id = np.chunk_id
            WHERE np.node_id = ?
            ORDER BY np.chunk_id
            """,
            (nid,),
        ).fetchall():
            d = dict(p)
            chat_id, turn_index = parse_archive_ref(str(d["source_ref"]))
            m_tid = re.search(r"turn_id=([A-Za-z0-9_:-]+)", str(d["source_ref"]))
            d["chat_id"] = chat_id
            d["turn_index"] = turn_index
            d["turn_id"] = m_tid.group(1) if m_tid else None
            provenance.append(d)

        verifs = [
            dict(v)
            for v in conn.execute(
                "SELECT * FROM node_verifications WHERE node_id = ? ORDER BY verification_id",
                (nid,),
            ).fetchall()
        ]
        outgoing = [
            dict(e)
            for e in conn.execute(
                """
                SELECT e.edge_id, e.relation_type, e.to_node AS peer_node_id,
                       n.epistemic_tier AS peer_tier, n.summary AS peer_summary, e.external_ref, e.notes
                FROM edges e JOIN nodes n ON n.node_id = e.to_node
                WHERE e.from_node = ? ORDER BY e.edge_id
                """,
                (nid,),
            ).fetchall()
        ]
        incoming = [
            dict(e)
            for e in conn.execute(
                """
                SELECT e.edge_id, e.relation_type, e.from_node AS peer_node_id,
                       n.epistemic_tier AS peer_tier, n.summary AS peer_summary, e.external_ref, e.notes
                FROM edges e JOIN nodes n ON n.node_id = e.from_node
                WHERE e.to_node = ? ORDER BY e.edge_id
                """,
                (nid,),
            ).fetchall()
        ]
        branches = [
            dict(b)
            for b in conn.execute(
                "SELECT * FROM research_branches WHERE root_node_id = ? ORDER BY branch_id",
                (nid,),
            ).fetchall()
        ]
        return {
            "mode": "ro",
            "node": dict(row),
            "provenance": provenance,
            "verifications": verifs,
            "outgoing_edges": outgoing,
            "incoming_edges": incoming,
            "research_branches": branches,
        }
    finally:
        conn.close()


def get_packet(
    query: str,
    *,
    max_tokens: int = 2200,
    domain: str | None = None,
    db_path: Path = DB_PATH,
    archive_path: Path = ARCHIVE_DB_PATH,
) -> dict[str, Any]:
    """Assemble a bounded <= 2200-token truth-gated packet (canonical bus entrypoint)."""
    return corpus_query(
        query=query,
        max_tokens=max_tokens,
        domain=domain,
        db_path=db_path,
        archive_path=archive_path,
    )


def query_nodes(
    *,
    query: str | None = None,
    tier: str | None = None,
    domain: str | None = None,
    limit: int = 20,
    db_path: Path = DB_PATH,
) -> dict[str, Any]:
    """Read-only (?mode=ro) structured filter/search across epistemic nodes."""
    lim = max(1, min(100, int(limit or 20)))
    clauses: list[str] = []
    params: list[Any] = []
    if tier:
        if tier not in VALID_TIERS:
            raise ValueError(f"Invalid epistemic_tier filter: {tier}")
        clauses.append("n.epistemic_tier = ?")
        params.append(tier)
    if domain:
        clauses.append("lower(n.domain) = lower(?)")
        params.append(domain.strip())
    if query and query.strip():
        like = f"%{query.strip()}%"
        clauses.append("(lower(n.summary) LIKE lower(?) OR lower(COALESCE(n.dsl_expr, '')) LIKE lower(?))")
        params.extend([like, like])

    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    conn = _open_corpus_ro(db_path)
    try:
        total_matching = int(
            conn.execute(f"SELECT COUNT(*) FROM nodes n {where}", params).fetchone()[0]
        )
        rows = conn.execute(
            f"""
            SELECT n.node_id, n.domain, n.epistemic_tier, n.summary, n.dsl_expr, n.created_at,
                   (SELECT COUNT(*) FROM node_verifications nv WHERE nv.node_id = n.node_id) AS verifications_count,
                   (SELECT COUNT(*) FROM edges e WHERE e.from_node = n.node_id OR e.to_node = n.node_id) AS edges_count
            FROM nodes n
            {where}
            ORDER BY n.node_id DESC
            LIMIT ?
            """,
            params + [lim],
        ).fetchall()
        return {
            "mode": "ro",
            "filters": {"query": query, "tier": tier, "domain": domain, "limit": lim},
            "total_matching": total_matching,
            "returned": len(rows),
            "nodes": [dict(r) for r in rows],
        }
    finally:
        conn.close()


def check_flags(
    *,
    include_resolved: bool = False,
    flag_type: str | None = None,
    limit: int = 50,
    db_path: Path = DB_PATH,
) -> dict[str, Any]:
    """Read-only (?mode=ro) inspection of node_audit_flags."""
    lim = max(1, min(200, int(limit or 50)))
    conn = _open_corpus_ro(db_path)
    try:
        if not _table_exists(conn, "node_audit_flags"):
            return {
                "mode": "ro",
                "table_present": False,
                "open_flags_total": 0,
                "resolved_flags_total": 0,
                "by_flag_type": {},
                "flags": [],
            }
        open_tot = int(conn.execute("SELECT COUNT(*) FROM node_audit_flags WHERE resolved = 0").fetchone()[0])
        res_tot = int(conn.execute("SELECT COUNT(*) FROM node_audit_flags WHERE resolved = 1").fetchone()[0])
        by_type: dict[str, dict[str, int]] = {}
        for r in conn.execute(
            "SELECT flag_type, resolved, COUNT(*) AS cnt FROM node_audit_flags GROUP BY flag_type, resolved"
        ).fetchall():
            bucket = by_type.setdefault(r["flag_type"], {"open": 0, "resolved": 0})
            bucket["resolved" if r["resolved"] else "open"] = int(r["cnt"])

        clauses: list[str] = []
        params: list[Any] = []
        if not include_resolved:
            clauses.append("f.resolved = 0")
        if flag_type:
            clauses.append("f.flag_type = ?")
            params.append(flag_type.strip())
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        rows = conn.execute(
            f"""
            SELECT f.flag_id, f.node_id, f.flag_type, f.prior_tier, f.reason, f.resolved, f.created_at,
                   n.epistemic_tier AS current_tier, substr(n.summary, 1, 200) AS node_summary
            FROM node_audit_flags f
            LEFT JOIN nodes n ON n.node_id = f.node_id
            {where}
            ORDER BY f.resolved ASC, f.flag_id ASC
            LIMIT ?
            """,
            params + [lim],
        ).fetchall()
        return {
            "mode": "ro",
            "table_present": True,
            "open_flags_total": open_tot,
            "resolved_flags_total": res_tot,
            "by_flag_type": by_type,
            "returned": len(rows),
            "flags": [dict(r) for r in rows],
        }
    finally:
        conn.close()


def handoff_queue_tool(
    *,
    action: str = "list",
    task_id: int | None = None,
    title: str | None = None,
    spec: str | None = None,
    constraints: str = "",
    status: str | None = None,
    exit_code: int | None = None,
    sha256_diff: str | None = None,
    summary: str | None = None,
    limit: int = 50,
    db_path: Path = DB_PATH,
) -> dict[str, Any]:
    """Structured PR-style task bus over handoff_queue (read-only for list; write for enqueue/approve/update)."""
    act = (action or "list").strip().lower()
    if act == "list":
        conn = _open_corpus_ro(db_path)
        try:
            items = list_handoffs(conn, status=status, limit=limit)
            return {"mode": "ro", "action": "list", "count": len(items), "tasks": items}
        finally:
            conn.close()

    conn = get_connection(db_path)
    try:
        if act == "enqueue":
            row = enqueue_handoff(
                conn,
                title=str(title or ""),
                spec=str(spec or ""),
                constraints=str(constraints or ""),
                status=str(status or "PENDING"),
            )
            return {"action": "enqueue", "task": row}
        if act == "approve":
            if task_id is None:
                raise ValueError("task_id is required for action='approve'")
            row = update_handoff_status(
                conn,
                int(task_id),
                "APPROVED",
                exit_code=exit_code,
                sha256_diff=sha256_diff,
                summary=summary,
            )
            return {"action": "approve", "task": row}
        if act == "update":
            if task_id is None:
                raise ValueError("task_id is required for action='update'")
            if not status:
                raise ValueError("status is required for action='update'")
            row = update_handoff_status(
                conn,
                int(task_id),
                str(status),
                exit_code=exit_code,
                sha256_diff=sha256_diff,
                summary=summary,
            )
            return {"action": "update", "task": row}
        raise ValueError(f"Unsupported handoff_queue action: {action}")
    finally:
        conn.close()


def call_tool(name: str, args: dict[str, Any]) -> Any:
    if name == "corpus_status":
        return corpus_status(slice_name=str(args.get("slice_name") or "bio_neuro_psych"))
    if name in ("get_packet", "corpus_query"):
        return get_packet(
            query=str(args["query"]),
            max_tokens=int(args.get("max_tokens", 2200)),
            domain=str(args["domain"]) if args.get("domain") else None,
        )
    if name == "corpus_node":
        return corpus_node(node_id=int(args["node_id"]))
    if name == "query_nodes":
        return query_nodes(
            query=str(args["query"]) if args.get("query") else None,
            tier=str(args["tier"]) if args.get("tier") else None,
            domain=str(args["domain"]) if args.get("domain") else None,
            limit=int(args.get("limit", 20)),
        )
    if name == "check_flags":
        return check_flags(
            include_resolved=bool(args.get("include_resolved", False)),
            flag_type=str(args["flag_type"]) if args.get("flag_type") else None,
            limit=int(args.get("limit", 50)),
        )
    if name == "handoff_queue":
        return handoff_queue_tool(
            action=str(args.get("action") or "list"),
            task_id=int(args["task_id"]) if args.get("task_id") is not None else None,
            title=str(args["title"]) if args.get("title") is not None else None,
            spec=str(args["spec"]) if args.get("spec") is not None else None,
            constraints=str(args.get("constraints") or ""),
            status=str(args["status"]) if args.get("status") else None,
            exit_code=int(args["exit_code"]) if args.get("exit_code") is not None else None,
            sha256_diff=str(args["sha256_diff"]) if args.get("sha256_diff") is not None else None,
            summary=str(args["summary"]) if args.get("summary") is not None else None,
            limit=int(args.get("limit", 50)),
        )
    raise ValueError(f"Unknown tool: {name}")


def handle_request(req: dict[str, Any]) -> dict[str, Any] | None:
    method = req.get("method")
    req_id = req.get("id")
    params = req.get("params") or {}

    if method == "notifications/initialized" or req_id is None:
        return None
    if method == "initialize":
        proto = params.get("protocolVersion") or "2024-11-05"
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": proto,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "brain_mcp", "version": "0.2.0"},
            },
        }
    if method == "ping":
        return {"jsonrpc": "2.0", "id": req_id, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": TOOLS}}
    if method == "tools/call":
        tname = str(params.get("name") or "")
        targs = params.get("arguments") or {}
        try:
            data = call_tool(tname, targs)
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [{"type": "text", "text": json.dumps(data, indent=2, ensure_ascii=False)}],
                    "isError": False,
                },
            }
        except Exception as exc:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [{"type": "text", "text": f"Error in {tname}: {exc}"}],
                    "isError": True,
                },
            }
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": f"Method not found: {method}"}}


def main() -> None:
    for line in sys.stdin:
        stripped = line.strip()
        if not stripped:
            continue
        try:
            req = json.loads(stripped)
        except json.JSONDecodeError as exc:
            sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": str(exc)}}) + "\n")
            sys.stdout.flush()
            continue
        resp = handle_request(req)
        if resp is not None:
            sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
