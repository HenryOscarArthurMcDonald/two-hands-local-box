#!/usr/bin/env python3
"""
sync_gemini.py — Incremental Sync for Regular Gemini (/app) & Spark (/spark/chat)
Captures only:
  1. Brand-new conversations not yet in archive.db
  2. The top N most recent conversations in each sidebar (to pick up new turns)
  3. Any explicit --url conversations passed on the command line
"""

from __future__ import annotations
import argparse
import asyncio
import hashlib
import os
import pathlib
import re
import sys
from typing import Any, Dict, List, Optional, Set

sys.path.insert(0, str(pathlib.Path(__file__).parent))

from gemini_archiver import (
    GeminiScraperEngine,
    JS_DISCOVER_SIDEBAR_CHATS,
    JS_SCROLL_SIDEBAR,
)

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


DEFAULT_ARCHIVE_DIR = _default_archive_dir()
DEFAULT_PROFILE_DIR = _default_profile_dir()
DEFAULT_SURFACES = [
    "https://gemini.google.com/app",
]


def extract_chat_id(url: str) -> str:
    m = re.search(r"/(?:app|chat)/([a-zA-Z0-9_-]{8,})", url)
    if m:
        return m.group(1)
    return hashlib.sha1(url.encode()).hexdigest()[:16]


async def _try_open_sidebar(page: Any) -> None:
    """Click the first visible sidebar/menu toggle button if chats are not yet visible."""
    try:
        clicked = await page.evaluate("""() => {
            const selectors = [
                '[data-test-id="side-nav-menu-button"]',
                'button[aria-label*="Main menu" i]',
                'button[aria-label*="Expand menu" i]',
                'button[aria-label*="Show sidebar" i]',
                'button[aria-label*="Open menu" i]',
            ];
            for (const sel of selectors) {
                const els = Array.from(document.querySelectorAll(sel));
                for (const el of els) {
                    const rect = el.getBoundingClientRect();
                    if (rect.width > 0 && rect.height > 0) {
                        const expanded = el.getAttribute("aria-expanded");
                        if (expanded !== "true") {
                            el.click();
                            return true;
                        }
                    }
                }
            }
            return false;
        }""")
        if clicked:
            await asyncio.sleep(1.5)
    except Exception:
        pass


async def discover_surface_chats(page: Any, surface_url: str, max_scrolls: int = 8) -> List[Dict[str, Any]]:
    """Open a Gemini surface (/app or /spark) and discover sidebar chats."""
    print(f"[+] Scanning surface: {surface_url}")
    await page.goto(surface_url, wait_until="domcontentloaded", timeout=90000)

    is_spark_landing = surface_url.rstrip("/").endswith("/spark")

    # Wait up to 15s for sidebar chat links to render on /app surfaces
    wait_limit = 3 if is_spark_landing else 15
    for sec in range(wait_limit):
        await asyncio.sleep(1.0)
        items = await page.evaluate(JS_DISCOVER_SIDEBAR_CHATS)
        if items:
            break
        if sec in (3, 7) and not is_spark_landing:
            await _try_open_sidebar(page)

    if not is_spark_landing and not await page.evaluate(JS_DISCOVER_SIDEBAR_CHATS):
        print(f"    [!] No sidebar chats detected yet on {surface_url}.")
        print("        Check the Chrome window (sign in or click the top-left menu to open the sidebar).")
        try:
            ans = input("        Press Enter to re-scan this surface, or type 's' to skip: ").strip().lower()
            if ans != "s":
                await _try_open_sidebar(page)
                await asyncio.sleep(1.5)
        except (KeyboardInterrupt, EOFError):
            pass

    discovered: List[Dict[str, Any]] = []
    seen: Set[str] = set()
    stagnant = 0

    for _ in range(max_scrolls):
        items = await page.evaluate(JS_DISCOVER_SIDEBAR_CHATS)
        added = 0
        for item in items:
            cid = item["chat_id"]
            if cid not in seen:
                seen.add(cid)
                discovered.append(item)
                added += 1
        if added == 0:
            stagnant += 1
        else:
            stagnant = 0

        scrolled = await page.evaluate(JS_SCROLL_SIDEBAR)
        await asyncio.sleep(0.8)
        if stagnant >= 2 and not scrolled:
            break

    print(f"    Found {len(discovered)} visible chat(s) on this surface.")
    return discovered


async def run_incremental_sync(
    archive_dir: pathlib.Path,
    profile_dir: pathlib.Path,
    surfaces: List[str],
    recent_refresh: int,
    extra_urls: List[str],
    cdp_url: Optional[str],
    max_turns: int,
    max_scroll_steps: int,
) -> None:
    from playwright.async_api import async_playwright

    archive_dir.mkdir(parents=True, exist_ok=True)
    profile_dir.mkdir(parents=True, exist_ok=True)

    engine = GeminiScraperEngine(archive_dir, profile_dir, cdp_url=cdp_url)
    existing = {
        row["chat_id"]: row
        for row in engine.db.get_all_conversations()
    }
    print(f"[+] Loaded archive.db: {len(existing)} existing conversation(s).")

    effective_scroll_steps = max(max_scroll_steps, (max_turns // 2) + 500)

    async with async_playwright() as p:
        browser = None
        if cdp_url:
            browser = await p.chromium.connect_over_cdp(cdp_url)
            context = browser.contexts[0] if browser.contexts else await browser.new_context()
        else:
            context = await p.chromium.launch_persistent_context(
                user_data_dir=str(profile_dir),
                headless=False,
                channel="chrome" if pathlib.Path("/Applications/Google Chrome.app").exists() else None,
                viewport={"width": 1440, "height": 960},
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--disable-features=IsolateOrigins,site-per-process",
                ],
            )

        page = await context.new_page()

        # Authenticate on primary Gemini surface first
        await page.goto(surfaces[0], wait_until="domcontentloaded", timeout=90000)
        await asyncio.sleep(2.5)
        await engine._wait_for_authentication(page)

        queue_map: Dict[str, Dict[str, Any]] = {}

        # 1. Explicit URLs always queued
        for u in extra_urls:
            cid = extract_chat_id(u)
            queue_map[cid] = {
                "chat_id": cid,
                "title": existing.get(cid, {}).get("title", f"Conversation {cid}"),
                "url": u,
                "is_pinned": False,
                "reason": "explicit --url",
            }

        # 2. Scan each surface (/app and /spark)
        total_discovered = 0
        for surface in surfaces:
            items = await discover_surface_chats(page, surface)
            total_discovered += len(items)
            engine.db.register_sidebar_conversations(items)

            for idx, item in enumerate(items):
                cid = item["chat_id"]
                db_row = existing.get(cid)
                is_new = db_row is None
                is_incomplete = bool(
                    db_row and (
                        db_row.get("status") in ("discovered", "error", "interrupted", "needs_higher_limit")
                        or int(db_row.get("max_turns_exceeded") or 0) == 1
                    )
                )
                is_recent = idx < recent_refresh

                if is_new or is_incomplete or is_recent:
                    reason = "new" if is_new else ("incomplete" if is_incomplete else f"recent #{idx + 1}")
                    if cid not in queue_map:
                        item_copy = dict(item)
                        item_copy["reason"] = reason
                        queue_map[cid] = item_copy

        pending = list(queue_map.values())
        if total_discovered == 0 and not extra_urls:
            print("\n[!] Warning: 0 visible chats discovered across all surfaces — nothing was synced.")
            print("    (For specific chats, pass the URL directly: python3 scraper/capture_spark_chat.py <url>)")
        else:
            print(f"\n[+] Discovered {total_discovered} sidebar chat(s); queued {len(pending)} new/recent/incomplete conversation(s).")

        for i, conv in enumerate(pending, start=1):
            cid = conv["chat_id"]
            title = conv.get("title", cid)
            url = conv["url"]
            reason = conv.get("reason", "sync")
            print(f"\n--- [{i}/{len(pending)}] Syncing '{title}' ({cid}) [{reason}] ---")

            try:
                record = await engine._scrape_single_conversation(
                    page=page,
                    chat_id=cid,
                    initial_title=title,
                    url=url,
                    is_pinned=bool(conv.get("is_pinned")),
                    max_turns_limit=max_turns,
                    max_scroll_steps=effective_scroll_steps,
                )
                await engine._download_attachments(page, record)
                folder = await engine._export_with_playwright_pdf(context, record)
                print(f"✔ Synced '{record.title}' ({record.total_turns:,} turns) -> {folder.name}")
            except Exception as exc:
                err_str = f"{type(exc).__name__}: {exc}"
                print(f"✖ Error syncing {cid}: {err_str}")
                engine.db.mark_error(cid, err_str)

        manifest_path, index_path, global_hg_path = engine.exporter.write_master_manifest_and_index()
        print(f"\n[✓] Sync complete. Updated manifest: {manifest_path}")

        if browser:
            await page.close()
        else:
            await context.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Incremental Gemini + Spark Sync into archive.db")
    parser.add_argument("--archive", type=pathlib.Path, default=DEFAULT_ARCHIVE_DIR, help="Archive directory containing archive.db")
    parser.add_argument("--profile", type=pathlib.Path, default=DEFAULT_PROFILE_DIR, help="Chrome profile directory")
    parser.add_argument("--surface", action="append", dest="surfaces", help="Gemini/Spark surface URL(s) to scan")
    parser.add_argument("--recent", type=int, default=5, help="Top N recent chats per surface to re-check for new turns (default: 5)")
    parser.add_argument("--url", action="append", dest="extra_urls", default=[], help="Specific conversation or Spark URL to sync")
    parser.add_argument("--cdp-url", type=str, default=None, help="Optional Chrome CDP URL (e.g. http://127.0.0.1:9222)")
    parser.add_argument("--max-turns", type=int, default=5000)
    parser.add_argument("--max-scroll-steps", type=int, default=3000)
    args = parser.parse_args()

    surfaces = args.surfaces if args.surfaces else DEFAULT_SURFACES
    asyncio.run(
        run_incremental_sync(
            archive_dir=args.archive.expanduser().resolve(),
            profile_dir=args.profile.expanduser().resolve(),
            surfaces=surfaces,
            recent_refresh=args.recent,
            extra_urls=args.extra_urls,
            cdp_url=args.cdp_url,
            max_turns=args.max_turns,
            max_scroll_steps=args.max_scroll_steps,
        )
    )


if __name__ == "__main__":
    main()