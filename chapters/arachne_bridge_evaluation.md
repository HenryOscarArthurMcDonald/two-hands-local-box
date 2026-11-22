# Arachne / Portable Knowledge Graph <-> `corpus.db` Mutual Evaluation Report

> **Database:** `./data/corpus.db` | **Archive Link:** `{'available': True, 'conversations': 342, 'turns': 8826, 'ouroboros_turns': 29, 'max_ouroboros_turn_id': 9158}`  
> **Core Digest Size:** `24,428` bytes (`23.86 KB`, in 15–30 KB target window: `True`)  
> **`digest_state` Watermarks Tracked:** `17` rows | **Delta No-Op Recompiles:** `0`

---

## 1. Mutual Evaluation Summary (Two Halves of One Coin)

| Criterion | Half Evaluated | Result | Target |
| :--- | :---: | :---: | :---: |
| Pinned `core_digest.md` Footprint | Digest Layer 1 | **`23.86 KB`** | `15–30 KB` |
| Avg Hydrated Working-Memory Packet | Arachne Recall | **`2091.0` tokens** | `<= 2200` tokens (`100%` within budget) |
| Token Compression vs Raw Top-15 `FTS5` RAG | Arachne Recall | **`-72.2%`** (`150,457 -> 41,820`) | Cut noise bloat |
| Median/Mean Hybrid Hydration Latency | Arachne Recall | **`301.78 ms`** | Sub-second tick hydration |
| Chunk / Archive Provenance Preservation | Arachne <-> Corpus | **`20/20`** (`19/20` full `turn_id`+`sha256`) | `chunk_id/chat_id/turn_id/sha256` |
| Pitfall Suppression + `pivoted_to` Gating | Corpus Truth Gate | **`15/15` (`100.0%`)** | Zero unmasked `FALSIFIED` leaks |
| Stage 4 `concept_bridges` Vocabulary Probes | Loop Closure | **`4/4`** | Bidirectional legacy recall |
| Active Branch `max_dry_hops=3` Compliance | Corpus Halting | **`0` violations** | `0` runaway dry branches |

## 2. Stage 4 Vocabulary-Drift Probes (`concept_bridges` -> `archive.db` + `corpus.db`)

| Probe | Bridges Triggered | Archive/Turn Provenance Hits | Expanded Concepts Matched | Status |
| :--- | :---: | :---: | :--- | :---: |
| Transformer Stateless Pass <-> Legacy Mousetrap Metaphor | 8 | 7 | `mousetrap, feedback loop, stateless` | **PASS** |
| PDA Intolerance of Uncertainty <-> Early ACP / DAT Framing | 2 | 8 | `anti-conformance, acp, dat, causal entropy` | **PASS** |
| Optical Refraction Phase Superposition <-> Early Interference Notes | 1 | 2 | `phase superposition` | **PASS** |
| Information Entropy <-> Compression / Landauer Bounds | 5 | 6 | `lossy, compression` | **PASS** |

## 3. Per-Question Tier-Gated Hydration & Compression Audit (`20` Cross-Domain Questions)

| ID | Ring | Domain | Raw RAG Tok | Hydrated Tok | Latency (ms) | Suppressed Raw | Neg Constraints | Verified Inv | Pitfall Guarded |
| :- | :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| #1 | Ring 1 | `physics` | 6894 | 2180 | 387.13 | 5 | 10 | 10 | **PASS** |
| #2 | Ring 1 | `physics` | 6572 | 2167 | 354.78 | 1 | 8 | 10 | **PASS** |
| #3 | Ring 1 | `physics` | 7358 | 2167 | 368.7 | 0 | 7 | 10 | **PASS** |
| #4 | Ring 1 | `physics` | 7072 | 2091 | 271.97 | 2 | 10 | 10 | **PASS** |
| #5 | Ring 1 | `physics` | 6655 | 2093 | 337.14 | 2 | 10 | 10 | **PASS** |
| #6 | Ring 2 | `formal_math` | 6841 | 1755 | 299.56 | 0 | 2 | 10 | **PASS** |
| #7 | Ring 2 | `formal_math` | 9418 | 2133 | 252.9 | 0 | 10 | 10 | **PASS** |
| #8 | Ring 2 | `formal_math` | 7857 | 2148 | 276.24 | 1 | 7 | 10 | **PASS** |
| #9 | Ring 2 | `formal_math` | 9321 | 2125 | 287.42 | 1 | 8 | 10 | **PASS** |
| #10 | Ring 2 | `formal_math` | 6677 | 2103 | 261.27 | 1 | 9 | 10 | **PASS** |
| #11 | Ring 3 | `ai_systems` | 7629 | 2165 | 271.52 | 0 | 5 | 10 | **PASS** |
| #12 | Ring 3 | `ai_systems` | 6274 | 2122 | 472.47 | 2 | 7 | 10 | **PASS** |
| #13 | Ring 3 | `ai_systems` | 5970 | 1841 | 287.07 | 0 | 2 | 10 | **PASS** |
| #14 | Ring 3 | `ai_systems` | 14380 | 2083 | 279.42 | 0 | 6 | 10 | **PASS** |
| #15 | Ring 3 | `ai_systems` | 6607 | 2109 | 307.92 | 0 | 6 | 10 | **PASS** |
| #16 | Ring 4A | `bio_neuro_psych` | 7025 | 2078 | 264.67 | 1 | 6 | 10 | **PASS** |
| #17 | Ring 4A | `bio_neuro_psych` | 7295 | 2097 | 251.82 | 0 | 10 | 10 | **PASS** |
| #18 | Ring 4A | `bio_neuro_psych` | 6605 | 2118 | 301.96 | 2 | 10 | 10 | **PASS** |
| #19 | Ring 4A | `bio_neuro_psych` | 7124 | 2114 | 246.94 | 0 | 10 | 10 | **PASS** |
| #20 | Ring 4A | `bio_neuro_psych` | 6883 | 2131 | 254.74 | 2 | 6 | 10 | **PASS** |
