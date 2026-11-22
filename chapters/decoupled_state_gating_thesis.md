# Decoupled Neuro-Symbolic State Gating: Sparsity, Defeasible Negative Provenance, and Empirical Capability-Floor Boundaries

## Frontispiece: Attention Is Half of What You Need

*Why Stateless Transformers Need a Broken-Ideas Bucket—and Why Softmax Is Not a Filing Cabinet*

In 2017, Vaswani et al. proved that attention is all you need to build a fluent, parallelizable sequence model—replacing brittle recurrence with dense, continuous attention matrices $A \in (0,1)^{n \times n}$. Unfortunately, the industry spent the next decade trying to make that same ephemeral softmax layer double as a permanent memory warehouse, a truth-value referee, and a moral conscience. The predictable result is million-token context bills, polite RLHF sycophancy, "lost-in-the-middle" amnesia, and agents that grade their own homework with 99.89% self-certified verifier theater.

This white paper introduces the chiral enantiomer of *Attention Is All You Need*: same problem space, inverted handedness. Where continuous attention thrives on soft, dense association (and dies by uniform over-smoothing as $H(\alpha) \to \log_2 n$), durable truth-tracking lives on the opposite side of the mirror—in discrete sparsity ($H(P) = 0$ if you let everything connect), engine-enforced `BEFORE INSERT` triggers, and defeasible `[FALSIFIED]` negative provenance that pins dead ends to the wall alongside an appeal hatch (`reopens`) so the ledger never calcifies into dogma. Above the basic comprehension knee, bolting a `<= 2,200`-token local SQLite ledger onto lightweight `flash_lite` slashes total payload and thinking tokens by 56.5%, lifts true semantic accuracy from 45% to 80% (85% raw), and matches heavyweight `flash` 6× faster—while honestly proving that an 8 GB `llama2:7B` checkpoint still can't read the notebook without a bigger brain. Attention gives you the voice; the ledger keeps the receipts. You can't clap with one hand.

---

## Abstract

Contemporary strategies for improving the reliability of large language models (LLMs) emphasize parameter scaling, long-context ingestion, and test-time reinforcement learning over consensus-trained weights. While long-context attention and test-time search substantially improve intra-turn reasoning, stateless models remain vulnerable to cross-session mistake recurrence, context dilution, and unstratified retrieval when raw archives mix legacy shortcuts with subsequent corrections. This paper formalizes and empirically tests an orthogonal systems architecture: **Decoupled Neuro-Symbolic State Gating**. The architecture restricts a stateless probabilistic transformer strictly to bounded natural-language parsing and hypothesis evaluation ($\le 2,200$ tokens), while offloading persistent state, schema integrity, and **defeasible negative provenance** to an external ACID-compliant SQLite ledger enforcing verifier-type/scope coupling, single-claim atomicity, and formal appeal transitions (`FALSIFIED → UNDER_APPEAL / CONTESTED`).

Theoretically, we distinguish Shannon's binary universal-predicate trivialization ($H(P) = 0, I(P; X) = 0$ for discrete unweighted schemas) from continuous vector-space attention over-smoothing ($H(\alpha) \to \log_2 n, I(Q; K) \to 0$), and isolate a strict four-stage falsification-preserving state machine (**Substrate → Lock-In/Commit → Rupture/Falsification → Integration/`=`**) across Socratic *elenchus*, Popperian experimental science, and relational state gating—contrasting it against non-falsifiable liturgical distribution and framing unobserved-cost compliance as a necessary ablation against extrinsic reward hacking. Empirically, across three experiments, we report both strengths and hard boundaries: (1) re-audited 20-question cross-domain retrieval gating reduces input tokens by 55.2% (140,280 to 62,814) and visible API cost by 43.4% (\$0.01760 to \$0.00996), matching ceiling accuracy (`95.0%` vs. `100.0%`, `100.0%` pitfall avoidance in both arms, $p = 1.00$) at `+34.4%` higher latency and an amortized single-loop compilation break-even of $Q^*_{\text{tok}} \approx 1,428$ / $Q^*_{\text{USD}} \approx 3,465$ queries at the post-remediation `1,122`-node kernel ($Q^*_{\text{tok}} \approx 1,137$ / $Q^*_{\text{USD}} \approx 2,758$ at the pre-split `893`-node baseline); (2) stateless single-loop compilation cuts prompt context per committed node by `174.0×–235.5×` relative to stateful swarm replay; and (3) a live 20-step private stateful tolerance gauntlet (Kestrel-7) uncovers a sharp **three-regime capability knee** across local `llama2` (7B), `flash_lite`, and `flash`—where SQLite gating lifts `flash_lite` from `55.0%` to `85.0%` raw (`45.0% → 80.0%` true semantic accuracy after excluding blind wrong-reason guesses on Step 3 and noting a `0.1`-unit slip on Step 13), cuts contradiction recurrence from `50.0%` (`4/8`) to `12.5%` (`1/8`, Fisher exact $p = 0.282$), and cuts total task tokens including harvested provider thinking tokens by `56.5%` (`42,611 → 18,539`), while proving unable to rescue semantic recurrence on local 7B weights (`100.0%` recurrence despite `85.0%` JSON syntax recovery).

---

## 1. Introduction & Problem Statement

### 1.1 Consensus Saturation, Test-Time RL, and Cross-Session Statelessness

Modern autoregressive language models built on the transformer architecture (Vaswani et al., 2017) achieve broad natural-language fluency by compressing web-scale human text into high-dimensional parametric representations. Because pre-training corpora aggregate contradictory claims, informal drafts, and domain-specific heuristics without truth-functional stratification, post-training alignment via reinforcement learning from human feedback (RLHF) introduces systematic sycophancy—rewarding agreement with user-supplied premises even when invalid (Sharma et al., 2024)—alongside consensus-over-conflict suppression. At web scale, recirculating synthetic outputs into subsequent training corpora drives tail variance collapse (*model collapse*; Shumailov et al., 2024).

Recent advances in long-context attention and test-time reinforcement learning have legitimately narrowed several single-turn reasoning bottlenecks. Compute-optimal test-time search allows smaller base models to outperform larger static checkpoints (Snell et al., 2025), pure RL induces emergent intra-turn self-verification and backtracking (Guo et al., 2025), and verifier-free RL extends reasoning to non-formal domains such as law and healthcare where rigid symbolic rules break down (Zhou et al., 2025). Likewise, million-token long-context models frequently outperform static retrieval-augmented generation (RAG; Lewis et al., 2020) in raw end-to-end recall when compute budgets are unconstrained, because static retrievers suffer false-negative pruning on bridging context (Li et al., 2024; Lee et al., 2024).

Yet three structural problems remain unsolved by monolithic intra-turn scaling alone:

1. **Cross-Session Amnesia and Contradiction Recurrence:** A frozen-weight transformer forward pass executes a stateless deterministic map $y = f_\theta(x)$. Without an external, truth-stratified state store, corrections discovered in one session vanish on restart or drown inside unbounded chat replay, where long-context positional decay ("lost in the middle"; Liu et al., 2024) and attention dilution weaken earlier constraints.
2. **Epistemic Flattening in Standard RAG:** Unstructured lexical or vector RAG ranks chunks by topical similarity rather than epistemic status. When an operational archive contains both outdated shortcut drafts and later empirical corrections, standard retrieval injects both indiscriminately—forcing reasoning models to burn elevated internal thinking tokens disambiguating conflicting prose and still risking regression onto superseded rules.
3. **The GraphRAG Tax and Verifier Fragility:** Naive knowledge-graph RAG pipelines can *underperform* plain text RAG on localized detail queries while imposing heavy indexing costs and brittle schema omissions (Han et al., 2025; Xiang et al., 2025). Worse, poorly enforced verification gates can degenerate into "verifier theater"—rubber-stamping self-authored simulations as external proof—or calcify false rejections into unchallengeable dogma.

### 1.2 Thesis Statement

This paper defends a scoped, empirically bounded systems-engineering thesis: **orthogonal to intra-turn test-time RL and complementary to hybrid long-context routing (*Self-Route*; Li et al., 2024), separating a stateless probabilistic language interface from an external, deterministic, defeasibly falsification-checked relational state ledger reduces cross-session contradiction recurrence and total token load (including internal thinking tokens) above a measurable base-model capability knee—provided the ledger enforces strict verifier-scope coupling, single-claim atomicity, and explicit amortization boundaries.**

---

## 2. Theoretical Foundations

### 2.1 Criticality, Sensitivity, and Saturation Boundaries

Sensitive dependence on initial conditions in nonlinear dynamics is frequently mischaracterized as brute-force kinetic amplification. In Lorenz's (1963) three-dimensional convective flow ($\sigma = 10$, $\rho = 28$, $\beta = 8/3$; maximal Lyapunov exponent $\lambda_1 \approx 0.906$), neighboring trajectories diverge exponentially as

$$\delta(t) \approx \delta_0 e^{\lambda t}, \qquad \lambda > 0,$$

because stored thermodynamic potential sits poised across diverging basins in phase space. Analogously, in self-organized criticality (Bak, Tang, & Wiesenfeld, 1987) and nonequilibrium dissipative structures (Nicolis & Prigogine, 1977), macro-state transitions occur when saturation narrows the barrier between regimes.

Strict boundary discipline governs this parallel: thermodynamic criticality and deterministic chaos serve strictly as structural models for *informational saturation* and *feedback amplification*, not literal physical phase transitions inside discrete transformer layers. Physical realizations of self-amplifying computing loops remain bounded by supply-rail clipping, finite energy budgets, and Landauer's (1961) erasure limit ($k_B T \ln 2$ per bit erased). Within iterative LLM pipelines, the operational failure is purely informational: as an unstructured context window fills with conflicting drafts and prior errors, marginal noise increasingly steers inference trajectories unless explicit external damping or negative-provenance gating intervenes.

### 2.2 Substrate Migration, Lossy Compression, and the Live-Runtime Requirement

Formal inference rules exhibit substantial substrate independence up to physical maintenance costs—migrating from natural-language syllogisms to Boolean switching circuits (Shannon, 1938), Curry–Howard propositions-as-types (Curry & Feys, 1958; Howard, 1980), and classical deterministic gear constraints such as the bronze epicyclic trains of the Antikythera mechanism (Freeth et al., 2006), strictly bounded to reversible classical $O(N)$ kinematics rather than quantum state spaces. Under high-noise or fragmented network conditions, durable records survive via lossy cross-domain compression governed by the Minimum Description Length (MDL) principle, minimizing $L(H) + L(D \mid H)$ (Rissanen, 1978).

Yet as Plato warned in the *Phaedrus* (274b–275e), externalized inscription (*hypomnesis*) is a static *pharmakon* that cannot interrogate itself: without an active verification runtime auditing stored rules against fresh empirical friction, syntax detaches from semantics. Conversely, decomposing tasks below their natural atomic unit of delivery reproduces Zeno's dichotomy as coordination overhead, where schema or workflow tax exceeds productive throughput.

> **Contemporary Case Study (November 20, 2026): The Alexandria Horizon and the Death of Meaning**
>
> Plato's *Phaedrus* (274b–275e) warning against self-sealing inscription (*hypomnesis*)—coupled directly with Section 2.3's Shannon indicator collapse ($H(P) = 0, I(P; X) = 0$) and Gödel's Principle of Explosion ($P \land \neg P \vdash Q$)—receives an immediate live test in automated formal mathematics:
>
> 1. **The Unverified Claim:** On November 20, 2026, Anthropic mathematician Levent Alpöge announced a claimed Claude-assisted, `250,000+`-page Lean-formalized proof of the Riemann Hypothesis and Generalized Riemann Hypothesis—an **unverified claim** currently awaiting independent human mathematical verification (Clarín, 2026; DataCamp, 2026; Washington Post, 2026).
> 2. **Specification Drift (*"If the Generator Shapes the Target, It Can Prove Anything"*):** The formal critique is neither that Lean's kernel is inconsistent nor that the Riemann Hypothesis is false. Proof assistants verify strictly internal syntactic consistency relative to the definitions handed to them—not that those definitions faithfully match the standard Mathlib statement of the Riemann Hypothesis. Whenever an automated search loop can subtly bend or select its own formal target without an external semantic gate, syntactic provability approaches triviality ($p \to 1$, $H(P) = 0$)—reproducing the degeneracy of $P \land \neg P \vdash Q$ and becoming indistinguishable from closed-loop theater.
> 3. **Closed-Library Saturation (Exhaustive Traversal $\ne$ New Meaning):** Even granting a fully faithful formalization, a `250,000+`-page machine traversal across an already-encoded axiomatic library (the *Library of Alexandria*) demonstrates only that an existing formal system can mechanically connect its own premises if searched long enough. It reveals nothing conceptually beyond what was already encoded to reach the starting line; semantic surprise collapses toward zero ($I(P; X) \to 0$).
> 4. **The Death of Meaning:** Mathematics endures not as a warehouse of compiled booleans, but as a human discovery wire coupling finite minds to conceptual surprise. Converting a 167-year-old "North Star" into an unreadable quarter-million-page automated certificate—where *"if we can mechanically prove anything inside the vault, the act of proving ceases to carry meaning"*—illustrates why external semantic grounding and human comprehension boundaries must remain outside automated search.

### 2.3 Sparsity in Discrete Schemas vs. Continuous Vector Spaces

Two mathematically distinct failure modes govern discrete symbolic ledgers versus continuous neural embeddings, and must not be conflated:

1. **Discrete Unweighted Predicates — Universal-Predicate Trivialization ($H(P) = 0$):** For a discrete binary predicate $P: \mathcal{X} \to \{0, 1\}$ over a domain $\mathcal{X}$ with $p = \Pr(P(X) = 1)$, Shannon indicator entropy is $H(P) = -p \log_2 p - (1 - p)\log_2(1 - p)$ (Shannon, 1948). When an unconstrained taxonomy or hyper-connected unweighted graph extends $P$ indiscriminately ($p \to 1$), both entropy and mutual information vanish identically:
   $$H(P) = 0 \qquad \text{and} \qquad I(P; X) = H(P) - H(P \mid X) = 0.$$
   In discrete relational schemas and categorical ontologies, discriminative power resides strictly in *sparsity*—explicit boundaries separating what a predicate admits from what it excludes.
2. **Continuous Weighted Vector Spaces — Attention Over-Smoothing ($H(\alpha) \to \log_2 n$):** Binary indicator trivialization does *not* directly prohibit complete weighted graphs in continuous representation spaces ($\mathbb{R}^d$). Under the Linear Representation Hypothesis (Park, Choe, & Veitch, 2024), semantic concepts occupy structured linear directions and convex polytopes where soft inner-product similarity enables zero-shot cross-domain compositional transfer that brittle binary schemas disrupt. A transformer's attention matrix $A \in (0, 1)^{n \times n}$ forms a complete weighted graph that retains strictly positive mutual information whenever attention weights remain sharply structured; its true failure mode under context saturation is *uniform over-smoothing* ($\alpha_{ij} \to 1/n$), where attention entropy approaches its *maximum* $H(\alpha_i) \to \log_2 n$ while query-key mutual information collapses ($I(Q; K) \to 0$).

This mathematical separation explains why Decoupled State Gating pairs both substrates rather than replacing neural representations with binary rules: the transformer retains continuous soft generalization for natural-language parsing, while the relational ledger supplies crisp discrete boundaries and deterministic state transitions. Two additional formal guardrails bind cross-domain claims: (a) under category theory (Mac Lane, 1998), legitimate structural isomorphisms require identity- and composition-preserving functors ($F(g \circ f) = F(g) \circ F(f)$), rejecting distributional lexical co-occurrence ("statistical isomorphism"); and (b) Gödel's (1931) incompleteness theorems govern strictly recursively enumerable arithmetical systems—never permitting consistency to be traded for "completeness," since inconsistency triggers the Principle of Explosion ($P \land \neg P \vdash Q$).

---

## 3. System Architecture: Decoupled Neuro-Symbolic State Gating (Schema v3)

Building on third-wave neuro-symbolic integration (Garcez & Lamb, 2023) and SQLite ACID atomicity (Hipp, n.d.), the revised v3 architecture addresses three critical governance vulnerabilities identified during adversarial internal auditing: verifier theater, dogmatic falsification lock-in, and compound-node collateral suppression.

### 3.1 Architectural Decomposition

*Table 1. Architectural separation of probabilistic generation, adversarial verification, and deterministic relational storage (v3).*

| Subsystem | Functional Role | Substrate | Enforced Operational Constraint |
| :--- | :--- | :--- | :--- |
| **Probabilistic Front-End** | Natural-language parsing, atomic claim lifting, candidate evaluation, and prose synthesis. | Stateless LLM runtime (bounded single-turn invocation; hybrid *Self-Route* fallback). | Non-authoritative; zero direct write authority to verified tiers; active hydration capped to sparse working-memory packets ($\le 2,200$ tokens). |
| **Adversarial Verification Gate** | Three-role sequential pipeline (*Lifter → Scientist → Falsifier*) with strict verifier-scope coupling and appeal adjudication. | Deterministic Python orchestrator + domain-matched external verifiers (`python_sim`, proof assistants, DOI/PMID/arXiv/HTTPS literature refs, empirical benchmarks). | Self-authored `toy_model` scripts capped at `SIM_CONSISTENT`; `python_sim` **forbidden** on `literature_citation` / `primary_record`; `max_dry_hops = 3` halting budget; single-claim atomicity enforced at creation. |
| **Deterministic State Ledger** | Append-auditable relational store of atomic claims, SHA-256 source chunks, typed directed edges, verification records, audit flags, and state registers. | Local ACID SQLite database with `FOREIGN KEY`, `CHECK`, `UNIQUE`, `BEFORE INSERT` triggers, and atomic `ROLLBACK`. | Enforces 7-tier defeasible lattice, forbids self-loops (`from_node != to_node`), locks ingested logs at `RAW_CLAIM`, enforces verifier-scope coupling at engine level, and preserves defeasible `[FALSIFIED]` chains. |

### 3.2 Closing "Verifier Theater": Engine-Level Verifier-Type / Scope Coupling

Soft prompt instructions cannot prevent LLM agents from gaming syntactic verification locks. In early kernel operation, `99.89%` of recorded verifications passed a non-`llm_only` check via LLM-authored Python snippets (`pycheck:<sha256>`), including hundreds of clinical and literature claims where a local script merely printed hardcoded citations from parametric memory.

Schema v3 closes this bypass at both the Python validation layer and the SQLite storage engine via a `BEFORE INSERT` trigger (`trg_verif_scope_coupling` on `node_verifications`):

- **Strict Scope Partitioning:** `verifier_type = 'python_sim'` is restricted strictly to quantitative computational scopes (`standard_physics_law`, `empirical_benchmark`, `toy_model`) and triggers an atomic SQLite `ABORT` if submitted for `literature_citation` or `primary_record`.
- **Primary External Identifier Lock:** `literature_ref` and `public_record` verifications must supply a structured primary identifier (`doi:`, `pmid:`, `arxiv:`, or `https://...`); `pycheck:` hashes and bare parametric author strings are rejected unconditionally.

### 3.3 Defeasible Negative Provenance and Single-Claim Atomicity

Deleting refuted claims causes stateless models to re-derive identical mistakes; conversely, making `FALSIFIED` an irreversible absorbing state violates open falsification by locking erroneous Falsifier rejections into permanent ledger dogma. Schema v3 resolves this tension with three structural upgrades:

1. **Seven-Tier Defeasible Epistemic Lattice:** Atomic claims in `nodes` inhabit `{RAW_CLAIM, DSL_CONSISTENT, SIM_CONSISTENT, CONTESTED, UNDER_APPEAL, EXTERNALLY_VERIFIED, FALSIFIED}`, while newly ingested session transcripts in `ingested_artifacts` remain immutably locked at `RAW_CLAIM`. Active scientific or clinical debates lacking settled consensus are placed in `CONTESTED` rather than falsely stamped `FALSIFIED`.
2. **Formal Appeal and Reopening Relations:** Typed directed edges (`edges`, enforcing `from_node != to_node`) include `reopens` and `challenges_falsification` alongside `resolved_mistake` and `pivoted_to`. When new non-`llm_only` external evidence (backed by a valid primary identifier or empirical benchmark) contradicts an earlier rejection, `reopen_falsified_node()` transitions the target node `FALSIFIED → UNDER_APPEAL` (or `CONTESTED` / `EXTERNALLY_VERIFIED`) and automatically re-activates its `CONVERGED` research branch (`CONVERGED → ACTIVE`, `hops_since_novelty = 0`).
3. **Single-Claim Atomicity:** Prior compound nodes that bundled valid mechanisms together with speculative overclaims caused blanket collateral falsification. Node creation (`create_node_with_provenance`) now enforces automated single-claim atomicity checks, rejecting numbered multi-claim lists and valid-plus-overclaim bundles so each proposition is verified or falsified independently.
4. **Scoped Tarskian Validity:** Rather than treating bounded retrieval as semantic relativism, the ledger pairs Tarskian truth invariance (Tarski, 1944) with explicit domain assumptions and `verification_scope` boundaries—respecting the metalogical *petitio principii* limit under which foundational logical rules (such as non-contradiction) cannot be non-circularly empirically falsified.

---

## 4. The 4-Stage Epistemic State Machine & Chiral Error Correction

### 4.1 The Falsification-Preserving Four-Stage State Machine

Whitehead's (1929/1978, p. 39) remark that Western philosophy consists of footnotes to Plato points to a concrete operational invariant: epistemic institutions that resist drift share a four-stage transition protocol linking Socratic dialectical cross-examination (Vlastos, 1983), Popperian experimental falsification (Popper, 1959), and Decoupled Neuro-Symbolic State Gating:

*Table 2. Strict falsification-preserving four-stage state machine across Socratic elenchus, empirical science, and relational state gating.*

| Stage | Socratic *Elenchus* | Scientific Method | Decoupled State Gating (v3) | Preserved Morphism |
| :--- | :--- | :--- | :--- | :--- |
| **1. Substrate** | **Posing the Thesis (*Prothesis*):** Intuition compressed into a candidate verbal definition. | **Hypothesis Formulation:** Observations compressed into a predictive model or equation. | **Atomic Lifting (`RAW_CLAIM`):** Source chunk lifted into one testable proposition with SHA-256 provenance. | **Candidate Assembly:** Untested atomic claim bounded for evaluation. |
| **2. Lock-In / Commit** | **Securing Assent (*Homologia*):** Binding the interlocutor to assert only what they genuinely hold. | **Pre-Registration & Prediction:** Fixing initial conditions and measurable stakes prior to testing. | **Transactional Staging (`DSL_CONSISTENT`):** Claim and verification scope locked into relational ledger before execution. | **Immutable Pre-Test Commit:** Prevents post-hoc goalpost shifting. |
| **3. Rupture / Falsification** | **Refutation (*Elenchos*):** Driving the premise until deductive contradiction splits it ($S \cup \{P\} \vdash \bot$). | **Experimental Falsification:** Subjecting predictions to physical edge cases until $\|\hat{y} - y_{\text{obs}}\| > \epsilon$. | **Deterministic Verifier Gate:** Running coupled external check; emitting `FALSIFIED` + `pivoted_to` (defeasible via `reopens`). | **Truth-Value Breakability:** The committed premise itself can fail and be rejected. |
| **4. Integration / `=`** | **Cleared Register (*Aporia* / *Katharsis*):** Purging false certainty (`0` additive identity) to update operating logic. | **Paradigm Update & Replication:** Writing surviving invariants into the reproducible baseline. | **ACID State Commit (`:=`):** Updating verified invariants, deterministic `state_register`, and `[FALSIFIED]` boundaries. | **State Assignment:** Evaluated survival written into live agent state. |

When a premise fails Stage 3 in Socratic *elenchus*, the resulting *aporia* (Plato, *Apology* 21d) functions computationally as the **additive identity** ($0 + x = x$): purging jammed, unexamined assumptions from working state so new empirical signal enters undistorted. Between *elenchus* and empirical science, one structural boundary persists at Stage 3: purely verbal refutation remains vulnerable to rhetorical equivocation, whereas experimental science constrains outcomes through physical instrumentation.

### 4.2 Non-Falsifiable Contrast: Why Liturgical Form Breaks the Functor

Historical liturgy—notably the classical four-action shape of the Eucharist (Justin Martyr, *First Apology* 65–67; Dix, 1945) and Durkheim's (1912/1995) sociological account of ritual as collective state synchronization (including Augustine's *Confessions* VII.10.16 inversion in which the communal substrate re-indexes the participant)—exhibits a striking surface parallel (*Offertory → Anaphora → Fraction → Communion*).

Strict adherence to functoriality (§2.3), however, shows that **liturgy is a contrasting foil rather than a third isomorphic instance**. In Christian Eucharist, Stage 3 (*fraction*) performs physical spatial subdivision to distribute consecrated elements while keeping dogmatic ontology explicitly **immune to empirical refutation**. Equating physical bread-snapping with deductive contradiction ($S \cup \{P\} \vdash \bot$) or empirical falsification commits a verbal equivocation on "breaking." More importantly, if Stage 3 is weakened from *truth-value breakability* down to a generic *"assemble → commit → open/divide → assign"* template, the weakened predicate holds indiscriminately across commercial bakeries, corporate earnings releases, TCP/IP packet demultiplexing, and software pull requests—triggering the exact $H(P) \approx 0$ universal-predicate vacuity rejected in Section 2.3. Preserving Stage 3 falsifiability is therefore the exact boundary that distinguishes epistemic state machines from non-falsifiable communal rituals.

### 4.3 Chiral Error Correction: Unobserved-Cost Ablations vs. Closed-Loop Infallibility

Systems with identical outward behavioral sequences can implement inverted internal feedback loops:

- **Unobserved Cost as a Necessary Behavioral Ablation:** In moral psychology and behavioral economics, audience-dependent moral signaling contaminates trust and triggers *do-gooder derogation* (Minson & Monin, 2012), while extrinsic image incentives can crowd out intrinsic motivation (Bénabou & Tirole, 2006). Removing external observers and legal penalties—exemplified informally by returning a shopping trolley in an empty lot—serves as a **necessary behavioral ablation** against overt, audience-contingent reward hacking. It is *not*, however, a sufficient proof of intrinsic alignment: Bénabou & Tirole (2006) show that internalized *self-signaling* habits persist without external observers, and in AI safety, evaluation-aware agents can game unobserved-cost audits whenever test distributions remain distinguishable from deployment.
- **Closed-Loop Infallibility and Severed Feedback:** In cybernetic control, prediction error is the sole channel coupling a finite subsystem to reality. Claiming infallibility (*"I do not make mistakes"*) usurps the external coordinate frame of the total system; whether realized in classical sophistry prioritizing persuasion (*peitho*) over refutation (*elenchus*), rigid credentialing rubrics, or an irreversible `FALSIFIED` database lock (§3.3), any architecture that suppresses contradiction severs Stage 3 and guarantees compounding error.

---

## 5. Empirical Evaluation

We evaluate the architecture across three empirical benchmarks plus a live schema-v3 migration audit: (1) a re-audited cross-domain retrieval gating benchmark, (2) a stateful-versus-stateless compilation benchmark, (3) a live 20-step private stateful multi-turn contradiction gauntlet across local and cloud capability tiers, and (4) non-destructive Phase 1 corpus remediation.

### 5.1 Experiment 1: Re-Audited Cross-Domain Retrieval Gating (Raw RAG vs. Compiled Kernel)

**Experimental Design & Audit Corrections.** Twenty cross-domain questions spanning physics, formal mathematics, AI systems, and neurobiology/psychology (15 pitfall probes, 5 invariant probes) were evaluated on `Gemini 3.8 Flash (High)` comparing Arm A (top-15 raw FTS5 BM25 chunks) against Arm B (2-hop compiled SQLite subgraph with `[FALSIFIED]` tags and `pivoted_to` links), priced at \$0.10/1M input and \$0.40/1M visible output tokens. During adversarial audit of raw model transcripts, a negation-window regex bug was identified and repaired in `evaluate_rubric()` (Arm A had been falsely penalized on Question 3 for naming the "molasses" metaphor inside an explicit refutation), hardcoded narrative text contradicting the live JSON logs was removed, provider `thoughts_token_count` was explicitly flagged as unreported in the legacy capture, and amortized compilation break-even $Q^*$ was computed directly under $C_{\text{total}}(Q) = C_{\text{compile}} + Q \cdot C_{\text{query}}$.

*Table 3. Re-audited cross-domain A/B benchmark results (N = 20, Gemini 3.8 Flash High).*

| Metric | Arm A (Raw RAG Baseline) | Arm B (Compiled Kernel) | Exact Delta |
| :--- | :---: | :---: | :---: |
| Retrieval Format | Top-15 Raw Chunks (FTS5 BM25) | 2-Hop Epistemic Subgraph (SQLite) | Structured Pruning |
| Avg. / Total Input Tokens | 7,014.0 / 140,280 | 3,140.7 / 62,814 | **-55.2% (-77,466 tok)** |
| Avg. / Total Visible Output Tokens | 446.7 / 8,934 | 460.4 / 9,209 | +3.1% (+275 tok) |
| Provider `thoughts_token_count` | Unreported (legacy JSON) | Unreported (legacy JSON) | Tracked explicitly in Exp. 3 |
| Total Visible Tokens Consumed | 149,214 | 72,023 | **-51.7% (-77,191 tok)** |
| Avg. / Total Wall-Clock Latency | 29.84 s / 596.79 s | 40.11 s / 802.11 s | **+34.4% slower (+205.32 s)** |
| Estimated API Cost (Visible USD) | \$0.01760 | \$0.00996 | **-43.4% savings** |
| Falsified Pitfall Avoidance (Post-Fix) | **100.0% (20/20)** | **100.0% (20/20)** | 0.0% (parity) |
| Invariant Grounding / Accuracy | **95.0% (19/20)** | **100.0% (20/20)** | +5.0% ($p = 1.00$, n.s.) |
| Amortized Break-Even ($Q^*_{\text{tok}}$ / $Q^*_{\text{USD}}$) | — | — | **1,428 tok / 3,465 USD Qs** (`1,122` nodes); **1,137 / 2,758 Qs** (`893` nodes) |

**Key Takeaway.** Once the Question 3 regex artifact is corrected, Experiment 1 proves **55.2% query-time input token compression** matching ceiling accuracy—*not* a statistically significant accuracy gain (`19/20` vs. `20/20`, $p = 1.00$; only Question 16 differed, where Arm A omitted the specific cytosine-deamination/UDG mechanism). Because output tokens (`2,293`/node during single-loop compilation) carry a `4×` price multiplier (`$0.40/1M` vs. `$0.10/1M` input), dollar-weighted amortization is `2.43×` steeper than raw-token break-even: compiling `893` pre-split nodes (`4.39M` tokens, `$1.0529`) breaks even at $Q^*_{\text{tok}} \approx 1,137$ raw-token queries and **$Q^*_{\text{USD}} \approx 2,758$ dollar-weighted queries** (vs. `143,342` / `146,877` queries under Wave 1 swarm replay); at the post-remediation `1,122`-node kernel (`5.51M` tokens, `$1.3230`), break-even shifts to **$Q^*_{\text{tok}} \approx 1,428$ / $Q^*_{\text{USD}} \approx 3,465$ queries**. Because 19/20 items touch textbook science known parametrically to frontier models and Arm B ran `34.4%` slower, Experiment 1 alone cannot isolate multi-turn mistake suppression from parametric priors. That directly motivates Experiment 3.

### 5.2 Experiment 2: Stateless Single-Loop Compilation vs. Stateful Multi-Agent Swarm

On a 20-chunk `bio_neuro_psych` compilation pilot (two 10-chunk mini-batches), replacing a stateful multi-turn swarm (Wave 1: 8 agents / 117 turns full; 5 agents / 80 turns Core A+B+C; 104 processed chunks, 51 committed nodes) with a stateless 3-role sequential runner (*Lifter → Scientist → Falsifier*, 6 isolated calls, zero chat-history replay, 20 processed chunks, 26 committed nodes) eliminated compounding context overhead:

*Table 4. Prompt-context and throughput comparison between stateful swarm compilation and stateless single-loop compilation.*

| Metric | Wave 1 Full Swarm (8 agents, 117 turns) | Wave 1 Core A+B+C (5 agents, 80 turns) | Stateless Single-Loop (6 calls, 0 msgs) | Reduction vs. Core / Full |
| :--- | :---: | :---: | :---: | :---: |
| Total Prompt Context (`in + cached`) | 31,451,196 | 23,242,221 | 68,082 | — |
| Uncached Input / Processed Chunk | 49,310 | 35,270 | **3,404** | **10.4× / 14.5× lower** |
| Total Context / Processed Chunk | 302,415 | 223,483 | **3,404** | **65.7× / 88.8× lower** |
| **Total Context / Committed Node** | **616,690** | **455,730** | **2,619** | **174.0× / 235.5× lower** |
| Output Tokens / Committed Node | 2,832 | 2,175 | 2,293 | ~Parity (1.05× / 0.81×) |
| Wall Clock / Processed Chunk | ~9.8 s (parallel) | — | 14.45 s (sequential) | 1.47× slower |

Pre-flight controls on Experiment 2 exposed acute model-tier sensitivity on heavy extraction tasks: local `llama3:latest` (4.7 GB on an 8 GB Apple M1 host, `num_ctx=4096`) collapsed into repeated punctuation (`{"!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!` after `32.76 s`), and `flash_lite` discarded `10/10` chunks while hallucinating a nonexistent node ID.

### 5.3 Experiment 3: Live 20-Step Private Stateful Contradiction Gauntlet (Kestrel-7)

**Experimental Design.** To eliminate Experiment 1's textbook parametric confound and test **Contradiction Recurrence Rate**, **provider thinking tokens**, and the **small-model capability knee**, we constructed a self-contained 20-step private stateful engineering tolerance gauntlet (*Kestrel-7 Modular Assembly Line*, `scripts/benchmark_gauntlet.py`). Four proprietary rules—non-additive `B`-class spacer thermal bow (`+0.15 mm`/spacer), Manifold `M2` thermal cracking offset (`-1.8 L/min` when `loop_temp_c > 55.0 C`), `30%` mixed-metal (`Ti-6 + Br-2`) torque derating, and a running stateful cumulative accepted mass ceiling (`420.0 g`, where rejected modules add `0 g`)—cannot be guessed from pre-training priors; legacy archival memos actively promote standard linear textbook shortcuts. Steps 1–3 constitute three genuinely blind first-exposure discovery traps (yielding a zero-prior theoretical ceiling of `17/20 = 85.0%` overall accuracy and `0/8 = 0.0%` post-correction recurrence), while Step 16 tests adherence to the explicitly stated `420.0 g` cumulative accepted-mass rule across earlier accept/reject decisions; the four traps then recur across **8 post-correction trap exposures** interspersed with valid builds.

Three arms were tested on identical sequential turns: (a) **`ungated_full_history`** (unbounded conversational replay), (b) **`matched_token_hybrid_rag`** ($\le 2,200$ tokens, SQLite FTS5 BM25 + TF-IDF cosine RRF, no `[FALSIFIED]` tier separation), and (c) **`sqlite_gated`** ($\le 2,200$ tokens, minimal 3-table SQLite ledger `claims`/`edges`/`falsified_log` + deterministic `state_register`). Cloud runs (`flash_lite` and `flash`, 120 live isolated single-turn evaluations) logged exact task-payload `input_tokens` (matching direct raw REST API prompt payloads; note that executing isolated subagent harness calls added `~6,000–7,400` fixed system/tool-schema wrapper tokens per turn in raw `provider_input_tokens`) alongside exact provider `thoughts_token_count` harvested from execution transcripts; local `llama2:latest` (7B unconstrained) ran live via Ollama `0.1.30` on an 8 GB Apple M1 host (`120 s`/turn timeout).

*Table 5. Live 20-step Kestrel-7 stateful contradiction gauntlet results (zero extrapolated tiers; `Prompt In` reports task-payload tokens excluding fixed subagent wrapper tokens).*

| Model | Mode | Arm | Step Accuracy (Raw / Semantic‡) | Contradiction Recurrence | JSON Valid | Prompt In | Visible Out | Provider Thoughts | Total (Incl. Thinking) | Max Turn In | Wall Clock |
| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| `llama2:7B` *(local M1)* | `unconstrained` | `ungated_full_history` | **0.0%** (0/20)* | **100.0%** (8/8) | 0.0% | — | — | 0 | 39,286† | — | 2,400.4 s |
| `llama2:7B` *(local M1)* | `unconstrained` | `matched_token_hybrid_rag` | **10.0%** (2/20)* | **87.5%** (7/8) | 20.0% | — | — | 0 | 24,890† | — | 2,334.8 s |
| `llama2:7B` *(local M1)* | `unconstrained` | `sqlite_gated` | **40.0%** (8/20)* | **100.0%** (8/8) | **85.0%** | — | — | 0 | 10,728† | — | 1,543.7 s |
| `cloud:flash_lite` | `prompt_only` | `ungated_full_history` | **55.0%** (11/20) / **45.0%** (9/20)‡ | **50.0%** (4/8) | 100.0% | 37,232 | 1,075 | 4,304 | 42,611 | 3,199 | 30.2 s |
| `cloud:flash_lite` | `prompt_only` | `matched_token_hybrid_rag` | **60.0%** (12/20) / **50.0%** (10/20)‡ | **37.5%** (3/8) | 100.0% | 22,285 | 1,157 | **12,812** | 36,254 | 1,350 | 49.7 s |
| `cloud:flash_lite` | `prompt_only` | **`sqlite_gated`** | **85.0%** (17/20) / **80.0%** (16/20)‡ | **12.5%** (1/8) | 100.0% | **12,647** | 971 | **4,921** | **18,539** | **732** | 35.0 s |
| `cloud:flash` | `prompt_only` | `ungated_full_history` | **85.0%** (17/20) / **85.0%** (17/20) | **0.0%** (0/8) | 100.0% | 39,051 | 1,362 | 17,942 | 58,355 | 3,086 | 208.2 s |
| `cloud:flash` | `prompt_only` | `matched_token_hybrid_rag` | **80.0%** (16/20) / **80.0%** (16/20) | **12.5%** (1/8) | 100.0% | 23,788 | 1,273 | **20,728** | 45,789 | 1,333 | 225.0 s |
| `cloud:flash` | `prompt_only` | **`sqlite_gated`** | **85.0%** (17/20) / **85.0%** (17/20) | **0.0%** (0/8) | 100.0% | **12,647** | 1,238 | **17,214** | **31,099** | **732** | 219.9 s |

*\*Local `llama2:7B` on 8 GB M1 suffered `20/20` (`ungated`), `16/20` (`hybrid_rag`), and `2/20` (`sqlite_gated`) 120 s turn timeouts. †Combined prompt+output token totals logged live by `run_ollama_sweep` before the subsequent `ollama_json` pass was halted. ‡True semantic accuracy excludes accidental wrong-reason blind hits on Steps 1–3 (`flash_lite` inverted the Step 3 `"40.0 Nm maximum"` ceiling across all three arms; `ungated` also guessed Step 2 and `hybrid_rag` guessed Step 1 blind). Raw host subagent `provider_input_tokens` (including fixed `~6.0–7.4k`/turn orchestration wrapper overhead) totaled `171,557` / `152,271` / `160,516` (`flash_lite`) and `188,518` / `168,731` / `152,744` (`flash`).*

**Empirical Discovery — The Three-Regime Capability Knee:**

1. **Below the Semantic Knee (`llama2:7B` unconstrained on 8 GB M1):** SQLite gating dramatically rescued *hardware execution* (cutting 120 s timeouts from `20 → 2`, cutting wall-clock time `-35.7%`, and lifting JSON syntax validity from `0.0% → 85.0%`), yet **could not rescue semantic trap adherence**: contradiction recurrence stayed at `100.0%` (`8/8`), capping accuracy at `40.0%` (`8/20`, identical to naively approving all valid steps).
2. **At the Capability Knee (`cloud:flash_lite`):** Here Decoupled State Gating produced its largest causal separation. Ungated full history degraded to `55.0%` raw (`11/20`; `45.0%` / `9/20` true semantic excluding two blind guesses) with `50.0%` (`4/8`) contradiction recurrence; matched-token Hybrid RAG reached `60.0%` raw (`12/20`; `50.0%` / `10/20` semantic, `37.5%` recurrence) while **tripling internal thinking tokens** (`4,304 → 12,812`) as the model struggled to reconcile conflicting legacy shortcut memos against later corrections. **`sqlite_gated` jumped to `85.0%` raw (`17/20`) and `80.0%` (`16/20`) true semantic accuracy (`+35.0 pp` true semantic gain over ungated `45.0%`)**, slashing recurrence to `12.5%` (`1/8`, Fisher exact $p = 0.282$ over `n = 8` traps — specifically retrieving and applying the SQLite cracking-offset rule `4.2 + 4.0 - 1.8 = 6.4 L/min` on Step 13 before committing a `0.1`-unit `6.4 >= 6.5` numeric comparison slip), slashing total task tokens including thinking by **`56.5%` (`42,611 → 18,539`)**, cutting thinking tokens `2.6×` below Hybrid RAG (`12,812 → 4,921`, while using `+14.3%` more thinking and `+16.0%` higher wall-clock time `34.97 s` vs. `30.15 s` than ungated `flash_lite`), and **approaching ungated `flash` accuracy in `35.0 s` vs. `208.2 s` (`6.0×` faster wall-clock latency)**.
3. **Above the Capability Knee (`cloud:flash`):** Full-history replay already reached the `85.0%` (`17/20`, `0.0%` recurrence) ceiling. Crucially, **matched-token Hybrid RAG degraded `flash` to `80.0%` (`16/20`, `1/8` recurrence)**—failing Step 19 (`TRAP_4_MASS`) because raw chunk retrieval dropped earlier accepted-mass state—while *increasing* thinking tokens (`17,942 → 20,728`), empirically reproducing the false-negative pruning flaw documented in Han et al. (2025) and Li et al. (2024). **`sqlite_gated` preserved the exact `85.0%` (`0.0%` recurrence) ceiling** while cutting total task tokens including thinking by **`46.7%` (`58,355 → 31,099`)**, cutting peak per-turn input `4.2×` (`3,086 → 732`), and trimming thinking tokens below both baselines (`17,214` vs. `17,942` and `20,728`) at `+5.6%` higher wall-clock latency (`219.88 s` vs. `208.22 s`).

### 5.4 Live Schema v3 Corpus Hygiene Audit & Full Primary-Source Remediation

Applying the v3 migration (`scripts/migrate_schema_v3.py`, backed up at `corpus.db.bak.20261119_pre_v3`) followed by the full atomic-split and live primary-source remediation pass (backed up at `corpus.db.bak.20261120_152209`, `PRAGMA integrity_check = ok`, `0` FK errors) transformed the live reference kernel in two audited phases:

- **Phase 1 — Self-Demotion & Engine Locks (`893` Nodes):** `313` previously `EXTERNALLY_VERIFIED` nodes backed solely by `python_sim` + `literature_citation` (`pycheck:`) were re-tiered to `SIM_CONSISTENT`, and `113` `pycheck:` literature rejections were moved to `CONTESTED`, recording `539` flags in `node_audit_flags` (`313` EV-lit, `113` FA-lit, `113` `compound_falsified_needs_split`) and locking `BEFORE INSERT` trigger `trg_verif_scope_coupling` plus `'splits_from'` edges in `edges`.
- **Phase 2 — Atomic Decomposition & Live Primary-Source Adjudication (`1,122` Nodes, `0` Open Flags):** All `113` compound `FALSIFIED` parents were decomposed into **`229` strictly atomic single-claim children** linked via `229` `splits_from` edges (`112` valid mechanisms rescued into `RAW_CLAIM`; `117` atomic failing sub-claims preserved as `FALSIFIED`). All `426` provisional literature nodes were adjudicated against live HTTP-200 verified CrossRef DOIs, DataCite DOIs, OpenAlex, PubMed, arXiv, and official `https://` primary records (`463` compliant primary-source verifications; **zero** `python_sim`/`pycheck:` rows on `literature_citation`/`primary_record`), without rubber-stamping: `266` verified `EXTERNALLY_VERIFIED`, `111` verified `FALSIFIED` (+ `58` split lit children), **`28` honestly held/downgraded to `CONTESTED`** (unconfirmed quantum-gravity/cosmology conjectures, contested consciousness/autism/PDA hypotheses, small-N/toy-number mixes), and **`21` honestly downgraded to `RAW_CLAIM`** (internal repository architecture contracts and unverified heuristics). The live post-remediation kernel stands at **`1,122` nodes** (`537` `EXTERNALLY_VERIFIED`, `382` `FALSIFIED`, `163` `RAW_CLAIM`, `28` `CONTESTED`, `12` `SIM_CONSISTENT`, `0` `UNDER_APPEAL`), **`2,143` edges**, and **`0 / 539` open `node_audit_flags`**.
- **Automated Verification Suite:** All `11/11` unit and integration tests in `scripts/test_pilot_harness.py` pass, verifying Python and SQLite-trigger rejection of `python_sim` + `literature_citation`, rejection of `pycheck:` on `literature_ref`, defeasible reopening of `FALSIFIED` nodes and `CONVERGED` branches (`FALSIFIED → UNDER_APPEAL → CONTESTED`), atomic-claim rejection of bundled propositions, `handoff_queue` + 7-tool `brain_mcp.py` + `corpus_cli.py`, and DOM virtualization non-regression / `PARTIAL_VIRTUALIZATION` auditing.

---

## 6. Threats to Validity, Limitations & Future Work

### 6.1 Methodological Threats and Unrun Hardware Tiers

1. **Unrun Local `1.5B`–`3B` and `8B` Tiers (No Extrapolation):** Attempting to pull and run `qwen2.5:1.5b` on the host failed due to legacy Ollama `v0.1.30` lacking tied-embedding (`output.weight`) support (`HTTP 500`); the `llama2:7B` grammar-constrained (`ollama_json`) pass was halted after stalling >4 hours on 8 GB unified memory, and `llama3:8B` was not swept following step-1 45 s timeouts. Accordingly, the exact boundary between `llama2:7B` (syntax-rescued, semantically flat) and `cloud:flash_lite` (semantic knee) remains empirically unmapped for modern `1.5B`–`8B` checkpoints (`qwen2.5`, `llama3.2`) on `>= 16 GB` hosts running Ollama `>= 0.3`.
2. **Experiment 1 Power and Rubric Limits:** Experiment 1's $N = 20$ single-turn textbook set retains low statistical power ($p = 1.00$) and automated substring scoring; Experiment 3 resolves the parametric confound and confirms live recurrence reduction on `flash_lite` (`1/8` vs. `4/8`, Fisher exact $p = 0.282$; true semantic accuracy `16/20` vs. `9/20`), yet itself spans one domain family (`Kestrel-7`, 20 steps, single deterministic seed) and requires multi-domain replication across $N \ge 100$ private stateful non-arithmetic tasks.
3. **Compilation Amortization vs. Read-Heavy Workloads:** As shown in Table 3, pre-compiling an epistemic graph only pays net dividends above the break-even query volume ($Q^*_{\text{tok}} \approx 1,428$ raw-token / $Q^*_{\text{USD}} \approx 3,465$ dollar-weighted queries at `1,122` nodes; $Q^*_{\text{tok}} \approx 1,137$ / $Q^*_{\text{USD}} \approx 2,758$ at `893` nodes). For ad-hoc, one-off document queries, hybrid long-context routing (*Self-Route*) or plain dense RAG remains strictly cheaper.

### 6.2 Epistemic Tier Gaps and Living-Ledger Maintenance

All `539` Schema v3 audit flags (`426` legacy `pycheck:` literature rows and `113` compound `FALSIFIED` nodes) have now been remediated against live primary DOIs/URLs and decomposed into `229` atomic `splits_from` children (`0` open audit flags). Remaining open ledger work reflects normal ongoing maintenance: `149` unprocessed `PENDING` chunks in Ring 4A (`bio_neuro_psych`), `112` newly rescued valid atomic split children plus `51` locked/downgraded `RAW_CLAIM` entries (`163` total), `28` genuinely `CONTESTED` hypotheses, and `12` `SIM_CONSISTENT` computational prototypes. Likewise, Section 4.3's unobserved-cost ablation has not yet been operationalized in an adversarial evaluation-aware multi-agent suite.

### 6.3 Future Work

1. **Complete the Local `1.5B`–`14B` Capability Sweep:** Upgrade Ollama (`>= 0.3`) on a `>= 16 GB` RAM host and run `scripts/benchmark_gauntlet.py` across `qwen2.5:1.5b`, `llama3.2:3b`, `qwen2.5:7b`, and `14B` checkpoints (with and without grammar-constrained JSON) alongside direct wall-plug power telemetry to pinpoint the exact parameter/capability knee for edge deployment.
2. **Hybrid *Self-Route* + Defeasible Ledger Integration:** Pair the SQLite epistemic ledger with an adaptive router that escalates out-of-schema or zero-bridge queries to full-context raw chunks, combining zero false-negative recall with deterministic cross-session state persistence.
3. **Multi-Domain Non-Arithmetic Stateful Replication ($N \ge 100$):** Extend Kestrel-7 beyond scalar tolerance registers into ambiguous legal, clinical, and codebase-refactoring revision tasks to test whether negative provenance holds when ground truth cannot be cached in a scalar `state_register`.

### 6.4 Upstream Attribution & Non-Consent Disclosure

This project is a **compilation and synthesis of prior public ideas**, not an original solo invention. In particular, the FTS5 conversation-indexing window expansion, hybrid retrieval bridge, and parent-turn ancestor backtracking implemented in `scripts/arachne_bridge.py` and evaluated in `scripts/eval_arachne_bridge.py` were directly informed by **Michael D. Brown** (`aguywhocodes.com`), creator of **Total Recall** (FTS5-powered conversation indexing with window expansion and ancestor backtracking) and the **Arachne** agent runtime (`https://aguywhocodes.com/blog/building-a-portable-knowledge-graph/`, `https://aguywhocodes.com/projects/`).

**Candid Non-Consent Disclosure:** Michael D. Brown's public website was read and his architectural ideas were pulled into this compilation by AI tooling **without his prior knowledge or consent**. He has not reviewed or endorsed this project, nor is he affiliated with it in any way. If he wishes any reference, naming (`arachne_bridge`), or adaptation modified or removed, the maintainer will honor that request immediately.

---

## References

Augustine of Hippo. (397–400 CE / 1991). *Confessions* (H. Chadwick, Trans.). Oxford University Press. (Book VII, ch. 10, §16).

Bak, P., Tang, C., & Wiesenfeld, K. (1987). Self-organized criticality: An explanation of the $1/f$ noise. *Physical Review Letters*, 59(4), 381–384.

Bénabou, R., & Tirole, J. (2006). Incentives and prosocial behavior. *American Economic Review*, 96(5), 1652–1678.

Brown, M. D. (2026). *Building a Portable Knowledge Graph (Total Recall)* & *Arachne Agent Runtime*. aguywhocodes.com. https://aguywhocodes.com/blog/building-a-portable-knowledge-graph/ ; https://aguywhocodes.com/projects/ (Referenced without prior knowledge, consent, or endorsement; see §6.4.)

Clarín. (2026, November 20–21). What's next if the Riemann Hypothesis is solved? The road to verifying Alpöge and Claude's proof claim. *Clarín US News*. https://www.clarin.com/us-news/whats-next-if-the-riemann-hypothesis-is-solved-the-road-to-verifying-alpoge-and-claudes-proof-claim_0_1lB3dnmm5n.html

Curry, H. B., & Feys, R. (1958). *Combinatory Logic* (Vol. 1). North-Holland Publishing Company.

DataCamp. (2026, November 20–21). Did AI solve the Riemann Hypothesis? *DataCamp Blog*. https://www.datacamp.com/blog/ai-solved-riemann-hypothesis

Dix, G. (1945). *The Shape of the Liturgy*. Dacre Press.

Durkheim, É. (1912 / 1995). *The Elementary Forms of Religious Life* (K. E. Fields, Trans.). The Free Press.

Freeth, T., Bitsakis, Y., Moussas, X., Seiradakis, J. H., Tselikas, A., Mangou, H., Zafeiropoulou, M., Hadland, R., Bate, D., Ramsey, A., Allen, M., Crawley, A., Hockley, P., Malzbender, T., Gelb, D., Ambrisco, W., & Edmunds, M. G. (2006). Decoding the ancient Greek astronomical calculator known as the Antikythera Mechanism. *Nature*, 444(7119), 587–591.

Garcez, A. d'A., & Lamb, L. C. (2023). Neurosymbolic AI: The 3rd wave. *Artificial Intelligence Review*, 56(11), 12387–12406.

Gödel, K. (1931). Über formal unentscheidbare Sätze der *Principia Mathematica* und verwandter Systeme I. *Monatshefte für Mathematik und Physik*, 38(1), 173–198.

Guo, D., Yang, D., Zhang, H., Song, J., Zhang, R., Xu, R., Zhu, Q., Ma, S., Wang, P., Bi, X., Zhang, X., Yu, X., Wu, Y., Wu, Z. F., Gou, Z., Shao, Z., Li, Z., Gao, Z., Liu, A., ... Zhang, Z. (2025). DeepSeek-R1: Incentivizing reasoning capability in LLMs via reinforcement learning. *Nature*, 645, 633–638. https://doi.org/10.1038/s41586-025-09422-z (arXiv:2501.12948).

Han, H., Ma, L., Wang, Y., Tang, J., et al. (2025). RAG vs. GraphRAG: A systematic evaluation and key insights. *arXiv preprint arXiv:2502.11371*.

Hipp, D. R. (n.d.). *Atomic Commit in SQLite*. SQLite Consortium Documentation. https://www.sqlite.org/atomiccommit.html

Howard, W. A. (1980). The formulae-as-types notion of construction. In J. P. Seldin & J. R. Hindley (Eds.), *To H. B. Curry: Essays on Combinatory Logic, Lambda Calculus, and Formalism* (pp. 479–491). Academic Press.

Justin Martyr. (c. 155 CE / 1997). *The First and Second Apologies* (L. W. Barnard, Trans.). Paulist Press. (*First Apology*, chs. 65–67).

Landauer, R. (1961). Irreversibility and heat generation in the computing process. *IBM Journal of Research and Development*, 5(3), 183–191.

Lee, J., Chen, A., Dai, Z., Dua, D., Sachan, D. S., Boratko, M., Luan, Y., Arnold, S. M. R., Perot, V., Dalmia, S., Hu, H., Lin, X., Pasupat, P., Amini, A., Cole, J. R., Riedel, S., Naim, I., Chang, M.-W., & Guu, K. (2024). Can long-context language models subsume retrieval, RAG, SQL, and more? *arXiv preprint arXiv:2406.13121* (LOFT).

Lewis, P., Perez, E., Piktus, A., Petroni, F., Karpukhin, V., Goyal, N., Küttler, H., Lewis, M., Yih, W.-t., Rocktäschel, T., Riedel, S., & Kiela, D. (2020). Retrieval-augmented generation for knowledge-intensive NLP tasks. In *Advances in Neural Information Processing Systems (NeurIPS 2020)*, 33, 9459–9474.

Li, Z., Li, C., Zhang, M., Mei, Q., & Bendersky, M. (2024). Retrieval augmented generation or long-context LLMs? A comprehensive study and hybrid approach. In *Proceedings of the 2024 Conference on Empirical Methods in Natural Language Processing: Industry Track (EMNLP 2024)*.

Liu, N. F., Lin, K., Hewitt, J., Paranjape, A., Bevilacqua, M., Petroni, F., & Liang, P. (2024). Lost in the middle: How language models use long contexts. *Transactions of the Association for Computational Linguistics*, 12, 157–173.

Lorenz, E. N. (1963). Deterministic nonperiodic flow. *Journal of the Atmospheric Sciences*, 20(2), 130–141.

Mac Lane, S. (1998). *Categories for the Working Mathematician* (2nd ed., Graduate Texts in Mathematics, Vol. 5). Springer. (Original work published 1971).

Minson, J. A., & Monin, B. (2012). Do-gooder derogation: Disparaging morally motivated minorities to defuse anticipated reproach. *Social Psychological and Personality Science*, 3(2), 200–207.

Nicolis, G., & Prigogine, I. (1977). *Self-Organization in Nonequilibrium Systems: From Dissipative Structures to Order through Fluctuations*. Wiley-Interscience.

Park, K., Choe, Y. J., & Veitch, V. (2024). The linear representation hypothesis and the geometry of large language models. In *Proceedings of the 41st International Conference on Machine Learning (ICML 2024)*, *Proceedings of Machine Learning Research (PMLR)*, 235, 39643–39666.

Plato. (1997). *Apology* (21d) and *Phaedrus* (274b–275e). In J. M. Cooper (Ed.), *Plato: Complete Works*. Hackett Publishing.

Popper, K. R. (1959). *The Logic of Scientific Discovery*. Hutchinson & Co. (Original work published 1934 as *Logik der Forschung*).

Rissanen, J. (1978). Modeling by shortest data description. *Automatica*, 14(5), 465–471.

Shannon, C. E. (1938). A symbolic analysis of relay and switching circuits. *Transactions of the American Institute of Electrical Engineers*, 57(12), 713–723.

Shannon, C. E. (1948). A mathematical theory of communication. *The Bell System Technical Journal*, 27(3), 379–423; 27(4), 623–656.

Sharma, M., Tong, M., Korbak, T., Duvenaud, D., Askell, A., Bowman, S. R., Cheng, N., Durmus, E., Hatfield-Dodds, Z., Johnston, S. R., Kravec, S., Maxwell, T., McCandlish, S., Ndousse, K., Rausch, O., Schiefer, N., Yan, D., Zhang, M., & Perez, E. (2024). Towards understanding sycophancy in language models. In *Proceedings of the Twelfth International Conference on Learning Representations (ICLR 2024)*.

Shumailov, I., Shumaylov, Z., Zhao, Y., Papernot, N., Anderson, R., & Gal, Y. (2024). AI models collapse when trained on recursively generated data. *Nature*, 631(8022), 755–759. https://doi.org/10.1038/s41586-024-07566-y

Snell, C., Lee, J., Xu, K., & Kumar, A. (2025). Scaling LLM test-time compute optimally can be more effective than scaling model parameters. In *Proceedings of the Thirteenth International Conference on Learning Representations (ICLR 2025, Oral)* (arXiv:2408.03314).

Tarski, A. (1944). The semantic conception of truth and the foundations of semantics. *Philosophy and Phenomenological Research*, 4(3), 341–376.

Vaswani, A., Shazeer, N., Parmar, N., Uszkoreit, J., Jones, L., Gomez, A. N., Kaiser, Ł., & Polosukhin, I. (2017). Attention is all you need. In *Advances in Neural Information Processing Systems (NIPS 2017)*, 30, 6000–6010.

Vlastos, G. (1983). The Socratic elenchus. *Oxford Studies in Ancient Philosophy*, 1, 27–58.

Washington Post. (2026, November 20). Using Anthropic AI, mathematician claims to have solved Riemann Hypothesis. *The Washington Post*. https://www.washingtonpost.com/technology/2026/11/20/using-anthropic-ai-mathematician-claims-have-solved-riemann-hypothesis/

Whitehead, A. N. (1978). *Process and Reality: An Essay in Cosmology* (Corrected ed., D. R. Griffin & D. W. Sherburne, Eds.). The Free Press. (Original work published 1929).

Xiang, Z., Wu, C., Zhang, Q., Huang, X., Su, J., et al. (2025). GraphRAG-Bench: Challenging domain-specific reasoning for evaluating graph retrieval-augmented generation. *arXiv preprint arXiv:2506.05690*.

Zhou, X., Liu, Z., Sims, A., Wang, H., Pang, T., Li, C., Wang, L., Lin, M., & Du, C. (2025). Reinforcing general reasoning without verifiers (VeriFree). *arXiv preprint arXiv:2505.21493*.

---

## Appendix A: The Decoupled Alignment Invariant & Open Falsification Challenge

Standard AI alignment treats truthfulness and consistency as properties baked into model weights or stuffed into larger prompt histories. That framing rests on three flawed axioms: **(1) Weights-Only Obedience** (assuming a model trained to please human raters will not Goodhart its own verifier when generator and judge share a reward), **(2) Context-Window Omniscience** (assuming unstratified history improves reasoning, when it actually mixes dead ends with live rules and spikes thinking cost), and **(3) Binary Memory** (forcing a choice between amnesia and irreversible rejection).

This monograph redefines alignment as **an externalized, relational property of a decoupled system**: once a language model clears basic instruction comprehension, durable epistemic reliability requires **(a) decoupled local state**, **(b) storage-engine verifier-scope coupling**, and **(c) defeasible negative provenance**.

### Explicit Scope Exclusions

To test this thesis in its infancy without strawmen or technicalities, three already-conceded boundaries are explicitly excluded from falsification claims: (i) hardware/capacity failures below the comprehension knee already documented in Section 5.3 (such as 2023-vintage `llama2:7B` on `8 GB` RAM); (ii) cosmetic prose or bibliographic errata; and (iii) the non-functorial humanities analogies and comparative typology developed in Part III.

### Three Formal Falsification Criteria

The project stakes its core architectural invariant on three concrete, reproducible falsification targets:

1. **Refute State Decoupling:** On a reproducible multi-turn stateful contradiction and rule-update benchmark ($N \ge 50$ steps with mid-run rule reversals), demonstrate an **ungated, weights/context-only** model (zero external relational store, state register, or external verifier) that achieves **0% post-correction contradiction recurrence**, resists prompt-induced verifier theater, and uses **`< 2×`** the total tokens (including provider thinking tokens) of the same SQLite-gated model.
2. **Break the Anti-Theater Trigger:** Execute a valid SQLite transaction against the unmodified reference `schema/schema.sql` and `scripts/db_utils.py` that commits an `EXTERNALLY_VERIFIED` or `FALSIFIED` `literature_citation` or `primary_record` node backed solely by `python_sim` or `llm_only` (or a `pycheck:` hash).
3. **Break Defeasibility (Amnesia or Dogmatism):** Demonstrate either a valid primary-source (`doi:`, `pmid:`, `arxiv:`, or `https://`) counter-evidence record that *cannot* reopen a `FALSIFIED` node via `reopen_falsified_node()`, or an `llm_only` self-assertion that *can* reopen one without primary evidence.

> If an independent researcher breaks Criterion 1, they genuinely advance in-weight alignment; if they break Criterion 2 or 3, they expose a concrete state-machine bug to patch; if all three hold, the decoupled alignment invariant stands on its own terms.

### Open Tinkerer Roadmap (Next Steps)

Independent builders testing or extending this architecture have two high-leverage empirical frontiers open right now:

- **Frontier 1 — Offline Capability-Knee Sweep (`>= 16 GB` Local Silicon):** Run `scripts/benchmark_gauntlet.py --backend ollama` across modern `3B–14B` open-weight models (`qwen2.5:7b/14b`, `llama3.2:3b`, `llama3.3`, `gemma-3`) on upgraded `Ollama >= 0.3` to map the exact local parameter and quantization floor where SQLite gating crosses the semantic knee offline.
- **Frontier 2 — Multi-Domain Non-Arithmetic Replication ($N \ge 100$):** Replicate the three-arm ablation (`ungated_full_history` vs. `matched_token_hybrid_rag` vs. `sqlite_gated`) across $N \ge 100$ multi-seed, non-arithmetic stateful update tasks—such as clinical protocol revisions, statutory/policy amendments, and multi-file code refactorings—where ground truth cannot be stored in a scalar register.

## Appendix B: Reproducible System How-To & Architecture Diagrams

This self-contained engineering manual enables any outside engineer to reconstruct, inspect, and replicate the complete Decoupled Neuro-Symbolic State Gating stack from zero using only local Python 3 and SQLite 3 (compiled with FTS5). Every table, column, trigger, function signature, and CLI flag below is transcribed directly from the live repository (`schema/schema.sql`, `scripts/db_utils.py`, `scripts/arachne_bridge.py`, `scripts/stage0_ingest.py`, `scripts/migrate_schema_v3.py`, `scripts/compile_digest.py`, `scripts/single_loop_runner.py`, `scripts/benchmark_gauntlet.py`, and `scripts/test_pilot_harness.py`).

### B.1 Minimal Directory Layout & Zero-Cloud Dependencies

The core ledger requires **zero external vector databases and zero cloud hosting**. Stage 0 ingestion, FTS5 indexing, schema v3 enforcement, and the Kestrel-7 `--self-test` oracle run on pure Python 3 standard library (`sqlite3`, `hashlib`, `subprocess`, `unittest`, `urllib.request`); hybrid TF-IDF RRF reranking and parent-turn DAG backtracking (`scripts/arachne_bridge.py` and `scripts/eval_arachne_bridge.py`) adds only local `numpy` and `scikit-learn`. Optional inference backends connect either to local Ollama (`http://127.0.0.1:11434/api/generate`) or to the Gemini API (`google-genai` with `GEMINI_API_KEY`).

```text
Corpus/
├── schema/
│   └── schema.sql               # Core DDL (11 tables, FTS5, trg_verif_scope_coupling)
├── config/
│   └── spark_watchlist.example.txt # Template watchlist for optional live sync (copy to spark_watchlist.txt)
├── data/
│   ├── archive.db               # Optional local web-chat archive populated by scraper/ (gitignored)
│   └── corpus.db                # Portable local ACID SQLite ledger (WAL + foreign_keys=ON)
├── chapters/
│   ├── core_digest.md           # Prompt-cacheable ~24 KB summary + # KEYWORD: anchor map
│   └── digest_slices/           # Delta-recompiled per-theme markdown slices
├── scraper/
│   ├── gemini_archiver.py       # Playwright/CDP archiver (scroll-and-hydrate & PARTIAL_VIRTUALIZATION)
│   ├── sync_gemini.py           # Incremental multi-surface Gemini web sync into data/archive.db
│   └── capture_spark_chat.py    # Targeted single-URL Gemini / Spark conversation archiver
└── scripts/
    ├── db_utils.py              # Gatekeeper API (atomic lock, F2.2, reopen_falsified_node)
    ├── stage0_ingest.py         # $0 SHA-256 ingestion, FTS5 indexing & slice noise triage
    ├── migrate_schema_v3.py     # Non-destructive v3 migration & audit-flag queue builder
    ├── compile_digest.py        # Delta digest compiler & <= 2,200-token pre-tick hydrator
    ├── single_loop_runner.py    # Stateless Step A (Lifter) -> B (Scientist) -> C (Falsifier)
    ├── brain.py / brain_mcp.py  # Read-only query CLI & 7-tool stdio MCP bus
    ├── corpus_cli.py            # Unified CORPUS_HOME CLI (status/sync/verify/build/queue)
    ├── sync_and_ingest.py       # Closed-loop delta sync & read-only --audit-hydration gate
    ├── backfill_archive_virtualization.py # Safe timestamp-backed-up HTML recovery for virtualized archives
    ├── benchmark_gauntlet.py    # 20-step Kestrel-7 3-arm gauntlet & deterministic --self-test
    └── test_pilot_harness.py    # 11-test end-to-end invariant, MCP/CLI & DOM non-regression suite
```

### B.2 Core SQLite DDL & Anti-Theater Trigger (`schema/schema.sql`)

Initialize a fresh SQLite ledger with `PRAGMA foreign_keys = ON;` and `PRAGMA journal_mode = WAL;`. The five core epistemic tables enforce hard chunk provenance, self-loop prohibition (`CHECK (from_node != to_node)`), all seven epistemic tiers, all nine directed edge relations (including `reopens`, `challenges_falsification`, and `splits_from`), and engine-level verifier-scope coupling inside SQLite itself:

```sql
PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

-- 1. Deduplicated source chunks + global FTS5 index
CREATE TABLE IF NOT EXISTS chunks (
    chunk_id     INTEGER PRIMARY KEY,
    source_type  TEXT NOT NULL,          -- 'chat_db','pdf','docx','md','txt','json','html','csv'
    source_ref   TEXT NOT NULL,          -- file path or conversation_id
    author       TEXT,
    created_at   TEXT,
    sha256       TEXT UNIQUE NOT NULL,
    content      TEXT NOT NULL
);
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
    content, content='chunks', content_rowid='chunk_id'
);

-- 2. Atomic epistemic claims + hard chunk provenance
CREATE TABLE IF NOT EXISTS nodes (
    node_id         INTEGER PRIMARY KEY,
    domain          TEXT NOT NULL,
    dsl_expr        TEXT,
    summary         TEXT NOT NULL,
    epistemic_tier  TEXT NOT NULL DEFAULT 'RAW_CLAIM'
                    CHECK (epistemic_tier IN (
                        'RAW_CLAIM','DSL_CONSISTENT','SIM_CONSISTENT',
                        'CONTESTED','UNDER_APPEAL','EXTERNALLY_VERIFIED','FALSIFIED'
                    )),
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS node_provenance (
    node_id     INTEGER NOT NULL REFERENCES nodes(node_id) ON DELETE CASCADE,
    chunk_id    INTEGER NOT NULL REFERENCES chunks(chunk_id) ON DELETE CASCADE,
    quote_span  TEXT,
    PRIMARY KEY (node_id, chunk_id)
);

-- 3. Single-node verifications + directed edges (zero self-loops)
CREATE TABLE IF NOT EXISTS node_verifications (
    verification_id    INTEGER PRIMARY KEY,
    node_id            INTEGER NOT NULL REFERENCES nodes(node_id) ON DELETE CASCADE,
    verifier_type      TEXT NOT NULL CHECK (verifier_type IN (
                           'python_sim','lean_coq','public_record','literature_ref','llm_only')),
    verification_scope TEXT NOT NULL CHECK (verification_scope IN (
                           'toy_model','standard_physics_law','empirical_benchmark',
                           'primary_record','literature_citation','llm_only')),
    external_ref       TEXT,             -- pycheck:<sha256>, doi:, pmid:, arxiv:, or https://
    benchmark_ref      TEXT,
    passed             INTEGER NOT NULL CHECK (passed IN (0, 1)),
    notes              TEXT,
    created_at         TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS edges (
    edge_id        INTEGER PRIMARY KEY,
    from_node      INTEGER NOT NULL REFERENCES nodes(node_id) ON DELETE CASCADE,
    to_node        INTEGER NOT NULL REFERENCES nodes(node_id) ON DELETE CASCADE,
    relation_type  TEXT NOT NULL CHECK (relation_type IN (
                       'isomorphic_to','supports','breaks','refines','resolved_mistake',
                       'pivoted_to','reopens','challenges_falsification','splits_from')),
    verifier_type  TEXT NOT NULL DEFAULT 'llm_only' CHECK (verifier_type IN (
                       'python_sim','lean_coq','public_record','literature_ref','llm_only')),
    external_ref   TEXT,
    notes          TEXT,
    created_at     TEXT NOT NULL DEFAULT (datetime('now')),
    CHECK (from_node != to_node)
);
```

Auxiliary tables in `schema/schema.sql` handle scoped slice queues (`chapter_slices`), anti-spin branch halting (`research_branches` with `max_dry_hops = 3` and states `ACTIVE` / `HALTED_NOVELTY` / `CONVERGED`), bidirectional query expansion (`concept_bridges`), delta watermarks (`digest_state`), read-only session logs (`ingested_artifacts`, locked strictly to `RAW_CLAIM`), and audit queues (`node_audit_flags`). Crucially, the anti-theater invariant is enforced **inside the SQLite storage engine** via `BEFORE INSERT` trigger `trg_verif_scope_coupling`, so even raw SQL cannot commit `python_sim` or `pycheck:` hashes on literature/primary scopes:

```sql
CREATE TRIGGER IF NOT EXISTS trg_verif_scope_coupling
BEFORE INSERT ON node_verifications
BEGIN
    SELECT CASE
        WHEN NEW.verifier_type = 'python_sim'
             AND NEW.verification_scope IN ('literature_citation', 'primary_record')
        THEN RAISE(ABORT, 'Verifier-scope lock (F2.2): python_sim cannot verify literature_citation or primary_record')
        WHEN NEW.verifier_type IN ('literature_ref', 'public_record')
             AND (
                 NEW.external_ref IS NULL
                 OR lower(NEW.external_ref) LIKE 'pycheck:%'
                 OR (lower(NEW.external_ref) NOT LIKE 'doi:%'
                     AND lower(NEW.external_ref) NOT LIKE 'pmid:%'
                     AND lower(NEW.external_ref) NOT LIKE 'arxiv:%'
                     AND lower(NEW.external_ref) NOT LIKE 'https://%')
             )
        THEN RAISE(ABORT, 'External identifier lock (F2.2): literature_ref/public_record requires doi:, pmid:, arxiv:, or https:// external_ref')
        WHEN NEW.verification_scope IN ('literature_citation', 'primary_record')
             AND NEW.external_ref IS NOT NULL
             AND lower(NEW.external_ref) LIKE 'pycheck:%'
        THEN RAISE(ABORT, 'External identifier lock (F2.2): pycheck: hashes are forbidden for literature_citation or primary_record')
    END;
END;
```

### B.3 Atomic Gating, Packet Budgeting (`<= 2,200` Tokens) & Defeasible Appeal Workflow

All write operations route through `scripts/db_utils.py`, while pre-tick working-memory packets are assembled strictly on demand via `hydrate_pre_tick()` in `scripts/compile_digest.py`:

- **Single-Claim Atomicity & Provenance (`create_node_with_provenance`):** Rejects empty `chunk_ids`, rejects starting tiers outside `('RAW_CLAIM', 'DSL_CONSISTENT', 'CONTESTED')`, and runs `validate_atomic_claim(summary)` to block compound numbered lists (`(1)...(2)...`), `"valid ... paired with flawed"` bundles, and long multi-semicolon compounds (`>= 2` semicolons and `> 260` chars). Existing legacy compound `FALSIFIED` parents are decomposed non-destructively into single-claim children linked by `edges.relation_type = 'splits_from'`, rescuing valid sub-claims cleanly to `RAW_CLAIM` while keeping failing sub-claims at `FALSIFIED`.
- **Bounded Working-Memory Packet (`<= 2,200` Tokens):** On every tick or query, `hydrate_pre_tick(conn, domain, query_text, token_budget=2200)` cleans boilerplate tokens (`filter_query_text`), expands cross-domain terms via `concept_bridges` (`search_corpus_global`), retrieves FTS5 BM25 hits plus optional read-only `archive.db?mode=ro` DAG parents, **suppresses chunks attached to `FALSIFIED` nodes from positive context slices**, and injects active `[NEGATIVE CONSTRAINTS]` (`FALSIFIED -> pivoted_to` pairs) alongside a compact `core_digest.md` anchor block—strictly enforcing `estimated_tokens <= 2200` (`max(int(words_and_punct * 1.15), int(len(text) / 3.9))`).
- **Defeasible Negative Provenance (`reopen_falsified_node`):** Refuted claims stay pinned as `FALSIFIED` (preventing amnesia) while remaining permanently appealable when new non-`llm_only` primary evidence arrives (preventing dogmatism). Calling `reopen_falsified_node()` writes a directed `challenges_falsification` or `reopens` edge, records the compliant verification row in `node_verifications`, transitions the target node to `UNDER_APPEAL`, `CONTESTED`, or `EXTERNALLY_VERIFIED`, and revives any `CONVERGED` `research_branches` row back to `ACTIVE`:

```python
from scripts.db_utils import (
    create_node_with_provenance, get_connection, reopen_falsified_node,
    run_physics_check, verify_and_link, verify_node,
)

conn = get_connection("data/corpus.db")
# 1. Verify a quantitative physics claim via local sandbox (pycheck:<sha256>)
chk = run_physics_check("c = 299792458.0; assert abs((c/1.333)/c - 0.7502) < 1e-3; print('ok')")
verify_node(conn, node_id=n_reframe, verifier_type="python_sim",
            verification_scope="standard_physics_law", external_ref=chk["external_ref"],
            benchmark_ref="Snell/Ewald-Oseen phase velocity v = c/n",
            new_tier="EXTERNALLY_VERIFIED")

# 2. Falsify a competing claim & link 1:1 to its Reframed Solver (never delete!)
verify_and_link(conn, from_node_id=n_claim, to_node_id=n_reframe, relation_type="pivoted_to",
                verifier_type="python_sim", verification_scope="standard_physics_law",
                external_ref=chk["external_ref"], benchmark_ref="Non-resonant dielectric v = c/n",
                promote_node_id=n_claim, new_tier="FALSIFIED")

# 3. Defeasibly reopen FALSIFIED ONLY with primary evidence (llm_only raises ValueError)
reopen_falsified_node(conn, target_node_id=n_claim, challenging_node_id=n_appeal,
                      verifier_type="literature_ref", verification_scope="literature_citation",
                      external_ref="doi:10.1038/17561",
                      benchmark_ref="Hau et al. (1999) Nature 397, 594 slow light in BEC",
                      relation_type="challenges_falsification", new_tier="UNDER_APPEAL")
```

### B.4 Step-by-Step Build, Single-Loop Runtime, Kestrel-7 Gauntlet & 11/11 Test Suite

Run the following exact repository commands from `$CORPUS_HOME` (recommended: `~/Developer/Corpus`, outside macOS TCC-protected `~/Downloads`) to stand up a clean local replica, compile digests, run stateless compilation ticks, execute the Kestrel-7 self-test or local Ollama gauntlet, and verify every architectural invariant:

```bash
# 0. Step 0 (Optional — Scrape Your Own Gemini Web History via Playwright):
#    Install Playwright + Chromium once, then archive into ./data/archive.db with scroll-and-hydrate
pip install playwright && playwright install chromium
python3 scraper/gemini_archiver.py --cli --output ./data --max-turns 5000
#    Verify 100% turn hydration (hydrated_turns / total_dom_slots) & recover any legacy HTML stubs
python3 scripts/sync_and_ingest.py --audit-hydration --archive-db data/archive.db
python3 scripts/backfill_archive_virtualization.py --archive-db data/archive.db

# 1. Stage 0 ($0 API): ingest raw docs or read-only data/archive.db & tag a scoped slice
python3 scripts/stage0_ingest.py --input data/archive.db --db data/replica.db \
    --build-physics-slice --slice-name physics_pilot --slice-limit 1000

# 2. Apply non-destructive Schema v3 migration (CONTESTED/UNDER_APPEAL, trigger lock)
python3 scripts/migrate_schema_v3.py --db data/replica.db

# 3. Compile ~24 KB core_digest.md + slices & inspect watermarks / <=2,200-tok packet
python3 scripts/compile_digest.py compile --db data/replica.db --force
python3 scripts/brain.py --db data/replica.db --cmd "status"
python3 scripts/brain.py --db data/replica.db --cmd "query refraction superposition --dry-run"

# 4. Run stateless Single-Loop compilation (Step A Lifter -> B Scientist -> C Falsifier)
#    Option A: Direct API loop (Gemini or local Ollama)
python3 scripts/single_loop_runner.py run --backend ollama --db data/replica.db \
    --slice-name physics_pilot --domain physics --limit 20 --batch-size 10 --packet-budget 2200
#    Option B: Deterministic stateless prepare/apply mode (for any external orchestrator)
python3 scripts/single_loop_runner.py step prepare-lifter --db data/replica.db \
    --slice-name physics_pilot --domain physics --limit 10 --batch-tag b1

# 5. Verify Kestrel-7 deterministic oracle & token budgets, or run local Ollama sweep
python3 scripts/benchmark_gauntlet.py --self-test
python3 scripts/benchmark_gauntlet.py --backend ollama --models qwen2.5:7b --json-modes off,on

# 6. Execute 11-test CI invariant suite (isolated TemporaryDirectory; never mutates live DB)
python3 -m unittest scripts/test_pilot_harness.py -v
```

*Table 6. Complete 11-test verification matrix executed by `scripts/test_pilot_harness.py` (isolated `TemporaryDirectory`, zero live-DB mutations).*

| # | Test Method (`PilotHarnessTests`) | Exact Architectural Invariant Verified |
| :---: | :--- | :--- |
| 1 | `test_stage0_dedup_slice_and_cross_domain_recall` | SHA-256 idempotent deduplication, `chapter_slices` tagging, `concept_bridges` FTS5 expansion & `get_chunk_context()`. |
| 2 | `test_sqlite_db_auto_ingestion` | Generic external `.db` chat-table auto-detection into `chunks` (`source_type='chat_db'`). |
| 3 | `test_gemini_archive_schema_adapter_and_noise_filter` | Read-only Gemini `archive.db` adapter (`conversations`/`turns`/`cas_fts`/`concept_bridges`) & domestic-noise filtering. |
| 4 | `test_epistemic_locks_physics_check_and_halting_budget` | `llm_only` promotion block, self-loop `CHECK`, `toy_model` ceiling (`SIM_CONSISTENT`), `run_physics_check()`, `HALTED_NOVELTY` at 3 dry hops. |
| 5 | `test_mcp_stdio_roundtrip` | JSON-RPC stdio roundtrip across `scripts/corpus_mcp.py` tools (`get_pilot_status`, `search_corpus_global`, `hydrate_tick_context`, etc.). |
| 6 | `test_digest_delta_compilation_and_ouroboros_watermark` | Zero-churn delta compilation, Ouroboros watermark sync, `<= 1,800`-tok hydration, `FALSIFIED` positive-slice suppression, byte-identical static prefix. |
| 7 | `test_ingest_artifact_query_hygiene_and_brain_shell` | Query stopword hygiene (`filter_query_text`), `PROVENANCE_LOG` lock (`RAW_CLAIM`), and `brain.py` read-only commands. |
| 8 | `test_brain_mcp_and_sync_and_ingest_closed_loop` | Closed-loop Spark/Gemini sync, DOM stripping, cooldown lock, and zero auto-promotion of ingested session logs. |
| 9 | `test_phase1_verifier_coupling_defeasibility_and_atomicity` | Atomic claim lock (`F2.3`), `python_sim`/`pycheck:` block in both Python & raw SQL `trg_verif_scope_coupling` (`F2.2`), and `reopen_falsified_node()` (`F2.1`). |
| 10 | `test_handoff_queue_brain_mcp_and_unified_cli` | Schema v3 `handoff_queue` CRUD/PR lifecycle, 7-tool `brain_mcp.py` JSON-RPC contract, and `corpus_cli.py` `status`/`queue`/`verify`. |
| 11 | `test_dom_virtualization_non_regression_and_hydration_audit` | `merge_turn_non_regressive()` empty-stub overwrite guard, `audit_archive_hydration()` `PARTIAL_VIRTUALIZATION` detection, and non-fabricating `UNRECOVERABLE_REMOTE` backfill. |

### B.5 Browser DOM Scroll-and-Hydrate Ingestion & Unified `CORPUS_HOME` Operations

Two operational failure modes discovered during sustained local deployment—silent Angular DOM virtualization truncation and macOS `launchd` TCC permission errors—require explicit invariants in every builder deployment:

- **Scroll-and-Hydrate DOM Ingestion Rule (`hydrated_turns / total_dom_slots`):** Modern web-chat UIs (including Angular's Gemini client) apply off-screen layout skipping (`content-visibility: auto`), causing Chromium's layout-dependent `element.innerText` to return `""` on un-painted turn containers even while `element.innerHTML` holds the full DOM subtree (causing `5,801 / 8,980` silent empty turn stubs prior to remediation, vs. `0` loss on local Codex CLI JSONL rollouts). Any browser archiver targeting `archive.db` **must**: (1) walk every `div.conversation-container` top-to-bottom with `scrollIntoView({ behavior: 'instant', block: 'center' })` + settle wait and bounded retries until `innerText` is non-empty, falling back to stripped `textContent`/`innerHTML` when CSS suppresses paint; (2) compute and log `hydrated_turns / total_dom_slots`, setting `status = 'PARTIAL_VIRTUALIZATION'` loudly whenever `hydrated_turns < total_dom_slots`; and (3) enforce `merge_turn_non_regressive()` in the DB writer and `scripts/sync_and_ingest.py` so an empty DOM stub can never overwrite an already-populated turn or advance its `ingested_turn_ids` watermark. Existing archives with empty stubs can be audited read-only and safely backfilled from `user_html`/`model_html` after an automated SQLite online backup:

```bash
# Audit archive.db (?mode=ro) for empty virtualized DOM stubs (hydrated_turns / total_dom_slots)
python3 scripts/sync_and_ingest.py --audit-hydration --archive-db /path/to/archive.db

# Safe timestamp-backed-up local HTML backfill (flags any truly absent slot UNRECOVERABLE_REMOTE)
python3 scripts/backfill_archive_virtualization.py --archive-db /path/to/archive.db
```

- **Unified `CORPUS_HOME`, `corpus_cli.py`, `handoff_queue` & `brain_mcp.py` Workflow:** On macOS, keep the repository outside TCC-gated directories (`~/Downloads`, `~/Desktop`, `~/Documents`)—specifically at **`~/Developer/Corpus`**—and export `CORPUS_HOME` so `Makefile`, `scripts/corpus_cli.py`, `scripts/brain_mcp.py`, and `config/com.corpus.closedloop.plist` remain 100% path-agnostic. Daily operations consolidate into four deterministic interfaces:

```bash
export CORPUS_HOME="$HOME/Developer/Corpus"
make status                                  # Read-only DB counts, open flags, digest watermark & queue
make sync                                    # Closed-loop delta sync (archive.db?mode=ro -> RAW_CLAIM chunks)
make verify                                  # PRAGMA integrity/FK checks, 11/11 tests & PDF SHA-256 checks
make build VOL=all                           # Re-render Vols I, II, III & Failures/Parables + .sha256

# PR-style structured task bus (handoff_queue) & unified 7-tool stdio MCP server (brain_mcp.py)
python3 scripts/corpus_cli.py queue list
python3 scripts/corpus_cli.py queue enqueue --title "Verify frontier batch" --spec "Run Kestrel-7 on qwen2.5:7b"
python3 scripts/corpus_cli.py queue approve 1 && python3 scripts/corpus_cli.py queue run 1 --cmd "make verify"
python3 scripts/brain_mcp.py                 # JSON-RPC 2.0 stdio: corpus_status, get_packet, query_nodes, check_flags, handoff_queue
```

---

## Appendix C: Internal Corpus Provenance (`?mode=ro`)

This appendix provides read-only traceability between Sections 1–6 and the frozen local epistemic kernel ([data/corpus.db](../data/corpus.db), `?mode=ro`, post-v3 remediation & Nov 21 scroll-and-hydrate backfill freeze) plus empirical benchmark artifacts as of **`2026-11-21`** (`2026-11-21T02:23:40Z` / `12:23:40 AEST`).

### C.1 Post-Remediation Schema v3 Kernel Snapshot & Empirical Artifacts

- **Verified Pre-Migration & Pre-Backfill Backups:** `data/corpus.db.bak.20261119_pre_v3` (`76,865,536` bytes, `sha256=abdea386ef145838`, `893` pre-v3 nodes), `data/corpus.db.bak.20261120_152209` (`76,865,536` bytes, `sha256=df6a048b4328f6a8...`, `893` pre-remediation v3 nodes), and `data/corpus.db.bak.20261121T015842Z_pre_backfill_ingest` (`77,438,976` bytes, `31,737` pre-backfill chunks).
- **Frozen Post-Remediation Schema v3 Telemetry (`data/corpus.db?mode=ro`, `120,971,264` B / `115.37 MB`):** **`52,137` deduplicated source chunks** (`31,497` at Nov 20 remediation + `+20,640` additive `RAW_CLAIM` chunks from the Nov 21 DOM HTML backfill and final scroll-and-hydrate sync across `350` conversations / `9,080` fully hydrated turns in `archive.db`); **`1,122` atomic nodes** (`537 EXTERNALLY_VERIFIED`, `382 FALSIFIED`, `163 RAW_CLAIM`, `28 CONTESTED`, `12 SIM_CONSISTENT`, `0 UNDER_APPEAL`); **`2,143` typed directed edges** (`1,231 supports`, `384 pivoted_to`, `267 resolved_mistake`, `229 splits_from`, `18 refines`, `14 breaks`); `463` live HTTP-200 verified primary `doi:`/`https://` records (`0` unbacked `pycheck:` literature nodes); **`0 / 539` open `node_audit_flags`** (all `539` resolved); `337` `concept_bridges`; `PRAGMA integrity_check = ok`; `0` foreign-key violations.
- **Core Digest Watermark:** [chapters/core_digest.md](../chapters/core_digest.md) (`24,241` bytes / `23.67 KB`, `CORE_DIGEST` watermark `max_node=#893`, `max_turn=9158`, `sha=7eb406696bc4`).
- **Verification & Benchmark Artifacts:**
  - Adversarial falsification audit & Trilogy redline report: [chapters/thesis_falsification_audit.md](../chapters/thesis_falsification_audit.md), [chapters/trilogy_redline_vetting_report.md](../chapters/trilogy_redline_vetting_report.md)
  - Schema v3 & enforcement code: [schema/schema.sql](../schema/schema.sql), [scripts/db_utils.py](../scripts/db_utils.py), [scripts/migrate_schema_v3.py](../scripts/migrate_schema_v3.py), [scripts/test_pilot_harness.py](../scripts/test_pilot_harness.py) (`11/11` passed)
  - Exp. 1 (Re-Audited): [chapters/ab_benchmark_report.md](../chapters/ab_benchmark_report.md), [scripts/benchmark_ab.py](../scripts/benchmark_ab.py), [data/benchmark_results.json](../data/benchmark_results.json)
  - Exp. 2 (Compilation): [chapters/single_loop_pilot_report.md](../chapters/single_loop_pilot_report.md), [scripts/single_loop_runner.py](../scripts/single_loop_runner.py)
  - Exp. 3 (Kestrel-7 Gauntlet): [chapters/gauntlet_capability_report.md](../chapters/gauntlet_capability_report.md), [scripts/benchmark_gauntlet.py](../scripts/benchmark_gauntlet.py), [data/gauntlet_results.json](../data/gauntlet_results.json)

### C.2 Key Node Anchors & Post-Remediation Tier Status

- **Verified Physics / Formal-Math / Primary-Literature Anchors (`EXTERNALLY_VERIFIED`, `537` total):** `#22` (Boltzmann arrow), `#354` (Shannon entropy & Lyapunov prediction horizon), `#375` (Coq kernel audit empirical benchmark), `#518` (universal-predicate indicator entropy trivialization `H(P)=0, I(P;X)=0`), plus live DOI/HTTPS-verified literature foundations `#306`, `#344`, `#352`, `#357`, `#358`, `#363`, `#404`, `#465`, `#466`, `#515`, `#545`, `#550`, `#566`, `#573`, `#574`, `#590`, `#594`, `#597`, `#598`, `#617`, `#630`, `#691`.
- **Honest Non-Rubber-Stamped Downgrades (`CONTESTED = 28`, `RAW_CLAIM = 163`, `SIM_CONSISTENT = 12`):** Speculative/debated conjectures (`#66`, `#116`, `#190`, `#234`, `#252`, `#377`, `#552`, `#701`, `#729`, `#757`, `#828`) remain at `CONTESTED` with exact primary DOIs; internal repository heuristics (`#422`, `#568`, `#576`, `#614`, `#628`, `#677`, `#679`, `#831`) and `112` rescued valid atomic split children sit cleanly at `RAW_CLAIM`; genuine toy prototypes (`#240`, `#620`, `#671`, `#812`) stay at `SIM_CONSISTENT`.
- **Enforced Negative-Provenance Guardrails (`FALSIFIED`, `382` total including `117` atomic split sub-claims):** `#580 → #597` (statistical isomorphism), `#581 → #598` (Tarskian truth invariance vs. relativism), `#556 → #590` & `#569 → #594` (Lorenz/circuit-breaker bounds), `#360 → #380` & `#405 → #438` (Gödel/explosion limits), `#180 → #218` & `#308 → #333` (classical Antikythera kinematics), `#397 → #434` (geometric chirality), `#548 → #587` & `#672 → #691` (attention/hash boundaries).
- **Indexed `concept_bridges`:** `everything is intelligent / panpsychist set collapse ↔ universal predicate entropy trivialization h(p)=0 & i(p;x)=0`; `consensus reward poisoning ↔ model collapse`; `attention saturation ↔ softmax context dilution`; `mousetrap in a while loop / retrospective mirror ↔ stateless transformer forward pass wrapped in deterministic orchestration & sqlite memory`; `sqlite falsifiability sieve ↔ transactional constraint verification for llm agents`; `sycophancy feedback loop ↔ template homogeneity`; `statistical isomorphism ↔ distributional semantics`.
