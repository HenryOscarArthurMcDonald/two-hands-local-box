"""Non-destructive in-place migration of data/corpus.db to schema v3 (F2.1, F2.2, F2.3).

Applies:
  1. Expanded nodes.epistemic_tier CHECK adding CONTESTED and UNDER_APPEAL.
  2. Expanded edges.relation_type CHECK adding reopens and challenges_falsification.
  3. node_audit_flags table for non-destructive provisional re-tiering and compound-split queues.
  4. BEFORE INSERT SQLite trigger trg_verif_scope_coupling enforcing F2.2 at engine level.
  5. Non-destructive re-tiering of existing pycheck:-only literature_citation/primary_record nodes:
       - EXTERNALLY_VERIFIED -> SIM_CONSISTENT (flagged provisional_pycheck_literature_ev)
       - FALSIFIED           -> CONTESTED      (flagged provisional_pycheck_literature_falsified)
  6. Non-destructive flagging of compound FALSIFIED nodes (flagged compound_falsified_needs_split).
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from db_utils import DEFAULT_DB_PATH, get_connection


TRIGGER_SQL = """
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
                 OR (
                     lower(NEW.external_ref) NOT LIKE 'doi:%'
                     AND lower(NEW.external_ref) NOT LIKE 'pmid:%'
                     AND lower(NEW.external_ref) NOT LIKE 'arxiv:%'
                     AND lower(NEW.external_ref) NOT LIKE 'https://%'
                 )
             )
        THEN RAISE(ABORT, 'External identifier lock (F2.2): literature_ref/public_record requires doi:, pmid:, arxiv:, or https:// external_ref')
        WHEN NEW.verification_scope IN ('literature_citation', 'primary_record')
             AND NEW.external_ref IS NOT NULL
             AND lower(NEW.external_ref) LIKE 'pycheck:%'
        THEN RAISE(ABORT, 'External identifier lock (F2.2): pycheck: hashes are forbidden for literature_citation or primary_record')
    END;
END;
"""


def migrate_v3(db_path: Path = DEFAULT_DB_PATH) -> dict[str, Any]:
    conn = get_connection(db_path)
    try:
        conn.execute("PRAGMA foreign_keys = OFF;")
        conn.execute("BEGIN;")

        # 1. Rebuild nodes table with CONTESTED and UNDER_APPEAL if needed
        nodes_sql = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='nodes'"
        ).fetchone()[0]
        if "'UNDER_APPEAL'" not in nodes_sql or "'CONTESTED'" not in nodes_sql:
            conn.execute(
                """
                CREATE TABLE nodes_v3 (
                    node_id         INTEGER PRIMARY KEY,
                    domain          TEXT NOT NULL,
                    dsl_expr        TEXT,
                    summary         TEXT NOT NULL,
                    epistemic_tier  TEXT NOT NULL DEFAULT 'RAW_CLAIM'
                                    CHECK (epistemic_tier IN (
                                        'RAW_CLAIM',
                                        'DSL_CONSISTENT',
                                        'SIM_CONSISTENT',
                                        'CONTESTED',
                                        'UNDER_APPEAL',
                                        'EXTERNALLY_VERIFIED',
                                        'FALSIFIED'
                                    )),
                    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
                );
                """
            )
            conn.execute(
                "INSERT INTO nodes_v3 (node_id, domain, dsl_expr, summary, epistemic_tier, created_at) "
                "SELECT node_id, domain, dsl_expr, summary, epistemic_tier, created_at FROM nodes;"
            )
            conn.execute("DROP TABLE nodes;")
            conn.execute("ALTER TABLE nodes_v3 RENAME TO nodes;")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_nodes_tier ON nodes(epistemic_tier);")

        # 2. Rebuild edges table with reopens and challenges_falsification if needed
        edges_sql = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='edges'"
        ).fetchone()[0]
        if "'reopens'" not in edges_sql or "'challenges_falsification'" not in edges_sql:
            conn.execute(
                """
                CREATE TABLE edges_v3 (
                    edge_id        INTEGER PRIMARY KEY,
                    from_node      INTEGER NOT NULL REFERENCES nodes(node_id) ON DELETE CASCADE,
                    to_node        INTEGER NOT NULL REFERENCES nodes(node_id) ON DELETE CASCADE,
                    relation_type  TEXT NOT NULL
                                   CHECK (relation_type IN (
                                       'isomorphic_to',
                                       'supports',
                                       'breaks',
                                       'refines',
                                       'resolved_mistake',
                                       'pivoted_to',
                                       'reopens',
                                       'challenges_falsification'
                                   )),
                    verifier_type  TEXT NOT NULL DEFAULT 'llm_only'
                                   CHECK (verifier_type IN (
                                       'python_sim',
                                       'lean_coq',
                                       'public_record',
                                       'literature_ref',
                                       'llm_only'
                                   )),
                    external_ref   TEXT,
                    notes          TEXT,
                    created_at     TEXT NOT NULL DEFAULT (datetime('now')),
                    CHECK (from_node != to_node)
                );
                """
            )
            conn.execute(
                "INSERT INTO edges_v3 (edge_id, from_node, to_node, relation_type, verifier_type, external_ref, notes, created_at) "
                "SELECT edge_id, from_node, to_node, relation_type, verifier_type, external_ref, notes, created_at FROM edges;"
            )
            conn.execute("DROP TABLE edges;")
            conn.execute("ALTER TABLE edges_v3 RENAME TO edges;")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_edges_from ON edges(from_node);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_edges_to ON edges(to_node);")

        # 3. Create node_audit_flags table
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS node_audit_flags (
                flag_id    INTEGER PRIMARY KEY,
                node_id    INTEGER NOT NULL REFERENCES nodes(node_id) ON DELETE CASCADE,
                flag_type  TEXT NOT NULL
                           CHECK (flag_type IN (
                               'provisional_pycheck_literature_ev',
                               'provisional_pycheck_literature_falsified',
                               'compound_falsified_needs_split'
                           )),
                prior_tier TEXT,
                reason     TEXT NOT NULL,
                resolved   INTEGER NOT NULL DEFAULT 0 CHECK (resolved IN (0, 1)),
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                UNIQUE (node_id, flag_type)
            );
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_flags_type ON node_audit_flags(flag_type, resolved);")

        # 3b. Create structured PR-style handoff_queue table
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS handoff_queue (
                task_id     INTEGER PRIMARY KEY,
                title       TEXT NOT NULL,
                spec        TEXT NOT NULL,
                constraints TEXT NOT NULL DEFAULT '',
                status      TEXT NOT NULL DEFAULT 'PENDING'
                            CHECK (status IN ('PENDING','RUNNING','NEEDS_APPROVAL','APPROVED','COMPLETED','FAILED')),
                exit_code   INTEGER,
                sha256_diff TEXT,
                summary     TEXT,
                created_at  TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
            );
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_handoff_status ON handoff_queue(status, updated_at);")

        # 4. Install BEFORE INSERT trigger enforcing F2.2 verifier-scope coupling
        conn.execute("DROP TRIGGER IF EXISTS trg_verif_scope_coupling;")
        conn.execute(TRIGGER_SQL)

        # 5. Flag compound FALSIFIED nodes BEFORE re-tiering pycheck literature nodes (F2.3)
        compound_rows = conn.execute(
            """
            SELECT node_id FROM nodes
            WHERE epistemic_tier = 'FALSIFIED'
              AND (
                  lower(summary) LIKE '%vs.%'
                  OR lower(summary) LIKE '%paired with%'
                  OR lower(summary) LIKE '%valid%'
                  OR lower(summary) LIKE '%contrasts%'
              )
            ORDER BY node_id
            """
        ).fetchall()
        compound_flagged = 0
        for row in compound_rows:
            cur = conn.execute(
                """
                INSERT OR IGNORE INTO node_audit_flags (node_id, flag_type, prior_tier, reason)
                VALUES (?, 'compound_falsified_needs_split', 'FALSIFIED',
                        'F2.3 audit: compound node bundles multiple/contrasting propositions under one FALSIFIED stamp; queued for atomic splitting.')
                """,
                (int(row["node_id"]),),
            )
            compound_flagged += cur.rowcount

        # 6. Non-destructively re-tier EXTERNALLY_VERIFIED pycheck:-only literature nodes -> SIM_CONSISTENT (F2.2)
        ev_pylit_rows = conn.execute(
            """
            SELECT n.node_id, MIN(nv.external_ref) AS orig_ref
            FROM nodes n
            JOIN node_verifications nv ON nv.node_id = n.node_id
            WHERE n.epistemic_tier = 'EXTERNALLY_VERIFIED'
              AND nv.verifier_type = 'python_sim'
              AND nv.verification_scope IN ('literature_citation', 'primary_record')
              AND nv.external_ref LIKE 'pycheck:%'
              AND NOT EXISTS (
                  SELECT 1 FROM node_verifications nv2
                  WHERE nv2.node_id = n.node_id AND nv2.passed = 1
                    AND (
                        (nv2.verifier_type = 'python_sim'
                         AND nv2.verification_scope IN ('standard_physics_law', 'empirical_benchmark'))
                        OR (nv2.verifier_type IN ('literature_ref', 'public_record', 'lean_coq')
                            AND nv2.external_ref IS NOT NULL
                            AND lower(nv2.external_ref) NOT LIKE 'pycheck:%')
                    )
              )
            GROUP BY n.node_id
            ORDER BY n.node_id
            """
        ).fetchall()
        ev_demoted = 0
        for row in ev_pylit_rows:
            nid = int(row["node_id"])
            orig_ref = str(row["orig_ref"])
            cur = conn.execute(
                """
                INSERT OR IGNORE INTO node_audit_flags (node_id, flag_type, prior_tier, reason)
                VALUES (?, 'provisional_pycheck_literature_ev', 'EXTERNALLY_VERIFIED',
                        'F2.2 migration v3: prior EXTERNALLY_VERIFIED rested solely on python_sim + literature_citation (pycheck:); downgraded to SIM_CONSISTENT pending primary DOI/PMID/arXiv/HTTPS literature_ref.')
                """,
                (nid,),
            )
            if cur.rowcount > 0:
                conn.execute(
                    "UPDATE nodes SET epistemic_tier = 'SIM_CONSISTENT' WHERE node_id = ?",
                    (nid,),
                )
                conn.execute(
                    """
                    INSERT INTO node_verifications
                        (node_id, verifier_type, verification_scope, external_ref, benchmark_ref, passed, notes)
                    VALUES (?, 'python_sim', 'toy_model', ?, 'F2.2_migration_v3:demoted_pycheck_literature_ev', 1,
                            'Non-destructive F2.2 re-tiering: EXTERNALLY_VERIFIED -> SIM_CONSISTENT until backed by primary literature_ref (doi:/pmid:/arxiv:/https://).')
                    """,
                    (nid, orig_ref),
                )
                ev_demoted += 1

        # 7. Non-destructively re-tier FALSIFIED pycheck:-only literature nodes -> CONTESTED (F2.2)
        f_pylit_rows = conn.execute(
            """
            SELECT n.node_id, MIN(nv.external_ref) AS orig_ref
            FROM nodes n
            JOIN node_verifications nv ON nv.node_id = n.node_id
            WHERE n.epistemic_tier = 'FALSIFIED'
              AND nv.verifier_type = 'python_sim'
              AND nv.verification_scope IN ('literature_citation', 'primary_record')
              AND nv.external_ref LIKE 'pycheck:%'
              AND NOT EXISTS (
                  SELECT 1 FROM node_verifications nv2
                  WHERE nv2.node_id = n.node_id AND nv2.passed = 0
                    AND (
                        (nv2.verifier_type = 'python_sim'
                         AND nv2.verification_scope IN ('standard_physics_law', 'empirical_benchmark'))
                        OR (nv2.verifier_type IN ('literature_ref', 'public_record', 'lean_coq')
                            AND nv2.external_ref IS NOT NULL
                            AND lower(nv2.external_ref) NOT LIKE 'pycheck:%')
                    )
              )
            GROUP BY n.node_id
            ORDER BY n.node_id
            """
        ).fetchall()
        f_demoted = 0
        for row in f_pylit_rows:
            nid = int(row["node_id"])
            orig_ref = str(row["orig_ref"])
            cur = conn.execute(
                """
                INSERT OR IGNORE INTO node_audit_flags (node_id, flag_type, prior_tier, reason)
                VALUES (?, 'provisional_pycheck_literature_falsified', 'FALSIFIED',
                        'F2.2 migration v3: prior FALSIFIED rested solely on python_sim + literature_citation (pycheck:); moved to CONTESTED pending primary DOI/PMID/arXiv/HTTPS literature_ref.')
                """,
                (nid,),
            )
            if cur.rowcount > 0:
                conn.execute(
                    "UPDATE nodes SET epistemic_tier = 'CONTESTED' WHERE node_id = ?",
                    (nid,),
                )
                conn.execute(
                    """
                    INSERT INTO node_verifications
                        (node_id, verifier_type, verification_scope, external_ref, benchmark_ref, passed, notes)
                    VALUES (?, 'python_sim', 'toy_model', ?, 'F2.2_migration_v3:demoted_pycheck_literature_falsified', 0,
                            'Non-destructive F2.2 re-tiering: FALSIFIED -> CONTESTED until backed by primary literature_ref (doi:/pmid:/arxiv:/https://).')
                    """,
                    (nid, orig_ref),
                )
                f_demoted += 1

        conn.commit()
        conn.execute("PRAGMA foreign_keys = ON;")
        fk_violations = conn.execute("PRAGMA foreign_key_check;").fetchall()
        if fk_violations:
            raise RuntimeError(f"Foreign key violations after v3 migration: {fk_violations[:5]}")

        tiers = dict(
            conn.execute(
                "SELECT epistemic_tier, COUNT(*) FROM nodes GROUP BY epistemic_tier ORDER BY epistemic_tier"
            ).fetchall()
        )
        flags = dict(
            conn.execute(
                "SELECT flag_type, COUNT(*) FROM node_audit_flags GROUP BY flag_type ORDER BY flag_type"
            ).fetchall()
        )
        return {
            "db_path": str(db_path),
            "ev_pycheck_lit_demoted_to_sim_consistent": ev_demoted,
            "falsified_pycheck_lit_demoted_to_contested": f_demoted,
            "compound_falsified_flagged_for_split": compound_flagged,
            "total_nodes": sum(tiers.values()),
            "post_migration_tiers": tiers,
            "audit_flags": flags,
            "total_edges": conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0],
            "total_verifications": conn.execute("SELECT COUNT(*) FROM node_verifications").fetchone()[0],
            "foreign_key_violations": len(fk_violations),
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Migrate corpus.db to schema v3 (F2.1–F2.3).")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    args = parser.parse_args()
    result = migrate_v3(args.db)
    print(json.dumps(result, indent=2))
