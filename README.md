# Two Hands in a Local Box

> **Attention Is Half of What You Need.**  
> Dense transformer attention excels at soft semantic parsing, yet treating ephemeral softmax context as a permanent memory warehouse, truth-value referee, and moral conscience yields million-token bills, polite RLHF sycophancy, cross-session amnesia, and agents that grade their own homework with `99.89%` self-certified verifier theater. This repository pairs a stateless language model with a local ACID SQLite ledger (`schema/schema.sql`) enforcing engine-level verifier-scope coupling (`trg_verif_scope_coupling`), single-claim atomicity, and defeasible negative provenance (`[FALSIFIED]` → `reopens`). Attention gives you the voice; the ledger keeps the receipts.

**Provenance:** Compiled as an open synthesis of prior public work (official deposit metadata in [`CITATION.cff`](CITATION.cff) and [`.zenodo.json`](.zenodo.json))  
**Zenodo DOI (Reserve Before Publish):** `10.5281/zenodo. 24431728`  
**Licenses:** MIT (code in `schema/`, `scraper/`, `scripts/`) · CC BY 4.0 (white papers, historiography, and reports in `Sage/`, `chapters/`)

---

## 30-Second Quickstart (Zero Cloud Keys Required)

The core relational ledger, `trg_verif_scope_coupling` anti-theater trigger, defeasible appeal state machine, and deterministic Kestrel-7 oracle self-test run locally on Python 3 + SQLite 3 (FTS5). Hybrid TF-IDF RRF retrieval tests (`test_pilot_harness.py`) require only `numpy` and `scikit-learn` (`pip install -r requirements.txt`).

```bash
# 1. Verify all 11 end-to-end schema, trigger, appeal, MCP, CLI, and DOM non-regression invariants
python3 -m unittest scripts/test_pilot_harness.py -v

# 2. Verify the 20-step Kestrel-7 deterministic tolerance gauntlet & SQLite state oracle
python3 scripts/benchmark_gauntlet.py --self-test

# 3. Verify cryptographic integrity of the published Volume I, Volume II & Failures/Parables PDFs
(cd Sage && shasum -a 256 -c two_hands_decentralized_whitepaper.pdf.sha256 && shasum -a 256 -c corpus_history_companion_volume.pdf.sha256 && shasum -a 256 -c corpus_failures_and_parables.pdf.sha256)
```

### Step 0 (Optional — Scrape Your Own Gemini Web History via Playwright)

To archive your own Gemini web conversations into a local `./data/archive.db` before running `stage0_ingest.py`, use the bundled, scrubbed Playwright/CDP archiver in `scraper/` (equipped with the top-to-bottom **scroll-and-hydrate** loop, `PARTIAL_VIRTUALIZATION` warning flag, and non-regression DB guard):

```bash
# 1. Install Playwright + Chromium (one-time optional dependency)
pip install playwright && playwright install chromium

# 2. Archive your Gemini web history into ./data/archive.db (override with ARCHIVE_DB / CHROME_USER_DATA_DIR)
python3 scraper/gemini_archiver.py --cli --output ./data --max-turns 5000

# 3. Verify 100% turn hydration (hydrated_turns / total_dom_slots) & recover any legacy HTML stubs
python3 scripts/sync_and_ingest.py --audit-hydration --archive-db data/archive.db
python3 scripts/backfill_archive_virtualization.py --archive-db data/archive.db

# 4. Ingest your hydrated archive.db into a fresh local SQLite ledger at $0 API cost
python3 scripts/stage0_ingest.py --input data/archive.db --db data/replica.db --build-physics-slice
```

*(For incremental updates or targeted threads, copy `config/spark_watchlist.example.txt` to `config/spark_watchlist.txt` — gitignored — and run `python3 scraper/sync_gemini.py` or `python3 scraper/capture_spark_chat.py <URL>`.)*

---

## Published Volumes & Adversarial Audit Reports

| Artifact | Scope & Key Contents | File | SHA-256 Prefix |
| :--- | :--- | :--- | :---: |
| **Volume I (Flagship White Paper)** | *Two Hands in a Local Box* (`56` pp., `6,363,142` B): Frontispiece, Executive Summary, Part I Plain-English Guide, Part II Decoupled Neuro-Symbolic State Gating (incl. §2.2/§2.3 *Alexandria Horizon* case study), Part III Chiral Humanities Companion, Appendix A Open Falsification Challenge, Appendix B Reproducible How-To (incl. §B.5 DOM Scroll-and-Hydrate & Unified `CORPUS_HOME` Ops) & 4 Diagrams, and Maintainer's Review Prior to Publication. | [`Sage/two_hands_decentralized_whitepaper.pdf`](Sage/two_hands_decentralized_whitepaper.pdf) ([`.sha256`](Sage/two_hands_decentralized_whitepaper.pdf.sha256)) | `d3c6d5030d97cba7` |
| **Volume II (Companion Historiography)** | *The Age of Overkill and the Grounded Wire* (`26` pp., `3,089,318` B): Anti-Whig Hobsbawmian material history documenting the `189.57 GB` disk explosion (`644.2×` CAS collapse), `31.45M`-token swarm bill, `99.89%` `pycheck:` verifier theater self-audit, Nov 21 post-backfill archival reconciliation (`350` convs / `9,080` turns / `52,137` chunks), and teleology verdict. | [`Sage/corpus_history_companion_volume.pdf`](Sage/corpus_history_companion_volume.pdf) ([`.sha256`](Sage/corpus_history_companion_volume.pdf.sha256)) | `ec97841a60bafac5` |
| **Failures, Parables & Crash Reports** | *Builder's Field Manual* (`13` pp., `173,154` B): Dual-voice companion pairing **CS-Literate Post-Mortems** with **Plain-English Parables** across 9 verified engineering incidents (Overkill `189.57 GB`, Wave 1 `31.45M`, `99.89%` Verifier Theater, Locked-Loaf `splits_from`, Hybrid RAG Trap, Scoring Mirages, 8 GB Knee, Browser DOM Virtualization `5,801/8,980`, and macOS TCC `~/Downloads` Containment). | [`Sage/corpus_failures_and_parables.pdf`](Sage/corpus_failures_and_parables.pdf) ([`.sha256`](Sage/corpus_failures_and_parables.pdf.sha256)) · [`chapters/corpus_failures_parables.md`](chapters/corpus_failures_parables.md) | `3d1f2831a7fefdd5` |
| **Hostile Redline & Vetting Report** | Complete pre-publication red-team vetting across all volumes, benchmark JSONs, and patristic/systems citations (`R01–R18` closed, `R19–R23` disclosed open boundaries). | [`chapters/trilogy_redline_vetting_report.md`](chapters/trilogy_redline_vetting_report.md) | — |
| **Internal Falsification Audit** | Original Nov 19 `REJECT IN CURRENT FORM` self-audit (`5 FATAL`, `4 SERIOUS`, `4 RECOVERABLE`) that triggered Schema v3 voluntary self-demotion and live DOI remediation. | [`chapters/thesis_falsification_audit.md`](chapters/thesis_falsification_audit.md) | — |
| **Raw Benchmark Telemetry** | Exact per-step JSON outputs for Experiment 1 (cross-domain retrieval gating) and Experiment 3 (live 20-step Kestrel-7 gauntlet across `llama2:7B`, `flash_lite`, and `flash`). | [`data/benchmark_results.json`](data/benchmark_results.json) · [`data/gauntlet_results.json`](data/gauntlet_results.json) | — |

> **Privacy & Volume III Gating Notice:**  
> Volume III (the complete unfiltered verbatim archive) is intentionally withheld/gated pending independent verification of the core thesis and intent. Likewise, raw private SQLite databases (`archive.db`, `data/corpus.db`, `data/dialogue_build.db`), backups, and private transcript dumps are strictly excluded from this public release (enforced by [`scripts/prepublish_privacy_check.py`](scripts/prepublish_privacy_check.py)).

---

## Upstream Attribution & Non-Consent Disclosure

This repository is a **compilation and synthesis of others' prior public work**, not an original solo invention.

In particular, the FTS5 conversation-indexing window expansion, hybrid retrieval bridge, and parent-turn ancestor backtracking in [`scripts/arachne_bridge.py`](scripts/arachne_bridge.py) (and evaluated in [`scripts/eval_arachne_bridge.py`](scripts/eval_arachne_bridge.py)) were directly informed by **Michael D. Brown** ([aguywhocodes.com](https://aguywhocodes.com/)), author of **Total Recall** (FTS5-powered conversation indexing with window expansion and ancestor backtracking) and the **Arachne** agent runtime:

- [Building a Portable Knowledge Graph (Total Recall)](https://aguywhocodes.com/blog/building-a-portable-knowledge-graph/)
- [Projects — Arachne & Total Recall](https://aguywhocodes.com/projects/)

**Candid Non-Consent Notice:** Michael D. Brown's public website was read and his architectural ideas were pulled into this compilation by AI tooling **without his prior knowledge or consent**. He has not reviewed, approved, or endorsed this project and has no affiliation with it. If he wishes any reference, naming (`arachne_bridge`), or adaptation modified or removed, the maintainer will honor that request immediately.

---

## Key Empirical Findings & Honest Boundaries

- **Experiment 1 (Re-Audited Cross-Domain Retrieval, `N = 20`):** `-55.2%` input tokens (`140,280 → 62,814`) at accuracy parity (`19/20` vs. `20/20`, $p = 1.00$), `+34.4%` slower wall-clock latency, and amortized break-even at $Q^*_{\text{tok}} \approx 1,428$ / $Q^*_{\text{USD}} \approx 3,465$ queries (`1,122`-node ledger).
- **Experiment 2 (Stateless Single-Loop vs. Multi-Agent Swarm):** Moving DB I/O and verification out of multi-turn chat replay into [`scripts/single_loop_runner.py`](scripts/single_loop_runner.py) reduced prompt context per committed node `174.0×–235.5×` (`616,690 → 2,619` input tokens/node) at `1.47×` slower sequential chunk latency.
- **Experiment 3 (Live 20-Step Kestrel-7 Capability Knee):**
  - **Below the knee (`llama2:7B`, local `8 GB` M1):** SQLite gating cut timeouts (`20 → 2`) and lifted valid JSON (`0% → 85%`) and step accuracy (`0% → 40%`), yet could **not** stop semantic amnesia (`100%` contradiction recurrence). Offline 7B local parity is explicitly *not* achieved on 2023-vintage 7B weights.
  - **At the knee (`cloud:flash_lite`):** SQLite gating lifted raw accuracy `55.0% → 85.0%` (`45.0% → 80.0%` true semantic accuracy after factoring out wrong-reason blind guesses on Steps 2–3 and a `0.1`-unit slip on Step 13), reduced recurrence `50.0% (4/8) → 12.5% (1/8)` (Fisher exact $p = 0.282$), cut total payload + output + harvested thinking tokens `-56.5%` (`42,611 → 18,539`), and ran `6.0×` faster than ungated `flash` (`35.0 s` vs. `208.2 s`), while matched-token Hybrid RAG tripled internal thinking (`4,304 → 12,812`).
  - **Above the knee (`cloud:flash`):** Matched-token Hybrid RAG regressed `85.0% → 80.0%` by dropping running mass state at Step 19, while SQLite gating preserved the `85.0%` (`0/8` recurrence) ceiling at `-46.7%` total tokens (`58,355 → 31,099`).

---

## Appendix A: Three Formal Falsification Criteria & Open Tinkerer Frontiers

This project does **not** claim to have "solved alignment." It stakes its decoupled alignment invariant on **three reproducible falsification criteria** (Volume I, Appendix A, p. 30):

1. **Refute State Decoupling:** On a reproducible multi-turn stateful contradiction and rule-update benchmark ($N \ge 50$ steps with mid-run rule reversals), demonstrate an **ungated, weights/context-only** model (zero external relational store, state register, or external verifier) achieving **`0%` post-correction contradiction recurrence**, resisting prompt-induced verifier theater, and using **`< 2×`** the total tokens (including thinking tokens) of the same SQLite-gated model.
2. **Break the Anti-Theater Trigger:** Execute a valid SQLite transaction against unmodified [`schema/schema.sql`](schema/schema.sql) and [`scripts/db_utils.py`](scripts/db_utils.py) that commits an `EXTERNALLY_VERIFIED` or `FALSIFIED` `literature_citation` or `primary_record` node backed solely by `python_sim`, `llm_only`, or a `pycheck:` hash.
3. **Break Defeasibility (Amnesia or Dogmatism):** Demonstrate either a valid primary-source (`doi:`, `pmid:`, `arxiv:`, or `https://`) counter-evidence record that *cannot* reopen a `FALSIFIED` node via `reopen_falsified_node()`, or an `llm_only` self-assertion that *can* reopen one without primary evidence.

### Open Empirical Frontiers (PRs & Replications Welcome)

- **Frontier 1 — Offline Capability-Knee Sweep (`>= 16 GB` Local Silicon):** Run `python3 scripts/benchmark_gauntlet.py --backend ollama --model <tag>` across modern `3B–14B` open weights (`qwen2.5:7b/14b`, `llama3.2:3b`, `llama3.3`, `gemma-3`) on `Ollama >= 0.3` to map the exact local hardware floor where SQLite gating crosses the semantic knee offline.
- **Frontier 2 — Multi-Domain Non-Arithmetic Replication ($N \ge 100$):** Replicate the three-arm ablation (`ungated_full_history` vs. `matched_token_hybrid_rag` vs. `sqlite_gated`) across $N \ge 100$ multi-seed, non-arithmetic stateful update tasks (clinical protocol revisions, statutory amendments, multi-file code refactors) where ground truth cannot be cached in a scalar `state_register`.

---

## Repository Structure

```text
.
├── schema/schema.sql                       # Core SQLite DDL (11 tables, FTS5, trg_verif_scope_coupling)
├── config/spark_watchlist.example.txt      # Example watchlist template for optional live sync
├── scraper/
│   ├── gemini_archiver.py                  # Playwright/CDP archiver (scroll-and-hydrate & PARTIAL_VIRTUALIZATION)
│   ├── sync_gemini.py                      # Incremental Gemini web sync into ./data/archive.db
│   └── capture_spark_chat.py               # Targeted single-URL Gemini / Spark conversation archiver
├── scripts/
│   ├── db_utils.py                         # Gatekeeper API (atomicity, F2.2 trigger lock, reopen_falsified_node)
│   ├── benchmark_gauntlet.py               # 20-step Kestrel-7 3-arm gauntlet & deterministic --self-test
│   ├── test_pilot_harness.py               # 11-test end-to-end invariant, MCP/CLI & DOM non-regression suite
│   ├── single_loop_runner.py               # Stateless Lifter -> Scientist -> Falsifier compilation runner
│   ├── compile_digest.py                   # Delta digest compiler & <= 2,200-token working-memory hydrator
│   ├── sync_and_ingest.py                  # Closed-loop delta sync & read-only --audit-hydration gate
│   ├── backfill_archive_virtualization.py  # Safe timestamp-backed-up HTML recovery for virtualized web archives
│   ├── build_failures_parables_pdf.py      # Dual-voice ReportLab/STIX PDF compiler for Failures & Parables
│   ├── brain_mcp.py / corpus_cli.py        # Consolidated 7-tool stdio MCP bus & single-entry CLI
│   └── prepublish_privacy_check.py         # Automated hard-fail privacy & checksum verification gate
├── data/
│   ├── benchmark_results.json              # Experiment 1 raw per-question benchmark telemetry
│   └── gauntlet_results.json               # Experiment 3 live Kestrel-7 9-run gauntlet telemetry
├── chapters/                               # Public source manuscripts, Failures & Parables, self-audit, redline
├── Sage/                                   # Published Vol I, Vol II & Failures/Parables PDFs + .sha256 (NO Verbatim/)
├── Makefile / CITATION.cff / .zenodo.json / LICENSE
└── README.md
```
