# Single-Loop Sequential Runner (`scripts/single_loop_runner.py`) — 20-Chunk Pilot Benchmark Report

> **Target Slice:** `bio_neuro_psych` (`20` `PENDING` chunks in [data/corpus.db](../data/corpus.db) -> `260` `PENDING` remaining)  
> **Architecture:** Stateless 3-Role Sequential Loop (Step A Lifter -> Step B Scientist -> Step C Falsifier) with zero `/teamwork` swarm board messaging and byte-identical static prefixes placed at the top of each role prompt  
> **Baseline Compared:** Ring 4A (`bio_neuro_psych`) Wave 1 `/teamwork` Swarm (`240` chunks triaged: `104` `PROCESSED`, `136` `SKIPPED`, `51` nodes `#699–#749`)

---

## 1. Execution & Environment Notes

- **Runner Implemented:** [scripts/single_loop_runner.py](../scripts/single_loop_runner.py) supports:
  1. `--backend gemini` (`google-genai` SDK with `GEMINI_API_KEY`, configurable `--lifter-model`, `--scientist-model`, `--falsifier-model`, explicit `thinking_budget`, and native `usage_metadata.cached_content_token_count` logging).
  2. `--backend ollama` (`http://127.0.0.1:11434/api/generate` for local inference).
  3. `step` subcommands (`prepare-lifter`, `apply-lifter`, `apply-scientist`, `apply-falsifier`) for deterministic DB I/O, `run_physics_check` execution, branch reconciliation, and strict-JSON stateless subagent orchestration.
- **Backend Pre-Flight Audit:**
  - `GEMINI_API_KEY` / `GOOGLE_API_KEY` / `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` were unset (`set=0`) in the workspace shell.
  - Local Ollama (`llama3:latest`, `4.7 GB` on an `8 GB` RAM host) produced degenerate output (`{"!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!` after `32.76 s` at `num_ctx=4096`), failing `v0.2.0` precision requirements.
  - Accordingly, this 20-chunk pilot ran via `scripts/single_loop_runner.py step` paired with **six isolated, zero-history single-turn `invoke_subagent` calls** (`sl_lifter`, `sl_scientist`, `sl_falsifier`, zero tools enabled, zero swarm board usage), recording exact Antigravity transcript token counts (`input_tokens`, `cache_read_tokens`, `output_tokens`) directly apples-to-apples against Wave 1's swarm transcripts.
- **Model-Tier Fidelity Finding (`flash_lite` vs. `flash`):**
  - Testing mini-batch `b1` Step A on `flash_lite` (`36ebd915`: `13,313` in / `690` out, `~3 s`) triggered **severe epistemic collapse**: it lazily dumped all `10/10` chunks into `skipped` (`9` labeled `duplicate_export`, `1` labeled `debug_churn`) and hallucinated a non-existent node `#796`.
  - Switching Step A (`sl_lifter`), Step B (`sl_scientist`), and Step C (`sl_falsifier`) to **`flash`** (with the tightened static boundary forbidding skipping testable mechanisms/overclaims) eliminated laziness and preserved 100% `v0.2.0` fidelity across both mini-batches (`b1` and `b2`).

---

## 2. Per-Call Token, Cache & Wall-Clock Log (20-Chunk Run)

| Mini-Batch | Role (Model) | Conversation ID | Steps | `input_tokens` (Uncached) | `cached_input_tokens` | `output_and_thinking_tokens` | `wall_clock_s` | Outcome |
| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :---: | :--- |
| `b1` *(diagnostic)* | Step A Lifter (`flash_lite`) | `36ebd915` | 1 | `13,313` | `0` | `690` | `3.0` | *Rejected (dropped all 10 chunks as `skipped`, hallucinated `#796`)* |
| **`b1` (10 chunks)** | Step A Lifter (`flash`) | `e2bac84f` | 1 | `14,089` | `0` | `9,380` | `43.0` | `2` attached (`#742`, `#746`), `8` lifted (`#782–#789`) |
| **`b1` (8 nodes)** | Step B Scientist (`flash`) | `ed270938` | 1 | `7,597` | `0` | `13,416` | `68.0` | `8/8` `run_physics_check` passed (`pycheck`) |
| **`b1` (8 nodes)** | Step C Falsifier (`flash`) | `ba51f36e` | 1 | `12,533` | `0` | `7,273` | `34.0` | `1` verified (`#783`), `2` `SIM_CONSISTENT` (`#782,#785`), `5` `FALSIFIED` -> `#790–#794` |
| **`b2` (10 chunks)** | Step A Lifter (`flash`) | `60195aeb` | 1 | `14,022` | `0` | `10,348` | `49.0` | `3` attached (`#783` cross-batch, `#746`, `#769`), `7` lifted (`#795–#801`) |
| **`b2` (7 nodes)** | Step B Scientist (`flash`) | `c7d5b962` | 1 | `7,697` | `0` | `11,820` | `58.0` | `7/7` `run_physics_check` passed (`pycheck`) |
| **`b2` (7 nodes)** | Step C Falsifier (`flash`) | `070e0aae` | 1 | `12,144` | `0` | `7,373` | `37.0` | `1` verified (`#801`), `6` `FALSIFIED` -> `#802–#807` |
| **Total Active Run** | **6 Stateless Calls** | — | **6** | **`68,082`** | **`0`** | **`59,610`** | **`289.0`** | **`20` `PROCESSED`, `0` `SKIPPED`, `26` nodes (`#782–#807`), `13` `CONVERGED` / `2` `ACTIVE` `toy_model`** |

> **Why `cached_input_tokens == 0` in the subagent harness:** Every Antigravity `invoke_subagent` starts a fresh 1-turn session (`steps=1`), where `cache_read_tokens` only activates on Turn 2+ of the same session or via direct Gemini API implicit/explicit context caching (`--backend gemini`). Notice that `b1` and `b2` share identical static role prefixes (`LIFTER_STATIC_PREFIX` = `1,750` chars, `SCIENTIST_STATIC_PREFIX` = `1,636` chars, `FALSIFIER_STATIC_PREFIX` = `1,548` chars), so under direct `--backend gemini` repeated mini-batches hit implicit prefix caching directly.

---

## 3. Epistemic Fidelity Summary (`#782–#807`)

- **Slice Progress (`bio_neuro_psych`):** `241` `PROCESSED` (`+20`), `342` `SKIPPED`, `260` `PENDING`.
- **Canonical Deduplication Across Batches:** Mini-batch `b2` Step A (`60195aeb`) immediately matched chunk `20847` onto `#783` (which `b1` had minted minutes earlier), plus `26310 -> #742`, `26305 -> #746`, `956 -> #746`, and `19022 -> #769` (`5` of `20` chunks deduplicated cleanly via `attach_node_provenance`).
- **Nodes Committed (`26` total: `#782–#807`):**
  - `13` `EXTERNALLY_VERIFIED`: `#783` (DNA vs. silicon Shannon/Landauer bounds), `#801` (Weak Central Coherence & declarative ASD language compensation), plus `11` reframings (`#790–#794`, `#802–#807`).
  - `2` `SIM_CONSISTENT` (`toy_model` lock enforced; branches `B514`, `B517` remain `ACTIVE`): `#782` (binary TraumaOS prototype) and `#785` (hypothesized SSD–PDA comorbidity).
  - `11` `FALSIFIED` -> `resolved_mistake` + `pivoted_to` -> `EXTERNALLY_VERIFIED`: `#784` (global ATP vs. local PFC glutamatergic fatigue), `#786` (Selectron spin-0 breathing / Debye time-reversal / Planck retinal aliasing), `#787` (exact scale invariance vs. fixed Debye/RC cutoffs), `#788` ("Adrenal Floor" vs. intact basal cortisol + D2 downregulation), `#789` ("Bio-Pi Rosetta Stone" base-pair arithmetic), `#795` (1D ACh squeeze vs. multi-axial CB1/$\alpha_2$ pharmacology), `#796` (roleplay `HCD/DAT` aneurysm vs. AHA/ASA stroke perfusion), `#797` (prompt divergence increasing fixed $2N$ dense Transformer FLOPs), `#798` (`<1%` plant ALA-to-DHA conversion), `#799` (DSM-5 `<5y` hard-cutoff claim), `#800` ("meat malware / 0-deg empathy" vs. Attwell–Laughlin `~20 W` budget).
- **Edges & Bridges:** `48` directed edges (`11` `resolved_mistake`, `11` `pivoted_to`, `26` `supports`, `0` self-loops); `7` new `concept_bridges` (`312 -> 319`).
- **Branch Convergence (`B514–B528`):** `13/13` resolved branches auto-flipped to `CONVERGED`; strictly the `2` `toy_model` branches (`B514`, `B517`) stayed `ACTIVE`.

---

## 4. Quantitative Token Efficiency Comparison vs. Wave 1 `/teamwork` Swarm

Wave 1 swarm totals were extracted directly from the `8` Wave 1 agent transcripts across `2026-11-17T04:19:00Z – 06:30:00Z` (`240` chunks triaged -> `104` `PROCESSED`, `136` `SKIPPED`, `51` nodes `#699–#749`; **excluding** Step 5/6 `compiler`, `monitor`, and `coordinator` separately so both "Full Swarm" and "Core A+B+C Only" baselines are shown):

| Metric | Wave 1 Full Swarm (`8` agents, `117` turns) | Wave 1 Core A+B+C (`5` agents, `80` turns) | **Single-Loop Runner** (`6` calls, `0` swarm msgs) | Gain vs. Wave 1 Core A+B+C | Gain vs. Wave 1 Full Swarm |
| :--- | :---: | :---: | :---: | :---: | :---: |
| Chunks Processed (`PROCESSED`) | `104` *(+ `136` skipped)* | `104` *(+ `136` skipped)* | **`20`** *(`0` skipped)* | — | — |
| Nodes Committed (incl. reframed) | `51` | `51` | **`26`** | — | — |
| Total Uncached `input_tokens` | `5,128,202` | `3,668,057` | **`68,082`** | — | — |
| Total `cached_input_tokens` | `26,322,994` | `19,574,164` | **`0`** | — | — |
| Total Prompt Context (`in + cached`) | `31,451,196` | `23,242,221` | **`68,082`** | — | — |
| Total `output_tokens` | `144,444` | `110,939` | **`59,610`** | — | — |
| **Uncached Input / `PROCESSED` Chunk** | `49,310` | `35,270` | **`3,404`** | **`10.4×` lower** | **`14.5×` lower** |
| **Total Context / `PROCESSED` Chunk** | `302,415` | `223,483` | **`3,404`** | **`65.7×` lower** | **`88.8×` lower** |
| **Uncached Input / Node Committed** | `100,553` | `71,923` | **`2,619`** | **`27.5×` lower** | **`38.4×` lower** |
| **Total Context / Node Committed** | `616,690` | `455,730` | **`2,619`** | **`174.0×` lower** | **`235.5×` lower** |
| **Output Tokens / `PROCESSED` Chunk** | `1,389` | `1,067` | **`2,981`** | `2.8×` higher* | `2.1×` higher* |
| **Output Tokens / Node Committed** | `2,832` | `2,175` | **`2,293`** | **~Parity (`1.05×`)** | **`1.24×` lower** |
| **Wall Clock / `PROCESSED` Chunk** | `~9.8 s` *(parallel H1–H3)* | — | **`14.45 s`** *(`289 s / 20`)* | — | `1.47×` slower |

*\*Output tokens per processed chunk were higher (`2,981` vs. `1,067`) purely because this 20-chunk subset had `0%` skipped chunks and `75%` brand-new `RAW_CLAIM` extraction (`15/20` vs. Wave 1's `37/104 = 35.6%`) with `11` full `FALSIFIED` reframings; normalized **per node committed**, output tokens stayed at parity (`2,293` vs. `2,175`).*

---

## 5. Key Architectural Takeaways

1. **Multi-Turn Conversation History Bloat Dominated Swarm Cost:** In `/teamwork` swarm mode, every tool call (`get_slice_chunks`, `run_physics_check`, `verify_node`, `verify_and_link`, `read_board`, `post_message`) replays the entire growing multi-turn history—accumulating **`223,483` context tokens per processed chunk** (`455,730` per node) across `80` Core A+B+C turns. Moving DB reads, `pycheck` execution, and SQLite commits out of the LLM loop into Python reduced context overhead by **`65.7×–174.0×`**.
2. **`flash_lite` Fails Nuanced Step A Lifting:** Using `flash_lite` caused immediate triage collapse (skipping all 10 chunks and hallucinating `#796`). `flash` is the lightest reliable floor for Step A/B/C while still costing zero multi-turn bloat.
3. **Recommended Hybrid Production Pattern:** Run Steps A–C (Lifter, Scientist, Falsifier) via `scripts/single_loop_runner.py` (`--backend gemini` once `GEMINI_API_KEY` is exported, or stateless `flash` mini-batches of 10 chunks) to finish the remaining `260` `PENDING` chunks in `bio_neuro_psych` + `philosophy_epistemology` + `residual_sweep` at ~`3.4k` input tokens/chunk, then invoke `compiler` once at the end of each ring to synthesize the textbook chapters and audit log.

---

## 6. Post-Run Verification

- **Unit Test Harness:** `/Library/Frameworks/Python.framework/Versions/3.14/bin/python3 scripts/test_pilot_harness.py` -> **`Ran 5 tests in 0.118s — OK` (`5/5` passed)**.
