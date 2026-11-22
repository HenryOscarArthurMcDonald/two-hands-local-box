#!/usr/bin/env python3
"""Unified Interactive Terminal (`brain.py`) for Corpus + Archive + Core Digest.

Closes the Epistemic Corpus Kernel (`data/corpus.db`), the strictly read-only
Gemini Archive (`archive.db?mode=ro`), and delta-compiled digest momentum
(`chapters/core_digest.md` + `digest_state`) into one interactive shell or
single-command CLI without mutating `levi.py`.

Commands (`brain> ` or `--cmd "..."`):
  status                                   Inspect corpus, archive (?mode=ro), core digest, & digest_state
  query <text> [--dry-run|--live] [...]    Truth-gated Arachne hydration (+ optional live synthesis)
  inspect <target>                         Inspect node:<id>, turn:<id>, #<KEYWORD>, or pivots
  ingest <path> [--tag LABEL] [...]        Idempotent RAW_CLAIM / PROVENANCE_LOG ingest + delta sync
  tick <domain> [--limit 5] [...]          Bounded Lifter -> Scientist -> Falsifier + Stage 3 delta
  help / exit / quit
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import sqlite3
import sys
import tempfile
import urllib.request
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
from compile_digest import (
    DEFAULT_CORE_DIGEST_PATH,
    DEFAULT_SLICES_DIR,
    extract_core_anchor_block,
    resolve_digest_targets,
)
from db_utils import (
    DEFAULT_DB_PATH,
    WORKSPACE_ROOT,
    classify_text_to_section_key,
    estimate_tokens,
    init_db,
)
from ingest_session import ingest_artifact
from single_loop_runner import build_lifter_prompt, run_direct_loop

DEFAULT_ARCHIVE_DB = Path.home() / "Desktop" / "GeminiAccountArchive" / "archive.db"

SLICE_DOMAIN_ALIASES: dict[str, tuple[str, str]] = {
    "physics": ("physics_pilot", "physics"),
    "physics_pilot": ("physics_pilot", "physics"),
    "formal_math": ("lean4_formal", "formal_math"),
    "lean4_formal": ("lean4_formal", "formal_math"),
    "ai_systems": ("ai_systems", "ai_systems"),
    "bio_neuro_psych": ("bio_neuro_psych", "bio_neuro_psych"),
    "philosophy": ("philosophy_epistemology", "philosophy"),
    "philosophy_epistemology": ("philosophy_epistemology", "philosophy"),
}


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


def _archive_summary(archive_db: Path | None) -> dict[str, Any]:
    arch_conn, err = open_archive_ro(archive_db)
    if arch_conn is None:
        return {"available": False, "path": str(archive_db or ""), "reason": err or "unavailable"}
    try:
        convs = int(arch_conn.execute("SELECT COUNT(*) FROM conversations").fetchone()[0])
        turns = int(arch_conn.execute("SELECT COUNT(*) FROM turns").fetchone()[0])
        ouro = arch_conn.execute(
            "SELECT COUNT(*), COALESCE(MAX(id), 0) FROM turns WHERE chat_id = 'levi_recursive_memory'"
        ).fetchone()
        return {
            "available": True,
            "path": str(resolve_archive_db(archive_db) or archive_db),
            "mode": "ro",
            "conversations": convs,
            "turns": turns,
            "ouroboros_turns": int(ouro[0]),
            "max_ouroboros_turn_id": int(ouro[1]),
        }
    except sqlite3.Error as exc:
        return {"available": False, "path": str(archive_db or ""), "reason": str(exc)}
    finally:
        arch_conn.close()


def _resolve_digest_paths(
    db_path: Path,
    core_digest_arg: Path | None = None,
    slices_dir_arg: Path | None = None,
) -> tuple[Path, Path]:
    d_core, d_slices = resolve_digest_targets(db_path)
    return (core_digest_arg or d_core), (slices_dir_arg or d_slices)


# ---------------------------------------------------------------------------
# Command 1: status (strictly read-only)
# ---------------------------------------------------------------------------

def cmd_status(
    *,
    db_path: Path,
    archive_db: Path | None,
    core_digest_path: Path,
    as_json: bool = False,
) -> dict[str, Any]:
    conn = _open_corpus_ro(db_path)
    try:
        total_nodes = int(conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0])
        tiers = {
            r["epistemic_tier"]: int(r["cnt"])
            for r in conn.execute(
                "SELECT epistemic_tier, COUNT(*) AS cnt FROM nodes GROUP BY epistemic_tier"
            ).fetchall()
        }
        edges_cnt = int(conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0])
        bridges_cnt = int(conn.execute("SELECT COUNT(*) FROM concept_bridges").fetchone()[0])
        chunks_cnt = int(conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0])
        ingested_cnt = (
            int(conn.execute("SELECT COUNT(*) FROM ingested_artifacts").fetchone()[0])
            if _table_exists(conn, "ingested_artifacts")
            else 0
        )

        slices: dict[str, dict[str, int]] = {}
        for r in conn.execute(
            "SELECT slice_name, status, COUNT(*) AS cnt FROM chapter_slices GROUP BY slice_name, status ORDER BY slice_name, status"
        ).fetchall():
            slices.setdefault(r["slice_name"], {})[r["status"]] = int(r["cnt"])

        branches = {
            r["status"]: int(r["cnt"])
            for r in conn.execute(
                "SELECT status, COUNT(*) AS cnt FROM research_branches GROUP BY status"
            ).fetchall()
        }

        watermarks: list[dict[str, Any]] = []
        if _table_exists(conn, "digest_state"):
            for r in conn.execute(
                "SELECT section_key, last_compiled_node_id, last_compiled_turn_id, substr(section_sha256, 1, 12) AS sha_prefix, updated_at "
                "FROM digest_state ORDER BY section_key"
            ).fetchall():
                watermarks.append(dict(r))

        core_exists = core_digest_path.exists()
        core_bytes = len(core_digest_path.read_bytes()) if core_exists else 0
        arch = _archive_summary(archive_db)

        payload = {
            "corpus_db": str(db_path.resolve()),
            "mode": "ro",
            "nodes_total": total_nodes,
            "node_tiers": tiers,
            "edges": edges_cnt,
            "concept_bridges": bridges_cnt,
            "chunks": chunks_cnt,
            "ingested_artifacts": ingested_cnt,
            "chapter_slices": slices,
            "research_branches": branches,
            "archive_db": arch,
            "core_digest": {
                "path": str(core_digest_path),
                "exists": core_exists,
                "bytes": core_bytes,
                "kb": round(core_bytes / 1024.0, 2),
                "in_15_30kb_window": 15 * 1024 <= core_bytes <= 30 * 1024,
            },
            "digest_state_count": len(watermarks),
            "digest_state": watermarks,
        }

        if as_json:
            print(json.dumps(payload, indent=2, ensure_ascii=False))
        else:
            print("=== BRAIN STATUS (Corpus + Archive RO + Core Digest) ===")
            print(f"Corpus DB      : {payload['corpus_db']} (?mode=ro)")
            print(
                f"Nodes / Chunks : {total_nodes} nodes ("
                f"EXTERNALLY_VERIFIED={tiers.get('EXTERNALLY_VERIFIED', 0)}, "
                f"FALSIFIED={tiers.get('FALSIFIED', 0)}, "
                f"SIM_CONSISTENT={tiers.get('SIM_CONSISTENT', 0)}, "
                f"CONTESTED={tiers.get('CONTESTED', 0)}, "
                f"UNDER_APPEAL={tiers.get('UNDER_APPEAL', 0)}, "
                f"RAW_CLAIM={tiers.get('RAW_CLAIM', 0)}) | "
                f"{chunks_cnt:,} chunks | {edges_cnt} edges | {bridges_cnt} bridges | {ingested_cnt} ingested_artifacts"
            )
            print(
                f"Branches       : CONVERGED={branches.get('CONVERGED', 0)} | "
                f"ACTIVE={branches.get('ACTIVE', 0)} | HALTED_NOVELTY={branches.get('HALTED_NOVELTY', 0)}"
            )
            bnp = slices.get("bio_neuro_psych", {})
            print(
                f"bio_neuro_psych: PROCESSED={bnp.get('PROCESSED', 0)} / "
                f"SKIPPED={bnp.get('SKIPPED', 0)} / PENDING={bnp.get('PENDING', 0)}"
            )
            for sname, sc in slices.items():
                if sname != "bio_neuro_psych":
                    print(
                        f"  {sname:<16}: PROCESSED={sc.get('PROCESSED', 0)} / "
                        f"SKIPPED={sc.get('SKIPPED', 0)} / PENDING={sc.get('PENDING', 0)}"
                    )
            if arch.get("available"):
                print(
                    f"Archive DB     : connected (?mode=ro) | {arch['conversations']} convs | "
                    f"{arch['turns']:,} turns | {arch['ouroboros_turns']} ouroboros (max_turn_id={arch['max_ouroboros_turn_id']})"
                )
            else:
                print(f"Archive DB     : unavailable ({arch.get('reason')})")
            print(
                f"Core Digest    : {core_digest_path} | {core_bytes:,} bytes ({payload['core_digest']['kb']} KB, "
                f"target 15-30 KB: {payload['core_digest']['in_15_30kb_window']})"
            )
            print(f"digest_state   : {len(watermarks)} watermarks tracked")
            for w in watermarks:
                if w["section_key"] in ("CORE_DIGEST", "OUROBOROS_LEDGER"):
                    print(
                        f"  - {w['section_key']}: max_node=#{w['last_compiled_node_id']} | "
                        f"max_turn={w['last_compiled_turn_id']} | sha={w['sha_prefix']} | {w['updated_at']}"
                    )
        return payload
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Command 2: query <text> (strictly read-only + truth-gated)
# ---------------------------------------------------------------------------

def _synthesize_live(
    *,
    backend: str,
    model: str | None,
    ollama_url: str,
    prompt: str,
) -> str:
    if backend == "gemini":
        from google import genai
        from google.genai import types

        api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY or GOOGLE_API_KEY must be set for --live Gemini synthesis.")
        client = genai.Client(api_key=api_key)
        resp = client.models.generate_content(
            model=model or "gemini-2.5-flash",
            contents=prompt,
            config=types.GenerateContentConfig(temperature=0.1),
        )
        return (resp.text or "").strip()

    req = urllib.request.Request(
        f"{ollama_url.rstrip('/')}/api/generate",
        data=json.dumps(
            {
                "model": model or "llama3.1:8b",
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": 0.1, "num_ctx": 8192},
            }
        ).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=180) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return str(data.get("response") or "").strip()


def cmd_query(
    raw_args: list[str],
    *,
    db_path: Path,
    archive_db: Path | None,
    core_digest_path: Path,
    default_budget: int = 2200,
    default_backend: str = "dry-run",
    model: str | None = None,
    ollama_url: str = "http://127.0.0.1:11434",
    as_json: bool = False,
) -> dict[str, Any]:
    qp = argparse.ArgumentParser(prog="query", add_help=False)
    qp.add_argument("--dry-run", action="store_true")
    qp.add_argument("--live", action="store_true")
    qp.add_argument("--domain", default=None)
    qp.add_argument("--budget", type=int, default=default_budget)
    qp.add_argument("--backend", choices=["gemini", "ollama"], default="gemini" if default_backend != "ollama" else "ollama")
    qp.add_argument("terms", nargs="*")
    qargs, unknown = qp.parse_known_args(raw_args)

    raw_text = " ".join(qargs.terms + unknown).strip()
    if not raw_text:
        raise ValueError("Usage: query <text> [--dry-run|--live] [--domain DOMAIN] [--budget 2200]")

    cleaned_query = filter_query_text(raw_text) or raw_text
    is_live = bool(qargs.live or (not qargs.dry_run and default_backend in ("gemini", "ollama") and "--dry-run" not in raw_args))
    if "--live" not in raw_args and default_backend == "dry-run":
        is_live = False

    conn = _open_corpus_ro(db_path)
    arch_conn, arch_err = open_archive_ro(archive_db)
    try:
        packet = retrieve_hybrid_and_gated(
            conn,
            cleaned_query,
            domain=qargs.domain,
            archive_conn=arch_conn,
            top_k_chunks=8,
            top_k_nodes=10,
            token_budget=int(qargs.budget),
            expand_bridges=True,
            backtrack_parents=True,
        )
        core_text = core_digest_path.read_text(encoding="utf-8") if core_digest_path.exists() else ""
        core_anchor = extract_core_anchor_block(core_text)
        section_key = classify_text_to_section_key(cleaned_query)

        citations = {
            "verified_node_ids": [v["node_id"] for v in packet.get("verified_invariants", [])],
            "provisional_node_ids": [p["node_id"] for p in packet.get("provisional_claims", [])],
            "falsified_pivots": [
                {
                    "falsified_node_id": f["falsified_node_id"],
                    "pivoted_to_node_id": f["pivoted_to_node_id"],
                }
                for f in packet.get("falsified_constraints", [])
            ],
            "slice_sources": [
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
        }

        synthesis: str | None = None
        if is_live:
            llm_prompt = (
                "You are the Epistemic Corpus Brain. Answer using ONLY grounded evidence below.\n"
                "- Cite exact node_id (#...), chunk_id, turn_id, and sha256 prefixes.\n"
                "- Never assert PROVISIONAL (RAW_CLAIM / SIM_CONSISTENT) items as verified law.\n"
                "- Respect all [NEGATIVE CONSTRAINTS] and use their pivoted_to replacements.\n\n"
                f"=== PINNED CORE ANCHOR ===\n{core_anchor}\n\n"
                f"{packet['rendered_markdown']}\n\n"
                f"USER QUESTION: {raw_text}\n"
            )
            synthesis = _synthesize_live(
                backend=qargs.backend,
                model=model,
                ollama_url=ollama_url,
                prompt=llm_prompt,
            )

        out = {
            "raw_query": raw_text,
            "cleaned_query": cleaned_query,
            "section_key": section_key,
            "archive_db_status": "connected" if arch_err is None else arch_err,
            "estimated_tokens": packet["estimated_tokens"],
            "token_budget": int(qargs.budget),
            "mode": "live" if is_live else "dry-run",
            "citations": citations,
            "synthesis": synthesis,
            "packet": packet,
        }
        if as_json:
            print(json.dumps(out, indent=2, ensure_ascii=False))
        else:
            print(
                f"=== BRAIN QUERY ({out['mode']}) | target={section_key} | "
                f"tokens={packet['estimated_tokens']}/{qargs.budget} | archive={out['archive_db_status']} ==="
            )
            print(f"Cleaned Query: {cleaned_query}")
            print()
            print(packet["rendered_markdown"])
            print("\n=== CITATION MANIFEST ===")
            print(
                f"Verified nodes: {citations['verified_node_ids']} | "
                f"Provisional nodes: {citations['provisional_node_ids']} | "
                f"Negative constraints: {citations['falsified_pivots']}"
            )
            if citations["slice_sources"]:
                for c in citations["slice_sources"]:
                    print(
                        f"  - [{c['source']}] chunk_id={c['chunk_id']} chat_id={c['chat_id']} "
                        f"turn_index={c['turn_index']} turn_id={c['turn_id']} "
                        f"parent_turn_id={c['parent_turn_id']} sha256={str(c['sha256'] or '')[:12]}"
                    )
            if synthesis is not None:
                print("\n=== GROUNDED SYNTHESIS ===")
                print(synthesis)
        return out
    finally:
        if arch_conn is not None:
            arch_conn.close()
        conn.close()


# ---------------------------------------------------------------------------
# Command 3: inspect <target> (strictly read-only)
# ---------------------------------------------------------------------------

def cmd_inspect(
    raw_args: list[str],
    *,
    db_path: Path,
    archive_db: Path | None,
    slices_dir: Path,
    as_json: bool = False,
) -> dict[str, Any]:
    if not raw_args:
        raise ValueError("Usage: inspect <node:745 | turn:<id> | #<KEYWORD> | pivots>")

    target = " ".join(raw_args).strip()
    conn = _open_corpus_ro(db_path)
    arch_conn, arch_err = open_archive_ro(archive_db)
    try:
        # 1. FALSIFIED -> PIVOTED_TO chains
        if target.lower().startswith("pivots") or target.lower() == "falsified":
            parts = target.split()
            lim = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 25
            rows = conn.execute(
                """
                SELECT f.node_id AS falsified_node_id, f.domain, f.epistemic_tier AS falsified_tier,
                       f.summary AS falsified_summary, e.relation_type,
                       t.node_id AS pivoted_to_node_id, t.epistemic_tier AS pivoted_to_tier,
                       t.summary AS pivoted_to_summary
                FROM edges e
                JOIN nodes f ON f.node_id = e.from_node
                JOIN nodes t ON t.node_id = e.to_node
                WHERE e.relation_type IN ('pivoted_to', 'resolved_mistake')
                ORDER BY f.node_id DESC, e.edge_id DESC
                LIMIT ?
                """,
                (lim,),
            ).fetchall()
            out = {"target": "pivots", "chains": [dict(r) for r in rows]}
            if as_json:
                print(json.dumps(out, indent=2, ensure_ascii=False))
            else:
                print(f"=== FALSIFIED -> PIVOTED_TO CHAINS (top {len(rows)}) ===")
                for r in out["chains"]:
                    print(
                        f"- #{r['falsified_node_id']} [{r['falsified_tier']}] --({r['relation_type']})--> "
                        f"#{r['pivoted_to_node_id']} [{r['pivoted_to_tier']}]\n"
                        f"    FALSIFIED: {r['falsified_summary'][:140]}\n"
                        f"    REFRAMED : {r['pivoted_to_summary'][:140]}"
                    )
            return out

        # 2. node:<id> or #<id> or bare integer
        m_node = re.match(r"^(?:node:|#)(\d+)$|^(\d+)$", target, re.IGNORECASE)
        if m_node:
            nid = int(m_node.group(1) or m_node.group(2))
            node = conn.execute("SELECT * FROM nodes WHERE node_id = ?", (nid,)).fetchone()
            if node is None:
                raise KeyError(f"Node #{nid} not found in {db_path}")
            prov = [
                {
                    **dict(p),
                    "chat_id": parse_archive_ref(str(p["source_ref"]))[0],
                    "turn_index": parse_archive_ref(str(p["source_ref"]))[1],
                }
                for p in conn.execute(
                    """
                    SELECT np.chunk_id, np.quote_span, c.source_type, c.source_ref, c.sha256, substr(c.content, 1, 200) AS snippet
                    FROM node_provenance np
                    JOIN chunks c ON c.chunk_id = np.chunk_id
                    WHERE np.node_id = ?
                    ORDER BY np.chunk_id
                    """,
                    (nid,),
                ).fetchall()
            ]
            verifs = [
                dict(v)
                for v in conn.execute(
                    "SELECT * FROM node_verifications WHERE node_id = ? ORDER BY verification_id",
                    (nid,),
                ).fetchall()
            ]
            edges_out = [
                dict(e)
                for e in conn.execute(
                    """
                    SELECT e.edge_id, e.relation_type, e.to_node AS peer_id, n.epistemic_tier AS peer_tier,
                           n.summary AS peer_summary, e.external_ref, e.notes
                    FROM edges e
                    JOIN nodes n ON n.node_id = e.to_node
                    WHERE e.from_node = ?
                    ORDER BY e.edge_id
                    """,
                    (nid,),
                ).fetchall()
            ]
            edges_in = [
                dict(e)
                for e in conn.execute(
                    """
                    SELECT e.edge_id, e.relation_type, e.from_node AS peer_id, n.epistemic_tier AS peer_tier,
                           n.summary AS peer_summary, e.external_ref, e.notes
                    FROM edges e
                    JOIN nodes n ON n.node_id = e.from_node
                    WHERE e.to_node = ?
                    ORDER BY e.edge_id
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
            out = {
                "target": f"node:{nid}",
                "node": dict(node),
                "provenance": prov,
                "verifications": verifs,
                "outgoing_edges": edges_out,
                "incoming_edges": edges_in,
                "research_branches": branches,
            }
            if as_json:
                print(json.dumps(out, indent=2, ensure_ascii=False))
            else:
                n = out["node"]
                print(f"=== NODE #{n['node_id']} [{n['epistemic_tier']} | {n['domain']}] ===")
                print(f"Summary    : {n['summary']}")
                if n.get("dsl_expr"):
                    print(f"DSL        : {n['dsl_expr']}")
                print(f"Provenance : {len(prov)} chunk(s)")
                for p in prov:
                    print(
                        f"  - chunk_id={p['chunk_id']} ({p['source_type']}) sha256={p['sha256'][:12]} "
                        f"chat_id={p['chat_id']} turn_index={p['turn_index']} ref={p['source_ref']}"
                    )
                print(f"Verifs     : {len(verifs)}")
                for v in verifs:
                    print(
                        f"  - [{v['verifier_type']} / {v['verification_scope']}] passed={bool(v['passed'])} "
                        f"ref={v['external_ref']} | benchmark={v['benchmark_ref']}"
                    )
                if edges_out or edges_in:
                    print("Edges:")
                    for e in edges_out:
                        print(f"  - OUT #{nid} --({e['relation_type']})--> #{e['peer_id']} [{e['peer_tier']}]: {e['peer_summary'][:120]}")
                    for e in edges_in:
                        print(f"  - IN  #{e['peer_id']} [{e['peer_tier']}] --({e['relation_type']})--> #{nid}: {e['peer_summary'][:120]}")
                for b in branches:
                    print(
                        f"Branch #{b['branch_id']}: status={b['status']} role={b['agent_role']} "
                        f"hops={b['total_hops']} dry={b['hops_since_novelty']}/{b['max_dry_hops']}"
                    )
            return out

        # 3. turn:<id_or_turn_id> or archive:<chat_id>:turn:<idx>
        if target.lower().startswith("turn:") or target.lower().startswith("archive:"):
            if arch_conn is None:
                raise RuntimeError(f"Cannot inspect turn {target!r}: {arch_err}")
            m_arch = re.match(r"^archive:([^:]+):turn:(\d+)$", target, re.IGNORECASE)
            if m_arch:
                tid_raw = target
                row = arch_conn.execute(
                    """
                    SELECT t.*, COALESCE(c.title, '') AS chat_title
                    FROM turns t
                    LEFT JOIN conversations c ON c.chat_id = t.chat_id
                    WHERE t.chat_id = ? AND t.turn_index = ?
                    """,
                    (m_arch.group(1), int(m_arch.group(2))),
                ).fetchone()
            else:
                tid_raw = target.split(":", 1)[1].strip()
                if tid_raw.isdigit():
                    row = arch_conn.execute(
                        """
                        SELECT t.*, COALESCE(c.title, '') AS chat_title
                        FROM turns t
                        LEFT JOIN conversations c ON c.chat_id = t.chat_id
                        WHERE t.id = ?
                        """,
                        (int(tid_raw),),
                    ).fetchone()
                else:
                    row = arch_conn.execute(
                        """
                        SELECT t.*, COALESCE(c.title, '') AS chat_title
                        FROM turns t
                        LEFT JOIN conversations c ON c.chat_id = t.chat_id
                        WHERE t.turn_id = ?
                        """,
                        (tid_raw,),
                    ).fetchone()
            if row is None:
                raise KeyError(f"Turn {tid_raw!r} not found in archive.db")
            td = dict(row)
            sref_pat = f"archive:{td['chat_id']}:turn:{td['turn_index']}%"
            linked_chunks = [
                dict(r)
                for r in conn.execute(
                    "SELECT chunk_id, source_ref, sha256 FROM chunks WHERE source_ref LIKE ? LIMIT 10",
                    (sref_pat,),
                ).fetchall()
            ]
            out = {"target": f"turn:{tid_raw}", "turn": td, "linked_corpus_chunks": linked_chunks}
            if as_json:
                print(json.dumps(out, indent=2, ensure_ascii=False))
            else:
                print(
                    f"=== ARCHIVE TURN rowid={td['id']} | turn_id={td.get('turn_id')} | "
                    f"parent={td.get('parent_turn_id')} | next={td.get('next_turn_id')} ==="
                )
                print(f"Chat   : {td['chat_id']} (turn_index={td['turn_index']}) | {td.get('chat_title')}")
                print(f"SHA256 : {td.get('sha256')} | timestamp={td.get('timestamp_hint')}")
                print(f"User   : {(td.get('user_prompt') or '')[:350]}")
                print(f"Model  : {(td.get('model_response') or '')[:450]}")
                if linked_chunks:
                    print(f"Corpus Chunks: {[c['chunk_id'] for c in linked_chunks]}")
            return out

        # 4. # KEYWORD: <SECTION_KEY> or section slice lookup
        sec_clean = re.sub(r"^#?\s*(?:KEYWORD:\s*)?", "", target, flags=re.IGNORECASE).strip().upper()
        candidates = sorted(p.stem for p in slices_dir.glob("*.md")) if slices_dir.exists() else []
        matched_key = next((c for c in candidates if c == sec_clean or c.startswith(sec_clean)), sec_clean)
        slice_file = slices_dir / f"{matched_key}.md"
        wm = None
        if _table_exists(conn, "digest_state"):
            wrow = conn.execute("SELECT * FROM digest_state WHERE section_key = ?", (matched_key,)).fetchone()
            wm = dict(wrow) if wrow is not None else None
        if not slice_file.exists() and wm is None:
            raise KeyError(f"Inspect target not recognized or missing: {target!r}")
        slice_text = slice_file.read_text(encoding="utf-8") if slice_file.exists() else ""
        out = {
            "target": f"section:{matched_key}",
            "watermark": wm,
            "slice_file": str(slice_file) if slice_file.exists() else None,
            "preview": "\n".join(slice_text.splitlines()[:60]),
        }
        if as_json:
            print(json.dumps(out, indent=2, ensure_ascii=False))
        else:
            print(f"=== SECTION # KEYWORD: {matched_key} ===")
            print(f"Watermark : {wm}")
            if out["preview"]:
                print(out["preview"])
        return out
    finally:
        if arch_conn is not None:
            arch_conn.close()
        conn.close()


# ---------------------------------------------------------------------------
# Command 4 & 5: ingest & tick
# ---------------------------------------------------------------------------

def cmd_ingest(
    raw_args: list[str],
    *,
    db_path: Path,
    archive_db: Path | None,
    as_json: bool = False,
) -> dict[str, Any]:
    ip = argparse.ArgumentParser(prog="ingest", add_help=False)
    ip.add_argument("--tag", default="PROVENANCE_LOG")
    ip.add_argument("--chat-id", default=None)
    ip.add_argument("--slice", dest="slice_name", default=None)
    ip.add_argument("--no-sync", action="store_true")
    ip.add_argument("path", nargs="?")
    iargs, unknown = ip.parse_known_args(raw_args)
    src = iargs.path or (unknown[0] if unknown else None)
    if not src:
        raise ValueError("Usage: ingest <path> [--tag PROVENANCE_LOG] [--chat-id ID] [--no-sync]")

    res = ingest_artifact(
        db_path=db_path,
        source_path=src,
        source_tag=iargs.tag,
        chat_id=iargs.chat_id,
        sync_digest=not iargs.no_sync,
        slice_name=iargs.slice_name,
        archive_db=archive_db,
    )
    if as_json:
        print(json.dumps(res, indent=2, ensure_ascii=False))
    else:
        print(
            f"=== INGEST [{res['status']}] | {res['source_type']} | tier={res['epistemic_tier']} "
            f"(auto_promoted={res['nodes_auto_promoted']}) ==="
        )
        print(
            f"Path: {res['source_path']} | tag={res['source_tag']} | sha256={res['sha256'][:12]} | "
            f"inserted={res['chunks_inserted']} chunks | skipped_dups={res['duplicates_skipped']} | section={res['section_key']}"
        )
        if res.get("digest_delta"):
            dd = res["digest_delta"]
            print(
                f"Digest Delta: recompiled={dd.get('recompiled_sections')} | "
                f"core_refreshed={dd.get('core_refreshed')} | core_bytes={dd.get('core_digest_bytes')}"
            )
    return res


def cmd_tick(
    raw_args: list[str],
    *,
    db_path: Path,
    archive_db: Path | None,
    packet_budget: int = 2200,
    default_backend: str = "gemini",
    ollama_url: str = "http://127.0.0.1:11434",
) -> None:
    tp = argparse.ArgumentParser(prog="tick", add_help=False)
    tp.add_argument("--limit", type=int, default=5)
    tp.add_argument("--batch-size", type=int, default=5)
    tp.add_argument("--slice", dest="slice_name", default=None)
    tp.add_argument("--backend", choices=["gemini", "ollama"], default="ollama" if default_backend == "ollama" else "gemini")
    tp.add_argument("--dry-run", action="store_true")
    tp.add_argument("domain_arg", nargs="?")
    targs, unknown = tp.parse_known_args(raw_args)

    raw_dom = targs.domain_arg or (unknown[0] if unknown else "bio_neuro_psych")
    slice_default, canonical_dom = SLICE_DOMAIN_ALIASES.get(raw_dom, (raw_dom, raw_dom))
    slice_name = targs.slice_name or slice_default

    if targs.dry_run:
        with tempfile.TemporaryDirectory(prefix="brain_tick_dry_") as tmpdir:
            conn = _open_corpus_ro(db_path)
            try:
                rows = conn.execute(
                    """
                    SELECT c.chunk_id, c.source_type, c.source_ref, c.content
                    FROM chapter_slices cs
                    JOIN chunks c ON c.chunk_id = cs.chunk_id
                    WHERE cs.slice_name = ? AND cs.status = 'PENDING'
                    ORDER BY cs.relevance ASC
                    LIMIT ?
                    """,
                    (slice_name, int(targs.limit)),
                ).fetchall()
                chunks = [dict(r) for r in rows]
                arch_conn, arch_err = open_archive_ro(archive_db)
                try:
                    q_seed = filter_query_text(" ".join(c["content"][:500] for c in chunks)) or canonical_dom
                    pkt = retrieve_hybrid_and_gated(
                        conn,
                        q_seed,
                        domain=canonical_dom,
                        archive_conn=arch_conn,
                        exclude_chunk_ids={int(c["chunk_id"]) for c in chunks},
                        token_budget=int(packet_budget),
                    )
                finally:
                    if arch_conn is not None:
                        arch_conn.close()
                core_path, _ = resolve_digest_targets(db_path)
                prompt = build_lifter_prompt(
                    conn,
                    canonical_dom,
                    chunks,
                    hydrated={"core_digest_path": str(core_path), "packet": pkt},
                    core_mode="anchor",
                )
                preview_path = Path(tmpdir) / "dry_run_step_a_prompt.txt"
                preview_path.write_text(prompt, encoding="utf-8")
                print(
                    json.dumps(
                        {
                            "status": "dry_run_ok",
                            "slice_name": slice_name,
                            "domain": canonical_dom,
                            "chunk_ids": [c["chunk_id"] for c in chunks],
                            "packet_tokens": pkt["estimated_tokens"],
                            "prompt_tokens": estimate_tokens(prompt),
                            "archive_db_status": "connected" if arch_err is None else arch_err,
                        },
                        indent=2,
                    )
                )
                return
            finally:
                conn.close()

    init_db(db_path)
    run_ns = argparse.Namespace(
        backend=targs.backend,
        db=db_path,
        slice_name=slice_name,
        domain=canonical_dom,
        limit=int(targs.limit),
        batch_size=int(targs.batch_size),
        lifter_model="gemini-2.5-flash" if targs.backend == "gemini" else "llama3.1:8b",
        scientist_model="gemini-2.5-flash" if targs.backend == "gemini" else "llama3.1:8b",
        falsifier_model="gemini-2.5-flash" if targs.backend == "gemini" else "llama3.1:8b",
        ollama_url=ollama_url,
        metrics_out=WORKSPACE_ROOT / "data" / "single_loop_runs" / "brain_tick_metrics.json",
        archive_db=archive_db,
        no_hydrate=False,
        core_mode="anchor",
        packet_budget=int(packet_budget),
        no_digest_delta=False,
    )
    run_direct_loop(run_ns)


# ---------------------------------------------------------------------------
# Dispatcher & Unified REPL
# ---------------------------------------------------------------------------

HELP_TEXT = """Commands inside brain> :
  status                                    Print Corpus, Archive (?mode=ro), Core Digest & digest_state
  query <text> [--dry-run|--live] [...]     Truth-gated hydration (+ optional LLM synthesis)
  inspect <node:745|turn:...|#<KEY>|pivots> Inspect verified provenance, pivots, archive turns, or slices
  ingest <path> [--tag LABEL] [--no-sync]   Fold .md/.txt/.json/.html cleanly as RAW_CLAIM + delta compile
  tick <domain> [--limit 5] [--dry-run]     Run bounded Lifter->Scientist->Falsifier + Stage 3 delta
  help | exit | quit"""


def dispatch_command(line: str, ctx: dict[str, Any]) -> bool:
    """Execute one brain shell line. Returns False to exit REPL."""
    parts = shlex.split(line.strip())
    if not parts:
        return True
    cmd, rest = parts[0].lower(), parts[1:]

    if cmd in ("exit", "quit", "q"):
        return False
    if cmd in ("help", "?"):
        print(HELP_TEXT)
        return True
    if cmd == "status":
        cmd_status(
            db_path=ctx["db_path"],
            archive_db=ctx["archive_db"],
            core_digest_path=ctx["core_digest"],
            as_json=ctx["as_json"],
        )
        return True
    if cmd == "query":
        cmd_query(
            rest,
            db_path=ctx["db_path"],
            archive_db=ctx["archive_db"],
            core_digest_path=ctx["core_digest"],
            default_budget=ctx["packet_budget"],
            default_backend=ctx["backend"],
            model=ctx["model"],
            ollama_url=ctx["ollama_url"],
            as_json=ctx["as_json"],
        )
        return True
    if cmd == "inspect":
        cmd_inspect(
            rest,
            db_path=ctx["db_path"],
            archive_db=ctx["archive_db"],
            slices_dir=ctx["slices_dir"],
            as_json=ctx["as_json"],
        )
        return True
    if cmd == "ingest":
        if ctx.get("mode") == "readonly":
            raise PermissionError("ingest is disabled under --mode readonly")
        cmd_ingest(
            rest,
            db_path=ctx["db_path"],
            archive_db=ctx["archive_db"],
            as_json=ctx["as_json"],
        )
        return True
    if cmd == "tick":
        if ctx.get("mode") == "readonly" and "--dry-run" not in rest:
            raise PermissionError("mutating tick is disabled under --mode readonly (pass --dry-run)")
        cmd_tick(
            rest,
            db_path=ctx["db_path"],
            archive_db=ctx["archive_db"],
            packet_budget=ctx["packet_budget"],
            default_backend=ctx["backend"] if ctx["backend"] in ("gemini", "ollama") else "gemini",
            ollama_url=ctx["ollama_url"],
        )
        return True
    print(f"Unknown command {cmd!r}. Type 'help' for valid commands.")
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="Unified Corpus + Archive + Digest Brain Terminal")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--archive-db", type=Path, default=DEFAULT_ARCHIVE_DB)
    parser.add_argument("--core-digest", type=Path, default=None)
    parser.add_argument("--slices-dir", type=Path, default=None)
    parser.add_argument("--packet-budget", type=int, default=2200)
    parser.add_argument("--backend", choices=["dry-run", "gemini", "ollama"], default="dry-run")
    parser.add_argument("--model", default=None)
    parser.add_argument("--ollama-url", default="http://127.0.0.1:11434")
    parser.add_argument("--mode", choices=["repl", "single", "readonly"], default="repl", help="Optional runtime mode selector")
    parser.add_argument("--cmd", default=None, help="Execute one command cleanly and exit")
    parser.add_argument("--json", action="store_true", help="Emit structured JSON output")
    args = parser.parse_args()

    core_path, slices_dir = _resolve_digest_paths(args.db, args.core_digest, args.slices_dir)
    ctx = {
        "db_path": args.db,
        "archive_db": args.archive_db,
        "core_digest": core_path,
        "slices_dir": slices_dir,
        "packet_budget": int(args.packet_budget),
        "backend": args.backend,
        "model": args.model,
        "ollama_url": args.ollama_url,
        "mode": args.mode,
        "as_json": bool(args.json),
    }

    if args.cmd is not None:
        dispatch_command(args.cmd, ctx)
        return

    print("Epistemic Corpus Brain Shell (Corpus DB + Archive RO + Core Digest). Type 'help' or 'exit'.")
    while True:
        try:
            line = input("brain> ")
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not line.strip():
            continue
        try:
            keep_going = dispatch_command(line, ctx)
        except Exception as exc:
            print(f"[error] {exc}")
            keep_going = True
        if not keep_going:
            break


if __name__ == "__main__":
    main()
