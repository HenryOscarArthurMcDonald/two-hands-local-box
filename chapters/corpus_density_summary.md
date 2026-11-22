# Corpus Disciplinary Density Summary

> **Database:** `data/corpus.db` (`?mode=ro`, read-only)  
> **Scope:** `31,060` non-empty chunks (`0` crawler/boilerplate chunks skipped), `5,247,745` words, `40,408,877` characters  
> **Method ($0 API):** `TfidfVectorizer(ngram_range=(1, 2), stop_words='english', max_df=0.85, min_df=5, sublinear_tf=True)` (`121,708` features) + `NMF(n_components=30, random_state=42)`; chunks with `max_topic_weight / sum < 0.28` flagged as `Miscellaneous / Multi-Topic`  
> **Chart:** [corpus_density_map.png](./corpus_density_map.png)

---

## 1. Discipline Density (Merged Single-Pass Labels)

| Discipline | Tier | Chunks | % Chunks | Words | % Words | Clusters | Representative Keywords |
| :--- | :--- | ---: | ---: | ---: | ---: | :--- | :--- |
| **AI / Systems & Software Architecture** | Major | 9,952 | 32.04% | 1,275,442 | 24.30% | T02, T04, T08, T09, T10, T14, T18, T22, T23, T26, T27 | `py`, `file`, `python`, `script`, `run`, `python3`, `assertequal`, `self assertequal` |
| **Formal Methods & Lean 4 Verification** | Major | 4,904 | 15.79% | 441,975 | 8.42% | T00, T01, T05, T06, T24, T25 | `projection operator`, `dialogue seed`, `seed projection`, `projection`, `operator`, `h1_valid`, `seed_hash`, `hashlib` |
| **Biology, Neurodivergence & Cognitive Psych** | Major | 4,830 | 15.55% | 1,086,642 | 20.71% | T29 | `high`, `brain`, `like`, `low`, `social`, `pda` |
| **Physics, Cosmology & Thermodynamics** | Major | 3,122 | 10.05% | 725,570 | 13.83% | T15, T16 | `universe`, `just`, `physics`, `like`, `geometry`, `quantum`, `carnot`, `dissipation carnot` |
| **Philosophy, Epistemology & Inquiry** | Major | 3,013 | 9.70% | 705,574 | 13.45% | T17, T28 | `user`, `ve`, `focusing`, `exploring`, `core`, `analyzing`, `inquiry`, `passage` |
| **Mathematics, Number Theory & Quant/Viz** | Minor | 1,883 | 6.06% | 449,195 | 8.56% | T21 | `pi`, `color`, `const`, `digits`, `digit`, `10` |
| **Information Theory, Bayes & Graph Math** | Minor | 637 | 2.05% | 99,729 | 1.90% | T07, T11, T12, T19 | `prior_odds`, `p_post`, `p_prior`, `posterior_odds`, `prior_odds prior_odds`, `nassert p_post`, `shannon source`, `shannon` |
| **Pharmacokinetics & Clearance Models** | Minor | 508 | 1.64% | 59,897 | 1.14% | T03, T13 | `life invariant`, `pharmacokinetic clearance`, `clearance half`, `macro`, `half life`, `pharmacokinetic`, `clearance`, `t_half` |
| **Ontology & Knowledge-Layer Axioms** | Minor | 197 | 0.63% | 32,746 | 0.62% | T20 | `timestamp 2025`, `2025 12`, `13_the_gold_syntropy type`, `layer 13_the_gold_syntropy`, `status sorted`, `13_the_gold_syntropy` |
| **Miscellaneous / Multi-Topic** | Miscellaneous | 2,014 | 6.48% | 370,975 | 7.07% | Diffuse | `multi-topic`, `diffuse`, `cross-domain`, `conversational` |

---

## 2. Raw Latent Clusters (`k = 30` NMF Topics + Diffuse Pool)

| Cluster | Assigned Discipline | Chunks | % Chunks | Words | Chars | Top 12 Keywords |
| :--- | :--- | ---: | ---: | ---: | ---: | :--- |
| `T29` | Biology, Neurodivergence & Cognitive Psych | 4,830 | 15.55% | 1,086,642 | 6,894,582 | high, brain, like, low, social, pda, just, pain, need, feel, adhd, internal |
| `T09` | AI / Systems & Software Architecture | 3,138 | 10.10% | 385,069 | 3,130,860 | source, model, evidence, live, md, ll, checks, existing, original, remain, tests, new |
| `T15` | Physics, Cosmology & Thermodynamics | 2,998 | 9.65% | 712,450 | 4,453,377 | universe, just, physics, like, geometry, quantum, space, time, energy, reality, physical, theory |
| `T17` | Philosophy, Epistemology & Inquiry | 2,660 | 8.56% | 644,378 | 4,234,983 | user, ve, focusing, exploring, core, analyzing, focus, thoughts, exposed thoughts, exposed, considering, concept |
| `T00` | Formal Methods & Lean 4 Verification | 2,503 | 8.06% | 195,234 | 1,464,255 | projection operator, dialogue seed, seed projection, projection, operator, h1_valid, h2_valid, dialogue, seed, hold, h1_valid h2_valid, h2 |
| `T21` | Mathematics, Number Theory & Quant/Viz | 1,883 | 6.06% | 449,195 | 2,887,213 | pi, color, const, digits, digit, 10, price, print, let, div, script, position |
| `T24` | Formal Methods & Lean 4 Verification | 1,697 | 5.46% | 132,366 | 991,685 | projection operator, dialogue seed, seed projection, projection, operator, h2_valid, h1_valid, dialogue, seed, hold, h1_valid h2_valid, h2 |
| `T02` | AI / Systems & Software Architecture | 1,402 | 4.51% | 239,954 | 1,755,061 | py, file, python, script, run, python3, bash, google, [redacted-user], terminal, code, files |
| `T26` | AI / Systems & Software Architecture | 1,180 | 3.80% | 112,444 | 1,882,042 | db, raise, valueerror, db execute, raise valueerror, self, id, execute, closing, store, connect, value |
| `T23` | AI / Systems & Software Architecture | 817 | 2.63% | 147,838 | 1,248,472 | print, codex, node, return, genesis, try, json, os, parent_node, def, new_id, type |
| `T14` | AI / Systems & Software Architecture | 767 | 2.47% | 140,323 | 1,347,120 | conn, conn execute, str, chat_id, execute, self, db_path, execute select, dict, select, turns, def |
| `T04` | AI / Systems & Software Architecture | 678 | 2.18% | 35,086 | 1,035,275 | assertequal, self assertequal, self, patch, def, asserttrue, self asserttrue, assertequal len, return_value, content, unittest, self root |
| `T27` | AI / Systems & Software Architecture | 609 | 1.96% | 49,297 | 941,141 | root, folder, json, state, read_text, self state, spec, atomic_json, json read_text, path, raise, json loads |
| `T10` | AI / Systems & Software Architecture | 536 | 1.73% | 71,090 | 679,501 | [redacted-home-path], desktop, users, desktop geminiaccountarchive, geminiaccountarchive, partner macbook, macbook air |
| `T22` | AI / Systems & Software Architecture | 394 | 1.27% | 41,673 | 612,005 | self send, api, send, return self, path, path api, self, return, urllib, urllib parse, store, parse |
| `T28` | Philosophy, Epistemology & Inquiry | 353 | 1.14% | 61,196 | 428,852 | inquiry, passage, project inquiry, step, source, ideas, understanding, inquiry state, henry, project, inform, structural engineer |
| `T03` | Pharmacokinetics & Clearance Models | 339 | 1.09% | 31,299 | 290,742 | life invariant, pharmacokinetic clearance, clearance half, macro, half life, pharmacokinetic, clearance, update operator, coherence update, cognitive belief, belief coherence, half |
| `T08` | AI / Systems & Software Architecture | 264 | 0.85% | 44,701 | 447,744 | 00 chat_id, completed created_at, related_skill_id, related_skill_id skill, id task, rationale, state completed, category, completed, task, created_at 2026, rationale active |
| `T01` | Formal Methods & Lean 4 Verification | 219 | 0.71% | 30,868 | 343,215 | seed_hash, hashlib, raw_bytes, seed invariant, seed_hash 16, sha256 raw_bytes, raw_bytes hexdigest, hexdigest nassert, nassert, violated, hashlib sha256, hexdigest |
| `T07` | Information Theory, Bayes & Graph Math | 214 | 0.69% | 37,747 | 369,007 | prior_odds, p_post, p_prior, posterior_odds, prior_odds prior_odds, nassert p_post, bayes_factor, coherence, p_post p_prior, coherence invariant, monotonicity, belief |
| `T06` | Formal Methods & Lean 4 Verification | 208 | 0.67% | 42,524 | 354,030 | exported specification, lean exported, skill skill, 279 convs, convs, 279, hold reinforced, reinforced macro, tactics, anchor hold, tier_1_formal verified, uses progress |
| `T20` | Ontology & Knowledge-Layer Axioms | 197 | 0.63% | 32,746 | 320,986 | timestamp 2025, 2025 12, 13_the_gold_syntropy type, layer 13_the_gold_syntropy, status sorted, 13_the_gold_syntropy, sorted id, tags, 2025, sorted, layer, timestamp |
| `T13` | Pharmacokinetics & Clearance Models | 169 | 0.54% | 28,598 | 289,577 | clearance, t_half, k_el, elimination, pharmacokinetic, c0, math, half life, macro 260, half, k_el t_half, 260 |
| `T18` | AI / Systems & Software Architecture | 167 | 0.54% | 7,967 | 234,450 | py, shutil, stage, shutil copyfile, copyfile, archive_vault, agent_capsule, project_compass, routed_research py, py corpus_profile, corpus_profile py, py project_compass |
| `T11` | Information Theory, Bayes & Graph Math | 160 | 0.52% | 28,521 | 270,533 | shannon source, shannon, avg_len, probs, source coding, sum, lengths, 125, optimal, macro 261, 261, 2f |
| `T05` | Formal Methods & Lean 4 Verification | 157 | 0.51% | 34,161 | 270,921 | tactic, conserve, invert, chain, tactic invert, composed tactic, assert, premise true, causal grounding, composed, macro tactic, tactic chain |
| `T12` | Information Theory, Bayes & Graph Math | 142 | 0.46% | 23,097 | 219,268 | handshaking, degrees, sum degrees, handshaking invariant, sum, topological handshaking, topological, simplegraph, corpus invariant, nassert, degree, trigger_context active |
| `T16` | Physics, Cosmology & Thermodynamics | 124 | 0.40% | 13,120 | 105,280 | carnot, dissipation carnot, carnot efficiency, efficiency bound, landauer dissipation, landauer, dissipation, efficiency, bound dialogue, bound, composition landauer, invariant landauer |
| `T19` | Information Theory, Bayes & Graph Math | 121 | 0.39% | 10,364 | 76,670 | tree lower, comparison tree, lower bound, asymptotic comparison, asymptotic, tree, comparison, lower, bound dialogue, bound, invariant asymptotic, composition asymptotic |
| `T25` | Formal Methods & Lean 4 Verification | 120 | 0.39% | 6,822 | 56,093 | string, string string, rfl, string seed, seed rfl, seed string, seed seed, kernel dialogue, seed, projection invariant, title corpus, 11 09t07 |
| `Diffuse` | Miscellaneous / Multi-Topic | 2,014 | 6.48% | 370,975 | 2,773,937 | chunks with dominant topic share < 0.28 or zero TF-IDF overlap |

---

## 3. Sizing Implications for Rings 2–4

- **Ring 1 Baseline (`Physics, Cosmology & Thermodynamics`):** `3,122` chunks (**10.05%** of chunks / **13.83%** of words), confirming substantial headroom beyond the `800`-chunk `physics_pilot` slice.
- **Ring 2 Candidate (`Formal Methods & Lean 4` + `Mathematics & Info Theory`):** `7,424` chunks (**23.90%** of chunks / **18.88%** of words) across Lean 4 formal proofs, Number Theory/Quant, Bayes, Shannon, and Graph Math.
- **Ring 3 Candidate (`AI / Systems & Software Architecture` + `Philosophy, Epistemology & Inquiry`):** `12,965` chunks (**41.74%** of chunks / **37.75%** of words) spanning agentic/software tooling and meta-reasoning traces.
- **Ring 4 Candidate (`Biology, Neurodivergence & Cognitive Psych` + `Pharmacokinetics` + `Ontology`):** `5,535` chunks (**17.82%** of chunks / **22.47%** of words); note that `T29` also absorbs some personal/everyday life threads alongside neurobiology.
