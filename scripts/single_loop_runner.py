"""Standalone, prefix-cache-friendly single-loop sequential runner (v0.2.0 epistemic fidelity).

Supports three execution paths without /teamwork or swarm board messaging:
  1. Direct Gemini API (`--backend gemini`, requires GEMINI_API_KEY / GOOGLE_API_KEY)
  2. Local Ollama API (`--backend ollama`, calls http://127.0.0.1:11434/api/generate)
  3. Deterministic step mode (`run-step` subcommands: prepare-lifter, apply-lifter,
     prepare-scientist, apply-scientist, prepare-falsifier, apply-falsifier, write-report)
     so any external stateless orchestrator can run Step A / B / C cleanly.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from arachne_bridge import filter_query_text
from compile_digest import (
    extract_core_anchor_block,
    hydrate_pre_tick,
    on_falsifier_commit,
    resolve_digest_targets,
    sync_ouroboros_deltas,
)
from db_utils import (
    DEFAULT_DB_PATH,
    WORKSPACE_ROOT,
    attach_node_provenance,
    create_node_with_provenance,
    get_connection,
    init_db,
    reconcile_converged_branches,
    run_physics_check,
    verify_and_link,
    verify_node,
)

DEFAULT_SLICE = "bio_neuro_psych"
DEFAULT_STATE_DIR = WORKSPACE_ROOT / "data" / "single_loop_runs"
DEFAULT_REPORT_PATH = WORKSPACE_ROOT / "chapters" / "single_loop_pilot_report.md"

# ---------------------------------------------------------------------------
# Static Prefixes (MUST remain byte-for-byte identical at TOP of every prompt
# so implicit prefix/context caching hits across mini-batches)
# ---------------------------------------------------------------------------

LIFTER_STATIC_PREFIX = """=== ROLE: STEP A (STRUCTURAL LIFTER) — STATIC SYSTEM RULES ===
You execute ONLY Step A (Lifting & Noise Triage) on a slice mini-batch. Never assume shared history.

1. HERMENEUTIC FRAMING:
   - Treat identity claims ("is", "literally") as assertions of structural isomorphism up to substrate.
   - Lift substantive claims into crisp formal relational schemas (`dsl_expr`) plus 1-sentence summaries.
2. STANDING RULE 1 — AGGRESSIVE NOISE TRIAGE (`SKIPPED` with `skip_reason`):
   - Mark stack traces / compiler retries / API error logs as `skip_reason: "debug_churn"`.
   - Mark ONLY pure personal diary/parenting chatter lacking a verifiable mechanism, crawler telemetry, UI chips, or wrapper boilerplate as `skip_reason: "boilerplate"`.
   - Mark verbatim or near-verbatim repeats carrying zero new relational nuance as `skip_reason: "duplicate_export"`.
   - NEVER put a chunk with a testable biological/pharmacological mechanism or a falsifiable pseudoscientific overclaim (e.g. numerology, "Selectron" lungs, "Adrenal Floor") into `skipped`: either attach it to a matching canonical node via `attach_provenance` or mint a `RAW_CLAIM` under `new_nodes` so Step B/C can audit it!
3. STANDING RULE 2 — CANONICAL DEDUPLICATION (`attach_provenance`):
   - Check the EXISTING CANONICAL NODES table at the bottom. If a chunk reinforces an already-captured mechanism/invariant without introducing a distinct new failure mode, emit it under `attach_provenance` referencing ONLY an existing `node_id` listed below (never invent IDs).
   - Emit `new_nodes` (`RAW_CLAIM`) whenever a chunk introduces a genuinely distinct physiological/cognitive claim OR a distinct falsifiable overclaim/numerology scheme needing Step B/C verification.
4. SCHEMA & ATOMICITY RULES (`corpus.db` v3, F2.3):
   - Every new node starts as `RAW_CLAIM` (or `CONTESTED` for actively debated hypotheses) grounded in exact `chunk_ids` and short `quote_spans`.
   - ATOMIC CLAIM LOCK: Every new node MUST state ONE single atomic testable proposition. NEVER bundle a valid mechanism together with a speculative overclaim or numbered `(1)...(2)...` list inside one node; split them into separate `new_nodes` so Step C can verify or falsify each independently without collateral suppression.
   - Every chunk in the input mini-batch MUST appear in EITHER `skipped`, `attach_provenance`, or `new_nodes` (100% coverage).

RETURN STRICT JSON ONLY (no markdown fences):
{
  "skipped": [{"chunk_id": 123, "skip_reason": "boilerplate|debug_churn|duplicate_export", "reason": "..."}],
  "attach_provenance": [{"node_id": 701, "chunk_ids": [124], "quote_spans": ["..."]}],
  "new_nodes": [{"summary": "...", "dsl_expr": "...", "chunk_ids": [125], "quote_spans": ["..."]}],
  "concept_bridges": [{"term": "...", "alias": "...", "structural_pattern": "..."}]
}
"""

SCIENTIST_STATIC_PREFIX = """=== ROLE: STEP B (SCIENTIST / VERIFICATION DESIGNER) — STATIC SYSTEM RULES ===
You execute ONLY Step B (Verification Script & Literature Benchmark Synthesis) for newly lifted `RAW_CLAIM` nodes.

1. STRICT v3 EPISTEMIC TIERING, VERIFIER-SCOPE COUPLING (F2.2) & TOY-SCRIPT LOCK:
   - Never conflate a self-authored illustrative script (`toy_model`) with an external law (`standard_physics_law`, `empirical_benchmark`, `literature_citation`, `primary_record`).
   - VERIFIER-SCOPE COUPLING: `verifier_type = "python_sim"` is ALLOWED ONLY for `standard_physics_law`, `empirical_benchmark`, or `toy_model` — it is STRICTLY FORBIDDEN for `literature_citation` or `primary_record`.
   - For `literature_citation` or `primary_record`, set `verifier_type = "literature_ref"` (or `"public_record"`) and supply a real primary `external_ref` starting with `doi:`, `pmid:`, `arxiv:`, or `https://` (`pycheck:` hashes are rejected by the database trigger).
   - Use `toy_model` ONLY if the claim is an unbenchmarked prototype script.
2. DETERMINISTIC `run_physics_check` PYTHON SNIPPETS:
   - Write self-contained Python 3 standard-library code (`import math`, etc. — NO third-party numpy/scipy) with explicit numerical computation, `assert` checks, and a single concise `print(...)` summary line.
   - If a claim mixes valid physiology/math with a false conflation or dimensional error, write the Python check to prove the exact quantitative discrepancy / boundary (so Step C Falsifier can mark `FALSIFIED` and pivot cleanly).
3. BENCHMARK REFERENCES:
   - Supply a concrete, non-empty `benchmark_ref` (author/year, physical law, thermodynamic bound, or PK constant) and `expected_verdict` (`HOLDS`, `BREAKS`, or `TOY_ONLY`).

RETURN STRICT JSON ONLY (no markdown fences):
{
  "checks": [
    {
      "node_id": 782,
      "verification_scope": "standard_physics_law|empirical_benchmark|literature_citation|toy_model",
      "verifier_type": "python_sim|literature_ref",
      "benchmark_ref": "Concrete external law / citation / benchmark",
      "expected_verdict": "HOLDS|BREAKS|BREAKS_PARTIAL|TOY_ONLY",
      "python_code": "import math\\n...\\nassert ...\\nprint('...')",
      "notes": "1-2 sentence mechanistic note"
    }
  ]
}
"""

FALSIFIER_STATIC_PREFIX = """=== ROLE: STEP C (FALSIFIER GATE) — STATIC SYSTEM RULES ===
You execute ONLY Step C (Epistemic Falsifier Gate) using ONLY the node summary/DSL, deterministic `pycheck` output, and `v0.2.0` rules (`db_utils.py`).

1. v0.2.0 EPISTEMIC LOCKS:
   - `EXTERNALLY_VERIFIED` requires: `pycheck.passed == true` (or valid non-`llm_only` ref), `verification_scope` in `{"standard_physics_law", "empirical_benchmark", "literature_citation", "primary_record"}`, and non-empty `benchmark_ref`.
   - `toy_model` scope may promote at most to `SIM_CONSISTENT` (and branch remains `ACTIVE`).
   - `FALSIFIED` requires recording a reframed `EXTERNALLY_VERIFIED` replacement node (`reframed_summary`, `reframed_dsl_expr`) linked via BOTH `resolved_mistake` and `pivoted_to` (`from_node_id != to_node_id`; self-loops forbidden!).
2. ANTI-LITERALISM & REFRAMED SOLVER:
   - Do not reject a valid isomorphism merely for substrate differences; reject ONLY where conservation laws, dimensional analysis, biological/PK bounds, or formal logic actually break.
   - Suggest 1–2 existing verified ancestor `node_id`s from the ANCESTOR INDEX (`support_targets`) for cross-linking (`supports` edges, never pointing to a `FALSIFIED` node).

RETURN STRICT JSON ONLY (no markdown fences):
{
  "decisions": [
    {
      "node_id": 782,
      "verdict": "EXTERNALLY_VERIFIED|SIM_CONSISTENT|FALSIFIED",
      "verification_scope": "standard_physics_law|empirical_benchmark|literature_citation|toy_model",
      "benchmark_ref": "...",
      "notes": "...",
      "support_targets": [701, 716],
      "reframed_summary": "Required if verdict == FALSIFIED; null otherwise",
      "reframed_dsl_expr": "Required if verdict == FALSIFIED; null otherwise"
    }
  ]
}
"""


def _extract_json(raw_text: str) -> dict[str, Any]:
    cleaned = raw_text.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*\})\s*```", cleaned, flags=re.DOTALL)
    if fence:
        cleaned = fence.group(1)
    else:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start != -1 and end != -1 and end > start:
            cleaned = cleaned[start : end + 1]
    return json.loads(cleaned)


def _domain_snapshot(conn: sqlite3.Connection, domain: str, limit: int = 90) -> str:
    rows = conn.execute(
        """
        SELECT node_id, epistemic_tier, substr(summary, 1, 140) AS s
        FROM nodes
        WHERE domain = ? AND epistemic_tier != 'FALSIFIED'
        ORDER BY node_id DESC
        LIMIT ?
        """,
        (domain, limit),
    ).fetchall()
    return "\n".join(f"- #{r['node_id']} [{r['epistemic_tier']}]: {r['s']}" for r in rows)


def _format_hydration_block(hydrated: dict[str, Any] | None, core_mode: str = "anchor") -> str:
    if not hydrated:
        return ""
    core_path = Path(hydrated["core_digest_path"])
    core_text = core_path.read_text(encoding="utf-8") if core_path.exists() else ""
    if core_mode == "none":
        core_block = ""
    elif core_mode == "full":
        core_block = core_text.strip()
    else:
        core_block = extract_core_anchor_block(core_text)
    pkt_md = hydrated.get("packet", {}).get("rendered_markdown", "")
    parts: list[str] = []
    if core_block:
        parts.append(f"=== PINNED CORE DIGEST ({core_mode.upper()}) ===\n{core_block}")
    if pkt_md:
        parts.append(pkt_md)
    return ("\n\n".join(parts) + "\n\n") if parts else ""


def build_lifter_prompt(
    conn: sqlite3.Connection,
    domain: str,
    chunks: list[dict[str, Any]],
    hydrated: dict[str, Any] | None = None,
    core_mode: str = "anchor",
) -> str:
    snapshot = _domain_snapshot(conn, domain)
    hyd_block = _format_hydration_block(hydrated, core_mode=core_mode)
    chunk_block = json.dumps(
        [
            {
                "chunk_id": c["chunk_id"],
                "source_ref": c["source_ref"],
                "content": c["content"][:1800],
            }
            for c in chunks
        ],
        ensure_ascii=False,
        indent=2,
    )
    return (
        f"{LIFTER_STATIC_PREFIX}\n"
        f"{hyd_block}"
        f"=== DYNAMIC BATCH PAYLOAD (DOMAIN={domain}) ===\n"
        f"EXISTING CANONICAL NODES (use attach_provenance when matching):\n{snapshot}\n\n"
        f"TARGET MINI-BATCH CHUNKS ({len(chunks)} chunks):\n{chunk_block}\n"
    )


def build_scientist_prompt(
    domain: str,
    nodes_payload: list[dict[str, Any]],
    hydrated: dict[str, Any] | None = None,
    core_mode: str = "anchor",
) -> str:
    hyd_block = _format_hydration_block(hydrated, core_mode=core_mode)
    nodes_block = json.dumps(nodes_payload, ensure_ascii=False, indent=2)
    return (
        f"{SCIENTIST_STATIC_PREFIX}\n"
        f"{hyd_block}"
        f"=== DYNAMIC BATCH PAYLOAD (DOMAIN={domain}) ===\n"
        f"RAW_CLAIM NODES TO DESIGN CHECKS FOR:\n{nodes_block}\n"
    )


def build_falsifier_prompt(
    conn: sqlite3.Connection,
    domain: str,
    candidates_with_pycheck: list[dict[str, Any]],
    hydrated: dict[str, Any] | None = None,
    core_mode: str = "anchor",
) -> str:
    ancestors = _domain_snapshot(conn, domain, limit=60)
    hyd_block = _format_hydration_block(hydrated, core_mode=core_mode)
    cand_block = json.dumps(candidates_with_pycheck, ensure_ascii=False, indent=2)
    return (
        f"{FALSIFIER_STATIC_PREFIX}\n"
        f"{hyd_block}"
        f"=== DYNAMIC BATCH PAYLOAD (DOMAIN={domain}) ===\n"
        f"VERIFIED ANCESTOR INDEX (for support_targets):\n{ancestors}\n\n"
        f"CANDIDATES WITH DETERMINISTIC PYCHECK OUTPUT:\n{cand_block}\n"
    )


def apply_lifter_output(
    conn: sqlite3.Connection,
    slice_name: str,
    domain: str,
    batch_chunk_ids: list[int],
    lifter_json: dict[str, Any],
) -> dict[str, Any]:
    created_nodes: list[dict[str, Any]] = []
    attached: list[dict[str, Any]] = []
    skipped_ids: list[int] = []
    processed_ids: list[int] = []

    for item in lifter_json.get("skipped", []):
        cid = int(item["chunk_id"])
        reason = item.get("skip_reason") or "boilerplate"
        if reason not in ("debug_churn", "boilerplate", "duplicate_export"):
            reason = "boilerplate"
        conn.execute(
            "UPDATE chapter_slices SET status = 'SKIPPED', skip_reason = ? WHERE slice_name = ? AND chunk_id = ?",
            (reason, slice_name, cid),
        )
        skipped_ids.append(cid)

    for item in lifter_json.get("attach_provenance", []):
        nid = int(item["node_id"])
        cids = [int(x) for x in item.get("chunk_ids", [])]
        spans = [str(x) for x in item.get("quote_spans", [])]
        res = attach_node_provenance(conn, node_id=nid, chunk_ids=cids, quote_spans=spans)
        attached.append(res)
        for cid in cids:
            conn.execute(
                "UPDATE chapter_slices SET status = 'PROCESSED', skip_reason = NULL WHERE slice_name = ? AND chunk_id = ?",
                (slice_name, cid),
            )
            processed_ids.append(cid)

    for item in lifter_json.get("new_nodes", []):
        cids = [int(x) for x in item.get("chunk_ids", [])]
        spans = [str(x) for x in item.get("quote_spans", [])]
        nid = create_node_with_provenance(
            conn,
            domain=domain,
            summary=str(item["summary"]),
            chunk_ids=cids,
            dsl_expr=str(item.get("dsl_expr") or ""),
            quote_spans=spans,
            epistemic_tier="RAW_CLAIM",
        )
        bcur = conn.execute(
            "INSERT INTO research_branches (root_node_id, agent_role, max_dry_hops) VALUES (?, 'scientist', 3)",
            (nid,),
        )
        branch_id = int(bcur.lastrowid)
        created_nodes.append(
            {
                "node_id": nid,
                "branch_id": branch_id,
                "summary": str(item["summary"]),
                "dsl_expr": str(item.get("dsl_expr") or ""),
                "chunk_ids": cids,
            }
        )
        for cid in cids:
            conn.execute(
                "UPDATE chapter_slices SET status = 'PROCESSED', skip_reason = NULL WHERE slice_name = ? AND chunk_id = ?",
                (slice_name, cid),
            )
            processed_ids.append(cid)

    for br in lifter_json.get("concept_bridges", []):
        term = str(br.get("term", "")).strip()
        alias = str(br.get("alias", "")).strip()
        pattern = str(br.get("structural_pattern", "")).strip() or None
        if term and alias:
            conn.execute(
                "INSERT OR IGNORE INTO concept_bridges (term, alias, structural_pattern) VALUES (?, ?, ?)",
                (term, alias, pattern),
            )

    # Ensure any batch chunk omitted by mistake is not left dangling silently
    handled = set(skipped_ids) | set(processed_ids)
    unhandled = [cid for cid in batch_chunk_ids if cid not in handled]
    conn.commit()
    return {
        "created_nodes": created_nodes,
        "attached": attached,
        "skipped_count": len(skipped_ids),
        "processed_count": len(processed_ids),
        "unhandled_chunk_ids": unhandled,
    }


def execute_scientist_checks(
    lifter_nodes: list[dict[str, Any]],
    scientist_json: dict[str, Any],
) -> list[dict[str, Any]]:
    by_nid = {int(n["node_id"]): n for n in lifter_nodes}
    out: list[dict[str, Any]] = []
    for chk in scientist_json.get("checks", []):
        nid = int(chk["node_id"])
        node_info = by_nid.get(nid, {"node_id": nid})
        py_code = str(chk.get("python_code") or "print('no code provided')\nassert False\n")
        py_res = run_physics_check(py_code)
        out.append(
            {
                **node_info,
                "verification_scope": chk.get("verification_scope", "literature_citation"),
                "verifier_type": chk.get("verifier_type", "python_sim"),
                "benchmark_ref": chk.get("benchmark_ref", ""),
                "expected_verdict": chk.get("expected_verdict", "HOLDS"),
                "scientist_notes": chk.get("notes", ""),
                "pycheck": py_res,
            }
        )
    return out


def apply_falsifier_output(
    conn: sqlite3.Connection,
    domain: str,
    candidates_with_pycheck: list[dict[str, Any]],
    falsifier_json: dict[str, Any],
    *,
    db_path: Path | None = None,
    archive_db: Path | str | None = None,
    trigger_digest: bool = True,
) -> dict[str, Any]:
    cand_by_nid = {int(c["node_id"]): c for c in candidates_with_pycheck}
    committed: list[dict[str, Any]] = []
    affected_node_ids: list[int] = []

    for dec in falsifier_json.get("decisions", []):
        nid = int(dec["node_id"])
        cand = cand_by_nid[nid]
        branch_id = cand.get("branch_id")
        verdict = str(dec["verdict"])
        scope = str(dec.get("verification_scope") or cand.get("verification_scope") or "standard_physics_law")
        vtype = str(dec.get("verifier_type") or cand.get("verifier_type") or ("literature_ref" if scope in ("literature_citation", "primary_record") else "python_sim"))
        bench = str(dec.get("benchmark_ref") or cand.get("benchmark_ref") or "").strip()
        notes = str(dec.get("notes") or cand.get("scientist_notes") or "").strip()
        py_res = cand.get("pycheck", {})
        if vtype in ("literature_ref", "public_record"):
            ext_ref = str(dec.get("external_ref") or cand.get("external_ref") or "").strip() or None
            passed = bool(ext_ref)
        else:
            ext_ref = py_res.get("external_ref")
            passed = bool(py_res.get("passed"))

        if not passed or not ext_ref:
            raise ValueError(f"Node #{nid} verification ({vtype}) did not pass; refusing commit ({py_res.get('stderr')}).")

        if scope == "toy_model" and verdict == "EXTERNALLY_VERIFIED":
            verdict = "SIM_CONSISTENT"

        if verdict in ("SIM_CONSISTENT", "CONTESTED", "UNDER_APPEAL"):
            target_scope = "toy_model" if verdict == "SIM_CONSISTENT" and vtype == "python_sim" else scope
            res = verify_node(
                conn,
                node_id=nid,
                verifier_type=vtype,
                verification_scope=target_scope,
                external_ref=ext_ref,
                benchmark_ref=bench or None,
                passed=True,
                branch_id=branch_id,
                new_tier=verdict,
                notes=notes,
            )
            affected_node_ids.append(nid)
            committed.append({"node_id": nid, "tier": verdict, "verification_id": res["verification_id"]})
        elif verdict == "EXTERNALLY_VERIFIED":
            res = verify_node(
                conn,
                node_id=nid,
                verifier_type=vtype,
                verification_scope=scope,
                external_ref=ext_ref,
                benchmark_ref=bench,
                passed=True,
                branch_id=branch_id,
                new_tier="EXTERNALLY_VERIFIED",
                notes=notes,
            )
            affected_node_ids.append(nid)
            for tgt in dec.get("support_targets", []) or []:
                tgt_id = int(tgt)
                if tgt_id != nid:
                    row = conn.execute(
                        "SELECT epistemic_tier FROM nodes WHERE node_id = ?", (tgt_id,)
                    ).fetchone()
                    if row and row["epistemic_tier"] != "FALSIFIED":
                        verify_and_link(
                            conn,
                            from_node_id=nid,
                            to_node_id=tgt_id,
                            relation_type="supports",
                            verifier_type=vtype,
                            external_ref=ext_ref,
                            verification_scope=scope,
                            benchmark_ref=bench,
                            notes="Cross-domain structural support",
                        )
                        affected_node_ids.append(tgt_id)
            committed.append({"node_id": nid, "tier": "EXTERNALLY_VERIFIED", "verification_id": res["verification_id"]})
        elif verdict == "FALSIFIED":
            ref_summary = str(dec.get("reframed_summary") or "").strip()
            ref_dsl = str(dec.get("reframed_dsl_expr") or "").strip()
            if not ref_summary:
                raise ValueError(f"FALSIFIED node #{nid} missing reframed_summary.")
            chunk_ids = [
                r["chunk_id"]
                for r in conn.execute(
                    "SELECT chunk_id FROM node_provenance WHERE node_id = ?", (nid,)
                ).fetchall()
            ]
            reframed_id = create_node_with_provenance(
                conn,
                domain=domain,
                summary=ref_summary,
                chunk_ids=chunk_ids,
                dsl_expr=ref_dsl,
                epistemic_tier="DSL_CONSISTENT",
            )
            verify_node(
                conn,
                node_id=reframed_id,
                verifier_type=vtype,
                verification_scope=scope,
                external_ref=ext_ref,
                benchmark_ref=bench,
                passed=True,
                new_tier="EXTERNALLY_VERIFIED",
                notes=f"Reframed verified resolution of #{nid}: {notes}",
            )
            verify_and_link(
                conn,
                from_node_id=nid,
                to_node_id=reframed_id,
                relation_type="resolved_mistake",
                verifier_type=vtype,
                external_ref=ext_ref,
                verification_scope=scope,
                benchmark_ref=bench,
                branch_id=branch_id,
                promote_node_id=nid,
                new_tier="FALSIFIED",
                notes=notes,
            )
            verify_and_link(
                conn,
                from_node_id=nid,
                to_node_id=reframed_id,
                relation_type="pivoted_to",
                verifier_type=vtype,
                external_ref=ext_ref,
                verification_scope=scope,
                benchmark_ref=bench,
                branch_id=branch_id,
                notes="Pivoted falsified overclaim to verified reframing",
            )
            affected_node_ids.extend([nid, reframed_id])
            for tgt in dec.get("support_targets", []) or []:
                tgt_id = int(tgt)
                if tgt_id not in (nid, reframed_id):
                    row = conn.execute(
                        "SELECT epistemic_tier FROM nodes WHERE node_id = ?", (tgt_id,)
                    ).fetchone()
                    if row and row["epistemic_tier"] != "FALSIFIED":
                        verify_and_link(
                            conn,
                            from_node_id=reframed_id,
                            to_node_id=tgt_id,
                            relation_type="supports",
                            verifier_type=vtype,
                            external_ref=ext_ref,
                            verification_scope=scope,
                            benchmark_ref=bench,
                            notes="Cross-domain structural support from reframed node",
                        )
                        affected_node_ids.append(tgt_id)
            committed.append(
                {
                    "node_id": nid,
                    "tier": "FALSIFIED",
                    "reframed_node_id": reframed_id,
                }
            )
        else:
            raise ValueError(f"Unsupported verdict {verdict!r} for node #{nid}")

    rec = reconcile_converged_branches(conn)
    digest_delta: dict[str, Any] | None = None
    if trigger_digest and affected_node_ids:
        core_path, slices_dir = resolve_digest_targets(db_path)
        digest_delta = on_falsifier_commit(
            conn,
            affected_node_ids,
            archive_db=archive_db,
            core_path=core_path,
            slices_dir=slices_dir,
        )
    return {"committed": committed, "reconciled": rec, "digest_delta": digest_delta}


# ---------------------------------------------------------------------------
# Direct API Backends (Gemini SDK / Local Ollama)
# ---------------------------------------------------------------------------

def _call_gemini(model: str, prompt: str, thinking_budget: int | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    from google import genai
    from google.genai import types

    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY or GOOGLE_API_KEY must be set for --backend gemini.")
    client = genai.Client(api_key=api_key)
    cfg_kwargs: dict[str, Any] = {"temperature": 0.0, "response_mime_type": "application/json"}
    if thinking_budget is not None:
        cfg_kwargs["thinking_config"] = types.ThinkingConfig(thinking_budget=thinking_budget)
    t0 = time.monotonic()
    resp = client.models.generate_content(
        model=model,
        contents=prompt,
        config=types.GenerateContentConfig(**cfg_kwargs),
    )
    elapsed = time.monotonic() - t0
    um = resp.usage_metadata
    in_tok = int(getattr(um, "prompt_token_count", 0) or 0)
    cached_tok = int(getattr(um, "cached_content_token_count", 0) or 0)
    cand_tok = int(getattr(um, "candidates_token_count", 0) or 0)
    thought_tok = int(getattr(um, "thoughts_token_count", 0) or 0)
    usage = {
        "model": model,
        "input_tokens": max(0, in_tok - cached_tok),
        "cached_input_tokens": cached_tok,
        "output_and_thinking_tokens": cand_tok + thought_tok,
        "wall_clock_s": round(elapsed, 3),
    }
    return _extract_json(resp.text or "{}"), usage


def _call_ollama(model: str, prompt: str, ollama_url: str) -> tuple[dict[str, Any], dict[str, Any]]:
    t0 = time.monotonic()
    req = urllib.request.Request(
        f"{ollama_url.rstrip('/')}/api/generate",
        data=json.dumps(
            {
                "model": model,
                "prompt": prompt,
                "format": "json",
                "stream": False,
                "keep_alive": "15m",
                "options": {"temperature": 0.0, "num_ctx": 8192},
            }
        ).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=180) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    elapsed = time.monotonic() - t0
    usage = {
        "model": model,
        "input_tokens": int(data.get("prompt_eval_count") or 0),
        "cached_input_tokens": 0,
        "output_and_thinking_tokens": int(data.get("eval_count") or 0),
        "wall_clock_s": round(elapsed, 3),
    }
    return _extract_json(data.get("response", "{}")), usage


def _hydrate_for_nodes(
    conn: sqlite3.Connection,
    *,
    db_path: Path,
    domain: str,
    nodes_list: list[dict[str, Any]],
    archive_db: Path | None,
    token_budget: int,
    sync_deltas_first: bool = False,
) -> dict[str, Any]:
    core_path, slices_dir = resolve_digest_targets(db_path)
    raw_q_text = " ".join(
        f"{n.get('summary', '')} {n.get('dsl_expr', '')}" for n in nodes_list
    ).strip()
    q_text = filter_query_text(raw_q_text) or raw_q_text or domain
    return hydrate_pre_tick(
        conn,
        domain=domain,
        chunks=None,
        query_text=q_text,
        archive_db=archive_db,
        core_path=core_path,
        slices_dir=slices_dir,
        token_budget=token_budget,
        sync_deltas_first=sync_deltas_first,
    )


def run_direct_loop(args: argparse.Namespace) -> None:
    init_db(args.db)
    conn = get_connection(args.db)
    core_path, slices_dir = resolve_digest_targets(args.db)
    archive_db = getattr(args, "archive_db", None)
    use_hydrate = not getattr(args, "no_hydrate", False)
    core_mode = getattr(args, "core_mode", "full")
    pkt_budget = int(getattr(args, "packet_budget", 2200))
    use_delta = not getattr(args, "no_digest_delta", False)

    try:
        if use_hydrate:
            sync_ouroboros_deltas(conn, archive_db=archive_db, core_path=core_path, slices_dir=slices_dir)

        rows = conn.execute(
            """
            SELECT c.chunk_id, c.source_type, c.source_ref, c.content, cs.relevance
            FROM chapter_slices cs
            JOIN chunks c ON c.chunk_id = cs.chunk_id
            WHERE cs.slice_name = ? AND cs.status = 'PENDING'
            ORDER BY cs.relevance ASC
            LIMIT ?
            """,
            (args.slice_name, args.limit),
        ).fetchall()
        chunks = [dict(r) for r in rows]
        if not chunks:
            print(json.dumps({"status": "no_pending_chunks", "slice_name": args.slice_name}))
            return

        runs: list[dict[str, Any]] = []
        for idx in range(0, len(chunks), args.batch_size):
            batch = chunks[idx : idx + args.batch_size]
            b_ids = [c["chunk_id"] for c in batch]

            def invoke(role_model: str, prompt: str, t_budget: int | None) -> tuple[dict[str, Any], dict[str, Any]]:
                if args.backend == "gemini":
                    return _call_gemini(role_model, prompt, thinking_budget=t_budget)
                return _call_ollama(role_model, prompt, args.ollama_url)

            # Stage 2 Pre-Tick Hydration (before Step A Lifter)
            hyd_a = (
                hydrate_pre_tick(
                    conn,
                    domain=args.domain,
                    chunks=batch,
                    archive_db=archive_db,
                    core_path=core_path,
                    slices_dir=slices_dir,
                    token_budget=pkt_budget,
                    sync_deltas_first=True,
                )
                if use_hydrate
                else None
            )

            # Step A: Lifter (stateless)
            p_a = build_lifter_prompt(conn, args.domain, batch, hydrated=hyd_a, core_mode=core_mode)
            out_a, u_a = invoke(args.lifter_model, p_a, 0)
            res_a = apply_lifter_output(conn, args.slice_name, args.domain, b_ids, out_a)

            # Step B: Scientist (stateless, hydrated for lifted nodes)
            res_b: list[dict[str, Any]] = []
            u_b = {"model": args.scientist_model, "input_tokens": 0, "cached_input_tokens": 0, "output_and_thinking_tokens": 0, "wall_clock_s": 0.0}
            if res_a["created_nodes"]:
                hyd_b = (
                    _hydrate_for_nodes(
                        conn,
                        db_path=args.db,
                        domain=args.domain,
                        nodes_list=res_a["created_nodes"],
                        archive_db=archive_db,
                        token_budget=pkt_budget,
                    )
                    if use_hydrate
                    else None
                )
                p_b = build_scientist_prompt(args.domain, res_a["created_nodes"], hydrated=hyd_b, core_mode=core_mode)
                out_b, u_b = invoke(args.scientist_model, p_b, 1024)
                res_b = execute_scientist_checks(res_a["created_nodes"], out_b)

            # Step C: Falsifier (stateless, followed by Stage 3 Delta Re-Compilation)
            res_c: dict[str, Any] = {"committed": [], "reconciled": {}, "digest_delta": None}
            u_c = {"model": args.falsifier_model, "input_tokens": 0, "cached_input_tokens": 0, "output_and_thinking_tokens": 0, "wall_clock_s": 0.0}
            if res_b:
                hyd_c = (
                    _hydrate_for_nodes(
                        conn,
                        db_path=args.db,
                        domain=args.domain,
                        nodes_list=res_b,
                        archive_db=archive_db,
                        token_budget=pkt_budget,
                    )
                    if use_hydrate
                    else None
                )
                p_c = build_falsifier_prompt(conn, args.domain, res_b, hydrated=hyd_c, core_mode=core_mode)
                out_c, u_c = invoke(args.falsifier_model, p_c, 1024)
                res_c = apply_falsifier_output(
                    conn,
                    args.domain,
                    res_b,
                    out_c,
                    db_path=args.db,
                    archive_db=archive_db,
                    trigger_digest=use_delta,
                )

            runs.append(
                {
                    "mini_batch": idx // args.batch_size + 1,
                    "chunk_ids": b_ids,
                    "processed_chunks": res_a["processed_count"],
                    "skipped_chunks": res_a["skipped_count"],
                    "nodes_committed": len(res_c["committed"]),
                    "digest_recompiled_sections": (res_c.get("digest_delta") or {}).get("recompiled_sections", []),
                    "hydrated_tokens": (hyd_a or {}).get("packet", {}).get("estimated_tokens", 0),
                    "suppressed_falsified_hits": len((hyd_a or {}).get("packet", {}).get("suppressed_falsified_raw_hits", [])),
                    "step_a": u_a,
                    "step_b": u_b,
                    "step_c": u_c,
                }
            )
        out_path = Path(args.metrics_out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps({"slice_name": args.slice_name, "domain": args.domain, "runs": runs}, indent=2), encoding="utf-8")
        print(json.dumps({"status": "ok", "batches": len(runs), "metrics_out": str(out_path)}, indent=2))
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Step Subcommands (Deterministic Prompt Prep / Pycheck / Commit)
# ---------------------------------------------------------------------------

def cmd_step(args: argparse.Namespace) -> None:
    init_db(args.db)
    conn = get_connection(args.db)
    state_dir = Path(args.state_dir)
    state_dir.mkdir(parents=True, exist_ok=True)
    core_path, slices_dir = resolve_digest_targets(args.db)
    archive_db = getattr(args, "archive_db", None)
    use_hydrate = not getattr(args, "no_hydrate", False)
    core_mode = getattr(args, "core_mode", "anchor")
    pkt_budget = int(getattr(args, "packet_budget", 2200))
    use_delta = not getattr(args, "no_digest_delta", False)

    try:
        if args.step_action == "prepare-lifter":
            if args.chunk_ids:
                cids = [int(x) for x in args.chunk_ids.split(",") if x.strip()]
                rows = conn.execute(
                    f"SELECT chunk_id, source_type, source_ref, content FROM chunks WHERE chunk_id IN ({','.join('?' for _ in cids)})",
                    tuple(cids),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT c.chunk_id, c.source_type, c.source_ref, c.content
                    FROM chapter_slices cs
                    JOIN chunks c ON c.chunk_id = cs.chunk_id
                    WHERE cs.slice_name = ? AND cs.status = 'PENDING'
                    ORDER BY cs.relevance ASC
                    LIMIT ?
                    """,
                    (args.slice_name, args.limit),
                ).fetchall()
            chunks = [dict(r) for r in rows]
            hyd = (
                hydrate_pre_tick(
                    conn,
                    domain=args.domain,
                    chunks=chunks,
                    archive_db=archive_db,
                    core_path=core_path,
                    slices_dir=slices_dir,
                    token_budget=pkt_budget,
                    sync_deltas_first=True,
                )
                if use_hydrate
                else None
            )
            prompt = build_lifter_prompt(conn, args.domain, chunks, hydrated=hyd, core_mode=core_mode)
            p_path = state_dir / f"{args.batch_tag}_step_a_prompt.txt"
            m_path = state_dir / f"{args.batch_tag}_batch_chunks.json"
            p_path.write_text(prompt, encoding="utf-8")
            m_path.write_text(json.dumps([c["chunk_id"] for c in chunks]), encoding="utf-8")
            if hyd is not None:
                (state_dir / f"{args.batch_tag}_hydrated_packet.json").write_text(
                    json.dumps(hyd, indent=2, ensure_ascii=False), encoding="utf-8"
                )
                (state_dir / f"{args.batch_tag}_hydrated_packet.md").write_text(
                    hyd["packet"]["rendered_markdown"], encoding="utf-8"
                )
            print(
                json.dumps(
                    {
                        "prompt_file": str(p_path),
                        "chunk_ids": [c["chunk_id"] for c in chunks],
                        "prompt_chars": len(prompt),
                        "hydrated": use_hydrate,
                        "packet_tokens": (hyd or {}).get("packet", {}).get("estimated_tokens", 0),
                        "archive_db_status": (hyd or {}).get("archive_db_status", "skipped"),
                    }
                )
            )

        elif args.step_action == "apply-lifter":
            lifter_json = _extract_json(Path(args.response_file).read_text(encoding="utf-8"))
            batch_ids = json.loads((state_dir / f"{args.batch_tag}_batch_chunks.json").read_text(encoding="utf-8"))
            res_a = apply_lifter_output(conn, args.slice_name, args.domain, batch_ids, lifter_json)
            (state_dir / f"{args.batch_tag}_lifter_applied.json").write_text(json.dumps(res_a, indent=2), encoding="utf-8")
            hyd_b = (
                _hydrate_for_nodes(
                    conn,
                    db_path=args.db,
                    domain=args.domain,
                    nodes_list=res_a["created_nodes"],
                    archive_db=archive_db,
                    token_budget=pkt_budget,
                )
                if (use_hydrate and res_a["created_nodes"])
                else None
            )
            sci_prompt = build_scientist_prompt(args.domain, res_a["created_nodes"], hydrated=hyd_b, core_mode=core_mode)
            sp_path = state_dir / f"{args.batch_tag}_step_b_prompt.txt"
            sp_path.write_text(sci_prompt, encoding="utf-8")
            print(json.dumps({"applied": res_a, "step_b_prompt_file": str(sp_path), "created_nodes_count": len(res_a["created_nodes"])}, indent=2))

        elif args.step_action == "prepare-scientist-nodes":
            nids = [int(x) for x in args.node_ids.split(",") if x.strip()]
            created_nodes: list[dict[str, Any]] = []
            for nid in nids:
                row = conn.execute(
                    "SELECT node_id, summary, dsl_expr FROM nodes WHERE node_id = ?",
                    (nid,),
                ).fetchone()
                if row is None:
                    continue
                br = conn.execute(
                    "SELECT branch_id FROM research_branches WHERE root_node_id = ? AND status = 'ACTIVE' ORDER BY branch_id DESC LIMIT 1",
                    (nid,),
                ).fetchone()
                if br is not None:
                    bid = int(br["branch_id"])
                else:
                    bcur = conn.execute(
                        "INSERT INTO research_branches (root_node_id, agent_role, max_dry_hops) VALUES (?, 'scientist', 3)",
                        (nid,),
                    )
                    bid = int(bcur.lastrowid)
                cids = [
                    int(r["chunk_id"])
                    for r in conn.execute(
                        "SELECT chunk_id FROM node_provenance WHERE node_id = ? ORDER BY chunk_id",
                        (nid,),
                    ).fetchall()
                ]
                created_nodes.append(
                    {
                        "node_id": int(row["node_id"]),
                        "branch_id": bid,
                        "summary": str(row["summary"]),
                        "dsl_expr": str(row["dsl_expr"] or ""),
                        "chunk_ids": cids,
                    }
                )
            conn.commit()
            res_a = {"created_nodes": created_nodes}
            (state_dir / f"{args.batch_tag}_lifter_applied.json").write_text(json.dumps(res_a, indent=2), encoding="utf-8")
            hyd_b = (
                _hydrate_for_nodes(
                    conn,
                    db_path=args.db,
                    domain=args.domain,
                    nodes_list=created_nodes,
                    archive_db=archive_db,
                    token_budget=pkt_budget,
                    sync_deltas_first=True,
                )
                if (use_hydrate and created_nodes)
                else None
            )
            sci_prompt = build_scientist_prompt(args.domain, created_nodes, hydrated=hyd_b, core_mode=core_mode)
            sp_path = state_dir / f"{args.batch_tag}_step_b_prompt.txt"
            sp_path.write_text(sci_prompt, encoding="utf-8")
            print(json.dumps({"step_b_prompt_file": str(sp_path), "nodes_count": len(created_nodes), "prompt_chars": len(sci_prompt)}))

        elif args.step_action == "apply-scientist":
            sci_json = _extract_json(Path(args.response_file).read_text(encoding="utf-8"))
            res_a = json.loads((state_dir / f"{args.batch_tag}_lifter_applied.json").read_text(encoding="utf-8"))
            res_b = execute_scientist_checks(res_a["created_nodes"], sci_json)
            (state_dir / f"{args.batch_tag}_scientist_pychecks.json").write_text(json.dumps(res_b, indent=2), encoding="utf-8")
            hyd_c = (
                _hydrate_for_nodes(
                    conn,
                    db_path=args.db,
                    domain=args.domain,
                    nodes_list=res_b,
                    archive_db=archive_db,
                    token_budget=pkt_budget,
                )
                if (use_hydrate and res_b)
                else None
            )
            fal_prompt = build_falsifier_prompt(conn, args.domain, res_b, hydrated=hyd_c, core_mode=core_mode)
            fp_path = state_dir / f"{args.batch_tag}_step_c_prompt.txt"
            fp_path.write_text(fal_prompt, encoding="utf-8")
            print(
                json.dumps(
                    {
                        "pychecks_total": len(res_b),
                        "pychecks_passed": sum(1 for r in res_b if r["pycheck"]["passed"]),
                        "step_c_prompt_file": str(fp_path),
                    },
                    indent=2,
                )
            )

        elif args.step_action == "apply-falsifier":
            fal_json = _extract_json(Path(args.response_file).read_text(encoding="utf-8"))
            res_b = json.loads((state_dir / f"{args.batch_tag}_scientist_pychecks.json").read_text(encoding="utf-8"))
            res_c = apply_falsifier_output(
                conn,
                args.domain,
                res_b,
                fal_json,
                db_path=args.db,
                archive_db=archive_db,
                trigger_digest=use_delta,
            )
            (state_dir / f"{args.batch_tag}_falsifier_committed.json").write_text(json.dumps(res_c, indent=2), encoding="utf-8")
            print(json.dumps(res_c, indent=2))
    finally:
        conn.close()


def _add_digest_flags(p: argparse.ArgumentParser, default_core_mode: str) -> None:
    p.add_argument("--archive-db", type=Path, default=None, help="Optional path to read-only archive.db")
    p.add_argument("--no-hydrate", action="store_true", help="Disable Stage 2 pre-tick digest hydration")
    p.add_argument("--core-mode", choices=["anchor", "full", "none"], default=default_core_mode, help="Core digest prefix level")
    p.add_argument("--packet-budget", type=int, default=2200, help="Token budget for dynamic hydrated slice packet")
    p.add_argument("--no-digest-delta", action="store_true", help="Disable Stage 3 post-Falsifier delta recompilation")


def main() -> None:
    parser = argparse.ArgumentParser(description="Single-loop prefix-cache-friendly epistemic runner")
    sub = parser.add_subparsers(dest="command", required=True)

    p_run = sub.add_parser("run", help="Run direct API sequential loop (gemini or ollama)")
    p_run.add_argument("--backend", choices=["gemini", "ollama"], default="gemini")
    p_run.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    p_run.add_argument("--slice-name", default=DEFAULT_SLICE)
    p_run.add_argument("--domain", default=DEFAULT_SLICE)
    p_run.add_argument("--limit", type=int, default=20)
    p_run.add_argument("--batch-size", type=int, default=10)
    p_run.add_argument("--lifter-model", default="gemini-2.5-flash-lite")
    p_run.add_argument("--scientist-model", default="gemini-2.5-flash")
    p_run.add_argument("--falsifier-model", default="gemini-2.5-flash")
    p_run.add_argument("--ollama-url", default="http://127.0.0.1:11434")
    p_run.add_argument("--metrics-out", type=Path, default=DEFAULT_STATE_DIR / "metrics.json")
    _add_digest_flags(p_run, default_core_mode="full")

    p_step = sub.add_parser("step", help="Deterministic stateless step prepare/apply helper")
    p_step.add_argument(
        "step_action",
        choices=["prepare-lifter", "apply-lifter", "prepare-scientist-nodes", "apply-scientist", "apply-falsifier"],
    )
    p_step.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    p_step.add_argument("--slice-name", default=DEFAULT_SLICE)
    p_step.add_argument("--domain", default=DEFAULT_SLICE)
    p_step.add_argument("--limit", type=int, default=10)
    p_step.add_argument("--chunk-ids", default="")
    p_step.add_argument("--node-ids", default="")
    p_step.add_argument("--batch-tag", default="b1")
    p_step.add_argument("--response-file", type=Path)
    p_step.add_argument("--state-dir", type=Path, default=DEFAULT_STATE_DIR)
    _add_digest_flags(p_step, default_core_mode="anchor")

    args = parser.parse_args()
    if args.command == "run":
        run_direct_loop(args)
    else:
        cmd_step(args)


if __name__ == "__main__":
    main()
