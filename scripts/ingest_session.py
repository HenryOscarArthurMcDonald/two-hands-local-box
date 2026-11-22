#!/usr/bin/env python3
"""Idempotent session & artifact ingester for Corpus + Arachne.

Supports .md, .txt, .json, and .html exports (session logs, build reports,
conversations, briefings) and folds them into chunks + chunks_fts with
explicit provenance and SHA-256 deduplication.

Truth-Gate Invariant:
  Ingested artifacts are strictly held at epistemic_tier='RAW_CLAIM' / source_tag
  ('PROVENANCE_LOG' by default) and NEVER auto-promoted to EXTERNALLY_VERIFIED.
"""

from __future__ import annotations

import argparse
import hashlib
import html as html_lib
import html.parser
import json
import re
import sqlite3
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from compile_digest import compile_digest, resolve_digest_targets
from db_utils import (
    DEFAULT_DB_PATH,
    classify_text_to_section_key,
    ensure_digest_state_table,
    ensure_ingested_artifacts_table,
    get_connection,
    init_db,
)
from stage0_ingest import chunk_text, iter_json_records, normalize_whitespace

SUPPORTED_SUFFIXES = {".md", ".txt", ".json", ".html", ".htm"}

DATA_URI_RE = re.compile(
    r"data:[a-z0-9.+_-]+/[a-z0-9.+_-]+(?:;[a-z0-9=._-]+)*;base64,[a-z0-9+/=\r\n]+",
    re.IGNORECASE,
)


class _CleanHTMLParser(html.parser.HTMLParser):
    """Strip HTML/Angular DOM tags while skipping style/script/button/hidden blocks."""

    _SKIP_TAGS = {"script", "style", "noscript", "svg", "template", "button", "mat-icon", "gem-icon"}
    _SKIP_CLASSES = (
        "cdk-visually-hidden",
        "screen-reader-user-query-label",
        "luminous-toggle-container",
        "code-block-decoration",
    )
    _BLOCK_TAGS = {
        "p", "div", "section", "article", "header", "footer", "main",
        "aside", "nav", "br", "hr", "li", "ul", "ol", "blockquote",
        "pre", "tr", "td", "th", "h1", "h2", "h3", "h4", "h5", "h6",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip_stack: list[str] = []
        self._math_stack: list[str] = []
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        low = tag.lower()
        amap = {k.lower(): (v or "") for k, v in attrs}
        cls = amap.get("class", "").lower()

        if self._skip_stack:
            self._skip_stack.append(low)
            return
        if low in self._SKIP_TAGS or any(sc in cls for sc in self._SKIP_CLASSES):
            self._skip_stack.append(low)
            return
        if self._math_stack:
            self._math_stack.append(low)
            return
        if ("math-inline" in cls or "math-block" in cls) and "data-math" in amap:
            self._parts.append(f" {amap['data-math'].strip()} ")
            self._math_stack.append(low)
            return
        if low in self._BLOCK_TAGS:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        low = tag.lower()
        if self._skip_stack:
            self._skip_stack.pop()
            return
        if self._math_stack:
            self._math_stack.pop()
            return
        if low in self._BLOCK_TAGS:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip_stack and not self._math_stack and data:
            self._parts.append(data)

    def get_text(self) -> str:
        return "".join(self._parts)


def strip_html_cleanly(raw_html: str) -> str:
    """Strip HTML tags, Angular chrome, style/script blocks, and base64 data URIs cleanly."""
    cleaned_html = DATA_URI_RE.sub(" ", raw_html or "")
    parser = _CleanHTMLParser()
    parser.feed(cleaned_html)
    parser.close()
    text = DATA_URI_RE.sub(" ", parser.get_text())
    return normalize_whitespace(text)


def clean_gemini_turn_text(plain_text: str | None, html_text: str | None, *, is_user: bool = False) -> str:
    """Extract clean plaintext from Gemini/Spark turn columns (falling back to stripped HTML)."""
    raw = (plain_text or "").strip()
    html_raw = (html_text or "").strip()
    if raw and not re.search(r"<(?:span|div|p|h[1-6]|user-query|mat-icon|button|code|pre)\b|_ngcontent", raw, re.IGNORECASE):
        text = normalize_whitespace(DATA_URI_RE.sub(" ", html_lib.unescape(raw)))
    elif html_raw:
        text = strip_html_cleanly(html_raw)
    elif raw:
        text = strip_html_cleanly(raw)
    else:
        return ""

    if is_user:
        lines = text.splitlines()
        if lines and lines[0].startswith("You said "):
            preview = lines[0][len("You said ") :].strip()
            rest = "\n".join(lines[1:]).lstrip()
            if "…" in preview or preview.endswith("...") or rest.startswith(preview):
                lines = rest.splitlines()
        elif lines and lines[0].strip() == "You said":
            lines = lines[1:]
        text = normalize_whitespace("\n".join(lines))
    return text


def extract_clean_artifact_records(source_path: Path) -> tuple[str, list[dict[str, Any]]]:
    """Extract cleaned (source_type, [{author, created_at, turn_index, content}, ...])."""
    suffix = source_path.suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise ValueError(
            f"Unsupported artifact extension {suffix!r} for {source_path}; "
            f"expected one of {sorted(SUPPORTED_SUFFIXES)}"
        )

    raw_text = source_path.read_text(encoding="utf-8", errors="replace")
    records: list[dict[str, Any]] = []

    if suffix in (".html", ".htm"):
        src_type = "html"
        cleaned = strip_html_cleanly(raw_text)
        for idx, ch in enumerate(chunk_text(cleaned)):
            records.append({"author": None, "created_at": None, "turn_index": idx, "content": ch})
    elif suffix in (".md", ".txt"):
        src_type = suffix.lstrip(".")
        cleaned = normalize_whitespace(DATA_URI_RE.sub(" ", raw_text))
        for idx, ch in enumerate(chunk_text(cleaned)):
            records.append({"author": None, "created_at": None, "turn_index": idx, "content": ch})
    else:  # .json
        src_type = "json"
        data = json.loads(raw_text)
        turn_idx = 0
        if isinstance(data, dict) and isinstance(data.get("turns"), list) and data["turns"] and isinstance(data["turns"][0], dict) and "turn_index" in data["turns"][0]:
            for item in data["turns"]:
                body = str(item.get("content") or item.get("text") or "")
                cleaned_body = normalize_whitespace(DATA_URI_RE.sub(" ", body))
                t_idx = int(item.get("turn_index") if item.get("turn_index") is not None else turn_idx)
                t_id = str(item.get("turn_id") or "").strip() or None
                author = str(item.get("author") or item.get("role") or "") or None
                created_at = str(item.get("created_at") or item.get("timestamp") or "") or None
                for ch in chunk_text(cleaned_body):
                    records.append(
                        {
                            "author": author,
                            "created_at": created_at,
                            "turn_index": t_idx,
                            "turn_id": t_id,
                            "content": ch,
                        }
                    )
                turn_idx += 1
        else:
            for author, created_at, body in iter_json_records(data, str(source_path)):
                cleaned_body = normalize_whitespace(DATA_URI_RE.sub(" ", body))
                for ch in chunk_text(cleaned_body):
                    records.append(
                        {
                            "author": author,
                            "created_at": created_at,
                            "turn_index": turn_idx,
                            "content": ch,
                        }
                    )
                    turn_idx += 1

    return src_type, records


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def ingest_artifact(
    db_path: Path | str,
    source_path: Path | str,
    source_tag: str = "PROVENANCE_LOG",
    chat_id: str | None = None,
    sync_digest: bool = True,
    *,
    slice_name: str | None = None,
    archive_db: Path | str | None = None,
) -> dict[str, Any]:
    """Idempotently ingest a .md/.txt/.json/.html artifact as RAW_CLAIM / PROVENANCE_LOG chunks."""
    db_file = Path(db_path).expanduser().resolve()
    src = Path(source_path).expanduser().resolve()
    if not src.is_file():
        raise FileNotFoundError(f"Artifact file not found: {src}")

    src_type, records = extract_clean_artifact_records(src)
    cleaned_joined = "\n\n".join(r["content"] for r in records)
    content_sha256 = _hash_text(cleaned_joined) if cleaned_joined else _hash_text(src.read_text(encoding="utf-8", errors="replace"))
    raw_file_sha256 = hashlib.sha256(src.read_bytes()).hexdigest()

    init_db(db_file)
    conn = get_connection(db_file)
    try:
        ensure_digest_state_table(conn)
        ensure_ingested_artifacts_table(conn)

        existing = conn.execute(
            "SELECT artifact_id, chunk_count, first_chunk_id, last_chunk_id, section_key, epistemic_tier "
            "FROM ingested_artifacts WHERE file_sha256 IN (?, ?) LIMIT 1",
            (content_sha256, raw_file_sha256),
        ).fetchone()
        if existing is not None:
            return {
                "status": "already_ingested",
                "source_path": str(src),
                "source_type": src_type,
                "source_tag": source_tag,
                "chat_id": chat_id or f"{source_tag}:{src.stem}",
                "sha256": content_sha256,
                "file_sha256": raw_file_sha256,
                "epistemic_tier": "RAW_CLAIM",
                "nodes_auto_promoted": 0,
                "chunks_inserted": 0,
                "duplicates_skipped": len(records),
                "chunk_ids": [],
                "section_key": existing["section_key"],
                "digest_delta": None,
            }

        if not records:
            return {
                "status": "empty_or_skipped",
                "source_path": str(src),
                "source_type": src_type,
                "source_tag": source_tag,
                "chat_id": chat_id or f"{source_tag}:{src.stem}",
                "sha256": content_sha256,
                "file_sha256": raw_file_sha256,
                "epistemic_tier": "RAW_CLAIM",
                "nodes_auto_promoted": 0,
                "chunks_inserted": 0,
                "duplicates_skipped": 0,
                "chunk_ids": [],
                "section_key": None,
                "digest_delta": None,
            }

        effective_chat_id = (chat_id or f"{source_tag}:{src.stem}").strip()
        inserted_cids: list[int] = []
        dups_skipped = 0

        for rec in records:
            norm = normalize_whitespace(rec["content"])
            if len(norm) < 10:
                continue
            chunk_sha = _hash_text(norm)
            turn_idx = int(rec["turn_index"])
            turn_id_part = f" | turn_id={rec['turn_id']}" if rec.get("turn_id") else ""
            source_ref = (
                f"archive:{effective_chat_id}:turn:{turn_idx}{turn_id_part} | "
                f"tag={source_tag} | tier=RAW_CLAIM | path={src} | sha256={content_sha256[:12]}"
            )
            cur = conn.execute(
                """
                INSERT OR IGNORE INTO chunks
                    (source_type, source_ref, author, created_at, sha256, content)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    src_type,
                    source_ref,
                    rec.get("author"),
                    rec.get("created_at"),
                    chunk_sha,
                    norm,
                ),
            )
            if cur.rowcount > 0:
                cid = int(cur.lastrowid)
                conn.execute(
                    "INSERT INTO chunks_fts(rowid, content) VALUES (?, ?)",
                    (cid, norm),
                )
                if slice_name:
                    conn.execute(
                        """
                        INSERT OR IGNORE INTO chapter_slices (slice_name, chunk_id, relevance, status)
                        VALUES (?, ?, 0.5, 'PENDING')
                        """,
                        (slice_name, cid),
                    )
                inserted_cids.append(cid)
            else:
                dups_skipped += 1

        if not inserted_cids:
            return {
                "status": "already_ingested" if dups_skipped else "empty_or_skipped",
                "source_path": str(src),
                "source_type": src_type,
                "source_tag": source_tag,
                "chat_id": effective_chat_id,
                "sha256": content_sha256,
                "file_sha256": raw_file_sha256,
                "epistemic_tier": "RAW_CLAIM",
                "nodes_auto_promoted": 0,
                "chunks_inserted": 0,
                "duplicates_skipped": dups_skipped,
                "chunk_ids": [],
                "section_key": None,
                "digest_delta": None,
            }

        section_key = classify_text_to_section_key(
            f"{source_tag} {src.name} {cleaned_joined[:4000]}"
        )
        conn.execute(
            """
            INSERT INTO ingested_artifacts
                (source_path, source_type, source_tag, chat_id, file_sha256,
                 epistemic_tier, chunk_count, first_chunk_id, last_chunk_id, section_key)
            VALUES (?, ?, ?, ?, ?, 'RAW_CLAIM', ?, ?, ?, ?)
            """,
            (
                str(src),
                src_type,
                source_tag,
                effective_chat_id,
                content_sha256,
                len(inserted_cids),
                inserted_cids[0],
                inserted_cids[-1],
                section_key,
            ),
        )
        conn.commit()

        digest_delta: dict[str, Any] | None = None
        if sync_digest:
            core_path, slices_dir = resolve_digest_targets(db_file)
            digest_delta = compile_digest(
                conn,
                archive_db=archive_db,
                core_path=core_path,
                slices_dir=slices_dir,
                only_section_keys={section_key},
                force_all=False,
                sync_ouroboros=True,
            )

        return {
            "status": "ingested",
            "source_path": str(src),
            "source_type": src_type,
            "source_tag": source_tag,
            "chat_id": effective_chat_id,
            "sha256": content_sha256,
            "file_sha256": raw_file_sha256,
            "epistemic_tier": "RAW_CLAIM",
            "nodes_auto_promoted": 0,
            "chunks_inserted": len(inserted_cids),
            "duplicates_skipped": dups_skipped,
            "chunk_ids": inserted_cids,
            "section_key": section_key,
            "digest_delta": digest_delta,
        }
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Idempotent session/document ingester (.md, .txt, .json, .html) -> RAW_CLAIM chunks"
    )
    parser.add_argument("source_path", type=Path, help="Path to .md, .txt, .json, or .html artifact")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--tag", default="PROVENANCE_LOG", help="Source provenance tag")
    parser.add_argument("--chat-id", default=None, help="Optional chat_id for provenance linkage")
    parser.add_argument("--slice-name", default=None, help="Optional chapter_slices target to enqueue chunks")
    parser.add_argument("--archive-db", type=Path, default=None, help="Optional read-only archive.db")
    parser.add_argument("--no-sync", action="store_true", help="Skip targeted compile_digest delta update")
    args = parser.parse_args()

    res = ingest_artifact(
        db_path=args.db,
        source_path=args.source_path,
        source_tag=args.tag,
        chat_id=args.chat_id,
        sync_digest=not args.no_sync,
        slice_name=args.slice_name,
        archive_db=args.archive_db,
    )
    print(json.dumps(res, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
