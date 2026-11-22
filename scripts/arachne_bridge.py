#!/usr/bin/env python3
"""Arachne / Portable Knowledge Graph <-> corpus.db Epistemic Bridge.

Implements Binding Protocol Rules 1-4:
  1. Dual-Index Hybrid Retrieval on Shared SQLite:
     Combines FTS5 BM25 (corpus.db chunks_fts + optional archive.db turns_fts/cas_fts)
     with dense L2-normalized TF-IDF / sqlite-vec semantic similarity via Reciprocal Rank Fusion (RRF),
     parent_turn_id DAG backtracking, and bidirectional concept_bridges query expansion (Stage 4).
  2. Tier-Gated Hydration (The Truth Filter):
     - EXTERNALLY_VERIFIED -> trusted invariant context
     - RAW_CLAIM / SIM_CONSISTENT -> marked [PROVISIONAL] with remaining max_dry_hops budget
     - FALSIFIED -> suppressed from positive evidence slices and emitted strictly as
       [NEGATIVE CONSTRAINT] paired with its resolved_mistake / pivoted_to replacement.
  3. Full Provenance Preservation:
     Retains chunk_id, source_ref, chat_id, turn_index, turn_id, parent_turn_id, sha256.
"""

from __future__ import annotations

import json
import re
import sqlite3
import sys
from pathlib import Path
from typing import Any

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer

sys.path.insert(0, str(Path(__file__).resolve().parent))
from db_utils import WORKSPACE_ROOT, estimate_tokens, fts_sanitize

CONFIG_PATH = WORKSPACE_ROOT / "corpus_config.json"

STOP_WORDS = {
    "about", "above", "after", "again", "against", "also", "although", "among",
    "and", "another", "any", "are", "because", "been", "before", "being", "between",
    "both", "but", "can", "could", "did", "does", "doing", "done", "down", "during",
    "each", "either", "enough", "even", "ever", "every", "for", "from", "further",
    "had", "has", "have", "having", "here", "how", "however", "into", "its", "just",
    "like", "many", "may", "might", "more", "most", "much", "must", "neither", "never",
    "nor", "not", "now", "only", "other", "our", "out", "over", "same", "shall",
    "should", "since", "some", "such", "than", "that", "the", "their", "them", "then",
    "there", "these", "they", "this", "those", "through", "thus", "under", "until",
    "very", "was", "were", "what", "when", "where", "whether", "which", "while",
    "who", "whom", "whose", "why", "will", "with", "within", "without", "would",
    # Conversational / archive / path / markup boilerplate tokens (Part 2 query hygiene)
    "user", "assistant", "turn", "turns", "archive", "google", "gemini", "said",
    "chunk", "chunks", "chunk_id", "cas", "conversation", "conversations", "audits",
    "recovered", "dataset", "recovered_dataset", "his", "her", "hers", "him", "she",
    "you", "your", "yours", "system", "html", "htm", "json", "jsonl", "md", "txt",
    "pdf", "docx", "csv", "sqlite", "sqlite3", "chat", "chat_id", "turn_id",
    "turn_index", "parent_turn_id", "sha256", "source_ref", "source_path",
    "exposed", "thoughts", "prompt", "response", "file", "files", "path",
    "http", "https", "www", "com", "true", "false", "none", "null",
    "raw_claim", "provenance_log", "data", "image", "base64",
}

METADATA_PATH_RE = re.compile(
    r"(?:cas:\S+|archive:[^\s|]+|data:[a-z0-9.+_-]+/[a-z0-9.+_-]+;base64,[a-z0-9+/=]+|"
    r"https?://\S+|\b[0-9a-f]{12,64}\b|(?:[A-Za-z0-9_.-]+/)+[A-Za-z0-9_.-]+|"
    r"\b[A-Za-z0-9_.-]+\.(?:md|html?|jsonl?|txt|pdf|docx|csv|sqlite3?|db)\b)",
    re.IGNORECASE,
)

DOMESTIC_NOISE_RE = re.compile(
    r"(pesto pasta|brisbane|pool heat pump|mazda|hyundai|tucson|playgrounds?|"
    r"wishing well|wedding|house material cost|scrap price|cat joint|payslips?|"
    r"lingerie|anagrams?|jaws theme song|bookshops?|venezuela invasion|"
    r"swimart|coles|woolworths|bunnings|free-to-air|hobart)",
    re.IGNORECASE,
)

ARCHIVE_REF_RE = re.compile(r"^archive:([^:]+):turn:(\d+)")


def resolve_archive_db(archive_db: Path | str | None = None) -> Path | None:
    """Resolve real non-empty archive.db path without touching CWD 0-byte stubs."""
    candidates: list[Path] = []
    if archive_db:
        candidates.append(Path(archive_db).expanduser())
    if CONFIG_PATH.exists():
        try:
            cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            if cfg.get("archive_db"):
                candidates.append(Path(cfg["archive_db"]).expanduser())
        except Exception:
            pass
    candidates.append(Path.home() / "Desktop" / "GeminiAccountArchive" / "archive.db")
    for cand in candidates:
        try:
            if cand.is_file() and cand.stat().st_size > 0:
                return cand
        except OSError:
            continue
    return None


def open_archive_ro(archive_db: Path | str | None = None) -> tuple[sqlite3.Connection | None, str | None]:
    """Open archive.db strictly read-only (?mode=ro). Returns (None, error) if sandbox-blocked."""
    path = resolve_archive_db(archive_db)
    if path is None:
        return None, "archive_db_not_found"
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5.0)
        conn.row_factory = sqlite3.Row
        conn.execute("SELECT 1 FROM sqlite_master LIMIT 1").fetchone()
        return conn, None
    except (sqlite3.OperationalError, PermissionError, OSError) as exc:
        return None, f"archive_db_unavailable: {exc}"


def parse_archive_ref(source_ref: str) -> tuple[str | None, int | None]:
    """Extract (chat_id, turn_index) from canonical 'archive:<chat_id>:turn:<idx>' strings."""
    m = ARCHIVE_REF_RE.match(source_ref or "")
    if not m:
        return None, None
    return m.group(1), int(m.group(2))


def strip_metadata_paths(text: str) -> str:
    """Remove CAS/archive URIs, file paths, base64 URIs, and hex hashes from query text."""
    if not text:
        return ""
    cleaned = METADATA_PATH_RE.sub(" ", text)
    return re.sub(r"\s+", " ", cleaned).strip()


def filter_query_text(text: str) -> str:
    """Filter path/metadata/boilerplate stopwords while preserving meaningful domain tokens."""
    stripped = strip_metadata_paths(text)
    kept: list[str] = []
    for tok in re.findall(r"[A-Za-z0-9_'-]+", stripped):
        low = tok.lower()
        if low in STOP_WORDS or low.isdigit():
            continue
        if len(low) == 1:
            continue
        kept.append(tok)
    return " ".join(kept)


def extract_query_keywords(text: str, max_terms: int = 10) -> list[str]:
    """Extract informative domain tokens for multi-concept FTS5 & bridge expansion."""
    cleaned = strip_metadata_paths(text or "")
    freq: dict[str, int] = {}
    for tok in re.findall(r"[A-Za-z][A-Za-z0-9_]{2,}", cleaned):
        low = tok.lower()
        if low in STOP_WORDS or low.isdigit():
            continue
        freq[low] = freq.get(low, 0) + 1
    ranked = sorted(freq.items(), key=lambda kv: (-kv[1], -len(kv[0]), kv[0]))
    return [k for k, _ in ranked[:max_terms]]


def _word_boundary_match(needle: str, haystack: str) -> bool:
    if not needle or len(needle) < 2:
        return False
    if len(needle) <= 3:
        return re.search(rf"(?<![a-z0-9]){re.escape(needle)}(?![a-z0-9])", haystack) is not None
    return re.search(rf"\b{re.escape(needle)}\b", haystack) is not None or (
        " " in needle and needle in haystack
    )


def _bridge_variants(side: str) -> list[str]:
    """Split slash-separated alternatives and strip parentheticals cleanly."""
    variants: list[str] = []
    seen: set[str] = set()
    for part in re.split(r"\s*(?:/|;|\band\b)\s*", side or ""):
        part = part.strip()
        if not part:
            continue
        bare = re.sub(r"\([^)]*\)", " ", part)
        bare = re.sub(r"\s+", " ", bare).strip(" :-")
        for cand in (part, bare):
            if len(cand) >= 4 and cand not in seen:
                seen.add(cand)
                variants.append(cand)
        for inner in re.findall(r"\(([^)]{2,16})\)", part):
            ic = inner.strip()
            if len(ic) >= 3 and ic not in STOP_WORDS and ic not in seen:
                seen.add(ic)
                variants.append(ic)
    if side and side not in seen:
        variants.insert(0, side)
    return variants


def expand_query_with_bridges(
    conn: sqlite3.Connection,
    query_text: str,
    archive_conn: sqlite3.Connection | None = None,
    max_bridges: int = 12,
) -> dict[str, Any]:
    """Stage 4: Bidirectional concept_bridges expansion across corpus.db + optional archive.db."""
    q_lower = (query_text or "").lower()
    raw_bridges: dict[tuple[str, str], str] = {}

    for r in conn.execute(
        "SELECT term, alias, COALESCE(structural_pattern, '') AS sp FROM concept_bridges"
    ).fetchall():
        t = str(r["term"]).strip().lower()
        a = str(r["alias"]).strip().lower()
        if t and a and t != a:
            raw_bridges[(t, a)] = str(r["sp"] or "")

    if archive_conn is not None:
        try:
            has_ab = archive_conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='concept_bridges'"
            ).fetchone()
            if has_ab:
                for r in archive_conn.execute("SELECT term, alias FROM concept_bridges").fetchall():
                    t = str(r["term"]).strip().lower()
                    a = str(r["alias"]).strip().lower()
                    if t and a and t != a and (t, a) not in raw_bridges:
                        raw_bridges[(t, a)] = "archive_concept_bridge"
        except sqlite3.Error:
            pass

    bridges_used: list[dict[str, str]] = []
    seen_pairs: set[tuple[str, str]] = set()
    expanded_phrases: list[str] = []
    seen_phrases: set[str] = set()

    # Prefer substantive structural bridges before generic pairs
    sorted_items = sorted(
        raw_bridges.items(),
        key=lambda kv: (kv[1] in ("", "imported_from_archive", "archive_concept_bridge"), -len(kv[0][0])),
    )
    for (term, alias), pattern in sorted_items:
        t_vars = _bridge_variants(term)
        a_vars = _bridge_variants(alias)
        hit_term = any(_word_boundary_match(v, q_lower) for v in t_vars)
        hit_alias = any(_word_boundary_match(v, q_lower) for v in a_vars)
        if not (hit_term or hit_alias):
            continue
        pair = (term, alias)
        if pair in seen_pairs:
            continue
        seen_pairs.add(pair)
        bridges_used.append({"term": term, "alias": alias, "structural_pattern": pattern})
        target_vars = a_vars if hit_term else t_vars
        for phrase in target_vars + t_vars[:2] + a_vars[:2]:
            if phrase and phrase not in seen_phrases:
                seen_phrases.add(phrase)
                expanded_phrases.append(phrase)
        if len(bridges_used) >= max_bridges:
            break

    base_keywords = extract_query_keywords(query_text, max_terms=8)
    for kw in base_keywords:
        if kw not in seen_phrases:
            seen_phrases.add(kw)
            expanded_phrases.append(kw)

    return {
        "base_keywords": base_keywords,
        "bridges_used": bridges_used,
        "expanded_phrases": expanded_phrases,
    }


def _cosine_scores(query_text: str, docs: list[str]) -> list[float]:
    """Compute dense L2-normalized TF-IDF cosine similarity across candidate texts."""
    if not docs or not (query_text or "").strip():
        return [0.0 for _ in docs]
    corpus = [query_text] + [d if d.strip() else "empty" for d in docs]
    try:
        vec = TfidfVectorizer(
            ngram_range=(1, 2),
            sublinear_tf=True,
            max_features=8192,
            token_pattern=r"(?u)\b[A-Za-z0-9_]{2,}\b",
        )
        mat = vec.fit_transform(corpus)
        q_vec = mat[0]
        d_mat = mat[1:]
        sims = (d_mat @ q_vec.T).toarray().ravel()
        return [float(s) for s in sims]
    except Exception:
        # Pure-NumPy fallback if vocabulary is tiny or all stop-words
        q_set = set(re.findall(r"[a-z0-9_]{2,}", query_text.lower()))
        out: list[float] = []
        for d in docs:
            d_set = set(re.findall(r"[a-z0-9_]{2,}", d.lower()))
            denom = float(np.sqrt(max(1, len(q_set) * len(d_set))))
            out.append(len(q_set & d_set) / denom if q_set and d_set else 0.0)
        return out


def _enrich_turns_metadata(
    archive_conn: sqlite3.Connection | None,
    candidates: list[dict[str, Any]],
) -> None:
    """Attach exact turn_id, parent_turn_id, next_turn_id, sha256 from archive.db.turns."""
    if archive_conn is None or not candidates:
        return
    need_lookup: list[tuple[str, int, dict[str, Any]]] = []
    for item in candidates:
        cid = item.get("chat_id")
        tidx = item.get("turn_index")
        if cid and tidx is not None and (not item.get("turn_id") or item.get("parent_turn_id") is None):
            need_lookup.append((str(cid), int(tidx), item))
    for cid, tidx, item in need_lookup:
        try:
            row = archive_conn.execute(
                """
                SELECT id, turn_id, parent_turn_id, next_turn_id, sha256
                FROM turns
                WHERE chat_id = ? AND turn_index = ?
                LIMIT 1
                """,
                (cid, tidx),
            ).fetchone()
            if row is not None:
                item["archive_turn_rowid"] = int(row["id"])
                item["turn_id"] = row["turn_id"] or f"turn:{cid}:{tidx}"
                item["parent_turn_id"] = row["parent_turn_id"] or ""
                item["next_turn_id"] = row["next_turn_id"] or ""
                if row["sha256"] and not item.get("sha256"):
                    item["sha256"] = row["sha256"]
        except sqlite3.Error:
            continue


def _build_falsified_maps(conn: sqlite3.Connection) -> dict[str, Any]:
    """Map chunk_ids, sha256s, and (chat_id, turn_index) linked to FALSIFIED nodes."""
    rows = conn.execute(
        """
        SELECT np.chunk_id, c.source_ref, c.sha256, n.node_id, n.epistemic_tier, n.domain, n.summary
        FROM node_provenance np
        JOIN nodes n ON n.node_id = np.node_id
        JOIN chunks c ON c.chunk_id = np.chunk_id
        """
    ).fetchall()

    chunk_tiers: dict[int, set[str]] = {}
    chunk_nodes: dict[int, list[int]] = {}
    ref_tiers: dict[tuple[str, int], set[str]] = {}
    sha_tiers: dict[str, set[str]] = {}

    for r in rows:
        cid = int(r["chunk_id"])
        tier = str(r["epistemic_tier"])
        nid = int(r["node_id"])
        chunk_tiers.setdefault(cid, set()).add(tier)
        chunk_nodes.setdefault(cid, []).append(nid)
        if r["sha256"]:
            sha_tiers.setdefault(str(r["sha256"]), set()).add(tier)
        chat_id, turn_idx = parse_archive_ref(str(r["source_ref"]))
        if chat_id is not None and turn_idx is not None:
            ref_tiers.setdefault((chat_id, turn_idx), set()).add(tier)

    # Identify purely falsified or falsified-tainted references
    falsified_chunks = {
        cid
        for cid, tiers in chunk_tiers.items()
        if "FALSIFIED" in tiers and "EXTERNALLY_VERIFIED" not in tiers
    }
    falsified_refs = {
        key
        for key, tiers in ref_tiers.items()
        if "FALSIFIED" in tiers and "EXTERNALLY_VERIFIED" not in tiers
    }
    falsified_shas = {
        s
        for s, tiers in sha_tiers.items()
        if "FALSIFIED" in tiers and "EXTERNALLY_VERIFIED" not in tiers
    }

    # Also build pivot replacement map for any FALSIFIED node
    pivots: dict[int, dict[str, Any]] = {}
    prow = conn.execute(
        """
        SELECT nf.node_id AS f_id, nf.domain AS f_domain, nf.summary AS f_summary, nf.dsl_expr AS f_dsl,
               nt.node_id AS t_id, nt.epistemic_tier AS t_tier, nt.summary AS t_summary, nt.dsl_expr AS t_dsl,
               e.relation_type, e.notes,
               (SELECT benchmark_ref FROM node_verifications nv WHERE nv.node_id = nt.node_id AND nv.passed = 1 ORDER BY verification_id DESC LIMIT 1) AS t_bench
        FROM nodes nf
        LEFT JOIN edges e ON e.from_node = nf.node_id AND e.relation_type IN ('pivoted_to', 'resolved_mistake')
        LEFT JOIN nodes nt ON nt.node_id = e.to_node
        WHERE nf.epistemic_tier = 'FALSIFIED'
        ORDER BY nf.node_id DESC
        """
    ).fetchall()
    for r in prow:
        fid = int(r["f_id"])
        existing = pivots.get(fid)
        if existing is None or (r["relation_type"] == "pivoted_to" and r["t_id"] is not None):
            pivots[fid] = {
                "falsified_node_id": fid,
                "domain": r["f_domain"],
                "falsified_summary": r["f_summary"],
                "falsified_dsl": r["f_dsl"],
                "relation_type": r["relation_type"],
                "pivoted_to_node_id": int(r["t_id"]) if r["t_id"] is not None else None,
                "pivoted_to_tier": r["t_tier"],
                "pivoted_to_summary": r["t_summary"],
                "pivoted_to_benchmark_ref": r["t_bench"],
                "notes": r["notes"],
            }

    return {
        "chunk_tiers": chunk_tiers,
        "chunk_nodes": chunk_nodes,
        "falsified_chunks": falsified_chunks,
        "falsified_refs": falsified_refs,
        "falsified_shas": falsified_shas,
        "pivots_by_id": pivots,
    }


def retrieve_hybrid_and_gated(
    conn: sqlite3.Connection,
    query_text: str,
    *,
    domain: str | None = None,
    archive_conn: sqlite3.Connection | None = None,
    exclude_chunk_ids: set[int] | None = None,
    top_k_chunks: int = 8,
    top_k_nodes: int = 10,
    token_budget: int = 2200,
    expand_bridges: bool = True,
    backtrack_parents: bool = True,
) -> dict[str, Any]:
    """Execute Dual-Index Hybrid Retrieval + Tier-Gated Truth Filter + Provenance Packing."""
    excl = exclude_chunk_ids or set()
    if expand_bridges:
        bridge_info = expand_query_with_bridges(conn, query_text, archive_conn=archive_conn)
    else:
        bridge_info = {
            "base_keywords": extract_query_keywords(query_text, max_terms=8),
            "bridges_used": [],
            "expanded_phrases": extract_query_keywords(query_text, max_terms=8),
        }

    search_phrases = bridge_info["expanded_phrases"][:12]
    if not search_phrases and query_text.strip():
        search_phrases = [query_text.strip()]

    f_maps = _build_falsified_maps(conn)

    # 1. Lexical FTS5 retrieval in corpus.db (chunks_fts)
    chunk_pool: dict[int, dict[str, Any]] = {}
    fts_ranked_ids: list[int] = []
    for phrase in search_phrases:
        q = fts_sanitize(phrase)
        if not q:
            continue
        try:
            rows = conn.execute(
                """
                SELECT c.chunk_id, c.source_type, c.source_ref, c.author, c.created_at,
                       c.sha256, c.content, bm25(chunks_fts) AS bm25_score
                FROM chunks_fts
                JOIN chunks c ON c.chunk_id = chunks_fts.rowid
                WHERE chunks_fts MATCH ?
                ORDER BY bm25_score
                LIMIT 18
                """,
                (q,),
            ).fetchall()
        except sqlite3.Error:
            continue
        for r in rows:
            cid = int(r["chunk_id"])
            if cid in excl:
                continue
            if DOMESTIC_NOISE_RE.search(str(r["source_ref"])) and not DOMESTIC_NOISE_RE.search(query_text):
                continue
            chat_id, turn_idx = parse_archive_ref(str(r["source_ref"]))
            if cid not in chunk_pool:
                chunk_pool[cid] = {
                    "source": "corpus_chunk",
                    "chunk_id": cid,
                    "source_type": r["source_type"],
                    "source_ref": r["source_ref"],
                    "chat_id": chat_id,
                    "turn_index": turn_idx,
                    "turn_id": None,
                    "parent_turn_id": None,
                    "sha256": r["sha256"],
                    "created_at": r["created_at"],
                    "content": r["content"],
                    "bm25_score": float(r["bm25_score"]),
                    "matched_via": [phrase],
                }
                fts_ranked_ids.append(cid)
            else:
                if phrase not in chunk_pool[cid]["matched_via"]:
                    chunk_pool[cid]["matched_via"].append(phrase)
                chunk_pool[cid]["bm25_score"] = min(chunk_pool[cid]["bm25_score"], float(r["bm25_score"]))

    # 2. Lexical FTS5 retrieval in archive.db (turns_fts + cas_fts) if accessible
    archive_pool: dict[str, dict[str, Any]] = {}
    if archive_conn is not None:
        has_turns_fts = bool(
            archive_conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='turns_fts'"
            ).fetchone()
        )
        has_cas_fts = bool(
            archive_conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='cas_fts'"
            ).fetchone()
        )
        for phrase in search_phrases[:8]:
            q = fts_sanitize(phrase)
            if not q:
                continue
            if has_turns_fts:
                try:
                    trows = archive_conn.execute(
                        """
                        SELECT t.id AS rowid_id, t.chat_id, tf.title, t.turn_index, t.turn_id,
                               t.parent_turn_id, t.next_turn_id, t.sha256, t.timestamp_hint,
                               t.user_prompt, t.model_response, bm25(turns_fts) AS bm25_score
                        FROM turns_fts tf
                        JOIN turns t ON t.id = tf.rowid
                        WHERE turns_fts MATCH ?
                        ORDER BY bm25_score
                        LIMIT 12
                        """,
                        (q,),
                    ).fetchall()
                    for r in trows:
                        title = str(r["title"] or "")
                        if DOMESTIC_NOISE_RE.search(title) and not DOMESTIC_NOISE_RE.search(query_text):
                            continue
                        key = f"turn:{r['chat_id']}:{r['turn_index']}"
                        body = f"USER: {(r['user_prompt'] or '')[:700]}\nASSISTANT: {(r['model_response'] or '')[:900]}".strip()
                        if not body:
                            continue
                        if key not in archive_pool:
                            archive_pool[key] = {
                                "source": "archive_turn",
                                "key": key,
                                "chunk_id": None,
                                "archive_turn_rowid": int(r["rowid_id"]),
                                "source_ref": f"archive:{r['chat_id']}:turn:{r['turn_index']} | {title}",
                                "chat_id": r["chat_id"],
                                "turn_index": int(r["turn_index"]),
                                "turn_id": r["turn_id"] or key,
                                "parent_turn_id": r["parent_turn_id"] or "",
                                "next_turn_id": r["next_turn_id"] or "",
                                "sha256": r["sha256"] or "",
                                "created_at": r["timestamp_hint"] or "",
                                "content": body,
                                "bm25_score": float(r["bm25_score"]),
                                "matched_via": [phrase],
                            }
                        elif phrase not in archive_pool[key]["matched_via"]:
                            archive_pool[key]["matched_via"].append(phrase)
                except sqlite3.Error:
                    pass

            if has_cas_fts:
                try:
                    crows = archive_conn.execute(
                        """
                        SELECT sha256, sample_path, ext, content_text, bm25(cas_fts) AS bm25_score
                        FROM cas_fts
                        WHERE cas_fts MATCH ?
                        ORDER BY bm25_score
                        LIMIT 6
                        """,
                        (q,),
                    ).fetchall()
                    for r in crows:
                        spath = str(r["sample_path"] or "")
                        if DOMESTIC_NOISE_RE.search(spath) and not DOMESTIC_NOISE_RE.search(query_text):
                            continue
                        sha = str(r["sha256"] or "")
                        key = f"cas:{sha or spath}"
                        if key not in archive_pool:
                            archive_pool[key] = {
                                "source": "archive_cas",
                                "key": key,
                                "chunk_id": None,
                                "source_ref": f"cas:{spath}",
                                "chat_id": None,
                                "turn_index": None,
                                "turn_id": None,
                                "parent_turn_id": None,
                                "sha256": sha,
                                "created_at": "",
                                "content": str(r["content_text"] or "")[:1200],
                                "bm25_score": float(r["bm25_score"]),
                                "matched_via": [phrase],
                            }
                except sqlite3.Error:
                    pass

    # Enrich corpus chunk archive metadata from archive.db (turn_id, parent_turn_id)
    _enrich_turns_metadata(archive_conn, list(chunk_pool.values()))

    # 3. Combine raw evidence candidates & apply Dual-Index RRF (FTS5 BM25 + Semantic Cosine)
    all_raw: list[dict[str, Any]] = list(chunk_pool.values()) + list(archive_pool.values())
    if all_raw:
        fts_sorted = sorted(range(len(all_raw)), key=lambda i: all_raw[i]["bm25_score"])
        fts_rank_map = {idx: rank + 1 for rank, idx in enumerate(fts_sorted)}
        sem_scores = _cosine_scores(
            " ".join([query_text] + bridge_info["expanded_phrases"][:4]),
            [f"{it['source_ref']} {it['content'][:1200]}" for it in all_raw],
        )
        sem_sorted = sorted(range(len(all_raw)), key=lambda i: -sem_scores[i])
        sem_rank_map = {idx: rank + 1 for rank, idx in enumerate(sem_sorted)}
        for idx, it in enumerate(all_raw):
            multi_bonus = min(0.01, 0.002 * max(0, len(it["matched_via"]) - 1))
            rrf = (1.0 / (60 + fts_rank_map[idx])) + (1.0 / (60 + sem_rank_map[idx])) + multi_bonus
            it["fts_rank"] = fts_rank_map[idx]
            it["semantic_score"] = round(sem_scores[idx], 4)
            it["rrf_score"] = round(rrf, 6)
        all_raw.sort(key=lambda x: -x["rrf_score"])

    # 4. Tier-Gated Filtering of Raw Retrieval Slices (Binding Protocol Rule 2)
    positive_slices: list[dict[str, Any]] = []
    suppressed_falsified_items: list[dict[str, Any]] = []
    tainted_falsified_node_ids: set[int] = set()

    for it in all_raw:
        cid = it.get("chunk_id")
        chat_id = it.get("chat_id")
        turn_idx = it.get("turn_index")
        sha = it.get("sha256") or ""

        is_falsified = False
        linked_nids: list[int] = []
        if cid is not None:
            linked_nids = f_maps["chunk_nodes"].get(int(cid), [])
            if int(cid) in f_maps["falsified_chunks"]:
                is_falsified = True
        if not is_falsified and chat_id and turn_idx is not None:
            if (str(chat_id), int(turn_idx)) in f_maps["falsified_refs"]:
                is_falsified = True
        if not is_falsified and sha and sha in f_maps["falsified_shas"]:
            is_falsified = True

        # Check explicit provenance link tiers for linked nodes
        tiers = []
        if cid is not None and int(cid) in f_maps["chunk_tiers"]:
            tiers = sorted(f_maps["chunk_tiers"][int(cid)])

        for nid in linked_nids:
            if nid in f_maps["pivots_by_id"]:
                tainted_falsified_node_ids.add(nid)

        if is_falsified:
            suppressed_falsified_items.append(
                {
                    "chunk_id": cid,
                    "source_ref": it["source_ref"],
                    "chat_id": chat_id,
                    "turn_index": turn_idx,
                    "turn_id": it.get("turn_id"),
                    "sha256": sha,
                    "linked_node_ids": linked_nids,
                }
            )
            continue

        it["epistemic_tiers"] = tiers if tiers else ["UNVETTED_ARCHIVE"]
        it["linked_node_ids"] = linked_nids
        positive_slices.append(it)

    # Deduplicate archive turns that already appeared as corpus chunks (keep richest)
    seen_ref_keys: set[tuple[str, int]] = set()
    seen_shas: set[str] = set()
    dedup_positive: list[dict[str, Any]] = []
    for it in positive_slices:
        rk = (str(it["chat_id"]), int(it["turn_index"])) if it.get("chat_id") and it.get("turn_index") is not None else None
        sha = it.get("sha256") or ""
        if rk and rk in seen_ref_keys:
            continue
        if sha and sha in seen_shas:
            continue
        if rk:
            seen_ref_keys.add(rk)
        if sha:
            seen_shas.add(sha)
        dedup_positive.append(it)

    selected_slices = dedup_positive[:top_k_chunks]

    # Optional Arachne-style DAG parent backtracking on top selected archive turns
    parent_context: list[dict[str, Any]] = []
    if backtrack_parents and archive_conn is not None:
        seen_parent_ids: set[str] = {str(it.get("turn_id")) for it in selected_slices if it.get("turn_id")}
        for it in selected_slices:
            if len(parent_context) >= 3:
                break
            ptid = it.get("parent_turn_id")
            cid = it.get("chat_id")
            if ptid and cid and ptid not in seen_parent_ids:
                seen_parent_ids.add(ptid)
                try:
                    prow = archive_conn.execute(
                        """
                        SELECT id, chat_id, turn_index, turn_id, parent_turn_id, sha256, user_prompt, model_response
                        FROM turns
                        WHERE chat_id = ? AND turn_id = ?
                        LIMIT 1
                        """,
                        (cid, ptid),
                    ).fetchone()
                    if prow is not None:
                        p_sha = str(prow["sha256"] or "")
                        if (str(cid), int(prow["turn_index"])) in f_maps["falsified_refs"] or (p_sha and p_sha in f_maps["falsified_shas"]):
                            continue
                        parent_context.append(
                            {
                                "source": "archive_parent_turn",
                                "chunk_id": None,
                                "source_ref": f"archive:{prow['chat_id']}:turn:{prow['turn_index']}",
                                "chat_id": prow["chat_id"],
                                "turn_index": int(prow["turn_index"]),
                                "turn_id": prow["turn_id"],
                                "parent_turn_id": prow["parent_turn_id"] or "",
                                "sha256": p_sha,
                                "content": f"PARENT USER: {(prow['user_prompt'] or '')[:350]}\nPARENT ASSISTANT: {(prow['model_response'] or '')[:450]}".strip(),
                            }
                        )
                except sqlite3.Error:
                    pass

    # 5. Semantic + Lexical Epistemic Node Retrieval (2-hop + Tier Filter)
    node_rows = conn.execute(
        """
        SELECT n.node_id, n.domain, n.summary, n.dsl_expr, n.epistemic_tier,
               (SELECT benchmark_ref FROM node_verifications nv WHERE nv.node_id = n.node_id AND nv.passed = 1 ORDER BY verification_id DESC LIMIT 1) AS benchmark_ref,
               (SELECT external_ref FROM node_verifications nv WHERE nv.node_id = n.node_id ORDER BY verification_id DESC LIMIT 1) AS external_ref
        FROM nodes n
        ORDER BY n.node_id
        """
    ).fetchall()

    verified_invariants: list[dict[str, Any]] = []
    provisional_claims: list[dict[str, Any]] = []
    matched_falsified_ids: set[int] = set(tainted_falsified_node_ids)

    if node_rows:
        node_texts = [f"{r['domain']} {r['summary']} {r['dsl_expr'] or ''} {r['benchmark_ref'] or ''}" for r in node_rows]
        q_sem = " ".join([query_text] + bridge_info["expanded_phrases"][:6])
        n_cos = _cosine_scores(q_sem, node_texts)
        kw_set = set(re.findall(r"[a-z0-9_]{3,}", q_sem.lower()))

        scored_nodes: list[tuple[float, sqlite3.Row]] = []
        for idx, r in enumerate(node_rows):
            txt_low = node_texts[idx].lower()
            lex_hits = sum(1 for kw in kw_set if kw in txt_low)
            dom_bonus = 0.08 if domain and r["domain"] == domain else 0.0
            score = n_cos[idx] * 2.0 + min(0.6, lex_hits * 0.08) + dom_bonus
            if score > 0.04:
                scored_nodes.append((score, r))
        scored_nodes.sort(key=lambda x: -x[0])

        # Expand 1-hop supports/pivoted_to neighbors of top seeds
        seed_ids = {int(r["node_id"]) for _, r in scored_nodes[:top_k_nodes]}
        expanded_ids = set(seed_ids)
        if seed_ids:
            ph = ",".join("?" for _ in seed_ids)
            for er in conn.execute(
                f"SELECT from_node, to_node, relation_type FROM edges WHERE from_node IN ({ph}) OR to_node IN ({ph})",
                list(seed_ids) * 2,
            ).fetchall():
                expanded_ids.add(int(er["from_node"]))
                expanded_ids.add(int(er["to_node"]))

        score_by_id = {int(r["node_id"]): sc for sc, r in scored_nodes}
        row_by_id = {int(r["node_id"]): r for r in node_rows}

        for nid in expanded_ids:
            r = row_by_id.get(nid)
            if r is None:
                continue
            tier = str(r["epistemic_tier"])
            sc = score_by_id.get(nid, 0.1)
            if tier == "FALSIFIED":
                matched_falsified_ids.add(nid)
            elif tier == "EXTERNALLY_VERIFIED":
                verified_invariants.append(
                    {
                        "node_id": nid,
                        "domain": r["domain"],
                        "epistemic_tier": tier,
                        "summary": r["summary"],
                        "dsl_expr": r["dsl_expr"],
                        "benchmark_ref": r["benchmark_ref"],
                        "external_ref": r["external_ref"],
                        "score": round(sc, 4),
                    }
                )
            else:
                # RAW_CLAIM / DSL_CONSISTENT / SIM_CONSISTENT
                provisional_claims.append(
                    {
                        "node_id": nid,
                        "domain": r["domain"],
                        "epistemic_tier": tier,
                        "summary": r["summary"],
                        "dsl_expr": r["dsl_expr"],
                        "score": round(sc, 4),
                    }
                )

        verified_invariants.sort(key=lambda x: -x["score"])
        provisional_claims.sort(key=lambda x: -x["score"])

    # Attach provenance chunk_ids to selected verified invariants
    for v in verified_invariants[:top_k_nodes]:
        cids = [
            int(pr["chunk_id"])
            for pr in conn.execute(
                "SELECT chunk_id FROM node_provenance WHERE node_id = ? ORDER BY chunk_id LIMIT 5",
                (v["node_id"],),
            ).fetchall()
        ]
        v["chunk_ids"] = cids

    # Build negative constraints from matched FALSIFIED nodes (never injected as positive truth)
    falsified_constraints = [
        f_maps["pivots_by_id"][fid]
        for fid in sorted(matched_falsified_ids)
        if fid in f_maps["pivots_by_id"]
    ][:top_k_nodes]

    # Active research_branches & remaining max_dry_hops budget
    branch_query = """
        SELECT b.branch_id, b.root_node_id, b.agent_role, b.total_hops, b.hops_since_novelty,
               b.max_dry_hops, b.status, n.domain, n.epistemic_tier, substr(n.summary, 1, 140) AS summary
        FROM research_branches b
        JOIN nodes n ON n.node_id = b.root_node_id
        WHERE b.status = 'ACTIVE'
    """
    params: list[Any] = []
    if domain:
        branch_query += " AND n.domain = ?"
        params.append(domain)
    branch_query += " ORDER BY b.branch_id DESC LIMIT 20"
    active_branches = []
    for br in conn.execute(branch_query, params).fetchall():
        d = dict(br)
        d["remaining_dry_hops"] = max(0, int(d["max_dry_hops"]) - int(d["hops_since_novelty"]))
        active_branches.append(d)

    packet = {
        "bridges_used": bridge_info["bridges_used"],
        "expanded_phrases": search_phrases,
        "verified_invariants": verified_invariants[:top_k_nodes],
        "provisional_claims": provisional_claims[:8],
        "active_branches": active_branches,
        "falsified_constraints": falsified_constraints,
        "suppressed_falsified_raw_hits": suppressed_falsified_items,
        "dynamic_slices": selected_slices,
        "parent_dag_backtrack": parent_context,
        "token_budget": token_budget,
    }
    packet["rendered_markdown"] = render_hydrated_packet_md(packet, token_budget=token_budget)
    packet["estimated_tokens"] = estimate_tokens(packet["rendered_markdown"])
    return packet


def render_hydrated_packet_md(packet: dict[str, Any], token_budget: int = 2200) -> str:
    """Format tiered working-memory packet concisely while honoring a strict token budget."""
    sections: list[str] = []

    if packet.get("bridges_used"):
        b_lines = ["**Vocabulary-Drift Bridges Expanded (Stage 4):**"]
        for b in packet["bridges_used"][:8]:
            pat = f" [{b['structural_pattern']}]" if b.get("structural_pattern") else ""
            b_lines.append(f"- `{b['term']}` <-> `{b['alias']}`{pat}")
        sections.append("\n".join(b_lines))

    if packet.get("active_branches"):
        br_lines = ["**Active Research Branches & Halting Budgets (`max_dry_hops = 3`):**"]
        for b in packet["active_branches"][:8]:
            br_lines.append(
                f"- Branch #{b['branch_id']} (root `#{b['root_node_id']}` [{b['epistemic_tier']}], "
                f"role=`{b['agent_role']}`, hops={b['total_hops']}, dry={b['hops_since_novelty']}/{b['max_dry_hops']}, "
                f"remaining={b['remaining_dry_hops']}): {b['summary']}"
            )
        sections.append("\n".join(br_lines))

    if packet.get("falsified_constraints"):
        f_lines = ["**[NEGATIVE CONSTRAINTS — FALSIFIED -> PIVOTED_TO] (DO NOT RE-EXPLORE):**"]
        for fc in packet["falsified_constraints"][:8]:
            pid = fc.get("pivoted_to_node_id")
            rep = fc.get("pivoted_to_summary") or fc.get("notes") or "See verified pivot."
            f_lines.append(
                f"- [FALSIFIED `#{fc['falsified_node_id']}`]: {fc['falsified_summary'][:160]} "
                f"=> **PIVOTED TO `#{pid}`**: {rep[:180]}"
            )
        sections.append("\n".join(f_lines))

    if packet.get("verified_invariants"):
        v_lines = ["**[TRUSTED INVARIANTS — EXTERNALLY_VERIFIED]:**"]
        for v in packet["verified_invariants"][:8]:
            cids = ",".join(str(x) for x in v.get("chunk_ids", []))
            ref = v.get("benchmark_ref") or v.get("external_ref") or ""
            v_lines.append(
                f"- [`#{v['node_id']}` | `{v['domain']}` | chunks:{cids}] {v['summary'][:190]} "
                f"(ref: {ref[:90]})"
            )
        sections.append("\n".join(v_lines))

    if packet.get("provisional_claims"):
        p_lines = ["**[PROVISIONAL — RAW_CLAIM / SIM_CONSISTENT]:**"]
        for p in packet["provisional_claims"][:5]:
            p_lines.append(f"- [`#{p['node_id']}` | {p['epistemic_tier']}] {p['summary'][:170]}")
        sections.append("\n".join(p_lines))

    if packet.get("dynamic_slices") or packet.get("parent_dag_backtrack"):
        s_lines = ["**Dynamic Hybrid Slice (FTS5 + Semantic RRF, Tier-Filtered Provenance):**"]
        for sl in list(packet.get("dynamic_slices", [])) + list(packet.get("parent_dag_backtrack", [])):
            meta_parts = []
            if sl.get("chunk_id") is not None:
                meta_parts.append(f"chunk_id={sl['chunk_id']}")
            if sl.get("chat_id"):
                meta_parts.append(f"chat_id={sl['chat_id']}")
            if sl.get("turn_index") is not None:
                meta_parts.append(f"turn_index={sl['turn_index']}")
            if sl.get("turn_id"):
                meta_parts.append(f"turn_id={sl['turn_id']}")
            if sl.get("parent_turn_id") is not None and sl.get("parent_turn_id") != "":
                meta_parts.append(f"parent_turn_id={sl['parent_turn_id']}")
            if sl.get("sha256"):
                meta_parts.append(f"sha256={sl['sha256'][:12]}")
            meta_str = " | ".join(meta_parts)
            snip = re.sub(r"\s+", " ", str(sl.get("content", "")))[:240]
            s_lines.append(f"- [{sl['source']} | {meta_str}]: {snip}")
        sections.append("\n".join(s_lines))

    # Pack sequentially under strict token_budget
    out_parts: list[str] = ["=== HYDRATED WORKING-MEMORY PACKET (ARACHNE RECALL x CORPUS TRUTH GATE) ==="]
    used_tok = estimate_tokens(out_parts[0])
    for sec in sections:
        sec_tok = estimate_tokens(sec)
        if used_tok + sec_tok + 2 <= token_budget:
            out_parts.append(sec)
            used_tok += sec_tok + 2
        else:
            # Trim line-by-line within budget
            kept: list[str] = []
            for line in sec.splitlines():
                ltok = estimate_tokens(line)
                if used_tok + ltok + 1 > token_budget:
                    break
                kept.append(line)
                used_tok += ltok + 1
            if len(kept) > 1:
                out_parts.append("\n".join(kept))
            break
    return "\n\n".join(out_parts)
