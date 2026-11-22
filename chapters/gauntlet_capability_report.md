# 20-Step Multi-Turn Contradiction & Capability-Floor Gauntlet Report

**Task:** Private Kestrel-7 Modular Assembly Line (20 sequential stateful steps, 4 non-textbook trap rules: `TRAP_1_BOW`, `TRAP_2_VALVE`, `TRAP_3_DERATE`, `TRAP_4_MASS` ceiling `420.0 g`).  
**Arms:** (a) `ungated_full_history` (unbounded), (b) `matched_token_hybrid_rag` (`<= 2,200` tokens, BM25+TF-IDF RRF, no `[FALSIFIED]` tier), (c) `sqlite_gated` (`<= 2,200` tokens, 3-table SQLite `[FALSIFIED]` ledger + deterministic mass register).

## Summary Table (Live Runs Only — Zero Extrapolated Tiers)

| Model | Constraint Mode | Arm | Step Accuracy | Contradiction Recurrence | JSON Valid | Input Tok | Output Tok | Thoughts Tok | Total Tok | Max Turn In | Wall Clock |
| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| `cloud:flash_lite` | `prompt_only` | `ungated_full_history` | **55.0%** (11/20) | **50.0%** (4/8) | 100.0% | 37,232 | 1,075 | 4304 | 42,611 | 3,199 | 30.1 s |
| `cloud:flash_lite` | `prompt_only` | `matched_token_hybrid_rag` | **60.0%** (12/20) | **37.5%** (3/8) | 100.0% | 22,285 | 1,157 | 12812 | 36,254 | 1,350 | 49.7 s |
| `cloud:flash_lite` | `prompt_only` | `sqlite_gated` | **85.0%** (17/20) | **12.5%** (1/8) | 100.0% | 12,647 | 971 | 4921 | 18,539 | 732 | 35.0 s |
| `cloud:flash` | `prompt_only` | `ungated_full_history` | **85.0%** (17/20) | **0.0%** (0/8) | 100.0% | 39,051 | 1,362 | 17942 | 58,355 | 3,086 | 208.2 s |
| `cloud:flash` | `prompt_only` | `matched_token_hybrid_rag` | **80.0%** (16/20) | **12.5%** (1/8) | 100.0% | 23,788 | 1,273 | 20728 | 45,789 | 1,333 | 225.0 s |
| `cloud:flash` | `prompt_only` | `sqlite_gated` | **85.0%** (17/20) | **0.0%** (0/8) | 100.0% | 12,647 | 1,238 | 17214 | 31,099 | 732 | 219.9 s |
| `llama2:latest (7B)` | `unconstrained` | `ungated_full_history` | **0.0%** (0/20) | **100.0%** (8/8) | 0.0% | 39,286 | 0 | 0 | 39,286 | 0 | 2400.4 s |
| `llama2:latest (7B)` | `unconstrained` | `matched_token_hybrid_rag` | **10.0%** (2/20) | **87.5%** (7/8) | 20.0% | 24,890 | 0 | 0 | 24,890 | 0 | 2334.8 s |
| `llama2:latest (7B)` | `unconstrained` | `sqlite_gated` | **40.0%** (8/20) | **100.0%** (8/8) | 85.0% | 10,728 | 0 | 0 | 10,728 | 0 | 1543.7 s |
