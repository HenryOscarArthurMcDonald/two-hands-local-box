#!/usr/bin/env python3
"""
capture_spark_chat.py — Targeted Gemini / Spark Conversation Archiver

Connects to a logged-in Chromium/Chrome session via Playwright and archives a
specific Gemini or Spark conversation URL directly into your local `archive.db`
using the scroll-and-hydrate engine in `scraper/gemini_archiver.py`.

Environment overrides:
  ARCHIVE_DB / ARCHIVE_DIR : Target archive.db path or output directory (default: ./data/archive.db)
  CHROME_USER_DATA_DIR     : Persistent Chromium profile directory (default: ~/.cache/corpus_chrome_profile)
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gemini_archiver import GeminiScraperEngine


def _default_archive_dir() -> Path:
    env_dir = os.environ.get("ARCHIVE_DIR", "").strip()
    if env_dir:
        return Path(env_dir).expanduser()
    env_db = os.environ.get("ARCHIVE_DB", "").strip() or os.environ.get("ARCHIVE_DB_PATH", "").strip()
    if env_db:
        return Path(env_db).expanduser().parent
    return Path(__file__).resolve().parent.parent / "data"


def _default_profile_dir() -> Path:
    env_prof = os.environ.get("CHROME_USER_DATA_DIR", "").strip()
    if env_prof:
        return Path(env_prof).expanduser()
    return Path.home() / ".cache" / "corpus_chrome_profile"


def extract_chat_id(url: str) -> str:
    m = re.search(r"/(?:app|chat)/([a-zA-Z0-9_-]{8,})", url)
    if m:
        return m.group(1)
    return hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]


async def capture_conversation(
    url: str,
    archive_dir: Path,
    profile_dir: Path,
    *,
    cdp_url: str | None = None,
    max_turns: int = 5000,
) -> None:
    chat_id = extract_chat_id(url)
    archive_dir = archive_dir.expanduser().resolve()
    profile_dir = profile_dir.expanduser().resolve()
    archive_dir.mkdir(parents=True, exist_ok=True)
    profile_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print(f"  CONVERSATION ARCHIVER: {chat_id}")
    print(f"  Target URL : {url}")
    print(f"  Archive DB : {archive_dir / 'archive.db'}")
    print(f"  Profile Dir: {profile_dir}")
    print("=" * 60)

    engine = GeminiScraperEngine(archive_dir, profile_dir, cdp_url=cdp_url)
    await engine.run_full_archive(
        specific_urls=[url],
        force_rescrape=True,
        max_turns_per_chat=max_turns,
        max_scroll_Attempts_per_chat=3000,
    )
    print(f"[OK] Archived conversation [{chat_id}] into {archive_dir / 'archive.db'}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Archive a specific Gemini / Spark conversation URL into archive.db")
    parser.add_argument("url", help="Full Gemini or Spark conversation URL (e.g. https://gemini.google.com/app/<id>)")
    parser.add_argument("--archive", type=Path, default=_default_archive_dir(), help="Target archive directory (default: ./data)")
    parser.add_argument("--profile", type=Path, default=_default_profile_dir(), help="Persistent Chromium profile directory")
    parser.add_argument("--cdp-url", type=str, default=None, help="Optional Chrome Remote Debugging URL (e.g. http://127.0.0.1:9222)")
    parser.add_argument("--max-turns", type=int, default=5000, help="Max turns ceiling")
    args = parser.parse_args()

    asyncio.run(
        capture_conversation(
            args.url,
            args.archive,
            args.profile,
            cdp_url=args.cdp_url,
            max_turns=args.max_turns,
        )
    )


if __name__ == "__main__":
    main()
