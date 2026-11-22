#!/usr/bin/env python3
"""
Generate 300 DPI quantitative historiography figures for the Corpus History Companion Volume.
Reads strictly from pre-extracted read-only telemetry JSONs:
  - data/archive_ro_forensics.json (from Desktop archive.db?mode=ro)
  - data/local_corpus_forensics.json (from data/corpus.db?mode=ro & corpus.db.bak.20261119_pre_v3?mode=ro)
"""

import json
import os
import sqlite3
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", "/tmp/mpl_corpus_whitepaper")

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "output" / "whitepaper_assets"
ASSETS.mkdir(parents=True, exist_ok=True)

# Museum / University-Press Palette (matching Volume I)
INK = "#1C2127"
MUTED = "#5A626A"
GRID = "#E2DDD5"
CREAM = "#FAF8F4"
NAVY = "#1E3A5F"        # Verified / Primary Architecture
SLATE = "#6B7C93"       # Raw / Pre-audit / Background
RUST = "#B55239"        # Crisis / Bloat / Falsified
AMBER = "#C88A2E"       # Provisional / SIM_CONSISTENT / Contested
SAGE = "#2E6A5E"        # Consolidation / CAS / Survival
PLUM = "#6E4B6E"        # Contested
ROSE_BG = "#F8ECE8"
SAGE_BG = "#EAF2EF"
NAVY_BG = "#EAF0F6"
GOLD_BG = "#F5EFE3"

plt.rcParams.update({
    "font.family": "serif",
    "font.serif": ["DejaVu Serif"],
    "mathtext.fontset": "dejavuserif",
    "axes.edgecolor": "#B8B0A4",
    "axes.linewidth": 0.8,
    "axes.labelcolor": INK,
    "xtick.color": INK,
    "ytick.color": INK,
    "text.color": INK,
    "figure.facecolor": "white",
    "axes.facecolor": "white",
    "savefig.dpi": 300,
    "savefig.bbox": "tight",
    "savefig.pad_inches": 0.20,
})


def build_hist_fig1_timeline():
    """
    Figure 1: Longitudinal Material History of the Corpus
      Panel A: Conversation & word stratigraphy across all 342 threads in archive.db (chronological order)
      Panel B: The 26-day archival-industrial crucible (Oct 26 - Nov 20, 2026): 189.57 GB Overkill spike -> 294 MB CAS -> 893 nodes -> Schema v3 -> White Paper
    """
    arch = json.loads((ROOT / "data" / "archive_ro_forensics.json").read_text())
    local = json.loads((ROOT / "data" / "local_corpus_forensics.json").read_text())

    # Panel A: Reconstruct chronological strata from archive.db rowid_deciles
    # Note: In Gemini sidebar scraping on 2026-10-26, rows 1..279 were discovered newest-first (row 279 = oldest, row 1 = Oct 26),
    # followed by post-scrape captures rows 280..342 (Nov 11..15).
    decs = arch["rowid_deciles"]
    # Pre-scrape deciles (indices 0..7 cover rows 1..272, index 8 covers 273..306 mixing 273..279 + Nov 11-13, indices 9..10 cover 307..342).
    # For cleanest historical fidelity, group into 6 true archival strata from the raw deciles + discovered_day counts!
    strata_labels = [
        "Stratum 1\nOldest Pre-History\n(rows 272–205)\nAuDHD/PDA & Axioms",
        "Stratum 2\nCognitive Audit &\nEarly Metaphysics\n(rows 204–171)",
        "Stratum 3\nGenesis Codex &\nLarge-Text Sprawl\n(rows 170–137)",
        "Stratum 4\nPi / Number Theory\n& Resonance Cycle\n(rows 136–103)",
        "Stratum 5\nArchiver, Hypergraph\n& Pre-Scrape Peak\n(rows 102–1)",
        "Stratum 6\nPost-Scrape Reckoning\nOverkill & Codex\n(rows 280–342)",
    ]
    # Compute exact figures from rowid_deciles:
    # decs[0]: 1..34, decs[1]: 35..68, decs[2]: 69..102 -> Stratum 5
    # decs[3]: 103..136 -> Stratum 4
    # decs[4]: 137..170 -> Stratum 3
    # decs[5]: 171..204 -> Stratum 2
    # decs[6]: 205..238, decs[7]: 239..272 -> Stratum 1
    # decs[8]: 273..306, decs[9]: 307..340, decs[10]: 341..342 -> Stratum 6 (note 273..279 is tiny 7 convs)
    s_words = [
        (decs[6]["est_words"] + decs[7]["est_words"]) / 1000.0,
        decs[5]["est_words"] / 1000.0,
        decs[4]["est_words"] / 1000.0,
        decs[3]["est_words"] / 1000.0,
        (decs[0]["est_words"] + decs[1]["est_words"] + decs[2]["est_words"]) / 1000.0,
        (decs[8]["est_words"] + decs[9]["est_words"] + decs[10]["est_words"]) / 1000.0,
    ]
    s_turns = [
        decs[6]["turns"] + decs[7]["turns"],
        decs[5]["turns"],
        decs[4]["turns"],
        decs[3]["turns"],
        decs[0]["turns"] + decs[1]["turns"] + decs[2]["turns"],
        decs[8]["turns"] + decs[9]["turns"] + decs[10]["turns"],
    ]

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(13.6, 8.2), gridspec_kw={"height_ratios": [1.0, 1.15]})
    fig.subplots_adjust(hspace=0.46, top=0.90, bottom=0.11)

    # --- PANEL A ---
    x = np.arange(len(strata_labels))
    bar_cols = [SLATE, SLATE, RUST, AMBER, NAVY, SAGE]
    bars = ax1.bar(x, s_words, width=0.56, color=bar_cols, edgecolor="white", linewidth=0.8, zorder=3)
    ax1_r = ax1.twinx()
    ax1_r.plot(x, s_turns, color=INK, marker="o", markersize=6.0, linewidth=1.8, linestyle="--", label="Captured Turns", zorder=5)

    for idx, (b, w_k, t_n) in enumerate(zip(bars, s_words, s_turns)):
        y_w = w_k + 22
        if idx == 2:
            y_w = w_k - 78
            ax1.text(b.get_x() + b.get_width() / 2, y_w, f"{w_k:,.0f}k w", ha="center", va="center",
                     fontsize=7.9, fontweight="bold", color="white")
        else:
            ax1.text(b.get_x() + b.get_width() / 2, y_w, f"{w_k:,.0f}k w", ha="center", va="bottom",
                     fontsize=7.8, fontweight="bold", color=INK)
        y_t = t_n + 165 if idx != 1 else t_n - 210
        ax1_r.text(idx, y_t, f"{t_n:,} turns", ha="center", va="center",
                   fontsize=7.1, color=INK, style="italic",
                   bbox=dict(boxstyle="round,pad=0.14", fc="white", ec="none", alpha=0.88), zorder=6)

    ax1.annotate("Genesis Body (2025-12-16)\n& Processing Large Text (638k w)",
                 xy=(2, s_words[2] + 8), xytext=(0.78, 1070),
                 ha="center", fontsize=7.4, fontweight="bold", color=RUST,
                 bbox=dict(boxstyle="round,pad=0.28", fc=ROSE_BG, ec=RUST, lw=0.85),
                 arrowprops=dict(arrowstyle="->", color=RUST, lw=0.95))

    ax1.annotate("Overkill Collapse, HTTP 429\n& Hand Sub-Network (Nov 11–15)",
                 xy=(5, s_words[5] + 95), xytext=(3.78, 1075),
                 ha="center", fontsize=7.4, fontweight="bold", color=SAGE,
                 bbox=dict(boxstyle="round,pad=0.28", fc=SAGE_BG, ec=SAGE, lw=0.85),
                 arrowprops=dict(arrowstyle="->", color=SAGE, lw=0.95))

    ax1.set_ylim(0, 1230)
    ax1_r.set_ylim(0, 3150)
    ax1.set_xticks(x)
    ax1.set_xticklabels(strata_labels, fontsize=7.4)
    ax1.set_ylabel("Estimated Words (Thousands)", fontsize=8.8, fontweight="bold", color=NAVY)
    ax1_r.set_ylabel("Dialogue Turns", fontsize=8.8, fontweight="bold", color=INK)
    ax1.set_title("A. Conversational Stratigraphy Across All 342 Archive Threads (8,922 Turns · 2.16M Verbatim Words / 16.83M Chars)",
                  fontsize=9.8, fontweight="bold", pad=10, loc="left")
    ax1.grid(axis="y", color=GRID, linewidth=0.6, zorder=0)
    ax1.spines["top"].set_visible(False)
    ax1_r.spines["top"].set_visible(False)

    # --- PANEL B: 26-Day Material & Epistemic Crucible (Oct 25 - Nov 20, 2026) ---
    ft_days = {r["day"]: r["bytes"] / 1e9 for r in arch["file_trail_by_day_recent"] if r["day"] >= "2026-10-25"}
    # Build complete continuous calendar Oct 25 .. Nov 20 (27 days)
    dates = [f"2026-10-{d:02d}" for d in range(25, 32)] + [f"2026-11-{d:02d}" for d in range(1, 21)]
    date_lbls = [d[5:] for d in dates]
    gb_vals = [ft_days.get(d, 0.0) for d in dates]
    # Add post-CAS SQLite steady-state markers (Nov 13-15 CAS = 0.294 GB; Nov 16-20 corpus.db = 0.077 GB)
    xi = np.arange(len(dates))

    # Era shading bands on Panel B
    ax2.axvspan(-0.5, 18.5, color=ROSE_BG, alpha=0.40, zorder=0)
    ax2.axvspan(18.5, 21.5, color=GOLD_BG, alpha=0.50, zorder=0)
    ax2.axvspan(21.5, 24.5, color=NAVY_BG, alpha=0.45, zorder=0)
    ax2.axvspan(24.5, 26.5, color=SAGE_BG, alpha=0.55, zorder=0)

    # Plot daily file bloat on log scale (in MB, floor 0.5 MB for visual readability when >0)
    mb_vals = [v * 1000.0 if v > 0 else 0.0 for v in gb_vals]
    b_cols = [RUST if m > 1000 else SLATE for m in mb_vals]
    ax2.bar(xi, [m if m > 0 else np.nan for m in mb_vals], width=0.65, color=b_cols, edgecolor="white", linewidth=0.5, zorder=3,
            label="Daily Pre-CAS File Volume (MB, file_trail.modified_at)")

    # Overlay post-migration compact SQLite footprint line (Nov 13-20)
    cas_x = [19, 20, 21, 22, 23, 24, 25, 26]  # Nov 13..Nov 20
    cas_mb = [294.3, 294.3, 294.3, 76.9, 76.9, 76.9, 76.9, 77.1]  # 294.3 MB CAS -> 77.1 MB corpus.db
    ax2.plot(cas_x, cas_mb, color=SAGE, marker="s", markersize=5.0, linewidth=2.0, zorder=5,
             label="Post-CAS / Local SQLite Kernel Footprint (294 MB CAS \u2192 77.1 MB corpus.db)")

    ax2.set_yscale("log")
    ax2.set_ylim(0.5, 3.2e6)

    # Major historical inflection annotations
    ax2.annotate("OVERKILL SPIKE (Oct 27)\n122,944 files · 186.30 GB\n(189.57 GB total bloat)",
                 xy=(2, 186304), xytext=(6.6, 480000),
                 ha="center", fontsize=7.6, fontweight="bold", color=RUST,
                 bbox=dict(boxstyle="round,pad=0.30", fc="white", ec=RUST, lw=0.9),
                 arrowprops=dict(arrowstyle="->", color=RUST, lw=1.05))

    ax2.annotate("Playwright Scrape\n279 convs (Oct 26)",
                 xy=(1, 2622), xytext=(3.6, 16000),
                 ha="center", fontsize=7.0, color=INK,
                 arrowprops=dict(arrowstyle="->", color=INK, lw=0.85))

    ax2.annotate("overkill_migrate.py\n(Nov 13–15)\n189.6 GB \u2192 294 MB\n(99.84% compressed)",
                 xy=(19, 320), xytext=(15.0, 26000),
                 ha="center", fontsize=7.4, fontweight="bold", color=SAGE,
                 bbox=dict(boxstyle="round,pad=0.28", fc="white", ec=SAGE, lw=0.9),
                 arrowprops=dict(arrowstyle="->", color=SAGE, lw=1.0))

    ax2.annotate("Rings 1–4A Sprint\n(Nov 16–17)\n893 nodes · 174\u00d7\nsingle-loop pivot",
                 xy=(22, 85), xytext=(20.6, 2200),
                 ha="center", fontsize=7.2, fontweight="bold", color=NAVY,
                 bbox=dict(boxstyle="round,pad=0.26", fc="white", ec=NAVY, lw=0.85),
                 arrowprops=dict(arrowstyle="->", color=NAVY, lw=0.9))

    ax2.annotate("Self-Audit, Live DOI\nRemediation (1,122)\n& Trilogy (Nov 19\u201320)",
                 xy=(25.5, 85), xytext=(24.2, 60000),
                 ha="center", fontsize=7.2, fontweight="bold", color=NAVY,
                 bbox=dict(boxstyle="round,pad=0.26", fc=NAVY_BG, ec=NAVY, lw=0.9),
                 arrowprops=dict(arrowstyle="->", color=NAVY, lw=0.95))

    ax2.set_xticks(xi[::2])
    ax2.set_xticklabels(date_lbls[::2], fontsize=7.6)
    ax2.set_xlabel("Calendar Date (October 25 \u2013 November 20, 2026)", fontsize=8.8, fontweight="bold")
    ax2.set_ylabel("Material Storage Scale (MB, Log Scale)", fontsize=8.8, fontweight="bold")
    ax2.set_title("B. The 26-Day Material & Epistemic Crucible: From 189.57 GB Recursive Hypergraph Bloat to 77.1 MB SQLite Kernel",
                  fontsize=10.0, fontweight="bold", pad=10, loc="left")
    ax2.legend(loc="lower left", frameon=True, facecolor="white", framealpha=0.94, edgecolor=GRID, fontsize=7.5)
    ax2.grid(axis="y", which="major", color=GRID, linewidth=0.6, zorder=1)
    ax2.spines["top"].set_visible(False)
    ax2.spines["right"].set_visible(False)

    fig.suptitle("Figure 1. Longitudinal Material History of the Corpus: Archival Stratigraphy and Storage-to-Verification Compression",
                 fontsize=11.4, fontweight="bold", y=0.97)
    fig.text(0.01, 0.012,
             "Source: Read-only primary extraction from Desktop archive.db (?mode=ro: 342 conversations, 8,922 turns, 166,915 file_trail records, 10,424 cas_blobs) and data/corpus.db (?mode=ro).\n"
             "Panel A preserves Gemini sidebar capture stratigraphy (oldest threads rows 272\u2013205 through Oct 26 rows 102\u20131 and post-scrape Nov 11\u201315 rows 280\u2013342). Panel B plots exact file_trail modified_at bytes.",
             fontsize=7.2, color=MUTED, style="italic")

    out = ASSETS / "hist_fig1_longitudinal_timeline.png"
    fig.savefig(out, dpi=300)
    plt.close(fig)
    print(f"Saved {out}")


def build_hist_fig2_epistemic_audit():
    """
    Figure 2: Three-Stage Epistemic Transformation & Live DOI Remediation Chart
      Panel A: Pre-Audit v0.2.0 (893) -> Schema v3 Self-Demotion (893) -> Post-Part-1 Live DOI Remediation (1,122)
      Panel B: Domain-by-Domain EV Collapse & Live DOI Recovery (0 open audit flags)
    """
    local = json.loads((ROOT / "data" / "local_corpus_forensics.json").read_text())
    pre = local["pre_v3_tiers"]
    v3 = local["v3_tiers"]
    pre_dom = local["pre_v3_domain_tiers"]
    v3_dom = local["v3_domain_tiers"]

    # Query live remediated data/corpus.db strictly read-only (?mode=ro)
    conn = sqlite3.connect(f"file:{ROOT / 'data' / 'corpus.db'}?mode=ro", uri=True)
    live = dict(conn.execute("SELECT epistemic_tier, COUNT(*) FROM nodes GROUP BY epistemic_tier").fetchall())
    live_dom = {}
    for d, t, c in conn.execute("SELECT domain, epistemic_tier, COUNT(*) FROM nodes GROUP BY domain, epistemic_tier"):
        live_dom.setdefault(d, {})[t] = c
    conn.close()

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13.8, 5.2), gridspec_kw={"width_ratios": [1.14, 1.02]})
    fig.subplots_adjust(wspace=0.28, top=0.79, bottom=0.20)

    # Panel A: 3-Stage Tier Shift (v0.2.0 -> Schema v3 -> Post-Part-1 Live)
    tiers = [
        ("EXTERNALLY_VERIFIED", "Externally\nVerified", NAVY),
        ("FALSIFIED", "Falsified\n(Negative)", RUST),
        ("RAW_CLAIM", "Raw Claim\n(Rescued/Lock)", SLATE),
        ("CONTESTED", "Contested\n(Unsettled)", PLUM),
        ("SIM_CONSISTENT", "Sim-Consistent\n(Toy Model)", AMBER),
    ]
    x = np.arange(len(tiers))
    w = 0.25
    pre_vals = [pre.get(t[0], 0) for t in tiers]
    v3_vals = [v3.get(t[0], 0) for t in tiers]
    live_vals = [live.get(t[0], 0) for t in tiers]

    b1 = ax1.bar(x - w, pre_vals, w, label="1. Pre-Audit v0.2.0 (893 nodes)", color="#C5CFD8", edgecolor="white", linewidth=0.6, zorder=3)
    b2 = ax1.bar(x, v3_vals, w, label="2. Schema v3 Demotion (893 · 539 flags)", color="#E0B66A", edgecolor="white", linewidth=0.6, zorder=3)
    b3 = ax1.bar(x + w, live_vals, w, label="3. Post-Part-1 Live DOI (1,122 · 0 flags)", color=[t[2] for t in tiers], edgecolor="white", linewidth=0.6, zorder=3)

    for bp, bv, bl, pv, vv, lv in zip(b1, b2, b3, pre_vals, v3_vals, live_vals):
        ax1.text(bp.get_x() + bp.get_width() / 2, pv + 8, f"{pv}", ha="center", va="bottom", fontsize=6.6, color=MUTED)
        ax1.text(bv.get_x() + bv.get_width() / 2, vv + 8, f"{vv}", ha="center", va="bottom", fontsize=6.6, color="#8A5E14")
        ax1.text(bl.get_x() + bl.get_width() / 2, lv + 8, f"{lv}", ha="center", va="bottom", fontsize=7.3, fontweight="bold", color=INK)

    ax1.annotate("463 live HTTP-200 DOIs/URLs\n+ 229 atomic splits_from children\n(539/539 flags closed; 0 pycheck: lit)",
                 xy=(2.25, 195), xytext=(3.10, 440),
                 ha="center", fontsize=7.0, fontweight="bold", color=INK,
                 bbox=dict(boxstyle="round,pad=0.32", fc=SAGE_BG, ec=SAGE, lw=0.9),
                 arrowprops=dict(arrowstyle="->", color=SAGE, lw=1.0))

    ax1.set_ylim(0, 720)
    ax1.set_xticks(x)
    ax1.set_xticklabels([t[1] for t in tiers], fontsize=7.5)
    ax1.set_ylabel("Number of Atomic Epistemic Nodes", fontsize=8.8, fontweight="bold")
    ax1.set_title("A. Three-Stage Epistemic Evolution (893 \u2192 1,122 Nodes)", fontsize=9.8, fontweight="bold", pad=10, loc="left")
    ax1.legend(loc="upper right", frameon=True, facecolor="white", framealpha=0.96, edgecolor=GRID, fontsize=7.0)
    ax1.grid(axis="y", color=GRID, linewidth=0.6, zorder=0)
    ax1.spines["top"].set_visible(False)
    ax1.spines["right"].set_visible(False)

    # Panel B: Domain-by-Domain EV Trajectory (v0.2.0 -> v3 Drop -> Live DOI Recovery)
    doms = [
        ("physics", "Ring 1\nPhysics &\nThermo"),
        ("formal_math", "Ring 2\nFormal Math\n& Lean 4"),
        ("bio_neuro_psych", "Ring 4A\nBio, Neuro\n& Psych"),
        ("ai_systems", "Ring 3\nAI Systems &\nCybernetics"),
    ]
    xd = np.arange(len(doms))
    wd = 0.25
    pre_ev = [pre_dom[d[0]].get("EXTERNALLY_VERIFIED", 0) for d in doms]
    v3_ev = [v3_dom[d[0]].get("EXTERNALLY_VERIFIED", 0) for d in doms]
    live_ev = [live_dom[d[0]].get("EXTERNALLY_VERIFIED", 0) for d in doms]

    ax2.bar(xd - wd, pre_ev, wd, color="#C5CFD8", edgecolor="white", linewidth=0.6, label="Pre-Audit v0.2.0 EV (incl. pycheck:)", zorder=3)
    ax2.bar(xd, v3_ev, wd, color=AMBER, edgecolor="white", linewidth=0.6, label="Schema v3 Retained EV (Non-Lit Only)", zorder=3)
    ax2.bar(xd + wd, live_ev, wd, color=NAVY, edgecolor="white", linewidth=0.6, label="Post-Part-1 Live DOI / Law EV", zorder=3)

    for idx, (p, v, l) in enumerate(zip(pre_ev, v3_ev, live_ev)):
        ax2.text(idx - wd, p + 4, f"{p}", ha="center", va="bottom", fontsize=6.7, color=MUTED)
        ax2.text(idx, v + 4, f"{v}", ha="center", va="bottom", fontsize=6.7, color="#8A5E14")
        ax2.text(idx + wd, l + 4, f"{l}", ha="center", va="bottom", fontsize=7.5, fontweight="bold", color=NAVY)
        rec_pct = 100.0 * l / p if p else 0.0
        ax2.text(idx, max(p, l) + 23, f"{rec_pct:.0f}% rec.", ha="center", va="bottom",
                 fontsize=7.0, fontweight="bold", color=SAGE)

    ax2.set_ylim(0, 295)
    ax2.set_xticks(xd)
    ax2.set_xticklabels([d[1] for d in doms], fontsize=7.6)
    ax2.set_ylabel("EXTERNALLY_VERIFIED Nodes", fontsize=8.8, fontweight="bold")
    ax2.set_title("B. Ring-by-Ring EV Drop (v3) & Live DOI Recovery", fontsize=9.8, fontweight="bold", pad=10, loc="left")
    ax2.legend(loc="upper right", frameon=True, facecolor="white", framealpha=0.96, edgecolor=GRID, fontsize=7.0)
    ax2.grid(axis="y", color=GRID, linewidth=0.6, zorder=0)
    ax2.spines["top"].set_visible(False)
    ax2.spines["right"].set_visible(False)

    fig.suptitle("Figure 2. The Self-Audit & Live Remediation Arc: v0.2.0 Pre-Audit \u2192 Schema v3 Demotion \u2192 Post-Part-1 Live DOI Ledger",
                 fontsize=11.0, fontweight="bold", y=0.99)
    fig.text(0.01, 0.012,
             "Source: Read-only diff across corpus.db.bak.20261119_pre_v3 (v0.2.0), corpus.db.bak.20261120_152209 (Schema v3), and live remediated data/corpus.db (?mode=ro).\n"
             "AI Systems shows the strictest anti-rubber-stamping filter (79.6% EV recovery; 22 internal architecture contracts & unsettled specs honestly downgraded to RAW_CLAIM / CONTESTED).",
             fontsize=7.1, color=MUTED, style="italic")

    out = ASSETS / "hist_fig2_epistemic_tier_audit.png"
    fig.savefig(out, dpi=300)
    plt.close(fig)
    print(f"Saved {out}")


if __name__ == "__main__":
    build_hist_fig1_timeline()
    build_hist_fig2_epistemic_audit()
