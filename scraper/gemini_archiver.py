#!/usr/bin/env python3
"""
Gemini Complete Account History Archiver & Hypergraph Exporter (macOS)
======================================================================
A desktop GUI and CLI application for macOS that connects to your logged-in
Google Gemini session (via Playwright / Chrome Remote Debugging or Persistent
Profile), discovers every chat in your sidebar history, scrolls through even
thousands of turns until the very first prompt is loaded into memory, verifies
turn completeness, alerts you via macOS Notification Center + GUI dialog if
any thread hits your configured turn/scroll ceiling, stores everything in a
local SQLite database with resume support, and exports every conversation into
all major archival and graph formats side-by-side:
  - JSON (.json)            : Full structured turn data, metadata, & hashes
  - Hypergraph (.json)      : Per-chat & global cross-chat hypergraph (nodes,
                              n-ary hyperedges, incidence lists, HIF-compatible)
  - Markdown (.md)          : Clean readable conversation with code blocks
  - CSV (.csv)              : Turn-by-turn tabular dataset for Excel / Pandas
  - Plain Text (.txt)       : Universal archival plain text transcript
  - HTML (.html)            : Standalone styled offline web archive
  - PDF (.pdf)              : Print-ready paginated document rendered via Chromium
  - SQLite (archive.db)     : Master FTS5 database + hypergraph_nodes /
                              hypergraph_edges / hypergraph_incidence tables
  - Manifest (manifest.json): Cryptographic SHA-256 verification ledger

Usage (GUI mode - default):
    python3 gemini_archiver.py

Usage (CLI mode):
    python3 scraper/gemini_archiver.py --cli --output ./data --max-turns 5000
"""

from __future__ import annotations

import argparse
import asyncio
import collections
import contextlib
import csv
import datetime as dt
import errno
import hashlib
import html
import json
import os
import pathlib
import queue
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

try:
    from archive_vault import atomic_json, atomic_output, sha as file_sha, DEFAULT_RESERVE_BYTES  # type: ignore
except ImportError:
    DEFAULT_RESERVE_BYTES = 256 * 1024 * 1024

    def file_sha(path: pathlib.Path) -> Optional[str]:
        p = pathlib.Path(path)
        if not p.exists() or not p.is_file():
            return None
        h = hashlib.sha256()
        with p.open("rb") as fh:
            for chunk in iter(lambda: fh.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()

    @contextlib.contextmanager
    def atomic_output(path: pathlib.Path, *, additional_bytes: int = 0, expected_sha256: Optional[str] = None, **_kw: Any):
        target = pathlib.Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=str(target.parent))
        os.close(fd)
        tmp_path = pathlib.Path(tmp_name)
        try:
            yield tmp_path
            tmp_path.replace(target)
        except Exception:
            try:
                tmp_path.unlink(missing_ok=True)
            except OSError:
                pass
            raise

    def atomic_json(
        path: pathlib.Path,
        payload: Any,
        *,
        ensure_ascii: bool = False,
        indent: int = 2,
        trailing_newline: bool = True,
        **_kw: Any,
    ) -> None:
        text = json.dumps(payload, ensure_ascii=ensure_ascii, indent=indent)
        if trailing_newline:
            text += "\n"
        with atomic_output(path) as tmp_path:
            tmp_path.write_text(text, encoding="utf-8")

# Optional Tkinter import for macOS native GUI
try:
    import tkinter as tk
    from tkinter import filedialog, messagebox, scrolledtext, ttk
    HAS_TK = True
except ImportError:
    HAS_TK = False


# ============================================================================
# Stopwords & Entity Extraction Helpers for Hypergraph Construction
# ============================================================================

STOPWORDS: Set[str] = {
    "about", "above", "after", "again", "against", "all", "also", "always", "among",
    "an", "and", "any", "are", "aren", "around", "as", "ask", "asked", "at", "away",
    "back", "be", "became", "because", "become", "becomes", "been", "before", "being",
    "below", "between", "both", "but", "by", "call", "called", "can", "cannot", "come",
    "could", "couldn", "did", "didn", "do", "does", "doesn", "doing", "don", "done",
    "down", "during", "each", "either", "else", "enough", "even", "ever", "every",
    "everything", "example", "few", "find", "first", "for", "found", "from", "further",
    "gave", "get", "gets", "getting", "give", "given", "gives", "go", "goes", "going",
    "gone", "good", "got", "great", "had", "hadn", "has", "hasn", "have", "haven",
    "having", "he", "help", "her", "here", "hers", "herself", "high", "him", "himself",
    "his", "how", "however", "http", "https", "if", "important", "in", "include",
    "includes", "including", "into", "is", "isn", "it", "its", "itself", "just", "keep",
    "kept", "know", "known", "knows", "large", "last", "later", "least", "left", "less",
    "let", "lets", "like", "likely", "line", "little", "long", "look", "looking", "looks",
    "lot", "made", "make", "makes", "making", "many", "may", "maybe", "me", "mean",
    "means", "might", "more", "most", "mostly", "much", "must", "my", "myself", "name",
    "need", "needed", "needs", "never", "new", "next", "no", "non", "none", "nor", "not",
    "nothing", "now", "number", "of", "off", "often", "old", "on", "once", "one", "ones",
    "only", "onto", "or", "other", "others", "ought", "our", "ours", "ourselves", "out",
    "over", "own", "part", "per", "perhaps", "place", "please", "point", "possible",
    "put", "quite", "rather", "really", "right", "run", "said", "same", "saw", "say",
    "saying", "says", "see", "seem", "seemed", "seems", "seen", "several", "shall",
    "she", "should", "shouldn", "show", "shows", "side", "since", "small", "so", "some",
    "somebody", "someone", "something", "sometimes", "somewhere", "still", "such",
    "sure", "take", "taken", "takes", "taking", "tell", "than", "that", "the", "their",
    "theirs", "them", "themselves", "then", "there", "therefore", "these", "they",
    "thing", "things", "think", "this", "those", "though", "three", "through",
    "throughout", "thus", "time", "times", "to", "together", "too", "took", "toward",
    "towards", "try", "trying", "turn", "turns", "two", "under", "unless", "until",
    "up", "upon", "us", "use", "used", "useful", "uses", "using", "usually", "value",
    "values", "various", "very", "via", "want", "wanted", "wants", "was", "wasn", "way",
    "ways", "we", "well", "went", "were", "weren", "what", "whatever", "when", "where",
    "whether", "which", "while", "who", "whole", "whom", "whose", "why", "will", "with",
    "within", "without", "won", "work", "worked", "working", "works", "would", "wouldn",
    "write", "written", "www", "yes", "yet", "you", "your", "yours", "yourself",
    "yourselves", "gemini", "user", "model", "prompt", "response", "code", "true", "false",
}


def extract_turn_concepts_and_urls(
    user_text: str, model_text: str, thoughts_text: str = ""
) -> Tuple[List[str], List[str]]:
    """
    Extracts salient semantic concepts/entities (capitalized multi-word phrases,
    camelCase/snake_case identifiers, inline backtick symbols, hashtags, and top
    domain terms) plus canonical URLs for hypergraph node & hyperedge linking.
    """
    combined = f"{user_text}\n{model_text}\n{thoughts_text}"

    # 1. Extract URLs
    raw_urls = re.findall(r"https?://[^\s<>\"\'\)\]]+", combined)
    urls = sorted({u.rstrip(".,;:!?)") for u in raw_urls if len(u) > 10})[:25]

    concepts: Dict[str, int] = collections.Counter()

    # 2. Inline code symbols (`symbol_name`)
    for sym in re.findall(r"`([a-zA-Z_][a-zA-Z0-9_.:/-]{2,42})`", combined):
        low = sym.lower()
        if low not in STOPWORDS and not low.isdigit():
            concepts[low] += 3

    # 3. Capitalized Proper Noun / Technical Phrases (e.g., "Hypergraph Incidence", "Playwright")
    for phrase in re.findall(r"\b([A-Z][a-zA-Z0-9_-]{2,25}(?:\s+[A-Z][a-zA-Z0-9_-]{2,25}){0,2})\b", combined):
        low = phrase.strip().lower()
        parts = low.split()
        if all(p not in STOPWORDS for p in parts) and len(low) >= 3:
            concepts[low] += 2

    # 4. High-signal technical tokens (snake_case, hyphenated, or >=5 char domain terms)
    for tok in re.findall(r"\b([a-zA-Z][a-zA-Z0-9_]{4,36})\b", combined.lower()):
        if tok not in STOPWORDS and not tok.isdigit():
            weight = 2 if ("_" in tok or any(c.isdigit() for c in tok)) else 1
            concepts[tok] += weight

    ranked = [term for term, _ in concepts.most_common(18)]
    return ranked, urls


# ============================================================================
# Data Models
# ============================================================================

def _default_archive_dir() -> pathlib.Path:
    env_dir = os.environ.get("ARCHIVE_DIR", "").strip()
    if env_dir:
        return pathlib.Path(env_dir).expanduser()
    env_db = os.environ.get("ARCHIVE_DB", "").strip() or os.environ.get("ARCHIVE_DB_PATH", "").strip()
    if env_db:
        return pathlib.Path(env_db).expanduser().parent
    return pathlib.Path(__file__).resolve().parent.parent / "data"


def _default_profile_dir() -> pathlib.Path:
    env_prof = os.environ.get("CHROME_USER_DATA_DIR", "").strip()
    if env_prof:
        return pathlib.Path(env_prof).expanduser()
    return pathlib.Path.home() / ".cache" / "corpus_chrome_profile"


class _StandaloneOperation:
    def __init__(self) -> None:
        self.result: Dict[str, Any] = {}

    def log(self, msg: str) -> None:
        print(f"[{dt.datetime.now().strftime('%H:%M:%S')}] {msg}")

    def __enter__(self) -> "_StandaloneOperation":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


def _open_project_operation(out_dir: pathlib.Path, op_name: str, base_dir: pathlib.Path, configuration: Optional[Dict[str, Any]] = None):
    try:
        from project_history import ProjectOperation  # type: ignore
        return ProjectOperation(out_dir, op_name, base_dir, configuration=configuration)
    except ImportError:
        return _StandaloneOperation()


@dataclass
class TurnAttachment:
    name: str
    url: str = ""
    mime_type: str = ""
    local_path: str = ""
    download_error: str = ""


@dataclass
class ChatTurn:
    turn_index: int
    turn_id: str
    user_prompt: str
    user_html: str
    model_response: str
    model_html: str
    model_thoughts: str = ""
    code_blocks: List[Dict[str, str]] = field(default_factory=list)
    attachments: List[TurnAttachment] = field(default_factory=list)
    timestamp_hint: str = ""
    sha256: str = ""
    # Hypergraph-ready relational & structural fields
    node_id: str = ""
    user_node_id: str = ""
    model_node_id: str = ""
    parent_turn_id: str = ""
    next_turn_id: str = ""
    concepts: List[str] = field(default_factory=list)
    urls: List[str] = field(default_factory=list)
    user_token_estimate: int = 0
    model_token_estimate: int = 0

    def enrich_and_hash(self, chat_id: str, prev_turn_id: str = "", next_turn_id: str = "") -> str:
        self.node_id = f"turn:{chat_id}:{self.turn_index}"
        self.user_node_id = f"msg:{chat_id}:{self.turn_index}:user"
        self.model_node_id = f"msg:{chat_id}:{self.turn_index}:model"
        self.parent_turn_id = prev_turn_id
        self.next_turn_id = next_turn_id
        self.user_token_estimate = max(1, len(self.user_prompt) // 4) if self.user_prompt else 0
        self.model_token_estimate = max(1, len(self.model_response) // 4) if self.model_response else 0
        if not self.concepts and not self.urls:
            self.concepts, self.urls = extract_turn_concepts_and_urls(
                self.user_prompt, self.model_response, self.model_thoughts
            )
        payload = json.dumps({"turn_index": self.turn_index, "turn_id": self.turn_id, "user_prompt": self.user_prompt, "user_html": self.user_html, "model_response": self.model_response, "model_html": self.model_html, "model_thoughts": self.model_thoughts, "code_blocks": self.code_blocks, "attachments": [asdict(a) for a in self.attachments], "timestamp_hint": self.timestamp_hint}, sort_keys=True, ensure_ascii=False)
        self.sha256 = hashlib.sha256(payload.encode("utf-8", errors="replace")).hexdigest()
        return self.sha256

    def compute_hash(self) -> str:
        payload = json.dumps({"turn_index": self.turn_index, "turn_id": self.turn_id, "user_prompt": self.user_prompt, "user_html": self.user_html, "model_response": self.model_response, "model_html": self.model_html, "model_thoughts": self.model_thoughts, "code_blocks": self.code_blocks, "attachments": [asdict(a) for a in self.attachments], "timestamp_hint": self.timestamp_hint}, sort_keys=True, ensure_ascii=False)
        self.sha256 = hashlib.sha256(payload.encode("utf-8", errors="replace")).hexdigest()
        return self.sha256


@dataclass
class ConversationRecord:
    chat_id: str
    title: str
    url: str
    scraped_at: str
    total_turns: int
    total_user_chars: int
    total_model_chars: int
    is_pinned: bool = False
    scroll_iterations: int = 0
    reached_beginning_of_chat: bool = False
    max_turns_limit_exceeded: bool = False
    configured_max_turns: int = 5000
    configured_max_scroll_steps: int = 2500
    truncation_warning: str = ""
    turns: List[ChatTurn] = field(default_factory=list)
    capture_status: str = "captured_unverified"
    completeness_note: str = "DOM capture only; completeness has not been independently verified."
    raw_rpc_payloads_captured: int = 0
    conversation_sha256: str = ""
    exported_files: Dict[str, str] = field(default_factory=dict)

    def finalize_topology_and_digest(self) -> str:
        for i, t in enumerate(self.turns):
            prev_id = self.turns[i - 1].turn_id if i > 0 else ""
            next_id = self.turns[i + 1].turn_id if (i + 1) < len(self.turns) else ""
            t.enrich_and_hash(self.chat_id, prev_turn_id=prev_id, next_turn_id=next_id)
        turn_hashes = "|".join(t.sha256 for t in self.turns)
        raw = f"{self.chat_id}|{self.title}|{len(self.turns)}|{turn_hashes}"
        self.conversation_sha256 = hashlib.sha256(raw.encode("utf-8", errors="replace")).hexdigest()
        return self.conversation_sha256

    def compute_digest(self) -> str:
        return self.finalize_topology_and_digest()


# ============================================================================
# macOS System Notification & Truncation Alert Helper
# ============================================================================

def send_macos_limit_exceeded_notification(
    title: str,
    message: str,
    sound_name: str = "Sosumi",
) -> None:
    """
    Fires a native macOS Notification Center banner + audible alert via osascript
    whenever a conversation hits the configured max_turns or max_scroll_steps ceiling.
    """
    if sys.platform != "darwin":
        return
    safe_title = title.replace('"', '\\"').replace("'", "")
    safe_msg = message.replace('"', '\\"').replace("'", "")
    script = f'display notification "{safe_msg}" with title "{safe_title}" sound name "{sound_name}"'
    try:
        subprocess.run(
            ["osascript", "-e", script],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
        )
    except Exception:
        pass


# ============================================================================
# SQLite Master Archive, Hypergraph Store & Resume State Manager
# ============================================================================

class ArchiveDatabase:
    """Manages local SQLite storage, Full-Text Search (FTS5), Hypergraph tables, and resume state."""

    def __init__(self, db_path: pathlib.Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._work_db_path = self.db_path
        self._uses_staging = False
        try:
            conn = sqlite3.connect(str(self.db_path))
            conn.execute("CREATE TABLE IF NOT EXISTS _lock_probe (id INT);")
            conn.close()
        except sqlite3.OperationalError:
            self._uses_staging = True
            h = hashlib.sha1(str(self.db_path).encode()).hexdigest()[:12]
            self._work_db_path = pathlib.Path("/tmp") / f"gemini_archive_{h}.db"
            if self.db_path.exists() and not self._work_db_path.exists():
                shutil.copyfile(str(self.db_path), str(self._work_db_path))
        self._init_db()

    def _sync_if_staged(self) -> None:
        if self._uses_staging and self._work_db_path.exists():
            shutil.copyfile(str(self._work_db_path), str(self.db_path))

    @contextlib.contextmanager
    def _connect(self):
        conn = sqlite3.connect(str(self._work_db_path), timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=MEMORY;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS conversations (
                    chat_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    url TEXT NOT NULL,
                    is_pinned INTEGER DEFAULT 0,
                    status TEXT DEFAULT 'discovered',
                    total_turns INTEGER DEFAULT 0,
                    total_user_chars INTEGER DEFAULT 0,
                    total_model_chars INTEGER DEFAULT 0,
                    reached_beginning INTEGER DEFAULT 0,
                    max_turns_exceeded INTEGER DEFAULT 0,
                    configured_max_turns INTEGER DEFAULT 5000,
                    scroll_iterations INTEGER DEFAULT 0,
                    conversation_sha256 TEXT DEFAULT '',
                    folder_path TEXT DEFAULT '',
                    discovered_at TEXT,
                    scraped_at TEXT,
                    error_message TEXT DEFAULT ''
                );

                CREATE TABLE IF NOT EXISTS turns (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id TEXT NOT NULL,
                    turn_index INTEGER NOT NULL,
                    turn_id TEXT,
                    node_id TEXT,
                    parent_turn_id TEXT,
                    next_turn_id TEXT,
                    user_prompt TEXT,
                    user_html TEXT,
                    model_response TEXT,
                    model_html TEXT,
                    model_thoughts TEXT,
                    code_blocks_json TEXT,
                    attachments_json TEXT,
                    concepts_json TEXT,
                    urls_json TEXT,
                    user_token_estimate INTEGER DEFAULT 0,
                    model_token_estimate INTEGER DEFAULT 0,
                    timestamp_hint TEXT,
                    sha256 TEXT,
                    UNIQUE(chat_id, turn_index),
                    FOREIGN KEY(chat_id) REFERENCES conversations(chat_id)
                );

                CREATE TABLE IF NOT EXISTS exported_files (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id TEXT NOT NULL,
                    format TEXT NOT NULL,
                    file_path TEXT NOT NULL,
                    file_size_bytes INTEGER NOT NULL,
                    file_sha256 TEXT NOT NULL,
                    exported_at TEXT NOT NULL,
                    UNIQUE(chat_id, format)
                );

                -- Native Hypergraph Relational Schema (Nodes, N-ary Hyperedges, Incidence)
                CREATE TABLE IF NOT EXISTS hypergraph_nodes (
                    node_id TEXT PRIMARY KEY,
                    node_type TEXT NOT NULL,
                    label TEXT NOT NULL,
                    chat_id TEXT DEFAULT '',
                    turn_index INTEGER DEFAULT 0,
                    content_hash TEXT DEFAULT '',
                    metadata_json TEXT DEFAULT '{}'
                );

                CREATE TABLE IF NOT EXISTS hypergraph_edges (
                    edge_id TEXT PRIMARY KEY,
                    edge_type TEXT NOT NULL,
                    label TEXT NOT NULL,
                    chat_id TEXT DEFAULT '',
                    weight REAL DEFAULT 1.0,
                    metadata_json TEXT DEFAULT '{}'
                );

                CREATE TABLE IF NOT EXISTS hypergraph_incidence (
                    edge_id TEXT NOT NULL,
                    node_id TEXT NOT NULL,
                    role TEXT NOT NULL DEFAULT 'member',
                    position INTEGER DEFAULT 0,
                    PRIMARY KEY (edge_id, node_id, role),
                    FOREIGN KEY(edge_id) REFERENCES hypergraph_edges(edge_id),
                    FOREIGN KEY(node_id) REFERENCES hypergraph_nodes(node_id)
                );

                CREATE VIRTUAL TABLE IF NOT EXISTS turns_fts USING fts5(
                    chat_id,
                    title,
                    user_prompt,
                    model_response
                );
                """
            )
            # Ensure migrations if upgrading an older archive.db
            existing_cols = {
                r["name"] for r in conn.execute("PRAGMA table_info(conversations);").fetchall()
            }
            if "max_turns_exceeded" not in existing_cols:
                conn.execute("ALTER TABLE conversations ADD COLUMN max_turns_exceeded INTEGER DEFAULT 0;")
            if "configured_max_turns" not in existing_cols:
                conn.execute("ALTER TABLE conversations ADD COLUMN configured_max_turns INTEGER DEFAULT 5000;")

    def register_sidebar_conversations(self, items: List[Dict[str, Any]]) -> int:
        now = dt.datetime.now(dt.timezone.utc).isoformat()
        new_count = 0
        with self._connect() as conn:
            for item in items:
                chat_id = item["chat_id"]
                existing = conn.execute(
                    "SELECT status FROM conversations WHERE chat_id = ?", (chat_id,)
                ).fetchone()
                if not existing:
                    conn.execute(
                        """
                        INSERT INTO conversations (chat_id, title, url, is_pinned, status, discovered_at)
                        VALUES (?, ?, ?, ?, 'discovered', ?)
                        """,
                        (
                            chat_id,
                            item.get("title", f"Conversation {chat_id}"),
                            item["url"],
                            1 if item.get("is_pinned") else 0,
                            now,
                        ),
                    )
                    new_count += 1
                else:
                    conn.execute(
                        """
                        UPDATE conversations
                        SET title = CASE WHEN title LIKE 'Conversation %' OR title = 'Untitled' THEN ? ELSE title END,
                            is_pinned = MAX(is_pinned, ?)
                        WHERE chat_id = ?
                        """,
                        (item.get("title", "Untitled"), 1 if item.get("is_pinned") else 0, chat_id),
                    )
        self._sync_if_staged()
        return new_count

    def get_pending_conversations(self, force_rescrape: bool = False) -> List[Dict[str, Any]]:
        """
        Returns conversations that haven't been completed yet OR that previously hit
        status='needs_higher_limit' so increasing max_turns automatically re-scrapes them.
        """
        with self._connect() as conn:
            if force_rescrape:
                rows = conn.execute(
                    "SELECT * FROM conversations ORDER BY is_pinned DESC, discovered_at ASC"
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT * FROM conversations
                    WHERE status != 'completed' OR max_turns_exceeded = 1
                    ORDER BY is_pinned DESC, discovered_at ASC
                    """
                ).fetchall()
            return [dict(r) for r in rows]

    def get_all_conversations(self) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM conversations ORDER BY is_pinned DESC, scraped_at DESC"
            ).fetchall()
            return [dict(r) for r in rows]

    def save_conversation(self, record: ConversationRecord, folder_path: str) -> None:
        status_val = "needs_higher_limit" if record.max_turns_limit_exceeded else record.capture_status
        with self._connect() as conn:
            # Non-regression guard: load existing populated turns for this chat_id so an
            # unhydrated/virtualized DOM stub can NEVER overwrite already-captured prose.
            existing_rows = conn.execute(
                """
                SELECT turn_id, turn_index, user_prompt, user_html, model_response, model_html, model_thoughts
                FROM turns WHERE chat_id = ?
                """,
                (record.chat_id,),
            ).fetchall()
            existing_by_tid: Dict[str, Dict[str, str]] = {}
            existing_by_idx: Dict[int, Dict[str, str]] = {}
            for er in existing_rows:
                ed = {
                    "user_prompt": er["user_prompt"] or "",
                    "user_html": er["user_html"] or "",
                    "model_response": er["model_response"] or "",
                    "model_html": er["model_html"] or "",
                    "model_thoughts": er["model_thoughts"] or "",
                }
                if er["turn_id"]:
                    existing_by_tid[str(er["turn_id"])] = ed
                if er["turn_index"] is not None:
                    existing_by_idx[int(er["turn_index"])] = ed

            for turn in record.turns:
                prev = existing_by_tid.get(str(turn.turn_id)) or existing_by_idx.get(int(turn.turn_index))
                if prev:
                    if not (turn.user_prompt or "").strip() and prev["user_prompt"].strip():
                        turn.user_prompt = prev["user_prompt"]
                    if not (turn.user_html or "").strip() and prev["user_html"].strip():
                        turn.user_html = prev["user_html"]
                    if not (turn.model_response or "").strip() and prev["model_response"].strip():
                        turn.model_response = prev["model_response"]
                    if not (turn.model_html or "").strip() and prev["model_html"].strip():
                        turn.model_html = prev["model_html"]
                    if not (turn.model_thoughts or "").strip() and prev["model_thoughts"].strip():
                        turn.model_thoughts = prev["model_thoughts"]
                    turn.user_token_estimate = max(1, len(turn.user_prompt) // 4) if turn.user_prompt else 0
                    turn.model_token_estimate = max(1, len(turn.model_response) // 4) if turn.model_response else 0

            record.total_user_chars = sum(len(t.user_prompt or "") for t in record.turns)
            record.total_model_chars = sum(len(t.model_response or "") for t in record.turns)

            conn.execute(
                """
                INSERT INTO conversations (
                    chat_id, title, url, is_pinned, status, total_turns,
                    total_user_chars, total_model_chars, reached_beginning,
                    max_turns_exceeded, configured_max_turns,
                    scroll_iterations, conversation_sha256, folder_path, scraped_at, error_message
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(chat_id) DO UPDATE SET
                    title = excluded.title,
                    url = excluded.url,
                    is_pinned = excluded.is_pinned,
                    status = excluded.status,
                    total_turns = excluded.total_turns,
                    total_user_chars = excluded.total_user_chars,
                    total_model_chars = excluded.total_model_chars,
                    reached_beginning = excluded.reached_beginning,
                    max_turns_exceeded = excluded.max_turns_exceeded,
                    configured_max_turns = excluded.configured_max_turns,
                    scroll_iterations = excluded.scroll_iterations,
                    conversation_sha256 = excluded.conversation_sha256,
                    folder_path = excluded.folder_path,
                    scraped_at = excluded.scraped_at,
                    error_message = excluded.error_message
                """,
                (
                    record.chat_id,
                    record.title,
                    record.url,
                    1 if record.is_pinned else 0,
                    status_val,
                    record.total_turns,
                    record.total_user_chars,
                    record.total_model_chars,
                    1 if record.reached_beginning_of_chat else 0,
                    1 if record.max_turns_limit_exceeded else 0,
                    record.configured_max_turns,
                    record.scroll_iterations,
                    record.conversation_sha256,
                    folder_path,
                    record.scraped_at,
                    record.truncation_warning or record.completeness_note,
                ),
            )

            conn.execute("DELETE FROM turns WHERE chat_id = ?", (record.chat_id,))
            conn.execute("DELETE FROM turns_fts WHERE chat_id = ?", (record.chat_id,))

            for turn in record.turns:
                conn.execute(
                    """
                    INSERT INTO turns (
                        chat_id, turn_index, turn_id, node_id, parent_turn_id, next_turn_id,
                        user_prompt, user_html, model_response, model_html, model_thoughts,
                        code_blocks_json, attachments_json, concepts_json, urls_json,
                        user_token_estimate, model_token_estimate, timestamp_hint, sha256
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        record.chat_id,
                        turn.turn_index,
                        turn.turn_id,
                        turn.node_id,
                        turn.parent_turn_id,
                        turn.next_turn_id,
                        turn.user_prompt,
                        turn.user_html,
                        turn.model_response,
                        turn.model_html,
                        turn.model_thoughts,
                        json.dumps(turn.code_blocks, ensure_ascii=False),
                        json.dumps([asdict(a) for a in turn.attachments], ensure_ascii=False),
                        json.dumps(turn.concepts, ensure_ascii=False),
                        json.dumps(turn.urls, ensure_ascii=False),
                        turn.user_token_estimate,
                        turn.model_token_estimate,
                        turn.timestamp_hint,
                        turn.sha256,
                    ),
                )
                conn.execute(
                    """
                    INSERT INTO turns_fts (chat_id, title, user_prompt, model_response)
                    VALUES (?, ?, ?, ?)
                    """,
                    (record.chat_id, record.title, turn.user_prompt, turn.model_response),
                )

    def save_hypergraph_elements(
        self,
        chat_id: str,
        nodes: List[Dict[str, Any]],
        edges: List[Dict[str, Any]],
        incidences: List[Dict[str, Any]],
    ) -> None:
        """Persists nodes, n-ary hyperedges, and incidence rows into SQLite."""
        with self._connect() as conn:
            # Remove prior chat-scoped edges & incidences for clean idempotent re-runs
            old_edges = [
                r["edge_id"]
                for r in conn.execute(
                    "SELECT edge_id FROM hypergraph_edges WHERE chat_id = ?", (chat_id,)
                ).fetchall()
            ]
            for eid in old_edges:
                conn.execute("DELETE FROM hypergraph_incidence WHERE edge_id = ?", (eid,))
            conn.execute("DELETE FROM hypergraph_edges WHERE chat_id = ?", (chat_id,))
            conn.execute("DELETE FROM hypergraph_nodes WHERE chat_id = ? AND node_id NOT IN (SELECT node_id FROM hypergraph_incidence)", (chat_id,))

            for n in nodes:
                conn.execute(
                    """
                    INSERT INTO hypergraph_nodes (node_id, node_type, label, chat_id, turn_index, content_hash, metadata_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(node_id) DO UPDATE SET
                        label = excluded.label,
                        content_hash = excluded.content_hash,
                        metadata_json = excluded.metadata_json
                    """,
                    (
                        n["node_id"],
                        n["node_type"],
                        n["label"],
                        n.get("chat_id", ""),
                        int(n.get("turn_index", 0)),
                        n.get("content_hash", ""),
                        json.dumps(n.get("metadata", {}), ensure_ascii=False),
                    ),
                )

            for e in edges:
                conn.execute(
                    """
                    INSERT INTO hypergraph_edges (edge_id, edge_type, label, chat_id, weight, metadata_json)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(edge_id) DO UPDATE SET
                        label = excluded.label,
                        weight = excluded.weight,
                        metadata_json = excluded.metadata_json
                    """,
                    (
                        e["edge_id"],
                        e["edge_type"],
                        e["label"],
                        e.get("chat_id", ""),
                        float(e.get("weight", 1.0)),
                        json.dumps(e.get("metadata", {}), ensure_ascii=False),
                    ),
                )

            for inc in incidences:
                conn.execute(
                    """
                    INSERT INTO hypergraph_incidence (edge_id, node_id, role, position)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(edge_id, node_id, role) DO UPDATE SET
                        position = excluded.position
                    """,
                    (
                        inc["edge_id"],
                        inc["node_id"],
                        inc.get("role", "member"),
                        int(inc.get("position", 0)),
                    ),
                )

    def build_global_account_hypergraph(self) -> Dict[str, Any]:
        """
        Synthesizes the full account-wide hypergraph from SQLite, including
        cross-conversation semantic hyperedges that connect turns from *different*
        conversations sharing concepts, code languages, or external URLs.
        """
        with self._connect() as conn:
            nodes = [dict(r) for r in conn.execute("SELECT * FROM hypergraph_nodes").fetchall()]
            edges = [dict(r) for r in conn.execute("SELECT * FROM hypergraph_edges").fetchall()]
            incidences = [
                dict(r)
                for r in conn.execute(
                    "SELECT * FROM hypergraph_incidence ORDER BY edge_id, position"
                ).fetchall()
            ]

        # Group incidences by node_id to detect cross-conversation bridges
        concept_to_turns: Dict[str, List[str]] = collections.defaultdict(list)
        node_lookup = {n["node_id"]: n for n in nodes}

        for inc in incidences:
            nid = inc["node_id"]
            if nid.startswith("concept:") or nid.startswith("url:") or nid.startswith("lang:"):
                concept_to_turns[nid].append(inc["edge_id"])

        # Build Bipartite / Hypergraph Incidence Dictionary (HIF-compatible standard)
        edge_members: Dict[str, List[Dict[str, Any]]] = collections.defaultdict(list)
        for inc in incidences:
            edge_members[inc["edge_id"]].append(
                {
                    "node_id": inc["node_id"],
                    "role": inc["role"],
                    "position": inc["position"],
                }
            )

        formatted_edges = []
        for e in edges:
            eid = e["edge_id"]
            formatted_edges.append(
                {
                    "edge_id": eid,
                    "edge_type": e["edge_type"],
                    "label": e["label"],
                    "chat_id": e["chat_id"],
                    "weight": e["weight"],
                    "metadata": json.loads(e["metadata_json"] or "{}"),
                    "incident_nodes": edge_members.get(eid, []),
                }
            )

        formatted_nodes = []
        for n in nodes:
            formatted_nodes.append(
                {
                    "node_id": n["node_id"],
                    "node_type": n["node_type"],
                    "label": n["label"],
                    "chat_id": n["chat_id"],
                    "turn_index": n["turn_index"],
                    "content_hash": n["content_hash"],
                    "metadata": json.loads(n["metadata_json"] or "{}"),
                }
            )

        return {
            "schema_version": "GeminiHypergraph-1.0",
            "generated_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
            "conversion_note": "Custom incidence schema; convert node_id/edge_id fields for your chosen graph library.",
            "statistics": {
                "total_nodes": len(formatted_nodes),
                "total_hyperedges": len(formatted_edges),
                "total_incidences": len(incidences),
            },
            "nodes": formatted_nodes,
            "hyperedges": formatted_edges,
            "incidence": incidences,
        }

    def record_exported_file(self, chat_id: str, fmt: str, file_path: pathlib.Path) -> None:
        if not file_path.exists():
            return
        data = file_path.read_bytes()
        sha = hashlib.sha256(data).hexdigest()
        now = dt.datetime.now(dt.timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO exported_files (chat_id, format, file_path, file_size_bytes, file_sha256, exported_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(chat_id, format) DO UPDATE SET
                    file_path = excluded.file_path,
                    file_size_bytes = excluded.file_size_bytes,
                    file_sha256 = excluded.file_sha256,
                    exported_at = excluded.exported_at
                """,
                (chat_id, fmt, str(file_path), len(data), sha, now),
            )

    def mark_error(self, chat_id: str, error_msg: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE conversations SET status = 'error', error_message = ? WHERE chat_id = ?",
                (error_msg, chat_id),
            )
        self._sync_if_staged()


# ============================================================================
# Hypergraph Builder (Vertices, N-Ary Hyperedges, & Incidence Tensors)
# ============================================================================

class HypergraphBuilder:
    """
    Transforms a ConversationRecord into a formal Hypergraph structure H = (V, E, I)
    where each hyperedge e in E can connect an arbitrary subset of vertices V with
    explicit semantic roles:
      - `turn_exchange` hyperedge: connects {ConversationNode, TurnNode, UserPromptNode,
        ModelResponseNode, ThoughtNode?, CodeArtifactNodes..., AttachmentNodes...,
        ConceptNodes..., URLNodes...}
      - `temporal_transition` hyperedge: connects {Turn_i, Turn_{i+1}, SharedConcepts...}
      - `concept_cooccurrence` hyperedge: connects {ConceptNode, ConversationNode,
        all TurnNodes in which that concept appears}
      - `code_language_cluster` hyperedge: connects {LanguageNode, all TurnNodes and
        CodeArtifactNodes using that language}
    """

    @staticmethod
    def build_for_conversation(
        record: ConversationRecord,
    ) -> Tuple[Dict[str, Any], List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
        nodes_map: Dict[str, Dict[str, Any]] = {}
        edges: List[Dict[str, Any]] = []
        incidences: List[Dict[str, Any]] = []

        conv_node_id = f"conv:{record.chat_id}"
        nodes_map[conv_node_id] = {
            "node_id": conv_node_id,
            "node_type": "conversation",
            "label": record.title,
            "chat_id": record.chat_id,
            "turn_index": 0,
            "content_hash": record.conversation_sha256,
            "metadata": {
                "url": record.url,
                "total_turns": record.total_turns,
                "reached_beginning_of_chat": record.reached_beginning_of_chat,
                "max_turns_limit_exceeded": record.max_turns_limit_exceeded,
                "scraped_at": record.scraped_at,
            },
        }

        concept_turns: Dict[str, List[str]] = collections.defaultdict(list)
        lang_members: Dict[str, List[str]] = collections.defaultdict(list)

        for idx, t in enumerate(record.turns):
            turn_nid = t.node_id or f"turn:{record.chat_id}:{t.turn_index}"
            user_nid = t.user_node_id or f"msg:{record.chat_id}:{t.turn_index}:user"
            model_nid = t.model_node_id or f"msg:{record.chat_id}:{t.turn_index}:model"

            nodes_map[turn_nid] = {
                "node_id": turn_nid,
                "node_type": "turn",
                "label": f"Turn #{t.turn_index} ({record.chat_id})",
                "chat_id": record.chat_id,
                "turn_index": t.turn_index,
                "content_hash": t.sha256,
                "metadata": {
                    "turn_id": t.turn_id,
                    "parent_turn_id": t.parent_turn_id,
                    "next_turn_id": t.next_turn_id,
                    "timestamp_hint": t.timestamp_hint,
                    "user_tokens": t.user_token_estimate,
                    "model_tokens": t.model_token_estimate,
                },
            }

            nodes_map[user_nid] = {
                "node_id": user_nid,
                "node_type": "user_message",
                "label": (t.user_prompt[:80] + "…") if len(t.user_prompt) > 80 else t.user_prompt,
                "chat_id": record.chat_id,
                "turn_index": t.turn_index,
                "content_hash": hashlib.sha256(t.user_prompt.encode("utf-8", errors="replace")).hexdigest(),
                "metadata": {"char_length": len(t.user_prompt), "token_estimate": t.user_token_estimate},
            }

            nodes_map[model_nid] = {
                "node_id": model_nid,
                "node_type": "model_message",
                "label": (t.model_response[:80] + "…") if len(t.model_response) > 80 else t.model_response,
                "chat_id": record.chat_id,
                "turn_index": t.turn_index,
                "content_hash": hashlib.sha256(t.model_response.encode("utf-8", errors="replace")).hexdigest(),
                "metadata": {"char_length": len(t.model_response), "token_estimate": t.model_token_estimate},
            }

            # N-ary Hyperedge 1: Full Turn Synthesis Hyperedge
            he_turn_id = f"he:turn:{record.chat_id}:{t.turn_index}"
            edges.append(
                {
                    "edge_id": he_turn_id,
                    "edge_type": "turn_exchange",
                    "label": f"Turn {t.turn_index} Exchange",
                    "chat_id": record.chat_id,
                    "weight": 1.0,
                    "metadata": {"turn_index": t.turn_index, "sha256": t.sha256},
                }
            )
            incidences.extend(
                [
                    {"edge_id": he_turn_id, "node_id": conv_node_id, "role": "context_conversation", "position": 0},
                    {"edge_id": he_turn_id, "node_id": turn_nid, "role": "turn_anchor", "position": 1},
                    {"edge_id": he_turn_id, "node_id": user_nid, "role": "prompt_source", "position": 2},
                    {"edge_id": he_turn_id, "node_id": model_nid, "role": "response_target", "position": 3},
                ]
            )

            # Optional Reasoning / Thought node
            if t.model_thoughts.strip():
                thought_nid = f"thought:{record.chat_id}:{t.turn_index}"
                nodes_map[thought_nid] = {
                    "node_id": thought_nid,
                    "node_type": "model_reasoning",
                    "label": f"Reasoning #{t.turn_index}",
                    "chat_id": record.chat_id,
                    "turn_index": t.turn_index,
                    "content_hash": hashlib.sha256(t.model_thoughts.encode("utf-8", errors="replace")).hexdigest(),
                    "metadata": {"char_length": len(t.model_thoughts)},
                }
                incidences.append(
                    {"edge_id": he_turn_id, "node_id": thought_nid, "role": "intermediate_reasoning", "position": 4}
                )

            # Code blocks as artifact nodes + language nodes
            for c_idx, cb in enumerate(t.code_blocks, start=1):
                code_str = cb.get("code", "")
                lang = (cb.get("language") or "text").lower().strip() or "text"
                code_hash = hashlib.sha256(code_str.encode("utf-8", errors="replace")).hexdigest()[:16]
                code_nid = f"code:{code_hash}"
                nodes_map[code_nid] = {
                    "node_id": code_nid,
                    "node_type": "code_artifact",
                    "label": f"{lang} snippet ({len(code_str)} chars)",
                    "chat_id": record.chat_id,
                    "turn_index": t.turn_index,
                    "content_hash": code_hash,
                    "metadata": {"language": lang, "char_length": len(code_str)},
                }
                incidences.append(
                    {"edge_id": he_turn_id, "node_id": code_nid, "role": "generated_code", "position": 10 + c_idx}
                )

                lang_nid = f"lang:{lang}"
                nodes_map[lang_nid] = {
                    "node_id": lang_nid,
                    "node_type": "programming_language",
                    "label": lang,
                    "chat_id": "",
                    "turn_index": 0,
                    "content_hash": "",
                    "metadata": {},
                }
                lang_members[lang].extend([turn_nid, code_nid])

            # Attachments as artifact nodes
            for a_idx, att in enumerate(t.attachments, start=1):
                att_nid = f"att:{record.chat_id}:{t.turn_index}:{a_idx}"
                nodes_map[att_nid] = {
                    "node_id": att_nid,
                    "node_type": "attachment",
                    "label": att.name,
                    "chat_id": record.chat_id,
                    "turn_index": t.turn_index,
                    "content_hash": "",
                    "metadata": {"url": att.url, "mime_type": att.mime_type},
                }
                incidences.append(
                    {"edge_id": he_turn_id, "node_id": att_nid, "role": "attached_media", "position": 50 + a_idx}
                )

            # Concept / Entity nodes (Global IDs so they automatically bridge across conversations!)
            for k_idx, concept in enumerate(t.concepts, start=1):
                slug = re.sub(r"[^a-z0-9_-]+", "_", concept.lower()).strip("_")
                if not slug:
                    continue
                concept_nid = f"concept:{slug}"
                if concept_nid not in nodes_map:
                    nodes_map[concept_nid] = {
                        "node_id": concept_nid,
                        "node_type": "concept",
                        "label": concept,
                        "chat_id": "",
                        "turn_index": 0,
                        "content_hash": "",
                        "metadata": {},
                    }
                incidences.append(
                    {"edge_id": he_turn_id, "node_id": concept_nid, "role": "semantic_concept", "position": 100 + k_idx}
                )
                concept_turns[concept_nid].append(turn_nid)

            # External URL nodes (Global IDs across conversations)
            for u_idx, url_val in enumerate(t.urls, start=1):
                url_hash = hashlib.sha1(url_val.encode("utf-8", errors="replace")).hexdigest()[:14]
                url_nid = f"url:{url_hash}"
                nodes_map[url_nid] = {
                    "node_id": url_nid,
                    "node_type": "external_url",
                    "label": url_val,
                    "chat_id": "",
                    "turn_index": 0,
                    "content_hash": url_hash,
                    "metadata": {"url": url_val},
                }
                incidences.append(
                    {"edge_id": he_turn_id, "node_id": url_nid, "role": "referenced_url", "position": 200 + u_idx}
                )

            # N-ary Hyperedge 2: Sequential Temporal Flow + Shared Concept Bridge between Turn_{i-1} and Turn_i
            if idx > 0:
                prev_turn = record.turns[idx - 1]
                prev_turn_nid = prev_turn.node_id or f"turn:{record.chat_id}:{prev_turn.turn_index}"
                he_flow_id = f"he:flow:{record.chat_id}:{prev_turn.turn_index}_to_{t.turn_index}"
                shared_concepts = sorted(set(prev_turn.concepts).intersection(set(t.concepts)))
                edges.append(
                    {
                        "edge_id": he_flow_id,
                        "edge_type": "temporal_transition",
                        "label": f"Turn {prev_turn.turn_index} → Turn {t.turn_index}",
                        "chat_id": record.chat_id,
                        "weight": 1.0 + 0.25 * len(shared_concepts),
                        "metadata": {"shared_concept_count": len(shared_concepts)},
                    }
                )
                incidences.append(
                    {"edge_id": he_flow_id, "node_id": prev_turn_nid, "role": "predecessor_turn", "position": 0}
                )
                incidences.append(
                    {"edge_id": he_flow_id, "node_id": turn_nid, "role": "successor_turn", "position": 1}
                )
                for s_idx, sc in enumerate(shared_concepts, start=2):
                    sc_slug = re.sub(r"[^a-z0-9_-]+", "_", sc.lower()).strip("_")
                    if sc_slug:
                        incidences.append(
                            {
                                "edge_id": he_flow_id,
                                "node_id": f"concept:{sc_slug}",
                                "role": "continuity_concept",
                                "position": s_idx,
                            }
                        )

        # N-ary Hyperedge 3: Concept Co-Occurrence Hyperedges (connects all turns in chat sharing a concept)
        for concept_nid, t_nids in concept_turns.items():
            unique_turns = list(dict.fromkeys(t_nids))
            if len(unique_turns) >= 2:
                he_concept_id = f"he:concept_cluster:{record.chat_id}:{concept_nid.split(':', 1)[1]}"
                edges.append(
                    {
                        "edge_id": he_concept_id,
                        "edge_type": "concept_cooccurrence",
                        "label": f"Concept Cluster: {nodes_map[concept_nid]['label']}",
                        "chat_id": record.chat_id,
                        "weight": float(len(unique_turns)),
                        "metadata": {"turn_Multiplicity": len(unique_turns)},
                    }
                )
                incidences.append(
                    {"edge_id": he_concept_id, "node_id": concept_nid, "role": "hub_concept", "position": 0}
                )
                incidences.append(
                    {"edge_id": he_concept_id, "node_id": conv_node_id, "role": "scope_conversation", "position": 1}
                )
                for pos, t_nid in enumerate(unique_turns, start=2):
                    incidences.append(
                        {"edge_id": he_concept_id, "node_id": t_nid, "role": "cooccurring_turn", "position": pos}
                    )

        # N-ary Hyperedge 4: Programming Language Clusters
        for lang, member_nids in lang_members.items():
            unique_members = list(dict.fromkeys(member_nids))
            he_lang_id = f"he:lang_cluster:{record.chat_id}:{lang}"
            edges.append(
                {
                    "edge_id": he_lang_id,
                    "edge_type": "code_language_cluster",
                    "label": f"Language Cluster: {lang}",
                    "chat_id": record.chat_id,
                    "weight": float(len(unique_members)),
                    "metadata": {"language": lang},
                }
            )
            incidences.append(
                {"edge_id": he_lang_id, "node_id": f"lang:{lang}", "role": "language_anchor", "position": 0}
            )
            for pos, m_nid in enumerate(unique_members, start=1):
                incidences.append(
                    {"edge_id": he_lang_id, "node_id": m_nid, "role": "language_member", "position": pos}
                )

        nodes_list = list(nodes_map.values())
        hypergraph_doc = {
            "schema_version": "GeminiConversationHypergraph-1.0",
            "chat_id": record.chat_id,
            "title": record.title,
            "generated_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
            "max_turns_limit_exceeded": record.max_turns_limit_exceeded,
            "reached_beginning_of_chat": record.reached_beginning_of_chat,
            "statistics": {
                "num_nodes": len(nodes_list),
                "num_hyperedges": len(edges),
                "num_incidences": len(incidences),
            },
            "nodes": nodes_list,
            "hyperedges": edges,
            "incidence": incidences,
        }
        return hypergraph_doc, nodes_list, edges, incidences


# ============================================================================
# Multi-Format Exporter (JSON, Hypergraph, MD, CSV, TXT, HTML, PDF + Manifest)
# ============================================================================

class MultiFormatExporter:
    """Exports a ConversationRecord into all archival + hypergraph formats and computes SHA-256 verification."""

    def __init__(self, output_root: pathlib.Path, db: ArchiveDatabase) -> None:
        self.output_root = output_root
        self.conversations_dir = output_root / "conversations"
        self.conversations_dir.mkdir(parents=True, exist_ok=True)
        self.db = db

    @staticmethod
    def sanitize_slug(text: str, max_len: int = 64) -> str:
        cleaned = re.sub(r"[^\w\s\-]", "", text, flags=re.UNICODE).strip()
        cleaned = re.sub(r"[\s_-]+", "_", cleaned)
        return (cleaned[:max_len].strip("_") or "untitled_chat").lower()

    def get_conversation_folder(self, record: ConversationRecord) -> pathlib.Path:
        slug = self.sanitize_slug(record.title)
        folder_name = f"{slug}__{record.chat_id}"
        folder = self.conversations_dir / folder_name
        folder.mkdir(parents=True, exist_ok=True)
        return folder

    def export_all_formats(
        self,
        record: ConversationRecord,
        pdf_renderer: Optional[Callable[[pathlib.Path, pathlib.Path], bool]] = None,
    ) -> pathlib.Path:
        folder = self.get_conversation_folder(record)
        prior = folder / "conversation.json"
        if prior.exists():
            previous = json.loads(prior.read_text(encoding="utf-8"))
            if previous.get("turns") and previous.get("turns") != [asdict(t) for t in record.turns]:
                stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
                history = folder / "previous_captures" / stamp
                history.mkdir(parents=True, exist_ok=True)
                for existing in folder.iterdir():
                    if existing.is_file():
                        shutil.copy2(existing, history / existing.name)
        record.finalize_topology_and_digest()

        # 1. JSON (Raw structured record + metadata + hashes + node/turn pointers)
        json_path = folder / "conversation.json"
        self._write_json(record, json_path)
        record.exported_files["json"] = str(json_path)
        self.db.record_exported_file(record.chat_id, "json", json_path)

        # 2. Hypergraph JSON (custom incidence standard nodes, n-ary hyperedges, and incidence list)
        hg_path = folder / "conversation_hypergraph.json"
        hg_doc, hg_nodes, hg_edges, hg_incidences = HypergraphBuilder.build_for_conversation(record)
        atomic_json(hg_path, hg_doc, ensure_ascii=False, reserve_bytes=DEFAULT_RESERVE_BYTES, trailing_newline=False)
        record.exported_files["hypergraph_json"] = str(hg_path)
        self.db.record_exported_file(record.chat_id, "hypergraph_json", hg_path)
        self.db.save_hypergraph_elements(record.chat_id, hg_nodes, hg_edges, hg_incidences)

        # 3. Markdown (.md)
        md_path = folder / "conversation.md"
        self._write_atomic(record, md_path, self._write_markdown)
        record.exported_files["markdown"] = str(md_path)
        self.db.record_exported_file(record.chat_id, "markdown", md_path)

        # 4. CSV (.csv)
        csv_path = folder / "conversation.csv"
        self._write_atomic(record, csv_path, self._write_csv)
        record.exported_files["csv"] = str(csv_path)
        self.db.record_exported_file(record.chat_id, "csv", csv_path)

        # 5. Plain Text (.txt)
        txt_path = folder / "conversation.txt"
        self._write_atomic(record, txt_path, self._write_txt)
        record.exported_files["txt"] = str(txt_path)
        self.db.record_exported_file(record.chat_id, "txt", txt_path)

        # 6. Standalone Offline HTML (.html)
        html_path = folder / "conversation.html"
        self._write_atomic(record, html_path, self._write_html)
        record.exported_files["html"] = str(html_path)
        self.db.record_exported_file(record.chat_id, "html", html_path)

        # 7. Paginated Printable PDF (.pdf)
        pdf_path = folder / "conversation.pdf"
        self._write_pdf_atomic(html_path, pdf_path, record, pdf_renderer)
        if pdf_path.exists():
            record.exported_files["pdf"] = str(pdf_path)
            self.db.record_exported_file(record.chat_id, "pdf", pdf_path)

        # Update JSON with all exported file paths
        self._write_json(record, json_path)
        self.db.record_exported_file(record.chat_id, "json", json_path)

        # Save to SQLite master database
        self.db.save_conversation(record, str(folder))
        self.db._sync_if_staged()
        return folder

    def _write_atomic(self, record: ConversationRecord, path: pathlib.Path, writer: Callable) -> None:
        with atomic_output(path) as temporary:
            writer(record, temporary)

    def _write_pdf_atomic(self, html_path, pdf_path, record, pdf_renderer=None):
        with atomic_output(pdf_path) as temporary:
            pdf_ok = False
            if pdf_renderer is not None:
                try:
                    pdf_ok = pdf_renderer(html_path, temporary)
                except OSError as exc:
                    if exc.errno == errno.ENOSPC:
                        raise
                except Exception:
                    pass
            if not pdf_ok:
                self._fallback_pdf_export(html_path, temporary, record)

    def _write_json(self, record: ConversationRecord, path: pathlib.Path) -> None:
        payload = asdict(record)
        atomic_json(path, payload, ensure_ascii=False, reserve_bytes=DEFAULT_RESERVE_BYTES, trailing_newline=False)

    def _write_markdown(self, record: ConversationRecord, path: pathlib.Path) -> None:
        lines = [
            f"# {record.title}",
            "",
            f"- **Chat ID**: `{record.chat_id}`",
            f"- **Source URL**: {record.url}",
            f"- **Scraped At (UTC)**: `{record.scraped_at}`",
            f"- **Total Turns**: {record.total_turns}",
            f"- **Top Appears Stable (Unverified)**: `{record.reached_beginning_of_chat}`",
            f"- **Max-Turns Limit Exceeded**: `{record.max_turns_limit_exceeded}`",
            f"- **Conversation SHA-256**: `{record.conversation_sha256}`",
            "",
        ]
        if record.max_turns_limit_exceeded and record.truncation_warning:
            lines.extend(
                [
                    f"> **⚠️ TRUNCATION WARNING**: {record.truncation_warning}",
                    "",
                ]
            )
        for turn in record.turns:
            lines.append(f"## Turn {turn.turn_index} (ID: `{turn.turn_id}` | Node: `{turn.node_id}`)")
            if turn.timestamp_hint:
                lines.append(f"*Timestamp: {turn.timestamp_hint}*")
            if turn.concepts:
                lines.append(f"*Hypergraph Concepts: {', '.join(f'`{c}`' for c in turn.concepts[:10])}*")
            lines.append("")
            lines.append("### User")
            lines.append(turn.user_prompt.strip() or "*(No text prompt / attachment only)*")
            lines.append("")
            if turn.attachments:
                lines.append("**Attachments:**")
                for att in turn.attachments:
                    lines.append(f"- `{att.name}` ({att.mime_type or 'file'}) {att.url}")
                lines.append("")
            if turn.model_thoughts.strip():
                lines.append("### Gemini Thinking / Reasoning")
                lines.append("```text")
                lines.append(turn.model_thoughts.strip())
                lines.append("```")
                lines.append("")
            lines.append("### Gemini")
            response = turn.model_response.strip() or "*(Empty response)*"
            for block in {cb.get("code", ""): cb for cb in turn.code_blocks}.values():
                code = block.get("code", "")
                if not code:
                    continue
                fence = "`" * max(3, max((len(m.group()) + 1 for m in re.finditer(r"`+", code)), default=3))
                language = re.sub(r"[^a-zA-Z0-9_+-]", "", block.get("language", ""))
                formatted = f"\n{fence}{language}\n{code}\n{fence}\n"
                response = response.replace(code, formatted, 1) if code in response else response + formatted
            lines.append(response)
            lines.append("")
            lines.append(f"<!-- Turn SHA-256: {turn.sha256} -->")
            lines.append("")

        path.write_text("\n".join(lines), encoding="utf-8")

    def _write_csv(self, record: ConversationRecord, path: pathlib.Path) -> None:
        with path.open("w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow([
                "chat_id",
                "chat_title",
                "turn_index",
                "turn_id",
                "node_id",
                "parent_turn_id",
                "next_turn_id",
                "timestamp_hint",
                "user_chars",
                "model_chars",
                "user_token_estimate",
                "model_token_estimate",
                "concepts_pipe_separated",
                "urls_pipe_separated",
                "user_prompt",
                "model_thoughts",
                "model_response",
                "code_blocks_count",
                "attachments_count",
                "turn_sha256",
            ])
            for t in record.turns:
                writer.writerow([
                    record.chat_id,
                    record.title,
                    t.turn_index,
                    t.turn_id,
                    t.node_id,
                    t.parent_turn_id,
                    t.next_turn_id,
                    t.timestamp_hint,
                    len(t.user_prompt),
                    len(t.model_response),
                    t.user_token_estimate,
                    t.model_token_estimate,
                    "|".join(t.concepts),
                    "|".join(t.urls),
                    t.user_prompt,
                    t.model_thoughts,
                    t.model_response,
                    len(t.code_blocks),
                    len(t.attachments),
                    t.sha256,
                ])

    def _write_txt(self, record: ConversationRecord, path: pathlib.Path) -> None:
        sep = "=" * 80
        subsep = "-" * 80
        lines = [
            sep,
            f"GEMINI ARCHIVE TRANSCRIPT: {record.title}",
            f"Chat ID           : {record.chat_id}",
            f"Source URL        : {record.url}",
            f"Scraped At (UTC)  : {record.scraped_at}",
            f"Total Turns       : {record.total_turns}",
            f"Reached Start     : {record.reached_beginning_of_chat}",
            f"Limit Exceeded    : {record.max_turns_limit_exceeded}",
            f"Verification Hash : {record.conversation_sha256}",
            sep,
            "",
        ]
        if record.max_turns_limit_exceeded and record.truncation_warning:
            lines.extend([f"WARNING: {record.truncation_warning}", sep, ""])

        for t in record.turns:
            lines.append(f"[TURN {t.turn_index} / {record.total_turns}] (ID: {t.turn_id} | Node: {t.node_id})")
            if t.timestamp_hint:
                lines.append(f"Timestamp: {t.timestamp_hint}")
            if t.concepts:
                lines.append(f"Concepts : {', '.join(t.concepts[:10])}")
            lines.append(subsep)
            lines.append("USER:")
            lines.append(t.user_prompt.strip() or "(No text prompt)")
            lines.append("")
            if t.model_thoughts.strip():
                lines.append("GEMINI THOUGHTS:")
                lines.append(t.model_thoughts.strip())
                lines.append("")
            lines.append("GEMINI:")
            lines.append(t.model_response.strip() or "(Empty response)")
            lines.append("")
            lines.append(f"Turn SHA-256: {t.sha256}")
            lines.append(sep)
            lines.append("")

        path.write_text("\n".join(lines), encoding="utf-8")

    def _write_html(self, record: ConversationRecord, path: pathlib.Path) -> None:
        warning_banner = ""
        if record.max_turns_limit_exceeded:
            warning_banner = f"""
            <div style="background:#fef2f2;border:2px solid #dc2626;color:#991b1b;padding:14px 18px;border-radius:10px;margin-bottom:20px;font-size:14px;">
                <strong>⚠️ Maximum Turn / Scroll Limit Exceeded:</strong> {html.escape(record.truncation_warning)}
            </div>
            """
        turns_html = []
        for t in record.turns:
            user_content = t.user_html.strip() if t.user_html.strip() else f"<pre class='plain'>{html.escape(t.user_prompt)}</pre>"
            model_content = t.model_html.strip() if t.model_html.strip() else f"<pre class='plain'>{html.escape(t.model_response)}</pre>"
            for att in t.attachments:
                if att.local_path and att.url:
                    user_content = user_content.replace(att.url, html.escape(att.local_path, quote=True))
            attachment_links = "".join(
                f"<p>Attachment: <a href='{html.escape(att.local_path, quote=True)}'>{html.escape(att.name)}</a></p>"
                if att.local_path else f"<p>Attachment unavailable offline: {html.escape(att.name)} — {html.escape(att.download_error)}</p>"
                for att in t.attachments
            )
            user_content += attachment_links
            thoughts_block = ""
            if t.model_thoughts.strip():
                thoughts_block = f"""
                <details class="thoughts">
                    <summary>Model Reasoning / Thoughts</summary>
                    <pre class="plain">{html.escape(t.model_thoughts)}</pre>
                </details>
                """
            concepts_chips = ""
            if t.concepts:
                chips = " ".join(f"<span class='chip'>{html.escape(c)}</span>" for c in t.concepts[:8])
                concepts_chips = f"<div class='chip-row'>{chips}</div>"

            turns_html.append(
                f"""
                <section class="turn" id="turn-{t.turn_index}">
                    <div class="turn-header">
                        <span class="turn-badge">Turn #{t.turn_index}</span>
                        <span class="turn-meta">Node: <code>{html.escape(t.node_id)}</code> {('• ' + html.escape(t.timestamp_hint)) if t.timestamp_hint else ''}</span>
                        <span class="turn-hash">SHA-256: {t.sha256[:16]}…</span>
                    </div>
                    <div class="message user-message">
                        <div class="role-label">User</div>
                        <div class="message-body">{user_content}</div>
                    </div>
                    <div class="message model-message">
                        <div class="role-label">Gemini</div>
                        {thoughts_block}
                        <div class="message-body">{model_content}</div>
                        {concepts_chips}
                    </div>
                </section>
                """
            )

        doc = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(record.title)} — Gemini Offline Archive</title>
<style>
  :root {{
    --bg: #f8fafc;
    --card: #ffffff;
    --border: #e2e8f0;
    --text: #0f172a;
    --muted: #475569;
    --accent: #1d4ed8;
    --user-bg: #eff6ff;
    --model-bg: #ffffff;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0;
    padding: 24px;
    font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", "Segoe UI", Roboto, sans-serif;
    background: var(--bg);
    color: var(--text);
    line-height: 1.6;
  }}
  .container {{ max-width: 960px; margin: 0 auto; }}
  header.archive-header {{
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 20px 24px;
    margin-bottom: 24px;
  }}
  header.archive-header h1 {{ margin: 0 0 10px 0; font-size: 22px; }}
  .meta-grid {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
    gap: 8px 16px;
    font-size: 13px;
    color: var(--muted);
  }}
  .turn {{
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 12px;
    margin-bottom: 18px;
    overflow: hidden;
    page-break-inside: avoid;
  }}
  .turn-header {{
    background: #f1f5f9;
    padding: 8px 16px;
    font-size: 12px;
    color: var(--muted);
    display: flex;
    justify-content: space-between;
    align-items: center;
    border-bottom: 1px solid var(--border);
  }}
  .turn-badge {{ font-weight: 700; color: var(--accent); }}
  .message {{ padding: 16px 20px; }}
  .user-message {{ background: var(--user-bg); border-bottom: 1px solid var(--border); }}
  .role-label {{
    font-size: 11px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    color: var(--muted);
    margin-bottom: 6px;
  }}
  .chip-row {{ margin-top: 12px; display: flex; flex-wrap: wrap; gap: 6px; }}
  .chip {{
    background: #f1f5f9;
    border: 1px solid #cbd5e1;
    border-radius: 999px;
    padding: 2px 10px;
    font-size: 11px;
    color: #334155;
  }}
  pre, pre.plain {{
    white-space: pre-wrap;
    word-wrap: break-word;
    background: #0f172a;
    color: #f8fafc;
    padding: 12px;
    border-radius: 8px;
    font-size: 13px;
    overflow-x: auto;
  }}
  .user-message pre.plain, .model-message pre.plain {{
    background: transparent;
    color: inherit;
    padding: 0;
    font-family: inherit;
    font-size: 14px;
  }}
  details.thoughts {{
    margin-bottom: 12px;
    background: #f8fafc;
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 8px 12px;
    font-size: 13px;
  }}
  @media print {{
    body {{ background: #fff; padding: 0; }}
    .container {{ max-width: 100%; }}
  }}
</style>
</head>
<body>
  <div class="container">
    {warning_banner}
    <header class="archive-header">
      <h1>{html.escape(record.title)}</h1>
      <div class="meta-grid">
        <div><strong>Chat ID:</strong> {html.escape(record.chat_id)}</div>
        <div><strong>Total Turns:</strong> {record.total_turns}</div>
        <div><strong>Scraped At:</strong> {html.escape(record.scraped_at)}</div>
        <div><strong>Reached First Turn:</strong> {'Top appears stable (unverified)' if record.reached_beginning_of_chat else 'Partial / interrupted'}</div>
        <div><strong>User Characters:</strong> {record.total_user_chars:,}</div>
        <div><strong>Gemini Characters:</strong> {record.total_model_chars:,}</div>
        <div style="grid-column: 1 / -1;"><strong>SHA-256 Digest:</strong> <code>{record.conversation_sha256}</code></div>
      </div>
    </header>
    {''.join(turns_html)}
  </div>
</body>
</html>
"""
        path.write_text(doc, encoding="utf-8")

    def _fallback_pdf_export(
        self, html_path: pathlib.Path, pdf_path: pathlib.Path, record: ConversationRecord
    ) -> None:
        chrome_candidates = [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
            "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
            shutil.which("chromium"),
            shutil.which("google-chrome"),
        ]
        for binary in chrome_candidates:
            if binary and os.path.exists(binary):
                try:
                    subprocess.run(
                        [
                            binary,
                            "--headless=new",
                            "--disable-gpu",
                            "--no-pdf-header-footer",
                            f"--print-to-pdf={str(pdf_path)}",
                            f"file://{str(html_path.resolve())}",
                        ],
                        check=True,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        timeout=120,
                    )
                    if pdf_path.exists() and pdf_path.stat().st_size > 0:
                        return
                except Exception:
                    continue

        self._write_minimal_pdf(pdf_path, record)

    @staticmethod
    def _write_minimal_pdf(pdf_path: pathlib.Path, record: ConversationRecord) -> None:
        import textwrap
        lines = [
            "TEXT FALLBACK PDF: Unicode is replaced where unsupported. Use JSON/HTML for full fidelity.",
            f"GEMINI ARCHIVE: {record.title}",
            f"Chat ID: {record.chat_id} | Turns: {record.total_turns} | SHA256: {record.conversation_sha256[:24]}",
            "-" * 90,
        ]
        for t in record.turns:
            lines.append(f"TURN {t.turn_index} USER:")
            for uline in (t.user_prompt or "").splitlines():
                lines.extend("  " + line for line in textwrap.wrap(uline, 95, replace_whitespace=False) or [""])
            lines.append(f"TURN {t.turn_index} GEMINI:")
            for mline in (t.model_response or "").splitlines():
                lines.extend("  " + line for line in textwrap.wrap(mline, 95, replace_whitespace=False) or [""])
            lines.append("")

        pages_lines = [lines[i : i + 48] for i in range(0, max(1, len(lines)), 48)]
        objects: List[bytes] = []

        page_obj_ids = []
        content_obj_ids = []
        next_id = 4
        for _ in pages_lines:
            page_obj_ids.append(next_id)
            content_obj_ids.append(next_id + 1)
            next_id += 2

        kids_str = " ".join(f"{pid} 0 R" for pid in page_obj_ids)
        objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
        objects.append(f"<< /Type /Pages /Kids [{kids_str}] /Count {len(page_obj_ids)} >>".encode("latin-1"))
        objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Courier >>")

        for idx, plines in enumerate(pages_lines):
            cid = content_obj_ids[idx]
            page_dict = (
                f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                f"/Resources << /Font << /F1 3 0 R >> >> /Contents {cid} 0 R >>"
            ).encode("latin-1")
            objects.append(page_dict)

            stream_cmds = ["BT", "/F1 9 Tf", "11 TL", "36 756 Td"]
            for line in plines:
                safe = (
                    line.encode("latin-1", errors="replace")
                    .decode("latin-1")
                    .replace("\\", "\\\\")
                    .replace("(", "\\(")
                    .replace(")", "\\)")
                )
                stream_cmds.append(f"({safe}) Tj T*")
            stream_cmds.append("ET")
            stream_data = "\n".join(stream_cmds).encode("latin-1")
            content_obj = (
                f"<< /Length {len(stream_data)} >>\nstream\n".encode("latin-1")
                + stream_data
                + b"\nendstream"
            )
            objects.append(content_obj)

        out = bytearray(b"%PDF-1.4\n")
        offsets = [0]
        for i, obj in enumerate(objects, start=1):
            offsets.append(len(out))
            out.extend(f"{i} 0 obj\n".encode("latin-1"))
            out.extend(obj)
            out.extend(b"\nendobj\n")

        xref_pos = len(out)
        out.extend(f"xref\n0 {len(objects) + 1}\n".encode("latin-1"))
        out.extend(b"0000000000 65535 f \n")
        for off in offsets[1:]:
            out.extend(f"{off:010d} 00000 n \n".encode("latin-1"))
        out.extend(
            f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF\n".encode(
                "latin-1"
            )
        )
        pdf_path.write_bytes(bytes(out))

    def write_master_manifest_and_index(self) -> Tuple[pathlib.Path, pathlib.Path, pathlib.Path]:
        """
        Writes:
          1. manifest.json     (cryptographic audit log + limit-exceeded warnings)
          2. hypergraph.json   (global account-wide cross-chat hypergraph in custom incidence format)
          3. index.html        (offline searchable dashboard with hypergraph & warning badges)
        """
        conversations = self.db.get_all_conversations()
        exceeded_chats = [c for c in conversations if int(c.get("max_turns_exceeded") or 0) == 1]

        global_hg = self.db.build_global_account_hypergraph()
        global_hg_path = self.output_root / "hypergraph.json"
        atomic_json(global_hg_path, global_hg, ensure_ascii=False, reserve_bytes=DEFAULT_RESERVE_BYTES, trailing_newline=False)

        with self.db._connect() as conn:
            file_ledger = [dict(row) for row in conn.execute("SELECT * FROM exported_files ORDER BY chat_id, format")]
        manifest = {
            "completeness_note": "Discovery and scroll stopping are heuristic. Hashes verify saved files, not account completeness. Attachments may remain remote URLs.",
            "exported_files": file_ledger,
            "generated_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
            "output_root": str(self.output_root),
            "global_hypergraph_file": str(global_hg_path),
            "hypergraph_statistics": global_hg["statistics"],
            "total_conversations": len(conversations),
            "completed_conversations": sum(1 for c in conversations if c["status"] == "completed"),
            "captured_unverified_conversations": sum(1 for c in conversations if c["status"] == "captured_unverified"),
            "conversations_exceeding_max_turns_limit": len(exceeded_chats),
            "exceeded_conversation_ids": [c["chat_id"] for c in exceeded_chats],
            "total_turns_archived": sum(int(c["total_turns"] or 0) for c in conversations),
            "total_user_chars": sum(int(c["total_user_chars"] or 0) for c in conversations),
            "total_model_chars": sum(int(c["total_model_chars"] or 0) for c in conversations),
            "conversations": conversations,
        }
        manifest_path = self.output_root / "manifest.json"
        atomic_json(manifest_path, manifest, ensure_ascii=False, reserve_bytes=DEFAULT_RESERVE_BYTES, trailing_newline=False)
        self.db._sync_if_staged()

        # Generate Offline Master Dashboard HTML
        warning_summary_html = ""
        if exceeded_chats:
            items_li = "".join(
                f"<li><strong>{html.escape(c['title'])}</strong> (<code>{html.escape(c['chat_id'])}</code>) — "
                f"captured {int(c['total_turns'] or 0):,} turns before hitting limit {int(c.get('configured_max_turns') or 5000):,}.</li>"
                for c in exceeded_chats
            )
            warning_summary_html = f"""
            <div style="background:#fef2f2;border:2px solid #dc2626;color:#991b1b;padding:16px 20px;border-radius:10px;margin-bottom:20px;">
              <strong>⚠️ ACTION NEEDED — {len(exceeded_chats)} Conversation(s) Hit the Max Turns / Scroll Ceiling!</strong>
              <p style="margin:6px 0;">Increase <code>--max-turns</code> / <strong>Max Turns Limit</strong> (e.g. from 5,000 to 15,000) and run the scraper again. It will automatically re-scrape only these truncated threads:</p>
              <ul style="margin:6px 0 0 20px;">{items_li}</ul>
            </div>
            """

        rows_html = []
        for c in conversations:
            folder_rel = ""
            if c.get("folder_path"):
                try:
                    folder_rel = str(pathlib.Path(c["folder_path"]).relative_to(self.output_root))
                except ValueError:
                    folder_rel = c["folder_path"]
            links = []
            if folder_rel:
                for ext, label in [
                    ("conversation.html", "HTML"),
                    ("conversation.pdf", "PDF"),
                    ("conversation.md", "MD"),
                    ("conversation.json", "JSON"),
                    ("conversation_hypergraph.json", "Hypergraph"),
                    ("conversation.csv", "CSV"),
                    ("conversation.txt", "TXT"),
                ]:
                    links.append(f"<a href='{html.escape(folder_rel)}/{ext}' target='_blank'>{label}</a>")

            exceeded = int(c.get("max_turns_exceeded") or 0) == 1
            verified_badge = (
                "<span style='color:#dc2626;font-weight:700;'>⚠️ LIMIT EXCEEDED (Increase Max Turns)</span>"
                if exceeded
                else ("<span style='color:#15803d;font-weight:600;'>Top stable (unverified)</span>" if c.get("reached_beginning") else "Partial")
            )
            rows_html.append(
                f"""
                <tr style="{'background:#fff1f2;' if exceeded else ''}">
                    <td><strong>{html.escape(c.get('title') or 'Untitled')}</strong><br><small><code>{html.escape(c['chat_id'])}</code></small></td>
                    <td>{html.escape(c.get('status', ''))}</td>
                    <td style="text-align:right;">{int(c.get('total_turns') or 0):,}</td>
                    <td style="text-align:right;">{int(c.get('total_user_chars') or 0) + int(c.get('total_model_chars') or 0):,}</td>
                    <td>{verified_badge}</td>
                    <td>{' | '.join(links)}</td>
                    <td><code>{(c.get('conversation_sha256') or '')[:16]}…</code></td>
                </tr>
                """
            )

        hg_stats = global_hg["statistics"]
        index_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Gemini Master Account Archive &amp; Hypergraph Index</title>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, sans-serif; margin: 28px; background: #f8fafc; color: #0f172a; }}
  h1 {{ margin-bottom: 6px; }}
  .summary {{ margin-bottom: 20px; color: #475569; font-size: 14px; line-height: 1.6; }}
  input#filter {{ width: 100%; max-width: 460px; padding: 10px 14px; border: 1px solid #cbd5e1; border-radius: 8px; margin-bottom: 16px; font-size: 14px; }}
  table {{ width: 100%; border-collapse: collapse; background: #fff; border-radius: 10px; overflow: hidden; border: 1px solid #e2e8f0; }}
  th, td {{ padding: 10px 14px; border-bottom: 1px solid #e2e8f0; text-align: left; font-size: 13px; }}
  th {{ background: #f1f5f9; font-weight: 600; }}
  a {{ color: #1d4ed8; text-decoration: none; font-weight: 600; }}
  a:hover {{ text-decoration: underline; }}
</style>
</head>
<body>
  <h1>Gemini Complete Account Archive &amp; Hypergraph</h1>
  <div class="summary">
    Conversations Captured (Unverified): <strong>{manifest['captured_unverified_conversations']} / {manifest['total_conversations']}</strong> •
    Total Turns Archived: <strong>{manifest['total_turns_archived']:,}</strong> •
    Total Characters: <strong>{manifest['total_user_chars'] + manifest['total_model_chars']:,}</strong><br>
    Global Hypergraph (<a href="hypergraph.json" target="_blank">hypergraph.json</a>):
    <strong>{hg_stats['total_nodes']:,} Nodes</strong> •
    <strong>{hg_stats['total_hyperedges']:,} N-ary Hyperedges</strong> •
    <strong>{hg_stats['total_incidences']:,} Incidences</strong>
  </div>
  {warning_summary_html}
  <input id="filter" type="text" placeholder="Filter conversations by title or ID..." onkeyup="filterRows()">
  <table id="archiveTable">
    <thead>
      <tr>
        <th>Title &amp; Chat ID</th>
        <th>Status</th>
        <th style="text-align:right;">Turns</th>
        <th style="text-align:right;">Total Chars</th>
        <th>History Capture Status</th>
        <th>Export Variants (incl. Hypergraph)</th>
        <th>SHA-256</th>
      </tr>
    </thead>
    <tbody>
      {''.join(rows_html)}
    </tbody>
  </table>
  <script>
    function filterRows() {{
      const q = document.getElementById('filter').value.toLowerCase();
      const rows = document.querySelectorAll('#archiveTable tbody tr');
      rows.forEach(r => {{
        r.style.display = r.innerText.toLowerCase().includes(q) ? '' : 'none';
      }});
    }}
  </script>
</body>
</html>
"""
        index_path = self.output_root / "index.html"
        with atomic_output(index_path, additional_bytes=len(index_html.encode("utf-8"))) as temporary:
            temporary.write_text(index_html, encoding="utf-8")
        return manifest_path, index_path, global_hg_path


# ============================================================================
# Playwright Deep Gemini Scraper Engine (1,000+ Turns + Max-Turns Alerting)
# ============================================================================

JS_DISCOVER_SIDEBAR_CHATS = r"""
() => {
    const results = [];
    const seen = new Set();
    const anchors = Array.from(document.querySelectorAll('a[href*="/app/"], a[href*="/chat/"]'));
    for (const a of anchors) {
        const href = a.getAttribute('href') || '';
        const match = href.match(/\/(?:app|chat)\/([a-zA-Z0-9_-]{8,})/);
        if (match && !seen.has(match[1])) {
            seen.add(match[1]);
            const rawTitle = (a.innerText || a.getAttribute('aria-label') || '').trim().replace(/\s+/g, ' ');
            results.push({
                chat_id: match[1],
                title: rawTitle || `Conversation ${match[1]}`,
                url: new URL(href, window.location.origin).href,
                is_pinned: Boolean(a.closest('[ class*="pinned" ], [data-test-id*="pinned"]'))
            });
        }
    }

    const items = Array.from(document.querySelectorAll('[data-test-id*="conversation"], .conversation-items-container [role="button"], side-navigation-content [role="listitem"]'));
    for (const el of items) {
        const link = el.querySelector('a[href]');
        if (link) continue;
        const jslog = el.getAttribute('jslog') || el.getAttribute('data-conversation-id') || '';
        const idMatch = jslog.match(/c_([a-zA-Z0-9]{10,})/) || jslog.match(/([a-f0-9]{16})/);
        if (idMatch && !seen.has(idMatch[1])) {
            seen.add(idMatch[1]);
            const title = (el.innerText || '').trim().split('\n')[0] || `Conversation ${idMatch[1]}`;
            results.push({
                chat_id: idMatch[1],
                title,
                url: `${window.location.origin}/app/${idMatch[1]}`,
                is_pinned: false
            });
        }
    }
    return results;
}
"""

JS_SCROLL_SIDEBAR = r"""
() => {
    const candidates = [
        document.querySelector('infinite-scroller[ class*="conversations" ]'),
        document.querySelector('side-navigation-content infinite-scroller'),
        document.querySelector('[data-test-id="conversations-list"]'),
        document.querySelector('mat-sidenav'),
        ...Array.from(document.querySelectorAll('div, nav, aside')).filter(el => {
            const rect = el.getBoundingClientRect();
            return rect.left < 100 && rect.width > 140 && rect.width < 480 && el.scrollHeight > el.clientHeight + 40;
        })
    ].filter(Boolean);

    let scrolled = false;
    for (const el of candidates) {
        const prev = el.scrollTop;
        el.scrollTop = el.scrollHeight;
        if (el.scrollTop !== prev) scrolled = true;
    }
    const buttons = Array.from(document.querySelectorAll('side-navigation-content button, mat-sidenav button, nav button'));
    for (const btn of buttons) {
        const txt = (btn.innerText || '').toLowerCase();
        if (txt.includes('more') || txt.includes('older') || txt.includes('show')) {
            try { btn.click(); scrolled = true; } catch (e) {}
        }
    }
    return scrolled;
}
"""

JS_SCROLL_CHAT_TO_TOP_STEP = r"""
() => {
    const turnContainers = document.querySelectorAll('div.conversation-container');
    const userQueries = document.querySelectorAll('user-query, [data-message-author-role="user"]');
    const turnNodes = turnContainers.length > 0 ? turnContainers : userQueries;
    const firstTurn = turnNodes.length > 0 ? turnNodes[0] : null;

    const scrollers = [];
    if (firstTurn) {
        let curr = firstTurn.parentElement;
        while (curr && curr !== document.body) {
            const style = window.getComputedStyle(curr);
            if (
                (style.overflowY === 'auto' || style.overflowY === 'scroll' || curr.tagName.includes('SCROLLER')) &&
                curr.scrollHeight > curr.clientHeight
            ) {
                scrollers.push(curr);
            }
            curr = curr.parentElement;
        }
    }
    const fallbackScrollers = Array.from(
        document.querySelectorAll('infinite-scroller, main, [role="main"], .chat-history-scroll-container')
    ).filter(el => el.scrollHeight > el.clientHeight);

    const allScrollers = [...new Set([...scrollers, ...fallbackScrollers])];

    for (const scroller of allScrollers) {
        scroller.scrollTop = 0;
        scroller.dispatchEvent(new Event('scroll', { bubbles: true }));
    }
    if (firstTurn && firstTurn.scrollIntoView) {
        firstTurn.scrollIntoView({ behavior: 'instant', block: 'start' });
    }
    window.scrollTo(0, 0);

    const topTurnText = firstTurn ? (firstTurn.innerText || '').slice(0, 160).trim() : '';
    // Ignore hidden indicators and unrelated sidebar/account activity.
    const chatRoot = allScrollers[0] || (firstTurn && firstTurn.closest('main, [role="main"]'));
    const loadingSpinner = Boolean(chatRoot && Array.from(
        chatRoot.querySelectorAll('mat-progress-spinner, [role="progressbar"], .loading-history-indicator')
    ).some(el => {
        const style = window.getComputedStyle(el);
        return el.getClientRects().length > 0 && style.display !== 'none' &&
            style.visibility !== 'hidden' && style.opacity !== '0' &&
            !el.closest('[hidden], [aria-hidden="true"]');
    }));

    return {
        estimatedTurnCount: turnNodes.length,
        topTurnPreview: topTurnText,
        loadingSpinner,
        scrollerHeight: allScrollers[0] ? allScrollers[0].scrollHeight : document.body.scrollHeight
    };
}
"""

JS_HYDRATE_TURN_SLOT = r"""
(slotIndex) => {
    const containers = Array.from(document.querySelectorAll('div.conversation-container'));
    const c = containers[slotIndex];
    if (!c) {
        return { exists: false, totalSlots: containers.length, hydrated: false };
    }
    try {
        c.scrollIntoView({ behavior: 'instant', block: 'center' });
    } catch (e) {}
    const userEl = c.querySelector('user-query, .user-query-container, [data-message-author-role="user"]');
    const modelEl = c.querySelector('model-response, .model-response-container, [data-message-author-role="model"]');
    const msgContentEl = modelEl ? (modelEl.querySelector('message-content, .markdown') || modelEl) : null;
    const uInner = userEl ? (userEl.innerText || '').trim() : '';
    const mInner = msgContentEl ? (msgContentEl.innerText || '').trim() : (modelEl ? (modelEl.innerText || '').trim() : '');
    const uHtmlLen = userEl ? (userEl.innerHTML || '').length : 0;
    const mHtmlLen = msgContentEl ? (msgContentEl.innerHTML || '').length : (modelEl ? (modelEl.innerHTML || '').length : 0);
    return {
        exists: true,
        totalSlots: containers.length,
        hydrated: (uInner.length > 0 || mInner.length > 0),
        userTextLen: uInner.length,
        modelTextLen: mInner.length,
        userHtmlLen: uHtmlLen,
        modelHtmlLen: mHtmlLen
    };
}
"""

JS_EXPAND_THOUGHTS_AND_EXTRACT_TURNS = r"""
() => {
    const toggleButtons = Array.from(document.querySelectorAll('button[aria-expanded="false"], mat-expansion-panel-header'));
    for (const btn of toggleButtons) {
        const label = (btn.innerText || btn.getAttribute('aria-label') || '').toLowerCase();
        if (btn.getAttribute('aria-expanded') !== 'true' && (label.includes('thought') || label.includes('thinking') || label.includes('reasoning'))) {
            try { btn.click(); } catch (e) {}
        }
    }

    const extractSafeText = (el) => {
        if (!el) return '';
        const painted = (el.innerText || '').trim();
        if (painted.length > 0) return painted;
        // Fallback for CSS content-visibility: auto / off-screen Angular containers where
        // innerText returns "" even though the DOM subtree is present.
        try {
            const clone = el.cloneNode(true);
            clone.querySelectorAll(
                'script, style, noscript, svg, template, button, mat-icon, gem-icon, ' +
                '.cdk-visually-hidden, .screen-reader-user-query-label, .luminous-toggle-container, .code-block-decoration'
            ).forEach(n => n.remove());
            return (clone.textContent || '').replace(/\n{3,}/g, '\n\n').trim();
        } catch (e) {
            return (el.textContent || '').trim();
        }
    };

    const containers = Array.from(document.querySelectorAll('div.conversation-container'));
    const turns = [];

    const extractCodeBlocks = (root) => {
        if (!root) return [];
        return Array.from(root.querySelectorAll('pre, code-block')).map(cb => ({
            language: (cb.getAttribute('data-language') || cb.className || '').replace('language-', '').trim(),
            code: extractSafeText(cb)
        })).filter((c, i, all) => c.code.length > 0 && all.findIndex(x => x.code === c.code) === i);
    };

    const extractAttachments = (root) => {
        if (!root) return [];
        const list = [];
        const imgs = Array.from(root.querySelectorAll('img[src]'));
        for (const img of imgs) {
            const src = img.getAttribute('src') || '';
            if (src && !src.startsWith('data:image/svg')) {
                list.push({
                    name: img.getAttribute('alt') || 'image',
                    url: src,
                    mime_type: 'image/*'
                });
            }
        }
        const files = Array.from(root.querySelectorAll('[data-test-id*="attachment"], .attachment-chip, .file-preview'));
        for (const f of files) {
            list.push({
                name: (f.innerText || f.textContent || 'attachment').trim(),
                url: '',
                mime_type: 'application/octet-stream'
            });
        }
        return list;
    };

    if (containers.length > 0) {
        containers.forEach((c, idx) => {
            const userEl = c.querySelector('user-query, .user-query-container, [data-message-author-role="user"]');
            const modelEl = c.querySelector('model-response, .model-response-container, [data-message-author-role="model"]');
            const thoughtsEl = c.querySelector('model-thoughts, .thoughts-container, [data-test-id*="thoughts"]');
            const msgContentEl = modelEl ? (modelEl.querySelector('message-content, .markdown') || modelEl) : null;

            const userText = extractSafeText(userEl);
            const userHtml = userEl ? userEl.innerHTML : '';
            const modelText = msgContentEl ? extractSafeText(msgContentEl) : extractSafeText(modelEl);
            const modelHtml = msgContentEl ? msgContentEl.innerHTML : (modelEl ? modelEl.innerHTML : '');
            const thoughtsText = extractSafeText(thoughtsEl);

            turns.push({
                turn_index: idx + 1,
                turn_id: c.getAttribute('data-turn-id') || c.getAttribute('data-message-id') || c.id || (userEl && userEl.id) || `turn_${idx + 1}`,
                user_prompt: userText,
                user_html: userHtml,
                model_response: modelText,
                model_html: modelHtml,
                model_thoughts: thoughtsText,
                code_blocks: extractCodeBlocks(modelEl || c),
                attachments: extractAttachments(userEl || c),
                timestamp_hint: c.getAttribute('data-timestamp') || ''
            });
        });
        return {
            pageTitle: document.title || '',
            totalDomSlots: containers.length,
            turns
        };
    }

    const seqNodes = Array.from(
        document.querySelectorAll('user-query, model-response, [data-message-author-role="user"], [data-message-author-role="model"]')
    );
    let currentTurn = null;
    for (const node of seqNodes) {
        const tag = node.tagName.toLowerCase();
        const role = node.getAttribute('data-message-author-role') || (tag.includes('user') ? 'user' : 'model');
        if (role === 'user') {
            if (currentTurn) turns.push(currentTurn);
            currentTurn = {
                turn_index: turns.length + 1,
                turn_id: node.id || `turn_${turns.length + 1}`,
                user_prompt: (node.innerText || '').trim(),
                user_html: node.innerHTML || '',
                model_response: '',
                model_html: '',
                model_thoughts: '',
                code_blocks: [],
                attachments: extractAttachments(node),
                timestamp_hint: ''
            };
        } else {
            if (!currentTurn) {
                currentTurn = {
                    turn_index: turns.length + 1,
                    turn_id: node.id || `turn_${turns.length + 1}`,
                    user_prompt: '',
                    user_html: '',
                    model_response: '',
                    model_html: '',
                    model_thoughts: '',
                    code_blocks: [],
                    attachments: [],
                    timestamp_hint: ''
                };
            }
            const thoughtsEl = node.querySelector('model-thoughts, .thoughts-container');
            const msgEl = node.querySelector('message-content, .markdown') || node;
            currentTurn.model_response = (currentTurn.model_response + '\n' + (msgEl.innerText || '').trim()).trim();
            currentTurn.model_html += msgEl.innerHTML || '';
            if (thoughtsEl) {
                currentTurn.model_thoughts = (thoughtsEl.innerText || '').trim();
            }
            currentTurn.code_blocks = extractCodeBlocks(node);
        }
    }
    if (currentTurn) turns.push(currentTurn);

    return {
        pageTitle: document.title || '',
        turns
    };
}
"""


def merge_turn_snapshot(storage: Dict[str, Dict[str, Any]], order: List[str], turns: List[Dict[str, Any]]) -> None:
    """Keep turns across virtualized DOM windows; insert newly loaded older turns before overlaps."""
    keys = []
    occurrences: Dict[str, int] = collections.defaultdict(int)
    for turn in turns:
        tid = str(turn.get("turn_id") or "")
        if not tid or re.fullmatch(r"turn_\d+", tid):
            content = json.dumps([turn.get("user_prompt", ""), turn.get("model_response", "")], ensure_ascii=False)
            base = hashlib.sha256(content.encode()).hexdigest()
            occurrences[base] += 1
            tid = f"content:{base}:{occurrences[base]}"
        keys.append(tid)
        existing = storage.get(tid)
        merged = dict(turn, turn_id=tid)
        if existing:
            for text_field,html_field in (('user_prompt','user_html'),('model_response','model_html')):
                if not str(merged.get(text_field) or '').strip() and str(existing.get(text_field) or '').strip():
                    merged[text_field]=existing[text_field]
                    merged[html_field]=existing.get(html_field) or merged.get(html_field,'')
            # Virtualized placeholders must not erase bodies captured while rendered.
            for field in ('user_prompt', 'user_html', 'model_response', 'model_html', 'model_thoughts', 'timestamp_hint'):
                value = merged.get(field)
                if (not isinstance(value, str) or not value.strip()) and existing.get(field):
                    merged[field] = existing[field]
            for field in ('attachments', 'code_blocks'):
                if not merged.get(field) and existing.get(field):
                    merged[field] = existing[field]
        storage[tid] = merged
    for index in range(len(keys)):
        key = keys[index]
        if key not in order:
            successor = next((k for k in keys[index + 1:] if k in order), None)
            order.insert(order.index(successor) if successor else len(order), key)


class GeminiScraperEngine:
    """
    Controls a logged-in Chromium/Chrome browser via Playwright, intercepts
    Gemini's internal batchexecute network RPC responses, scrolls the sidebar
    to discover all chats, scrolls each conversation upward until the very first
    turn is loaded, and triggers macOS + GUI notifications if any chat exceeds
    the configured max_turns or max_scroll_steps threshold.
    """

    def __init__(
        self,
        output_dir: pathlib.Path,
        profile_dir: pathlib.Path,
        cdp_url: Optional[str] = None,
        log_fn: Optional[Callable[[str], None]] = None,
        progress_fn: Optional[Callable[[int, int, str], None]] = None,
        limit_alert_fn: Optional[Callable[[ConversationRecord], None]] = None,
    ) -> None:
        self.output_dir = output_dir
        self.profile_dir = profile_dir
        self.cdp_url = cdp_url
        self.log = log_fn or (lambda msg: print(f"[{dt.datetime.now().strftime('%H:%M:%S')}] {msg}"))
        self.progress = progress_fn or (lambda cur, tot, status: None)
        self.limit_alert_fn = limit_alert_fn
        self.db = ArchiveDatabase(output_dir / "archive.db")
        self.exporter = MultiFormatExporter(output_dir, self.db)
        self._stop_requested = False
        self.exceeded_records: List[ConversationRecord] = []

    def request_stop(self) -> None:
        self._stop_requested = True

    async def run_full_archive(
        self,
        force_rescrape: bool = False,
        max_turns_per_chat: int = 5000,
        max_scroll_Attempts_per_chat: int = 2500,
        specific_urls: Optional[List[str]] = None,
    ) -> Tuple[pathlib.Path, pathlib.Path, pathlib.Path]:
        if max_turns_per_chat < 1 or max_scroll_Attempts_per_chat < 1:
            raise ValueError("Turn and scroll limits must be positive.")
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:
            raise RuntimeError(
                "Playwright is not installed yet. Run `./setup_and_run_mac.sh` first to install Playwright."
            ) from exc

        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        self.exceeded_records.clear()

        # Automatically ensure max_scroll_Attempts_per_chat is scaled to support max_turns_per_chat
        effective_scroll_steps = max(max_scroll_Attempts_per_chat, (max_turns_per_chat // 2) + 500)

        async with async_playwright() as p:
            browser = None
            if self.cdp_url:
                self.log(f"Connecting to existing Chrome instance via CDP: {self.cdp_url}")
                browser = await p.chromium.connect_over_cdp(self.cdp_url)
                context = browser.contexts[0] if browser.contexts else await browser.new_context()
            else:
                self.log(f"Launching persistent Chrome profile at: {self.profile_dir}")
                context = await p.chromium.launch_persistent_context(
                    user_data_dir=str(self.profile_dir),
                    headless=False,
                    channel="chrome" if pathlib.Path("/Applications/Google Chrome.app").exists() else None,
                    viewport={"width": 1440, "height": 960},
                    args=[
                        "--disable-blink-features=AutomationControlled",
                        "--disable-features=IsolateOrigins,site-per-process",
                    ],
                )

            page = await context.new_page()

            self.log("Opening https://gemini.google.com/app ...")
            await page.goto("https://gemini.google.com/app", wait_until="domcontentloaded", timeout=90000)
            await asyncio.sleep(3.0)

            await self._wait_for_authentication(page)

            if specific_urls:
                discovered = []
                for u in specific_urls:
                    m = re.search(r"/(?:app|chat)/([a-zA-Z0-9_-]{8,})", u)
                    cid = m.group(1) if m else hashlib.sha1(u.encode()).hexdigest()[:16]
                    discovered.append({"chat_id": cid, "title": f"Conversation {cid}", "url": u, "is_pinned": False})
                self.db.register_sidebar_conversations(discovered)
            else:
                await self._discover_all_sidebar_chats(page)

            pending = self.db.get_pending_conversations(force_rescrape=force_rescrape)
            if specific_urls:
                selected_ids = {item["chat_id"] for item in discovered}
                pending = [item for item in pending if item["chat_id"] in selected_ids]
            total = len(pending)
            self.log(
                f"Total conversations queued to archive: {total} "
                f"(Max Turns Ceiling: {max_turns_per_chat:,} | Max Scroll Steps: {effective_scroll_steps:,})"
            )

            idx = 0
            for idx, conv_meta in enumerate(pending, start=1):
                if self._stop_requested:
                    self.log("Stop requested by user — saving progress cleanly.")
                    break

                chat_id = conv_meta["chat_id"]
                title = conv_meta["title"]
                url = conv_meta["url"]
                self.progress(idx - 1, total, f"Scraping [{idx}/{total}]: {title}")
                self.log(f"--- [{idx}/{total}] Scraping '{title}' ({chat_id}) ---")

                try:
                    record = await self._scrape_single_conversation(
                        page=page,
                        chat_id=chat_id,
                        initial_title=title,
                        url=url,
                        is_pinned=bool(conv_meta.get("is_pinned")),
                        max_turns_limit=max_turns_per_chat,
                        max_scroll_steps=effective_scroll_steps,
                    )

                    await self._download_attachments(page, record)
                    folder = await self._export_with_playwright_pdf(context, record)

                    if record.max_turns_limit_exceeded:
                        self.exceeded_records.append(record)
                        warn_banner = (
                            f"⚠️ MAX TURNS / SCROLL LIMIT EXCEEDED on '{record.title}' ({record.chat_id})! "
                            f"Captured {record.total_turns:,} turns (Limit: {max_turns_per_chat:,}), "
                            f"but older turns still remain in this chat. Increase the 5,000 limit (e.g. to {max_turns_per_chat * 2:,}+) "
                            f"and re-run to automatically resume & complete this chat."
                        )
                        self.log(warn_banner)
                        send_macos_limit_exceeded_notification(
                            title="⚠️ Gemini Archiver: Max Turns Exceeded!",
                            message=f"'{record.title}' hit {record.total_turns:,} turns without reaching the start. Increase Max Turns above {max_turns_per_chat:,}!",
                        )
                        if self.limit_alert_fn is not None:
                            self.limit_alert_fn(record)
                    else:
                        self.log(
                            f"✔ Saved '{record.title}' ({record.total_turns:,} turns, "
                            f"reached_start={record.reached_beginning_of_chat}) -> {folder.name}"
                        )
                except Exception as exc:
                    err_str = f"{type(exc).__name__}: {exc}"
                    self.log(f"✖ Error scraping {chat_id}: {err_str}")
                    self.db.mark_error(chat_id, err_str)

            manifest_path, index_path, global_hg_path = self.exporter.write_master_manifest_and_index()
            self.progress(idx if total else 0, total, f"Capture {'stopped' if self._stop_requested else 'finished; review completeness'}. Index: {index_path}")
            self.log(f"Master verification manifest written to: {manifest_path}")
            self.log(f"Global account hypergraph written to   : {global_hg_path}")
            self.log(f"Master offline dashboard written to    : {index_path}")

            if self.exceeded_records:
                summary_msg = (
                    f"⚠️ {len(self.exceeded_records)} conversation(s) exceeded the {max_turns_per_chat:,} turn ceiling. "
                    f"They are marked 'needs_higher_limit' in archive.db so raising the limit and re-running will re-scrape them automatically."
                )
                self.log(summary_msg)
                send_macos_limit_exceeded_notification(
                    title=f"⚠️ {len(self.exceeded_records)} Chat(s) Exceeded {max_turns_per_chat:,} Turns",
                    message="Increase Max Turns in Gemini Archiver and re-run to capture the remaining history.",
                )

            if browser:
                await page.close()
            else:
                await context.close()

            if not self._stop_requested:
                try:
                    from metadata_enrichment import enrich_archive
                    self.log("Recovering metadata from the saved network responses...")
                    enrich_archive(self.output_dir, log_fn=self.log, progress_fn=self.progress)
                except Exception as exc:
                    self.log(f"Metadata enrichment needs attention: {type(exc).__name__}: {exc}. Existing chat exports are saved.")
            return manifest_path, index_path, global_hg_path

    async def _wait_for_authentication(self, page: Any, stop_requested=None) -> None:
        self.log("Waiting for the Gemini chat interface. Sign in in the Chrome window if requested.")
        for attempt in range(180):
            if self._stop_requested or (stop_requested and stop_requested()):
                raise InterruptedError("Stopped while waiting for login.")
            sign_in = await page.get_by_role("link", name=re.compile(r"^sign in$", re.I)).count()
            composer = await page.locator('rich-textarea [contenteditable="true"], textarea, [role="textbox"][contenteditable="true"]').count()
            if "gemini.google.com" in page.url and composer and not sign_in:
                return
            await asyncio.sleep(2.0)
        raise RuntimeError("Timed out waiting for Gemini login. Sign in manually, then retry.")

    async def _discover_all_sidebar_chats(self, page: Any) -> None:
        self.log("Expanding sidebar and scrolling through entire chat history list...")
        try:
            menu_btn = page.locator(
                'button[aria-label*="Main menu"], button[aria-label*="Expand menu"], [data-test-id="side-nav-menu-button"]'
            ).first
            if await menu_btn.count() > 0:
                await menu_btn.click(timeout=3000)
                await asyncio.sleep(1.0)
        except Exception:
            pass

        stagnant_rounds = 0
        total_known = 0

        for step in range(1, 600):
            if self._stop_requested:
                break

            items = await page.evaluate(JS_DISCOVER_SIDEBAR_CHATS)
            newly_added = self.db.register_sidebar_conversations(items)
            current_total = len(items)

            if current_total > total_known or newly_added > 0:
                total_known = max(total_known, current_total)
                stagnant_rounds = 0
                if step % 3 == 1 or newly_added > 0:
                    self.log(f"  Sidebar scan step {step}: {total_known} conversations discovered so far...")
            else:
                stagnant_rounds += 1

            scrolled = await page.evaluate(JS_SCROLL_SIDEBAR)
            await asyncio.sleep(0.85)

            if stagnant_rounds >= 12 and not scrolled:
                break
            if stagnant_rounds >= 20:
                break

        all_convs = self.db.get_all_conversations()
        self.log(f"Sidebar discovery finished: {len(all_convs)} total conversations indexed in SQLite.")

    async def _scrape_single_conversation(
        self,
        page: Any,
        chat_id: str,
        initial_title: str,
        url: str,
        is_pinned: bool,
        max_turns_limit: int = 5000,
        max_scroll_steps: int = 3000,
    ) -> ConversationRecord:
        """
        Navigates to a single Gemini conversation, scrolls to the very top to load
        all turns, and detects if the thread exceeds `max_turns_limit` or `max_scroll_steps`
        before reaching the true beginning of the conversation.
        """
        captured_rpc_blobs: List[Dict[str, Any]] = []
        rpc_tasks = set()

        async def _on_response(response: Any) -> None:
            try:
                if "batchexecute" in response.url and response.status == 200:
                    body = await response.text()
                    if len(body) > 200:
                        captured_rpc_blobs.append({"rpc_payload": body, "observed_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(), "response_path": response.url.split("?", 1)[0], "http_status": response.status})
            except Exception:
                pass

        def _schedule_response(response: Any) -> None:
            task = asyncio.create_task(_on_response(response))
            rpc_tasks.add(task)
            task.add_done_callback(rpc_tasks.discard)

        page.on("response", _schedule_response)
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=90000)
            await asyncio.sleep(2.5)

            stagnant_top_checks = 0
            last_turn_count = -1
            last_top_preview = ""
            scroll_step = 0
            reached_beginning = False
            hit_turn_ceiling = False
            stalled_loading = False
            snapshots: Dict[str, Dict[str, Any]] = {}
            ordered_ids: List[str] = []

            for scroll_step in range(1, max_scroll_steps + 1):
                if self._stop_requested:
                    break

                state = await page.evaluate(JS_SCROLL_CHAT_TO_TOP_STEP)
                snapshot = await page.evaluate(JS_EXPAND_THOUGHTS_AND_EXTRACT_TURNS)
                merge_turn_snapshot(snapshots, ordered_ids, snapshot.get("turns") or [])
                est_turns = len(ordered_ids)
                if scroll_step % 10 == 0 or scroll_step == 1:
                    checkpoint_dir = self.output_dir / "checkpoints"
                    checkpoint_dir.mkdir(parents=True, exist_ok=True)
                    checkpoint = checkpoint_dir / f"{MultiFormatExporter.sanitize_slug(chat_id)}.json"
                    atomic_json(checkpoint, {"chat_id": chat_id, "title": initial_title, "url": url, "capture_status": "interrupted", "reached_beginning_of_chat": False, "turns": [snapshots[key] for key in ordered_ids]}, ensure_ascii=False, reserve_bytes=0, indent=None, trailing_newline=False)
                top_preview = state.get("topTurnPreview") or ""
                spinner = bool(state.get("loadingSpinner"))

                # Check if estimated turns in DOM exceeded the user's configured max_turns_limit
                if est_turns >= max_turns_limit:
                    hit_turn_ceiling = True
                    break

                if est_turns == last_turn_count and top_preview == last_top_preview:
                    stagnant_top_checks += 1
                else:
                    stagnant_top_checks = 0
                    if scroll_step % 10 == 0 or (est_turns - last_turn_count) >= 10:
                        self.log(
                            f"    [Scroll #{scroll_step}] Loaded ~{est_turns:,} turns in DOM "
                            f"(oldest preview: {top_preview[:48]!r}...)"
                        )
                    last_turn_count = est_turns
                    last_top_preview = top_preview

                await asyncio.sleep(1.1 if spinner else 0.55)

                if stagnant_top_checks >= 14 and est_turns > 0:
                    if not spinner:
                        reached_beginning = True
                        self.log(f"    No older turns appeared in {stagnant_top_checks} checks; exporting {est_turns:,} captured turns (completeness unverified).")
                        break
                    if stagnant_top_checks == 14:
                        self.log("    Oldest turn is unchanged; allowing extra time for the visible loading indicator...")
                    if stagnant_top_checks >= 40:
                        stalled_loading = True
                        self.log("    Loading indicator remains active without new turns after 40 checks; saving an unverified capture and moving on.")
                        break

            # Incremental top-to-bottom scroll-and-hydrate pass: walk every Angular DOM turn slot
            # with scrollIntoView + settle wait + bounded retries so virtualized / content-visibility
            # containers hydrate non-empty innerText before extraction.
            try:
                total_slots = int(await page.evaluate("() => document.querySelectorAll('div.conversation-container').length"))
            except Exception:
                total_slots = 0

            if total_slots > 0:
                hydrated_slots = 0
                for slot_idx in range(total_slots):
                    if self._stop_requested:
                        break
                    slot_ok = False
                    for attempt in range(3):
                        slot_res = await page.evaluate(JS_HYDRATE_TURN_SLOT, slot_idx)
                        if not slot_res or not slot_res.get("exists"):
                            break
                        if slot_res.get("hydrated"):
                            slot_ok = True
                            break
                        await asyncio.sleep(0.12 * (attempt + 1))
                    if slot_ok:
                        hydrated_slots += 1
                    # Snapshot periodically while scrolled into viewport so virtualized windows cannot unload text
                    if (slot_idx + 1) % 10 == 0 or slot_idx == total_slots - 1:
                        mid_snap = await page.evaluate(JS_EXPAND_THOUGHTS_AND_EXTRACT_TURNS)
                        merge_turn_snapshot(snapshots, ordered_ids, mid_snap.get("turns") or [])
                self.log(f"    Scroll-and-hydrate pass: {hydrated_slots}/{total_slots} DOM slots painted with non-empty innerText.")

            extracted = await page.evaluate(JS_EXPAND_THOUGHTS_AND_EXTRACT_TURNS)
            merge_turn_snapshot(snapshots, ordered_ids, extracted.get("turns") or [])
            extracted["turns"] = [snapshots[key] for key in ordered_ids]
        finally:
            try:
                page.remove_listener("response", _schedule_response)
            except Exception:
                pass
            if rpc_tasks:
                await asyncio.gather(*list(rpc_tasks), return_exceptions=True)

        raw_turns = extracted.get("turns") or []
        page_title = (extracted.get("pageTitle") or "").replace(" - Google Gemini", "").replace("Gemini - ", "").strip()
        final_title = initial_title
        if (not final_title or final_title.startswith("Conversation ")) and page_title and page_title != "Gemini":
            final_title = page_title

        if not raw_turns:
            raise RuntimeError("No turns found. Check login, chat access, or Gemini page selectors; this chat was not marked complete.")

        def _fallback_text_from_html(raw_html_str: str) -> str:
            if not raw_html_str or not raw_html_str.strip():
                return ""
            cleaned = re.sub(r"<(?:script|style|svg|noscript|button|mat-icon|gem-icon)\b[^>]*>.*?</(?:script|style|svg|noscript|button|mat-icon|gem-icon)>", " ", raw_html_str, flags=re.IGNORECASE | re.DOTALL)
            cleaned = re.sub(r"<(?:br|p|div|li|h[1-6]|tr|pre|blockquote)\b[^>]*>", "\n", cleaned, flags=re.IGNORECASE)
            cleaned = re.sub(r"<[^>]+>", " ", cleaned)
            cleaned = html.unescape(cleaned)
            lines = [re.sub(r"[ \t]+", " ", ln).strip() for ln in cleaned.splitlines()]
            return "\n".join(ln for ln in lines if ln and ln not in {"You said", "Gemini said", "Copy", "Edit"}).strip()

        turns: List[ChatTurn] = []
        for idx, rt in enumerate(raw_turns, start=1):
            atts = [
                TurnAttachment(
                    name=a.get("name", "attachment"),
                    url=a.get("url", ""),
                    mime_type=a.get("mime_type", ""),
                )
                for a in (rt.get("attachments") or [])
            ]
            u_html = rt.get("user_html") or ""
            m_html = rt.get("model_html") or ""
            u_prompt = (rt.get("user_prompt") or "").strip() or _fallback_text_from_html(u_html)
            m_resp = (rt.get("model_response") or "").strip() or _fallback_text_from_html(m_html)
            t = ChatTurn(
                turn_index=idx,
                turn_id=str(rt.get("turn_id") or f"turn_{idx}"),
                user_prompt=u_prompt,
                user_html=u_html,
                model_response=m_resp,
                model_html=m_html,
                model_thoughts=rt.get("model_thoughts") or "",
                code_blocks=rt.get("code_blocks") or [],
                attachments=atts,
                timestamp_hint=rt.get("timestamp_hint") or "",
            )
            turns.append(t)

        # Compute hydrated_turns / total_dom_slots and flag PARTIAL_VIRTUALIZATION loudly
        total_dom_slots = max(len(turns), int(extracted.get("totalDomSlots") or len(turns)))
        hydrated_turns = sum(1 for t in turns if (t.user_prompt or "").strip() or (t.model_response or "").strip())
        partial_virtualization = hydrated_turns < total_dom_slots
        self.log(f"    Hydration completeness: hydrated_turns={hydrated_turns}/{total_dom_slots} ({(hydrated_turns / total_dom_slots * 100.0) if total_dom_slots else 0.0:.1f}%)")
        if partial_virtualization:
            self.log(f"    [WARN][PARTIAL_VIRTUALIZATION] Conversation '{final_title}' ({chat_id}) left {total_dom_slots - hydrated_turns} empty turn slots after scroll-and-hydrate!")

        # Determine if maximum turns or scroll limit was exceeded before reaching the start of the thread
        limit_exceeded = bool(
            hit_turn_ceiling
            or (len(turns) >= max_turns_limit and not reached_beginning)
            or (scroll_step >= max_scroll_steps and not reached_beginning and len(turns) > 0)
        )
        trunc_warn = ""
        if limit_exceeded:
            trunc_warn = (
                f"Conversation '{final_title}' ({chat_id}) reached {len(turns):,} turns / {scroll_step:,} scroll steps "
                f"without reaching the very first turn (configured Max Turns Limit = {max_turns_limit:,}, "
                f"Max Scroll Steps = {max_scroll_steps:,}). Increase the Max Turns number (e.g. to {max_turns_limit * 2:,}) "
                f"and re-run to capture the complete thread."
            )
        elif partial_virtualization:
            trunc_warn = f"PARTIAL_VIRTUALIZATION: hydrated_turns={hydrated_turns}/{total_dom_slots}; empty DOM stubs remain."

        capture_status_val = (
            "interrupted"
            if self._stop_requested
            else ("PARTIAL_VIRTUALIZATION" if partial_virtualization else "captured_unverified")
        )
        record = ConversationRecord(
            chat_id=chat_id,
            title=final_title or f"Conversation {chat_id}",
            url=url,
            scraped_at=dt.datetime.now(dt.timezone.utc).isoformat(),
            total_turns=len(turns),
            total_user_chars=sum(len(t.user_prompt) for t in turns),
            total_model_chars=sum(len(t.model_response) for t in turns),
            is_pinned=is_pinned,
            scroll_iterations=scroll_step,
            reached_beginning_of_chat=reached_beginning and not limit_exceeded,
            max_turns_limit_exceeded=limit_exceeded,
            configured_max_turns=max_turns_limit,
            configured_max_scroll_steps=max_scroll_steps,
            truncation_warning=trunc_warn,
            turns=turns,
            capture_status=capture_status_val,
            completeness_note=(
                f"PARTIAL_VIRTUALIZATION ({hydrated_turns}/{total_dom_slots} hydrated)."
                if partial_virtualization
                else (
                    "Stopped by user; older turns may remain."
                    if self._stop_requested
                    else "Loading stalled: no older turns appeared in 40 checks while a loading indicator remained visible. Older turns may remain; retry this capture."
                    if stalled_loading
                    else f"Hydrated {hydrated_turns}/{total_dom_slots} DOM slots; top stability is a heuristic, not independent verification."
                )
            ),
            raw_rpc_payloads_captured=len(captured_rpc_blobs),
        )
        record.finalize_topology_and_digest()

        folder = self.exporter.get_conversation_folder(record)
        snapshot_path = folder / "dom_capture.json"
        snapshot_path.write_text(json.dumps(extracted, ensure_ascii=False, indent=2), encoding="utf-8")
        record.exported_files["dom_capture_json"] = str(snapshot_path)
        self.db.record_exported_file(chat_id, "dom_capture_json", snapshot_path)
        if captured_rpc_blobs:
            folder = self.exporter.get_conversation_folder(record)
            rpc_path = folder / "raw_network_rpc_payloads.jsonl"
            with rpc_path.open("w", encoding="utf-8") as f:
                for blob in captured_rpc_blobs:
                    f.write(json.dumps(blob, ensure_ascii=False) + "\n")
            record.exported_files["raw_rpc_jsonl"] = str(rpc_path)
            self.db.record_exported_file(chat_id, "raw_rpc_jsonl", rpc_path)

        return record

    async def _download_attachments(self, page: Any, record: ConversationRecord) -> None:
        """Use the signed-in browser's request context for exposed HTTP attachment URLs."""
        folder = self.exporter.get_conversation_folder(record)
        cache: Dict[str, str] = {}
        failures = 0
        for turn in record.turns:
            for attachment in turn.attachments:
                if self._stop_requested:
                    attachment.download_error = "Stopped before download."
                    failures += 1
                    continue
                if attachment.url in cache:
                    attachment.local_path = cache[attachment.url]
                    continue
                response = None
                try:
                    parsed = urllib.parse.urlparse(attachment.url)
                    if parsed.scheme not in ("http", "https"):
                        raise ValueError("No downloadable HTTP URL was exposed by Gemini.")
                    response = await page.request.get(attachment.url, timeout=30000)
                    if not response.ok:
                        raise RuntimeError(f"HTTP {response.status}")
                    content_type = response.headers.get("content-type", "").split(";", 1)[0]
                    if content_type == "text/html":
                        raise RuntimeError("Server returned an HTML page instead of an attachment.")
                    body = await response.body()
                    if not body:
                        raise RuntimeError("Server returned an empty attachment.")
                    suffixes = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp", "application/pdf": ".pdf", "image/gif": ".gif"}
                    suffix = suffixes.get(content_type, ".bin")
                    relative = pathlib.Path("attachments") / (hashlib.sha256(body).hexdigest() + suffix)
                    target = folder / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(body)
                    attachment.local_path = str(relative)
                    attachment.mime_type = content_type or attachment.mime_type
                    cache[attachment.url] = str(relative)
                    self.db.record_exported_file(record.chat_id, f"attachment:{target.name}", target)
                except Exception as exc:
                    attachment.download_error = str(exc)
                    failures += 1
                    self.log(f"Attachment not downloaded: {attachment.name}: {exc}")
                finally:
                    if response is not None:
                        await response.dispose()
        if failures:
            record.completeness_note += f" {failures} attachment(s) could not be downloaded; inspect download_error fields."

    async def _export_with_playwright_pdf(self, context: Any, record: ConversationRecord) -> pathlib.Path:
        folder = self.exporter.export_all_formats(record, pdf_renderer=lambda source, target: (self.exporter._write_minimal_pdf(target, record) or True))
        html_path = folder / "conversation.html"
        pdf_path = folder / "conversation.pdf"

        try:
            pdf_page = await context.new_page()
            await pdf_page.goto(f"file://{html_path.resolve()}", wait_until="load", timeout=60000)
            expected_pdf = file_sha(pdf_path)
            try:
                with atomic_output(pdf_path, expected_sha256=expected_pdf) as temporary:
                    await pdf_page.pdf(
                        path=str(temporary),
                        format="A4",
                        print_background=True,
                        margin={"top": "14mm", "bottom": "14mm", "left": "12mm", "right": "12mm"},
                    )
            finally:
                await pdf_page.close()
            record.exported_files["pdf"] = str(pdf_path)
            self.db.record_exported_file(record.chat_id, "pdf", pdf_path)
        except Exception:
            pass

        return folder


# ============================================================================
# Offline Local Importer (Normalizes JSON files into 7 formats + Hypergraph)
# ============================================================================

def import_local_json_or_takeout_folder(
    input_path: pathlib.Path,
    output_dir: pathlib.Path,
    log_fn: Optional[Callable[[str], None]] = None,
) -> Tuple[pathlib.Path, pathlib.Path, pathlib.Path]:
    log = log_fn or print
    db = ArchiveDatabase(output_dir / "archive.db")
    exporter = MultiFormatExporter(output_dir, db)

    json_files = [input_path] if input_path.is_file() else list(input_path.rglob("*.json"))
    log(f"Found {len(json_files)} JSON file(s) to normalize into all formats + hypergraph...")

    for jf in json_files:
        if jf.name in ("manifest.json", "hypergraph.json", "conversation_hypergraph.json"):
            continue
        try:
            data = json.loads(jf.read_text(encoding="utf-8"))
        except Exception:
            continue

        if isinstance(data, dict) and str(data.get("schema_version", "")).startswith("GeminiMetadata"):
            continue
        if isinstance(data, dict) and "turns" in data and "chat_id" in data:
            turns = []
            for idx, td in enumerate(data["turns"], start=1):
                t = ChatTurn(
                    turn_index=idx,
                    turn_id=str(td.get("turn_id") or f"turn_{idx}"),
                    user_prompt=td.get("user_prompt", ""),
                    user_html=td.get("user_html", ""),
                    model_response=td.get("model_response", ""),
                    model_html=td.get("model_html", ""),
                    model_thoughts=td.get("model_thoughts", ""),
                    code_blocks=td.get("code_blocks", []),
                    attachments=[TurnAttachment(**a) for a in td.get("attachments", [])],
                    timestamp_hint=td.get("timestamp_hint", ""),
                )
                turns.append(t)

            rec = ConversationRecord(
                chat_id=str(data["chat_id"]),
                title=str(data.get("title") or f"Conversation {data['chat_id']}"),
                url=str(data.get("url") or f"https://gemini.google.com/app/{data['chat_id']}"),
                scraped_at=str(data.get("scraped_at") or dt.datetime.now(dt.timezone.utc).isoformat()),
                total_turns=len(turns),
                total_user_chars=sum(len(x.user_prompt) for x in turns),
                total_model_chars=sum(len(x.model_response) for x in turns),
                is_pinned=bool(data.get("is_pinned", False)),
                scroll_iterations=int(data.get("scroll_iterations", 0)),
                reached_beginning_of_chat=bool(data.get("reached_beginning_of_chat", True)),
                max_turns_limit_exceeded=bool(data.get("max_turns_limit_exceeded", False)),
                configured_max_turns=int(data.get("configured_max_turns", 5000)),
                truncation_warning=str(data.get("truncation_warning", "")),
                capture_status=str(data.get("capture_status") or "captured_unverified"),
                completeness_note=str(data.get("completeness_note") or "Imported file; completeness is unverified."),
                turns=turns,
            )
            folder = exporter.export_all_formats(rec)
            log(f"✔ Exported '{rec.title}' ({rec.total_turns} turns + hypergraph) -> {folder}")

    return exporter.write_master_manifest_and_index()


# ============================================================================
# Native macOS Desktop GUI (Tkinter / ttk) with Max-Turns Alert Banner & Popup
# ============================================================================

class GeminiArchiverMacGUI:
    """Native macOS GUI for configuring, running, monitoring, and verifying the Gemini Archive & Hypergraph."""

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Gemini Complete Account Archiver & Hypergraph Builder (macOS)")
        self.root.geometry("1060x820")

        default_out = _default_archive_dir()
        default_profile = _default_profile_dir()

        self.output_dir_var = tk.StringVar(value=str(default_out))
        self.profile_dir_var = tk.StringVar(value=str(default_profile))
        self.cdp_url_var = tk.StringVar(value="")
        self.force_rescrape_var = tk.BooleanVar(value=False)
        self.max_turns_var = tk.IntVar(value=5000)
        self.max_scroll_var = tk.IntVar(value=3000)
        self.status_var = tk.StringVar(value="Ready. Click 'Start Full Account Scrape' to launch Chrome & archive.")
        self.alert_banner_var = tk.StringVar(value="")

        self.log_queue: "queue.Queue[str]" = queue.Queue()
        self.progress_queue: "queue.Queue[Tuple[int, int, str]]" = queue.Queue()
        self.done_queue: "queue.Queue[bool]" = queue.Queue()
        self.limit_alert_queue: "queue.Queue[ConversationRecord]" = queue.Queue()
        self.engine: Optional[GeminiScraperEngine] = None
        self.worker_thread: Optional[threading.Thread] = None
        self._metadata_stop = threading.Event()
        self.audit_media_var = tk.BooleanVar(value=True)
        self.history_auto_var = tk.BooleanVar(value=True)
        self.project_history = None
        self._history_operation_id = None
        self._history_last_progress = None
        self._history_sync_thread = None
        self._history_last_sync = 0.0
        self._activate_history(default_out)

        self._build_ui()
        self.root.after(150, self._poll_queues)
        self.root.protocol("WM_DELETE_WINDOW", self._close_app)

    def _close_app(self) -> None:
        server = getattr(self, '_graph_server', None)
        try:
            if server is not None:
                server.close()
        finally:
            self.root.destroy()

    def _build_ui(self) -> None:
        main = ttk.Frame(self.root, padding=14)
        main.pack(fill=tk.BOTH, expand=True)

        title_lbl = ttk.Label(
            main,
            text="Gemini Complete Account Archiver & Hypergraph Exporter",
            font=("-apple-system", 17, "bold"),
        )
        title_lbl.pack(anchor=tk.W, pady=(0, 4))

        sub_lbl = ttk.Label(
            main,
            text="Archives Gemini chats to JSON, graph JSON, Markdown, CSV, TXT, HTML, PDF and SQLite. Completeness requires review.",
            font=("-apple-system", 11),
        )
        sub_lbl.pack(anchor=tk.W, pady=(0, 10))

        # High-visibility red warning banner (hidden until a chat exceeds max_turns)
        self.alert_banner_label = tk.Label(
            main,
            textvariable=self.alert_banner_var,
            bg="#fee2e2",
            fg="#991b1b",
            font=("-apple-system", 11, "bold"),
            padx=12,
            pady=8,
            anchor="w",
            justify=tk.LEFT,
            wraplength=900,
        )

        cfg = ttk.LabelFrame(main, text="Archive, Turn Ceiling & Browser Configuration", padding=12)
        cfg.pack(fill=tk.X, pady=(0, 10))

        row0 = ttk.Frame(cfg)
        row0.pack(fill=tk.X, pady=3)
        ttk.Label(row0, text="Archive Output Folder:", width=22).pack(side=tk.LEFT)
        ttk.Entry(row0, textvariable=self.output_dir_var).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=6)
        ttk.Button(row0, text="Browse…", command=self._choose_output_dir).pack(side=tk.LEFT)

        row1 = ttk.Frame(cfg)
        row1.pack(fill=tk.X, pady=3)
        ttk.Label(row1, text="Persistent Login Profile:", width=22).pack(side=tk.LEFT)
        ttk.Entry(row1, textvariable=self.profile_dir_var).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=6)
        ttk.Button(row1, text="Browse…", command=self._choose_profile_dir).pack(side=tk.LEFT)

        row2 = ttk.Frame(cfg)
        row2.pack(fill=tk.X, pady=3)
        ttk.Label(row2, text="Max Turns Limit / Chat:", width=22).pack(side=tk.LEFT)
        ttk.Spinbox(row2, from_=100, to=100000, increment=500, textvariable=self.max_turns_var, width=10).pack(
            side=tk.LEFT, padx=6
        )
        ttk.Label(row2, text="Max Scroll Steps:").pack(side=tk.LEFT, padx=(12, 4))
        ttk.Spinbox(row2, from_=100, to=50000, increment=500, textvariable=self.max_scroll_var, width=10).pack(
            side=tk.LEFT, padx=6
        )
        ttk.Checkbutton(
            row2,
            text="Force Re-scrape Completed Chats",
            variable=self.force_rescrape_var,
        ).pack(side=tk.LEFT, padx=14)

        row3 = ttk.Frame(cfg)
        row3.pack(fill=tk.X, pady=3)
        ttk.Label(row3, text="Optional Chrome CDP URL:", width=22).pack(side=tk.LEFT)
        ttk.Entry(row3, textvariable=self.cdp_url_var).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=6)
        ttk.Label(row3, text="(Leave blank to launch persistent Chrome window)").pack(side=tk.LEFT)

        btn_bar = ttk.Frame(main)
        btn_bar.pack(fill=tk.X, pady=8)

        self.start_btn = ttk.Button(
            btn_bar, text="▶ Start Full Account Scrape", command=self._start_scrape
        )
        self.start_btn.pack(side=tk.LEFT, padx=(0, 8))

        self.stop_btn = ttk.Button(
            btn_bar, text="⏹ Stop & Save Progress", command=self._stop_scrape, state=tk.DISABLED
        )
        self.stop_btn.pack(side=tk.LEFT, padx=(0, 8))

        ttk.Button(
            btn_bar, text="📂 Open Archive Folder in Finder", command=self._open_in_finder
        ).pack(side=tk.LEFT, padx=(0, 8))

        ttk.Button(
            btn_bar, text="🌐 Open Master HTML Dashboard", command=self._open_dashboard
        ).pack(side=tk.LEFT)

        metadata_bar = ttk.Frame(main)
        metadata_bar.pack(fill=tk.X, pady=(0, 6))
        ttk.Button(metadata_bar, text="Enrich Saved Metadata", command=self._start_metadata).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(metadata_bar, text="Fetch Missing Metadata", command=lambda: self._start_metadata(live=True)).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(metadata_bar, text="Open Metadata Tables", command=self._open_metadata_outputs).pack(side=tk.LEFT)

        direct_bar = ttk.Frame(main)
        direct_bar.pack(fill=tk.X, pady=(0, 6))
        ttk.Label(direct_bar, text="Direct history (trial):").pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(direct_bar, text="Test Direct Fetch", command=lambda: self._start_metadata(direct_mode="probe")).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(direct_bar, text="Fetch Metadata Directly", command=lambda: self._start_metadata(direct_mode="fetch")).pack(side=tk.LEFT)

        audit_bar = ttk.Frame(main)
        audit_bar.pack(fill=tk.X, pady=(0, 6))
        ttk.Button(audit_bar, text="Local Dataset Audit", command=self._start_audit).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(audit_bar, text="Audit Account & Enrich", command=lambda: self._start_audit(live=True)).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(audit_bar, text="Open Audit Report", command=self._open_audit_report).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Checkbutton(audit_bar, text="Download exposed media", variable=self.audit_media_var).pack(side=tk.LEFT)

        history_bar = ttk.Frame(main)
        history_bar.pack(fill=tk.X, pady=(0, 6))
        ttk.Button(history_bar, text="Project History", command=self._open_project_history).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(history_bar, text="Sync Thread Now", command=self._sync_project_history).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(history_bar, text="Add Project Note", command=self._add_project_note).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(history_bar, text="Register Thread…", command=self._register_history_thread).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Checkbutton(history_bar, text="Auto-sync while open", variable=self.history_auto_var).pack(side=tk.LEFT)

        graph_bar = ttk.Frame(main)
        graph_bar.pack(fill=tk.X, pady=(0, 6))
        ttk.Button(graph_bar, text="Explore Hypergraph", command=self._open_hypergraph).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(graph_bar, text="Rebuild Hypergraph", command=lambda: self._open_hypergraph(rebuild=True)).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Label(graph_bar, text="Interactive map and text queries · opens locally in your browser").pack(side=tk.LEFT)

        prog_frame = ttk.Frame(main)
        prog_frame.pack(fill=tk.X, pady=(4, 8))
        self.progress_bar = ttk.Progressbar(prog_frame, orient=tk.HORIZONTAL, mode="determinate")
        self.progress_bar.pack(fill=tk.X)
        ttk.Label(prog_frame, textvariable=self.status_var, font=("-apple-system", 11, "bold")).pack(
            anchor=tk.W, pady=(4, 0)
        )

        log_frame = ttk.LabelFrame(main, text="Live Scraper, Hypergraph & Limit Verification Log", padding=8)
        log_frame.pack(fill=tk.BOTH, expand=True)
        self.log_box = scrolledtext.ScrolledText(
            log_frame,
            wrap=tk.WORD,
            font=("Menlo", 11),
            bg="#0f172a",
            fg="#f8fafc",
            insertbackground="#f8fafc",
        )
        self.log_box.pack(fill=tk.BOTH, expand=True)

    def _choose_output_dir(self) -> None:
        chosen = filedialog.askdirectory(initialdir=self.output_dir_var.get())
        if chosen:
            self.output_dir_var.set(chosen)

    def _choose_profile_dir(self) -> None:
        chosen = filedialog.askdirectory(initialdir=self.profile_dir_var.get())
        if chosen:
            self.profile_dir_var.set(chosen)

    def _activate_history(self, dataset_root) -> None:
        from project_history import ProjectHistory
        dataset_root = pathlib.Path(dataset_root).expanduser().resolve()
        if self.project_history and self.project_history.dataset_root == dataset_root:
            return
        try:
            self.project_history = ProjectHistory(dataset_root)
        except Exception as exc:
            self.project_history = None
            self.log_queue.put(f"Project history unavailable: {type(exc).__name__}: {exc}")

    def _history_event(self, kind, payload) -> None:
        if self.project_history:
            try:
                self.project_history.append(kind, payload)
            except Exception as exc:
                self.log_queue.put(f"Project history write failed: {type(exc).__name__}: {exc}")
                self.project_history = None

    def _begin_history_operation(self, dataset_root, kind, configuration=None) -> None:
        import uuid
        self._activate_history(dataset_root)
        self._history_operation_id = str(uuid.uuid4())
        self._history_last_progress = None
        self._history_event('operation.started', {'operation_id':self._history_operation_id,'kind':kind,'interface':'GUI','configuration':configuration or {},'dataset_root':str(pathlib.Path(dataset_root).resolve())})

    def _sync_project_history(self) -> None:
        if self._history_sync_thread and self._history_sync_thread.is_alive():
            return
        if not self._history_operation_id:
            self._activate_history(pathlib.Path(self.output_dir_var.get()))
        store = self.project_history
        self._history_last_sync = time.monotonic()
        if not store:
            return
        def target():
            try:
                result = store.sync()
                store.export()
                if result['new_messages']:
                    self.log_queue.put(f"Project history synced: {result['new_messages']} new visible message version(s).")
                for warning in result['warnings']:
                    self.log_queue.put(f"Project history: {warning}")
            except Exception as exc:
                self.log_queue.put(f"Project history sync: {type(exc).__name__}: {exc}")
        self._history_sync_thread = threading.Thread(target=target,daemon=True)
        self._history_sync_thread.start()

    def _open_project_history(self) -> None:
        self._activate_history(pathlib.Path(self.output_dir_var.get()))
        if not self.project_history:
            return
        try:
            self.project_history.sync()
            self.project_history.export()
            subprocess.run(['open',str(self.project_history.root/'index.html')],check=False)
        except Exception as exc:
            messagebox.showerror('Project history',str(exc))

    def _register_history_thread(self) -> None:
        selected = filedialog.askopenfilename(title='Register this project’s Codex rollout JSONL',
            initialdir=str(pathlib.Path.home()/'.codex'/'sessions'),filetypes=[('JSONL conversation','*.jsonl')])
        if not selected:
            return
        self._activate_history(pathlib.Path(self.output_dir_var.get()))
        try:
            if not self.project_history:
                raise RuntimeError('Project history is unavailable; see log.')
            self.project_history.register_codex(pathlib.Path(selected))
            self._sync_project_history()
        except Exception as exc:
            messagebox.showerror('Register project thread',str(exc))

    def _add_project_note(self) -> None:
        self._activate_history(pathlib.Path(self.output_dir_var.get()))
        if not self.project_history:
            return
        store = self.project_history
        window = tk.Toplevel(self.root)
        window.title('Append a project note')
        ttk.Label(window,text='Notes are labeled separately from conversation messages and appended to the history.').pack(padx=12,pady=10)
        editor = scrolledtext.ScrolledText(window,width=88,height=18,wrap=tk.WORD)
        editor.pack(fill=tk.BOTH,expand=True,padx=12,pady=6)
        def save():
            try:
                store.note(editor.get('1.0',tk.END),actor='user')
                store.export()
                window.destroy()
            except Exception as exc:
                messagebox.showerror('Project note',str(exc),parent=window)
        ttk.Button(window,text='Append Note',command=save).pack(pady=10)

    def _enqueue_log(self, msg: str) -> None:
        stamp = dt.datetime.now().strftime("%H:%M:%S")
        self.log_queue.put(f"[{stamp}] {msg}")
        self._history_event('application.log', {'message':str(msg),'operation_id':self._history_operation_id,'source':'GUI'})

    def _enqueue_progress(self, cur: int, tot: int, status: str) -> None:
        self.progress_queue.put((cur, tot, status))
        self._history_last_progress = {'current':cur,'total':tot,'status':status}
        self._history_event('operation.progress', dict(self._history_last_progress,operation_id=self._history_operation_id))

    def _enqueue_limit_alert(self, record: ConversationRecord) -> None:
        self.limit_alert_queue.put(record)

    def _poll_queues(self) -> None:
        if self.history_auto_var.get() and time.monotonic()-self._history_last_sync >= 5:
            self._sync_project_history()
        while not self.done_queue.empty():
            self.done_queue.get_nowait()
            self._on_worker_done()
        while not self.log_queue.empty():
            line = self.log_queue.get_nowait()
            self.log_box.insert(tk.END, line + "\n")
            self.log_box.see(tk.END)

        while not self.progress_queue.empty():
            cur, tot, status = self.progress_queue.get_nowait()
            if tot > 0:
                self.progress_bar["maximum"] = tot
                self.progress_bar["value"] = cur
            self.status_var.set(status)

        while not self.limit_alert_queue.empty():
            rec = self.limit_alert_queue.get_nowait()
            banner_txt = (
                f"⚠️ MAX TURNS EXCEEDED: '{rec.title}' hit {rec.total_turns:,} turns (Limit: {rec.configured_max_turns:,}) "
                f"without reaching the beginning of the chat! Increase 'Max Turns Limit / Chat' above {rec.configured_max_turns:,} "
                f"(e.g. to {rec.configured_max_turns * 2:,}) and click Start again."
            )
            self.alert_banner_var.set(banner_txt)
            self.alert_banner_label.pack(fill=tk.X, pady=(0, 10), before=self.log_box.master)

        self.root.after(150, self._poll_queues)

    def _start_scrape(self) -> None:
        if self.worker_thread and self.worker_thread.is_alive():
            return

        try:
            if int(self.max_turns_var.get()) < 1 or int(self.max_scroll_var.get()) < 1:
                raise ValueError("Limits must be positive integers.")
        except (ValueError, tk.TclError):
            messagebox.showerror("Invalid limits", "Enter positive whole numbers for both limits.")
            return
        out_dir = pathlib.Path(self.output_dir_var.get()).expanduser().resolve()
        prof_dir = pathlib.Path(self.profile_dir_var.get()).expanduser().resolve()
        cdp = self.cdp_url_var.get().strip() or None
        force = bool(self.force_rescrape_var.get())
        max_turns = int(self.max_turns_var.get())
        max_scroll = int(self.max_scroll_var.get())

        self.alert_banner_var.set("")
        self.alert_banner_label.pack_forget()

        self._begin_history_operation(out_dir, "full_account_scrape", {"max_turns":max_turns,"max_scroll_steps":max_scroll,"force_rescrape":force})
        self.engine = GeminiScraperEngine(
            output_dir=out_dir,
            profile_dir=prof_dir,
            cdp_url=cdp,
            log_fn=self._enqueue_log,
            progress_fn=self._enqueue_progress,
            limit_alert_fn=self._enqueue_limit_alert,
        )

        self.start_btn.config(state=tk.DISABLED)
        self.stop_btn.config(state=tk.NORMAL)

        def _target() -> None:
            try:
                asyncio.run(
                    self.engine.run_full_archive(
                        force_rescrape=force,
                        max_turns_per_chat=max_turns,
                        max_scroll_Attempts_per_chat=max_scroll,
                    )
                )
            except Exception as exc:
                self._enqueue_log(f"FATAL ERROR: {exc}")
            finally:
                self.done_queue.put(True)

        self.worker_thread = threading.Thread(target=_target, daemon=True)
        self.worker_thread.start()

    def _start_metadata(self, live: bool = False, direct_mode: Optional[str] = None) -> None:
        if self.worker_thread and self.worker_thread.is_alive():
            return
        from metadata_enrichment import enrich_archive, refresh_missing_metadata
        out_dir = pathlib.Path(self.output_dir_var.get()).expanduser().resolve()
        profile = pathlib.Path(self.profile_dir_var.get()).expanduser().resolve()
        cdp = self.cdp_url_var.get().strip() or None
        try:
            max_steps = int(self.max_scroll_var.get())
            if max_steps < 1:
                raise ValueError()
        except (ValueError, tk.TclError):
            messagebox.showerror("Invalid limit", "Max Scroll Steps must be a positive whole number.")
            return
        self._begin_history_operation(out_dir, "direct_"+direct_mode if direct_mode else "metadata_refresh" if live else "local_metadata_enrichment", {"live":live,"direct_mode":direct_mode,"max_scroll_steps":max_steps,"direct_page_size":50,"direct_max_pages":1000})
        self.engine = None
        self._metadata_stop.clear()
        self.start_btn.config(state=tk.DISABLED)
        self.stop_btn.config(state=tk.NORMAL)
        self.status_var.set("Recovering metadata from saved responses...")
        def target() -> None:
            try:
                if direct_mode:
                    from direct_history import direct_metadata_refresh
                    result = asyncio.run(direct_metadata_refresh(
                        out_dir, profile, probe=direct_mode == "probe", cdp_url=cdp,
                        log_fn=self._enqueue_log, progress_fn=self._enqueue_progress,
                        stop_requested=self._metadata_stop.is_set))
                else:
                    result = enrich_archive(out_dir, log_fn=self._enqueue_log, progress_fn=self._enqueue_progress,
                                            stop_requested=self._metadata_stop.is_set)
                    if live and not self._metadata_stop.is_set():
                        result = asyncio.run(refresh_missing_metadata(
                            out_dir, profile, cdp_url=cdp, log_fn=self._enqueue_log,
                            progress_fn=self._enqueue_progress, stop_requested=self._metadata_stop.is_set,
                            max_scroll_steps=max_steps))
                if direct_mode == "probe":
                    report = result.get('direct_fetch_report', {})
                    rows = report.get('results', [])
                    successful = bool(rows and rows[0].get('validated'))
                    self._enqueue_progress(1, 1, "Direct probe passed local comparison; see log/report." if successful else "Direct probe not validated; see log/report. Existing exports preserved.")
                    return
                stats = result['statistics']
                self._enqueue_progress(stats['turns_with_timestamp'], stats['turns'],
                    f"Metadata: {stats['turns_with_timestamp']:,}/{stats['turns']:,} turns have server timestamps. Open Metadata Tables for results.")
            except InterruptedError as exc:
                self._enqueue_log(str(exc))
                self._enqueue_progress(0, 0, "Metadata task stopped. Published results and original exports preserved.")
            except Exception as exc:
                self._enqueue_log(f"METADATA ERROR: {type(exc).__name__}: {exc}")
                self._enqueue_progress(0, 0, "Metadata task failed; see log. Original exports preserved.")
            finally:
                self.done_queue.put(True)
        self.worker_thread = threading.Thread(target=target, daemon=True)
        self.worker_thread.start()

    def _start_audit(self, live: bool = False) -> None:
        if self.worker_thread and self.worker_thread.is_alive():
            return
        from dataset_audit import local_audit, account_audit
        root = pathlib.Path(self.output_dir_var.get()).expanduser().resolve()
        profile = pathlib.Path(self.profile_dir_var.get()).expanduser().resolve()
        cdp = self.cdp_url_var.get().strip() or None
        media = bool(self.audit_media_var.get())
        self._begin_history_operation(root, "account_audit" if live else "local_audit", {"include_media":media,"resume":True,"max_pages":1000,"page_size":50})
        self.engine = None
        self._metadata_stop.clear()
        self.start_btn.config(state=tk.DISABLED)
        self.stop_btn.config(state=tk.NORMAL)
        self.status_var.set("Auditing saved data; original exports are preserved...")
        def target() -> None:
            try:
                if live:
                    result = asyncio.run(account_audit(root, profile, cdp_url=cdp, log_fn=self._enqueue_log,
                        progress_fn=self._enqueue_progress, stop_requested=self._metadata_stop.is_set, include_media=media))
                else:
                    result = local_audit(root, log_fn=self._enqueue_log, stop_requested=self._metadata_stop.is_set)
                count = sum(result['findings_by_severity'].values())
                self._enqueue_progress(1, 1, f"Audit {result['status']}: {count} findings. Click Open Audit Report.")
            except Exception as exc:
                self._enqueue_log(f"AUDIT ERROR: {type(exc).__name__}: {exc}")
                self._enqueue_progress(0, 0, "Audit needs attention; see log. Original exports preserved.")
            finally:
                self.done_queue.put(True)
        self.worker_thread = threading.Thread(target=target, daemon=True)
        self.worker_thread.start()

    def _open_hypergraph(self, rebuild=False) -> None:
        from hypergraph_explorer import ExplorerServer, build_hypergraph, safe_path
        root = pathlib.Path(self.output_dir_var.get()).expanduser().resolve()
        pointer = root / 'interactive_hypergraph/latest.json'
        if pointer.exists() and not rebuild:
            try:
                bundle = safe_path(root, json.loads(pointer.read_text())['bundle_directory'])
                server = getattr(self, '_graph_server', None)
                if server is None or server.store.bundle != bundle:
                    if server is not None:
                        server.close()
                    server = ExplorerServer(bundle, workspace=root / "semantic_workspace")
                    server.start()
                    self._graph_server = server
                subprocess.run(['open', server.url], check=False)
                self._enqueue_log('Local hypergraph explorer: ' + server.url)
            except Exception as exc:
                messagebox.showerror('Hypergraph explorer', str(exc))
            return
        if self.worker_thread and self.worker_thread.is_alive():
            messagebox.showinfo('Hypergraph explorer', 'Wait for the current job to finish before building a new graph. A previously built graph can be opened during other work.')
            return
        self._begin_history_operation(root, 'build_interactive_hypergraph')
        self.engine = None
        self._metadata_stop.clear()
        self.start_btn.config(state=tk.DISABLED)
        self.stop_btn.config(state=tk.NORMAL)
        self.status_var.set('Building the interactive hypergraph from audited evidence...')
        def target():
            try:
                result = build_hypergraph(root, log_fn=self._enqueue_log, progress_fn=self._enqueue_progress, stop_requested=self._metadata_stop.is_set)
                self._enqueue_log('Explorer bundle: ' + str(root / result['bundle_directory']))
                self._enqueue_progress(1, 1, 'Hypergraph ready. Click Explore Hypergraph to open.')
            except Exception as exc:
                self._enqueue_log(f'HYPERGRAPH: {type(exc).__name__}: {exc}')
                self._enqueue_progress(0, 0, 'Graph build did not finish; see log. Existing graph preserved.')
            finally:
                self.done_queue.put(True)
        self.worker_thread = threading.Thread(target=target, daemon=True)
        self.worker_thread.start()

    def _open_audit_report(self) -> None:
        root = pathlib.Path(self.output_dir_var.get()).expanduser().resolve()
        latest = root / 'audits' / 'latest.json'
        if latest.exists():
            report = json.loads(latest.read_text(encoding='utf-8'))
            subprocess.run(['open', str(root / report['run_directory'] / 'report.html')], check=False)
        else:
            messagebox.showinfo("Dataset audit", "Run Local Dataset Audit or Audit Account & Enrich first.")

    def _open_metadata_outputs(self) -> None:
        root = pathlib.Path(self.output_dir_var.get()).expanduser().resolve()
        latest = root / "metadata" / "latest.json"
        if latest.exists():
            info = json.loads(latest.read_text(encoding="utf-8"))
            subprocess.run(["open", str(root / info['run_directory'])], check=False)
        else:
            messagebox.showinfo("Metadata", "Click Enrich Saved Metadata first to generate analysis tables.")

    def _stop_scrape(self) -> None:
        self._history_event("operation.stop_requested", {"operation_id":self._history_operation_id})
        self._metadata_stop.set()
        if not self.engine:
            self._enqueue_log("Stopping metadata work after the current step...")
        if self.engine:
            self.engine.request_stop()
            self._enqueue_log("Stopping after current step completes...")

    def _on_worker_done(self) -> None:
        self._history_event('operation.finished', {'operation_id':self._history_operation_id,'outcome':'worker_finished','last_progress':self._history_last_progress})
        store = self.project_history
        operation_id = self._history_operation_id
        self._history_operation_id = None
        if store:
            def snapshot():
                try:
                    store.snapshot_project(pathlib.Path(__file__).parent,operation_id=operation_id)
                    store.sync()
                    store.export()
                except Exception as exc:
                    self.log_queue.put(f"Project history snapshot: {type(exc).__name__}: {exc}")
            threading.Thread(target=snapshot,daemon=True).start()
        self.start_btn.config(state=tk.NORMAL)
        self.stop_btn.config(state=tk.DISABLED)
        if self.engine and self.engine.exceeded_records:
            count = len(self.engine.exceeded_records)
            cur_limit = self.max_turns_var.get()
            names = "\n".join(
                f"• {r.title} ({r.total_turns:,} turns captured)"
                for r in self.engine.exceeded_records[:8]
            )
            messagebox.showwarning(
                "Maximum Turns Limit Exceeded!",
                f"{count} conversation(s) exceeded your configured Max Turns limit of {cur_limit:,} "
                f"before reaching the very first message:\n\n{names}\n\n"
                f"Please increase 'Max Turns Limit / Chat' (for example to {cur_limit * 2:,} or {cur_limit * 3:,}) "
                f"and click 'Start Full Account Scrape' again. The app will automatically resume and re-scrape "
                f"only the truncated conversation(s).",
            )

    def _open_in_finder(self) -> None:
        out_dir = pathlib.Path(self.output_dir_var.get()).expanduser().resolve()
        out_dir.mkdir(parents=True, exist_ok=True)
        subprocess.run(["open", str(out_dir)], check=False)

    def _open_dashboard(self) -> None:
        index_path = pathlib.Path(self.output_dir_var.get()).expanduser().resolve() / "index.html"
        if index_path.exists():
            subprocess.run(["open", str(index_path)], check=False)
        else:
            messagebox.showinfo(
                "Dashboard Not Found Yet",
                "Run a scrape first to generate index.html, hypergraph.json, and manifest.json.",
            )


# ============================================================================
# Self-Test / Demo Mode (Verifies all 7 formats, Hypergraph & Max-Turns Warning)
# ============================================================================

def run_self_test(output_dir: pathlib.Path) -> Tuple[pathlib.Path, pathlib.Path, pathlib.Path]:
    """
    Generates two sample conversations:
      1. A complete conversation with code blocks, URLs, and shared concepts.
      2. A conversation that simulates hitting a low max_turns limit (with cross-chat shared concepts),
    verifying per-chat hypergraphs, global cross-chat hypergraph.json, SQLite tables, and truncation alerts.
    """
    db = ArchiveDatabase(output_dir / "archive.db")
    exporter = MultiFormatExporter(output_dir, db)

    turns_1 = [
        ChatTurn(
            turn_index=1,
            turn_id="turn_0001",
            user_prompt="Can you explain how Hypergraph Incidence Format (HIF) works with HyperNetX and Playwright?",
            user_html="<p>Can you explain how Hypergraph Incidence Format (HIF) works with HyperNetX and Playwright?</p>",
            model_response="In HyperNetX, an n-ary hyperedge connects any number of vertices via an incidence table. Reference: https://github.com/pnnl/HyperNetX",
            model_html="<p>In HyperNetX, an n-ary hyperedge connects any number of vertices via an incidence table.</p>",
            model_thoughts="Connect Hypergraph Incidence Format to Python HyperNetX and SQLite.",
            code_blocks=[{"language": "python", "code": "import hypernetx as hnx\nH = hnx.Hypergraph(incidence_dict)"}],
            timestamp_hint="2026-10-26T09:00:00Z",
        ),
        ChatTurn(
            turn_index=2,
            turn_id="turn_0002",
            user_prompt="How do we verify every single turn was captured in HyperNetX?",
            user_html="<p>How do we verify every single turn was captured in HyperNetX?</p>",
            model_response="We compute a SHA-256 digest over every turn and link shared concepts across turns via `concept_cooccurrence` hyperedges.",
            model_html="<p>We compute a SHA-256 digest over every turn and link shared concepts across turns.</p>",
            model_thoughts="Verify SHA-256 and hyperedge incidence.",
            code_blocks=[],
            timestamp_hint="2026-10-26T09:01:12Z",
        ),
    ]

    rec_1 = ConversationRecord(
        chat_id="c_demo_complete_001",
        title="Hypergraph Architecture & Verification",
        url="https://gemini.google.com/app/c_demo_complete_001",
        scraped_at=dt.datetime.now(dt.timezone.utc).isoformat(),
        total_turns=len(turns_1),
        total_user_chars=sum(len(t.user_prompt) for t in turns_1),
        total_model_chars=sum(len(t.model_response) for t in turns_1),
        is_pinned=True,
        scroll_iterations=42,
        reached_beginning_of_chat=True,
        max_turns_limit_exceeded=False,
        configured_max_turns=5000,
        turns=turns_1,
    )
    exporter.export_all_formats(rec_1)

    # Second conversation shares concepts ("HyperNetX", "Playwright") with rec_1 and simulates hitting max_turns
    turns_2 = [
        ChatTurn(
            turn_index=1,
            turn_id="turn_5000",
            user_prompt="Using Playwright and HyperNetX on macOS to archive 5000+ turn threads.",
            user_html="<p>Using Playwright and HyperNetX on macOS to archive 5000+ turn threads.</p>",
            model_response="When `max_turns_limit_exceeded` triggers, the archiver notifies you on macOS to increase the 5000 limit.",
            model_html="<p>When <code>max_turns_limit_exceeded</code> triggers, the archiver notifies you on macOS.</p>",
            model_thoughts="Simulate max turns warning notification.",
            code_blocks=[{"language": "python", "code": "send_macos_limit_exceeded_notification('Warning', 'Increase limit')"}],
            timestamp_hint="2026-10-26T09:05:00Z",
        )
    ]
    rec_2 = ConversationRecord(
        chat_id="c_demo_exceeded_002",
        title="Massive Multi-Thousand Turn Research Thread",
        url="https://gemini.google.com/app/c_demo_exceeded_002",
        scraped_at=dt.datetime.now(dt.timezone.utc).isoformat(),
        total_turns=len(turns_2),
        total_user_chars=sum(len(t.user_prompt) for t in turns_2),
        total_model_chars=sum(len(t.model_response) for t in turns_2),
        is_pinned=False,
        scroll_iterations=2500,
        reached_beginning_of_chat=False,
        max_turns_limit_exceeded=True,
        configured_max_turns=5000,
        truncation_warning="Hit configured ceiling of 5,000 turns before reaching the first message. Increase --max-turns to 10,000+.",
        turns=turns_2,
    )
    exporter.export_all_formats(rec_2)

    return exporter.write_master_manifest_and_index()


# ============================================================================
# CLI Entrypoint
# ============================================================================

def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Gemini Complete Account History Archiver & Hypergraph Exporter (macOS)"
    )
    parser.add_argument(
        "--cli",
        action="store_true",
        help="Run in terminal CLI mode instead of launching the macOS Tkinter GUI.",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=str(_default_archive_dir()),
        help="Target directory where conversations/, archive.db, hypergraph.json, index.html, and manifest.json are stored.",
    )
    parser.add_argument(
        "--profile",
        type=str,
        default=str(_default_profile_dir()),
        help="Persistent Chromium user data directory so you only log in once.",
    )
    parser.add_argument(
        "--cdp-url",
        type=str,
        default=None,
        help="Optional Chrome Remote Debugging URL (e.g., http://127.0.0.1:9222) to attach to an existing Chrome session.",
    )
    parser.add_argument(
        "--force-rescrape",
        action="store_true",
        help="Re-scrape conversations even if already marked completed in archive.db.",
    )
    parser.add_argument(
        "--max-turns",
        type=int,
        default=5000,
        help="Maximum turns ceiling per conversation before firing a truncation warning notification (default: 5000).",
    )
    parser.add_argument(
        "--max-scroll-steps",
        type=int,
        default=3000,
        help="Maximum upward scroll iterations per conversation (default: 3000; auto-scales with --max-turns).",
    )
    parser.add_argument(
        "--chat-url",
        action="append",
        dest="chat_urls",
        help="Scrape specific Gemini conversation URL(s) instead of scanning the entire sidebar.",
    )
    parser.add_argument(
        "--import-local",
        type=str,
        default=None,
        help="Import and convert an existing folder of JSON files into all 7 export formats + Hypergraph + SQLite + Manifest.",
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="Run an offline export smoke test for JSON, Hypergraph, MD, CSV, TXT, HTML, PDF, SQLite, and Max-Turns alerts.",
    )
    metadata_modes = parser.add_mutually_exclusive_group()
    metadata_modes.add_argument("--build-hypergraph", action="store_true", help="Build a versioned portable interactive hypergraph from the completed account audit.")
    metadata_modes.add_argument("--explore-hypergraph", action="store_true", help="Open the local interactive explorer; build it first if needed.")
    metadata_modes.add_argument("--enrich-metadata", action="store_true", help="Decode saved network responses into metadata sidecars, CSV and SQLite; leave original exports unchanged.")
    metadata_modes.add_argument("--refresh-metadata", action="store_true", help="Enrich saved metadata, then revisit only chats with missing timestamps in Chrome.")
    metadata_modes.add_argument("--probe-direct-metadata", action="store_true", help="Test direct history pagination on one archived chat (at most two pages), without publishing metadata.")
    metadata_modes.add_argument("--direct-metadata", action="store_true", help="Trial: fetch missing metadata through direct history pagination, with archive comparison before publication.")
    parser.add_argument("--direct-page-size", type=int, default=50, help="Requested direct-history batch size, 1..100 (server may return fewer).")
    parser.add_argument("--direct-max-pages", type=int, default=1000, help="Maximum direct-history pages per conversation.")
    metadata_modes.add_argument("--audit-local", action="store_true", help="Check local integrity and inventory saved ancillary data; write a separate audit report.")
    metadata_modes.add_argument("--audit-account", action="store_true", help="Compare the visible Gemini account list/full histories with the archive and retain ancillary data separately.")
    parser.add_argument("--fresh-audit", action="store_true", help="Start a fresh account audit instead of resuming the last incomplete one.")
    parser.add_argument("--audit-no-media", action="store_true", help="Inventory exposed media URLs without downloading additional binaries.")
    parser.add_argument("--audit-max-pages", type=int, default=1000, help="Maximum list/history pages per account-audit request sequence.")
    metadata_modes.add_argument("--sync-project-history", action="store_true", help="Sync registered visible development threads and export the project history.")
    parser.add_argument("--project-history-source", type=str, help="Explicit Codex rollout JSONL to register when syncing project history.")
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    if args.max_turns < 1 or args.max_scroll_steps < 1:
        raise SystemExit("--max-turns and --max-scroll-steps must be positive.")
    out_dir = pathlib.Path(args.output).expanduser().resolve()
    prof_dir = pathlib.Path(args.profile).expanduser().resolve()

    if args.build_hypergraph or args.explore_hypergraph:
        from hypergraph_explorer import build_hypergraph, ExplorerServer, safe_path
        from project_history import ProjectOperation
        pointer = out_dir / 'interactive_hypergraph/latest.json'
        if args.build_hypergraph or not pointer.exists():
            with _open_project_operation(out_dir, 'build_interactive_hypergraph', pathlib.Path(__file__).parent) as operation:
                result = build_hypergraph(out_dir, log_fn=operation.log)
                operation.result = result
            print(json.dumps(result, indent=2))
        if args.explore_hypergraph:
            import webbrowser
            info = json.loads(pointer.read_text())
            server = ExplorerServer(safe_path(out_dir, info['bundle_directory']), workspace=out_dir / 'semantic_workspace')
            print('Local hypergraph explorer:', server.start(), flush=True)
            webbrowser.open(server.url)
            try:
                while server.thread.is_alive():
                    server.thread.join(timeout=1)
            except KeyboardInterrupt:
                pass
            finally:
                server.close()
        return 0

    if args.sync_project_history:
        from project_history import ProjectHistory
        store = ProjectHistory(out_dir)
        if args.project_history_source:
            store.register_codex(pathlib.Path(args.project_history_source))
        result = store.sync()
        store.snapshot_project(pathlib.Path(__file__).parent)
        result['summary'] = store.export()
        print(json.dumps(result, indent=2))
        return 0

    if args.audit_local or args.audit_account:
        from dataset_audit import local_audit, account_audit
        with _open_project_operation(out_dir, 'account_audit' if args.audit_account else 'local_audit', pathlib.Path(__file__).parent, configuration={'include_media':not args.audit_no_media,'resume':not args.fresh_audit,'max_pages':args.audit_max_pages}) as operation:
            if args.audit_local:
                result = local_audit(out_dir, log_fn=operation.log)
            else:
                result = asyncio.run(account_audit(out_dir, prof_dir, cdp_url=args.cdp_url, log_fn=operation.log,
                    include_media=not args.audit_no_media, resume=not args.fresh_audit, max_pages=args.audit_max_pages))
            operation.result = result
        print(json.dumps(result, indent=2))
        return 0 if result['status'] in ('local_checks_complete','account_checks_complete') else 1

    if args.probe_direct_metadata or args.direct_metadata:
        from direct_history import direct_metadata_refresh
        with _open_project_operation(out_dir, 'direct_probe' if args.probe_direct_metadata else 'direct_metadata', pathlib.Path(__file__).parent, configuration={'page_size':args.direct_page_size,'max_pages':args.direct_max_pages}) as operation:
            result = asyncio.run(direct_metadata_refresh(
                out_dir, prof_dir, probe=args.probe_direct_metadata, cdp_url=args.cdp_url, log_fn=operation.log,
                max_pages=args.direct_max_pages, page_size=args.direct_page_size))
            operation.result = result
        print(json.dumps(result.get('direct_fetch_report', {}), indent=2))
        return 0 if result.get('direct_fetch_report', {}).get('results') and all(row.get('validated') for row in result['direct_fetch_report']['results']) else 1

    if args.enrich_metadata or args.refresh_metadata:
        from metadata_enrichment import enrich_archive, refresh_missing_metadata
        with _open_project_operation(out_dir, 'metadata_refresh' if args.refresh_metadata else 'local_metadata_enrichment', pathlib.Path(__file__).parent, configuration={'max_scroll_steps':args.max_scroll_steps}) as operation:
            result = enrich_archive(out_dir, log_fn=operation.log)
            if args.refresh_metadata:
                result = asyncio.run(refresh_missing_metadata(out_dir, prof_dir, cdp_url=args.cdp_url, max_scroll_steps=args.max_scroll_steps, log_fn=operation.log))
            operation.result = result
        print(json.dumps(result['statistics'], indent=2))
        return 0

    if args.self_test:
        with _open_project_operation(out_dir, 'offline_export_smoke_test', pathlib.Path(__file__).parent) as operation:
            manifest_path, index_path, global_hg_path = run_self_test(out_dir)
            operation.result = {'status':'offline_export_smoke_test_returned'}
        print(
            f"Offline export smoke test finished (does not test live Gemini scraping)!\n"
            f"  Manifest  : {manifest_path}\n"
            f"  Hypergraph: {global_hg_path}\n"
            f"  Dashboard : {index_path}"
        )
        return 0

    if args.import_local:
        src = pathlib.Path(args.import_local).expanduser().resolve()
        with _open_project_operation(out_dir, 'local_import', pathlib.Path(__file__).parent, configuration={'input_folder':str(src)}) as operation:
            manifest_path, index_path, global_hg_path = import_local_json_or_takeout_folder(src, out_dir, log_fn=operation.log)
            operation.result = {'status':'local_import_returned'}
        print(
            f"Local import complete!\n"
            f"  Manifest  : {manifest_path}\n"
            f"  Hypergraph: {global_hg_path}\n"
            f"  Dashboard : {index_path}"
        )
        return 0

    if args.cli or not HAS_TK:
        with _open_project_operation(out_dir, 'full_account_scrape', pathlib.Path(__file__).parent, configuration={'max_turns':args.max_turns,'max_scroll_steps':args.max_scroll_steps,'force_rescrape':args.force_rescrape,'selected_chat_count':len(args.chat_urls or [])}) as operation:
            engine = GeminiScraperEngine(output_dir=out_dir, profile_dir=prof_dir, cdp_url=args.cdp_url, log_fn=operation.log)
            result = asyncio.run(engine.run_full_archive(
                force_rescrape=args.force_rescrape, max_turns_per_chat=args.max_turns,
                max_scroll_Attempts_per_chat=args.max_scroll_steps, specific_urls=args.chat_urls))
            operation.result = {'status':'engine_returned','manifest_file':str(result[0])}
        return 0

    root = tk.Tk()
    app = GeminiArchiverMacGUI(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("Interrupted. Check checkpoints/ for the most recent captured turns.", file=sys.stderr)
        sys.exit(130)
    except Exception as exc:
        print(f"Gemini Archiver: {type(exc).__name__}: {exc}", file=sys.stderr)
        sys.exit(1)