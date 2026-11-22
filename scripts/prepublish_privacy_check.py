#!/usr/bin/env python3
"""
Automated Pre-Publish Privacy & Integrity Scanner (`scripts/prepublish_privacy_check.py`)

Scans `release_stage/` (and any git-tracked candidate files if a git repo is present)
and HARD-FAILS (non-zero exit) on ANY privacy violation or integrity failure:
  1. Volume III / Verbatim Archive Ban:
       - corpus_verbatim_dialogue_complete*
       - Verbatim/ or Sage/Verbatim/
       - dialogue_shards/
       - corpus_history_extended* / extended_history_* (contains private 342-chat ledger)
  2. Raw Private Database & Backup Ban:
       - archive.db, corpus.db, dialogue_build.db
       - *.db, *.db-wal, *.db-shm, *.sqlite, *.sqlite3, *.bak.*
  3. Secrets, Credentials, Private Dumps & Local Host Path Ban:
       - .env, .env.*, *.pem, *.key, credentials.json
       - raw_corpus/, closedloop_deltas/, archive_ro_forensics.json, local_corpus_forensics.json,
         corpus_history_telemetry.json, dialogue_manifest_summary.json
       - Secret/API-key patterns (Google AIza..., OpenAI sk-..., GitHub ghp_..., Slack xox..., Private Keys)
       - Hardcoded personal home paths (/Users/<local-user>/...) inside staged public files
  4. Cryptographic Checksum & Standalone Test Verification:
       - `shasum -a 256 -c` for Volume I and Volume II inside BOTH `release_stage/github_repo/Sage/`
         and `release_stage/zenodo_bundle/`
       - `python3 -m unittest scripts/test_pilot_harness.py -v` inside `release_stage/github_repo/`
       - `python3 scripts/benchmark_gauntlet.py --self-test` inside `release_stage/github_repo/`

Read-only with respect to archive.db and data/corpus.db (never opens or touches private DBs).
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

# Auto-detect whether running from $CORPUS_HOME/scripts or release_stage/github_repo/scripts
THIS_FILE = Path(__file__).resolve()
REPO_ROOT = THIS_FILE.parent.parent

FORBIDDEN_PATH_SUBSTRINGS = (
    "corpus_verbatim_dialogue_complete",
    "dialogue_shards",
    "corpus_history_extended",
    "extended_history_dossier",
    "extended_history_strata",
    "extended_history_parts",
    "extended_history_audit_report",
    "closedloop_deltas",
    "raw_corpus",
    "archive_ro_forensics.json",
    "archive_backfill_report.json",
    "local_corpus_forensics.json",
    "corpus_history_telemetry.json",
    "dialogue_manifest_summary.json",
    "credentials.json",
    "spark_watchlist.txt",
)

FORBIDDEN_DIR_NAMES = {
    "Verbatim",
    "verbatim",
    "dialogue_shards",
    "raw_corpus",
    "closedloop_deltas",
    "extended_history_strata",
    "extended_history_parts",
    "digest_slices",
}

FORBIDDEN_FILE_GLOBS = (
    "*.db",
    "*.db-wal",
    "*.db-shm",
    "*.sqlite",
    "*.sqlite3",
    "*.bak.*",
    "*.bak",
    ".env",
    ".env.*",
    "*.pem",
    "*.key",
    "archive.db*",
    "corpus.db*",
    "dialogue_build.db*",
    "corpus_verbatim_dialogue_complete*",
    "corpus_history_extended*",
)

SECRET_CONTENT_PATTERNS = [
    ("Google/Gemini API Key", re.compile(r"AIza[0-9A-Za-z\-_]{25,}")),
    ("OpenAI/Anthropic Secret Key", re.compile(r"\bsk-(?:proj-|ant-)?[0-9A-Za-z\-_]{20,}")),
    ("GitHub Personal Access Token", re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[0-9A-Za-z]{20,}")),
    ("Slack Token", re.compile(r"\bxox[baprs]-[0-9A-Za-z\-]{10,}")),
    ("Private Key Material", re.compile(r"-----BEGIN (?:RSA |OPENSSH |EC |PGP )?PRIVATE KEY-----")),
    ("Hardcoded API Key Assignment", re.compile(r"(?:GEMINI|OPENAI|ANTHROPIC|GOOGLE)_API_KEY\s*=\s*['\"]?[A-Za-z0-9_\-]{18,}")),
]

PERSONAL_PATH_RE = re.compile(r"(?:/Users/|/home/)(?!\.\.\.|<|your|user\b|example\b)[A-Za-z0-9._-]{3,}(?:/|\b)")

TEXT_SUFFIXES = {
    ".py", ".md", ".txt", ".json", ".sql", ".cff", ".yml", ".yaml",
    ".sh", ".toml", ".ini", ".cfg", ".gitignore", "",
}


def find_python_with_sklearn() -> str:
    """Locate a Python interpreter that can run test_pilot_harness.py (needs numpy/sklearn)."""
    candidates: list[str] = []
    # Check parent CORPUS_HOME .venv if running inside release_stage/github_repo
    for base in (REPO_ROOT, REPO_ROOT.parent.parent):
        vp = base / ".venv" / "bin" / "python3"
        if vp.exists():
            candidates.append(str(vp))
    candidates.append(sys.executable)
    for extra in (shutil.which("python3"), "/Library/Frameworks/Python.framework/Versions/3.14/bin/python3"):
        if extra and extra not in candidates:
            candidates.append(extra)
    for py in candidates:
        try:
            proc = subprocess.run(
                [py, "-c", "import sklearn, numpy"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=10,
                check=False,
            )
            if proc.returncode == 0:
                return py
        except OSError:
            continue
    return sys.executable


def check_path_forbidden(rel_path: str, name: str, parts: tuple[str, ...]) -> list[str]:
    reasons: list[str] = []
    for d in parts[:-1]:
        if d in FORBIDDEN_DIR_NAMES:
            reasons.append(f"forbidden directory '{d}'")
    low_rel = rel_path.lower()
    for sub in FORBIDDEN_PATH_SUBSTRINGS:
        if sub.lower() in low_rel:
            reasons.append(f"forbidden artifact pattern '{sub}'")
    for glob_pat in FORBIDDEN_FILE_GLOBS:
        if fnmatch.fnmatch(name, glob_pat) or fnmatch.fnmatch(name.lower(), glob_pat.lower()):
            reasons.append(f"forbidden file glob '{glob_pat}'")
    return reasons


def scan_tree(scan_root: Path, label: str) -> dict[str, Any]:
    violations: list[dict[str, str]] = []
    files_scanned = 0
    if not scan_root.exists():
        return {"ok": False, "label": label, "error": f"Missing directory: {scan_root}", "files_scanned": 0, "violations": []}

    for p in sorted(scan_root.rglob("*")):
        rel_obj = p.relative_to(scan_root)
        # Skip .git internal metadata if user ran git init
        if ".git" in rel_obj.parts or "__pycache__" in rel_obj.parts:
            continue
        rel = rel_obj.as_posix()

        if p.is_dir():
            if p.name in FORBIDDEN_DIR_NAMES:
                violations.append({"path": rel, "rule": f"forbidden directory '{p.name}'"})
            continue

        files_scanned += 1
        reasons = check_path_forbidden(rel, p.name, rel_obj.parts)
        for r in reasons:
            violations.append({"path": rel, "rule": r})

        # Content scan on text files (skip this scanner's own regex definitions!)
        if p.name == "prepublish_privacy_check.py":
            continue
        if p.suffix.lower() in TEXT_SUFFIXES and p.stat().st_size <= 5 * 1024 * 1024:
            try:
                txt = p.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            for pat_name, rx in SECRET_CONTENT_PATTERNS:
                if rx.search(txt):
                    violations.append({"path": rel, "rule": f"secret/credential leak ({pat_name})"})
            if PERSONAL_PATH_RE.search(txt):
                violations.append({"path": rel, "rule": "hardcoded personal home path (/Users/<local-user>)"})
            if any(seg in rel_obj.parts for seg in ("scraper", "config")):
                for personal_tok in (
                    ".gemini_archiver_chrome_profile",
                    "Desktop/GeminiScraper",
                    "Desktop/GeminiAccountArchive",
                    "83b74d3a072ffe4d",
                    "4030c271f61cd5b2",
                    "7593b20d2e0d8790",
                ):
                    if personal_tok in txt:
                        violations.append({"path": rel, "rule": f"personal scraper/config path or chat ID ({personal_tok})"})

    return {
        "ok": len(violations) == 0 and files_scanned > 0,
        "label": label,
        "files_scanned": files_scanned,
        "violations": violations,
    }


def scan_git_tracked(git_root: Path) -> dict[str, Any]:
    if not (git_root / ".git").exists():
        return {"ok": True, "skipped": True, "reason": "not yet git-initialized", "tracked_files": 0, "violations": []}
    proc = subprocess.run(["git", "ls-files"], cwd=str(git_root), capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        return {"ok": False, "skipped": False, "error": proc.stderr.strip(), "violations": []}
    violations = []
    tracked = [ln.strip() for ln in proc.stdout.splitlines() if ln.strip()]
    for rel in tracked:
        p = Path(rel)
        reasons = check_path_forbidden(rel, p.name, p.parts)
        for r in reasons:
            violations.append({"path": rel, "rule": f"git-tracked {r}"})
    return {"ok": len(violations) == 0, "skipped": False, "tracked_files": len(tracked), "violations": violations}


def verify_sha256_pair(folder: Path, label: str) -> dict[str, Any]:
    required = [
        "two_hands_decentralized_whitepaper.pdf.sha256",
        "corpus_history_companion_volume.pdf.sha256",
        "corpus_failures_and_parables.pdf.sha256",
    ]
    allowed_pdfs = {
        "two_hands_decentralized_whitepaper.pdf",
        "corpus_history_companion_volume.pdf",
        "corpus_failures_and_parables.pdf",
    }
    results = []
    all_ok = True
    for sf in required:
        fp = folder / sf
        if not fp.exists():
            results.append({"file": sf, "ok": False, "detail": "missing .sha256 file"})
            all_ok = False
            continue
        proc = subprocess.run(["shasum", "-a", "256", "-c", sf], cwd=str(folder), capture_output=True, text=True, check=False)
        ok = proc.returncode == 0
        if not ok:
            all_ok = False
        results.append({"file": sf, "ok": ok, "detail": (proc.stdout or proc.stderr).strip()})
    # Ensure NO Volume III or Extended PDFs slipped into Sage/ or zenodo_bundle/
    extra_pdfs = sorted(
        p.name for p in folder.rglob("*.pdf")
        if p.name not in allowed_pdfs
    )
    if extra_pdfs:
        all_ok = False
        results.append({"file": "extra_pdfs", "ok": False, "detail": f"unexpected PDFs in {label}: {extra_pdfs}"})
    return {"ok": all_ok, "label": label, "checks": results}


def verify_required_layout(stage_root: Path) -> dict[str, Any]:
    required_paths = [
        "LAUNCH_CHECKLIST.md",
        "github_repo/README.md",
        "github_repo/.gitignore",
        "github_repo/LICENSE",
        "github_repo/CITATION.cff",
        "github_repo/.zenodo.json",
        "github_repo/Makefile",
        "github_repo/config/spark_watchlist.example.txt",
        "github_repo/schema/schema.sql",
        "github_repo/scraper/gemini_archiver.py",
        "github_repo/scraper/sync_gemini.py",
        "github_repo/scraper/capture_spark_chat.py",
        "github_repo/scripts/test_pilot_harness.py",
        "github_repo/scripts/benchmark_gauntlet.py",
        "github_repo/scripts/backfill_archive_virtualization.py",
        "github_repo/scripts/build_failures_parables_pdf.py",
        "github_repo/scripts/prepublish_privacy_check.py",
        "github_repo/data/benchmark_results.json",
        "github_repo/data/gauntlet_results.json",
        "github_repo/chapters/trilogy_redline_vetting_report.md",
        "github_repo/chapters/corpus_failures_parables.md",
        "github_repo/Sage/two_hands_decentralized_whitepaper.pdf",
        "github_repo/Sage/two_hands_decentralized_whitepaper.pdf.sha256",
        "github_repo/Sage/corpus_history_companion_volume.pdf",
        "github_repo/Sage/corpus_history_companion_volume.pdf.sha256",
        "github_repo/Sage/corpus_failures_and_parables.pdf",
        "github_repo/Sage/corpus_failures_and_parables.pdf.sha256",
        "zenodo_bundle/two_hands_decentralized_whitepaper.pdf",
        "zenodo_bundle/two_hands_decentralized_whitepaper.pdf.sha256",
        "zenodo_bundle/corpus_history_companion_volume.pdf",
        "zenodo_bundle/corpus_history_companion_volume.pdf.sha256",
        "zenodo_bundle/corpus_failures_and_parables.pdf",
        "zenodo_bundle/corpus_failures_and_parables.pdf.sha256",
        "zenodo_bundle/trilogy_redline_vetting_report.md",
        "zenodo_bundle/zenodo_metadata.json",
        "launch_posts/hacker_news_show_hn.md",
        "launch_posts/reddit_localllama.md",
        "launch_posts/lesswrong_localfirst.md",
    ]
    missing = [rel for rel in required_paths if not (stage_root / rel).exists()]
    return {"ok": len(missing) == 0, "checked": len(required_paths), "missing": missing}


def run_staged_tests(github_repo: Path, py: str) -> dict[str, Any]:
    # 1. Unittest suite (test_pilot_harness.py) inside staged github_repo
    env = os.environ.copy()
    env["CORPUS_HOME"] = str(github_repo)
    p_ut = subprocess.run(
        [py, "-m", "unittest", "scripts/test_pilot_harness.py", "-v"],
        cwd=str(github_repo),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    ut_tail = "\n".join((p_ut.stderr or p_ut.stdout or "").strip().splitlines()[-4:])

    # 2. Kestrel-7 deterministic self-test inside staged github_repo
    p_st = subprocess.run(
        [py, "scripts/benchmark_gauntlet.py", "--self-test"],
        cwd=str(github_repo),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    st_out = (p_st.stdout or p_st.stderr or "").strip()

    return {
        "ok": p_ut.returncode == 0 and p_st.returncode == 0,
        "python": py,
        "unittest_ok": p_ut.returncode == 0,
        "unittest_summary": ut_tail,
        "gauntlet_selftest_ok": p_st.returncode == 0,
        "gauntlet_selftest_output": st_out,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Hard Pre-Publish Privacy & Integrity Gate for Public Release Staging")
    parser.add_argument(
        "--stage-dir",
        type=Path,
        default=REPO_ROOT / "release_stage",
        help="Path to release_stage/ directory (default: $CORPUS_HOME/release_stage)",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON report")
    args = parser.parse_args()

    stage_root = args.stage_dir.expanduser().resolve()
    github_repo = stage_root / "github_repo"
    zenodo_bundle = stage_root / "zenodo_bundle"

    # Support running directly inside github_repo if release_stage/ doesn't exist
    standalone_github_mode = not stage_root.exists() and (REPO_ROOT / "Sage").exists() and (REPO_ROOT / "CITATION.cff").exists()
    if standalone_github_mode:
        github_repo = REPO_ROOT
        privacy_scan = scan_tree(github_repo, "github_repo (standalone)")
        git_scan = scan_git_tracked(github_repo)
        sha_gh = verify_sha256_pair(github_repo / "Sage", "github_repo/Sage")
        py = find_python_with_sklearn()
        tests = run_staged_tests(github_repo, py)
        all_ok = privacy_scan["ok"] and git_scan["ok"] and sha_gh["ok"] and tests["ok"]
        report = {
            "mode": "standalone_github_repo",
            "ok": all_ok,
            "privacy_scan": privacy_scan,
            "git_tracked_scan": git_scan,
            "sha256_github_sage": sha_gh,
            "staged_tests": tests,
        }
    else:
        layout = verify_required_layout(stage_root)
        privacy_scan = scan_tree(stage_root, "release_stage (full tree)")
        git_scan_gh = scan_git_tracked(github_repo)
        sha_gh = verify_sha256_pair(github_repo / "Sage", "github_repo/Sage")
        sha_zen = verify_sha256_pair(zenodo_bundle, "zenodo_bundle")
        py = find_python_with_sklearn()
        tests = run_staged_tests(github_repo, py)
        all_ok = (
            layout["ok"]
            and privacy_scan["ok"]
            and git_scan_gh["ok"]
            and sha_gh["ok"]
            and sha_zen["ok"]
            and tests["ok"]
        )
        report = {
            "mode": "full_release_stage",
            "stage_dir": str(stage_root),
            "ok": all_ok,
            "layout_check": layout,
            "privacy_scan": privacy_scan,
            "git_tracked_scan": git_scan_gh,
            "sha256_github_sage": sha_gh,
            "sha256_zenodo_bundle": sha_zen,
            "staged_tests": tests,
        }

    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print("=== PRE-PUBLISH PRIVACY & INTEGRITY SCANNER ===")
        if "layout_check" in report:
            lc = report["layout_check"]
            print(f"[{'PASS' if lc['ok'] else 'FAIL'}] required_layout ({lc['checked'] - len(lc['missing'])}/{lc['checked']} files present)")
            if lc["missing"]:
                print(f"       MISSING: {lc['missing']}")
        ps = report["privacy_scan"]
        print(f"[{'PASS' if ps['ok'] else 'FAIL'}] privacy_scan ({ps['files_scanned']} files scanned, {len(ps['violations'])} violations)")
        for v in ps["violations"][:20]:
            print(f"       VIOLATION: {v['path']} -> {v['rule']}")
        gs = report["git_tracked_scan"]
        gs_note = "not git-initialized yet" if gs.get("skipped") else f"{gs.get('tracked_files', 0)} tracked files, {len(gs['violations'])} violations"
        print(f"[{'PASS' if gs['ok'] else 'FAIL'}] git_tracked_scan ({gs_note})")
        for key in ("sha256_github_sage", "sha256_zenodo_bundle"):
            if key in report:
                sr = report[key]
                print(f"[{'PASS' if sr['ok'] else 'FAIL'}] {key}")
                for c in sr["checks"]:
                    print(f"       {c['file']}: {c['detail']}")
        st = report["staged_tests"]
        print(f"[{'PASS' if st['unittest_ok'] else 'FAIL'}] unittest_pilot_harness ({st['python']})")
        for ln in st["unittest_summary"].splitlines():
            print(f"       {ln}")
        print(f"[{'PASS' if st['gauntlet_selftest_ok'] else 'FAIL'}] benchmark_gauntlet --self-test")
        for ln in st["gauntlet_selftest_output"].splitlines()[-3:]:
            print(f"       {ln}")
        print(f"\nOVERALL PRE-PUBLISH GATE: {'PASS (SAFE TO FLIP SWITCH)' if report['ok'] else 'HARD FAIL (DO NOT PUBLISH)'}")

    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
