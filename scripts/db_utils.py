"""Shared SQLite, epistemic gate, FTS5 search, and verification helpers."""

from __future__ import annotations

import hashlib
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

_ENV_CORPUS_HOME = os.environ.get("CORPUS_HOME", "").strip()
WORKSPACE_ROOT = (
    Path(_ENV_CORPUS_HOME).expanduser().resolve()
    if _ENV_CORPUS_HOME
    else Path(__file__).resolve().parent.parent
)
DEFAULT_DB_PATH = Path(os.environ.get("CORPUS_DB_PATH", str(WORKSPACE_ROOT / "data" / "corpus.db"))).expanduser()
SCHEMA_PATH = WORKSPACE_ROOT / "schema" / "schema.sql"
VALID_HANDOFF_STATUSES = (
    "PENDING",
    "RUNNING",
    "NEEDS_APPROVAL",
    "APPROVED",
    "COMPLETED",
    "FAILED",
)

DEFAULT_BRIDGES: list[tuple[str, str, str]] = [
    ("mousetrap", "stateless forward pass", "stateless_input_to_output_cascade"),
    ("stateless forward pass", "mousetrap", "stateless_input_to_output_cascade"),
    ("harness", "feedback loop", "stateless_map_in_feedback_loop"),
    ("thermostat", "feedback loop", "stateless_map_in_feedback_loop"),
    ("refraction", "phase superposition", "wave_interference_effective_velocity"),
    ("speed of light", "causality", "invariant_maximum_propagation_speed"),
    ("tax code", "boolean logic", "rule_system_dressed_as_prose"),
    ("phase transition", "universality", "substrate_independent_critical_behavior"),
    ("conservation", "symmetry", "noether_invariant_under_transformation"),
    ("entropy", "compression", "information_theoretic_state_counting"),
]

VALID_TIERS = (
    "RAW_CLAIM",
    "DSL_CONSISTENT",
    "SIM_CONSISTENT",
    "CONTESTED",
    "UNDER_APPEAL",
    "EXTERNALLY_VERIFIED",
    "FALSIFIED",
)
VALID_RELATIONS = (
    "isomorphic_to",
    "supports",
    "breaks",
    "refines",
    "resolved_mistake",
    "pivoted_to",
    "reopens",
    "challenges_falsification",
    "splits_from",
)
REOPEN_RELATIONS = ("reopens", "challenges_falsification")
VALID_VERIFIERS = ("python_sim", "lean_coq", "public_record", "literature_ref", "llm_only")
EXTERNAL_SCOPES = (
    "standard_physics_law",
    "empirical_benchmark",
    "primary_record",
    "literature_citation",
)
LITERATURE_SCOPES = ("literature_citation", "primary_record")
PRIMARY_REF_PREFIXES = ("doi:", "pmid:", "arxiv:", "https://")
VALID_SCOPES = ("toy_model", "llm_only") + EXTERNAL_SCOPES

COMPOUND_BUNDLE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("numbered_multi_claim_list", re.compile(r"\(1\).*\(2\)", re.IGNORECASE | re.DOTALL)),
    (
        "valid_plus_overclaim_bundle",
        re.compile(
            r"\b(?:pairs\s+(?:this\s+)?valid|paired\s+with\s+the\s+(?:false|flawed|overclaim|unsubstantiated)|"
            r"contrasts\s+valid|blends\s+clinically\s+recognized|while\s+refuting\s+the\s+claim|"
            r"with\s+the\s+(?:false\s+(?:mathematical\s+)?claim|overclaim)\s+that)\b",
            re.IGNORECASE,
        ),
    ),
)


def is_valid_primary_external_ref(ref: str | None) -> bool:
    """Return True iff ref carries a real primary identifier (doi:, pmid:, arxiv:, or https://)."""
    if not ref:
        return False
    clean = ref.strip()
    low = clean.lower()
    if low.startswith("pycheck:") or any(ch.isspace() for ch in clean):
        return False
    for prefix in PRIMARY_REF_PREFIXES:
        if low.startswith(prefix):
            body = clean[len(prefix) :].strip()
            if prefix == "https://":
                return "." in body and len(body) >= 4
            return len(body) >= 4
    return False


def validate_atomic_claim(summary: str) -> tuple[bool, list[str]]:
    """Enforce single-claim atomicity (F2.3) so valid mechanisms are not bundled with overclaims."""
    text = (summary or "").strip()
    reasons: list[str] = []
    if not text:
        return False, ["empty_summary"]
    for label, pat in COMPOUND_BUNDLE_PATTERNS:
        if pat.search(text):
            reasons.append(label)
    if text.count(";") >= 2 and len(text) > 260:
        reasons.append("multi_clause_semicolon_bundle")
    return (len(reasons) == 0), reasons


def get_connection(db_path: Path | str = DEFAULT_DB_PATH) -> sqlite3.Connection:
    """Open a SQLite connection with foreign keys and Row factory enabled."""
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def init_db(db_path: Path | str = DEFAULT_DB_PATH) -> Path:
    """Initialize schema tables and seed default cross-domain concept bridges."""
    path = Path(db_path)
    schema_sql = SCHEMA_PATH.read_text(encoding="utf-8")
    conn = get_connection(path)
    try:
        conn.executescript(schema_sql)
        cols = {r[1] for r in conn.execute('PRAGMA table_info("chapter_slices")').fetchall()}
        if "skip_reason" not in cols:
            conn.execute("ALTER TABLE chapter_slices ADD COLUMN skip_reason TEXT;")
        conn.executemany(
            "INSERT OR IGNORE INTO concept_bridges (term, alias, structural_pattern) VALUES (?, ?, ?)",
            DEFAULT_BRIDGES,
        )
        conn.commit()
    finally:
        conn.close()
    return path


def fts_sanitize(phrase: str) -> str:
    """Turn a phrase into a safe FTS5 AND query over alphanumeric tokens."""
    tokens = re.findall(r"[A-Za-z0-9_]+", phrase)
    return " AND ".join(f'"{tok}"' for tok in tokens) if tokens else ""


def find_matching_bridges(conn: sqlite3.Connection, query: str) -> list[dict[str, str]]:
    """Return bidirectional concept bridges matching any term or alias inside query."""
    q_lower = query.lower()
    rows = conn.execute(
        """
        SELECT term, alias, COALESCE(structural_pattern, '') AS structural_pattern
        FROM concept_bridges
        WHERE ? LIKE '%' || lower(term) || '%'
           OR ? LIKE '%' || lower(alias) || '%'
        """,
        (q_lower, q_lower),
    ).fetchall()
    return [dict(r) for r in rows]


def search_corpus_global(
    conn: sqlite3.Connection,
    query: str,
    limit: int = 12,
    expand_bridges: bool = True,
) -> dict[str, Any]:
    """Run FTS5 BM25 search globally across all chunks, optionally expanding via concept_bridges."""
    phrases = [query]
    bridges: list[dict[str, str]] = []
    if expand_bridges:
        bridges = find_matching_bridges(conn, query)
        for b in bridges:
            for candidate in (b["alias"], b["term"]):
                if candidate and candidate.lower() not in [p.lower() for p in phrases]:
                    phrases.append(candidate)

    best_hits: dict[int, dict[str, Any]] = {}
    for phrase in phrases:
        fts_query = fts_sanitize(phrase)
        if not fts_query:
            continue
        rows = conn.execute(
            """
            SELECT c.chunk_id, c.source_type, c.source_ref, c.author, c.created_at,
                   c.content, bm25(chunks_fts) AS score
            FROM chunks_fts
            JOIN chunks c ON c.chunk_id = chunks_fts.rowid
            WHERE chunks_fts MATCH ?
            ORDER BY score
            LIMIT ?
            """,
            (fts_query, limit),
        ).fetchall()
        for r in rows:
            cid = r["chunk_id"]
            if cid not in best_hits or r["score"] < best_hits[cid]["score"]:
                hit = dict(r)
                hit["matched_via"] = phrase
                best_hits[cid] = hit

    ranked = sorted(best_hits.values(), key=lambda x: x["score"])[:limit]
    return {
        "query": query,
        "expanded_phrases": phrases,
        "bridges_used": bridges,
        "hits": ranked,
    }


def get_chunk_context(conn: sqlite3.Connection, chunk_id: int, window: int = 2) -> list[dict[str, Any]]:
    """Fetch surrounding chunks from the same source_ref around chunk_id."""
    anchor = conn.execute(
        "SELECT source_ref FROM chunks WHERE chunk_id = ?",
        (chunk_id,),
    ).fetchone()
    if anchor is None:
        return []
    rows = conn.execute(
        """
        SELECT chunk_id, source_type, source_ref, author, created_at, content
        FROM chunks
        WHERE source_ref = ?
          AND chunk_id BETWEEN ? AND ?
        ORDER BY chunk_id ASC
        """,
        (anchor["source_ref"], chunk_id - window, chunk_id + window),
    ).fetchall()
    return [dict(r) for r in rows]


def create_node_with_provenance(
    conn: sqlite3.Connection,
    domain: str,
    summary: str,
    chunk_ids: list[int],
    dsl_expr: str | None = None,
    quote_spans: list[str] | None = None,
    epistemic_tier: str = "RAW_CLAIM",
    enforce_atomic: bool = True,
) -> int:
    """Insert a node only if grounded in at least one valid chunk_id and single-claim atomic."""
    if not chunk_ids:
        raise ValueError("Provenance lock: at least one chunk_id is required to create a node.")
    if epistemic_tier not in ("RAW_CLAIM", "DSL_CONSISTENT", "CONTESTED"):
        raise ValueError(
            "Tier creation lock: new nodes must start as RAW_CLAIM, DSL_CONSISTENT, or CONTESTED "
            "(use verify_node or verify_and_link to promote)."
        )
    if enforce_atomic:
        is_atomic, reasons = validate_atomic_claim(summary)
        if not is_atomic:
            raise ValueError(
                f"Atomic claim lock (F2.3): summary appears to bundle multiple claims ({', '.join(reasons)}). "
                "Split valid mechanisms and speculative overclaims into separate atomic nodes."
            )

    existing = {
        r["chunk_id"]
        for r in conn.execute(
            f"SELECT chunk_id FROM chunks WHERE chunk_id IN ({','.join('?' for _ in chunk_ids)})",
            tuple(chunk_ids),
        ).fetchall()
    }
    missing = [cid for cid in chunk_ids if cid not in existing]
    if missing:
        raise ValueError(f"Unknown chunk_id(s) in provenance: {missing}")

    cur = conn.execute(
        """
        INSERT INTO nodes (domain, dsl_expr, summary, epistemic_tier)
        VALUES (?, ?, ?, ?)
        """,
        (domain.strip(), dsl_expr, summary.strip(), epistemic_tier),
    )
    node_id = int(cur.lastrowid)
    spans = quote_spans or []
    for idx, cid in enumerate(chunk_ids):
        span = spans[idx] if idx < len(spans) else None
        conn.execute(
            "INSERT OR IGNORE INTO node_provenance (node_id, chunk_id, quote_span) VALUES (?, ?, ?)",
            (node_id, cid, span),
        )
    conn.commit()
    return node_id


def attach_node_provenance(
    conn: sqlite3.Connection,
    node_id: int,
    chunk_ids: list[int],
    quote_spans: list[str] | None = None,
) -> dict[str, Any]:
    """Attach additional chunk_id provenance to an existing canonical node_id (deduplication)."""
    if not chunk_ids:
        raise ValueError("At least one chunk_id is required to attach provenance.")
    node = conn.execute("SELECT node_id FROM nodes WHERE node_id = ?", (node_id,)).fetchone()
    if node is None:
        raise ValueError(f"Unknown node_id: {node_id}")
    existing = {
        r["chunk_id"]
        for r in conn.execute(
            f"SELECT chunk_id FROM chunks WHERE chunk_id IN ({','.join('?' for _ in chunk_ids)})",
            tuple(chunk_ids),
        ).fetchall()
    }
    missing = [cid for cid in chunk_ids if cid not in existing]
    if missing:
        raise ValueError(f"Unknown chunk_id(s) in provenance: {missing}")

    spans = quote_spans or []
    added = 0
    for idx, cid in enumerate(chunk_ids):
        span = spans[idx] if idx < len(spans) else None
        cur = conn.execute(
            "INSERT OR IGNORE INTO node_provenance (node_id, chunk_id, quote_span) VALUES (?, ?, ?)",
            (node_id, cid, span),
        )
        added += cur.rowcount
    conn.commit()
    total = conn.execute("SELECT COUNT(*) FROM node_provenance WHERE node_id = ?", (node_id,)).fetchone()[0]
    return {"node_id": node_id, "chunks_attached": added, "total_provenance_chunks": total}


def _validate_verification_inputs(
    verifier_type: str,
    verification_scope: str,
    external_ref: str | None,
    benchmark_ref: str | None,
    new_tier: str | None,
) -> tuple[str | None, str | None]:
    if verifier_type not in VALID_VERIFIERS:
        raise ValueError(f"Invalid verifier_type {verifier_type!r}; expected one of {VALID_VERIFIERS}")
    if verification_scope not in VALID_SCOPES:
        raise ValueError(f"Invalid verification_scope {verification_scope!r}; expected one of {VALID_SCOPES}")

    clean_ref = (external_ref or "").strip() or None
    clean_bench = (benchmark_ref or "").strip() or None

    # F2.2 Verifier-Type / Scope Coupling Lock: close pycheck literature bypass.
    if verifier_type == "python_sim" and verification_scope in LITERATURE_SCOPES:
        raise ValueError(
            f"Verifier-scope lock (F2.2): verifier_type='python_sim' is forbidden for "
            f"verification_scope={verification_scope!r}. Use 'literature_ref' or 'public_record' "
            "with a primary identifier (doi:, pmid:, arxiv:, or https://)."
        )
    if verifier_type in ("literature_ref", "public_record"):
        if not is_valid_primary_external_ref(clean_ref):
            raise ValueError(
                f"External identifier lock (F2.2): verifier_type={verifier_type!r} requires a primary "
                f"external_ref starting with one of {PRIMARY_REF_PREFIXES} (pycheck: hashes rejected); "
                f"got {clean_ref!r}."
            )
    if verification_scope in LITERATURE_SCOPES and clean_ref and clean_ref.lower().startswith("pycheck:"):
        raise ValueError(
            f"External identifier lock (F2.2): pycheck: hashes are forbidden for "
            f"verification_scope={verification_scope!r}; supply doi:, pmid:, arxiv:, or https://."
        )

    if new_tier is not None:
        if new_tier not in VALID_TIERS:
            raise ValueError(f"Invalid epistemic_tier {new_tier!r}; expected one of {VALID_TIERS}")
        if new_tier == "SIM_CONSISTENT":
            if verifier_type == "llm_only" or not clean_ref:
                raise ValueError(
                    "SIM_CONSISTENT requires a non-llm_only verifier_type and a non-empty external_ref."
                )
        elif new_tier == "EXTERNALLY_VERIFIED":
            if verifier_type == "llm_only" or not clean_ref:
                raise ValueError(
                    "Tier promotion lock: EXTERNALLY_VERIFIED requires a non-llm_only verifier_type and non-empty external_ref."
                )
            if verification_scope not in EXTERNAL_SCOPES or not clean_bench:
                raise ValueError(
                    "Toy-script lock: EXTERNALLY_VERIFIED requires verification_scope in "
                    f"{EXTERNAL_SCOPES} and a non-empty benchmark_ref (toy_model can reach at most SIM_CONSISTENT)."
                )
    return clean_ref, clean_bench


def _check_active_branch(
    conn: sqlite3.Connection,
    branch_id: int | None,
    *,
    allow_reopen: bool = False,
) -> sqlite3.Row | None:
    if branch_id is None:
        return None
    branch = conn.execute(
        "SELECT * FROM research_branches WHERE branch_id = ?",
        (branch_id,),
    ).fetchone()
    if branch is None:
        raise ValueError(f"Unknown branch_id: {branch_id}")
    if branch["status"] != "ACTIVE":
        if allow_reopen and branch["status"] == "CONVERGED":
            conn.execute(
                """
                UPDATE research_branches
                SET status = 'ACTIVE', hops_since_novelty = 0, updated_at = datetime('now')
                WHERE branch_id = ?
                """,
                (branch_id,),
            )
            branch = conn.execute(
                "SELECT * FROM research_branches WHERE branch_id = ?",
                (branch_id,),
            ).fetchone()
            return branch
        raise ValueError(f"Branch {branch_id} is {branch['status']} and cannot accept new hops.")
    return branch


def _is_branch_converged(conn: sqlite3.Connection, root_node_id: int) -> bool:
    """Return True when root_node_id is EXTERNALLY_VERIFIED or FALSIFIED with a verified pivot target."""
    row = conn.execute(
        "SELECT epistemic_tier FROM nodes WHERE node_id = ?",
        (root_node_id,),
    ).fetchone()
    if row is None:
        return False
    if row["epistemic_tier"] == "EXTERNALLY_VERIFIED":
        return True
    if row["epistemic_tier"] == "FALSIFIED":
        pivoted = conn.execute(
            """
            SELECT 1
            FROM edges e
            JOIN nodes nt ON nt.node_id = e.to_node
            WHERE e.from_node = ?
              AND e.relation_type = 'pivoted_to'
              AND nt.epistemic_tier = 'EXTERNALLY_VERIFIED'
            LIMIT 1
            """,
            (root_node_id,),
        ).fetchone()
        return pivoted is not None
    return False


def reconcile_converged_branches(conn: sqlite3.Connection) -> dict[str, Any]:
    """Flip any ACTIVE branch whose root node has reached terminal resolution to CONVERGED."""
    active = conn.execute(
        "SELECT branch_id, root_node_id FROM research_branches WHERE status = 'ACTIVE' ORDER BY branch_id"
    ).fetchall()
    converged_ids: list[int] = []
    still_active: list[int] = []
    for r in active:
        if _is_branch_converged(conn, int(r["root_node_id"])):
            conn.execute(
                "UPDATE research_branches SET status = 'CONVERGED', updated_at = datetime('now') WHERE branch_id = ?",
                (r["branch_id"],),
            )
            converged_ids.append(int(r["branch_id"]))
        else:
            still_active.append(int(r["branch_id"]))
    conn.commit()
    return {"converged_branch_ids": converged_ids, "still_active_branch_ids": still_active}


def _advance_branch(
    conn: sqlite3.Connection,
    branch: sqlite3.Row | None,
    verifier_type: str,
    verification_scope: str,
    clean_ref: str | None,
    clean_bench: str | None,
    new_tier: str | None,
) -> dict[str, Any] | None:
    if branch is None:
        return None
    external_evidence = (
        verifier_type != "llm_only"
        and clean_ref is not None
        and verification_scope in EXTERNAL_SCOPES
        and clean_bench is not None
    )
    novelty_gained = external_evidence or (new_tier == "EXTERNALLY_VERIFIED")
    total_hops = int(branch["total_hops"]) + 1
    dry_hops = 0 if novelty_gained else int(branch["hops_since_novelty"]) + 1
    if dry_hops >= int(branch["max_dry_hops"]):
        new_status = "HALTED_NOVELTY"
    elif novelty_gained and _is_branch_converged(conn, int(branch["root_node_id"])):
        new_status = "CONVERGED"
    else:
        new_status = "ACTIVE"
    conn.execute(
        """
        UPDATE research_branches
        SET total_hops = ?, hops_since_novelty = ?, status = ?, updated_at = datetime('now')
        WHERE branch_id = ?
        """,
        (total_hops, dry_hops, new_status, branch["branch_id"]),
    )
    return {
        "branch_id": int(branch["branch_id"]),
        "total_hops": total_hops,
        "hops_since_novelty": dry_hops,
        "max_dry_hops": int(branch["max_dry_hops"]),
        "status": new_status,
        "novelty_gained": novelty_gained,
    }


def verify_node(
    conn: sqlite3.Connection,
    node_id: int,
    verifier_type: str,
    verification_scope: str,
    external_ref: str | None = None,
    benchmark_ref: str | None = None,
    passed: bool = True,
    branch_id: int | None = None,
    new_tier: str | None = None,
    notes: str = "",
) -> dict[str, Any]:
    """Record a single-node verification without creating a self-loop edge."""
    clean_ref, clean_bench = _validate_verification_inputs(
        verifier_type, verification_scope, external_ref, benchmark_ref, new_tier
    )
    branch = _check_active_branch(conn, branch_id, allow_reopen=new_tier in ("UNDER_APPEAL", "CONTESTED"))

    cur = conn.execute(
        """
        INSERT INTO node_verifications
            (node_id, verifier_type, verification_scope, external_ref, benchmark_ref, passed, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (node_id, verifier_type, verification_scope, clean_ref, clean_bench, 1 if passed else 0, notes.strip() or None),
    )
    verification_id = int(cur.lastrowid)

    if new_tier is not None:
        conn.execute("UPDATE nodes SET epistemic_tier = ? WHERE node_id = ?", (new_tier, node_id))

    branch_state = _advance_branch(
        conn, branch, verifier_type, verification_scope, clean_ref, clean_bench, new_tier
    )
    conn.commit()
    return {
        "verification_id": verification_id,
        "node_id": node_id,
        "new_tier": new_tier,
        "verification_scope": verification_scope,
        "branch": branch_state,
    }


def verify_and_link(
    conn: sqlite3.Connection,
    from_node_id: int,
    to_node_id: int,
    relation_type: str,
    verifier_type: str,
    external_ref: str | None = None,
    verification_scope: str = "llm_only",
    benchmark_ref: str | None = None,
    branch_id: int | None = None,
    promote_node_id: int | None = None,
    new_tier: str | None = None,
    notes: str = "",
) -> dict[str, Any]:
    """Record a directed inter-node edge (no self-loops), enforce tier locks, and update branch budget."""
    if from_node_id == to_node_id:
        raise ValueError(
            "Self-loop edge disallowed (from_node_id == to_node_id): use verify_node for single-node verifications."
        )
    if relation_type not in VALID_RELATIONS:
        raise ValueError(f"Invalid relation_type {relation_type!r}; expected one of {VALID_RELATIONS}")

    clean_ref, clean_bench = _validate_verification_inputs(
        verifier_type, verification_scope, external_ref, benchmark_ref, new_tier
    )
    allow_reopen = relation_type in REOPEN_RELATIONS or new_tier in ("UNDER_APPEAL", "CONTESTED")
    branch = _check_active_branch(conn, branch_id, allow_reopen=allow_reopen)

    cur = conn.execute(
        """
        INSERT INTO edges (from_node, to_node, relation_type, verifier_type, external_ref, notes)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (from_node_id, to_node_id, relation_type, verifier_type, clean_ref, notes.strip() or None),
    )
    edge_id = int(cur.lastrowid)

    verification_id: int | None = None
    if promote_node_id is not None and new_tier is not None:
        conn.execute(
            "UPDATE nodes SET epistemic_tier = ? WHERE node_id = ?",
            (new_tier, promote_node_id),
        )
        vcur = conn.execute(
            """
            INSERT INTO node_verifications
                (node_id, verifier_type, verification_scope, external_ref, benchmark_ref, passed, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                promote_node_id,
                verifier_type,
                verification_scope,
                clean_ref,
                clean_bench,
                0 if new_tier == "FALSIFIED" else 1,
                notes.strip() or None,
            ),
        )
        verification_id = int(vcur.lastrowid)

    branch_state = _advance_branch(
        conn, branch, verifier_type, verification_scope, clean_ref, clean_bench, new_tier
    )
    conn.commit()
    return {
        "edge_id": edge_id,
        "verification_id": verification_id,
        "promoted_node_id": promote_node_id,
        "new_tier": new_tier,
        "branch": branch_state,
    }


def reopen_falsified_node(
    conn: sqlite3.Connection,
    target_node_id: int,
    challenging_node_id: int,
    verifier_type: str,
    verification_scope: str,
    external_ref: str,
    benchmark_ref: str,
    *,
    relation_type: str = "challenges_falsification",
    new_tier: str = "UNDER_APPEAL",
    branch_id: int | None = None,
    notes: str = "",
) -> dict[str, Any]:
    """Make FALSIFIED defeasible (F2.1): reopen a FALSIFIED node and its CONVERGED branch with new primary evidence."""
    if target_node_id == challenging_node_id:
        raise ValueError("Self-loop disallowed: challenging_node_id must differ from target_node_id.")
    if relation_type not in REOPEN_RELATIONS:
        raise ValueError(f"Reopen requires relation_type in {REOPEN_RELATIONS}; got {relation_type!r}.")
    if new_tier not in ("UNDER_APPEAL", "CONTESTED", "EXTERNALLY_VERIFIED"):
        raise ValueError(
            f"reopen_falsified_node new_tier must be UNDER_APPEAL, CONTESTED, or EXTERNALLY_VERIFIED; got {new_tier!r}."
        )
    if verifier_type == "llm_only" or verification_scope not in EXTERNAL_SCOPES or not (benchmark_ref or "").strip():
        raise ValueError(
            "Defeasibility lock (F2.1): reopening a FALSIFIED node requires non-llm_only verifier_type, "
            f"verification_scope in {EXTERNAL_SCOPES}, a valid external_ref, and non-empty benchmark_ref."
        )

    target = conn.execute(
        "SELECT node_id, epistemic_tier FROM nodes WHERE node_id = ?",
        (target_node_id,),
    ).fetchone()
    if target is None:
        raise ValueError(f"Unknown target_node_id: {target_node_id}")
    if target["epistemic_tier"] not in ("FALSIFIED", "CONTESTED", "UNDER_APPEAL"):
        raise ValueError(
            f"Node #{target_node_id} is {target['epistemic_tier']}; only FALSIFIED/CONTESTED/UNDER_APPEAL nodes can be reopened."
        )

    # Auto-find any CONVERGED branch rooted at target_node_id if branch_id was omitted.
    if branch_id is None:
        brow = conn.execute(
            "SELECT branch_id FROM research_branches WHERE root_node_id = ? ORDER BY branch_id DESC LIMIT 1",
            (target_node_id,),
        ).fetchone()
        if brow is not None:
            branch_id = int(brow["branch_id"])

    return verify_and_link(
        conn,
        from_node_id=challenging_node_id,
        to_node_id=target_node_id,
        relation_type=relation_type,
        verifier_type=verifier_type,
        external_ref=external_ref,
        verification_scope=verification_scope,
        benchmark_ref=benchmark_ref,
        branch_id=branch_id,
        promote_node_id=target_node_id,
        new_tier=new_tier,
        notes=notes or f"Reopened #{target_node_id} via {relation_type} from #{challenging_node_id}",
    )


def run_physics_check(python_code: str, timeout_s: int = 10) -> dict[str, Any]:
    """Execute a deterministic Python verification snippet and return an external_ref hash on pass."""
    with tempfile.TemporaryDirectory(prefix="physcheck_") as tmpdir:
        script_path = Path(tmpdir) / "check.py"
        script_path.write_text(python_code, encoding="utf-8")
        try:
            proc = subprocess.run(
                [sys.executable, str(script_path)],
                cwd=tmpdir,
                capture_output=True,
                text=True,
                timeout=timeout_s,
            )
        except subprocess.TimeoutExpired:
            return {
                "passed": False,
                "exit_code": -1,
                "stdout": "",
                "stderr": f"Timed out after {timeout_s}s",
                "external_ref": None,
            }

    digest = hashlib.sha256((python_code + "\n---\n" + proc.stdout).encode("utf-8")).hexdigest()[:16]
    passed = proc.returncode == 0
    return {
        "passed": passed,
        "exit_code": proc.returncode,
        "stdout": proc.stdout[:4000],
        "stderr": proc.stderr[:4000],
        "external_ref": f"pycheck:{digest}" if passed else None,
    }


THEMATIC_BUCKETS: list[tuple[str, tuple[str, ...]]] = [
    (
        "Scattering Geometry & S-Matrix Bootstrap",
        ("veneziano", "coon", "bootstrap", "amplituhedron", "associahedron", "polytope", "s-matrix"),
    ),
    (
        "Flow Networks & Cross-Domain Morphisms",
        ("murray", "constructal", "viscous", "bifurcation", "bottleneck", "plumbing", "neurodivergen"),
    ),
    (
        "Quantum Information, Unitarity & Duality",
        ("unitarity", "decoherence", "bloch", "quaternary", "fourier", "heisenberg", "born", "entropy", "landauer"),
    ),
    (
        "Spacetime, Causality & Electrodynamics",
        ("photon", "light", "minkowski", "lorentz", "refraction", "sellmeier", "maxwell", "null", "metric", "clock"),
    ),
    (
        "Symmetry, Conservation & Inertia",
        ("noether", "symmetry", "conservation", "inertia", "higgs", "momentum", "oscillator", "yukawa", "propagator", "path integral", "least action", "stationary-phase"),
    ),
    (
        "Axiomatic Limits, Gödel & Completeness",
        ("godel", "gödel", "incompleteness", "axiom", "undecidable", "halting", "presburger", "peano", "tarski", "consistency"),
    ),
    (
        "Category Theory, Functors & Type Isomorphisms",
        ("functor", "morphism", "isomorphism", "curry-howard", "adjunction", "monad", "homotopy", "lean", "type theory", "projection"),
    ),
    (
        "Topology, Manifolds & Cobordism",
        ("topology", "indiscrete", "manifold", "cobordism", "pair of pants", "euler", "chern", "homology", "homeomorph"),
    ),
    (
        "Neural Architectures, Attention & Representation",
        ("transformer", "attention", "softmax", "embedding", "latent", "gradient", "backprop", "mlp", "feedforward", "context window", "kv cache"),
    ),
    (
        "Cybernetics, Control Loops & Active Inference",
        ("cybernetic", "feedback", "markov blanket", "free energy", "kalman", "pid", "thermostat", "attractor", "homeostasis", "mealy", "stateful"),
    ),
    (
        "Epistemic Grounding, Alignment & Multi-Agent Systems",
        ("sycophancy", "wireheading", "calibration", "hallucination", "provenance", "mimicry", "guardrail", "harness", "epistemic", "goodhart"),
    ),
    (
        "Neurobiology, HPA Axis & Autonomic Regulation",
        ("amygdala", "prefrontal", "hippocampus", "cortisol", "hpa", "vagus", "autonomic", "circadian", "interoception", "sympathetic", "parasympathetic"),
    ),
    (
        "Neurodivergence, Executive Function & Cognitive Psych",
        ("pda", "autis", "adhd", "audhd", "neurodivergen", "dmn", "salience", "executive function", "trauma", "anxiety", "coping", "demand avoidance"),
    ),
    (
        "Pharmacokinetics, Receptor Pharmacology & Biology",
        ("pharmacokinetic", "cyp", "half-life", "dopamine", "serotonin", "norepinephrine", "ssri", "stimulant", "vyvanse", "dexamphetamine", "receptor", "synap", "genetic", "evolution"),
    ),
]


def estimate_tokens(text: str) -> int:
    """Deterministic token estimator aligned with benchmark_ab.count_tokens."""
    if not text:
        return 0
    words_and_punct = re.findall(r"\b[\w']+\b|[^\w\s]", text)
    return max(int(len(words_and_punct) * 1.15), int(len(text) / 3.9))


THEME_TO_SECTION_KEY: dict[str, str] = {
    "Symmetry, Conservation & Inertia": "SYMMETRY_CONSERVATION_INERTIA",
    "Spacetime, Causality & Electrodynamics": "SPACETIME_CAUSALITY_ELECTRODYNAMICS",
    "Quantum Information, Unitarity & Duality": "QUANTUM_INFO_UNITARITY_DUALITY",
    "Scattering Geometry & S-Matrix Bootstrap": "SCATTERING_GEOMETRY_BOOTSTRAP",
    "Flow Networks & Cross-Domain Morphisms": "FLOW_NETWORKS_MORPHISMS",
    "Axiomatic Limits, Gödel & Completeness": "AXIOMATIC_LIMITS_GODEL",
    "Category Theory, Functors & Type Isomorphisms": "CATEGORY_THEORY_FUNCTORS",
    "Topology, Manifolds & Cobordism": "TOPOLOGY_MANIFOLDS_COBORDISM",
    "Neural Architectures, Attention & Representation": "NEURAL_ARCHITECTURES_ATTENTION",
    "Cybernetics, Control Loops & Active Inference": "CYBERNETICS_ACTIVE_INFERENCE",
    "Epistemic Grounding, Alignment & Multi-Agent Systems": "EPISTEMIC_GROUNDING_ALIGNMENT",
    "Neurobiology, HPA Axis & Autonomic Regulation": "NEUROBIOLOGY_HPA_AUTONOMIC",
    "Neurodivergence, Executive Function & Cognitive Psych": "NEURODIVERGENCE_COGNITIVE_PSYCH",
    "Pharmacokinetics, Receptor Pharmacology & Biology": "PHARMACOKINETICS_BIOLOGY",
    "General Invariants & Cross-Domain Synthesis": "GENERAL_CROSS_DOMAIN_SYNTHESIS",
}
SECTION_KEY_TO_THEME: dict[str, str] = {v: k for k, v in THEME_TO_SECTION_KEY.items()}


def section_key_for_theme(theme: str) -> str:
    """Return canonical uppercase # KEYWORD: anchor key for a thematic bucket."""
    if theme in THEME_TO_SECTION_KEY:
        return THEME_TO_SECTION_KEY[theme]
    slug = re.sub(r"[^A-Za-z0-9]+", "_", theme).strip("_").upper()
    return slug or "GENERAL_CROSS_DOMAIN_SYNTHESIS"


def ensure_digest_state_table(conn: sqlite3.Connection) -> None:
    """Create digest_state table idempotently on existing corpus.db databases."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS digest_state (
            section_key           TEXT PRIMARY KEY,
            last_compiled_node_id INTEGER,
            last_compiled_turn_id INTEGER,
            section_sha256        TEXT,
            updated_at            TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_digest_updated ON digest_state(updated_at);")


def ensure_ingested_artifacts_table(conn: sqlite3.Connection) -> None:
    """Create ingested_artifacts table idempotently; enforces RAW_CLAIM lock."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS ingested_artifacts (
            artifact_id      INTEGER PRIMARY KEY,
            source_path      TEXT NOT NULL,
            source_type      TEXT NOT NULL,
            source_tag       TEXT NOT NULL DEFAULT 'PROVENANCE_LOG',
            chat_id          TEXT,
            file_sha256      TEXT UNIQUE NOT NULL,
            epistemic_tier   TEXT NOT NULL DEFAULT 'RAW_CLAIM'
                             CHECK (epistemic_tier IN ('RAW_CLAIM')),
            chunk_count      INTEGER NOT NULL DEFAULT 0,
            first_chunk_id   INTEGER,
            last_chunk_id    INTEGER,
            section_key      TEXT,
            ingested_at      TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ingested_sha ON ingested_artifacts(file_sha256);")


def _classify_theme(text: str) -> str:
    lowered = text.lower()
    best_theme = "General Invariants & Cross-Domain Synthesis"
    best_hits = 0
    for theme, keywords in THEMATIC_BUCKETS:
        hits = sum(1 for kw in keywords if kw in lowered)
        if hits > best_hits:
            best_hits = hits
            best_theme = theme
    return best_theme


def classify_text_to_section_key(text: str) -> str:
    """Classify arbitrary claim or synthesis text into its canonical # KEYWORD: key."""
    return section_key_for_theme(_classify_theme(text))


def build_thematic_outline(conn: sqlite3.Connection, domain: str | None = None) -> dict[str, Any]:
    """Group all epistemic nodes, pivot chains, and edges by theme for Step 6 full-chapter recompilation."""
    if domain:
        node_rows = conn.execute("SELECT * FROM nodes WHERE domain = ? ORDER BY node_id", (domain,)).fetchall()
    else:
        node_rows = conn.execute("SELECT * FROM nodes ORDER BY node_id").fetchall()

    nodes_by_id: dict[int, dict[str, Any]] = {}
    for r in node_rows:
        n = dict(r)
        n["chunk_ids"] = [
            p["chunk_id"]
            for p in conn.execute(
                "SELECT chunk_id FROM node_provenance WHERE node_id = ? ORDER BY chunk_id",
                (n["node_id"],),
            ).fetchall()
        ]
        n["verifications"] = [
            {
                "verification_id": v["verification_id"],
                "verification_scope": v["verification_scope"],
                "external_ref": v["external_ref"],
                "benchmark_ref": v["benchmark_ref"],
                "passed": bool(v["passed"]),
            }
            for v in conn.execute(
                "SELECT * FROM node_verifications WHERE node_id = ? ORDER BY verification_id",
                (n["node_id"],),
            ).fetchall()
        ]
        nodes_by_id[n["node_id"]] = n

    edges = [dict(r) for r in conn.execute("SELECT * FROM edges ORDER BY edge_id").fetchall()]

    # Keep FALSIFIED -> pivoted_to/resolved_mistake target in the same thematic cluster as its target.
    pivot_targets: dict[int, int] = {}
    for e in edges:
        if e["relation_type"] in ("pivoted_to", "resolved_mistake") and e["to_node"] in nodes_by_id:
            pivot_targets[e["from_node"]] = e["to_node"]

    node_theme: dict[int, str] = {}
    for nid, node in nodes_by_id.items():
        if node["epistemic_tier"] == "FALSIFIED" and nid in pivot_targets:
            continue
        blob = f"{node['summary']} {node.get('dsl_expr') or ''}"
        node_theme[nid] = _classify_theme(blob)

    for nid, target_id in pivot_targets.items():
        if nid in nodes_by_id:
            node_theme[nid] = node_theme.get(
                target_id, _classify_theme(nodes_by_id[nid]["summary"])
            )

    grouped: dict[str, dict[str, Any]] = {}
    for nid, node in nodes_by_id.items():
        theme = node_theme.get(nid, "General Invariants & Cross-Domain Synthesis")
        bucket = grouped.setdefault(
            theme,
            {
                "theme": theme,
                "section_key": section_key_for_theme(theme),
                "nodes": [],
                "pivot_pairs": [],
                "internal_edges": [],
                "cross_theme_edges": [],
            },
        )
        bucket["nodes"].append(node)

    for e in edges:
        f_id, t_id = e["from_node"], e["to_node"]
        if f_id not in nodes_by_id or t_id not in nodes_by_id:
            continue
        f_theme, t_theme = node_theme[f_id], node_theme[t_id]
        if e["relation_type"] == "pivoted_to":
            grouped[t_theme]["pivot_pairs"].append(
                {"falsified_node_id": f_id, "reframed_node_id": t_id, "edge_id": e["edge_id"]}
            )
        if f_theme == t_theme:
            grouped[f_theme]["internal_edges"].append(e)
        else:
            grouped[f_theme]["cross_theme_edges"].append(
                {**e, "from_theme": f_theme, "to_theme": t_theme}
            )

    ordered_names = [
        "Symmetry, Conservation & Inertia",
        "Spacetime, Causality & Electrodynamics",
        "Quantum Information, Unitarity & Duality",
        "Scattering Geometry & S-Matrix Bootstrap",
        "Flow Networks & Cross-Domain Morphisms",
        "Axiomatic Limits, Gödel & Completeness",
        "Category Theory, Functors & Type Isomorphisms",
        "Topology, Manifolds & Cobordism",
        "Neural Architectures, Attention & Representation",
        "Cybernetics, Control Loops & Active Inference",
        "Epistemic Grounding, Alignment & Multi-Agent Systems",
        "Neurobiology, HPA Axis & Autonomic Regulation",
        "Neurodivergence, Executive Function & Cognitive Psych",
        "Pharmacokinetics, Receptor Pharmacology & Biology",
        "General Invariants & Cross-Domain Synthesis",
    ]
    themes = [grouped[name] for name in ordered_names if name in grouped]
    return {
        "total_nodes": len(nodes_by_id),
        "total_edges": len(edges),
        "themes": themes,
    }


def ensure_handoff_queue_table(conn: sqlite3.Connection) -> None:
    """Idempotently ensure the structured PR-style handoff_queue table exists."""
    conn.executescript(
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
        CREATE INDEX IF NOT EXISTS idx_handoff_status ON handoff_queue(status, updated_at);
        """
    )
    conn.commit()


def enqueue_handoff(
    conn: sqlite3.Connection,
    title: str,
    spec: str,
    constraints: str = "",
    status: str = "PENDING",
) -> dict[str, Any]:
    """Insert a structured handoff task spec into handoff_queue."""
    clean_title = (title or "").strip()
    clean_spec = (spec or "").strip()
    clean_constraints = (constraints or "").strip()
    if not clean_title:
        raise ValueError("handoff title must be non-empty")
    if not clean_spec:
        raise ValueError("handoff spec must be non-empty")
    if status not in VALID_HANDOFF_STATUSES:
        raise ValueError(f"Invalid handoff status: {status}")

    ensure_handoff_queue_table(conn)
    cur = conn.execute(
        """
        INSERT INTO handoff_queue (title, spec, constraints, status)
        VALUES (?, ?, ?, ?)
        """,
        (clean_title, clean_spec, clean_constraints, status),
    )
    task_id = int(cur.lastrowid)
    conn.commit()
    row = conn.execute("SELECT * FROM handoff_queue WHERE task_id = ?", (task_id,)).fetchone()
    return dict(row)


def update_handoff_status(
    conn: sqlite3.Connection,
    task_id: int,
    status: str,
    *,
    exit_code: int | None = None,
    sha256_diff: str | None = None,
    summary: str | None = None,
) -> dict[str, Any]:
    """Update a handoff_queue entry's lifecycle status and verification receipt fields."""
    if status not in VALID_HANDOFF_STATUSES:
        raise ValueError(f"Invalid handoff status: {status}")
    ensure_handoff_queue_table(conn)
    existing = conn.execute("SELECT * FROM handoff_queue WHERE task_id = ?", (int(task_id),)).fetchone()
    if existing is None:
        raise KeyError(f"Handoff task #{task_id} not found")

    next_exit = existing["exit_code"] if exit_code is None else int(exit_code)
    next_diff = existing["sha256_diff"] if sha256_diff is None else str(sha256_diff)
    next_summary = existing["summary"] if summary is None else str(summary)
    conn.execute(
        """
        UPDATE handoff_queue
        SET status = ?, exit_code = ?, sha256_diff = ?, summary = ?, updated_at = datetime('now')
        WHERE task_id = ?
        """,
        (status, next_exit, next_diff, next_summary, int(task_id)),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM handoff_queue WHERE task_id = ?", (int(task_id),)).fetchone()
    return dict(row)


def list_handoffs(
    conn: sqlite3.Connection,
    *,
    status: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Read-only safe listing of handoff_queue entries (optionally filtered by status)."""
    exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'handoff_queue'"
    ).fetchone()
    if not exists:
        return []
    lim = max(1, min(500, int(limit or 50)))
    if status:
        if status not in VALID_HANDOFF_STATUSES:
            raise ValueError(f"Invalid handoff status filter: {status}")
        rows = conn.execute(
            "SELECT * FROM handoff_queue WHERE status = ? ORDER BY task_id DESC LIMIT ?",
            (status, lim),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM handoff_queue ORDER BY task_id DESC LIMIT ?",
            (lim,),
        ).fetchall()
    return [dict(r) for r in rows]
