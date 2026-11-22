#!/usr/bin/env python3
"""
Generate 300 DPI publication-grade figures for the Two Hands Decentralized White Paper.
Reads live metrics directly from data/gauntlet_results.json and data/benchmark_results.json.
"""

import json
import os
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", "/tmp/mpl_corpus_whitepaper")

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "output" / "whitepaper_assets"
ASSETS.mkdir(parents=True, exist_ok=True)

# Museum / University-Press Palette
INK = "#1C2127"
MUTED = "#5A626A"
GRID = "#E2DDD5"
CREAM = "#FAF8F4"
NAVY = "#1E3A5F"        # SQLite State-Gated / Right Hand Primary
SLATE = "#6B7C93"       # Ungated Full History
RUST = "#B55239"        # Hybrid RAG / Warning / Falsified
AMBER = "#C88A2E"       # Thinking Tokens / Accent
SAGE = "#2E6A5E"        # Left Hand / Integration / Verified
GOLD_BG = "#F4EFE6"
ROSE_BG = "#F8ECE8"
SAGE_BG = "#EAF2EF"
NAVY_BG = "#EAF0F6"

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


def build_fig1_kestrel7():
    """Figure 1: Kestrel-7 Three-Regime Capability Knee (direct from data/gauntlet_results.json)."""
    data = json.loads((ROOT / "data" / "gauntlet_results.json").read_text())
    runs = data["runs"]

    models = [
        ("llama2:latest (7B)", "llama2:7B\nLocal 8 GB M1\n(Below Knee)"),
        ("cloud:flash_lite", "cloud:flash_lite\nLightweight\n(At Knee)"),
        ("cloud:flash", "cloud:flash\nHeavyweight\n(Above Knee)"),
    ]
    arms = [
        ("ungated_full_history", "Ungated Full History", SLATE),
        ("matched_token_hybrid_rag", "Matched-Token Hybrid RAG", RUST),
        ("sqlite_gated", "SQLite State-Gated (v3)", NAVY),
    ]

    lookup = {(r["model"], r["arm"]): r for r in runs}

    fig, axes = plt.subplots(1, 3, figsize=(14.4, 5.0), gridspec_kw={"width_ratios": [1.0, 1.0, 1.22]})
    fig.subplots_adjust(wspace=0.35, top=0.79, bottom=0.22)

    x = np.arange(len(models))
    width = 0.25

    # Panel A: Step Accuracy (%)
    ax = axes[0]
    for i, (arm_key, arm_label, color) in enumerate(arms):
        vals = [lookup[(m[0], arm_key)]["accuracy_pct"] for m in models]
        bars = ax.bar(x + (i - 1) * width, vals, width, label=arm_label, color=color, edgecolor="white", linewidth=0.6, zorder=3)
        for b, v in zip(bars, vals):
            y_pos = max(v + 2.2, 2.5)
            weight = "bold" if arm_key == "sqlite_gated" else "normal"
            ax.text(b.get_x() + b.get_width() / 2, y_pos, f"{v:.0f}%", ha="center", va="bottom",
                    fontsize=7.6, fontweight=weight, color=INK)

    ax.axhline(85.0, color=SAGE, linestyle="--", linewidth=1.1, zorder=2)
    ax.text(-0.42, 87.8, "Theoretical ceiling:\n85.0% (17/20)", fontsize=7.3, color=SAGE, style="italic", va="bottom")
    ax.annotate("+30 pp raw\n(+35 pp sem.*)", xy=(1 + width, 93.0), xytext=(0.95, 106.5),
                ha="center", fontsize=7.4, fontweight="bold", color=NAVY,
                arrowprops=dict(arrowstyle="->", color=NAVY, lw=0.95, connectionstyle="arc3,rad=-0.12"))
    ax.set_ylim(0, 118)
    ax.set_xlim(-0.52, 2.52)
    ax.set_ylabel("Step Accuracy (%)", fontsize=9.2, fontweight="bold")
    ax.set_title("A. Step Accuracy (Higher is Better)", fontsize=10.0, fontweight="bold", pad=10, loc="left")
    ax.set_xticks(x)
    ax.set_xticklabels([m[1] for m in models], fontsize=7.8)
    ax.grid(axis="y", color=GRID, linestyle="-", linewidth=0.6, zorder=0)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    # Panel B: Contradiction Recurrence Rate (%)
    ax = axes[1]
    for i, (arm_key, arm_label, color) in enumerate(arms):
        vals = [lookup[(m[0], arm_key)]["contradiction_recurrence_rate_pct"] for m in models]
        bars = ax.bar(x + (i - 1) * width, vals, width, color=color, edgecolor="white", linewidth=0.6, zorder=3)
        for b, v in zip(bars, vals):
            y_pos = v + 2.2
            lbl = f"{v:.1f}%" if v % 1 else f"{v:.0f}%"
            weight = "bold" if arm_key == "sqlite_gated" else "normal"
            ax.text(b.get_x() + b.get_width() / 2, y_pos, lbl, ha="center", va="bottom",
                    fontsize=7.4, fontweight=weight, color=INK)

    ax.annotate("RAG regressed\n(Step 19 mass)", xy=(2.0, 21.5), xytext=(2.0, 44.0),
                ha="center", fontsize=7.3, color=RUST, style="italic",
                arrowprops=dict(arrowstyle="->", color=RUST, lw=0.9))
    ax.set_ylim(0, 116)
    ax.set_xlim(-0.52, 2.52)
    ax.set_ylabel("Post-Correction Recurrence (%)", fontsize=9.2, fontweight="bold")
    ax.set_title("B. Contradiction Recurrence (Lower)", fontsize=9.6, fontweight="bold", pad=10, loc="left")
    ax.set_xticks(x)
    ax.set_xticklabels([m[1] for m in models], fontsize=7.8)
    ax.grid(axis="y", color=GRID, linestyle="-", linewidth=0.6, zorder=0)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    # Panel C: Stacked Total Tokens (Prompt In + Visible Out + Provider Thinking)
    ax = axes[2]
    for i, (arm_key, arm_label, color) in enumerate(arms):
        in_tok = [lookup[(m[0], arm_key)]["total_input_tokens"] / 1000.0 for m in models]
        out_tok = [lookup[(m[0], arm_key)]["total_output_tokens"] / 1000.0 for m in models]
        thk_tok = [lookup[(m[0], arm_key)]["total_thoughts_tokens"] / 1000.0 for m in models]
        pos = x + (i - 1) * width

        ax.bar(pos, in_tok, width, color=color, edgecolor="white", linewidth=0.5, zorder=3)
        ax.bar(pos, out_tok, width, bottom=in_tok, color="#9BA8B7", edgecolor="white", linewidth=0.5, zorder=3)
        ax.bar(pos, thk_tok, width, bottom=np.array(in_tok) + np.array(out_tok),
               color=AMBER, edgecolor="white", linewidth=0.5, hatch="///", zorder=3)

        totals = [lookup[(m[0], arm_key)]["total_tokens_incl_thinking"] / 1000.0 for m in models]
        for px, tot in zip(pos, totals):
            weight = "bold" if arm_key == "sqlite_gated" else "normal"
            ax.text(px, tot + 1.3, f"{tot:.1f}k", ha="center", va="bottom",
                    fontsize=7.3, fontweight=weight, color=INK)

    ax.annotate("-56.5%\ntotal tokens", xy=(1 + width, 25.5), xytext=(1.30, 50.5),
                ha="center", fontsize=7.5, fontweight="bold", color=NAVY,
                arrowprops=dict(arrowstyle="->", color=NAVY, lw=0.95))
    ax.annotate("-46.7%", xy=(2 + width, 38.0), xytext=(2.28, 56.5),
                ha="center", fontsize=7.5, fontweight="bold", color=NAVY,
                arrowprops=dict(arrowstyle="->", color=NAVY, lw=0.95))

    ax.set_ylim(0, 70)
    ax.set_xlim(-0.52, 2.55)
    ax.set_ylabel("Total Tokens (Thousands)", fontsize=9.2, fontweight="bold")
    ax.set_title("C. Total Fuel: Prompt + Output + Thinking", fontsize=10.0, fontweight="bold", pad=10, loc="left")
    ax.set_xticks(x)
    ax.set_xticklabels([m[1] for m in models], fontsize=7.8)
    ax.grid(axis="y", color=GRID, linestyle="-", linewidth=0.6, zorder=0)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    legend_handles = [
        mpatches.Patch(facecolor=SLATE, label="Ungated Full History"),
        mpatches.Patch(facecolor=RUST, label="Matched-Token Hybrid RAG"),
        mpatches.Patch(facecolor=NAVY, label="SQLite State-Gated (v3)"),
        mpatches.Patch(facecolor=AMBER, hatch="///", edgecolor="white", label="Provider Thinking Tokens (Harvested)"),
    ]
    fig.legend(handles=legend_handles, loc="upper center", bbox_to_anchor=(0.5, 0.935),
               ncol=4, frameon=False, fontsize=8.5)
    fig.suptitle("Figure 3. Kestrel-7 Stateful Contradiction Gauntlet: Three-Regime Capability Knee (N = 20 Steps, 8 Post-Correction Traps)",
                 fontsize=11.4, fontweight="bold", y=1.00)

    fig.text(0.01, 0.008,
             "Source: Live executions in data/gauntlet_results.json (Panel C shows task-payload + output + provider thinking tokens; excludes fixed host subagent wrapper).\n"
             "*True semantic accuracy (excluding wrong-reason blind guesses on Steps 2\u20133 & Step 13 6.4>=6.5 slip): flash_lite 45% \u2192 80% (+35 pp; recurrence n=8 Fisher p=0.282). "
             "Local llama2:7B rescued JSON 0%\u219285% yet held 100% recurrence.",
             fontsize=7.0, color=MUTED, style="italic")

    out = ASSETS / "fig1_kestrel7_capability_knee.png"
    fig.savefig(out, dpi=300)
    plt.close(fig)
    print(f"Saved {out}")


def build_fig2_amortization():
    """Figure 2: Exp. 1 Trade-Offs, Exp. 2 Log Compression, and Amortization Curve (Q* = 1,137)."""
    bench = json.loads((ROOT / "data" / "benchmark_results.json").read_text())
    agg = bench["aggregates"]
    arm_a = agg["arm_a"]
    arm_b = agg["arm_b"]
    amort = agg["amortization"]

    fig, axes = plt.subplots(1, 3, figsize=(14.0, 4.8), gridspec_kw={"width_ratios": [1.05, 0.95, 1.22]})
    fig.subplots_adjust(wspace=0.33, top=0.81, bottom=0.20)

    # Panel A: Exp 1 Relative Change (Arm B vs Arm A baseline = 100%)
    ax = axes[0]
    metrics = [
        ("Input Tokens\n(140.3k \u2192 62.8k)", (arm_b["total_input_tokens"] / arm_a["total_input_tokens"] - 1) * 100, NAVY),
        ("Visible API Cost\n(\\$0.0176 \u2192 \\$0.0100)", (arm_b["total_cost_usd"] / arm_a["total_cost_usd"] - 1) * 100, SAGE),
        ("Accuracy\n(95% \u2192 100%, p=1.0)", (arm_b["accuracy_rate"] - arm_a["accuracy_rate"]) * 100, "#4B799B"),
        ("Visible Output\n(8.9k \u2192 9.2k)", (arm_b["total_output_tokens"] / arm_a["total_output_tokens"] - 1) * 100, AMBER),
        ("Wall Latency\n(29.8s \u2192 40.1s/q)", (arm_b["avg_latency_s"] / arm_a["avg_latency_s"] - 1) * 100, RUST),
    ]
    y_pos = np.arange(len(metrics))
    vals = [m[1] for m in metrics]
    cols = [m[2] for m in metrics]

    ax.axvline(0, color=INK, linewidth=0.9, zorder=3)
    bars = ax.barh(y_pos, vals, height=0.56, color=cols, edgecolor="white", zorder=3)
    for b, v in zip(bars, vals):
        if v < 0:
            ax.text(v - 2.2, b.get_y() + b.get_height() / 2, f"{v:+.1f}%", va="center", ha="right",
                    fontsize=7.8, fontweight="bold", color=INK)
        else:
            ax.text(v + 2.2, b.get_y() + b.get_height() / 2, f"{v:+.1f}%", va="center", ha="left",
                    fontsize=7.8, fontweight="bold", color=INK)

    ax.set_yticks(y_pos)
    ax.set_yticklabels([m[0] for m in metrics], fontsize=7.6)
    ax.invert_yaxis()
    ax.set_xlim(-80, 58)
    ax.set_xlabel("Change: Compiled Kernel vs. Raw RAG (%)", fontsize=8.4, fontweight="bold")
    ax.set_title("A. Exp. 1 Query Trade-Off (N = 20)", fontsize=9.8, fontweight="bold", pad=10, loc="left")
    ax.grid(axis="x", color=GRID, linewidth=0.6, zorder=0)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    # Panel B: Exp 2 Context per Committed Node (Log Scale)
    ax = axes[1]
    labels_b = ["Wave 1\nFull Swarm\n(8 agents)", "Wave 1\nCore A+B+C\n(5 agents)", "Stateless\nSingle-Loop\n(6 calls)"]
    vals_b = [616690, 455730, 2619]
    cols_b = [SLATE, RUST, NAVY]
    xb = np.arange(len(labels_b))
    bars_b = ax.bar(xb, vals_b, width=0.52, color=cols_b, edgecolor="white", zorder=3)
    ax.set_yscale("log")
    ax.set_ylim(800, 2.5e6)
    for b, v in zip(bars_b, vals_b):
        ax.text(b.get_x() + b.get_width() / 2, v * 1.18, f"{v:,}", ha="center", va="bottom",
                fontsize=7.9, fontweight="bold", color=INK)

    ax.annotate("235.5\u00d7 lower\n(174.0\u00d7 vs. Core)", xy=(2.0, 5200), xytext=(1.35, 36000),
                ha="center", fontsize=7.8, fontweight="bold", color=NAVY,
                bbox=dict(boxstyle="round,pad=0.32", fc=NAVY_BG, ec=NAVY, lw=0.85),
                arrowprops=dict(arrowstyle="->", color=NAVY, lw=1.0))

    ax.set_xticks(xb)
    ax.set_xticklabels(labels_b, fontsize=7.8)
    ax.set_ylabel("Prompt Context / Committed Node (Log Scale)", fontsize=8.4, fontweight="bold")
    ax.set_title("B. Exp. 2 Compilation Compression", fontsize=9.8, fontweight="bold", pad=10, loc="left")
    ax.grid(axis="y", which="major", color=GRID, linewidth=0.6, zorder=0)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    # Panel C: Amortization Break-Even Curve (Post-Part-1 1,122-Node Corpus: Raw Token vs USD-Weighted)
    ax = axes[2]
    compile_tok_1122 = 1122 * (2619 + 2293)  # 5,511,264 tokens (2,619 in + 2,293 out / node)
    delta_tok = arm_a["avg_tokens"] - arm_b["avg_tokens"]
    q_star_tok = int(np.ceil(compile_tok_1122 / delta_tok))  # 1,428 queries
    q_star_usd = 3465  # dollar-weighted at $0.10/1M in, $0.40/1M out (4x output premium)

    q = np.linspace(0, 4000, 350)
    c_raw = (q * arm_a["avg_tokens"]) / 1e6
    c_comp = (compile_tok_1122 + q * arm_b["avg_tokens"]) / 1e6
    y_star = (q_star_tok * arm_a["avg_tokens"]) / 1e6

    ax.axvspan(0, q_star_tok, color=ROSE_BG, alpha=0.55, zorder=0)
    ax.axvspan(q_star_tok, q_star_usd, color=GOLD_BG, alpha=0.55, zorder=0)
    ax.axvspan(q_star_usd, 4000, color=SAGE_BG, alpha=0.60, zorder=0)

    ax.plot(q, c_raw, color=RUST, linewidth=2.0, linestyle="--", label=f"Arm A: Raw RAG ({arm_a['avg_tokens']:,.0f} tok/q)", zorder=3)
    ax.plot(q, c_comp, color=NAVY, linewidth=2.2, label=f"Arm B: Compiled Kernel (5.51M + {arm_b['avg_tokens']:,.0f} tok/q)", zorder=4)
    ax.scatter([q_star_tok], [y_star], color=INK, s=42, zorder=5)
    ax.axvline(q_star_tok, color=MUTED, linestyle=":", linewidth=1.0, zorder=2)
    ax.axvline(q_star_usd, color=SAGE, linestyle="-.", linewidth=1.1, zorder=2)

    ax.annotate(f"Raw-token parity\nQ*_tok = {q_star_tok:,}", xy=(q_star_tok, y_star), xytext=(520, 17.5),
                ha="center", fontsize=7.2, fontweight="bold", color=INK,
                bbox=dict(boxstyle="round,pad=0.28", fc="white", ec=INK, lw=0.8),
                arrowprops=dict(arrowstyle="->", color=INK, lw=0.95, connectionstyle="arc3,rad=0.15"))
    ax.text(q_star_usd - 80, 29.0, "USD parity (4\u00d7 out)\nQ*_USD = 3,465", ha="right", va="top",
            fontsize=7.1, fontweight="bold", color=SAGE,
            bbox=dict(boxstyle="round,pad=0.25", fc="white", ec=SAGE, lw=0.75))

    ax.text(700, 29.5, "Ad-hoc / Self-Route\ncheaper", ha="center", va="top", fontsize=7.0, color=RUST, style="italic")

    ax.set_xlim(0, 4000)
    ax.set_ylim(0, 31.5)
    ax.set_xlabel("Cumulative Query Volume (Q)", fontsize=8.4, fontweight="bold")
    ax.set_ylabel("Cumulative Total Tokens (Millions)", fontsize=8.4, fontweight="bold")
    ax.set_title("C. Amortization (1,122-Node Live Ledger)", fontsize=9.6, fontweight="bold", pad=10, loc="left")
    ax.legend(loc="lower right", frameon=True, facecolor="white", framealpha=0.94, edgecolor=GRID, fontsize=6.8)
    ax.grid(color=GRID, linewidth=0.5, zorder=1)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    fig.suptitle("Figure 2. Retrieval Compression vs. Latency Trade-Off, Compilation Context Reduction, and Amortization Threshold",
                 fontsize=11.4, fontweight="bold", y=0.98)
    fig.text(0.01, 0.012,
             "Source: Experiment 1 aggregates from data/benchmark_results.json (N = 20) and Experiment 2 pilot telemetry (2,619 in + 2,293 out tok/node).\n"
             "Post-remediation 1,122-node ledger (~5.51M compile tokens) hits parity at Q*_tok = 1,428 raw tokens and Q*_USD = 3,465 queries under 4\u00d7 output pricing "
             "(earlier 893-node baseline: 1,137 raw / 2,758 USD).",
             fontsize=7.1, color=MUTED, style="italic")

    out = ASSETS / "fig2_amortization_compression.png"
    fig.savefig(out, dpi=300)
    plt.close(fig)
    print(f"Saved {out}")


def build_fig3_chiral_architecture():
    """Figure 3: Clean Museum-Monograph Schematic of v3 Architecture, Stage 3 Mirror Plane, and The Clasp."""
    fig, ax = plt.subplots(figsize=(13.8, 8.6))
    ax.set_xlim(-0.08, 13.68)
    ax.set_ylim(0, 8.6)
    ax.axis("off")

    # Background archival bands with dedicated margins for Appeal Hatch (left) and Stage 3 Break (center)
    ax.add_patch(FancyBboxPatch((1.12, 2.08), 4.82, 5.65, boxstyle="round,pad=0.06,rounding_size=0.14",
                                facecolor=NAVY_BG, edgecolor="#C7D5E4", linewidth=1.0, zorder=0))
    ax.add_patch(FancyBboxPatch((7.66, 2.08), 4.82, 5.65, boxstyle="round,pad=0.06,rounding_size=0.14",
                                facecolor=SAGE_BG, edgecolor="#C3DBD3", linewidth=1.0, zorder=0))

    # Column Headers
    ax.text(3.53, 7.45, "RIGHT-HANDED ENANTIOMER (FALSIFICATION-FIRST)", ha="center", va="center",
            fontsize=8.2, fontweight="bold", color=NAVY)
    ax.text(3.53, 7.16, "Decoupled State Gating (v3)  \u00b7  Socratic Elenchus  \u00b7  Science",
            ha="center", va="center", fontsize=7.3, color=MUTED, style="italic")

    ax.text(10.07, 7.45, "LEFT-HANDED ENANTIOMER (INTEGRATION-FIRST)", ha="center", va="center",
            fontsize=8.2, fontweight="bold", color=SAGE)
    ax.text(10.07, 7.16, "Classical Liturgical Form  \u00b7  Communal Binding  \u00b7  Stewardship",
            ha="center", va="center", fontsize=7.3, color=MUTED, style="italic")

    # Central Vertical Chiral Mirror Plane
    ax.plot([6.80, 6.80], [2.16, 7.68], color=RUST, linestyle=(0, (5, 3)), linewidth=1.6, zorder=2)
    ax.text(6.80, 7.88, "CHIRAL MIRROR PLANE", ha="center", va="center", fontsize=7.8, fontweight="bold", color=RUST)

    def draw_stage_box(x0, y0, w, h, title, subtitle, bg, ec, title_col):
        box = FancyBboxPatch((x0, y0), w, h, boxstyle="round,pad=0.04,rounding_size=0.10",
                             facecolor=bg, edgecolor=ec, linewidth=1.25, zorder=3)
        ax.add_patch(box)
        ax.text(x0 + w / 2, y0 + h * 0.72, title, ha="center", va="center",
                fontsize=8.4, fontweight="bold", color=title_col, zorder=4)
        ax.text(x0 + w / 2, y0 + h * 0.29, subtitle, ha="center", va="center",
                fontsize=7.0, color=INK, linespacing=1.25, zorder=4)

    ys = [6.00, 4.74, 3.48, 2.22]
    bh = 0.88
    bw = 4.46
    rx = 1.30
    lx = 7.84

    right_stages = [
        ("Stage 1 \u00b7 Atomic Lifting (Lifter)",
         "Stateless LLM (\u2264 2,200 tok) \u2192 single RAW_CLAIM\nAnchored to exact SHA-256 source chunk"),
        ("Stage 2 \u00b7 Transactional Commit (Scientist)",
         "DSL_CONSISTENT lock-in inside local SQLite ledger\nFormal scope & measurable prediction fixed pre-test"),
        ("Stage 3 \u00b7 Adversarial Falsifier Gate",
         "Verifier-Scope Coupling (no python_sim on lit; DOI lock)\nEmits EXTERNALLY_VERIFIED or FALSIFIED + pivoted_to"),
        ("Stage 4 \u00b7 ACID SQLite State Commit (:=)",
         "Cleared register 0 (Aporia) + deterministic state_register\nPreserves [FALSIFIED] steric guardrails across sessions"),
    ]
    left_stages = [
        ("Stage 1 \u00b7 Offertory (Material Substrate)",
         "Cultured earthly staples (grain \u2192 bread; grapes \u2192 wine)\nDaily human labor & ordinary maintenance brought forward"),
        ("Stage 2 \u00b7 Anaphora (Canonical Commit)",
         "Public blessing & canonical acceptance (Rappaport)\nBinds assembly to shared historical & ethical order"),
        ("Stage 3 \u00b7 Sacramental Fraction (Opening)",
         "Unified vessel spatially divided across the assembly\nExplicitly non-falsifiable (communal opening, not lab test)"),
        ("Stage 4 \u00b7 Communion (Augustinian Reversal)",
         "Shared substrate assimilates isolated ego into one body\n(Confessions VII.10.16: 'you will be changed into me')"),
    ]

    for idx, y0 in enumerate(ys):
        ec_r = RUST if idx == 2 else NAVY
        bg_r = ROSE_BG if idx == 2 else "white"
        draw_stage_box(rx, y0, bw, bh, right_stages[idx][0], right_stages[idx][1], bg_r, ec_r, ec_r)

        ec_l = RUST if idx == 2 else SAGE
        bg_l = GOLD_BG if idx == 2 else "white"
        draw_stage_box(lx, y0, bw, bh, left_stages[idx][0], left_stages[idx][1], bg_l, ec_l, ec_l)

        if idx < 3:
            ax.annotate("", xy=(rx + bw / 2, ys[idx + 1] + bh + 0.04), xytext=(rx + bw / 2, y0 - 0.04),
                        arrowprops=dict(arrowstyle="-|>", color=NAVY, lw=1.35), zorder=4)
            ax.annotate("", xy=(lx + bw / 2, ys[idx + 1] + bh + 0.04), xytext=(lx + bw / 2, y0 - 0.04),
                        arrowprops=dict(arrowstyle="-|>", color=SAGE, lw=1.35), zorder=4)

    # Dedicated left-margin Defeasible Appeal Hatch (ZERO overlap with boxes!)
    appeal_box = FancyBboxPatch((0.02, 3.85), 0.96, 1.48, boxstyle="round,pad=0.04,rounding_size=0.08",
                                facecolor="#FFFBF2", edgecolor=AMBER, linewidth=1.2, zorder=5)
    ax.add_patch(appeal_box)
    ax.text(0.50, 4.59, "Appeal Hatch\nreopens\nUNDER_APPEAL\n/ CONTESTED", ha="center", va="center",
            fontsize=5.9, fontweight="bold", color="#8A5710", linespacing=1.28, zorder=6)

    arr_out = FancyArrowPatch((rx - 0.03, 3.86), (1.02, 4.18), connectionstyle="arc3,rad=0.18",
                              arrowstyle="-|>", mutation_scale=11, linestyle="--", linewidth=1.3, color=AMBER, zorder=6)
    arr_in = FancyArrowPatch((1.02, 4.98), (rx - 0.03, 5.20), connectionstyle="arc3,rad=-0.18",
                             arrowstyle="-|>", mutation_scale=11, linestyle="--", linewidth=1.3, color=AMBER, zorder=6)
    ax.add_patch(arr_out)
    ax.add_patch(arr_in)

    # Center corridor Stage 3 Parity Break Callout (fits cleanly between x=5.94 and x=7.66!)
    ax.add_patch(FancyBboxPatch((6.02, 3.56), 1.56, 0.72, boxstyle="round,pad=0.04,rounding_size=0.08",
                                facecolor="white", edgecolor=RUST, linewidth=1.5, zorder=7))
    ax.text(6.80, 4.08, "STAGE 3 BREAK", ha="center", va="center", fontsize=7.5, fontweight="bold", color=RUST, zorder=8)
    ax.text(6.80, 3.76, "Falsification \u2260 Fraction\nForbids H(P)\u22480 collapse", ha="center", va="center",
            fontsize=6.3, color=INK, linespacing=1.25, zorder=8)

    # Bottom Convergence: THE CLASP
    clasp_box = FancyBboxPatch((1.35, 0.34), 10.90, 1.22, boxstyle="round,pad=0.06,rounding_size=0.18",
                               facecolor=CREAM, edgecolor=INK, linewidth=1.5, zorder=3)
    ax.add_patch(clasp_box)

    arr_l = FancyArrowPatch((3.53, 2.18), (5.20, 1.60), connectionstyle="arc3,rad=0.16",
                            arrowstyle="-|>", mutation_scale=13, linewidth=1.6, color=NAVY, zorder=5)
    arr_r = FancyArrowPatch((10.07, 2.18), (8.40, 1.60), connectionstyle="arc3,rad=-0.16",
                            arrowstyle="-|>", mutation_scale=13, linewidth=1.6, color=SAGE, zorder=5)
    ax.add_patch(arr_l)
    ax.add_patch(arr_r)

    ax.text(6.80, 1.24, "THE CLASP  \u2014  Closed Tensile Ring & Standing Equilibrium",
            ha="center", va="center", fontsize=10.2, fontweight="bold", color=INK, zorder=4)
    ax.text(6.80, 0.76,
            "Local ACID ledger holds defeasible truth boundaries (Right Hand)  \u2194  Unobserved-cost stewardship holds communal vessel (Left Hand)\n"
            "Both reject Closed-Loop Infallibility: prediction error stays open \u00b7 daily maintenance holds the vintage \u00b7 zero energy leaked to applause.",
            ha="center", va="center", fontsize=7.7, color=MUTED, linespacing=1.35, zorder=4)

    ax.text(6.80, 8.32, "Figure 1. Chiral Parity Architecture: Decoupled Neuro-Symbolic State Gating vs. Integration-First Liturgy",
            ha="center", va="center", fontsize=11.4, fontweight="bold", color=INK)

    out = ASSETS / "fig3_chiral_architecture_clasp.png"
    fig.savefig(out, dpi=300)
    plt.close(fig)
    print(f"Saved {out}")


if __name__ == "__main__":
    build_fig1_kestrel7()
    build_fig2_amortization()
    build_fig3_chiral_architecture()
