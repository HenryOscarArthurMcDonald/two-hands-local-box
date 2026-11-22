#!/usr/bin/env python3
"""Structured Digest Momentum Compiler (Stages 1-4) & Pre-Tick Hydrator.

Replaces monolithic prototype_history exports with:
  Stage 1: Two-layer digest
    1) Pinned core_digest.md (~15-30 KB, prompt-cacheable)
       - Active ring status, EXTERNALLY_VERIFIED canonical invariants,
         FALSIFIED -> pivoted_to dead-end pairs, and # KEYWORD: anchor map.
    2) Compiled # KEYWORD: slices (chapters/digest_slices/<SECTION_KEY>.md) +
       on-demand dynamic topic slices over corpus.db + archive.db.
  Stage 2: Deterministic pre-tick hydration (hydrate_pre_tick) for single_loop_runner.py.
  Stage 3: Event-driven delta re-compilation on Falsifier commits (on_falsifier_commit)
           and Ouroboros turns in archive.db (sync_ouroboros_deltas), tracked in
           corpus.db digest_state(section_key, last_compiled_node_id,
           last_compiled_turn_id, section_sha256, updated_at).
  Stage 4: Vocabulary-drift loop closure via concept_bridges query expansion.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from arachne_bridge import (
    extract_query_keywords,
    filter_query_text,
    open_archive_ro,
    parse_archive_ref,
    retrieve_hybrid_and_gated,
    strip_metadata_paths,
)
from db_utils import (
    DEFAULT_DB_PATH,
    SECTION_KEY_TO_THEME,
    THEMATIC_BUCKETS,
    WORKSPACE_ROOT,
    build_thematic_outline,
    classify_text_to_section_key,
    ensure_digest_state_table,
    estimate_tokens,
    get_connection,
    init_db,
    section_key_for_theme,
)

DEFAULT_CORE_DIGEST_PATH = WORKSPACE_ROOT / "chapters" / "core_digest.md"
DEFAULT_SLICES_DIR = WORKSPACE_ROOT / "chapters" / "digest_slices"
WORKSPACE_DB_PATH = WORKSPACE_ROOT / "data" / "corpus.db"


def resolve_digest_targets(db_path: Path | str | None) -> tuple[Path, Path]:
    """Use chapters/ for the workspace corpus.db and sibling dir for isolated DBs."""
    if db_path is not None:
        resolved = Path(db_path).expanduser().resolve()
        if resolved != WORKSPACE_DB_PATH.resolve():
            return resolved.parent / "core_digest.md", resolved.parent / "digest_slices"
    return DEFAULT_CORE_DIGEST_PATH, DEFAULT_SLICES_DIR
CORE_SECTION_KEY = "CORE_DIGEST"
OUROBOROS_SECTION_KEY = "OUROBOROS_LEDGER"
OUROBOROS_CHAT_ID = "levi_recursive_memory"

CORE_MIN_BYTES = 15 * 1024
CORE_TARGET_BYTES = 24 * 1024
CORE_MAX_BYTES = 30 * 1024


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _compact(text: str | None, max_len: int = 120) -> str:
    clean = re.sub(r"\s+", " ", (text or "")).strip()
    if len(clean) <= max_len:
        return clean
    return clean[: max_len - 1].rstrip() + "…"


def _fetch_ouroboros_turns(
    archive_conn: sqlite3.Connection | None,
    since_turn_id: int = 0,
) -> list[dict[str, Any]]:
    """Read-only fetch of Levi Ouroboros syntheses from archive.db."""
    if archive_conn is None:
        return []
    out: list[dict[str, Any]] = []
    try:
        has_turns = bool(
            archive_conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='turns'"
            ).fetchone()
        )
        if has_turns:
            rows = archive_conn.execute(
                """
                SELECT t.id, t.chat_id, t.turn_index, COALESCE(t.turn_id, '') AS turn_id,
                       COALESCE(t.parent_turn_id, '') AS parent_turn_id,
                       COALESCE(t.sha256, '') AS sha256,
                       COALESCE(t.user_prompt, '') AS user_prompt,
                       COALESCE(t.model_response, '') AS model_response,
                       COALESCE(t.timestamp_hint, '') AS timestamp_hint,
                       COALESCE(c.title, 'Levi Autonomous Epistemic Ledger') AS title
                FROM turns t
                LEFT JOIN conversations c ON c.chat_id = t.chat_id
                WHERE t.chat_id = ? AND t.id > ?
                ORDER BY t.id ASC
                """,
                (OUROBOROS_CHAT_ID, since_turn_id),
            ).fetchall()
            for r in rows:
                out.append(dict(r))

        has_lrm_table = bool(
            archive_conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='levi_recursive_memory'"
            ).fetchone()
        )
        if has_lrm_table:
            cols = [
                c[1]
                for c in archive_conn.execute("PRAGMA table_info('levi_recursive_memory')").fetchall()
            ]
            id_col = "id" if "id" in cols else "rowid"
            rows = archive_conn.execute(
                f"SELECT {id_col} AS id, * FROM levi_recursive_memory WHERE {id_col} > ? ORDER BY {id_col} ASC",
                (since_turn_id,),
            ).fetchall()
            for r in rows:
                d = dict(r)
                out.append(
                    {
                        "id": int(d["id"]),
                        "chat_id": OUROBOROS_CHAT_ID,
                        "turn_index": int(d.get("turn_index") or d["id"]),
                        "turn_id": str(d.get("turn_id") or f"lrm:{d['id']}"),
                        "parent_turn_id": str(d.get("parent_turn_id") or ""),
                        "sha256": str(d.get("sha256") or ""),
                        "user_prompt": str(d.get("query") or d.get("user_prompt") or d.get("title") or ""),
                        "model_response": str(d.get("synthesis") or d.get("model_response") or d.get("content") or ""),
                        "timestamp_hint": str(d.get("created_at") or d.get("timestamp_hint") or ""),
                        "title": "Levi Recursive Memory",
                    }
                )
    except sqlite3.Error:
        return []
    return out


def _ingest_new_ouroboros_into_corpus(
    conn: sqlite3.Connection,
    turns: list[dict[str, Any]],
) -> int:
    """Optionally sync new read-only archive.db Ouroboros syntheses into corpus.db chunks+FTS5."""
    inserted = 0
    for t in turns:
        chat_id = str(t.get("chat_id") or OUROBOROS_CHAT_ID)
        tidx = int(t.get("turn_index") or 0)
        title = str(t.get("title") or "Levi Autonomous Epistemic Ledger").strip()
        sref = f"archive:{chat_id}:turn:{tidx} | {title}"
        ts = str(t.get("timestamp_hint") or "") or None
        for author, body in (("user", t.get("user_prompt")), ("assistant", t.get("model_response"))):
            norm = re.sub(r"\n{3,}", "\n\n", (body or "").strip())
            if len(norm) < 10:
                continue
            digest = _sha256_text(norm)
            cur = conn.execute(
                """
                INSERT OR IGNORE INTO chunks (source_type, source_ref, author, created_at, sha256, content)
                VALUES ('chat_db', ?, ?, ?, ?, ?)
                """,
                (sref, author, ts, digest, norm),
            )
            if cur.rowcount > 0:
                rowid = cur.lastrowid
                conn.execute(
                    "INSERT INTO chunks_fts(rowid, content) VALUES (?, ?)",
                    (rowid, norm),
                )
                inserted += 1
    if inserted:
        conn.commit()
    return inserted


def _get_digest_row(conn: sqlite3.Connection, section_key: str) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM digest_state WHERE section_key = ?",
        (section_key,),
    ).fetchone()
    return dict(row) if row is not None else None


def _upsert_digest_state(
    conn: sqlite3.Connection,
    section_key: str,
    last_node_id: int,
    last_turn_id: int,
    section_sha256: str,
) -> None:
    conn.execute(
        """
        INSERT INTO digest_state
            (section_key, last_compiled_node_id, last_compiled_turn_id, section_sha256, updated_at)
        VALUES (?, ?, ?, ?, datetime('now'))
        ON CONFLICT(section_key) DO UPDATE SET
            last_compiled_node_id = excluded.last_compiled_node_id,
            last_compiled_turn_id = excluded.last_compiled_turn_id,
            section_sha256        = excluded.section_sha256,
            updated_at            = datetime('now')
        """,
        (section_key, last_node_id, last_turn_id, section_sha256),
    )


def _node_stats_and_degrees(conn: sqlite3.Connection) -> dict[int, int]:
    deg: dict[int, int] = {}
    for r in conn.execute("SELECT from_node, to_node FROM edges").fetchall():
        f, t = int(r["from_node"]), int(r["to_node"])
        deg[f] = deg.get(f, 0) + 1
        deg[t] = deg.get(t, 0) + 1
    for r in conn.execute("SELECT node_id, COUNT(*) AS cnt FROM node_provenance GROUP BY node_id").fetchall():
        nid = int(r["node_id"])
        deg[nid] = deg.get(nid, 0) + int(r["cnt"])
    return deg


def _collect_ring_status(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Summarize slice completion & pending counts dynamically across Rings."""
    ring_meta = [
        ("physics_pilot", "Ring 1", "physics"),
        ("lean4_formal", "Ring 2", "formal_math"),
        ("ai_systems", "Ring 3", "ai_systems"),
        ("bio_neuro_psych", "Ring 4A", "bio_neuro_psych"),
        ("philosophy_epistemology", "Ring 4B", "philosophy"),
    ]
    seen_slices: set[str] = set()
    rows = conn.execute(
        """
        SELECT slice_name, status, COUNT(*) AS cnt
        FROM chapter_slices
        GROUP BY slice_name, status
        """
    ).fetchall()
    counts_by_slice: dict[str, dict[str, int]] = {}
    for r in rows:
        counts_by_slice.setdefault(r["slice_name"], {})[r["status"]] = int(r["cnt"])

    node_counts_by_domain: dict[str, dict[str, int]] = {}
    for r in conn.execute(
        "SELECT domain, epistemic_tier, COUNT(*) AS cnt FROM nodes GROUP BY domain, epistemic_tier"
    ).fetchall():
        node_counts_by_domain.setdefault(r["domain"], {})[r["epistemic_tier"]] = int(r["cnt"])

    out: list[dict[str, Any]] = []
    for sname, ring_lbl, dom in ring_meta:
        sc = counts_by_slice.get(sname, {})
        if not sc and sname != "philosophy_epistemology":
            pass
        elif not sc:
            continue
        seen_slices.add(sname)
        proc = sc.get("PROCESSED", 0)
        skip = sc.get("SKIPPED", 0)
        pend = sc.get("PENDING", 0)
        tot = proc + skip + pend
        if tot == 0:
            state = "EMPTY"
        elif pend == 0:
            state = "COMPLETE"
        else:
            state = "IN_PROGRESS"
        out.append(
            {
                "ring": ring_lbl,
                "slice_name": sname,
                "domain": dom,
                "state": state,
                "total": tot,
                "processed": proc,
                "skipped": skip,
                "pending": pend,
                "node_tiers": node_counts_by_domain.get(dom, {}),
            }
        )

    for sname in sorted(counts_by_slice):
        if sname not in seen_slices:
            sc = counts_by_slice[sname]
            proc, skip, pend = sc.get("PROCESSED", 0), sc.get("SKIPPED", 0), sc.get("PENDING", 0)
            out.append(
                {
                    "ring": "Extra",
                    "slice_name": sname,
                    "domain": sname,
                    "state": "COMPLETE" if (proc + skip + pend > 0 and pend == 0) else "IN_PROGRESS",
                    "total": proc + skip + pend,
                    "processed": proc,
                    "skipped": skip,
                    "pending": pend,
                    "node_tiers": node_counts_by_domain.get(sname, {}),
                }
            )
    return out


def _render_keyword_slice(
    conn: sqlite3.Connection,
    bucket: dict[str, Any],
    ouroboros_turns: list[dict[str, Any]],
    archive_conn: sqlite3.Connection | None,
) -> tuple[str, int, int]:
    """Render one full delta-compilable # KEYWORD: slice markdown and return (md, max_nid, max_tid)."""
    theme = bucket["theme"]
    skey = bucket["section_key"]
    nodes = bucket["nodes"]
    nodes_by_id = {int(n["node_id"]): n for n in nodes}
    max_nid = max((int(n["node_id"]) for n in nodes), default=0)

    # Keywords defining this thematic bucket
    bucket_kws: tuple[str, ...] = ()
    for t_name, kws in THEMATIC_BUCKETS:
        if t_name == theme:
            bucket_kws = kws
            break

    # Group nodes by tier
    verified = [n for n in nodes if n["epistemic_tier"] == "EXTERNALLY_VERIFIED"]
    falsified = [n for n in nodes if n["epistemic_tier"] == "FALSIFIED"]
    provisional = [
        n
        for n in nodes
        if n["epistemic_tier"] in ("SIM_CONSISTENT", "CONTESTED", "UNDER_APPEAL", "RAW_CLAIM", "DSL_CONSISTENT")
    ]

    # Pivot mapping for FALSIFIED nodes
    pivot_map: dict[int, dict[str, Any]] = {}
    for pp in bucket.get("pivot_pairs", []):
        fid = int(pp["falsified_node_id"])
        tid = int(pp["reframed_node_id"])
        pivot_map[fid] = {
            "target_id": tid,
            "target": nodes_by_id.get(tid),
            "edge_id": pp["edge_id"],
        }

    # Matching concept_bridges
    all_bridges = conn.execute(
        "SELECT term, alias, COALESCE(structural_pattern, '') AS sp FROM concept_bridges ORDER BY term, alias"
    ).fetchall()
    matched_bridges = [
        dict(b)
        for b in all_bridges
        if any(
            kw in str(b["term"]).lower() or kw in str(b["alias"]).lower() or kw in str(b["sp"]).lower()
            for kw in (bucket_kws or (theme.lower().split()[0],))
        )
    ]

    # Filter Ouroboros turns matching this section key
    matched_ouro = [
        t
        for t in ouroboros_turns
        if classify_text_to_section_key(f"{t.get('user_prompt', '')} {t.get('model_response', '')}") == skey
    ]
    max_tid = max((int(t["id"]) for t in matched_ouro), default=0)
    if max_tid == 0 and ouroboros_turns:
        max_tid = max(int(t["id"]) for t in ouroboros_turns)

    # Also find corpus provenance chunk refs with chat_id / turn_index for nodes in this section
    lines = [
        f"# KEYWORD: {skey}",
        f"Theme: {theme}",
        f"Last Node ID: {max_nid}",
        f"Last Ouroboros Turn ID: {max_tid}",
        (
            f"Tier Counts: EXTERNALLY_VERIFIED={len(verified)} | FALSIFIED={len(falsified)} "
            f"| PROVISIONAL={len(provisional)} | PIVOT_PAIRS={len(pivot_map)}"
        ),
        "",
        "## Verified Canonical Invariants",
    ]
    if verified:
        for n in verified:
            cids = ",".join(str(x) for x in n.get("chunk_ids", [])[:8])
            dsl = f" | `{_compact(n.get('dsl_expr'), 120)}`" if n.get("dsl_expr") else ""
            ver_refs = [
                f"{v['verification_scope']}:{v['benchmark_ref'] or v['external_ref']}"
                for v in n.get("verifications", [])
                if v.get("passed")
            ]
            vstr = f" | Ref: {_compact('; '.join(ver_refs), 110)}" if ver_refs else ""
            lines.append(
                f"- **[`#{n['node_id']}` | `{n['domain']}` | chunks:{cids}]** {n['summary']}{dsl}{vstr}"
            )
    else:
        lines.append("- *(No EXTERNALLY_VERIFIED nodes in this section yet.)*")

    lines.extend(["", "## FALSIFIED Dead Ends -> pivoted_to Replacements"])
    if falsified:
        for fn in falsified:
            fid = int(fn["node_id"])
            pv = pivot_map.get(fid)
            if pv and pv.get("target"):
                tn = pv["target"]
                lines.append(
                    f"- **[FALSIFIED `#{fid}`]** {fn['summary']} "
                    f"=> **`pivoted_to` `#{tn['node_id']}`**: {tn['summary']}"
                )
            else:
                lines.append(f"- **[FALSIFIED `#{fid}`]** {fn['summary']} => *(pending pivot resolution)*")
    else:
        lines.append("- *(No FALSIFIED nodes in this section.)*")

    lines.extend(["", "## Provisional Claims & Active Research Branches"])
    if provisional:
        for pn in provisional:
            br = conn.execute(
                "SELECT branch_id, total_hops, hops_since_novelty, max_dry_hops, status "
                "FROM research_branches WHERE root_node_id = ? ORDER BY branch_id DESC LIMIT 1",
                (pn["node_id"],),
            ).fetchone()
            binfo = (
                f" | branch=#{br['branch_id']} {br['status']} dry={br['hops_since_novelty']}/{br['max_dry_hops']}"
                if br
                else ""
            )
            lines.append(f"- **[`#{pn['node_id']}` | `{pn['epistemic_tier']}`{binfo}]** {pn['summary']}")
    else:
        lines.append("- *(No provisional nodes in this section.)*")

    lines.extend(["", "## Vocabulary-Drift Concept Bridges"])
    if matched_bridges:
        for b in matched_bridges[:30]:
            pat = f" ({b['sp']})" if b["sp"] else ""
            lines.append(f"- `{b['term']}` <-> `{b['alias']}`{pat}")
    else:
        lines.append("- *(No direct bucket bridges mapped yet.)*")

    if matched_ouro:
        lines.extend(["", "## Linked Ouroboros Archive Syntheses"])
        for t in matched_ouro[-8:]:
            lines.append(
                f"- [turn_rowid={t['id']} | chat_id={t['chat_id']} | turn_index={t['turn_index']} | "
                f"turn_id={t.get('turn_id') or '-'} | parent_turn_id={t.get('parent_turn_id') or '-'} | "
                f"sha256={(t.get('sha256') or '-')[:12]}]: **{_compact(t.get('user_prompt'), 100)}** -> "
                f"{_compact(t.get('model_response'), 180)}"
            )

    has_ingested_tbl = bool(
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='ingested_artifacts'"
        ).fetchone()
    )
    if has_ingested_tbl:
        ing_rows = conn.execute(
            """
            SELECT artifact_id, source_path, source_tag, chat_id, file_sha256,
                   chunk_count, first_chunk_id, last_chunk_id
            FROM ingested_artifacts
            WHERE section_key = ?
            ORDER BY artifact_id DESC
            LIMIT 10
            """,
            (skey,),
        ).fetchall()
        if ing_rows:
            lines.extend(["", "## Unverified Ingested Artifacts (`RAW_CLAIM` / `PROVENANCE_LOG`)"])
            for ar in ing_rows:
                lines.append(
                    f"- [artifact#{ar['artifact_id']} | RAW_CLAIM | tag={ar['source_tag']} | "
                    f"chat_id={ar['chat_id'] or '-'} | chunks={ar['first_chunk_id']}..{ar['last_chunk_id']} "
                    f"({ar['chunk_count']}) | sha256={str(ar['file_sha256'])[:12]}]: {ar['source_path']}"
                )

    md = "\n".join(lines).rstrip() + "\n"
    return md, max_nid, max_tid


def _render_core_digest(
    conn: sqlite3.Connection,
    outline: dict[str, Any],
    slices_dir: Path,
    archive_status: dict[str, Any],
) -> tuple[str, int]:
    """Render compact, prompt-cacheable chapters/core_digest.md targeting ~15-30 KB."""
    rings = _collect_ring_status(conn)
    deg = _node_stats_and_degrees(conn)
    total_chunks = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    total_bridges = conn.execute("SELECT COUNT(*) FROM concept_bridges").fetchone()[0]
    active_branches = conn.execute("SELECT COUNT(*) FROM research_branches WHERE status = 'ACTIVE'").fetchone()[0]
    halted_branches = conn.execute("SELECT COUNT(*) FROM research_branches WHERE status = 'HALTED_NOVELTY'").fetchone()[0]
    converged_branches = conn.execute("SELECT COUNT(*) FROM research_branches WHERE status = 'CONVERGED'").fetchone()[0]

    tier_totals = {
        r["epistemic_tier"]: int(r["cnt"])
        for r in conn.execute("SELECT epistemic_tier, COUNT(*) AS cnt FROM nodes GROUP BY epistemic_tier").fetchall()
    }
    max_node_id = conn.execute("SELECT COALESCE(MAX(node_id), 0) FROM nodes").fetchone()[0]

    # Build anchor map & per-theme ranked pools
    themes = outline["themes"]
    theme_verified_pools: list[list[dict[str, Any]]] = []
    theme_pivot_pools: list[list[tuple[dict[str, Any], dict[str, Any] | None]]] = []
    provisional_nodes: list[dict[str, Any]] = []
    anchor_lines: list[str] = []

    all_bridges = conn.execute(
        "SELECT term, alias FROM concept_bridges ORDER BY rowid DESC"
    ).fetchall()

    # Load all benchmarks for fast lookup
    bench_by_nid: dict[int, str] = {}
    for r in conn.execute(
        "SELECT node_id, benchmark_ref FROM node_verifications WHERE passed = 1 AND benchmark_ref IS NOT NULL ORDER BY verification_id DESC"
    ).fetchall():
        nid = int(r["node_id"])
        if nid not in bench_by_nid:
            bench_by_nid[nid] = str(r["benchmark_ref"])

    for bucket in themes:
        skey = bucket["section_key"]
        th_name = bucket["theme"]
        nodes = bucket["nodes"]
        nodes_by_id = {int(n["node_id"]): n for n in nodes}
        pivot_target_ids = {int(pp["falsified_node_id"]): int(pp["reframed_node_id"]) for pp in bucket.get("pivot_pairs", [])}
        reframed_ids = set(pivot_target_ids.values())

        v_list = [n for n in nodes if n["epistemic_tier"] == "EXTERNALLY_VERIFIED"]
        f_list = [n for n in nodes if n["epistemic_tier"] == "FALSIFIED"]
        p_list = [
            n
            for n in nodes
            if n["epistemic_tier"] in ("SIM_CONSISTENT", "CONTESTED", "UNDER_APPEAL", "RAW_CLAIM", "DSL_CONSISTENT")
        ]
        provisional_nodes.extend(p_list)

        # Rank verified nodes: non-reframed canonical first, then highest connectivity degree & provenance breadth
        v_list.sort(
            key=lambda n: (
                0 if int(n["node_id"]) not in reframed_ids else 1,
                -deg.get(int(n["node_id"]), 0),
                -int(n["node_id"]),
            )
        )
        theme_verified_pools.append(v_list)

        f_pairs = []
        for fn in sorted(f_list, key=lambda n: (-deg.get(int(n["node_id"]), 0), -int(n["node_id"]))):
            tid = pivot_target_ids.get(int(fn["node_id"]))
            f_pairs.append((fn, nodes_by_id.get(tid) if tid else None))
        theme_pivot_pools.append(f_pairs)

        b_kws: tuple[str, ...] = ()
        for tname, kws in THEMATIC_BUCKETS:
            if tname == th_name:
                b_kws = kws
                break
        sample_terms = []
        for b in all_bridges:
            bt = f"{b['term']}<->{b['alias']}"
            if any(kw in bt.lower() for kw in b_kws):
                if bt not in sample_terms:
                    sample_terms.append(bt)
            if len(sample_terms) >= 3:
                break
        b_note = f" | bridges: {', '.join(sample_terms)}" if sample_terms else ""
        s_max = max((int(n["node_id"]) for n in nodes), default=0)
        rel_slice = f"chapters/digest_slices/{skey}.md"
        anchor_lines.append(
            f"- `# KEYWORD: {skey}` — *{th_name}* (`V={len(v_list)}`, `F={len(f_list)}`, `P={len(p_list)}`, "
            f"max_node=`#{s_max}`, slice=`{rel_slice}`){b_note}"
        )

    # Interleave verified invariants round-robin across themes so all domains stay balanced
    interleaved_verified: list[dict[str, Any]] = []
    if theme_verified_pools:
        max_len = max(len(p) for p in theme_verified_pools)
        for i in range(max_len):
            for pool in theme_verified_pools:
                if i < len(pool):
                    interleaved_verified.append(pool[i])

    interleaved_pivots: list[tuple[dict[str, Any], dict[str, Any] | None]] = []
    if theme_pivot_pools:
        max_plen = max(len(p) for p in theme_pivot_pools)
        for i in range(max_plen):
            for pool in theme_pivot_pools:
                if i < len(pool):
                    interleaved_pivots.append(pool[i])

    arch_line = (
        f"connected (`{archive_status.get('conversations', 0)}` convs, "
        f"`{archive_status.get('turns', 0)}` turns, last_ouroboros_turn_id=`{archive_status.get('max_ouroboros_turn_id', 0)}`)"
        if archive_status.get("available")
        else f"offline/sandbox (`{archive_status.get('reason', 'ro_unavailable')}`)"
    )

    header_lines = [
        "# Epistemic Corpus Kernel — Pinned Core Digest (`core_digest.md`)",
        "",
        "*(Prompt-cacheable core layer compiled from `data/corpus.db` `digest_state` + `nodes`/`edges`/`chapter_slices`. "
        "Query per-tick dynamic slices via `scripts/compile_digest.py hydrate`.)*",
        "",
        "## 1. Active Ring Status & Global Telemetry",
        "",
        f"- **Corpus State:** `{total_chunks:,}` chunks | `{outline['total_nodes']}` nodes "
        f"(`EXTERNALLY_VERIFIED={tier_totals.get('EXTERNALLY_VERIFIED', 0)}`, "
        f"`FALSIFIED={tier_totals.get('FALSIFIED', 0)}`, "
        f"`SIM_CONSISTENT={tier_totals.get('SIM_CONSISTENT', 0)}`, "
        f"`CONTESTED={tier_totals.get('CONTESTED', 0)}`, "
        f"`UNDER_APPEAL={tier_totals.get('UNDER_APPEAL', 0)}`, "
        f"`RAW_CLAIM={tier_totals.get('RAW_CLAIM', 0)}`) | `{outline['total_edges']}` directed edges | "
        f"`{total_bridges}` `concept_bridges`",
        f"- **Branches (`max_dry_hops = 3`):** `CONVERGED={converged_branches}` | `ACTIVE={active_branches}` | `HALTED_NOVELTY={halted_branches}`",
        f"- **Archive Link (`archive.db` RO):** {arch_line}",
        "",
        "| Ring | Slice (`chapter_slices`) | Status | Processed | Skipped | Pending | Verified | Falsified |",
        "| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: |",
    ]
    for rg in rings:
        nt = rg["node_tiers"]
        header_lines.append(
            f"| {rg['ring']} | `{rg['slice_name']}` | **{rg['state']}** | "
            f"{rg['processed']} | {rg['skipped']} | {rg['pending']} | "
            f"{nt.get('EXTERNALLY_VERIFIED', 0)} | {nt.get('FALSIFIED', 0)} |"
        )

    header_lines.extend(["", "## 2. Top-Level `# KEYWORD:` Anchor Map", ""])
    header_lines.extend(anchor_lines)

    provisional_lines: list[str] = ["", "## 3. Active Provisional Watchlist (`SIM_CONSISTENT` / `CONTESTED` / `UNDER_APPEAL` / Open `RAW_CLAIM`)", ""]
    sim_only = [p for p in provisional_nodes if p["epistemic_tier"] == "SIM_CONSISTENT"]
    contested_only = [p for p in provisional_nodes if p["epistemic_tier"] in ("CONTESTED", "UNDER_APPEAL")]
    raw_only = [p for p in provisional_nodes if p["epistemic_tier"] in ("RAW_CLAIM", "DSL_CONSISTENT")]
    for p in sim_only[:12]:
        provisional_lines.append(f"- [`#{p['node_id']}` | `SIM_CONSISTENT` | `{p['domain']}`]: {_compact(p['summary'], 125)}")
    if len(sim_only) > 12:
        provisional_lines.append(
            f"- *Additional `SIM_CONSISTENT` watchlist nodes:* {len(sim_only) - 12} more (total `{len(sim_only)}`, including F2.2 provisional re-tiered items awaiting primary DOI/PMID/arXiv/HTTPS citations)."
        )
    if contested_only:
        c_preview = ", ".join(f"#{p['node_id']}" for p in contested_only[:8])
        provisional_lines.append(
            f"- *`CONTESTED` / `UNDER_APPEAL` queue:* {len(contested_only)} node(s) awaiting primary-source adjudication (first 8: {c_preview})."
        )
    if raw_only:
        raw_preview = ", ".join(f"#{p['node_id']}" for p in raw_only[:5])
        provisional_lines.append(
            f"- *Open `RAW_CLAIM` / `DSL_CONSISTENT` queue:* {len(raw_only)} node(s) awaiting Step B/C falsification "
            f"(first 5: {raw_preview})."
        )
    if not sim_only and not contested_only and not raw_only:
        provisional_lines.append("- *(All branches resolved; zero provisional items pending.)*")

    base_text = "\n".join(header_lines + provisional_lines)
    base_bytes = len(base_text.encode("utf-8"))

    # Reserve budget cleanly inside [CORE_MIN_BYTES, CORE_MAX_BYTES] (targeting ~CORE_TARGET_BYTES)
    remaining_for_lists = max(3000, CORE_TARGET_BYTES - base_bytes)
    inv_budget = int(remaining_for_lists * 0.56)
    piv_budget = remaining_for_lists - inv_budget

    inv_lines: list[str] = ["", "## 4. Verified Canonical Invariants (`EXTERNALLY_VERIFIED` Sample Spine)", ""]
    inv_used = len("\n".join(inv_lines).encode("utf-8"))
    for n in interleaved_verified:
        nid = int(n["node_id"])
        bench = bench_by_nid.get(nid, "")
        bench_s = f" [{_compact(bench, 48)}]" if bench else ""
        entry = f"- [`#{nid}`|`{n['domain']}`]: {_compact(n['summary'], 125)}{bench_s}"
        eb = len((entry + "\n").encode("utf-8"))
        if inv_used + eb > inv_budget and len(inv_lines) > 10:
            break
        inv_lines.append(entry)
        inv_used += eb

    piv_lines: list[str] = ["", "## 5. Active `FALSIFIED` Dead Ends Paired with `pivoted_to` Replacements", ""]
    piv_used = len("\n".join(piv_lines).encode("utf-8"))
    for fn, tn in interleaved_pivots:
        fid = int(fn["node_id"])
        tid = int(tn["node_id"]) if tn else None
        piv_txt = _compact(tn["summary"], 105) if tn else "pending pivot"
        entry = f"- [`#{fid}->#{tid}`|`{fn['domain']}`]: NOT `{_compact(fn['summary'], 82)}` => USE `{piv_txt}`"
        eb = len((entry + "\n").encode("utf-8"))
        if piv_used + eb > piv_budget and len(piv_lines) > 10:
            break
        piv_lines.append(entry)
        piv_used += eb

    full_lines = header_lines + provisional_lines + inv_lines + piv_lines
    rendered = "\n".join(full_lines).rstrip() + "\n"

    # Hard upper cap safety (< 30 KB)
    while len(rendered.encode("utf-8")) > CORE_MAX_BYTES - 128 and (len(piv_lines) > 5 or len(inv_lines) > 5):
        if len(piv_lines) >= len(inv_lines) and len(piv_lines) > 5:
            piv_lines.pop()
        elif len(inv_lines) > 5:
            inv_lines.pop()
        rendered = "\n".join(header_lines + provisional_lines + inv_lines + piv_lines).rstrip() + "\n"

    return rendered, int(max_node_id)


def compile_digest(
    conn: sqlite3.Connection,
    *,
    archive_db: Path | str | None = None,
    core_path: Path = DEFAULT_CORE_DIGEST_PATH,
    slices_dir: Path = DEFAULT_SLICES_DIR,
    only_section_keys: set[str] | None = None,
    force_all: bool = False,
    sync_ouroboros: bool = True,
    ingest_ouroboros: bool = True,
) -> dict[str, Any]:
    """Compile or delta-update # KEYWORD: slices and core_digest.md."""
    ensure_digest_state_table(conn)
    slices_dir.mkdir(parents=True, exist_ok=True)
    core_path.parent.mkdir(parents=True, exist_ok=True)

    archive_conn, arch_err = open_archive_ro(archive_db)
    archive_status: dict[str, Any] = {"available": False, "reason": arch_err or "unavailable"}
    all_ouroboros: list[dict[str, Any]] = []
    ouro_inserted = 0
    new_ouro_keys: set[str] = set()

    try:
        if archive_conn is not None:
            try:
                conv_cnt = archive_conn.execute("SELECT COUNT(*) FROM conversations").fetchone()[0]
                turn_cnt = archive_conn.execute("SELECT COUNT(*) FROM turns").fetchone()[0]
                all_ouroboros = _fetch_ouroboros_turns(archive_conn, since_turn_id=0)
                max_ouro_id = max((int(t["id"]) for t in all_ouroboros), default=0)
                archive_status = {
                    "available": True,
                    "conversations": int(conv_cnt),
                    "turns": int(turn_cnt),
                    "ouroboros_turns": len(all_ouroboros),
                    "max_ouroboros_turn_id": max_ouro_id,
                }
                if sync_ouroboros:
                    prev_ouro = _get_digest_row(conn, OUROBOROS_SECTION_KEY)
                    prev_tid = int(prev_ouro["last_compiled_turn_id"] or 0) if prev_ouro else 0
                    new_turns = [t for t in all_ouroboros if int(t["id"]) > prev_tid]
                    if new_turns:
                        if ingest_ouroboros:
                            ouro_inserted = _ingest_new_ouroboros_into_corpus(conn, new_turns)
                        for nt in new_turns:
                            skey = classify_text_to_section_key(
                                f"{nt.get('user_prompt', '')} {nt.get('model_response', '')}"
                            )
                            new_ouro_keys.add(skey)
            except sqlite3.Error as exc:
                archive_status = {"available": False, "reason": str(exc)}

        outline = build_thematic_outline(conn)
        buckets_by_key = {b["section_key"]: b for b in outline["themes"]}
        ouro_keys = {
            classify_text_to_section_key(f"{t.get('user_prompt', '')} {t.get('model_response', '')}")
            for t in all_ouroboros
        }
        all_active_keys = list(buckets_by_key.keys()) + [
            k for k in sorted(ouro_keys | new_ouro_keys | (only_section_keys or set())) if k not in buckets_by_key
        ]
        recompiled_sections: list[str] = []
        skipped_unchanged: list[str] = []

        target_keys: set[str] | None = None
        if only_section_keys is not None:
            target_keys = set(only_section_keys) | new_ouro_keys

        # Ensure every active canonical or Ouroboros-linked section compiles cleanly
        for skey in all_active_keys:
            bucket = buckets_by_key.get(
                skey,
                {
                    "theme": SECTION_KEY_TO_THEME.get(skey, skey),
                    "section_key": skey,
                    "nodes": [],
                    "pivot_pairs": [],
                    "internal_edges": [],
                    "cross_theme_edges": [],
                },
            )
            slice_file = slices_dir / f"{skey}.md"
            prev_row = _get_digest_row(conn, skey)

            if target_keys is not None and not force_all and skey not in target_keys:
                if prev_row is not None and slice_file.exists():
                    skipped_unchanged.append(skey)
                    continue

            md, max_nid, max_tid = _render_keyword_slice(conn, bucket, all_ouroboros, archive_conn)
            new_sha = _sha256_text(md)

            if max_tid == 0 and prev_row and prev_row.get("last_compiled_turn_id"):
                max_tid = int(prev_row["last_compiled_turn_id"])

            if (
                not force_all
                and prev_row is not None
                and prev_row.get("section_sha256") == new_sha
                and slice_file.exists()
            ):
                skipped_unchanged.append(skey)
                continue

            slice_file.write_text(md, encoding="utf-8")
            _upsert_digest_state(conn, skey, max_nid, max_tid, new_sha)
            recompiled_sections.append(skey)

        # Update Ouroboros watermark if archive.db provided higher turn_id
        max_ouro_seen = archive_status.get("max_ouroboros_turn_id", 0)
        if archive_conn is not None and (max_ouro_seen > 0 or force_all):
            ouro_sig = _sha256_text(
                json.dumps(
                    [(t["id"], t.get("turn_index"), t.get("sha256")) for t in all_ouroboros],
                    sort_keys=True,
                )
            )
            prev_ouro = _get_digest_row(conn, OUROBOROS_SECTION_KEY)
            if prev_ouro is None or prev_ouro.get("section_sha256") != ouro_sig or force_all:
                max_global_nid = conn.execute("SELECT COALESCE(MAX(node_id), 0) FROM nodes").fetchone()[0]
                _upsert_digest_state(conn, OUROBOROS_SECTION_KEY, int(max_global_nid), int(max_ouro_seen), ouro_sig)

        # Render core_digest.md & check SHA-256 delta
        core_md, max_global_nid = _render_core_digest(conn, outline, slices_dir, archive_status)
        core_sha = _sha256_text(core_md)
        prev_core = _get_digest_row(conn, CORE_SECTION_KEY)
        core_refreshed = False
        if (
            force_all
            or prev_core is None
            or prev_core.get("section_sha256") != core_sha
            or not core_path.exists()
        ):
            core_path.write_text(core_md, encoding="utf-8")
            _upsert_digest_state(
                conn,
                CORE_SECTION_KEY,
                max_global_nid,
                int(max_ouro_seen or (prev_core["last_compiled_turn_id"] if prev_core and prev_core.get("last_compiled_turn_id") else 0)),
                core_sha,
            )
            core_refreshed = True

        conn.commit()
        return {
            "core_digest_path": str(core_path),
            "core_digest_bytes": len(core_md.encode("utf-8")),
            "core_digest_tokens": estimate_tokens(core_md),
            "core_digest_sha256": core_sha,
            "core_refreshed": core_refreshed,
            "recompiled_sections": recompiled_sections,
            "skipped_unchanged_sections": skipped_unchanged,
            "ouroboros_chunks_ingested": ouro_inserted,
            "archive_status": archive_status,
        }
    finally:
        if archive_conn is not None:
            archive_conn.close()


def affected_sections_for_nodes(conn: sqlite3.Connection, node_ids: list[int]) -> set[str]:
    """Determine which # KEYWORD: section_keys own the given node_ids."""
    if not node_ids:
        return set()
    target_set = {int(n) for n in node_ids}
    outline = build_thematic_outline(conn)
    affected: set[str] = set()
    for bucket in outline["themes"]:
        bucket_nids = {int(n["node_id"]) for n in bucket["nodes"]}
        if bucket_nids & target_set:
            affected.add(bucket["section_key"])
    return affected


def on_falsifier_commit(
    conn: sqlite3.Connection,
    committed_node_ids: list[int],
    *,
    archive_db: Path | str | None = None,
    core_path: Path = DEFAULT_CORE_DIGEST_PATH,
    slices_dir: Path = DEFAULT_SLICES_DIR,
) -> dict[str, Any]:
    """Stage 3 hook: recompile ONLY affected # KEYWORD: slices + refresh core_digest.md if changed."""
    affected_keys = affected_sections_for_nodes(conn, committed_node_ids)
    if not affected_keys:
        # Check fallback if node_ids weren't yet found in outline
        return {"status": "no_affected_sections", "recompiled_sections": [], "core_refreshed": False}
    return compile_digest(
        conn,
        archive_db=archive_db,
        core_path=core_path,
        slices_dir=slices_dir,
        only_section_keys=affected_keys,
        force_all=False,
        sync_ouroboros=True,
    )


def sync_ouroboros_deltas(
    conn: sqlite3.Connection,
    *,
    archive_db: Path | str | None = None,
    core_path: Path = DEFAULT_CORE_DIGEST_PATH,
    slices_dir: Path = DEFAULT_SLICES_DIR,
    ingest_to_corpus: bool = True,
) -> dict[str, Any]:
    """Stage 3 hook: check archive.db levi_recursive_memory for new turns and delta-recompile."""
    ensure_digest_state_table(conn)
    archive_conn, arch_err = open_archive_ro(archive_db)
    if archive_conn is None:
        return {"status": "archive_unavailable", "reason": arch_err, "new_turns": 0, "recompiled_sections": []}
    try:
        prev_ouro = _get_digest_row(conn, OUROBOROS_SECTION_KEY)
        since_tid = int(prev_ouro["last_compiled_turn_id"] or 0) if prev_ouro else 0
        new_turns = _fetch_ouroboros_turns(archive_conn, since_turn_id=since_tid)
        if not new_turns:
            return {"status": "up_to_date", "last_compiled_turn_id": since_tid, "new_turns": 0, "recompiled_sections": []}
        affected_keys = {
            classify_text_to_section_key(f"{t.get('user_prompt', '')} {t.get('model_response', '')}")
            for t in new_turns
        }
    finally:
        archive_conn.close()

    res = compile_digest(
        conn,
        archive_db=archive_db,
        core_path=core_path,
        slices_dir=slices_dir,
        only_section_keys=affected_keys,
        force_all=False,
        sync_ouroboros=True,
        ingest_ouroboros=ingest_to_corpus,
    )
    res["status"] = "recompiled"
    res["new_turns"] = len(new_turns)
    return res


def hydrate_pre_tick(
    conn: sqlite3.Connection,
    *,
    domain: str,
    chunks: list[dict[str, Any]] | None = None,
    query_text: str | None = None,
    archive_db: Path | str | None = None,
    core_path: Path = DEFAULT_CORE_DIGEST_PATH,
    slices_dir: Path = DEFAULT_SLICES_DIR,
    token_budget: int = 2200,
    top_k_chunks: int = 8,
    top_k_nodes: int = 10,
    sync_deltas_first: bool = True,
) -> dict[str, Any]:
    """Stage 2 + Stage 4: Pre-tick hydration packet assembly before Lifter / Scientist / Falsifier."""
    ensure_digest_state_table(conn)
    delta_report: dict[str, Any] | None = None
    if sync_deltas_first:
        # Compile core_digest if missing, and auto-sync any Ouroboros turns or uncommitted node deltas
        if not core_path.exists() or _get_digest_row(conn, CORE_SECTION_KEY) is None:
            delta_report = compile_digest(conn, archive_db=archive_db, core_path=core_path, slices_dir=slices_dir)
        else:
            delta_report = sync_ouroboros_deltas(conn, archive_db=archive_db, core_path=core_path, slices_dir=slices_dir)

    batch_cids: set[int] = set()
    query_pieces: list[str] = []
    cleaned_user_query = filter_query_text(query_text or "")
    if cleaned_user_query:
        query_pieces.append(cleaned_user_query)
    for c in chunks or []:
        if c.get("chunk_id") is not None:
            batch_cids.add(int(c["chunk_id"]))
        clean_ref = strip_metadata_paths(str(c.get("source_ref", "")))
        query_pieces.append(f"{clean_ref} {str(c.get('content', ''))[:900]}")

    combined_query = "\n".join(query_pieces).strip() or domain
    # Derive concise, stopword-clean domain terms so path/metadata noise doesn't dilute recall
    kws = extract_query_keywords(combined_query, max_terms=14)
    if cleaned_user_query:
        uq_low = {t.lower() for t in cleaned_user_query.split()}
        extra_kws = [k for k in kws if k.lower() not in uq_low]
        focused_query = " ".join([cleaned_user_query] + extra_kws).strip()
    else:
        focused_query = " ".join(kws).strip() or filter_query_text(domain) or domain

    archive_conn, arch_err = open_archive_ro(archive_db)
    try:
        packet = retrieve_hybrid_and_gated(
            conn,
            focused_query,
            domain=domain,
            archive_conn=archive_conn,
            exclude_chunk_ids=batch_cids,
            top_k_chunks=top_k_chunks,
            top_k_nodes=top_k_nodes,
            token_budget=token_budget,
            expand_bridges=True,
            backtrack_parents=True,
        )
    finally:
        if archive_conn is not None:
            archive_conn.close()

    # Load compact core header (active ring status + # KEYWORD: anchor map) or full core path info
    core_text = core_path.read_text(encoding="utf-8") if core_path.exists() else ""
    target_section_key = classify_text_to_section_key(combined_query)
    slice_file = slices_dir / f"{target_section_key}.md"

    return {
        "domain": domain,
        "target_section_key": target_section_key,
        "target_slice_path": str(slice_file) if slice_file.exists() else None,
        "core_digest_path": str(core_path),
        "core_digest_bytes": len(core_text.encode("utf-8")),
        "core_digest_tokens": estimate_tokens(core_text),
        "core_digest_sha256": _sha256_text(core_text) if core_text else None,
        "archive_db_status": "connected" if arch_err is None else arch_err,
        "delta_sync": delta_report,
        "focused_query": focused_query,
        "packet": packet,
    }


def extract_core_anchor_block(core_text: str) -> str:
    """Return Ring Status + # KEYWORD: Anchor Map section from core_digest.md (~4 KB ultra-compact)."""
    if not core_text:
        return ""
    marker = "## 3. Active Provisional Watchlist"
    idx = core_text.find(marker)
    if idx != -1:
        return core_text[:idx].strip()
    return core_text[:4000].strip()


def main() -> None:
    parser = argparse.ArgumentParser(description="Structured Digest Compiler & Arachne/Corpus Hydrator")
    sub = parser.add_subparsers(dest="cmd", required=True)

    for cname in ("compile", "delta"):
        p = sub.add_parser(cname, help="Compile or delta-update core_digest.md and # KEYWORD: slices")
        p.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
        p.add_argument("--archive-db", type=Path, default=None)
        p.add_argument("--core-out", type=Path, default=None)
        p.add_argument("--slices-dir", type=Path, default=None)
        p.add_argument("--force", action="store_true", help="Force recompile all sections")
        p.add_argument("--nodes", default="", help="Comma-separated affected node_ids (for targeted delta)")

    p_sync = sub.add_parser("sync-ouroboros", help="Check archive.db levi_recursive_memory for new turns & recompile deltas")
    p_sync.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    p_sync.add_argument("--archive-db", type=Path, default=None)
    p_sync.add_argument("--core-out", type=Path, default=None)
    p_sync.add_argument("--slices-dir", type=Path, default=None)
    p_sync.add_argument("--no-ingest", action="store_true")

    p_hyd = sub.add_parser("hydrate", help="Stage 2+4: Assemble pre-tick working-memory packet")
    p_hyd.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    p_hyd.add_argument("--archive-db", type=Path, default=None)
    p_hyd.add_argument("--domain", default="bio_neuro_psych")
    p_hyd.add_argument("--query", default="")
    p_hyd.add_argument("--chunk-ids", default="")
    p_hyd.add_argument("--token-budget", type=int, default=2200)
    p_hyd.add_argument("--core-out", type=Path, default=None)
    p_hyd.add_argument("--slices-dir", type=Path, default=None)

    p_st = sub.add_parser("status", help="Inspect digest_state watermarks in corpus.db")
    p_st.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)

    args = parser.parse_args()
    default_core, default_slices = resolve_digest_targets(args.db)
    core_out = getattr(args, "core_out", None) or default_core
    slices_dir = getattr(args, "slices_dir", None) or default_slices
    init_db(args.db)
    conn = get_connection(args.db)
    try:
        if args.cmd in ("compile", "delta"):
            keys = None
            if args.nodes:
                nids = [int(x) for x in args.nodes.split(",") if x.strip()]
                keys = affected_sections_for_nodes(conn, nids)
            res = compile_digest(
                conn,
                archive_db=args.archive_db,
                core_path=core_out,
                slices_dir=slices_dir,
                only_section_keys=keys,
                force_all=bool(args.force or args.cmd == "compile"),
            )
            print(json.dumps(res, indent=2))
        elif args.cmd == "sync-ouroboros":
            res = sync_ouroboros_deltas(
                conn,
                archive_db=args.archive_db,
                core_path=core_out,
                slices_dir=slices_dir,
                ingest_to_corpus=not args.no_ingest,
            )
            print(json.dumps(res, indent=2))
        elif args.cmd == "hydrate":
            chunks: list[dict[str, Any]] = []
            if args.chunk_ids:
                cids = [int(x) for x in args.chunk_ids.split(",") if x.strip()]
                rows = conn.execute(
                    f"SELECT chunk_id, source_ref, content FROM chunks WHERE chunk_id IN ({','.join('?' for _ in cids)})",
                    tuple(cids),
                ).fetchall()
                chunks = [dict(r) for r in rows]
            res = hydrate_pre_tick(
                conn,
                domain=args.domain,
                chunks=chunks or None,
                query_text=args.query or None,
                archive_db=args.archive_db,
                core_path=core_out,
                slices_dir=slices_dir,
                token_budget=args.token_budget,
            )
            print(json.dumps(res, indent=2, ensure_ascii=False))
        elif args.cmd == "status":
            ensure_digest_state_table(conn)
            rows = [dict(r) for r in conn.execute("SELECT * FROM digest_state ORDER BY section_key").fetchall()]
            print(json.dumps({"digest_state_count": len(rows), "rows": rows}, indent=2))
    finally:
        conn.close()


if __name__ == "__main__":
    main()
