"""In-place migration of data/corpus.db to schema v2 (node_verifications, SIM_CONSISTENT, no self-loops)."""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from db_utils import DEFAULT_DB_PATH, get_connection


def migrate(db_path: Path = DEFAULT_DB_PATH) -> dict[str, int]:
    conn = get_connection(db_path)
    try:
        conn.execute("PRAGMA foreign_keys = OFF;")
        conn.execute("BEGIN;")

        # 1. Create node_verifications if not exists
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS node_verifications (
                verification_id    INTEGER PRIMARY KEY,
                node_id            INTEGER NOT NULL REFERENCES nodes(node_id) ON DELETE CASCADE,
                verifier_type      TEXT NOT NULL
                                   CHECK (verifier_type IN ('python_sim', 'lean_coq', 'public_record', 'literature_ref', 'llm_only')),
                verification_scope TEXT NOT NULL
                                   CHECK (verification_scope IN ('toy_model', 'standard_physics_law', 'empirical_benchmark', 'primary_record', 'literature_citation', 'llm_only')),
                external_ref       TEXT,
                benchmark_ref      TEXT,
                passed             INTEGER NOT NULL CHECK (passed IN (0, 1)),
                notes              TEXT,
                created_at         TEXT NOT NULL DEFAULT (datetime('now'))
            );
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_verif_node ON node_verifications(node_id);")

        # 2. Rebuild nodes with SIM_CONSISTENT in CHECK constraint
        conn.execute(
            """
            CREATE TABLE nodes_v2 (
                node_id         INTEGER PRIMARY KEY,
                domain          TEXT NOT NULL,
                dsl_expr        TEXT,
                summary         TEXT NOT NULL,
                epistemic_tier  TEXT NOT NULL DEFAULT 'RAW_CLAIM'
                                CHECK (epistemic_tier IN (
                                    'RAW_CLAIM', 'DSL_CONSISTENT', 'SIM_CONSISTENT', 'EXTERNALLY_VERIFIED', 'FALSIFIED'
                                )),
                created_at      TEXT NOT NULL DEFAULT (datetime('now'))
            );
            """
        )
        conn.execute("INSERT INTO nodes_v2 SELECT * FROM nodes;")
        conn.execute("DROP TABLE nodes;")
        conn.execute("ALTER TABLE nodes_v2 RENAME TO nodes;")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_nodes_tier ON nodes(epistemic_tier);")

        # 3. Convert self-loop edges to node_verifications, then rebuild edges with CHECK (from_node != to_node)
        self_loops = conn.execute(
            "SELECT * FROM edges WHERE from_node = to_node"
        ).fetchall()
        for row in self_loops:
            conn.execute(
                """
                INSERT INTO node_verifications
                    (node_id, verifier_type, verification_scope, external_ref, benchmark_ref, passed, notes, created_at)
                VALUES (?, ?, 'standard_physics_law', ?, 'Classical Mechanics: Noether symmetry & Verlet Kepler conservation', 1, ?, ?)
                """,
                (row["from_node"], row["verifier_type"], row["external_ref"], row["notes"], row["created_at"]),
            )

        conn.execute(
            """
            CREATE TABLE edges_v2 (
                edge_id        INTEGER PRIMARY KEY,
                from_node      INTEGER NOT NULL REFERENCES nodes(node_id) ON DELETE CASCADE,
                to_node        INTEGER NOT NULL REFERENCES nodes(node_id) ON DELETE CASCADE,
                relation_type  TEXT NOT NULL
                               CHECK (relation_type IN (
                                   'isomorphic_to', 'supports', 'breaks', 'refines', 'resolved_mistake', 'pivoted_to'
                               )),
                verifier_type  TEXT NOT NULL DEFAULT 'llm_only'
                               CHECK (verifier_type IN (
                                   'python_sim', 'lean_coq', 'public_record', 'literature_ref', 'llm_only'
                               )),
                external_ref   TEXT,
                notes          TEXT,
                created_at     TEXT NOT NULL DEFAULT (datetime('now')),
                CHECK (from_node != to_node)
            );
            """
        )
        conn.execute(
            """
            INSERT INTO edges_v2 (edge_id, from_node, to_node, relation_type, verifier_type, external_ref, notes, created_at)
            SELECT edge_id, from_node, to_node, relation_type, verifier_type, external_ref, notes, created_at
            FROM edges
            WHERE from_node != to_node;
            """
        )
        conn.execute("DROP TABLE edges;")
        conn.execute("ALTER TABLE edges_v2 RENAME TO edges;")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_edges_from ON edges(from_node);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_edges_to ON edges(to_node);")

        # 4. Backfill node_verifications for Batch 1 nodes 2..8 if empty, and tighten node 6 to SIM_CONSISTENT
        existing_vnodes = {r[0] for r in conn.execute("SELECT DISTINCT node_id FROM node_verifications").fetchall()}
        backfills = [
            (2, "python_sim", "standard_physics_law", "pycheck:007ee510f0368076", "Special Relativity: Lorentz gamma divergence at v->c", 0, "Falsified photon rest frame."),
            (3, "python_sim", "standard_physics_law", "pycheck:007ee510f0368076", "Special Relativity: Null geodesic ds^2=0 & E=pc", 1, "Verified Lorentz invariance of ds^2=0."),
            (4, "python_sim", "standard_physics_law", "pycheck:6a4288795d644c8b", "Special Relativity: Euclidean metric boost test", 0, "Falsified Euclidean metric invariance (16.81% drift)."),
            (5, "python_sim", "standard_physics_law", "pycheck:6a4288795d644c8b", "Special Relativity: Minkowski metric signature (+,-,-,-)", 1, "Verified ds^2 invariance to 0.00e+00."),
            (6, "python_sim", "toy_model", "pycheck:855065af20229d70", "Illustrative wave superposition identity using prescribed n=1.333", 1, "Toy phase-shift check only; downgraded to SIM_CONSISTENT until full Lorentz-oscillator dispersion benchmark is run."),
            (7, "python_sim", "standard_physics_law", "pycheck:df6897d9a5e8b65a", "Quantum Mechanics / Fourier Analysis: Kennard-Heisenberg bound sigma_x*sigma_k >= 1/2", 1, "DFT confirmed sigma_x*sigma_k = 0.5000."),
            (8, "python_sim", "standard_physics_law", "pycheck:df6897d9a5e8b65a", "Quantum Mechanics: Born rule complex amplitude interference", 1, "Confirmed destructive cancellation vs classical probability sum."),
        ]
        for nid, vt, vs, eref, bref, passed, notes in backfills:
            if nid not in existing_vnodes:
                conn.execute(
                    """
                    INSERT INTO node_verifications
                        (node_id, verifier_type, verification_scope, external_ref, benchmark_ref, passed, notes)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (nid, vt, vs, eref, bref, passed, notes),
                )
        # Apply strict toy-script demotion to node 6 until an empirical/physical dispersion check is run
        conn.execute(
            "UPDATE nodes SET epistemic_tier = 'SIM_CONSISTENT' WHERE node_id = 6 AND epistemic_tier = 'EXTERNALLY_VERIFIED'"
        )

        conn.commit()
        counts = {
            "self_loops_migrated": len(self_loops),
            "nodes": conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0],
            "edges": conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0],
            "node_verifications": conn.execute("SELECT COUNT(*) FROM node_verifications").fetchone()[0],
        }
        return counts
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.close()


if __name__ == "__main__":
    import json
    print(json.dumps(migrate(), indent=2))
