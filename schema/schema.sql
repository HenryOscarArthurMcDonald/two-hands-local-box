-- Epistemic Corpus & Physics Pilot Schema
-- Based on Stage 0 + Epistemic Tiering (with SIM_CONSISTENT vs EXTERNALLY_VERIFIED) + Anti-Spin Halting.

PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

-- 1. Normalized raw corpus (Stage 0 output)
CREATE TABLE IF NOT EXISTS chunks (
    chunk_id     INTEGER PRIMARY KEY,
    source_type  TEXT NOT NULL,          -- 'chat_db', 'pdf', 'docx', 'md', 'txt', 'json', 'html', 'csv'
    source_ref   TEXT NOT NULL,          -- original file path or conversation_id
    author       TEXT,                   -- 'user', 'assistant', or external author
    created_at   TEXT,                   -- ISO-8601 timestamp if known
    sha256       TEXT UNIQUE NOT NULL,   -- deduplication key
    content      TEXT NOT NULL
);

CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
    content,
    content='chunks',
    content_rowid='chunk_id'
);

-- 2. Scoped writing slices (e.g. 'physics_pilot' tags 500-1000 chunks while chunks_fts stays global)
CREATE TABLE IF NOT EXISTS chapter_slices (
    slice_name   TEXT NOT NULL,
    chunk_id     INTEGER NOT NULL REFERENCES chunks(chunk_id) ON DELETE CASCADE,
    relevance    REAL DEFAULT 0.0,
    status       TEXT NOT NULL DEFAULT 'PENDING'
                 CHECK (status IN ('PENDING', 'PROCESSED', 'SKIPPED')),
    skip_reason  TEXT,                -- 'debug_churn', 'boilerplate', 'duplicate_export', etc.
    PRIMARY KEY (slice_name, chunk_id)
);

-- 3. Extracted claims, invariants, and hypotheses
CREATE TABLE IF NOT EXISTS nodes (
    node_id         INTEGER PRIMARY KEY,
    domain          TEXT NOT NULL,       -- 'physics', 'info_theory', 'psychology', 'systems', etc.
    dsl_expr        TEXT,                -- formal/logical syntax or relational schema representation
    summary         TEXT NOT NULL,       -- human-readable statement
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

-- 4. Hard provenance: every node must trace back to exact corpus chunks
CREATE TABLE IF NOT EXISTS node_provenance (
    node_id     INTEGER NOT NULL REFERENCES nodes(node_id) ON DELETE CASCADE,
    chunk_id    INTEGER NOT NULL REFERENCES chunks(chunk_id) ON DELETE CASCADE,
    quote_span  TEXT,                    -- exact substring supporting the node
    PRIMARY KEY (node_id, chunk_id)
);

-- 5. Single-node verifications (keeps self-loops out of edges)
CREATE TABLE IF NOT EXISTS node_verifications (
    verification_id    INTEGER PRIMARY KEY,
    node_id            INTEGER NOT NULL REFERENCES nodes(node_id) ON DELETE CASCADE,
    verifier_type      TEXT NOT NULL
                       CHECK (verifier_type IN (
                           'python_sim',
                           'lean_coq',
                           'public_record',
                           'literature_ref',
                           'llm_only'
                       )),
    verification_scope TEXT NOT NULL
                       CHECK (verification_scope IN (
                           'toy_model',
                           'standard_physics_law',
                           'empirical_benchmark',
                           'primary_record',
                           'literature_citation',
                           'llm_only'
                       )),
    external_ref       TEXT,             -- pycheck:<sha256>, URL, or primary citation
    benchmark_ref      TEXT,             -- independent law, equation, or dataset checked against
    passed             INTEGER NOT NULL CHECK (passed IN (0, 1)),
    notes              TEXT,
    created_at         TEXT NOT NULL DEFAULT (datetime('now'))
);

-- 6. Directed inter-node relations (no self-loops allowed)
CREATE TABLE IF NOT EXISTS edges (
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
                       'challenges_falsification',
                       'splits_from'
                   )),
    verifier_type  TEXT NOT NULL DEFAULT 'llm_only'
                   CHECK (verifier_type IN (
                       'python_sim',
                       'lean_coq',
                       'public_record',
                       'literature_ref',
                       'llm_only'
                   )),
    external_ref   TEXT,                 -- URL, pycheck:<sha256>, or primary citation
    notes          TEXT,
    created_at     TEXT NOT NULL DEFAULT (datetime('now')),
    CHECK (from_node != to_node)
);

-- 7. Swarm halting budget (prevents tail-eating loops)
CREATE TABLE IF NOT EXISTS research_branches (
    branch_id          INTEGER PRIMARY KEY,
    root_node_id       INTEGER NOT NULL REFERENCES nodes(node_id) ON DELETE CASCADE,
    agent_role         TEXT NOT NULL
                       CHECK (agent_role IN ('historian', 'scientist', 'falsifier', 'synthesizer')),
    total_hops         INTEGER NOT NULL DEFAULT 0,
    hops_since_novelty INTEGER NOT NULL DEFAULT 0,
    max_dry_hops       INTEGER NOT NULL DEFAULT 3,
    status             TEXT NOT NULL DEFAULT 'ACTIVE'
                       CHECK (status IN ('ACTIVE', 'HALTED_NOVELTY', 'CONVERGED')),
    updated_at         TEXT NOT NULL DEFAULT (datetime('now'))
);

-- 8. Cross-domain vocabulary bridge (zero-cost query expansion)
CREATE TABLE IF NOT EXISTS concept_bridges (
    term               TEXT NOT NULL,
    alias              TEXT NOT NULL,
    structural_pattern TEXT,
    PRIMARY KEY (term, alias)
);

-- 9. Delta-compiled structured digest momentum watermarks
CREATE TABLE IF NOT EXISTS digest_state (
    section_key           TEXT PRIMARY KEY,
    last_compiled_node_id INTEGER,
    last_compiled_turn_id INTEGER,
    section_sha256        TEXT,
    updated_at            TEXT NOT NULL DEFAULT (datetime('now'))
);

-- 10. Idempotent provenance ledger for newly ingested session logs & artifacts
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
);

-- 11. Non-destructive epistemic audit flags (F2.2 provisional re-tiering & F2.3 atomic-split queue)
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

-- 12. Database-level verifier-type / scope coupling lock (F2.2: closes pycheck literature bypass)
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

-- 13. Structured PR-style handoff queue (replaces ad-hoc pasted prompts across sessions)
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

CREATE INDEX IF NOT EXISTS idx_slices_status ON chapter_slices(slice_name, status);
CREATE INDEX IF NOT EXISTS idx_nodes_tier ON nodes(epistemic_tier);
CREATE INDEX IF NOT EXISTS idx_verif_node ON node_verifications(node_id);
CREATE INDEX IF NOT EXISTS idx_edges_from ON edges(from_node);
CREATE INDEX IF NOT EXISTS idx_edges_to ON edges(to_node);
CREATE INDEX IF NOT EXISTS idx_branches_status ON research_branches(status);
CREATE INDEX IF NOT EXISTS idx_digest_updated ON digest_state(updated_at);
CREATE INDEX IF NOT EXISTS idx_ingested_sha ON ingested_artifacts(file_sha256);
CREATE INDEX IF NOT EXISTS idx_audit_flags_type ON node_audit_flags(flag_type, resolved);
CREATE INDEX IF NOT EXISTS idx_handoff_status ON handoff_queue(status, updated_at);
