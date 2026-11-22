"""Stage 0 deterministic ingestion & single-discipline Physics slice builder ($0 cost)."""

from __future__ import annotations

import argparse
import csv
import hashlib
import html.parser
import json
import os
import re
import sqlite3
import subprocess
import sys
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from typing import Iterable

sys.path.insert(0, str(Path(__file__).resolve().parent))
from db_utils import DEFAULT_DB_PATH, WORKSPACE_ROOT, get_connection, init_db

DEFAULT_RAW_DIR = WORKSPACE_ROOT / "raw_corpus"
CONFIG_PATH = WORKSPACE_ROOT / "corpus_config.json"

PHYSICS_SLICE_QUERY = (
    'photon OR refraction OR "speed of light" OR thermodynamic OR entropy OR '
    "conservation OR momentum OR relativity OR quantum OR causality OR "
    'hydrodynamic OR resonance OR superposition OR "wave packet" OR noether'
)

LEAN4_FORMAL_SLICE_QUERY = (
    'isomorphism OR functor OR morphism OR theorem OR axiom OR "curry howard" OR '
    'godel OR incompleteness OR topology OR manifold OR symmetry OR gauge OR '
    'lagrangian OR hamiltonian OR entropy OR "information theory" OR "category theory"'
)

AI_SYSTEMS_SLICE_QUERY = (
    'transformer OR attention OR gradient OR "free energy" OR bayesian OR kalman OR '
    'cybernetic OR "feedback loop" OR "stateless forward pass" OR "mutual information" OR '
    'backprop OR attractor OR isomorphism OR invariant'
)

BIO_NEURO_PSYCH_SLICE_QUERY = (
    'dopamine OR serotonin OR pda OR autism OR autistic OR neurodivergent OR '
    'adhd OR amygdala OR prefrontal OR hippocampus OR synapse OR synaptic OR '
    'cortisol OR circadian OR autonomic OR vagus OR homeostasis OR interoception OR '
    'evolution OR biology OR genetic OR dna OR neural OR cognition OR trauma OR anxiety OR '
    'pharmacokinetic OR pharmacology OR receptor OR neurotransmitter'
)

PHILOSOPHY_EPISTEMOLOGY_SLICE_QUERY = (
    'epistemology OR phenomenology OR metaphysics OR consciousness OR qualia OR '
    'hermeneutic OR ontology OR ethics OR "free will" OR determinism OR empiricism OR '
    'skepticism OR kant OR spinoza OR nietzsche OR wittgenstein OR buddhism OR stoic'
)

SLICE_QUERIES = {
    "physics_pilot": PHYSICS_SLICE_QUERY,
    "lean4_formal": LEAN4_FORMAL_SLICE_QUERY,
    "ai_systems": AI_SYSTEMS_SLICE_QUERY,
    "bio_neuro_psych": BIO_NEURO_PSYCH_SLICE_QUERY,
    "philosophy_epistemology": PHILOSOPHY_EPISTEMOLOGY_SLICE_QUERY,
}

DOMESTIC_NOISE_RE = re.compile(
    r"(pesto pasta|brisbane|pool heat pump|mazda|hyundai|tucson|playgrounds?|"
    r"wishing well|wedding|house material cost|scrap price|cat joint|payslips?|"
    r"lingerie|anagrams?|jaws theme song|bookshops?|venezuela invasion|"
    r"swimart|coles|woolworths|bunnings|free-to-air|hobart)",
    re.IGNORECASE,
)

DEBUG_CHURN_RE = re.compile(
    r"(Traceback \(most recent call last\):|SyntaxError:|ModuleNotFoundError:|"
    r"IndentationError:|Command exited with code [1-9]|npm ERR!|Last login: \w{3} \w{3}\s+\d+|"
    r"Fixing Python Environment Errors|Fixing Codex Access Token Error|"
    r"Quota exceeded for metric:|"
    r"error: unsolved goals|error: type mismatch|error: unknown identifier)",
    re.IGNORECASE,
)
BOILERPLATE_RE = re.compile(
    r"(lean_proofs/macro_|Levi_Voyager_v|Levi copy \d+\.app|crawler_task_log|"
    r"desktop_app/previous_apps/|agent_capsules/runs/|interactive_hypergraph/runs/|"
    r"intake_drop/original_files/|^\s*<Elicitation\s|"
    r"levi_epistemic_seed_v|\"kind\":\s*\"primitive\"|\"code_template\":\s*\"# Level|"
    r"\"formal_witness\":\s*\"|\"tactic_signature\":|\"TACTIC-CONSERVE\"|"
    r"MACRO-\d+\s*(?:⊗|\*)\s*MACRO-\d+|\"state\":\s*\"completed\",\s*\n\s*\"created_at\":|"
    r"Anchor Hold Reinforced:\s*\[MACRO-|📊\s*Progress:\s*\d+\s*/\s*\d+\s*convs|"
    r"Lean 4: Exported specification to macro_|^\s*# Bounded active inquiry\s*\n\s*State:\s*needs_review|"
    r"^\[(?:MICRO-INSIGHT|HYPOTHESIS|PROCESS)\]\s*\{|"
    r"# GeminiScraper — start here|Dialogue Trajectory Seed Invariant|"
    r"Complete macOS Gemini Account Archiver|"
    r"Recovered canonical RPC text; original archive preserved\.\s*$)",
    re.IGNORECASE,
)


def detect_noise_skip_reason(source_ref: str, content: str) -> str | None:
    """Return a concise skip_reason ('debug_churn', 'boilerplate', 'duplicate_export') if chunk is pure noise."""
    if BOILERPLATE_RE.search(source_ref) or BOILERPLATE_RE.search(content):
        return "boilerplate"
    if DEBUG_CHURN_RE.search(source_ref) or DEBUG_CHURN_RE.search(content):
        return "debug_churn"
    return None


def load_corpus_config() -> dict[str, str]:
    if CONFIG_PATH.exists():
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    return {}


class _HTMLTextExtractor(html.parser.HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._skip_depth = 0
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in ("script", "style", "noscript"):
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in ("script", "style", "noscript") and self._skip_depth > 0:
            self._skip_depth -= 1
        elif tag.lower() in ("p", "div", "br", "li", "h1", "h2", "h3", "h4", "tr"):
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0:
            self._parts.append(data)

    def get_text(self) -> str:
        return "".join(self._parts)


def normalize_whitespace(text: str) -> str:
    lines = [line.strip() for line in text.replace("\r\n", "\n").split("\n")]
    cleaned = "\n".join(line for line in lines if line)
    return re.sub(r"\n{3,}", "\n\n", cleaned).strip()


def chunk_text(text: str, max_chars: int = 1800) -> list[str]:
    """Split text along paragraph boundaries up to max_chars per chunk."""
    cleaned = normalize_whitespace(text)
    if not cleaned:
        return []
    paragraphs = cleaned.split("\n")
    chunks: list[str] = []
    buf: list[str] = []
    buf_len = 0
    for para in paragraphs:
        if len(para) > max_chars:
            if buf:
                chunks.append("\n".join(buf))
                buf, buf_len = [], 0
            for i in range(0, len(para), max_chars):
                chunks.append(para[i : i + max_chars])
            continue
        if buf_len + len(para) + 1 > max_chars and buf:
            chunks.append("\n".join(buf))
            buf, buf_len = [], 0
        buf.append(para)
        buf_len += len(para) + 1
    if buf:
        chunks.append("\n".join(buf))
    return chunks


def extract_docx_text(path: Path) -> str:
    with zipfile.ZipFile(path) as zf:
        if "word/document.xml" not in zf.namelist():
            return ""
        xml_bytes = zf.read("word/document.xml")
    root = ET.fromstring(xml_bytes)
    paragraphs: list[str] = []
    for p in root.iter():
        if p.tag.endswith("}p"):
            texts = [t.text for t in p.iter() if t.tag.endswith("}t") and t.text]
            if texts:
                paragraphs.append("".join(texts))
    return "\n".join(paragraphs)


def extract_pdf_text(path: Path) -> str:
    for cmd in (
        ["pdftotext", "-layout", str(path), "-"],
        [
            "swift",
            "-e",
            (
                "import PDFKit; import Foundation; "
                "let u = URL(fileURLWithPath: CommandLine.arguments[1]); "
                "if let d = PDFDocument(url: u) { "
                "for i in 0..<d.pageCount { if let s = d.page(at: i)?.string { print(s) } } }"
            ),
            str(path),
        ],
    ):
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            if proc.returncode == 0 and proc.stdout.strip():
                return proc.stdout
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue
    return ""


def extract_textutil_text(path: Path) -> str:
    try:
        proc = subprocess.run(
            ["textutil", "-convert", "txt", "-stdout", str(path)],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if proc.returncode == 0:
            return proc.stdout
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return ""


def iter_json_records(data: object, source_ref: str) -> Iterable[tuple[str | None, str | None, str]]:
    """Yield (author, created_at, content) tuples from common chat/note JSON shapes."""
    if isinstance(data, list):
        for item in data:
            yield from iter_json_records(item, source_ref)
    elif isinstance(data, dict):
        if "content" in data and isinstance(data["content"], str):
            author = str(data.get("author") or data.get("role") or "unknown")
            created = data.get("created_at") or data.get("timestamp")
            yield (author, str(created) if created else None, data["content"])
        elif "text" in data and isinstance(data["text"], str):
            author = str(data.get("author") or data.get("role") or "unknown")
            created = data.get("created_at") or data.get("timestamp")
            yield (author, str(created) if created else None, data["text"])
        elif "messages" in data and isinstance(data["messages"], list):
            yield from iter_json_records(data["messages"], source_ref)
        elif "turns" in data and isinstance(data["turns"], list):
            yield from iter_json_records(data["turns"], source_ref)
        elif "mapping" in data and isinstance(data["mapping"], dict):
            for node in data["mapping"].values():
                msg = (node or {}).get("message") if isinstance(node, dict) else None
                if isinstance(msg, dict):
                    role = (msg.get("author") or {}).get("role", "unknown")
                    parts = (msg.get("content") or {}).get("parts") or []
                    text = "\n".join(str(p) for p in parts if isinstance(p, str))
                    if text.strip():
                        yield (str(role), str(msg.get("create_time") or "") or None, text)
        else:
            dumped = json.dumps(data, ensure_ascii=False, indent=2)
            yield (None, None, dumped)


def inspect_sqlite_db(db_file: Path) -> dict[str, list[dict[str, str]]]:
    """Return table -> columns summary for any SQLite database."""
    conn = sqlite3.connect(f"file:{db_file}?mode=ro", uri=True)
    try:
        tables = [
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            ).fetchall()
        ]
        layout: dict[str, list[dict[str, str]]] = {}
        for t in tables:
            cols = conn.execute(f'PRAGMA table_info("{t}")').fetchall()
            layout[t] = [{"name": c[1], "type": c[2]} for c in cols]
        return layout
    finally:
        conn.close()


def insert_chunk(
    conn: sqlite3.Connection,
    source_type: str,
    source_ref: str,
    author: str | None,
    created_at: str | None,
    content: str,
) -> bool:
    norm = normalize_whitespace(content)
    if len(norm) < 10:
        return False
    digest = hashlib.sha256(norm.encode("utf-8")).hexdigest()
    cur = conn.execute(
        """
        INSERT OR IGNORE INTO chunks (source_type, source_ref, author, created_at, sha256, content)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (source_type, source_ref, author, created_at, digest, norm),
    )
    return cur.rowcount > 0


def ingest_gemini_archive_db(db_file: Path, target_conn: sqlite3.Connection) -> tuple[int, int, int]:
    """Ingest GeminiAccountArchive/archive.db read-only (turns, cas_fts, concept_bridges)."""
    src = sqlite3.connect(f"file:{db_file}?mode=ro", uri=True)
    src.row_factory = sqlite3.Row
    inserted = 0
    skipped = 0
    bridges_added = 0
    try:
        # 1. Conversations + turns (clean text, avoiding user_html/model_html duplicates)
        rows = src.execute(
            """
            SELECT t.chat_id, COALESCE(c.title, '') AS title, t.turn_index,
                   t.user_prompt, t.model_response, t.timestamp_hint
            FROM turns t
            LEFT JOIN conversations c ON c.chat_id = t.chat_id
            ORDER BY t.chat_id, t.turn_index
            """
        )
        for r in rows:
            title = r["title"].strip()
            sref = f"archive:{r['chat_id']}:turn:{r['turn_index']}" + (f" | {title}" if title else "")
            ts = r["timestamp_hint"]
            for author, body in (("user", r["user_prompt"]), ("assistant", r["model_response"])):
                if body and str(body).strip():
                    for chunk in chunk_text(str(body)):
                        if insert_chunk(target_conn, "chat_db", sref, author, ts, chunk):
                            inserted += 1
                        else:
                            skipped += 1

        # 2. CAS extracted text documents (cas_fts)
        tables = {
            row[0]
            for row in src.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        if "cas_fts" in tables:
            for r in src.execute("SELECT sample_path, ext, content_text FROM cas_fts"):
                content = r["content_text"]
                if not content or not str(content).strip():
                    continue
                ext = (r["ext"] or "").lstrip(".") or "txt"
                sref = f"cas:{r['sample_path']}"
                for chunk in chunk_text(str(content)):
                    if insert_chunk(target_conn, ext, sref, None, None, chunk):
                        inserted += 1
                    else:
                        skipped += 1

        # 3. Existing cross-domain concept bridges
        if "concept_bridges" in tables:
            for r in src.execute("SELECT term, alias FROM concept_bridges"):
                cur = target_conn.execute(
                    "INSERT OR IGNORE INTO concept_bridges (term, alias, structural_pattern) VALUES (?, ?, ?)",
                    (str(r["term"]).strip().lower(), str(r["alias"]).strip().lower(), "imported_from_archive"),
                )
                bridges_added += cur.rowcount
    finally:
        src.close()
    return inserted, skipped, bridges_added


def iter_generic_sqlite_chunks(db_file: Path) -> Iterable[tuple[str, str | None, str | None, str]]:
    """Fallback extractor for arbitrary SQLite DBs without the archive.db schema."""
    conn = sqlite3.connect(f"file:{db_file}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        tables = [
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%' AND name NOT LIKE '%_fts%'"
            ).fetchall()
        ]
        for table in tables:
            cols = [c[1] for c in conn.execute(f'PRAGMA table_info("{table}")').fetchall()]
            if not cols:
                continue
            author_col = next((c for c in cols if c.lower() in ("author", "role", "sender", "speaker")), None)
            time_col = next(
                (c for c in cols if c.lower() in ("created_at", "timestamp", "created", "date", "time")), None
            )
            conv_col = next(
                (c for c in cols if c.lower() in ("conversation_id", "thread_id", "chat_id", "session_id")), None
            )
            text_cols = [
                c
                for c in cols
                if c.lower()
                in ("content", "text", "message", "body", "prompt", "response", "summary", "notes", "transcript")
            ]
            if not text_cols:
                text_cols = [c for c in cols if c not in (author_col, time_col, conv_col) and not c.endswith("_id")]

            for row in conn.execute(f'SELECT rowid, * FROM "{table}"'):
                parts = [
                    str(row[c]).strip()
                    for c in text_cols
                    if row[c] is not None and isinstance(row[c], str) and len(str(row[c]).strip()) >= 12
                ]
                if not parts:
                    continue
                author = str(row[author_col]) if author_col and row[author_col] is not None else None
                created = str(row[time_col]) if time_col and row[time_col] is not None else None
                ref_suffix = str(row[conv_col]) if conv_col and row[conv_col] is not None else f"row:{row['rowid']}"
                source_ref = f"{db_file.name}:{table}:{ref_suffix}"
                for chunk in chunk_text("\n\n".join(parts)):
                    yield (source_ref, author, created, chunk)
    finally:
        conn.close()


def is_gemini_archive_db(db_file: Path) -> bool:
    conn = sqlite3.connect(f"file:{db_file}?mode=ro", uri=True)
    try:
        tables = {
            r[0]
            for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        return {"conversations", "turns"}.issubset(tables)
    finally:
        conn.close()


def ingest_path(input_path: Path, db_path: Path) -> dict[str, int]:
    """Ingest a file or directory into db_path and rebuild FTS5."""
    init_db(db_path)
    conn = get_connection(db_path)
    stats = {"files_seen": 0, "chunks_inserted": 0, "duplicates_skipped": 0, "bridges_imported": 0}
    files = [input_path] if input_path.is_file() else sorted(p for p in input_path.rglob("*") if p.is_file())

    try:
        for file_path in files:
            if file_path.name.startswith(".") or file_path.resolve() == db_path.resolve():
                continue
            ext = file_path.suffix.lower()
            stats["files_seen"] += 1
            rel_ref = str(file_path)

            if ext in (".db", ".sqlite", ".sqlite3"):
                if is_gemini_archive_db(file_path):
                    ins, skip, br = ingest_gemini_archive_db(file_path, conn)
                    stats["chunks_inserted"] += ins
                    stats["duplicates_skipped"] += skip
                    stats["bridges_imported"] += br
                else:
                    for sref, author, created, chunk in iter_generic_sqlite_chunks(file_path):
                        if insert_chunk(conn, "chat_db", sref, author, created, chunk):
                            stats["chunks_inserted"] += 1
                        else:
                            stats["duplicates_skipped"] += 1
            elif ext in (".md", ".txt", ".log", ".py", ".lean"):
                text = file_path.read_text(encoding="utf-8", errors="replace")
                for chunk in chunk_text(text):
                    if insert_chunk(conn, ext.lstrip("."), rel_ref, None, None, chunk):
                        stats["chunks_inserted"] += 1
                    else:
                        stats["duplicates_skipped"] += 1
            elif ext == ".json":
                raw = json.loads(file_path.read_text(encoding="utf-8", errors="replace"))
                for author, created, text in iter_json_records(raw, rel_ref):
                    for chunk in chunk_text(text):
                        if insert_chunk(conn, "json", rel_ref, author, created, chunk):
                            stats["chunks_inserted"] += 1
                        else:
                            stats["duplicates_skipped"] += 1
            elif ext == ".jsonl":
                for line in file_path.read_text(encoding="utf-8", errors="replace").splitlines():
                    if not line.strip():
                        continue
                    obj = json.loads(line)
                    for author, created, text in iter_json_records(obj, rel_ref):
                        for chunk in chunk_text(text):
                            if insert_chunk(conn, "jsonl", rel_ref, author, created, chunk):
                                stats["chunks_inserted"] += 1
                            else:
                                stats["duplicates_skipped"] += 1
            elif ext == ".csv":
                with file_path.open("r", encoding="utf-8", errors="replace", newline="") as fh:
                    reader = csv.DictReader(fh)
                    for row in reader:
                        row_text = "\n".join(f"{k}: {v}" for k, v in row.items() if v)
                        for chunk in chunk_text(row_text):
                            if insert_chunk(conn, "csv", rel_ref, None, None, chunk):
                                stats["chunks_inserted"] += 1
                            else:
                                stats["duplicates_skipped"] += 1
            elif ext in (".html", ".htm"):
                parser = _HTMLTextExtractor()
                parser.feed(file_path.read_text(encoding="utf-8", errors="replace"))
                for chunk in chunk_text(parser.get_text()):
                    if insert_chunk(conn, "html", rel_ref, None, None, chunk):
                        stats["chunks_inserted"] += 1
                    else:
                        stats["duplicates_skipped"] += 1
            elif ext == ".docx":
                text = extract_docx_text(file_path) or extract_textutil_text(file_path)
                for chunk in chunk_text(text):
                    if insert_chunk(conn, "docx", rel_ref, None, None, chunk):
                        stats["chunks_inserted"] += 1
                    else:
                        stats["duplicates_skipped"] += 1
            elif ext in (".rtf", ".doc", ".odt"):
                for chunk in chunk_text(extract_textutil_text(file_path)):
                    if insert_chunk(conn, ext.lstrip("."), rel_ref, None, None, chunk):
                        stats["chunks_inserted"] += 1
                    else:
                        stats["duplicates_skipped"] += 1
            elif ext == ".pdf":
                for chunk in chunk_text(extract_pdf_text(file_path)):
                    if insert_chunk(conn, "pdf", rel_ref, None, None, chunk):
                        stats["chunks_inserted"] += 1
                    else:
                        stats["duplicates_skipped"] += 1

        conn.execute("INSERT INTO chunks_fts(chunks_fts) VALUES('rebuild');")
        conn.commit()
    finally:
        conn.close()

    return stats


def build_slice(
    db_path: Path,
    slice_name: str = "physics_pilot",
    fts_query: str | None = None,
    limit: int = 1000,
    exclude_existing_slices: bool = False,
) -> int:
    """Tag top-N high-signal chunks matching an FTS5 query into chapter_slices."""
    query = fts_query or SLICE_QUERIES.get(slice_name, PHYSICS_SLICE_QUERY)
    conn = get_connection(db_path)
    try:
        excl_sql = (
            "AND c.chunk_id NOT IN (SELECT chunk_id FROM chapter_slices)"
            if exclude_existing_slices
            else ""
        )
        rows = conn.execute(
            f"""
            SELECT c.chunk_id, c.source_ref, c.content, bm25(chunks_fts) AS score
            FROM chunks_fts
            JOIN chunks c ON c.chunk_id = chunks_fts.rowid
            WHERE chunks_fts MATCH ?
              {excl_sql}
            ORDER BY score
            LIMIT ?
            """,
            (query, limit * 4),
        ).fetchall()
        inserted = 0
        for r in rows:
            sref = r["source_ref"]
            if DOMESTIC_NOISE_RE.search(sref) or DOMESTIC_NOISE_RE.search(r["content"]):
                continue
            if "lean_proofs/macro_" in sref:
                continue
            reason = detect_noise_skip_reason(sref, r["content"])
            status = "SKIPPED" if reason else "PENDING"
            cur = conn.execute(
                """
                INSERT OR IGNORE INTO chapter_slices (slice_name, chunk_id, relevance, status, skip_reason)
                VALUES (?, ?, ?, ?, ?)
                """,
                (slice_name, r["chunk_id"], float(r["score"]), status, reason),
            )
            if status == "PENDING":
                inserted += cur.rowcount
            if inserted >= limit:
                break
        conn.commit()
        return inserted
    finally:
        conn.close()


def _resolve_cfg_path(raw: str | None, fallback: Path) -> Path:
    if not raw:
        return fallback
    p = Path(os.path.expandvars(raw)).expanduser()
    return p if p.is_absolute() else (WORKSPACE_ROOT / p)


def main() -> None:
    cfg = load_corpus_config()
    default_db = _resolve_cfg_path(cfg.get("corpus_db"), DEFAULT_DB_PATH)
    default_input = _resolve_cfg_path(cfg.get("archive_db"), DEFAULT_RAW_DIR)

    parser = argparse.ArgumentParser(description="Stage 0 Corpus Ingestion & Slice Builder")
    parser.add_argument("--input", type=Path, default=default_input, help="File or directory to ingest")
    parser.add_argument("--db", type=Path, default=default_db, help="Target SQLite corpus database")
    parser.add_argument("--inspect-db", type=Path, help="Inspect tables/columns of an existing .db file and exit")
    parser.add_argument("--reset-db", action="store_true", help="Remove existing target corpus.db before ingesting")
    parser.add_argument("--build-physics-slice", action="store_true", help="Tag slice via FTS5 without re-ingesting if --slice-only is set")
    parser.add_argument("--slice-only", action="store_true", help="Build chapter_slice on existing DB without re-ingesting")
    parser.add_argument("--exclude-existing-slices", action="store_true", help="Exclude chunks already tagged in any chapter_slice")
    parser.add_argument("--slice-name", default="physics_pilot", help="Slice name (default: physics_pilot)")
    parser.add_argument("--fts-query", default=None, help="Optional custom FTS5 query override")
    parser.add_argument("--slice-limit", type=int, default=1000, help="Max chunks to tag into slice")
    args = parser.parse_args()

    if args.inspect_db:
        layout = inspect_sqlite_db(args.inspect_db)
        print(json.dumps(layout, indent=2))
        return

    if args.reset_db:
        for suffix in ("", "-wal", "-shm"):
            candidate = Path(str(args.db) + suffix)
            if candidate.exists():
                candidate.unlink()

    if args.slice_only:
        init_db(args.db)
        tagged = build_slice(
            args.db,
            slice_name=args.slice_name,
            fts_query=args.fts_query,
            limit=args.slice_limit,
            exclude_existing_slices=args.exclude_existing_slices,
        )
        print(json.dumps({"db": str(args.db), "slice_tagged": {args.slice_name: tagged}}, indent=2))
        return

    if not args.input.exists():
        raise FileNotFoundError(f"Input path does not exist: {args.input}")

    stats = ingest_path(args.input, args.db)
    result: dict[str, object] = {"ingest": stats, "input": str(args.input), "db": str(args.db)}
    if args.build_physics_slice:
        tagged = build_slice(
            args.db,
            slice_name=args.slice_name,
            fts_query=args.fts_query,
            limit=args.slice_limit,
            exclude_existing_slices=args.exclude_existing_slices,
        )
        result["slice_tagged"] = {args.slice_name: tagged}
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
