"""Live workflow runner for A/B benchmark using Antigravity agent primitives."""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

_ENV_HOME = os.environ.get("CORPUS_HOME", "").strip()
WORKSPACE_ROOT = Path(_ENV_HOME).expanduser().resolve() if _ENV_HOME else Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WORKSPACE_ROOT / "scripts"))

from benchmark_ab import (
    DEFAULT_DB_PATH,
    DEFAULT_REPORT_PATH,
    DEFAULT_RESULTS_PATH,
    SYSTEM_PROMPT,
    TEST_QUESTIONS,
    compute_aggregate_results,
    compute_cost,
    count_tokens,
    evaluate_rubric,
    generate_markdown_report,
    log_benchmark_verification_in_db,
    retrieve_arm_a,
    retrieve_arm_b,
)
from db_utils import get_connection

log("Starting live A/B benchmark across 20 questions...")
conn = get_connection(DEFAULT_DB_PATH)

# We run questions in batches of 5 to maintain stability
BATCH_SIZE = 5
results_qs = []

for batch_idx in range(0, len(TEST_QUESTIONS), BATCH_SIZE):
    batch = TEST_QUESTIONS[batch_idx : batch_idx + BATCH_SIZE]
    log(f"--- Processing Batch {batch_idx // BATCH_SIZE + 1} (Questions {batch_idx + 1} to {batch_idx + len(batch)}) ---")
    
    # 1. Prepare prompts
    items_a = []
    items_b = []
    for q in batch:
        raw_ctx, tok_in_a = retrieve_arm_a(conn, q["question"])
        comp_ctx, tok_in_b = retrieve_arm_b(conn, q["question"])
        
        prompt_a = f"{SYSTEM_PROMPT}\n\nRetrieved Raw Context:\n{raw_ctx}\n\nQuestion: {q['question']}"
        prompt_b = f"{SYSTEM_PROMPT}\n\nRetrieved Epistemic Subgraph:\n{comp_ctx}\n\nQuestion: {q['question']}"
        
        items_a.append({
            "q": q,
            "prompt": prompt_a,
            "tok_in": count_tokens(prompt_a)
        })
        items_b.append({
            "q": q,
            "prompt": prompt_b,
            "tok_in": count_tokens(prompt_b)
        })
        
    # 2. Run Arm A in parallel
    phase(f"Batch {batch_idx // BATCH_SIZE + 1}: Arm A (Raw RAG Baseline)")
    async def run_arm_a(item):
        a = agent(
            prompt=item["prompt"],
            schema={"type": "string"},
            role=f"ArmA_Q{item['q']['id']}",
            model="inherit"
        )
        t0 = time.perf_counter()
        ans = await a(item["prompt"])
        t1 = time.perf_counter()
        return {
            "item": item,
            "answer": ans,
            "latency_s": t1 - t0,
        }
        
    res_a = await parallel(items_a, run_arm_a)
    
    # 3. Run Arm B in parallel
    phase(f"Batch {batch_idx // BATCH_SIZE + 1}: Arm B (Compiled Epistemic Kernel)")
    async def run_arm_b(item):
        b = agent(
            prompt=item["prompt"],
            schema={"type": "string"},
            role=f"ArmB_Q{item['q']['id']}",
            model="inherit"
        )
        t0 = time.perf_counter()
        ans = await b(item["prompt"])
        t1 = time.perf_counter()
        return {
            "item": item,
            "answer": ans,
            "latency_s": t1 - t0,
        }
        
    res_b = await parallel(items_b, run_arm_b)
    
    # 4. Evaluate batch
    for ra, rb in zip(res_a, res_b):
        q = ra["item"]["q"]
        ans_a = ra["answer"]
        ans_b = rb["answer"]
        
        tok_out_a = count_tokens(ans_a)
        tok_out_b = count_tokens(ans_b)
        
        eval_a = evaluate_rubric(q, ans_a)
        eval_b = evaluate_rubric(q, ans_b)
        
        results_qs.append({
            "id": q["id"],
            "ring": q["ring"],
            "domain": q["domain"],
            "question": q["question"],
            "is_falsified_pitfall": q["is_falsified_pitfall"],
            "falsified_node_id": q["falsified_node_id"],
            "verified_node_id": q["verified_node_id"],
            "arm_a": {
                "input_tokens": ra["item"]["tok_in"],
                "output_tokens": tok_out_a,
                "total_tokens": ra["item"]["tok_in"] + tok_out_a,
                "latency_s": round(ra["latency_s"], 2),
                "cost_usd": compute_cost(ra["item"]["tok_in"], tok_out_a),
                "answer": ans_a,
                "evaluation": eval_a,
            },
            "arm_b": {
                "input_tokens": rb["item"]["tok_in"],
                "output_tokens": tok_out_b,
                "total_tokens": rb["item"]["tok_in"] + tok_out_b,
                "latency_s": round(rb["latency_s"], 2),
                "cost_usd": compute_cost(rb["item"]["tok_in"], tok_out_b),
                "answer": ans_b,
                "evaluation": eval_b,
            }
        })
        log(f"Q#{q['id']} ({q['domain']}): Arm A lat={ra['latency_s']:.2f}s acc={'PASS' if eval_a['is_accurate'] else 'FAIL'} | Arm B lat={rb['latency_s']:.2f}s acc={'PASS' if eval_b['is_accurate'] else 'FAIL'}")

# 5. Compute aggregates and save
phase("Compilation & Reporting")
results = compute_aggregate_results(results_qs)
results["model_name"] = "Gemini 3.8 Flash (High)"
results["db_path"] = str(DEFAULT_DB_PATH)

DEFAULT_RESULTS_PATH.write_text(json.dumps(results, indent=2), encoding="utf-8")
log(f"Saved benchmark results to {DEFAULT_RESULTS_PATH}")

generate_markdown_report(results, DEFAULT_REPORT_PATH)
log(f"Generated comprehensive report at {DEFAULT_REPORT_PATH}")

log_benchmark_verification_in_db(conn, results)
conn.close()

d = results["aggregates"]["delta"]
a = results["aggregates"]["arm_a"]
b = results["aggregates"]["arm_b"]
log("=" * 60)
log("LIVE A/B BENCHMARK COMPLETE")
log(f"Input Token Reduction:   {d['pct_input_token_reduction']:.1f}% ({a['total_input_tokens']:,} -> {b['total_input_tokens']:,})")
log(f"Output Token Reduction:  {d['pct_output_token_reduction']:.1f}% ({a['total_output_tokens']:,} -> {b['total_output_tokens']:,})")
log(f"Total Token Reduction:   {d['pct_total_token_reduction']:.1f}% ({a['total_tokens']:,} -> {b['total_tokens']:,})")
log(f"Latency Speedup:         {d['pct_latency_reduction']:.1f}% ({a['avg_latency_s']:.2f}s -> {b['avg_latency_s']:.2f}s)")
log(f"Cost Savings:            {d['pct_cost_reduction']:.1f}% (${a['total_cost_usd']:.4f} -> ${b['total_cost_usd']:.4f})")
log(f"Epistemic Accuracy:      Arm A: {a['accuracy_rate']*100:.1f}% | Arm B: {b['accuracy_rate']*100:.1f}% (+{d['accuracy_gain_pct']:.1f}% gain)")
log("=" * 60)
