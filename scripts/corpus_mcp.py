#!/usr/bin/env python3
"""Zero-dependency MCP stdio server for the Epistemic Corpus & Physics Pilot."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from brain_mcp import (
    ARCHIVE_DB_PATH as BRAIN_ARCHIVE_DB_PATH,
    TOOLS as BRAIN_BUS_TOOLS,
    check_flags as brain_check_flags,
    corpus_node as brain_corpus_node,
    corpus_status as brain_corpus_status,
    get_packet as brain_get_packet,
    handoff_queue_tool as brain_handoff_queue,
    query_nodes as brain_query_nodes,
)
from compile_digest import (
    hydrate_pre_tick,
    on_falsifier_commit,
    resolve_digest_targets,
    sync_ouroboros_deltas,
)
from db_utils import (
    DEFAULT_DB_PATH,
    VALID_RELATIONS,
    VALID_SCOPES,
    VALID_TIERS,
    VALID_VERIFIERS,
    attach_node_provenance,
    build_thematic_outline,
    create_node_with_provenance,
    ensure_digest_state_table,
    get_chunk_context,
    get_connection,
    init_db,
    run_physics_check,
    search_corpus_global,
    verify_and_link,
    verify_node,
)

DB_PATH = Path(os.environ.get("CORPUS_DB_PATH", str(DEFAULT_DB_PATH)))


TOOLS: list[dict[str, Any]] = [
    {
        "name": "get_pilot_status",
        "description": "Summarize corpus size, scoped slice progress, nodes by epistemic tier, verifications, edges, and active/halted branches.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "slice_name": {"type": "string", "default": "physics_pilot"},
            },
        },
    },
    {
        "name": "get_slice_chunks",
        "description": "Read chunks belonging to the scoped writing slice (e.g. physics_pilot).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "slice_name": {"type": "string", "default": "physics_pilot"},
                "status": {"type": "string", "enum": ["PENDING", "PROCESSED", "SKIPPED", "ALL"], "default": "PENDING"},
                "limit": {"type": "integer", "default": 20},
                "offset": {"type": "integer", "default": 0},
            },
        },
    },
    {
        "name": "mark_slice_chunk",
        "description": "Update a slice chunk's status to PROCESSED or SKIPPED (with optional skip_reason such as 'debug_churn', 'boilerplate', or 'duplicate_export').",
        "inputSchema": {
            "type": "object",
            "properties": {
                "slice_name": {"type": "string", "default": "physics_pilot"},
                "chunk_id": {"type": "integer"},
                "status": {"type": "string", "enum": ["PENDING", "PROCESSED", "SKIPPED"]},
                "skip_reason": {"type": "string"},
            },
            "required": ["chunk_id", "status"],
        },
    },
    {
        "name": "search_corpus_global",
        "description": "Search the ENTIRE global chunks_fts index (including cross-domain concept_bridges expansion) to allow cross-domain leaps while writing a scoped chapter.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer", "default": 12},
                "expand_bridges": {"type": "boolean", "default": True},
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_chunk_context",
        "description": "Fetch surrounding chunks (+/- window) from the same source_ref around a chunk_id.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "chunk_id": {"type": "integer"},
                "window": {"type": "integer", "default": 2},
            },
            "required": ["chunk_id"],
        },
    },
    {
        "name": "add_concept_bridge",
        "description": "Record a cross-domain structural alias in concept_bridges for future zero-cost query expansion.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "term": {"type": "string"},
                "alias": {"type": "string"},
                "structural_pattern": {"type": "string", "default": ""},
            },
            "required": ["term", "alias"],
        },
    },
    {
        "name": "create_node",
        "description": "Create an epistemic node grounded in exact chunk_ids (provenance lock enforced).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "domain": {"type": "string"},
                "summary": {"type": "string"},
                "chunk_ids": {"type": "array", "items": {"type": "integer"}},
                "dsl_expr": {"type": "string"},
                "quote_spans": {"type": "array", "items": {"type": "string"}},
                "epistemic_tier": {"type": "string", "enum": ["RAW_CLAIM", "DSL_CONSISTENT"], "default": "RAW_CLAIM"},
            },
            "required": ["domain", "summary", "chunk_ids"],
        },
    },
    {
        "name": "attach_node_provenance",
        "description": "Canonical deduplication: attach additional chunk_ids and quote_spans to an existing canonical node_id instead of creating a duplicate node.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "node_id": {"type": "integer"},
                "chunk_ids": {"type": "array", "items": {"type": "integer"}},
                "quote_spans": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["node_id", "chunk_ids"],
        },
    },
    {
        "name": "create_research_branch",
        "description": "Open a tracked research branch with an anti-spin halting budget (default max_dry_hops=3).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "root_node_id": {"type": "integer"},
                "agent_role": {"type": "string", "enum": ["historian", "scientist", "falsifier", "synthesizer"]},
                "max_dry_hops": {"type": "integer", "default": 3},
            },
            "required": ["root_node_id", "agent_role"],
        },
    },
    {
        "name": "run_physics_check",
        "description": "Execute a Python simulation, dimensional check, or unit test; returns stdout/stderr and a pycheck:<sha256> external_ref on pass.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "python_code": {"type": "string"},
            },
            "required": ["python_code"],
        },
    },
    {
        "name": "verify_node",
        "description": "Record a single-node verification in node_verifications (no self-loops). Toy scripts can promote at most to SIM_CONSISTENT; EXTERNALLY_VERIFIED requires non-toy verification_scope and benchmark_ref.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "node_id": {"type": "integer"},
                "verifier_type": {"type": "string", "enum": list(VALID_VERIFIERS)},
                "verification_scope": {"type": "string", "enum": list(VALID_SCOPES)},
                "external_ref": {"type": "string"},
                "benchmark_ref": {"type": "string"},
                "passed": {"type": "boolean", "default": True},
                "branch_id": {"type": "integer"},
                "new_tier": {"type": "string", "enum": list(VALID_TIERS)},
                "notes": {"type": "string", "default": ""},
            },
            "required": ["node_id", "verifier_type", "verification_scope"],
        },
    },
    {
        "name": "verify_and_link",
        "description": "Falsifier gate for directed two-node edges (from_node_id != to_node_id; self-loops blocked). Toy scripts can promote at most to SIM_CONSISTENT; EXTERNALLY_VERIFIED requires non-toy verification_scope and benchmark_ref.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "from_node_id": {"type": "integer"},
                "to_node_id": {"type": "integer"},
                "relation_type": {"type": "string", "enum": list(VALID_RELATIONS)},
                "verifier_type": {"type": "string", "enum": list(VALID_VERIFIERS)},
                "verification_scope": {"type": "string", "enum": list(VALID_SCOPES), "default": "llm_only"},
                "external_ref": {"type": "string"},
                "benchmark_ref": {"type": "string"},
                "branch_id": {"type": "integer"},
                "promote_node_id": {"type": "integer"},
                "new_tier": {"type": "string", "enum": list(VALID_TIERS)},
                "notes": {"type": "string", "default": ""},
            },
            "required": ["from_node_id", "to_node_id", "relation_type", "verifier_type"],
        },
    },
    {
        "name": "get_epistemic_graph",
        "description": "Return nodes (with provenance chunk_ids and node_verifications), directed edges, and research branches for audit and textbook synthesis.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "domain": {"type": "string"},
            },
        },
    },
    {
        "name": "get_thematic_outline",
        "description": "Group all nodes, falsification-to-pivot chains, and edges by conceptual theme for Step 6 full-chapter textbook recompilation (prevents chronological batch-by-batch appending).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "domain": {"type": "string"},
            },
        },
    },
    {
        "name": "hydrate_tick_context",
        "description": "Stage 2+4 Arachne/Corpus hybrid retrieval: assemble tier-gated pre-tick working memory packet (core digest anchors, FTS5+semantic RRF slice with chat_id/turn_id/parent_turn_id/sha256, active branch max_dry_hops budgets, FALSIFIED->pivoted_to constraints).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "domain": {"type": "string", "default": "bio_neuro_psych"},
                "query": {"type": "string", "default": ""},
                "chunk_ids": {"type": "array", "items": {"type": "integer"}},
                "token_budget": {"type": "integer", "default": 2200},
            },
        },
    },
    {
        "name": "sync_digest_deltas",
        "description": "Stage 3 incremental digest compiler: recompile affected # KEYWORD: slices and core_digest.md from Falsifier commits and Ouroboros archive.db watermarks.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "node_ids": {"type": "array", "items": {"type": "integer"}},
            },
        },
    },
] + [
    t for t in BRAIN_BUS_TOOLS
    if t["name"] in ("corpus_status", "get_packet", "corpus_node", "query_nodes", "check_flags", "handoff_queue")
]


def call_tool(name: str, args: dict[str, Any]) -> dict[str, Any]:
    init_db(DB_PATH)
    # Consolidated local bus tools (shared with brain_mcp.py)
    if name == "corpus_status":
        return brain_corpus_status(
            db_path=DB_PATH,
            archive_path=BRAIN_ARCHIVE_DB_PATH,
            slice_name=str(args.get("slice_name") or "bio_neuro_psych"),
        )
    if name == "get_packet":
        return brain_get_packet(
            query=str(args["query"]),
            max_tokens=int(args.get("max_tokens", 2200)),
            domain=str(args["domain"]) if args.get("domain") else None,
            db_path=DB_PATH,
            archive_path=BRAIN_ARCHIVE_DB_PATH,
        )
    if name == "corpus_node":
        return brain_corpus_node(node_id=int(args["node_id"]), db_path=DB_PATH)
    if name == "query_nodes":
        return brain_query_nodes(
            query=str(args["query"]) if args.get("query") else None,
            tier=str(args["tier"]) if args.get("tier") else None,
            domain=str(args["domain"]) if args.get("domain") else None,
            limit=int(args.get("limit", 20)),
            db_path=DB_PATH,
        )
    if name == "check_flags":
        return brain_check_flags(
            include_resolved=bool(args.get("include_resolved", False)),
            flag_type=str(args["flag_type"]) if args.get("flag_type") else None,
            limit=int(args.get("limit", 50)),
            db_path=DB_PATH,
        )
    if name == "handoff_queue":
        return brain_handoff_queue(
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
            db_path=DB_PATH,
        )
    conn = get_connection(DB_PATH)
    try:
        if name == "get_pilot_status":
            slice_name = args.get("slice_name", "physics_pilot")
            total_chunks = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
            slice_counts = {
                r["status"]: r["cnt"]
                for r in conn.execute(
                    "SELECT status, COUNT(*) AS cnt FROM chapter_slices WHERE slice_name = ? GROUP BY status",
                    (slice_name,),
                ).fetchall()
            }
            skip_reasons = {
                (r["skip_reason"] or "unspecified"): r["cnt"]
                for r in conn.execute(
                    "SELECT skip_reason, COUNT(*) AS cnt FROM chapter_slices WHERE slice_name = ? AND status = 'SKIPPED' GROUP BY skip_reason",
                    (slice_name,),
                ).fetchall()
            }
            tier_counts = {
                r["epistemic_tier"]: r["cnt"]
                for r in conn.execute(
                    "SELECT epistemic_tier, COUNT(*) AS cnt FROM nodes GROUP BY epistemic_tier"
                ).fetchall()
            }
            verif_counts = {
                r["verification_scope"]: r["cnt"]
                for r in conn.execute(
                    "SELECT verification_scope, COUNT(*) AS cnt FROM node_verifications GROUP BY verification_scope"
                ).fetchall()
            }
            edge_counts = {
                r["relation_type"]: r["cnt"]
                for r in conn.execute(
                    "SELECT relation_type, COUNT(*) AS cnt FROM edges GROUP BY relation_type"
                ).fetchall()
            }
            branch_counts = {
                r["status"]: r["cnt"]
                for r in conn.execute(
                    "SELECT status, COUNT(*) AS cnt FROM research_branches GROUP BY status"
                ).fetchall()
            }
            bridges_count = conn.execute("SELECT COUNT(*) FROM concept_bridges").fetchone()[0]
            ensure_digest_state_table(conn)
            digest_sections = conn.execute("SELECT COUNT(*) FROM digest_state").fetchone()[0]
            return {
                "db_path": str(DB_PATH),
                "total_chunks": total_chunks,
                "slice": {"name": slice_name, "counts": slice_counts, "skipped_by_reason": skip_reasons},
                "nodes_by_tier": tier_counts,
                "verifications_by_scope": verif_counts,
                "edges_by_relation": edge_counts,
                "branches_by_status": branch_counts,
                "concept_bridges": bridges_count,
                "digest_state_sections": digest_sections,
            }

        if name == "get_slice_chunks":
            slice_name = args.get("slice_name", "physics_pilot")
            status = args.get("status", "PENDING")
            limit = int(args.get("limit", 20))
            offset = int(args.get("offset", 0))
            if status == "ALL":
                rows = conn.execute(
                    """
                    SELECT cs.status, cs.relevance, c.chunk_id, c.source_type, c.source_ref,
                           c.author, c.created_at, c.content
                    FROM chapter_slices cs
                    JOIN chunks c ON c.chunk_id = cs.chunk_id
                    WHERE cs.slice_name = ?
                    ORDER BY cs.relevance ASC, c.chunk_id ASC
                    LIMIT ? OFFSET ?
                    """,
                    (slice_name, limit, offset),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT cs.status, cs.relevance, c.chunk_id, c.source_type, c.source_ref,
                           c.author, c.created_at, c.content
                    FROM chapter_slices cs
                    JOIN chunks c ON c.chunk_id = cs.chunk_id
                    WHERE cs.slice_name = ? AND cs.status = ?
                    ORDER BY cs.relevance ASC, c.chunk_id ASC
                    LIMIT ? OFFSET ?
                    """,
                    (slice_name, status, limit, offset),
                ).fetchall()
            return {"slice_name": slice_name, "chunks": [dict(r) for r in rows]}

        if name == "mark_slice_chunk":
            slice_name = args.get("slice_name", "physics_pilot")
            chunk_id = int(args["chunk_id"])
            status = str(args["status"])
            skip_reason = (args.get("skip_reason") or "").strip() or None
            cur = conn.execute(
                "UPDATE chapter_slices SET status = ?, skip_reason = COALESCE(?, skip_reason) WHERE slice_name = ? AND chunk_id = ?",
                (status, skip_reason, slice_name, chunk_id),
            )
            conn.commit()
            return {
                "updated": cur.rowcount,
                "slice_name": slice_name,
                "chunk_id": chunk_id,
                "status": status,
                "skip_reason": skip_reason,
            }

        if name == "search_corpus_global":
            return search_corpus_global(
                conn,
                query=str(args["query"]),
                limit=int(args.get("limit", 12)),
                expand_bridges=bool(args.get("expand_bridges", True)),
            )

        if name == "get_chunk_context":
            return {
                "chunk_id": int(args["chunk_id"]),
                "context": get_chunk_context(conn, int(args["chunk_id"]), int(args.get("window", 2))),
            }

        if name == "add_concept_bridge":
            term = str(args["term"]).strip().lower()
            alias = str(args["alias"]).strip().lower()
            pattern = str(args.get("structural_pattern", "")).strip()
            conn.execute(
                "INSERT OR IGNORE INTO concept_bridges (term, alias, structural_pattern) VALUES (?, ?, ?)",
                (term, alias, pattern),
            )
            conn.commit()
            return {"added": {"term": term, "alias": alias, "structural_pattern": pattern}}

        if name == "create_node":
            node_id = create_node_with_provenance(
                conn,
                domain=str(args["domain"]),
                summary=str(args["summary"]),
                chunk_ids=[int(x) for x in args["chunk_ids"]],
                dsl_expr=args.get("dsl_expr"),
                quote_spans=args.get("quote_spans"),
                epistemic_tier=str(args.get("epistemic_tier", "RAW_CLAIM")),
            )
            return {"node_id": node_id}

        if name == "attach_node_provenance":
            return attach_node_provenance(
                conn,
                node_id=int(args["node_id"]),
                chunk_ids=[int(x) for x in args["chunk_ids"]],
                quote_spans=args.get("quote_spans"),
            )

        if name == "create_research_branch":
            root_id = int(args["root_node_id"])
            role = str(args["agent_role"])
            max_dry = int(args.get("max_dry_hops", 3))
            cur = conn.execute(
                """
                INSERT INTO research_branches (root_node_id, agent_role, max_dry_hops)
                VALUES (?, ?, ?)
                """,
                (root_id, role, max_dry),
            )
            conn.commit()
            return {"branch_id": int(cur.lastrowid), "root_node_id": root_id, "agent_role": role, "max_dry_hops": max_dry}

        if name == "run_physics_check":
            return run_physics_check(str(args["python_code"]))

        if name == "verify_node":
            res = verify_node(
                conn,
                node_id=int(args["node_id"]),
                verifier_type=str(args["verifier_type"]),
                verification_scope=str(args["verification_scope"]),
                external_ref=args.get("external_ref"),
                benchmark_ref=args.get("benchmark_ref"),
                passed=bool(args.get("passed", True)),
                branch_id=int(args["branch_id"]) if args.get("branch_id") is not None else None,
                new_tier=args.get("new_tier"),
                notes=str(args.get("notes", "")),
            )
            if args.get("new_tier") in ("EXTERNALLY_VERIFIED", "SIM_CONSISTENT", "CONTESTED", "UNDER_APPEAL", "FALSIFIED"):
                core_p, sl_d = resolve_digest_targets(DB_PATH)
                res["digest_delta"] = on_falsifier_commit(conn, [int(args["node_id"])], core_path=core_p, slices_dir=sl_d)
            return res

        if name == "verify_and_link":
            res = verify_and_link(
                conn,
                from_node_id=int(args["from_node_id"]),
                to_node_id=int(args["to_node_id"]),
                relation_type=str(args["relation_type"]),
                verifier_type=str(args["verifier_type"]),
                external_ref=args.get("external_ref"),
                verification_scope=str(args.get("verification_scope", "llm_only")),
                benchmark_ref=args.get("benchmark_ref"),
                branch_id=int(args["branch_id"]) if args.get("branch_id") is not None else None,
                promote_node_id=int(args["promote_node_id"]) if args.get("promote_node_id") is not None else None,
                new_tier=args.get("new_tier"),
                notes=str(args.get("notes", "")),
            )
            if args.get("new_tier") in ("EXTERNALLY_VERIFIED", "SIM_CONSISTENT", "CONTESTED", "UNDER_APPEAL", "FALSIFIED") or args.get("relation_type") in ("resolved_mistake", "pivoted_to", "reopens", "challenges_falsification"):
                core_p, sl_d = resolve_digest_targets(DB_PATH)
                res["digest_delta"] = on_falsifier_commit(
                    conn, [int(args["from_node_id"]), int(args["to_node_id"])], core_path=core_p, slices_dir=sl_d
                )
            return res

        if name == "get_epistemic_graph":
            domain = args.get("domain")
            if domain:
                nodes = [
                    dict(r)
                    for r in conn.execute("SELECT * FROM nodes WHERE domain = ? ORDER BY node_id", (domain,)).fetchall()
                ]
            else:
                nodes = [dict(r) for r in conn.execute("SELECT * FROM nodes ORDER BY node_id").fetchall()]
            for n in nodes:
                n["provenance"] = [
                    dict(p)
                    for p in conn.execute(
                        "SELECT chunk_id, quote_span FROM node_provenance WHERE node_id = ?",
                        (n["node_id"],),
                    ).fetchall()
                ]
                n["verifications"] = [
                    dict(v)
                    for v in conn.execute(
                        "SELECT * FROM node_verifications WHERE node_id = ? ORDER BY verification_id",
                        (n["node_id"],),
                    ).fetchall()
                ]
            edges = [dict(r) for r in conn.execute("SELECT * FROM edges ORDER BY edge_id").fetchall()]
            branches = [dict(r) for r in conn.execute("SELECT * FROM research_branches ORDER BY branch_id").fetchall()]
            return {"nodes": nodes, "edges": edges, "branches": branches}

        if name == "get_thematic_outline":
            return build_thematic_outline(conn, domain=args.get("domain"))

        if name == "hydrate_tick_context":
            core_p, sl_d = resolve_digest_targets(DB_PATH)
            cids = [int(x) for x in (args.get("chunk_ids") or [])]
            chunks: list[dict[str, Any]] | None = None
            if cids:
                rows = conn.execute(
                    f"SELECT chunk_id, source_ref, content FROM chunks WHERE chunk_id IN ({','.join('?' for _ in cids)})",
                    tuple(cids),
                ).fetchall()
                chunks = [dict(r) for r in rows]
            return hydrate_pre_tick(
                conn,
                domain=str(args.get("domain", "bio_neuro_psych")),
                chunks=chunks,
                query_text=str(args.get("query") or "") or None,
                core_path=core_p,
                slices_dir=sl_d,
                token_budget=int(args.get("token_budget", 2200)),
            )

        if name == "sync_digest_deltas":
            core_p, sl_d = resolve_digest_targets(DB_PATH)
            nids = [int(x) for x in (args.get("node_ids") or [])]
            if nids:
                return on_falsifier_commit(conn, nids, core_path=core_p, slices_dir=sl_d)
            return sync_ouroboros_deltas(conn, core_path=core_p, slices_dir=sl_d)

        raise ValueError(f"Unknown tool: {name}")
    finally:
        conn.close()


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
                "serverInfo": {"name": "corpus-pilot", "version": "0.2.0"},
            },
        }

    if method == "ping":
        return {"jsonrpc": "2.0", "id": req_id, "result": {}}

    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": TOOLS}}

    if method == "tools/call":
        tool_name = params.get("name", "")
        tool_args = params.get("arguments") or {}
        try:
            data = call_tool(tool_name, tool_args)
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
                    "content": [{"type": "text", "text": f"Error in {tool_name}: {exc}"}],
                    "isError": True,
                },
            }

    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {"code": -32601, "message": f"Method not found: {method}"},
    }


def main() -> None:
    for line in sys.stdin:
        stripped = line.strip()
        if not stripped:
            continue
        try:
            req = json.loads(stripped)
        except json.JSONDecodeError as exc:
            err = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": str(exc)}}
            sys.stdout.write(json.dumps(err) + "\n")
            sys.stdout.flush()
            continue
        resp = handle_request(req)
        if resp is not None:
            sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
