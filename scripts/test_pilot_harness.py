"""End-to-end verification tests for the Stage 0 + Physics Pilot + MCP harness."""

from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from db_utils import (
    attach_node_provenance,
    build_thematic_outline,
    create_node_with_provenance,
    get_chunk_context,
    get_connection,
    init_db,
    is_valid_primary_external_ref,
    reconcile_converged_branches,
    reopen_falsified_node,
    run_physics_check,
    search_corpus_global,
    validate_atomic_claim,
    verify_and_link,
    verify_node,
)
from seed_sample_corpus import seed_sample_corpus
from stage0_ingest import build_slice, detect_noise_skip_reason, ingest_path

MCP_SERVER = Path(__file__).resolve().parent / "corpus_mcp.py"


class PilotHarnessTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="corpus_test_")
        self.tmp_dir = Path(self._tmp.name)
        self.raw_dir = self.tmp_dir / "raw"
        self.db_path = self.tmp_dir / "corpus.db"
        seed_sample_corpus(self.raw_dir)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_stage0_dedup_slice_and_cross_domain_recall(self) -> None:
        stats = ingest_path(self.raw_dir, self.db_path)
        self.assertEqual(stats["files_seen"], 2)
        self.assertGreaterEqual(stats["chunks_inserted"], 4)

        # Second ingest of the exact same files must deduplicate via sha256.
        stats2 = ingest_path(self.raw_dir, self.db_path)
        self.assertEqual(stats2["chunks_inserted"], 0)
        self.assertGreaterEqual(stats2["duplicates_skipped"], 4)

        tagged = build_slice(self.db_path, slice_name="physics_pilot", limit=100)
        self.assertGreaterEqual(tagged, 2)

        conn = get_connection(self.db_path)
        try:
            # Global FTS5 search on "refraction" should pull both physics & non-physics
            # thermostat/systems note via the refraction <-> phase superposition bridge.
            res = search_corpus_global(conn, "refraction", limit=10, expand_bridges=True)
            sources = {h["source_ref"] for h in res["hits"]}
            self.assertTrue(any("physics_notes.json" in s for s in sources))
            self.assertTrue(any("systems_and_woodworking_notes.md" in s for s in sources))

            # Searching "mousetrap" pulls stateless forward pass bridge metadata
            res2 = search_corpus_global(conn, "mousetrap", limit=5, expand_bridges=True)
            self.assertTrue(any("mousetrap" in h["content"].lower() for h in res2["hits"]))

            # Context window around a hit returns surrounding chunks
            first_cid = res["hits"][0]["chunk_id"]
            ctx = get_chunk_context(conn, first_cid, window=1)
            self.assertGreaterEqual(len(ctx), 1)
        finally:
            conn.close()

    def test_sqlite_db_auto_ingestion(self) -> None:
        # Simulate a user's existing chat .db file
        ext_db = self.raw_dir / "legacy_chats.db"
        ext_conn = sqlite3.connect(str(ext_db))
        ext_conn.execute(
            "CREATE TABLE messages (id INTEGER PRIMARY KEY, conversation_id TEXT, role TEXT, content TEXT)"
        )
        ext_conn.execute(
            "INSERT INTO messages VALUES (1, 'conv_42', 'user', "
            "'Why does phase velocity slow down in water if photons travel at c?')"
        )
        ext_conn.commit()
        ext_conn.close()

        stats = ingest_path(self.raw_dir, self.db_path)
        self.assertEqual(stats["files_seen"], 3)
        conn = get_connection(self.db_path)
        try:
            row = conn.execute(
                "SELECT source_type, source_ref, author FROM chunks WHERE source_type = 'chat_db'"
            ).fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row["author"], "user")
            self.assertIn("conv_42", row["source_ref"])
        finally:
            conn.close()

    def test_gemini_archive_schema_adapter_and_noise_filter(self) -> None:
        arch_db = self.tmp_dir / "archive.db"
        aconn = sqlite3.connect(str(arch_db))
        aconn.execute("CREATE TABLE conversations (chat_id TEXT PRIMARY KEY, title TEXT)")
        aconn.execute(
            "CREATE TABLE turns (id INTEGER PRIMARY KEY, chat_id TEXT, turn_index INTEGER, "
            "user_prompt TEXT, model_response TEXT, timestamp_hint TEXT)"
        )
        aconn.execute(
            "CREATE TABLE cas_fts (sha256 TEXT, sample_path TEXT, ext TEXT, content_text TEXT)"
        )
        aconn.execute(
            "CREATE TABLE concept_bridges (term TEXT, alias TEXT, created_at TEXT)"
        )
        aconn.execute("INSERT INTO conversations VALUES ('c_phys', 'Quantum Particle Bar Visit')")
        aconn.execute("INSERT INTO conversations VALUES ('c_pasta', 'One-Pot Pesto Pasta with Veggies')")
        aconn.execute(
            "INSERT INTO turns VALUES (1, 'c_phys', 0, "
            "'Does quantum superposition conserve probability amplitude?', "
            "'Yes, unitary evolution preserves norm and thermodynamic entropy bounds.', '2026-11-01')"
        )
        aconn.execute(
            "INSERT INTO turns VALUES (2, 'c_pasta', 0, "
            "'Simmer pesto pasta until thermodynamic equilibrium of the pot.', 'Enjoy dinner!', '2026-11-01')"
        )
        aconn.execute(
            "INSERT INTO cas_fts VALUES ('abc', 'notes/refraction_note.md', '.md', "
            "'Phase superposition reduces effective phase velocity in water.')"
        )
        aconn.execute(
            "INSERT INTO concept_bridges VALUES ('reference', 'impedance', '2026-11-15')"
        )
        aconn.commit()
        aconn.close()

        stats = ingest_path(arch_db, self.db_path)
        self.assertGreaterEqual(stats["chunks_inserted"], 4)
        self.assertEqual(stats["bridges_imported"], 1)

        tagged = build_slice(self.db_path, slice_name="physics_pilot", limit=50)
        self.assertGreaterEqual(tagged, 2)

        conn = get_connection(self.db_path)
        try:
            slice_refs = [
                r["source_ref"]
                for r in conn.execute(
                    "SELECT c.source_ref FROM chapter_slices cs JOIN chunks c ON c.chunk_id = cs.chunk_id"
                ).fetchall()
            ]
            self.assertTrue(any("Quantum Particle Bar Visit" in s for s in slice_refs))
            self.assertFalse(any("Pesto Pasta" in s for s in slice_refs))
            bridge = conn.execute(
                "SELECT * FROM concept_bridges WHERE term = 'reference' AND alias = 'impedance'"
            ).fetchone()
            self.assertIsNotNone(bridge)
        finally:
            conn.close()

    def test_epistemic_locks_physics_check_and_halting_budget(self) -> None:
        ingest_path(self.raw_dir, self.db_path)
        conn = get_connection(self.db_path)
        try:
            cids = [r["chunk_id"] for r in conn.execute("SELECT chunk_id FROM chunks LIMIT 2").fetchall()]
            n1 = create_node_with_provenance(
                conn,
                domain="physics",
                summary="Photons bounce like pinballs inside water.",
                chunk_ids=[cids[0]],
                dsl_expr="model(scattering=random_pinball, path_length=increased)",
            )
            n2 = create_node_with_provenance(
                conn,
                domain="physics",
                summary="Macroscopic phase velocity v = c/n arises from phase superposition; underlying interactions propagate at c.",
                chunk_ids=[cids[1]],
                dsl_expr="invariant(c_micro) & macroscopic(v_phase = c / n)",
                epistemic_tier="DSL_CONSISTENT",
            )

            # 1. Tier promotion lock: llm_only cannot promote to EXTERNALLY_VERIFIED
            with self.assertRaises(ValueError):
                verify_and_link(
                    conn,
                    from_node_id=n2,
                    to_node_id=n1,
                    relation_type="supports",
                    verifier_type="llm_only",
                    external_ref="",
                    promote_node_id=n2,
                    new_tier="EXTERNALLY_VERIFIED",
                )

            # 1b. Self-loop lock: verify_and_link and SQLite CHECK forbid from_node == to_node
            with self.assertRaises(ValueError):
                verify_and_link(
                    conn,
                    from_node_id=n2,
                    to_node_id=n2,
                    relation_type="supports",
                    verifier_type="python_sim",
                    verification_scope="standard_physics_law",
                    external_ref="pycheck:deadbeef",
                    benchmark_ref="Refraction",
                )
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute(
                    "INSERT INTO edges (from_node, to_node, relation_type, verifier_type) VALUES (?, ?, 'supports', 'llm_only')",
                    (n2, n2),
                )

            # 2. Toy-script lock: toy_model cannot earn EXTERNALLY_VERIFIED (only SIM_CONSISTENT)
            toy = run_physics_check("mousetrap_cascade = (1, 0)\nassert mousetrap_cascade[0] == 1\n")
            self.assertTrue(toy["passed"])
            with self.assertRaises(ValueError):
                verify_node(
                    conn,
                    node_id=n2,
                    verifier_type="python_sim",
                    verification_scope="toy_model",
                    external_ref=toy["external_ref"],
                    benchmark_ref="",
                    new_tier="EXTERNALLY_VERIFIED",
                )
            sim_res = verify_node(
                conn,
                node_id=n2,
                verifier_type="python_sim",
                verification_scope="toy_model",
                external_ref=toy["external_ref"],
                notes="Toy model reaches SIM_CONSISTENT only",
                new_tier="SIM_CONSISTENT",
            )
            self.assertEqual(sim_res["new_tier"], "SIM_CONSISTENT")

            # 3. Execute real physical law check (standard_physics_law + benchmark_ref)
            check = run_physics_check(
                "c = 299792458.0\n"
                "n_water = 1.333\n"
                "v_phase = c / n_water\n"
                "assert 0.74 * c < v_phase < 0.76 * c\n"
                "print(f'v_phase={v_phase:.2f} m/s, ratio={v_phase/c:.4f}')\n"
            )
            self.assertTrue(check["passed"], check["stderr"])
            self.assertTrue(str(check["external_ref"]).startswith("pycheck:"))

            # Promote n2 with single-node verify_node (no self-loop) and mark n1 FALSIFIED via resolved_mistake
            b_pivot = int(
                conn.execute(
                    "INSERT INTO research_branches (root_node_id, agent_role, max_dry_hops) VALUES (?, 'falsifier', 3)",
                    (n1,),
                ).lastrowid
            )
            conn.commit()
            res_mistake = verify_and_link(
                conn,
                from_node_id=n1,
                to_node_id=n2,
                relation_type="resolved_mistake",
                verifier_type="python_sim",
                verification_scope="standard_physics_law",
                external_ref=check["external_ref"],
                benchmark_ref="Optics: Snell/Ewald-Oseen phase velocity v = c/n in water (n=1.333)",
                branch_id=b_pivot,
                promote_node_id=n1,
                new_tier="FALSIFIED",
                notes="Pinball scattering would blur images; phase superposition preserves coherence.",
            )
            self.assertEqual(res_mistake["branch"]["status"], "ACTIVE")

            verify_node(
                conn,
                node_id=n2,
                verifier_type="python_sim",
                verification_scope="standard_physics_law",
                external_ref=check["external_ref"],
                benchmark_ref="Optics: Snell/Ewald-Oseen phase velocity v = c/n in water (n=1.333)",
                new_tier="EXTERNALLY_VERIFIED",
            )
            res_piv = verify_and_link(
                conn,
                from_node_id=n1,
                to_node_id=n2,
                relation_type="pivoted_to",
                verifier_type="python_sim",
                verification_scope="standard_physics_law",
                external_ref=check["external_ref"],
                benchmark_ref="Optics: Snell/Ewald-Oseen phase velocity v = c/n in water (n=1.333)",
                branch_id=b_pivot,
            )
            self.assertEqual(res_piv["branch"]["status"], "CONVERGED")

            # Also verify reconcile_converged_branches keeps SIM_CONSISTENT ACTIVE and converges EXTERNALLY_VERIFIED
            b_sim = int(
                conn.execute(
                    "INSERT INTO research_branches (root_node_id, agent_role, max_dry_hops) VALUES (?, 'scientist', 3)",
                    (n2,),
                ).lastrowid
            )
            conn.execute("UPDATE nodes SET epistemic_tier = 'SIM_CONSISTENT' WHERE node_id = ?", (n2,))
            conn.commit()
            rec1 = reconcile_converged_branches(conn)
            self.assertIn(b_sim, rec1["still_active_branch_ids"])
            conn.execute("UPDATE nodes SET epistemic_tier = 'EXTERNALLY_VERIFIED' WHERE node_id = ?", (n2,))
            conn.commit()
            rec2 = reconcile_converged_branches(conn)
            self.assertIn(b_sim, rec2["converged_branch_ids"])

            tiers = dict(conn.execute("SELECT node_id, epistemic_tier FROM nodes").fetchall())
            self.assertEqual(tiers[n1], "FALSIFIED")
            self.assertEqual(tiers[n2], "EXTERNALLY_VERIFIED")

            # 3b. Canonical deduplication: attach_node_provenance consolidates chunks onto existing node_id
            dedup_res = attach_node_provenance(
                conn,
                node_id=n2,
                chunk_ids=[cids[0], cids[1]],
                quote_spans=["duplicate mention of v = c/n", "original v = c/n span"],
            )
            self.assertEqual(dedup_res["node_id"], n2)
            self.assertEqual(dedup_res["chunks_attached"], 1)
            self.assertEqual(dedup_res["total_provenance_chunks"], 2)
            self.assertEqual(
                detect_noise_skip_reason("chat:debug", "Traceback (most recent call last):\nSyntaxError: invalid syntax"),
                "debug_churn",
            )

            # 3c. Thematic outline keeps FALSIFIED -> pivoted_to target in the same thematic section
            outline = build_thematic_outline(conn, domain="physics")
            self.assertEqual(outline["total_nodes"], 2)
            self.assertEqual(outline["total_edges"], 2)
            self.assertTrue(
                any(
                    {n["node_id"] for n in t["nodes"]} == {n1, n2}
                    for t in outline["themes"]
                )
            )

            # 4. Halting budget: 3 dry hops (including toy_model!) must flip status to HALTED_NOVELTY and block hop 4
            cur = conn.execute(
                "INSERT INTO research_branches (root_node_id, agent_role, max_dry_hops) VALUES (?, 'scientist', 3)",
                (n2,),
            )
            branch_id = int(cur.lastrowid)
            conn.commit()

            for hop in range(1, 4):
                res = verify_and_link(
                    conn,
                    from_node_id=n2,
                    to_node_id=n1,
                    relation_type="refines",
                    verifier_type="python_sim" if hop == 2 else "llm_only",
                    verification_scope="toy_model" if hop == 2 else "llm_only",
                    external_ref=toy["external_ref"] if hop == 2 else None,
                    branch_id=branch_id,
                )
                expected_status = "HALTED_NOVELTY" if hop == 3 else "ACTIVE"
                self.assertEqual(res["branch"]["status"], expected_status)
                self.assertFalse(res["branch"]["novelty_gained"])

            with self.assertRaises(ValueError):
                verify_and_link(
                    conn,
                    from_node_id=n2,
                    to_node_id=n1,
                    relation_type="refines",
                    verifier_type="llm_only",
                    branch_id=branch_id,
                )
        finally:
            conn.close()

    def test_mcp_stdio_roundtrip(self) -> None:
        ingest_path(self.raw_dir, self.db_path)
        build_slice(self.db_path, slice_name="physics_pilot", limit=100)

        requests = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2024-11-05"}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "get_pilot_status", "arguments": {"slice_name": "physics_pilot"}},
            },
            {
                "jsonrpc": "2.0",
                "id": 4,
                "method": "tools/call",
                "params": {"name": "search_corpus_global", "arguments": {"query": "refraction"}},
            },
        ]
        stdin_payload = "\n".join(json.dumps(r) for r in requests) + "\n"
        env = {"CORPUS_DB_PATH": str(self.db_path), "PATH": "/usr/bin:/bin"}
        proc = subprocess.run(
            [sys.executable, str(MCP_SERVER)],
            input=stdin_payload,
            capture_output=True,
            text=True,
            env=env,
            timeout=15,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        responses = [json.loads(line) for line in proc.stdout.strip().splitlines() if line.strip()]
        self.assertEqual(len(responses), 4)
        self.assertEqual(responses[0]["id"], 1)
        tool_names = {t["name"] for t in responses[1]["result"]["tools"]}
        self.assertIn("search_corpus_global", tool_names)
        self.assertIn("run_physics_check", tool_names)
        self.assertIn("verify_node", tool_names)
        self.assertIn("verify_and_link", tool_names)
        self.assertIn("get_thematic_outline", tool_names)

        status_payload = json.loads(responses[2]["result"]["content"][0]["text"])
        self.assertGreaterEqual(status_payload["total_chunks"], 4)
        self.assertGreaterEqual(status_payload["slice"]["counts"].get("PENDING", 0), 2)
        self.assertIn("digest_state_sections", status_payload)
        self.assertIn("hydrate_tick_context", tool_names)
        self.assertIn("sync_digest_deltas", tool_names)

    def test_digest_delta_compilation_and_ouroboros_watermark(self) -> None:
        from compile_digest import compile_digest, hydrate_pre_tick, sync_ouroboros_deltas
        from single_loop_runner import LIFTER_STATIC_PREFIX, apply_falsifier_output, apply_lifter_output, build_lifter_prompt

        # Create isolated archive.db with rich turn topology + Ouroboros ledger
        arch_db = self.tmp_dir / "archive.db"
        aconn = sqlite3.connect(str(arch_db))
        aconn.execute("CREATE TABLE conversations (chat_id TEXT PRIMARY KEY, title TEXT, url TEXT, total_turns INTEGER DEFAULT 0)")
        aconn.execute(
            "CREATE TABLE turns (id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id TEXT NOT NULL, turn_index INTEGER NOT NULL, "
            "turn_id TEXT, parent_turn_id TEXT, next_turn_id TEXT, user_prompt TEXT, model_response TEXT, "
            "model_thoughts TEXT, timestamp_hint TEXT, sha256 TEXT)"
        )
        aconn.execute("CREATE VIRTUAL TABLE turns_fts USING fts5(chat_id, title, user_prompt, model_response)")
        aconn.execute("CREATE TABLE cas_fts (sha256 TEXT, sample_path TEXT, ext TEXT, content_text TEXT)")
        aconn.execute("CREATE TABLE concept_bridges (term TEXT, alias TEXT, created_at TEXT)")
        aconn.execute("INSERT INTO conversations VALUES ('c_arch', 'Legacy Mousetrap Architecture', 'local://1', 2)")
        aconn.execute("INSERT INTO conversations VALUES ('levi_recursive_memory', 'Levi Autonomous Epistemic Ledger', 'local://2', 1)")
        aconn.execute(
            "INSERT INTO turns (id, chat_id, turn_index, turn_id, parent_turn_id, next_turn_id, user_prompt, model_response, timestamp_hint, sha256) "
            "VALUES (10, 'c_arch', 1, 'turn_root_1', '', 'turn_child_2', 'How does the outer coordinator remember?', "
            "'An external SQLite ledger keeps state across resets.', '2026-10-01', 'sha_root_001')"
        )
        aconn.execute(
            "INSERT INTO turns (id, chat_id, turn_index, turn_id, parent_turn_id, next_turn_id, user_prompt, model_response, timestamp_hint, sha256) "
            "VALUES (11, 'c_arch', 2, 'turn_child_2', 'turn_root_1', '', 'Explain thermostat and mousetrap weights.', "
            "'A mousetrap fires in one stateless pass while thermostat feedback regulates loop error.', '2026-10-02', 'sha_child_002')"
        )
        aconn.execute(
            "INSERT INTO turns (id, chat_id, turn_index, turn_id, parent_turn_id, next_turn_id, user_prompt, model_response, timestamp_hint, sha256) "
            "VALUES (20, 'levi_recursive_memory', 1, 'lrm_1', '', '', 'Synthesize thermostat feedback.', "
            "'Thermostat negative feedback suppresses oscillatory overshoot.', '2026-11-18', 'sha_lrm_001')"
        )
        aconn.execute(
            "INSERT INTO turns_fts(rowid, chat_id, title, user_prompt, model_response) VALUES "
            "(10, 'c_arch', 'Initial Thread', 'How does the outer coordinator remember?', 'An external SQLite ledger keeps state across resets.')"
        )
        aconn.execute(
            "INSERT INTO turns_fts(rowid, chat_id, title, user_prompt, model_response) VALUES "
            "(11, 'c_arch', 'Legacy Mousetrap Architecture', 'Explain thermostat and mousetrap weights.', 'A mousetrap fires in one stateless pass while thermostat feedback regulates loop error.')"
        )
        aconn.execute(
            "INSERT INTO turns_fts(rowid, chat_id, title, user_prompt, model_response) VALUES "
            "(20, 'levi_recursive_memory', 'Levi Autonomous Epistemic Ledger', 'Synthesize thermostat feedback.', 'Thermostat negative feedback suppresses oscillatory overshoot.')"
        )
        aconn.commit()
        aconn.close()

        ingest_path(self.raw_dir, self.db_path)
        build_slice(self.db_path, slice_name="physics_pilot", limit=50)
        core_path = self.tmp_dir / "core_digest.md"
        slices_dir = self.tmp_dir / "digest_slices"

        conn = get_connection(self.db_path)
        try:
            cids = [r["chunk_id"] for r in conn.execute("SELECT chunk_id FROM chunks ORDER BY chunk_id LIMIT 4").fetchall()]
            n_phys = create_node_with_provenance(
                conn,
                domain="physics",
                summary="Minkowski light-cone causality requires invariant speed c across Lorentz frames.",
                chunk_ids=[cids[0]],
                epistemic_tier="RAW_CLAIM",
            )
            n_cyb = create_node_with_provenance(
                conn,
                domain="ai_systems",
                summary="Thermostat negative feedback stabilizes loop setpoint against thermal disturbance.",
                chunk_ids=[cids[1]],
                epistemic_tier="RAW_CLAIM",
            )
            b_cyb = int(
                conn.execute(
                    "INSERT INTO research_branches (root_node_id, agent_role, max_dry_hops) VALUES (?, 'scientist', 3)",
                    (n_cyb,),
                ).lastrowid
            )
            conn.commit()

            # Initial full compile
            comp1 = compile_digest(conn, archive_db=arch_db, core_path=core_path, slices_dir=slices_dir, force_all=True)
            self.assertTrue(core_path.exists())
            self.assertTrue(comp1["core_refreshed"])
            self.assertIn("SPACETIME_CAUSALITY_ELECTRODYNAMICS", comp1["recompiled_sections"])
            self.assertIn("CYBERNETICS_ACTIVE_INFERENCE", comp1["recompiled_sections"])

            # Second delta run with zero changes must recompile 0 slices
            comp2 = compile_digest(conn, archive_db=arch_db, core_path=core_path, slices_dir=slices_dir)
            self.assertEqual(comp2["recompiled_sections"], [])
            self.assertFalse(comp2["core_refreshed"])
            phys_sha_before = conn.execute(
                "SELECT section_sha256 FROM digest_state WHERE section_key = 'SPACETIME_CAUSALITY_ELECTRODYNAMICS'"
            ).fetchone()[0]

            # Falsifier commit on ONLY n_cyb (CYBERNETICS_ACTIVE_INFERENCE) must NOT recompile SPACETIME_CAUSALITY_ELECTRODYNAMICS
            chk = run_physics_check("kp = 0.5\nerr = 1.0 - 0.8\nassert kp * err > 0\nprint('pid stable')\n")
            cands = [{"node_id": n_cyb, "branch_id": b_cyb, "pycheck": chk}]
            fal_out = {
                "decisions": [
                    {
                        "node_id": n_cyb,
                        "verdict": "EXTERNALLY_VERIFIED",
                        "verifier_type": "python_sim",
                        "verification_scope": "standard_physics_law",
                        "benchmark_ref": "Wiener (1948) Cybernetics negative feedback control stability",
                        "notes": "Verified control loop stability",
                        "support_targets": [],
                    }
                ]
            }
            res_c = apply_falsifier_output(
                conn,
                "ai_systems",
                cands,
                fal_out,
                db_path=self.db_path,
                archive_db=arch_db,
                trigger_digest=True,
            )
            self.assertEqual(res_c["digest_delta"]["recompiled_sections"], ["CYBERNETICS_ACTIVE_INFERENCE"])
            self.assertTrue(res_c["digest_delta"]["core_refreshed"])
            phys_sha_after = conn.execute(
                "SELECT section_sha256 FROM digest_state WHERE section_key = 'SPACETIME_CAUSALITY_ELECTRODYNAMICS'"
            ).fetchone()[0]
            self.assertEqual(phys_sha_before, phys_sha_after)

            # Append new Ouroboros turn in archive.db for Scattering Geometry and verify Stage 3 sync picks up ONLY that turn/slice
            aconn = sqlite3.connect(str(arch_db))
            aconn.execute(
                "INSERT INTO turns (id, chat_id, turn_index, turn_id, parent_turn_id, next_turn_id, user_prompt, model_response, timestamp_hint, sha256) "
                "VALUES (21, 'levi_recursive_memory', 2, 'lrm_2', 'lrm_1', '', 'Evaluate amplituhedron positive grassmannian', "
                "'Amplituhedron polytope geometry matches Veneziano S-matrix bootstrap channels.', '2026-11-18', 'sha_lrm_002')"
            )
            aconn.execute(
                "INSERT INTO turns_fts(rowid, chat_id, title, user_prompt, model_response) VALUES "
                "(21, 'levi_recursive_memory', 'Levi Autonomous Epistemic Ledger', 'Evaluate amplituhedron positive grassmannian', "
                "'Amplituhedron polytope geometry matches Veneziano S-matrix bootstrap channels.')"
            )
            aconn.commit()
            aconn.close()

            ouro_res = sync_ouroboros_deltas(conn, archive_db=arch_db, core_path=core_path, slices_dir=slices_dir)
            self.assertEqual(ouro_res["status"], "recompiled")
            self.assertEqual(ouro_res["new_turns"], 1)
            self.assertIn("SCATTERING_GEOMETRY_BOOTSTRAP", ouro_res["recompiled_sections"])
            wm = conn.execute(
                "SELECT last_compiled_turn_id FROM digest_state WHERE section_key = 'OUROBOROS_LEDGER'"
            ).fetchone()[0]
            self.assertEqual(wm, 21)

            # Stage 2 & Stage 4 test: vocabulary expansion ("stateless forward pass" -> "mousetrap") pulls legacy archive.db turn with DAG parent_turn_id + tier gate suppresses FALSIFIED
            bad_cid = int(
                conn.execute(
                    "INSERT INTO chunks (source_type, source_ref, author, sha256, content) VALUES ('chat_db', 'archive:bad:turn:1', 'user', 'badsha123', 'Absorption delay dt mousetrap pinball slows photons.')",
                ).lastrowid
            )
            conn.execute("INSERT INTO chunks_fts(rowid, content) VALUES (?, ?)", (bad_cid, "Absorption delay dt mousetrap pinball slows photons."))
            n_bad = create_node_with_provenance(
                conn,
                domain="physics",
                summary="Photons pause inside atoms during refraction absorption delay.",
                chunk_ids=[bad_cid],
                epistemic_tier="RAW_CLAIM",
            )
            n_good = create_node_with_provenance(
                conn,
                domain="physics",
                summary="Coherent dipole phase superposition yields v = c/n without photon capture.",
                chunk_ids=[cids[0]],
                epistemic_tier="DSL_CONSISTENT",
            )
            verify_node(
                conn,
                node_id=n_good,
                verifier_type="python_sim",
                verification_scope="standard_physics_law",
                external_ref=chk["external_ref"],
                benchmark_ref="Ewald-Oseen extinction theorem",
                new_tier="EXTERNALLY_VERIFIED",
            )
            verify_and_link(
                conn,
                from_node_id=n_bad,
                to_node_id=n_good,
                relation_type="resolved_mistake",
                verifier_type="python_sim",
                verification_scope="standard_physics_law",
                external_ref=chk["external_ref"],
                benchmark_ref="Ewald-Oseen",
                promote_node_id=n_bad,
                new_tier="FALSIFIED",
            )
            verify_and_link(
                conn,
                from_node_id=n_bad,
                to_node_id=n_good,
                relation_type="pivoted_to",
                verifier_type="python_sim",
                verification_scope="standard_physics_law",
                external_ref=chk["external_ref"],
                benchmark_ref="Ewald-Oseen",
            )
            conn.commit()

            hyd = hydrate_pre_tick(
                conn,
                domain="physics",
                query_text="stateless forward pass absorption delay photon",
                archive_db=arch_db,
                core_path=core_path,
                slices_dir=slices_dir,
                token_budget=1800,
                sync_deltas_first=False,
            )
            pkt = hyd["packet"]
            self.assertLessEqual(pkt["estimated_tokens"], 1800)
            self.assertEqual(hyd["archive_db_status"], "connected")
            # Concept bridge expanded "stateless forward pass" -> "mousetrap" -> pulled archive turn_id='turn_child_2'
            self.assertTrue(any(b["alias"] == "mousetrap" or b["term"] == "mousetrap" for b in pkt["bridges_used"]))
            slice_turn_ids = {s.get("turn_id") for s in pkt["dynamic_slices"]}
            self.assertIn("turn_child_2", slice_turn_ids)
            # Parent DAG backtracking pulled turn_root_1
            self.assertTrue(any(p.get("turn_id") == "turn_root_1" for p in pkt["parent_dag_backtrack"]))
            # FALSIFIED chunk suppressed from positive slices and included in falsified_constraints
            pos_cids = {s.get("chunk_id") for s in pkt["dynamic_slices"]}
            self.assertNotIn(bad_cid, pos_cids)
            self.assertTrue(any(fc["falsified_node_id"] == n_bad and fc["pivoted_to_node_id"] == n_good for fc in pkt["falsified_constraints"]))

            # Prompt-cache invariant: LIFTER_STATIC_PREFIX stays byte-identical at start of prompt
            prompt = build_lifter_prompt(conn, "physics", [{"chunk_id": cids[0], "source_ref": "x", "content": "hello"}], hydrated=hyd, core_mode="anchor")
            self.assertTrue(prompt.startswith(LIFTER_STATIC_PREFIX))
            self.assertIn("HYDRATED WORKING-MEMORY PACKET", prompt)
            self.assertIn("# KEYWORD:", prompt)

            # Verify apply_lifter_output -> concept_bridges insertion immediately expands subsequent Stage 2 queries
            apply_lifter_output(
                conn,
                "physics_pilot",
                "physics",
                [cids[0]],
                {
                    "skipped": [{"chunk_id": cids[0], "skip_reason": "boilerplate", "reason": "test"}],
                    "attach_provenance": [],
                    "new_nodes": [],
                    "concept_bridges": [
                        {"term": "outer coordinator", "alias": "thermostat", "structural_pattern": "feedback_controller"}
                    ],
                },
            )
            hyd2 = hydrate_pre_tick(
                conn,
                domain="physics",
                query_text="thermostat control",
                archive_db=arch_db,
                core_path=core_path,
                slices_dir=slices_dir,
                sync_deltas_first=False,
            )
            self.assertTrue(
                any(
                    b["term"] == "thermostat" or b["alias"] == "thermostat"
                    for b in hyd2["packet"]["bridges_used"]
                )
            )
        finally:
            conn.close()

    def test_ingest_artifact_query_hygiene_and_brain_shell(self) -> None:
        from arachne_bridge import filter_query_text
        from compile_digest import compile_digest, hydrate_pre_tick, resolve_digest_targets
        from ingest_session import ingest_artifact

        # 1. Seed isolated corpus + mock archive.db under self.tmp_dir (never touches data/corpus.db)
        ingest_path(self.raw_dir, self.db_path)
        build_slice(self.db_path, slice_name="physics_pilot", limit=100)
        core_path, slices_dir = resolve_digest_targets(self.db_path)

        arch_db = self.tmp_dir / "mock_archive.db"
        aconn = sqlite3.connect(str(arch_db))
        aconn.execute("CREATE TABLE conversations (chat_id TEXT PRIMARY KEY, title TEXT)")
        aconn.execute(
            "CREATE TABLE turns (id INTEGER PRIMARY KEY, chat_id TEXT, turn_index INTEGER, "
            "turn_id TEXT, parent_turn_id TEXT, next_turn_id TEXT, user_prompt TEXT, "
            "model_response TEXT, timestamp_hint TEXT, sha256 TEXT)"
        )
        aconn.execute(
            "CREATE VIRTUAL TABLE turns_fts USING fts5(chat_id, title, user_prompt, model_response)"
        )
        aconn.execute("INSERT INTO conversations VALUES ('c_refract', 'Wave Interference Notes')")
        aconn.execute(
            "INSERT INTO turns VALUES (10, 'c_refract', 0, 'turn_arch_10', 'turn_arch_9', '', "
            "'Explain phase superposition and Ewald-Oseen wave interference in refractive media', "
            "'Coherent dipole scattering shifts aggregate phase velocity c/n.', '2026-11-18', 'sha_arch_010')"
        )
        aconn.execute(
            "INSERT INTO turns_fts(rowid, chat_id, title, user_prompt, model_response) VALUES "
            "(10, 'c_refract', 'Wave Interference Notes', "
            "'Explain phase superposition and Ewald-Oseen wave interference in refractive media', "
            "'Coherent dipole scattering shifts aggregate phase velocity c/n.')"
        )
        aconn.commit()
        aconn.close()

        conn = get_connection(self.db_path)
        try:
            cids = [r[0] for r in conn.execute("SELECT chunk_id FROM chunks ORDER BY chunk_id").fetchall()]
            n_good = create_node_with_provenance(
                conn,
                domain="physics",
                summary="Coherent dipole phase superposition governs optical refraction index n.",
                chunk_ids=[cids[0]],
                epistemic_tier="DSL_CONSISTENT",
            )
            chk = run_physics_check("n_water = 1.333\nassert n_water > 1.0\nprint('refraction_ok')\n")
            verify_node(
                conn,
                node_id=n_good,
                verifier_type="python_sim",
                verification_scope="standard_physics_law",
                external_ref=chk["external_ref"],
                benchmark_ref="Ewald-Oseen extinction theorem",
                new_tier="EXTERNALLY_VERIFIED",
            )
            n_bad = create_node_with_provenance(
                conn,
                domain="physics",
                summary="Photons stop and sleep inside glass molecules during absorption delay.",
                chunk_ids=[cids[1]],
                epistemic_tier="RAW_CLAIM",
            )
            verify_and_link(
                conn,
                from_node_id=n_bad,
                to_node_id=n_good,
                relation_type="pivoted_to",
                verifier_type="python_sim",
                verification_scope="standard_physics_law",
                external_ref=chk["external_ref"],
                benchmark_ref="Ewald-Oseen",
                promote_node_id=n_bad,
                new_tier="FALSIFIED",
            )
            conn.commit()
            compile_digest(conn, archive_db=arch_db, core_path=core_path, slices_dir=slices_dir, force_all=True)

            # 2. Query hygiene stopword / boilerplate filtering (Part 2)
            dirty = "cas:audits/20261026/recovered_dataset/conversations/conversation.md his you system turn html json md vagal baroreflex attenuation"
            cleaned = filter_query_text(dirty)
            for noisy_tok in ("cas", "conversation", "his", "you", "system", "turn", "html", "json", "md"):
                self.assertNotIn(noisy_tok, cleaned.lower().split())
            self.assertIn("vagal", cleaned.lower())
            self.assertIn("baroreflex", cleaned.lower())

            hyd_clean = hydrate_pre_tick(
                conn,
                domain="physics",
                chunks=[
                    {
                        "chunk_id": cids[0],
                        "source_ref": "cas:audits/20261026/recovered_dataset/conversations/1a13/conversation.md",
                        "content": "His turn in json and html format: phase superposition in refractive optical media system.",
                    }
                ],
                query_text="cas conversation his you system turn html json md refraction",
                archive_db=arch_db,
                core_path=core_path,
                slices_dir=slices_dir,
                sync_deltas_first=False,
            )
            fq_tokens = hyd_clean["focused_query"].lower().split()
            for noisy_tok in ("cas", "conversation", "his", "you", "system", "turn", "html", "json", "md"):
                self.assertNotIn(noisy_tok, fq_tokens)
            self.assertIn("refraction", fq_tokens)
        finally:
            conn.close()

        # 3. Part 1: ingest_artifact HTML stripping (no style/script/base64) + sha256 idempotency + RAW_CLAIM lock
        html_doc = self.tmp_dir / "session_briefing.html"
        html_doc.write_text(
            "<html><head><style>.cls{color:red;background:url(data:image/png;base64,iVBORw0KGgoAAAANS)}</style>"
            "<script>var secret_js_token = 'should_not_appear';</script></head>"
            "<body><h1>Vagal Autonomic Regulation Log</h1>"
            "<p>HPA axis baroreflex feedback attenuates sympathetic arousal cleanly.</p>"
            "<img src=\"data:image/png;base64,AAAAABBBBBCCCCC1234567890\" alt=\"chart\"/>"
            "<p>Inline leak check: data:image/jpeg;base64,/9j/4AAQSkZJRgABAQEASABIAAD and more text.</p>"
            "</body></html>",
            encoding="utf-8",
        )
        pre_nodes = sqlite3.connect(self.db_path).execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
        pre_verif = sqlite3.connect(self.db_path).execute(
            "SELECT COUNT(*) FROM nodes WHERE epistemic_tier='EXTERNALLY_VERIFIED'"
        ).fetchone()[0]

        res1 = ingest_artifact(
            db_path=self.db_path,
            source_path=html_doc,
            source_tag="PROVENANCE_LOG",
            chat_id="codex_session_01",
            sync_digest=True,
            archive_db=arch_db,
        )
        self.assertEqual(res1["status"], "ingested")
        self.assertEqual(res1["epistemic_tier"], "RAW_CLAIM")
        self.assertEqual(res1["nodes_auto_promoted"], 0)
        self.assertGreaterEqual(res1["chunks_inserted"], 1)

        # Confirm HTML style/script/base64 did NOT pollute chunks or chunks_fts, while body text DID
        rconn = sqlite3.connect(self.db_path)
        try:
            post_nodes = rconn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
            post_verif = rconn.execute(
                "SELECT COUNT(*) FROM nodes WHERE epistemic_tier='EXTERNALLY_VERIFIED'"
            ).fetchone()[0]
            self.assertEqual(pre_nodes, post_nodes)
            self.assertEqual(pre_verif, post_verif)

            ing_row = rconn.execute(
                "SELECT epistemic_tier, source_tag, chat_id FROM ingested_artifacts WHERE file_sha256 = ?",
                (res1["sha256"],),
            ).fetchone()
            self.assertEqual(ing_row[0], "RAW_CLAIM")
            self.assertEqual(ing_row[1], "PROVENANCE_LOG")
            self.assertEqual(ing_row[2], "codex_session_01")

            cid = res1["chunk_ids"][0]
            txt = rconn.execute("SELECT content, source_ref FROM chunks WHERE chunk_id = ?", (cid,)).fetchone()
            self.assertIn("baroreflex feedback", txt[0])
            self.assertNotIn("secret_js_token", txt[0])
            self.assertNotIn("color:red", txt[0])
            self.assertNotIn("base64,", txt[0])
            self.assertIn("tier=RAW_CLAIM", txt[1])
            self.assertIn("archive:codex_session_01:turn:0", txt[1])

            fts_hit = rconn.execute(
                "SELECT rowid FROM chunks_fts WHERE chunks_fts MATCH 'baroreflex'"
            ).fetchall()
            self.assertTrue(any(int(r[0]) == cid for r in fts_hit))
        finally:
            rconn.close()

        # Re-ingesting exact same artifact must be idempotent (0 new chunks / 0 duplicates)
        res2 = ingest_artifact(
            db_path=self.db_path,
            source_path=html_doc,
            source_tag="PROVENANCE_LOG",
            chat_id="codex_session_01",
            sync_digest=True,
            archive_db=arch_db,
        )
        self.assertEqual(res2["status"], "already_ingested")
        self.assertEqual(res2["chunks_inserted"], 0)

        # Also check .md and .json ingestion idempotency
        md_doc = self.tmp_dir / "notes_round.md"
        md_doc.write_text("# Session Notes\n\nConstructal branching minimizes viscous pumping dissipation.\n", encoding="utf-8")
        md1 = ingest_artifact(self.db_path, md_doc, source_tag="PROVENANCE_LOG", archive_db=arch_db)
        md2 = ingest_artifact(self.db_path, md_doc, source_tag="PROVENANCE_LOG", archive_db=arch_db)
        self.assertEqual(md1["status"], "ingested")
        self.assertEqual(md2["status"], "already_ingested")
        self.assertEqual(md2["chunks_inserted"], 0)

        json_doc = self.tmp_dir / "chat_export.json"
        json_doc.write_text(
            json.dumps(
                {
                    "messages": [
                        {"role": "user", "timestamp": "2026-11-18T10:00:00Z", "content": "Compare Murray cubic law and network conductance scaling."},
                        {"role": "assistant", "timestamp": "2026-11-18T10:00:05Z", "content": "Murray r0^3 = r1^3 + r2^3 minimizes laminar pumping plus metabolic volume cost."},
                    ]
                }
            ),
            encoding="utf-8",
        )
        js1 = ingest_artifact(self.db_path, json_doc, source_tag="SESSION_EXPORT", chat_id="round_json_01", archive_db=arch_db)
        js2 = ingest_artifact(self.db_path, json_doc, source_tag="SESSION_EXPORT", chat_id="round_json_01", archive_db=arch_db)
        self.assertEqual(js1["status"], "ingested")
        self.assertEqual(js1["source_type"], "json")
        self.assertEqual(js1["epistemic_tier"], "RAW_CLAIM")
        self.assertEqual(js2["status"], "already_ingested")
        self.assertEqual(js2["chunks_inserted"], 0)

        # 4. Part 3: brain.py CLI --cmd tests (status, inspect, query --dry-run, ingest, tick --dry-run) on isolated DB
        brain_script = Path(__file__).resolve().parent / "brain.py"

        def run_brain(cmd_str: str) -> subprocess.CompletedProcess[str]:
            return subprocess.run(
                [
                    sys.executable,
                    str(brain_script),
                    "--db",
                    str(self.db_path),
                    "--archive-db",
                    str(arch_db),
                    "--core-digest",
                    str(core_path),
                    "--slices-dir",
                    str(slices_dir),
                    "--json",
                    "--cmd",
                    cmd_str,
                ],
                capture_output=True,
                text=True,
                check=True,
            )

        st_out = json.loads(run_brain("status").stdout)
        self.assertEqual(st_out["nodes_total"], 2)
        self.assertTrue(st_out["archive_db"]["available"])
        self.assertGreaterEqual(st_out["ingested_artifacts"], 3)

        insp_node = json.loads(run_brain(f"inspect node:{n_good}").stdout)
        self.assertEqual(insp_node["node"]["epistemic_tier"], "EXTERNALLY_VERIFIED")
        insp_piv = json.loads(run_brain("inspect pivots").stdout)
        self.assertTrue(any(p["falsified_node_id"] == n_bad and p["pivoted_to_node_id"] == n_good for p in insp_piv["chains"]))
        insp_turn = json.loads(run_brain("inspect turn:10").stdout)
        self.assertEqual(insp_turn["turn"]["turn_id"], "turn_arch_10")
        insp_kw = json.loads(run_brain("inspect SPACETIME_CAUSALITY_ELECTRODYNAMICS").stdout)
        self.assertEqual(insp_kw["target"], "section:SPACETIME_CAUSALITY_ELECTRODYNAMICS")

        q_out = json.loads(run_brain("query phase superposition refraction system json --dry-run").stdout)
        self.assertEqual(q_out["mode"], "dry-run")
        self.assertLessEqual(q_out["estimated_tokens"], 2200)
        self.assertNotIn("system", q_out["cleaned_query"].lower().split())
        self.assertNotIn("json", q_out["cleaned_query"].lower().split())
        self.assertIn(n_good, q_out["citations"]["verified_node_ids"])
        self.assertTrue(
            any(fc["falsified_node_id"] == n_bad and fc["pivoted_to_node_id"] == n_good for fc in q_out["citations"]["falsified_pivots"])
        )

        # CLI ingest via brain.py + verify second call skips cleanly
        txt_doc = self.tmp_dir / "levi_log.txt"
        txt_doc.write_text("Levi autonomous log noting noether symmetry invariants under spatial translation.\n", encoding="utf-8")
        ing1 = json.loads(run_brain(f"ingest {txt_doc} --tag LEVI_LOG").stdout)
        ing2 = json.loads(run_brain(f"ingest {txt_doc} --tag LEVI_LOG").stdout)
        self.assertEqual(ing1["status"], "ingested")
        self.assertEqual(ing1["epistemic_tier"], "RAW_CLAIM")
        self.assertEqual(ing2["status"], "already_ingested")
        self.assertEqual(ing2["chunks_inserted"], 0)

        # Bounded non-mutating tick --dry-run check
        tick_dry = json.loads(run_brain("tick physics --limit 1 --dry-run").stdout)
        self.assertEqual(tick_dry["status"], "dry_run_ok")
        self.assertLessEqual(tick_dry["packet_tokens"], 2200)

    def test_brain_mcp_and_sync_and_ingest_closed_loop(self) -> None:
        import fcntl
        from compile_digest import compile_digest, resolve_digest_targets
        from sync_and_ingest import run_closedloop

        # 1. Seed isolated corpus.db with one EXTERNALLY_VERIFIED invariant + one FALSIFIED -> pivoted_to pair
        ingest_path(self.raw_dir, self.db_path)
        init_db(self.db_path)
        core_path, slices_dir = resolve_digest_targets(self.db_path)

        arch_db = self.tmp_dir / "mock_spark_archive.db"
        aconn = sqlite3.connect(str(arch_db))
        aconn.execute("CREATE TABLE conversations (chat_id TEXT PRIMARY KEY, title TEXT)")
        aconn.execute(
            "CREATE TABLE turns (id INTEGER PRIMARY KEY, chat_id TEXT, turn_index INTEGER, "
            "turn_id TEXT, parent_turn_id TEXT, next_turn_id TEXT, user_prompt TEXT, "
            "user_html TEXT, model_response TEXT, model_html TEXT, timestamp_hint TEXT, sha256 TEXT)"
        )
        aconn.execute(
            "CREATE VIRTUAL TABLE turns_fts USING fts5(chat_id, title, user_prompt, model_response)"
        )
        aconn.execute("INSERT INTO conversations VALUES ('spark_chat_test', 'Levi Test Session')")
        aconn.execute(
            "INSERT INTO turns VALUES (10, 'spark_chat_test', 1, 'tid_spark_01', 'tid_spark_00', '', "
            "'Explain phase superposition in glass', NULL, "
            "'Coherent dipole scattering shifts phase velocity c/n.', NULL, '2026-11-18T08:00:00Z', 'sha_sp_01')"
        )
        aconn.execute(
            "INSERT INTO turns_fts(rowid, chat_id, title, user_prompt, model_response) VALUES "
            "(10, 'spark_chat_test', 'Levi Test Session', 'Explain phase superposition in glass', "
            "'Coherent dipole scattering shifts phase velocity c/n.')"
        )
        aconn.commit()
        aconn.close()

        conn = get_connection(self.db_path)
        try:
            cids = [r[0] for r in conn.execute("SELECT chunk_id FROM chunks ORDER BY chunk_id").fetchall()]
            n_good = create_node_with_provenance(
                conn,
                domain="physics",
                summary="Coherent dipole phase superposition governs optical refraction index n.",
                chunk_ids=[cids[0]],
                epistemic_tier="DSL_CONSISTENT",
            )
            chk = run_physics_check("n_water = 1.333\nassert n_water > 1.0\nprint('refraction_ok')\n")
            verify_node(
                conn,
                node_id=n_good,
                verifier_type="python_sim",
                verification_scope="standard_physics_law",
                external_ref=chk["external_ref"],
                benchmark_ref="Ewald-Oseen extinction theorem",
                new_tier="EXTERNALLY_VERIFIED",
            )
            n_bad = create_node_with_provenance(
                conn,
                domain="physics",
                summary="Photons stop and sleep inside glass atoms between absorption events.",
                chunk_ids=[cids[1]],
                epistemic_tier="RAW_CLAIM",
            )
            verify_and_link(
                conn,
                from_node_id=n_bad,
                to_node_id=n_good,
                relation_type="pivoted_to",
                verifier_type="python_sim",
                verification_scope="standard_physics_law",
                external_ref=chk["external_ref"],
                benchmark_ref="Ewald-Oseen",
                promote_node_id=n_bad,
                new_tier="FALSIFIED",
            )
            conn.commit()
            compile_digest(conn, archive_db=arch_db, core_path=core_path, slices_dir=slices_dir, force_all=True)
        finally:
            conn.close()

        # 2. Smoke-test brain_mcp.py (?mode=ro) stdio JSON-RPC roundtrip
        brain_mcp_server = Path(__file__).resolve().parent / "brain_mcp.py"
        requests = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2024-11-05"}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "corpus_status", "arguments": {}}},
            {
                "jsonrpc": "2.0",
                "id": 4,
                "method": "tools/call",
                "params": {"name": "corpus_query", "arguments": {"query": "phase superposition refraction", "max_tokens": 2200}},
            },
            {
                "jsonrpc": "2.0",
                "id": 5,
                "method": "tools/call",
                "params": {"name": "corpus_node", "arguments": {"node_id": n_bad}},
            },
        ]
        stdin_payload = "\n".join(json.dumps(r) for r in requests) + "\n"
        env = {"CORPUS_DB_PATH": str(self.db_path), "ARCHIVE_DB_PATH": str(arch_db), "PATH": "/usr/bin:/bin"}
        proc = subprocess.run(
            [sys.executable, str(brain_mcp_server)],
            input=stdin_payload,
            capture_output=True,
            text=True,
            env=env,
            check=True,
        )
        responses = {r["id"]: r for r in (json.loads(line) for line in proc.stdout.strip().splitlines())}
        self.assertEqual(responses[1]["result"]["serverInfo"]["name"], "brain_mcp")
        tool_names = {t["name"] for t in responses[2]["result"]["tools"]}
        self.assertTrue(
            {
                "corpus_status",
                "corpus_query",
                "corpus_node",
                "get_packet",
                "query_nodes",
                "check_flags",
                "handoff_queue",
            }.issubset(tool_names)
        )

        status_payload = json.loads(responses[3]["result"]["content"][0]["text"])
        self.assertEqual(status_payload["mode"], "ro")
        self.assertEqual(status_payload["nodes_total"], 2)
        self.assertTrue(status_payload["archive_db"]["available"])
        self.assertGreater(status_payload["core_digest"]["bytes"], 0)

        query_payload = json.loads(responses[4]["result"]["content"][0]["text"])
        self.assertLessEqual(query_payload["estimated_tokens"], 2200)
        self.assertIn(n_good, query_payload["citations"]["verified_node_ids"])
        self.assertTrue(
            any(
                fp["falsified_node_id"] == n_bad and fp["pivoted_to_node_id"] == n_good
                for fp in query_payload["citations"]["falsified_pivots"]
            )
        )

        node_payload = json.loads(responses[5]["result"]["content"][0]["text"])
        self.assertEqual(node_payload["mode"], "ro")
        self.assertEqual(node_payload["node"]["epistemic_tier"], "FALSIFIED")
        self.assertTrue(
            any(e["relation_type"] == "pivoted_to" and e["peer_node_id"] == n_good for e in node_payload["outgoing_edges"])
        )
        self.assertGreaterEqual(len(node_payload["provenance"]), 1)

        # 3. Test sync_and_ingest.py closed-loop runner
        watchlist = self.tmp_dir / "spark_watchlist.txt"
        watchlist.write_text("# Active watchlist\nhttps://gemini.google.com/spark/chat/spark_chat_test\n", encoding="utf-8")
        state_file = self.tmp_dir / "closedloop_state.json"
        log_file = self.tmp_dir / "closedloop.log"
        deltas_dir = self.tmp_dir / "closedloop_deltas"
        lock_file = self.tmp_dir / "closedloop.lock"

        # Add both an HTML-only turn (user_prompt NULL, user_html populated) and a plaintext turn to mock_archive.db
        aconn = sqlite3.connect(str(arch_db))
        aconn.execute(
            "INSERT INTO turns VALUES (11, 'spark_chat_test', 2, 'tid_spark_02', 'tid_spark_01', '', "
            "NULL, '<div class=\"user-query-container\" _ngcontent-x1=\"1\"><style>.hide{display:none}</style>"
            "<p>Descartes demon hypothesis and Landauer bit erasure thermodynamic bound.</p></div>', "
            "'Erasing one bit dissipates at least kT ln 2 heat into the thermal bath.', NULL, "
            "'2026-11-18T08:05:00Z', 'sha_sp_02')"
        )
        aconn.execute(
            "INSERT INTO turns VALUES (12, 'spark_chat_test', 3, 'tid_spark_03', 'tid_spark_02', '', "
            "'Verify refractive superposition scaling in coherent lattices.', NULL, "
            "'Constructive forward scattering lags the composite wavefront phase cleanly.', NULL, "
            "'2026-11-18T08:10:00Z', 'sha_sp_03')"
        )
        aconn.commit()
        aconn.close()

        # 3a. Contended fcntl.flock exits 0 with status='lock_held'
        sync_script = Path(__file__).resolve().parent / "sync_and_ingest.py"
        lock_fh = lock_file.open("a+", encoding="utf-8")
        try:
            fcntl.flock(lock_fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            locked_proc = subprocess.run(
                [
                    sys.executable,
                    str(sync_script),
                    "--dry-run",
                    "--skip-scrape",
                    "--db",
                    str(self.db_path),
                    "--archive-db",
                    str(arch_db),
                    "--watchlist",
                    str(watchlist),
                    "--state-file",
                    str(state_file),
                    "--log-file",
                    str(log_file),
                    "--deltas-dir",
                    str(deltas_dir),
                    "--lock-file",
                    str(lock_file),
                ],
                capture_output=True,
                text=True,
                check=True,
            )
            self.assertEqual(json.loads(locked_proc.stdout)["status"], "lock_held")
        finally:
            fcntl.flock(lock_fh.fileno(), fcntl.LOCK_UN)
            lock_fh.close()

        # Record pre-ingest counts
        pre_conn = sqlite3.connect(str(self.db_path))
        pre_chunks = pre_conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        pre_nodes = pre_conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
        pre_verif = pre_conn.execute("SELECT COUNT(*) FROM nodes WHERE epistemic_tier = 'EXTERNALLY_VERIFIED'").fetchone()[0]
        pre_conn.close()

        # 3b. --dry-run inspects delta without mutating DB or state
        dry_res = run_closedloop(
            db_path=self.db_path,
            archive_db=arch_db,
            watchlist_path=watchlist,
            state_file=state_file,
            log_file=log_file,
            deltas_dir=deltas_dir,
            lock_file=lock_file,
            dry_run=True,
            force=False,
            skip_scrape=True,
        )
        self.assertEqual(dry_res["status"], "dry_run_ok")
        self.assertGreaterEqual(dry_res["delta_turn_count"], 2)
        self.assertFalse(state_file.exists())
        chk_conn = sqlite3.connect(str(self.db_path))
        self.assertEqual(chk_conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0], pre_chunks)
        chk_conn.close()

        # 3c. First real delta ingest -> RAW_CLAIM, zero auto-promotions, refreshed core_digest.md
        ing_res = run_closedloop(
            db_path=self.db_path,
            archive_db=arch_db,
            watchlist_path=watchlist,
            state_file=state_file,
            log_file=log_file,
            deltas_dir=deltas_dir,
            lock_file=lock_file,
            dry_run=False,
            force=False,
            skip_scrape=True,
        )
        self.assertEqual(ing_res["status"], "ingested")
        self.assertEqual(ing_res["epistemic_tier"], "RAW_CLAIM")
        self.assertEqual(ing_res["nodes_auto_promoted"], 0)
        self.assertGreaterEqual(ing_res["chunks_inserted"], 4)
        self.assertTrue(state_file.exists())
        self.assertTrue(core_path.exists())

        post_conn = sqlite3.connect(str(self.db_path))
        post_chunks = post_conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        post_nodes = post_conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
        post_verif = post_conn.execute("SELECT COUNT(*) FROM nodes WHERE epistemic_tier = 'EXTERNALLY_VERIFIED'").fetchone()[0]
        spark_rows = post_conn.execute(
            "SELECT content, source_ref FROM chunks WHERE source_ref LIKE '%spark_chat_test%'"
        ).fetchall()
        post_conn.close()

        self.assertEqual(post_chunks, pre_chunks + ing_res["chunks_inserted"])
        self.assertEqual(post_nodes, pre_nodes)
        self.assertEqual(post_verif, pre_verif)
        joined_spark = "\n".join(r[0] for r in spark_rows)
        self.assertIn("Landauer bit erasure", joined_spark)
        self.assertNotIn("display:none", joined_spark)
        self.assertNotIn("_ngcontent", joined_spark)
        self.assertTrue(any("tier=RAW_CLAIM" in r[1] and "turn_id=tid_spark_02" in r[1] for r in spark_rows))

        # 3d. Immediate non-forced re-run must hit cooldown_active (< 4h)
        cool_res = run_closedloop(
            db_path=self.db_path,
            archive_db=arch_db,
            watchlist_path=watchlist,
            state_file=state_file,
            log_file=log_file,
            deltas_dir=deltas_dir,
            lock_file=lock_file,
            dry_run=False,
            force=False,
            skip_scrape=True,
        )
        self.assertEqual(cool_res["status"], "cooldown_active")

        # 3e. Immediate --force --skip-scrape re-run reports status='up_to_date' & corpus_db_writes=0
        zero_res = run_closedloop(
            db_path=self.db_path,
            archive_db=arch_db,
            watchlist_path=watchlist,
            state_file=state_file,
            log_file=log_file,
            deltas_dir=deltas_dir,
            lock_file=lock_file,
            dry_run=False,
            force=True,
            skip_scrape=True,
        )
        self.assertEqual(zero_res["status"], "up_to_date")
        self.assertEqual(zero_res["corpus_db_writes"], 0)

    def test_phase1_verifier_coupling_defeasibility_and_atomicity(self) -> None:
        """Verify F2.1 (defeasible FALSIFIED), F2.2 (verifier-scope coupling), and F2.3 (atomic claims)."""
        ingest_path(self.raw_dir, self.db_path)
        conn = get_connection(self.db_path)
        try:
            cids = [r["chunk_id"] for r in conn.execute("SELECT chunk_id FROM chunks LIMIT 3").fetchall()]

            # 1. F2.3 Atomic claim discipline rejects compound bundled claims
            ok_atomic, reasons_atomic = validate_atomic_claim(
                "Higgs vacuum expectation value imparts rest mass without kinematic drag."
            )
            self.assertTrue(ok_atomic)
            self.assertEqual(reasons_atomic, [])

            with self.assertRaises(ValueError):
                create_node_with_provenance(
                    conn,
                    domain="physics",
                    summary="Poynting flux carries EM power; pairs this valid electrodynamics with the flawed Higgs drag metaphor.",
                    chunk_ids=[cids[0]],
                )
            with self.assertRaises(ValueError):
                create_node_with_provenance(
                    conn,
                    domain="bio_neuro_psych",
                    summary="(1) Gamma synchrony tracks binding; (2) dendritic spines melt from plasma strikes.",
                    chunk_ids=[cids[0]],
                )

            n_claim = create_node_with_provenance(
                conn,
                domain="physics",
                summary="Optical refraction arises from discrete atomic absorption pauses.",
                chunk_ids=[cids[0]],
                epistemic_tier="RAW_CLAIM",
            )
            n_reframe = create_node_with_provenance(
                conn,
                domain="physics",
                summary="Optical refraction arises from coherent phase superposition of scattered waves.",
                chunk_ids=[cids[1]],
                epistemic_tier="DSL_CONSISTENT",
            )
            n_appeal = create_node_with_provenance(
                conn,
                domain="physics",
                summary="Resonant slow-light EIT media introduce genuine group-velocity storage delays.",
                chunk_ids=[cids[2]],
                epistemic_tier="RAW_CLAIM",
            )

            # 2. F2.2 Verifier-type / scope coupling lock
            chk = run_physics_check("n = 1.333\nassert 1.0 < n < 2.0\nprint('ok')\n")
            self.assertTrue(chk["passed"])

            # 2a. python_sim forbidden on literature_citation and primary_record
            with self.assertRaises(ValueError):
                verify_node(
                    conn,
                    node_id=n_reframe,
                    verifier_type="python_sim",
                    verification_scope="literature_citation",
                    external_ref=chk["external_ref"],
                    benchmark_ref="Feynman Lectures Vol. I Ch. 31",
                    new_tier="EXTERNALLY_VERIFIED",
                )
            with self.assertRaises(ValueError):
                verify_node(
                    conn,
                    node_id=n_reframe,
                    verifier_type="python_sim",
                    verification_scope="primary_record",
                    external_ref=chk["external_ref"],
                    benchmark_ref="NIST refractive index table",
                    new_tier="EXTERNALLY_VERIFIED",
                )

            # 2b. literature_ref / public_record reject pycheck: or bare text, accept doi:/pmid:/arxiv:/https://
            self.assertFalse(is_valid_primary_external_ref("pycheck:deadbeef12345678"))
            self.assertFalse(is_valid_primary_external_ref("Wiener 1948"))
            self.assertTrue(is_valid_primary_external_ref("doi:10.1038/s41586-024-07566-y"))
            self.assertTrue(is_valid_primary_external_ref("pmid:22726877"))
            self.assertTrue(is_valid_primary_external_ref("arxiv:2502.11371"))
            self.assertTrue(is_valid_primary_external_ref("https://www.sqlite.org/atomiccommit.html"))

            with self.assertRaises(ValueError):
                verify_node(
                    conn,
                    node_id=n_reframe,
                    verifier_type="literature_ref",
                    verification_scope="literature_citation",
                    external_ref=chk["external_ref"],
                    benchmark_ref="Shumailov et al. (2024)",
                    new_tier="EXTERNALLY_VERIFIED",
                )
            with self.assertRaises(ValueError):
                verify_node(
                    conn,
                    node_id=n_reframe,
                    verifier_type="public_record",
                    verification_scope="primary_record",
                    external_ref="not-a-uri",
                    benchmark_ref="NIST record",
                    new_tier="EXTERNALLY_VERIFIED",
                )

            # 2c. Database-level trigger blocks raw SQL bypasses too
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute(
                    "INSERT INTO node_verifications (node_id, verifier_type, verification_scope, external_ref, benchmark_ref, passed) "
                    "VALUES (?, 'python_sim', 'literature_citation', 'pycheck:1234567890abcdef', 'Bypass attempt', 1)",
                    (n_reframe,),
                )
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute(
                    "INSERT INTO node_verifications (node_id, verifier_type, verification_scope, external_ref, benchmark_ref, passed) "
                    "VALUES (?, 'literature_ref', 'literature_citation', 'pycheck:1234567890abcdef', 'Bypass attempt', 1)",
                    (n_reframe,),
                )

            # 2d. Valid literature_ref with real DOI succeeds
            v_lit = verify_node(
                conn,
                node_id=n_reframe,
                verifier_type="literature_ref",
                verification_scope="literature_citation",
                external_ref="doi:10.1119/1.1972241",
                benchmark_ref="Ewald-Oseen extinction theorem (Fearn et al. 1996)",
                new_tier="EXTERNALLY_VERIFIED",
            )
            self.assertEqual(v_lit["new_tier"], "EXTERNALLY_VERIFIED")

            # 3. F2.1 Defeasible FALSIFIED: falsify + converge branch, then reopen with primary evidence
            b_id = int(
                conn.execute(
                    "INSERT INTO research_branches (root_node_id, agent_role, max_dry_hops) VALUES (?, 'falsifier', 3)",
                    (n_claim,),
                ).lastrowid
            )
            conn.commit()
            verify_and_link(
                conn,
                from_node_id=n_claim,
                to_node_id=n_reframe,
                relation_type="resolved_mistake",
                verifier_type="python_sim",
                verification_scope="standard_physics_law",
                external_ref=chk["external_ref"],
                benchmark_ref="Non-resonant dielectric refraction v=c/n",
                branch_id=b_id,
                promote_node_id=n_claim,
                new_tier="FALSIFIED",
            )
            piv = verify_and_link(
                conn,
                from_node_id=n_claim,
                to_node_id=n_reframe,
                relation_type="pivoted_to",
                verifier_type="python_sim",
                verification_scope="standard_physics_law",
                external_ref=chk["external_ref"],
                benchmark_ref="Non-resonant dielectric refraction v=c/n",
                branch_id=b_id,
            )
            self.assertEqual(piv["branch"]["status"], "CONVERGED")

            # 3a. llm_only cannot reopen a FALSIFIED node
            with self.assertRaises(ValueError):
                reopen_falsified_node(
                    conn,
                    target_node_id=n_claim,
                    challenging_node_id=n_appeal,
                    verifier_type="llm_only",
                    verification_scope="llm_only",
                    external_ref="",
                    benchmark_ref="",
                    branch_id=b_id,
                )

            # 3b. Primary DOI evidence reopens FALSIFIED node -> UNDER_APPEAL and CONVERGED branch -> ACTIVE
            reopened = reopen_falsified_node(
                conn,
                target_node_id=n_claim,
                challenging_node_id=n_appeal,
                verifier_type="literature_ref",
                verification_scope="literature_citation",
                external_ref="doi:10.1038/17561",
                benchmark_ref="Hau et al. (1999) Nature 397, 594 slow light in ultracold atoms",
                relation_type="challenges_falsification",
                new_tier="UNDER_APPEAL",
                branch_id=b_id,
            )
            self.assertEqual(reopened["new_tier"], "UNDER_APPEAL")
            self.assertEqual(reopened["branch"]["status"], "ACTIVE")
            self.assertEqual(
                conn.execute("SELECT epistemic_tier FROM nodes WHERE node_id = ?", (n_claim,)).fetchone()[0],
                "UNDER_APPEAL",
            )

            # 3c. Reopened node can transition further via reopens -> CONTESTED
            contested = reopen_falsified_node(
                conn,
                target_node_id=n_claim,
                challenging_node_id=n_appeal,
                verifier_type="literature_ref",
                verification_scope="literature_citation",
                external_ref="arxiv:quant-ph/0001001",
                benchmark_ref="Scope-dependent resonant vs non-resonant optical delay",
                relation_type="reopens",
                new_tier="CONTESTED",
                branch_id=b_id,
            )
            self.assertEqual(contested["new_tier"], "CONTESTED")
            self.assertEqual(contested["branch"]["status"], "ACTIVE")
        finally:
            conn.close()

    def test_handoff_queue_mcp_bus_and_corpus_cli(self) -> None:
        """Verify handoff_queue helpers, consolidated MCP bus tools, and corpus_cli.py end-to-end."""
        from db_utils import enqueue_handoff, list_handoffs, update_handoff_status

        scripts_dir = Path(__file__).resolve().parent
        db_path = self.tmp_dir / "bus_test.db"
        init_db(db_path)
        conn = get_connection(db_path)
        try:
            # Seed one chunk + one node + one resolved flag so query_nodes / check_flags / get_packet exercise real rows
            cid = int(
                conn.execute(
                    """
                    INSERT INTO chunks (source_type, source_ref, author, sha256, content)
                    VALUES ('md', 'test:bus.md', 'Henry', 'sha_bus_001',
                            'Decoupled SQLite state gating prevents contradiction recurrence via BEFORE INSERT triggers.')
                    """
                ).lastrowid
            )
            conn.execute("INSERT INTO chunks_fts(rowid, content) VALUES (?, ?)", (cid, "Decoupled SQLite state gating prevents contradiction recurrence via BEFORE INSERT triggers."))
            n_id = create_node_with_provenance(
                conn,
                domain="ai_systems",
                summary="Decoupled SQLite state gating enforces verifier-scope coupling inside BEFORE INSERT triggers.",
                chunk_ids=[cid],
                dsl_expr="Trigger(verifier_type, scope) -> ACID_commit",
                epistemic_tier="RAW_CLAIM",
            )
            conn.execute(
                """
                INSERT INTO node_audit_flags (node_id, flag_type, prior_tier, reason, resolved)
                VALUES (?, 'compound_falsified_needs_split', 'FALSIFIED', 'test resolved flag', 1)
                """,
                (n_id,),
            )
            conn.commit()

            # 1. Direct db_utils handoff_queue lifecycle + CHECK guard
            t1 = enqueue_handoff(
                conn,
                title="Sync Volume II cross-anchor",
                spec="Update Volume II SHA-256 to match Volume I Rev. 3.",
                constraints="Read-only archive.db; preserve 1,122 nodes.",
            )
            self.assertEqual(t1["status"], "PENDING")
            self.assertEqual(len(list_handoffs(conn)), 1)
            with self.assertRaises(ValueError):
                update_handoff_status(conn, t1["task_id"], "BOGUS_STATE")
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute(
                    "INSERT INTO handoff_queue (title, spec, status) VALUES ('bad', 'bad', 'INVALID')"
                )
            t1_app = update_handoff_status(conn, t1["task_id"], "APPROVED", summary="Approved by Henry")
            self.assertEqual(t1_app["status"], "APPROVED")
        finally:
            conn.close()

        # 2. Consolidated local MCP bus stdio JSON-RPC roundtrip (scripts/brain_mcp.py)
        import os

        env = dict(os.environ)
        env["CORPUS_DB_PATH"] = str(db_path)
        env["ARCHIVE_DB_PATH"] = str(self.tmp_dir / "nonexistent_archive.db")
        reqs = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2024-11-05"}},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "corpus_status", "arguments": {}}},
            {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "get_packet", "arguments": {"query": "SQLite triggers", "max_tokens": 1200}}},
            {"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {"name": "query_nodes", "arguments": {"query": "SQLite", "tier": "RAW_CLAIM"}}},
            {"jsonrpc": "2.0", "id": 6, "method": "tools/call", "params": {"name": "check_flags", "arguments": {"include_resolved": True}}},
            {"jsonrpc": "2.0", "id": 7, "method": "tools/call", "params": {"name": "handoff_queue", "arguments": {"action": "enqueue", "title": "MCP queued task", "spec": "Run verify"}}},
            {"jsonrpc": "2.0", "id": 8, "method": "tools/call", "params": {"name": "handoff_queue", "arguments": {"action": "list"}}},
        ]
        proc = subprocess.run(
            [sys.executable, str(scripts_dir / "brain_mcp.py")],
            input="\n".join(json.dumps(r) for r in reqs) + "\n",
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        resps = {r["id"]: r for r in (json.loads(ln) for ln in proc.stdout.strip().splitlines() if ln.strip())}

        tool_names = {t["name"] for t in resps[2]["result"]["tools"]}
        self.assertTrue(
            {"corpus_status", "get_packet", "query_nodes", "check_flags", "handoff_queue"}.issubset(tool_names)
        )
        st_payload = json.loads(resps[3]["result"]["content"][0]["text"])
        self.assertEqual(st_payload["open_audit_flags"], 0)
        self.assertEqual(st_payload["handoff_queue"]["total"], 1)

        pkt_payload = json.loads(resps[4]["result"]["content"][0]["text"])
        self.assertLessEqual(pkt_payload["estimated_tokens"], 1200)

        qn_payload = json.loads(resps[5]["result"]["content"][0]["text"])
        self.assertEqual(qn_payload["total_matching"], 1)

        cf_payload = json.loads(resps[6]["result"]["content"][0]["text"])
        self.assertEqual(cf_payload["open_flags_total"], 0)
        self.assertEqual(cf_payload["resolved_flags_total"], 1)

        hq_list = json.loads(resps[8]["result"]["content"][0]["text"])
        self.assertEqual(hq_list["count"], 2)

        # 3. Unified CLI (scripts/corpus_cli.py): status, queue approve/run, verify (DB-only mode)
        cli = [sys.executable, str(scripts_dir / "corpus_cli.py"), "--db", str(db_path)]
        st_cli = subprocess.run(cli + ["status", "--json"], capture_output=True, text=True, check=False)
        self.assertEqual(st_cli.returncode, 0, st_cli.stderr)
        self.assertEqual(json.loads(st_cli.stdout)["handoff_queue"]["total"], 2)

        run_cli = subprocess.run(
            cli + ["queue", "run", str(t1["task_id"]), "--cmd", "echo cli_handoff_ok"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(run_cli.returncode, 0, run_cli.stderr)
        ran = json.loads(run_cli.stdout)
        self.assertEqual(ran["status"], "COMPLETED")
        self.assertEqual(ran["exit_code"], 0)
        self.assertEqual(len(ran["sha256_diff"]), 64)

        vf_cli = subprocess.run(
            cli + ["verify", "--skip-tests", "--skip-pdfs", "--json"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(vf_cli.returncode, 0, vf_cli.stderr)
        self.assertTrue(json.loads(vf_cli.stdout)["ok"])

    def test_dom_virtualization_non_regression_and_hydration_audit(self) -> None:
        from backfill_archive_virtualization import run_backfill
        from sync_and_ingest import (
            audit_archive_hydration,
            detect_archive_deltas,
            merge_turn_non_regressive,
        )

        # 1. Non-regression guard refuses to overwrite populated prose with empty DOM stubs
        existing = {
            "user_prompt": "Explain energy gradients delaying entropy.",
            "user_html": "<p>Explain energy gradients delaying entropy.</p>",
            "model_response": "Energy gradients sustain local dissipative structures.",
            "model_html": "<p>Energy gradients sustain local dissipative structures.</p>",
            "model_thoughts": "",
        }
        empty_stub = {
            "user_prompt": "",
            "user_html": "",
            "model_response": "",
            "model_html": "",
            "model_thoughts": "",
        }
        merged = merge_turn_non_regressive(existing, empty_stub)
        self.assertEqual(merged["user_prompt"], existing["user_prompt"])
        self.assertEqual(merged["model_response"], existing["model_response"])

        # 2. Mock archive.db with 1 hydrated turn, 1 HTML-only virtualized turn, and 1 truly empty remote stub
        arch_db = self.tmp_dir / "virt_archive.db"
        conn = sqlite3.connect(str(arch_db))
        conn.execute(
            "CREATE TABLE conversations (chat_id TEXT PRIMARY KEY, title TEXT, status TEXT, "
            "total_user_chars INTEGER DEFAULT 0, total_model_chars INTEGER DEFAULT 0, error_message TEXT)"
        )
        conn.execute(
            "CREATE TABLE turns (id INTEGER PRIMARY KEY, chat_id TEXT, turn_index INTEGER, turn_id TEXT, "
            "parent_turn_id TEXT, user_prompt TEXT, user_html TEXT, model_response TEXT, model_html TEXT, "
            "model_thoughts TEXT, user_token_estimate INTEGER DEFAULT 0, model_token_estimate INTEGER DEFAULT 0, "
            "timestamp_hint TEXT, sha256 TEXT)"
        )
        conn.execute("CREATE VIRTUAL TABLE turns_fts USING fts5(chat_id, title, user_prompt, model_response)")
        conn.execute("INSERT INTO conversations (chat_id, title, status) VALUES ('chat_v1', 'Virtualized Thread', 'captured_unverified')")
        conn.execute(
            "INSERT INTO turns (id, chat_id, turn_index, turn_id, user_prompt, user_html, model_response, model_html, sha256) "
            "VALUES (1, 'chat_v1', 1, 't1', 'Already hydrated user turn.', '<p>Already hydrated user turn.</p>', "
            "'Already hydrated model turn.', '<p>Already hydrated model turn.</p>', 'sha1')"
        )
        conn.execute(
            "INSERT INTO turns (id, chat_id, turn_index, turn_id, user_prompt, user_html, model_response, model_html, sha256) "
            "VALUES (2, 'chat_v1', 2, 't2', '', '<div class=\"user-query-container\"><p>Recovered from Angular DOM HTML.</p></div>', "
            "'', '<div class=\"markdown\"><p>Recovered model prose from DOM HTML.</p></div>', '')"
        )
        conn.execute(
            "INSERT INTO turns (id, chat_id, turn_index, turn_id, user_prompt, user_html, model_response, model_html, sha256) "
            "VALUES (3, 'chat_v1', 3, 't3', '', '', '', '', '')"
        )
        conn.commit()
        conn.close()

        # 3. Pre-backfill hydration audit catches PARTIAL_VIRTUALIZATION (1/3)
        audit_before = audit_archive_hydration(arch_db)
        self.assertTrue(audit_before["archive_available"])
        self.assertEqual(audit_before["hydrated_turns"], 1)
        self.assertEqual(audit_before["total_dom_slots"], 3)
        self.assertEqual(audit_before["partial_virtualization_count"], 1)
        self.assertEqual(audit_before["partial_virtualization_chats"][0]["status"], "PARTIAL_VIRTUALIZATION")

        # 4. detect_archive_deltas skips empty stub t3 without poisoning corpus.db
        init_db(self.db_path)
        delta = detect_archive_deltas(db_path=self.db_path, archive_db=arch_db, state={}, watchlist_chat_ids=["chat_v1"])
        self.assertEqual(delta["empty_stub_turns_skipped"], 1)
        self.assertEqual(delta["delta_turn_count"], 2)  # t1 + HTML-recovered t2

        # 5. Backfill recovers t2 non-regressively and flags t3 as UNRECOVERABLE_REMOTE (never fabricating text)
        rep = run_backfill(arch_db, report_out=None, dry_run=False, skip_backup=True)
        self.assertEqual(rep["before"]["active_turns"], 1)
        self.assertEqual(rep["after"]["active_turns"], 2)
        self.assertEqual(rep["recovery_summary"]["turns_recovered_from_dom_html"], 1)
        self.assertEqual(rep["recovery_summary"]["unrecoverable_remote_turns"], 1)
        self.assertEqual(rep["affected_conversations"][0]["status"], "UNRECOVERABLE_REMOTE")


if __name__ == "__main__":
    unittest.main(verbosity=2)
