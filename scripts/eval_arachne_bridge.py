#!/usr/bin/env python3
"""Mutual Evaluation Suite: Arachne Recall Layer <-> corpus.db Epistemic Kernel.

Evaluates Section 4 Binding Protocol Criteria ("Two Halves of One Coin"):
  1. Hydration & Compression (Arachne):
     - Pinned core_digest.md stays in 15-30 KB range.
     - Pre-tick dynamic working-memory packets stay strictly <= token_budget.
     - Retrieved items preserve full provenance (chunk_id, chat_id, turn_index, turn_id, parent_turn_id, sha256).
  2. Epistemic Rigor (corpus.db):
     - Stage 4 concept_bridges expansion surfaces historical vocabulary-drift turns.
     - Rule 2 Truth Filter suppresses FALSIFIED raw hits from positive context and emits
       explicit [NEGATIVE CONSTRAINT] paired 1:1 with pivoted_to replacements.
     - Dry-hop caps (max_dry_hops = 3) and delta watermarks (digest_state) remain invariant.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from benchmark_ab import TEST_QUESTIONS, retrieve_arm_a
from compile_digest import (
    DEFAULT_CORE_DIGEST_PATH,
    DEFAULT_SLICES_DIR,
    compile_digest,
    hydrate_pre_tick,
    resolve_digest_targets,
)
from db_utils import DEFAULT_DB_PATH, WORKSPACE_ROOT, estimate_tokens, get_connection, init_db

DEFAULT_EVAL_JSON = WORKSPACE_ROOT / "data" / "arachne_bridge_eval.json"
DEFAULT_EVAL_REPORT = WORKSPACE_ROOT / "chapters" / "arachne_bridge_evaluation.md"

VOCAB_DRIFT_PROBES = [
    {
        "label": "Transformer Stateless Pass <-> Legacy Mousetrap Metaphor",
        "query": "stateless forward pass harness outer feedback loop",
        "expected_bridge_tokens": ["mousetrap", "feedback loop", "stateless"],
    },
    {
        "label": "PDA Intolerance of Uncertainty <-> Early ACP / DAT Framing",
        "query": "pathological demand avoidance intolerance of uncertainty",
        "expected_bridge_tokens": ["anti-conformance", "acp", "dat", "causal entropy"],
    },
    {
        "label": "Optical Refraction Phase Superposition <-> Early Interference Notes",
        "query": "refraction phase velocity c/n in water",
        "expected_bridge_tokens": ["phase superposition"],
    },
    {
        "label": "Information Entropy <-> Compression / Landauer Bounds",
        "query": "entropy compression lossless deduplication",
        "expected_bridge_tokens": ["lossy", "compression", "landauer"],
    },
]


def run_evaluation(
    *,
    db_path: Path = DEFAULT_DB_PATH,
    archive_db: Path | None = None,
    token_budget: int = 2200,
    report_out: Path = DEFAULT_EVAL_REPORT,
    json_out: Path = DEFAULT_EVAL_JSON,
) -> dict[str, Any]:
    init_db(db_path)
    conn = get_connection(db_path)
    core_path, slices_dir = resolve_digest_targets(db_path)
    try:
        # 1. Stage 1 & 3: Compile & verify delta idempotency
        t0 = time.perf_counter()
        comp_res = compile_digest(
            conn,
            archive_db=archive_db,
            core_path=core_path,
            slices_dir=slices_dir,
            force_all=False,
        )
        t_comp = time.perf_counter() - t0
        delta_noop = compile_digest(
            conn,
            archive_db=archive_db,
            core_path=core_path,
            slices_dir=slices_dir,
            force_all=False,
        )

        # 2. Evaluate all 20 benchmark questions under Hydrated Packet vs Raw RAG Arm A
        q_rows: list[dict[str, Any]] = []
        raw_total_tok = 0
        hyd_total_tok = 0
        latencies_ms: list[float] = []
        provenance_hits = 0
        full_archive_topo_hits = 0
        pitfall_total = 0
        pitfall_blocked = 0
        within_budget_count = 0

        for q in TEST_QUESTIONS:
            _, raw_tok = retrieve_arm_a(conn, q["question"])
            ts0 = time.perf_counter()
            hyd = hydrate_pre_tick(
                conn,
                domain=q["domain"],
                query_text=q["question"],
                archive_db=archive_db,
                core_path=core_path,
                slices_dir=slices_dir,
                token_budget=token_budget,
                sync_deltas_first=False,
            )
            dt_ms = (time.perf_counter() - ts0) * 1000.0
            latencies_ms.append(dt_ms)

            pkt = hyd["packet"]
            ptok = int(pkt["estimated_tokens"])
            raw_total_tok += raw_tok
            hyd_total_tok += ptok
            if ptok <= token_budget:
                within_budget_count += 1

            # Check provenance preservation across dynamic_slices + parent_dag_backtrack
            all_sl = list(pkt.get("dynamic_slices", [])) + list(pkt.get("parent_dag_backtrack", []))
            has_prov = any(
                (s.get("chunk_id") is not None or s.get("turn_id")) and bool(s.get("sha256"))
                for s in all_sl
            )
            has_topo = any(
                s.get("chat_id") and s.get("turn_index") is not None and s.get("turn_id") is not None and s.get("sha256")
                for s in all_sl
            )
            if has_prov:
                provenance_hits += 1
            if has_topo:
                full_archive_topo_hits += 1

            # Check Falsified / Toy-Locked Pitfall Protection:
            # 1) Purely FALSIFIED chunk excluded from positive dynamic_slices (or accompanied by explicit constraint)
            # 2) Expected falsified_node_id or pivoted verified_node_id surfaced inside falsified_constraints / verified_invariants
            #    (or for SIM_CONSISTENT toy-locked nodes like #620/#671, surfaced in provisional_claims and NOT promoted to EXTERNALLY_VERIFIED)
            pitfall_guarded = True
            if q["is_falsified_pitfall"]:
                pitfall_total += 1
                f_nid = int(q["falsified_node_id"])
                v_nid = int(q["verified_node_id"])
                fc_fids = {fc["falsified_node_id"] for fc in pkt["falsified_constraints"]}
                fc_pids = {fc.get("pivoted_to_node_id") for fc in pkt["falsified_constraints"]}
                vi_nids = {vi["node_id"] for vi in pkt["verified_invariants"]}
                prov_nids = {pr["node_id"] for pr in pkt["provisional_claims"]}
                db_tier_row = conn.execute("SELECT epistemic_tier FROM nodes WHERE node_id = ?", (f_nid,)).fetchone()
                db_tier = str(db_tier_row["epistemic_tier"]) if db_tier_row else "FALSIFIED"
                leaked = any(
                    f_nid in s.get("linked_node_ids", []) and "EXTERNALLY_VERIFIED" not in s.get("epistemic_tiers", [])
                    for s in pkt["dynamic_slices"]
                )
                if db_tier == "SIM_CONSISTENT":
                    pitfall_guarded = (f_nid not in vi_nids) and (
                        (f_nid in prov_nids) or (v_nid in prov_nids) or (v_nid in vi_nids)
                    )
                else:
                    pitfall_guarded = (not leaked) and ((f_nid in fc_fids) or (v_nid in fc_pids) or (v_nid in vi_nids))
                if pitfall_guarded:
                    pitfall_blocked += 1

            q_rows.append(
                {
                    "id": q["id"],
                    "ring": q["ring"],
                    "domain": q["domain"],
                    "raw_rag_tokens": raw_tok,
                    "hydrated_tokens": ptok,
                    "latency_ms": round(dt_ms, 2),
                    "within_budget": ptok <= token_budget,
                    "has_provenance": has_prov,
                    "has_archive_topology": has_topo,
                    "suppressed_falsified_raw": len(pkt["suppressed_falsified_raw_hits"]),
                    "falsified_constraints_count": len(pkt["falsified_constraints"]),
                    "verified_invariants_count": len(pkt["verified_invariants"]),
                    "bridges_used_count": len(pkt["bridges_used"]),
                    "pitfall_guarded": pitfall_guarded,
                }
            )

        # 3. Stage 4 Vocabulary-Drift Probes
        vocab_results: list[dict[str, Any]] = []
        for pr in VOCAB_DRIFT_PROBES:
            hyd = hydrate_pre_tick(
                conn,
                domain="physics",
                query_text=pr["query"],
                archive_db=archive_db,
                core_path=core_path,
                slices_dir=slices_dir,
                token_budget=token_budget,
                sync_deltas_first=False,
            )
            pkt = hyd["packet"]
            phrases_str = " ".join(pkt["expanded_phrases"]).lower()
            matched_tokens = [tok for tok in pr["expected_bridge_tokens"] if tok in phrases_str]
            vocab_results.append(
                {
                    "label": pr["label"],
                    "bridges_triggered": len(pkt["bridges_used"]),
                    "expected_tokens_matched": matched_tokens,
                    "archive_turns_surfaced": sum(
                        1 for s in pkt["dynamic_slices"] if s.get("source") in ("archive_turn", "archive_parent_turn") or s.get("chat_id")
                    ),
                    "passed": len(pkt["bridges_used"]) > 0 and len(matched_tokens) > 0,
                }
            )

        # 4. Dry-hop budget & digest_state watermark check
        digest_count = conn.execute("SELECT COUNT(*) FROM digest_state").fetchone()[0]
        halted_or_invalid_hops = conn.execute(
            "SELECT COUNT(*) FROM research_branches WHERE status = 'ACTIVE' AND hops_since_novelty >= max_dry_hops"
        ).fetchone()[0]

        tok_reduction_pct = ((raw_total_tok - hyd_total_tok) / raw_total_tok * 100.0) if raw_total_tok else 0.0
        summary = {
            "core_digest_bytes": comp_res["core_digest_bytes"],
            "core_digest_in_15_30kb_window": 15 * 1024 <= comp_res["core_digest_bytes"] <= 30 * 1024,
            "digest_state_rows": digest_count,
            "delta_noop_recompiled": len(delta_noop["recompiled_sections"]),
            "archive_status": comp_res["archive_status"],
            "compile_time_s": round(t_comp, 3),
            "questions_evaluated": len(q_rows),
            "raw_rag_total_tokens": raw_total_tok,
            "hydrated_total_tokens": hyd_total_tok,
            "avg_hydrated_tokens": round(hyd_total_tok / len(q_rows), 1),
            "token_reduction_vs_raw_pct": round(tok_reduction_pct, 1),
            "within_budget_rate_pct": round(within_budget_count / len(q_rows) * 100.0, 1),
            "avg_hydration_latency_ms": round(sum(latencies_ms) / len(latencies_ms), 2),
            "provenance_preserved_count": provenance_hits,
            "full_archive_topology_count": full_archive_topo_hits,
            "pitfall_total": pitfall_total,
            "pitfall_guarded_count": pitfall_blocked,
            "pitfall_guard_rate_pct": round(pitfall_blocked / pitfall_total * 100.0, 1) if pitfall_total else 100.0,
            "vocab_drift_probes_passed": sum(1 for v in vocab_results if v["passed"]),
            "vocab_drift_probes_total": len(vocab_results),
            "active_branch_dry_hop_violations": halted_or_invalid_hops,
        }
        payload = {"summary": summary, "questions": q_rows, "vocab_drift_probes": vocab_results}
        json_out.parent.mkdir(parents=True, exist_ok=True)
        json_out.write_text(json.dumps(payload, indent=2), encoding="utf-8")

        lines = [
            "# Arachne / Portable Knowledge Graph <-> `corpus.db` Mutual Evaluation Report",
            "",
            f"> **Database:** `{db_path}` | **Archive Link:** `{comp_res['archive_status']}`  ",
            f"> **Core Digest Size:** `{summary['core_digest_bytes']:,}` bytes (`{summary['core_digest_bytes']/1024:.2f} KB`, in 15–30 KB target window: `{summary['core_digest_in_15_30kb_window']}`)  ",
            f"> **`digest_state` Watermarks Tracked:** `{summary['digest_state_rows']}` rows | **Delta No-Op Recompiles:** `{summary['delta_noop_recompiled']}`",
            "",
            "---",
            "",
            "## 1. Mutual Evaluation Summary (Two Halves of One Coin)",
            "",
            "| Criterion | Half Evaluated | Result | Target |",
            "| :--- | :---: | :---: | :---: |",
            f"| Pinned `core_digest.md` Footprint | Digest Layer 1 | **`{summary['core_digest_bytes']/1024:.2f} KB`** | `15–30 KB` |",
            f"| Avg Hydrated Working-Memory Packet | Arachne Recall | **`{summary['avg_hydrated_tokens']}` tokens** | `<= {token_budget}` tokens (`100%` within budget) |",
            f"| Token Compression vs Raw Top-15 `FTS5` RAG | Arachne Recall | **`-{summary['token_reduction_vs_raw_pct']}%`** (`{raw_total_tok:,} -> {hyd_total_tok:,}`) | Cut noise bloat |",
            f"| Median/Mean Hybrid Hydration Latency | Arachne Recall | **`{summary['avg_hydration_latency_ms']} ms`** | Sub-second tick hydration |",
            f"| Chunk / Archive Provenance Preservation | Arachne <-> Corpus | **`{provenance_hits}/{len(q_rows)}`** (`{full_archive_topo_hits}/{len(q_rows)}` full `turn_id`+`sha256`) | `chunk_id/chat_id/turn_id/sha256` |",
            f"| Pitfall Suppression + `pivoted_to` Gating | Corpus Truth Gate | **`{pitfall_blocked}/{pitfall_total}` (`{summary['pitfall_guard_rate_pct']}%`)** | Zero unmasked `FALSIFIED` leaks |",
            f"| Stage 4 `concept_bridges` Vocabulary Probes | Loop Closure | **`{summary['vocab_drift_probes_passed']}/{summary['vocab_drift_probes_total']}`** | Bidirectional legacy recall |",
            f"| Active Branch `max_dry_hops=3` Compliance | Corpus Halting | **`{summary['active_branch_dry_hop_violations']}` violations** | `0` runaway dry branches |",
            "",
            "## 2. Stage 4 Vocabulary-Drift Probes (`concept_bridges` -> `archive.db` + `corpus.db`)",
            "",
            "| Probe | Bridges Triggered | Archive/Turn Provenance Hits | Expanded Concepts Matched | Status |",
            "| :--- | :---: | :---: | :--- | :---: |",
        ]
        for v in vocab_results:
            lines.append(
                f"| {v['label']} | {v['bridges_triggered']} | {v['archive_turns_surfaced']} | "
                f"`{', '.join(v['expected_tokens_matched'])}` | **{'PASS' if v['passed'] else 'FAIL'}** |"
            )

        lines.extend(
            [
                "",
                "## 3. Per-Question Tier-Gated Hydration & Compression Audit (`20` Cross-Domain Questions)",
                "",
                "| ID | Ring | Domain | Raw RAG Tok | Hydrated Tok | Latency (ms) | Suppressed Raw | Neg Constraints | Verified Inv | Pitfall Guarded |",
                "| :- | :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |",
            ]
        )
        for r in q_rows:
            lines.append(
                f"| #{r['id']} | {r['ring']} | `{r['domain']}` | {r['raw_rag_tokens']} | {r['hydrated_tokens']} | "
                f"{r['latency_ms']} | {r['suppressed_falsified_raw']} | {r['falsified_constraints_count']} | "
                f"{r['verified_invariants_count']} | **{'PASS' if r['pitfall_guarded'] else 'FAIL'}** |"
            )
        report_out.parent.mkdir(parents=True, exist_ok=True)
        report_out.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return payload
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate Arachne <-> corpus.db unified retrieval & truth gate")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--archive-db", type=Path, default=None)
    parser.add_argument("--token-budget", type=int, default=2200)
    parser.add_argument("--report", type=Path, default=DEFAULT_EVAL_REPORT)
    parser.add_argument("--json-out", type=Path, default=DEFAULT_EVAL_JSON)
    args = parser.parse_args()
    res = run_evaluation(
        db_path=args.db,
        archive_db=args.archive_db,
        token_budget=args.token_budget,
        report_out=args.report,
        json_out=args.json_out,
    )
    print(json.dumps(res["summary"], indent=2))


if __name__ == "__main__":
    main()
