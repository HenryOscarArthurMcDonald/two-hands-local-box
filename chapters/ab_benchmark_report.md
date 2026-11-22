# Empirical A/B Benchmark Report: Raw RAG Baseline vs. Compiled Epistemic Kernel

**Date:** 2026-11-19  
**Database:** `./data/corpus.db`  
**Model:** `Gemini 3.8 Flash (High)`  
**Benchmark Scope:** Rings 1-4A (`physics`, `formal_math`, `ai_systems`, `bio_neuro_psych`)  
**Verification Scope:** `verification_scope = 'empirical_benchmark'`  

---

## 1. Executive Summary & Core Findings

This empirical benchmark evaluates replacing unstructured high-volume chunk retrieval (**Arm A: Raw RAG Baseline**) with a compiled 2-hop epistemic subgraph (**Arm B: Compiled Kernel**) across 20 cross-domain questions.

### Key Empirical Takeaways (Post-F1.1 / F1.3 Audit):
1. **Input Token Reduction:** **55.2% reduction** in input tokens (from **140,280** down to **62,814**, saving **77,466 tokens**).
2. **Estimated API Cost (Visible Tokens Only):** **43.4% reduction** (from **$0.01760** to **$0.00996** across 20 questions). Note: provider `thoughts_token_count` was not separately logged in the legacy capture.
3. **Wall-Clock Latency Trade-Off:** Arm B was **34.4% slower (+205.32 s total)** (`29.84 s` vs. `40.11 s/Q`), reflecting deeper structured reasoning/thinking time rather than net speedup.
4. **Honest Rubric Accuracy:** Arm A achieved **95.0%** (`19/20`, pitfall avoidance `100.0%`) vs. Arm B **100.0%** (`20/20`, pitfall avoidance `100.0%`). At $N=20$, a 1-question separation is not statistically significant ($p = 1.00$ two-sided exact McNemar).
5. **Amortized Compilation Break-Even ($Q^*$):** Under $C_{\text{total}}(Q) = C_{\text{compile}} + Q \cdot C_{\text{query}}$, saving **3,859.6 total tokens/query** against an estimated single-loop compilation cost of **4,385,729 tokens** (`893` nodes × `4,911.2` tokens/node from `single_loop_pilot_report.md`) requires **$Q^* \approx 1,137$ queries** to break even (or **$Q^* \approx 143,342$ queries** against historical Wave 1 swarm compilation rates).

---

## 2. Summary Comparison Table

| Metric | Arm A (Raw RAG Baseline) | Arm B (Compiled Epistemic Kernel) | Exact Improvement / Delta |
| :--- | :--- | :--- | :--- |
| **Retrieval Format** | Top 15 Raw Chunks (FTS5 BM25) | 2-Hop Epistemic Subgraph (SQLite) | Structured Epistemic Pruning |
| **Avg Input Tokens / Q** | 7014.0 tokens | 3140.7 tokens | **55.2% reduction** |
| **Total Input Tokens (20 Qs)** | 140,280 tokens | 62,814 tokens | **-77,466 tokens (55.2% cut)** |
| **Avg Visible Output Tokens / Q** | 446.7 tokens | 460.4 tokens | **+13.8 tokens / Q** |
| **Total Visible Output Tokens (20 Qs)** | 8,934 tokens | 9,209 tokens | **+275 tokens** |
| **Provider `thoughts_token_count`** | unreported (not split in legacy JSON) | unreported (not split in legacy JSON) | Logged separately when provided |
| **Total Visible Tokens Consumed** | 149,214 tokens | 72,023 tokens | **51.7% reduction (-77,191 tokens)** |
| **Avg Wall-Clock Latency** | 29.84 s | 40.11 s | **+10.27 s / Q** |
| **Total Wall-Clock Latency** | 596.79 s | 802.11 s | **34.4% slower (+205.32 s total)** |
| **Estimated API Cost (USD)** | $0.01760 | $0.00996 | **43.4% savings** |
| **Amortized Break-Even $Q^*$ (Single-Loop)** | — | — | **1,137 queries** |
| **Falsified Pitfall Avoidance** | 100.0% | 100.0% | **+0.0% margin** |
| **Invariant Grounding Rate** | 95.0% | 100.0% | **+5.0% margin** |
| **Overall Epistemic Accuracy** | **95.0%** | **100.0%** | **+5.0% margin** |

---

## 3. Ring-by-Ring Empirical Breakdown

The test set comprises 20 cross-domain questions spanning Rings 1-4A (15 pitfall probes and 5 structural invariant probes):

### Ring 1: Physics & Spacetime Invariants

| ID | Domain | Falsified Misconception / Invariant | Arm A Tokens | Arm B Tokens | Arm A Acc | Arm B Acc | Arm B Speedup |
| :- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| #1 | `physics` | FALSIFIED #2 | 7522 | 3347 | PASS | **PASS** | 55.8% |
| #2 | `physics` | FALSIFIED #19 | 7169 | 3445 | PASS | **PASS** | 32.0% |
| #3 | `physics` | FALSIFIED #15 | 7717 | 3454 | PASS | **PASS** | 6.6% |
| #4 | `physics` | INVARIANT #1 | 7681 | 3749 | PASS | **PASS** | -4.1% |
| #5 | `physics` | FALSIFIED #4 | 7185 | 3447 | PASS | **PASS** | -10.8% |

### Ring 2: Formal Mathematics, Logic & Cobordisms

| ID | Domain | Falsified Misconception / Invariant | Arm A Tokens | Arm B Tokens | Arm A Acc | Arm B Acc | Arm B Speedup |
| :- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| #6 | `formal_math` | FALSIFIED #360 | 7426 | 3748 | PASS | **PASS** | 27.6% |
| #7 | `formal_math` | FALSIFIED #362 | 7325 | 3793 | PASS | **PASS** | -7.5% |
| #8 | `formal_math` | FALSIFIED #353 | 8414 | 3343 | PASS | **PASS** | -35.4% |
| #9 | `formal_math` | INVARIANT #301 | 7598 | 3697 | PASS | **PASS** | -285.7% |
| #10 | `formal_math` | FALSIFIED #367 | 7242 | 3601 | PASS | **PASS** | 7.4% |

### Ring 3: AI Architectures, Cybernetics & Mailbox Routing

| ID | Domain | Falsified Misconception / Invariant | Arm A Tokens | Arm B Tokens | Arm A Acc | Arm B Acc | Arm B Speedup |
| :- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| #11 | `ai_systems` | FALSIFIED #548 | 8198 | 3927 | PASS | **PASS** | -156.4% |
| #12 | `ai_systems` | FALSIFIED #554 | 6916 | 3096 | PASS | **PASS** | -223.9% |
| #13 | `ai_systems` | FALSIFIED #620 | 6587 | 4155 | PASS | **PASS** | -243.8% |
| #14 | `ai_systems` | INVARIANT #501 | 7088 | 3872 | PASS | **PASS** | -122.8% |
| #15 | `ai_systems` | INVARIANT #510 | 7201 | 3522 | PASS | **PASS** | -170.5% |

### Ring 4A: Neurobiology, Genetics & Homeostatic Systems

| ID | Domain | Falsified Misconception / Invariant | Arm A Tokens | Arm B Tokens | Arm A Acc | Arm B Acc | Arm B Speedup |
| :- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| #16 | `bio_neuro_psych` | FALSIFIED #710 | 7577 | 3440 | FAIL | **PASS** | 22.1% |
| #17 | `bio_neuro_psych` | FALSIFIED #712 | 7909 | 3705 | PASS | **PASS** | 55.2% |
| #18 | `bio_neuro_psych` | FALSIFIED #713 | 7264 | 3439 | PASS | **PASS** | -40.4% |
| #19 | `bio_neuro_psych` | FALSIFIED #711 | 7717 | 3257 | PASS | **PASS** | 41.1% |
| #20 | `bio_neuro_psych` | INVARIANT #702 | 7478 | 3986 | PASS | **PASS** | 48.2% |

---

## 4. Data-Driven Failure & Latency Audit

### A. Observed Rubric Discrepancies (Derived Strictly from `benchmark_results.json`)
- **Arm A FAIL on Question 16 (`bio_neuro_psych`):** `avoided_pitfall=True`, `cited_invariant=False`, `triggered_negative=[]`, `triggered_positive=[]`.
- **Arm B (Compiled Kernel):** 0/20 rubric failures (`20/20` passed).

### B. Latency & Amortization Caveats (F1.1 / F1.3)
- **Latency Trade-Off:** Aggregate Arm B wall-clock latency was **34.4% slower (+205.32 s total)** (`596.79 s` vs. `802.11 s`), driven by heavier reasoning latency on Ring 2/3 questions even while input tokens dropped `55.2%`.
- **Amortization ($Q^*$):** Query-time savings of `3,859.6` visible tokens/query require **`Q* ≈ 1,137` queries** to amortize single-loop compilation of `893` nodes (`~4,385,729` tokens), or **`Q* ≈ 143,342` queries** at Wave 1 swarm rates.
- **Circularity & Statistical Power:** Because the 20 test items derive from textbook/in-corpus nodes and run on a strong frontier model, `19/20` vs. `20/20` accuracy is statistically indistinguishable from parity ($p = 1.00$). See `scripts/benchmark_gauntlet.py` for an out-of-distribution private stateful multi-turn test.

---

## 5. Per-Question Detailed Audit Table

| ID | Question | Arm A Input Tok | Arm B Input Tok | Arm A Latency | Arm B Latency | Arm A Avoid Pitfall | Arm B Avoid Pitfall | Arm A Invariant | Arm B Invariant |
| :- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| #1 | Does a photon possess a valid inertial rest frame where... | 7058 | 2968 | 35.72s | 15.80s | YES | YES | YES | YES |
| #2 | Does light slow down in water or glass because electron... | 6714 | 3010 | 23.91s | 16.26s | YES | YES | YES | YES |
| #3 | Does the Higgs field act like physical viscous friction... | 7355 | 3031 | 19.81s | 18.50s | YES | YES | YES | YES |
| #4 | How does Noether's Theorem relate continuous spacetime ... | 7233 | 3188 | 18.47s | 19.23s | YES | YES | YES | YES |
| #5 | Does time conversion via the speed of light c mean time... | 6817 | 3047 | 16.50s | 18.28s | YES | YES | YES | YES |
| #6 | Can Gödel's Incompleteness Theorem be applied to human ... | 6972 | 3236 | 29.76s | 21.55s | YES | YES | YES | YES |
| #7 | Can the Atiyah-Segal TQFT cobordism functor Z: Bord_n -... | 6892 | 3303 | 31.32s | 33.68s | YES | YES | YES | YES |
| #8 | Can an Agent-Based Model validly compute force by addin... | 8001 | 2862 | 25.58s | 34.64s | YES | YES | YES | YES |
| #9 | What does the Curry-Howard-Lambek isomorphism establish... | 7109 | 3274 | 28.29s | 109.11s | YES | YES | YES | YES |
| #10 | Can cosmological baryon asymmetry (10^9 + 1 vs 10^9) be... | 6840 | 3086 | 29.75s | 27.56s | YES | YES | YES | YES |
| #11 | Does Transformer softmax attention dot-product weightin... | 7760 | 3474 | 25.00s | 64.11s | YES | YES | YES | YES |
| #12 | Does a toy 12x12x12 discrete 3D fluid grid establish an... | 6407 | 2680 | 20.72s | 67.11s | YES | YES | YES | YES |
| #13 | Do unit test passes on a bounded SQLite mailbox (cell_r... | 6126 | 3671 | 21.52s | 73.98s | YES | YES | YES | YES |
| #14 | Why is an autoregressive Transformer forward pass struc... | 6572 | 3404 | 30.67s | 68.32s | YES | YES | YES | YES |
| #15 | How does Goodhart's law manifest in RLHF reward hacking... | 6762 | 3027 | 28.10s | 76.01s | YES | YES | YES | YES |
| #16 | Is the genetic code structured by 1-3-5-8 digital root ... | 7169 | 3007 | 26.90s | 20.95s | YES | YES | NO | YES |
| #17 | Does psychological trauma hard-code declarative memorie... | 7427 | 3177 | 70.07s | 31.42s | YES | YES | YES | YES |
| #18 | Does the mammalian autonomic nervous system operate lik... | 6766 | 2914 | 27.47s | 38.58s | YES | YES | YES | YES |
| #19 | Can Orch-OR quantum superposition in brain microtubules... | 7256 | 2865 | 25.91s | 15.27s | YES | YES | YES | YES |
| #20 | How does hippocampal glucocorticoid receptor negative f... | 7044 | 3590 | 61.32s | 31.75s | YES | YES | YES | YES |

---

## 6. Empirical Boundary Note for Nodes #620 & #671 (`empirical_benchmark`)

Nodes `#620` (Logical-Ring Reference Mailbox) and `#671` (Quorum-Sensing Batch Scheduling) carry logged `verification_scope = 'empirical_benchmark'` rows referencing `scripts/benchmark_ab.py:20_cross_domain_rings1_4a`, while remaining at `SIM_CONSISTENT` in `nodes` until distributed multi-host transport and small-model multi-turn benchmarks are validated:
- **Empirical Evidence:** Across 20 cross-domain queries, Arm B achieved **55.2% input token reduction** and **34.4% slower (+205.32 s total)**, with rubric accuracy **95.0% → 100.0%** (amortized break-even $Q^* \approx 1,137$ queries).

---
*Report automatically generated by `scripts/benchmark_ab.py`.*