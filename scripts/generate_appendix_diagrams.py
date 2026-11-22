#!/usr/bin/env python3
"""
Generate 4 publication-grade 300 DPI system architecture diagrams for Volume I Appendix B
(Reproducible System How-To & Replication Guide).

Matches Volume I's museum / university-press palette and typography exactly.
Outputs to output/whitepaper_assets/:
  - diag1_end_to_end_architecture.png
  - diag2_ingestion_trigger_gating.png
  - diag3_defeasible_state_machine.png
  - diag4_single_loop_gauntlet_runtime.png
"""

import os
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", "/tmp/mpl_corpus_whitepaper")

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "output" / "whitepaper_assets"
ASSETS.mkdir(parents=True, exist_ok=True)

# Museum / University-Press Palette (exact match to generate_whitepaper_figures.py)
INK = "#1C2127"
MUTED = "#5A626A"
GRID = "#D8D2C7"
CREAM = "#FAF8F4"
NAVY = "#1E3A5F"        # SQLite Ledger / Primary Architecture
SLATE = "#556880"       # Stateless Front-End / Auxiliary
RUST = "#B55239"        # FALSIFIED / Blocked / Abort
AMBER = "#B87A1E"       # Provisional / Appeal / Budget
SAGE = "#2E6A5E"        # Verified / Allowed / External Primary
PLUM = "#6B4C73"        # Contested / Under Appeal
NAVY_BG = "#EAF0F6"
SAGE_BG = "#EAF2EF"
ROSE_BG = "#F8ECE8"
GOLD_BG = "#F6EFE2"
PLUM_BG = "#F3EEF5"
SLATE_BG = "#EFF2F5"

plt.rcParams.update({
    "font.family": "serif",
    "font.serif": ["DejaVu Serif"],
    "axes.facecolor": "white",
    "figure.facecolor": "white",
    "text.color": INK,
    "savefig.dpi": 300,
    "savefig.bbox": "tight",
    "savefig.pad_inches": 0.16,
})


def box(ax, x, y, w, h, title, body="", bg="white", ec=NAVY, tc=NAVY,
        title_fs=8.0, body_fs=6.7, lw=1.2, rad=0.10, title_y=0.73, body_y=0.31, z=3):
    patch = FancyBboxPatch((x, y), w, h, boxstyle=f"round,pad=0.04,rounding_size={rad}",
                           facecolor=bg, edgecolor=ec, linewidth=lw, zorder=z)
    ax.add_patch(patch)
    if body:
        ax.text(x + w / 2, y + h * title_y, title, ha="center", va="center",
                fontsize=title_fs, fontweight="bold", color=tc, zorder=z + 1)
        ax.text(x + w / 2, y + h * body_y, body, ha="center", va="center",
                fontsize=body_fs, color=INK, linespacing=1.28, zorder=z + 1)
    else:
        ax.text(x + w / 2, y + h / 2, title, ha="center", va="center",
                fontsize=title_fs, fontweight="bold", color=tc, linespacing=1.22, zorder=z + 1)


def arrow(ax, p1, p2, color=NAVY, lw=1.35, ls="-", rad=0.0, scale=11, z=5):
    arr = FancyArrowPatch(p1, p2, connectionstyle=f"arc3,rad={rad}",
                          arrowstyle="-|>", mutation_scale=scale,
                          linewidth=lw, linestyle=ls, color=color, zorder=z)
    ax.add_patch(arr)


def build_diag1_end_to_end():
    """Diagram 1: End-to-End Decoupled Neuro-Symbolic Architecture."""
    fig, ax = plt.subplots(figsize=(13.6, 6.4))
    ax.set_xlim(0, 13.6)
    ax.set_ylim(0, 6.4)
    ax.axis("off")

    ax.text(6.8, 6.12, "Diagram 1. End-to-End Decoupled Architecture: Stateless LLM Front-End, Python Gatekeeper & Local ACID SQLite",
            ha="center", va="center", fontsize=10.8, fontweight="bold", color=INK)

    # Outer Zone Backgrounds
    ax.add_patch(FancyBboxPatch((0.20, 0.52), 3.35, 5.18, boxstyle="round,pad=0.06,rounding_size=0.14",
                                facecolor=SLATE_BG, edgecolor="#C5CDD6", lw=1.0, zorder=0))
    ax.add_patch(FancyBboxPatch((4.15, 0.52), 4.00, 5.18, boxstyle="round,pad=0.06,rounding_size=0.14",
                                facecolor=GOLD_BG, edgecolor="#DECBA8", lw=1.0, zorder=0))
    ax.add_patch(FancyBboxPatch((8.75, 2.55), 4.65, 3.15, boxstyle="round,pad=0.06,rounding_size=0.14",
                                facecolor=NAVY_BG, edgecolor="#BACBE0", lw=1.0, zorder=0))
    ax.add_patch(FancyBboxPatch((8.75, 0.52), 4.65, 1.82, boxstyle="round,pad=0.06,rounding_size=0.14",
                                facecolor=SAGE_BG, edgecolor="#B5D4C9", lw=1.0, zorder=0))

    # Zone Headers
    ax.text(1.88, 5.46, "1. STATELESS LLM FRONT-END", ha="center", va="center", fontsize=8.0, fontweight="bold", color=SLATE)
    ax.text(1.88, 5.20, "Swappable Commodity Parser (Zero DB Write)", ha="center", va="center", fontsize=6.7, color=MUTED, style="italic")

    ax.text(6.15, 5.46, "2. PYTHON RUNNER & GATEKEEPER", ha="center", va="center", fontsize=8.0, fontweight="bold", color=AMBER)
    ax.text(6.15, 5.20, "Deterministic Orchestration & Schema Enforcement", ha="center", va="center", fontsize=6.7, color=MUTED, style="italic")

    ax.text(11.08, 5.46, "3. LOCAL ACID SQLITE LEDGER", ha="center", va="center", fontsize=8.0, fontweight="bold", color=NAVY)
    ax.text(11.08, 5.20, "data/corpus.db (Single Portable File, WAL + FTS5)", ha="center", va="center", fontsize=6.7, color=MUTED, style="italic")

    ax.text(11.08, 2.13, "4. EXTERNAL GROUNDING ORACLES", ha="center", va="center", fontsize=8.0, fontweight="bold", color=SAGE)

    # Zone 1 boxes
    box(ax, 0.42, 3.65, 2.90, 1.25, "Cloud API or Local Ollama",
        "Gemini Flash / Flash-Lite\nor Local 3B–14B Weights\n(Zero retained chat state)",
        bg="white", ec=SLATE, tc=SLATE, title_y=0.78, body_y=0.35)
    box(ax, 0.42, 2.10, 2.90, 1.25, "Bounded Working Input",
        "Byte-identical static prefix\n+ core_digest.md (~24 KB)\n+ <= 2,200-token packet",
        bg="white", ec=NAVY, tc=NAVY, title_y=0.78, body_y=0.35)
    box(ax, 0.42, 0.72, 2.90, 1.12, "Strict JSON-Only Output",
        "Proposed claims / checks /\ndecisions (NEVER writes\ndirectly to verified tiers)",
        bg=ROSE_BG, ec=RUST, tc=RUST, title_y=0.76, body_y=0.33)

    # Zone 2 boxes
    box(ax, 4.38, 3.85, 3.54, 1.05, "Hydrator & Packet Assembler",
        "compile_digest.py · hydrate_pre_tick()\nFTS5 BM25 + concept_bridges expansion\nSuppresses FALSIFIED from positive slices",
        bg="white", ec=NAVY, tc=NAVY, title_y=0.78, body_y=0.33)
    box(ax, 4.38, 2.48, 3.54, 1.10, "Single-Loop & CLI Interfaces",
        "single_loop_runner.py (Steps A → B → C)\nbrain.py / brain_mcp.py / corpus_mcp.py\nZero multi-agent chat history replay",
        bg="white", ec=AMBER, tc=AMBER, title_y=0.78, body_y=0.34)
    box(ax, 4.38, 0.72, 3.54, 1.48, "Epistemic Gatekeeper (db_utils.py)",
        "validate_atomic_claim() (F2.3 lock)\n_validate_verification_inputs() (F2.2)\nverify_node() / verify_and_link()\nreopen_falsified_node() (F2.1 appeal)",
        bg="white", ec=RUST, tc=RUST, title_y=0.83, body_y=0.37)

    # Zone 3 boxes (SQLite)
    box(ax, 8.98, 3.92, 4.18, 1.02, "Core Epistemic Tables (schema/schema.sql)",
        "chunks + chunks_fts (FTS5) · chapter_slices\nnodes · edges (no self-loops) · node_provenance",
        bg="white", ec=NAVY, tc=NAVY, title_y=0.76, body_y=0.32)
    box(ax, 8.98, 2.74, 4.18, 0.98, "Audit & Engine Trigger Locks",
        "node_verifications · research_branches · node_audit_flags\ntrg_verif_scope_coupling (BEFORE INSERT RAISE ABORT)",
        bg=ROSE_BG, ec=RUST, tc=RUST, title_y=0.76, body_y=0.32)

    # Zone 4 boxes (Oracles)
    box(ax, 8.98, 1.24, 2.00, 0.68, "Primary Literature",
        "doi: / pmid: / arxiv: / https://\n(CrossRef, PubMed, NIST)",
        bg="white", ec=SAGE, tc=SAGE, title_fs=7.4, body_fs=6.1, title_y=0.73, body_y=0.28)
    box(ax, 11.16, 1.24, 2.00, 0.68, "Local Python Sandbox",
        "run_physics_check()\n→ pycheck:<sha256>",
        bg="white", ec=SAGE, tc=SAGE, title_fs=7.4, body_fs=6.1, title_y=0.73, body_y=0.28)
    box(ax, 8.98, 0.64, 4.18, 0.46, "Read-Only Primary Archive: archive.db (?mode=ro) · core_digest.md",
        bg=CREAM, ec=MUTED, tc=MUTED, title_fs=5.9, lw=0.9)

    # Connecting Arrows (clean corridors between zones x=3.55..4.15 and x=8.15..8.75)
    arrow(ax, (4.35, 4.35), (3.36, 4.25), color=NAVY, lw=1.45)
    ax.text(3.85, 4.55, "<=2.2k\ntok", ha="center", va="center", fontsize=6.4, fontweight="bold", color=NAVY)
    arrow(ax, (3.36, 1.28), (4.35, 1.48), color=RUST, lw=1.45)
    ax.text(3.85, 1.65, "JSON\nonly", ha="center", va="center", fontsize=6.4, fontweight="bold", color=RUST)

    arrow(ax, (1.88, 3.62), (1.88, 3.38), color=SLATE, lw=1.1, ls=":")
    arrow(ax, (1.88, 2.07), (1.88, 1.87), color=SLATE, lw=1.1, ls=":")
    arrow(ax, (6.15, 3.82), (6.15, 3.61), color=AMBER, lw=1.2)
    arrow(ax, (6.15, 2.45), (6.15, 2.23), color=AMBER, lw=1.2)

    # Gatekeeper <-> SQLite
    arrow(ax, (8.94, 4.42), (7.96, 4.42), color=NAVY, lw=1.4)
    ax.text(8.45, 4.66, "FTS5 +\n[FALS]", ha="center", va="center", fontsize=6.2, fontweight="bold", color=NAVY)
    arrow(ax, (7.96, 3.22), (8.94, 3.22), color=RUST, lw=1.4)
    ax.text(8.45, 3.46, "ACID\ncommit", ha="center", va="center", fontsize=6.2, fontweight="bold", color=RUST)

    # Gatekeeper <-> External Oracles
    arrow(ax, (7.96, 1.56), (8.94, 1.56), color=SAGE, lw=1.4)
    ax.text(8.45, 1.80, "verify\nexternal", ha="center", va="center", fontsize=6.2, fontweight="bold", color=SAGE)

    ax.text(6.8, 0.20,
            "Invariant: Language models propose structure in JSON; only deterministic Python checks + SQLite engine triggers commit verified tiers.",
            ha="center", va="center", fontsize=7.4, color=MUTED, style="italic")

    out = ASSETS / "diag1_end_to_end_architecture.png"
    fig.savefig(out, dpi=300)
    plt.close(fig)
    print(f"Saved {out}")


def build_diag2_ingestion_trigger():
    """Diagram 2: Stage 1 & 2 Ingestion, Atomic Gating & Trigger Enforcement Matrix."""
    fig, ax = plt.subplots(figsize=(13.6, 6.8))
    ax.set_xlim(0, 13.6)
    ax.set_ylim(0, 6.8)
    ax.axis("off")

    ax.text(6.8, 6.52, "Diagram 2. Stage 1 & 2 Ingestion, Atomic Claim Lock & SQLite Trigger Enforcement (trg_verif_scope_coupling)",
            ha="center", va="center", fontsize=10.6, fontweight="bold", color=INK)

    # Top Pipeline Band
    ax.add_patch(FancyBboxPatch((0.20, 4.25), 13.20, 1.95, boxstyle="round,pad=0.06,rounding_size=0.14",
                                facecolor=CREAM, edgecolor=GRID, lw=1.0, zorder=0))
    ax.text(0.42, 5.98, "INGESTION & PRE-COMMIT GATE PIPELINE (stage0_ingest.py → db_utils.py → schema/schema.sql)",
            ha="left", va="center", fontsize=7.6, fontweight="bold", color=NAVY)

    stages = [
        (0.38, "1. Stage 0 Ingest", "stage0_ingest.py\nSHA-256 dedup → chunks\nchunks_fts (FTS5)\nchapter_slices triage", NAVY_BG, NAVY, NAVY),
        (3.02, "2. Provenance Lock", "create_node_with_provenance()\nRequires >=1 valid chunk_id\nnode_provenance(node_id,\nchunk_id, quote_span)", NAVY_BG, NAVY, NAVY),
        (5.66, "3. Atomic Lock (F2.3)", "validate_atomic_claim()\nBlocks '(1)...(2)...' lists &\n'valid + flawed' bundles\nStarts RAW_CLAIM only", GOLD_BG, AMBER, AMBER),
        (8.30, "4. Python Guard (F2.2)", "_validate_verification_inputs()\nis_valid_primary_external_ref()\nRejects pycheck: on lit\nRejects llm_only -> EV/SIM", GOLD_BG, AMBER, AMBER),
        (10.94, "5. SQLite Trigger", "trg_verif_scope_coupling\nBEFORE INSERT ON\nnode_verifications\nRAISE(ABORT, ...)", ROSE_BG, RUST, RUST),
    ]
    bw = 2.26
    for idx, (x0, ttl, body, bg, ec, tc) in enumerate(stages):
        box(ax, x0, 4.46, bw, 1.28, ttl, body, bg=bg, ec=ec, tc=tc, title_fs=7.6, body_fs=6.2, title_y=0.81, body_y=0.36)
        if idx < len(stages) - 1:
            arrow(ax, (x0 + bw + 0.05, 5.10), (stages[idx + 1][0] - 0.05, 5.10), color=NAVY, lw=1.35)

    # Bottom Panel: Exact Allowed vs Blocked Matrix (from schema.sql lines 187-211 & db_utils.py lines 322-375)
    ax.add_patch(FancyBboxPatch((0.20, 0.48), 13.20, 3.52, boxstyle="round,pad=0.06,rounding_size=0.14",
                                facecolor="white", edgecolor="#B8B0A4", lw=1.0, zorder=0))
    ax.text(0.42, 3.77, "ENGINE-LEVEL COUPLING MATRIX: ALLOWED vs. BLOCKED (verifier_type × verification_scope × external_ref)",
            ha="left", va="center", fontsize=7.8, fontweight="bold", color=INK)

    # Left half: ALLOWED COMMITS
    ax.add_patch(FancyBboxPatch((0.40, 0.70), 6.22, 2.86, boxstyle="round,pad=0.04,rounding_size=0.10",
                                facecolor=SAGE_BG, edgecolor=SAGE, lw=1.1, zorder=1))
    ax.text(3.51, 3.35, "ALLOWED COMMITS (Pass Both db_utils.py & SQLite Trigger)",
            ha="center", va="center", fontsize=7.6, fontweight="bold", color=SAGE, zorder=2)

    allowed_rows = [
        ("python_sim  +  standard_physics_law / empirical_benchmark",
         "external_ref = pycheck:<sha256>  +  benchmark_ref  →  EXTERNALLY_VERIFIED / FALSIFIED"),
        ("python_sim  +  toy_model  (Toy-Script Lock)",
         "external_ref = pycheck:<sha256>  →  at most SIM_CONSISTENT (does NOT reset dry hops)"),
        ("lean_coq  +  standard_physics_law / empirical_benchmark",
         "external_ref = proof hash/URI  +  benchmark_ref  →  EXTERNALLY_VERIFIED"),
        ("literature_ref / public_record  +  literature_citation / primary_record",
         "external_ref MUST start with doi:, pmid:, arxiv:, or https://  +  benchmark_ref  →  EV / FALS"),
    ]
    for r_i, (r_top, r_bot) in enumerate(allowed_rows):
        ry = 2.86 - r_i * 0.62
        ax.add_patch(FancyBboxPatch((0.56, ry - 0.22), 5.90, 0.50, boxstyle="round,pad=0.02,rounding_size=0.06",
                                    facecolor="white", edgecolor="#B5D4C9", lw=0.8, zorder=2))
        ax.text(0.68, ry + 0.11, "[PASS]  " + r_top, ha="left", va="center", fontsize=6.4, fontweight="bold", color=SAGE, zorder=3)
        ax.text(0.88, ry - 0.10, r_bot, ha="left", va="center", fontsize=5.8, color=INK, zorder=3)

    # Right half: BLOCKED / RAISE(ABORT)
    ax.add_patch(FancyBboxPatch((6.98, 0.70), 6.22, 2.86, boxstyle="round,pad=0.04,rounding_size=0.10",
                                facecolor=ROSE_BG, edgecolor=RUST, lw=1.1, zorder=1))
    ax.text(10.09, 3.35, "BLOCKED COMMITS (ValueError / SQLite RAISE(ABORT))",
            ha="center", va="center", fontsize=7.6, fontweight="bold", color=RUST, zorder=2)

    blocked_rows = [
        ("python_sim  +  literature_citation  OR  primary_record",
         "BLOCKED by trg_verif_scope_coupling & db_utils.py (closes F2.2 pycheck theater)"),
        ("literature_ref / public_record  +  pycheck:<hash>  OR  bare text",
         "BLOCKED by SQLite trigger (requires strict doi:, pmid:, arxiv:, or https:// prefix)"),
        ("llm_only  →  EXTERNALLY_VERIFIED  OR  SIM_CONSISTENT",
         "BLOCKED by _validate_verification_inputs() (LLM self-assertion cannot promote)"),
        ("edges(from_node == to_node)  OR  ungrounded chunk_ids=[]",
         "BLOCKED by SQLite CHECK (from_node != to_node) & create_node_with_provenance()"),
    ]
    for r_i, (r_top, r_bot) in enumerate(blocked_rows):
        ry = 2.86 - r_i * 0.62
        ax.add_patch(FancyBboxPatch((7.14, ry - 0.22), 5.90, 0.50, boxstyle="round,pad=0.02,rounding_size=0.06",
                                    facecolor="white", edgecolor="#E2B9AF", lw=0.8, zorder=2))
        ax.text(7.26, ry + 0.11, "[BLOCK]  " + r_top, ha="left", va="center", fontsize=6.4, fontweight="bold", color=RUST, zorder=3)
        ax.text(7.46, ry - 0.10, r_bot, ha="left", va="center", fontsize=5.8, color=INK, zorder=3)

    ax.text(6.8, 0.18,
            "Defense-in-Depth: Even a raw SQL INSERT bypassing db_utils.py is aborted inside SQLite by trg_verif_scope_coupling.",
            ha="center", va="center", fontsize=7.4, color=MUTED, style="italic")

    out = ASSETS / "diag2_ingestion_trigger_gating.png"
    fig.savefig(out, dpi=300)
    plt.close(fig)
    print(f"Saved {out}")


def build_diag3_state_machine():
    """Diagram 3: Stage 3 Defeasible Negative Provenance State Machine."""
    fig, ax = plt.subplots(figsize=(13.6, 6.8))
    ax.set_xlim(0, 13.6)
    ax.set_ylim(0, 6.8)
    ax.axis("off")

    ax.text(6.8, 6.52, "Diagram 3. Stage 3 Defeasible Negative Provenance State Machine & Anti-Spin Branch Halting",
            ha="center", va="center", fontsize=10.8, fontweight="bold", color=INK)

    # State Nodes (all 7 exact nodes.epistemic_tier CHECK states)
    # Row 1 (Entry & Formalization): RAW_CLAIM -> DSL_CONSISTENT -> SIM_CONSISTENT
    box(ax, 0.45, 4.65, 2.35, 1.15, "RAW_CLAIM",
        "Default entry tier\n(create_node_with_provenance)\nIngested logs locked here",
        bg=SLATE_BG, ec=SLATE, tc=SLATE, title_y=0.76, body_y=0.33)
    box(ax, 3.90, 4.65, 2.45, 1.15, "DSL_CONSISTENT",
        "Formal relational schema\n(dsl_expr locked pre-test)\nAwaits external check",
        bg=NAVY_BG, ec=NAVY, tc=NAVY, title_y=0.76, body_y=0.33)
    box(ax, 7.55, 4.65, 2.55, 1.15, "SIM_CONSISTENT",
        "toy_model ceiling only\nNon-llm_only + pycheck:\nDoes NOT reset dry hops",
        bg=GOLD_BG, ec=AMBER, tc=AMBER, title_y=0.76, body_y=0.33)

    # Row 2 (Terminal & Adjudication Tiers): EXTERNALLY_VERIFIED, FALSIFIED, UNDER_APPEAL, CONTESTED
    box(ax, 10.65, 2.45, 2.65, 1.35, "EXTERNALLY_VERIFIED",
        "Non-llm_only + external_ref\n+ EXTERNAL_SCOPES +\nbenchmark_ref (passed=1)",
        bg=SAGE_BG, ec=SAGE, tc=SAGE, lw=1.6, title_y=0.78, body_y=0.34)

    box(ax, 0.45, 2.15, 2.85, 1.45, "FALSIFIED",
        "Refuted negative boundary\nPaired 1:1 with verified pivot\nvia resolved_mistake +\npivoted_to (NEVER deleted)",
        bg=ROSE_BG, ec=RUST, tc=RUST, lw=1.6, title_y=0.81, body_y=0.35)

    box(ax, 4.45, 2.15, 2.45, 1.25, "UNDER_APPEAL",
        "Defeasible reopen target\nreopen_falsified_node()\nRevives branch -> ACTIVE",
        bg=PLUM_BG, ec=PLUM, tc=PLUM, lw=1.4, title_y=0.78, body_y=0.34)

    box(ax, 7.65, 2.15, 2.35, 1.25, "CONTESTED",
        "Unsettled primary conflict\nor secondary appeal tier\n(reopens / direct entry)",
        bg=PLUM_BG, ec=PLUM, tc=PLUM, lw=1.3, title_y=0.78, body_y=0.34)

    # Transitions
    arrow(ax, (2.84, 5.22), (3.86, 5.22), color=NAVY)
    ax.text(3.35, 5.45, "formalize\n(dsl_expr)", ha="center", va="center", fontsize=6.2, color=NAVY)

    arrow(ax, (6.39, 5.22), (7.51, 5.22), color=AMBER)
    ax.text(6.95, 5.45, "toy_model\nverify_node()", ha="center", va="center", fontsize=6.2, color=AMBER)

    # SIM_CONSISTENT / DSL_CONSISTENT -> EXTERNALLY_VERIFIED
    arrow(ax, (10.14, 5.05), (11.75, 3.85), color=SAGE, lw=1.5, rad=-0.16)
    ax.text(11.65, 4.78, "verify_node()\nexternal scope +\nbenchmark_ref", ha="center", va="center", fontsize=6.2, fontweight="bold", color=SAGE)

    # RAW_CLAIM / DSL_CONSISTENT -> FALSIFIED
    arrow(ax, (1.55, 4.61), (1.55, 3.65), color=RUST, lw=1.45)
    ax.text(0.86, 4.12, "breaks /\npassed=0", ha="center", va="center", fontsize=6.2, fontweight="bold", color=RUST)

    # FALSIFIED -> RAW_CLAIM via splits_from (Atomic Split Decomposition)
    arrow(ax, (2.25, 3.65), (2.25, 4.61), color=SLATE, lw=1.3, ls="--")
    ax.text(3.00, 4.12, "splits_from\n(rescued atomic\nsub-claim)", ha="center", va="center", fontsize=6.1, color=SLATE)

    # FALSIFIED -> EXTERNALLY_VERIFIED via pivoted_to + resolved_mistake (lower clean arc!)
    arrow(ax, (1.88, 2.11), (11.98, 2.41), color=RUST, lw=1.35, ls="-.", rad=0.13)
    ax.text(6.85, 1.46, "edges: resolved_mistake + pivoted_to  (from_node != to_node; links refuted node to verified Reframed Solver)",
            ha="center", va="center", fontsize=6.6, fontweight="bold", color=RUST,
            bbox=dict(boxstyle="round,pad=0.22", fc="white", ec=RUST, lw=0.75), zorder=7)

    # FALSIFIED -> UNDER_APPEAL via reopen_falsified_node()
    arrow(ax, (3.34, 2.86), (4.41, 2.86), color=PLUM, lw=1.5)
    ax.text(3.88, 3.25, "challenges_\nfalsification\n(DOI/primary)", ha="center", va="center", fontsize=6.0, fontweight="bold", color=PLUM)

    # UNDER_APPEAL -> CONTESTED via reopens
    arrow(ax, (6.94, 2.86), (7.61, 2.86), color=PLUM, lw=1.4)
    ax.text(7.27, 3.16, "reopens", ha="center", va="center", fontsize=6.2, fontweight="bold", color=PLUM)

    # CONTESTED -> EXTERNALLY_VERIFIED
    arrow(ax, (10.04, 2.86), (10.61, 2.86), color=SAGE, lw=1.45)
    ax.text(10.33, 3.25, "primary\nverified", ha="center", va="center", fontsize=5.9, fontweight="bold", color=SAGE)

    # UNDER_APPEAL -> EXTERNALLY_VERIFIED (direct overturn arc)
    arrow(ax, (5.68, 3.44), (11.15, 3.84), color=SAGE, lw=1.15, ls="--", rad=-0.16)
    ax.text(8.42, 4.18, "reopen_falsified_node(new_tier='EXTERNALLY_VERIFIED')  [strictly non-llm_only + external_ref]",
            ha="center", va="center", fontsize=6.1, color=SAGE, style="italic")

    # Bottom Bar: Anti-Spin Branch Budget (research_branches) + Directed Edge Types
    ax.add_patch(FancyBboxPatch((0.25, 0.28), 13.10, 0.88, boxstyle="round,pad=0.05,rounding_size=0.10",
                                facecolor=CREAM, edgecolor=NAVY, lw=1.0, zorder=2))
    ax.text(6.8, 0.90, "ANTI-SPIN HALTING BUDGET (research_branches) & COMPLETE EDGE VOCABULARY (edges.relation_type)",
            ha="center", va="center", fontsize=7.5, fontweight="bold", color=NAVY, zorder=3)
    ax.text(6.8, 0.52,
            "Branch states: ACTIVE  \u2192  CONVERGED (root EV or FALSIFIED + verified pivoted_to)  |  ACTIVE  \u2192  HALTED_NOVELTY (hops_since_novelty >= max_dry_hops = 3)  |  CONVERGED  \u2192  ACTIVE (only via reopen_falsified_node).\n"
            "All 9 edges.relation_type values: isomorphic_to · supports · breaks · refines · resolved_mistake · pivoted_to · reopens · challenges_falsification · splits_from  (CHECK: from_node != to_node).",
            ha="center", va="center", fontsize=6.3, color=INK, linespacing=1.35, zorder=3)

    out = ASSETS / "diag3_defeasible_state_machine.png"
    fig.savefig(out, dpi=300)
    plt.close(fig)
    print(f"Saved {out}")


def build_diag4_runtime_gauntlet():
    """Diagram 4: Stage 4 Single-Loop Runtime & Kestrel-7 Evaluation Loop."""
    fig, ax = plt.subplots(figsize=(13.6, 6.6))
    ax.set_xlim(0, 13.6)
    ax.set_ylim(0, 6.6)
    ax.axis("off")

    ax.text(6.8, 6.32, "Diagram 4. Stage 4 Stateless Single-Loop Compilation Runtime & Kestrel-7 / Harness Verification Loop",
            ha="center", va="center", fontsize=10.6, fontweight="bold", color=INK)

    # Track A: Single-Loop Compilation Runtime
    ax.add_patch(FancyBboxPatch((0.20, 3.45), 13.20, 2.52, boxstyle="round,pad=0.06,rounding_size=0.14",
                                facecolor=NAVY_BG, edgecolor="#BACBE0", lw=1.0, zorder=0))
    ax.text(0.42, 5.74, "TRACK A: STATELESS SINGLE-LOOP COMPILATION (scripts/single_loop_runner.py — 174\u00d7–235.5\u00d7 Lower Prompt Context)",
            ha="left", va="center", fontsize=7.6, fontweight="bold", color=NAVY)

    a_boxes = [
        (0.38, "1. Queue Fetch", "chapter_slices\nstatus='PENDING'\nMini-batch (10 chunks)\nZero chat history", "white", NAVY, NAVY),
        (2.58, "2. Pre-Tick Hydrate", "hydrate_pre_tick()\n<= 2,200 tok budget\nFTS5 + concept_bridges\n+ [FALSIFIED] guards", "white", NAVY, NAVY),
        (4.78, "3. Step A: Lifter", "LIFTER_STATIC_PREFIX\nStateless LLM JSON\nSKIPPED / attach /\nnew RAW_CLAIM", "white", SLATE, SLATE),
        (6.98, "4. Step B: Scientist", "SCIENTIST_STATIC_PREFIX\nDesigns checks +\nlocal run_physics_check()\n→ pycheck:<sha256>", "white", AMBER, AMBER),
        (9.18, "5. Step C: Falsifier", "FALSIFIER_STATIC_PREFIX\nVerdict + Reframed\nSolver + support_targets\nStrict JSON gate", ROSE_BG, RUST, RUST),
        (11.38, "6. Commit & Delta", "verify_node / link()\ntrg_verif_scope_coupling\ncompile_digest.py\nDelta slice refresh", SAGE_BG, SAGE, SAGE),
    ]
    w_a = 1.88
    for idx, (x0, ttl, body, bg, ec, tc) in enumerate(a_boxes):
        box(ax, x0, 4.02, w_a, 1.48, ttl, body, bg=bg, ec=ec, tc=tc, title_fs=7.2, body_fs=6.0, title_y=0.83, body_y=0.37)
        if idx < len(a_boxes) - 1:
            arrow(ax, (x0 + w_a + 0.04, 4.76), (a_boxes[idx + 1][0] - 0.04, 4.76), color=NAVY, lw=1.3, scale=10)

    # Clean orthogonal feedback return path below all 6 boxes (ZERO overlap!)
    ax.plot([12.32, 12.32, 1.32], [3.98, 3.76, 3.76], color=SAGE, lw=1.25, ls="--", zorder=4)
    arrow(ax, (1.32, 3.76), (1.32, 3.98), color=SAGE, lw=1.25, ls="--", scale=10, z=5)
    ax.text(6.80, 3.59, "Next isolated tick reads updated corpus.db & core_digest.md (zero conversation history carried forward)",
            ha="center", va="center", fontsize=6.4, color=SAGE, fontweight="bold")

    # Track B: Kestrel-7 Gauntlet & 9/9 Test Harness Audit Loop
    ax.add_patch(FancyBboxPatch((0.20, 0.52), 13.20, 2.66, boxstyle="round,pad=0.06,rounding_size=0.14",
                                facecolor=CREAM, edgecolor=GRID, lw=1.0, zorder=0))
    ax.text(0.42, 2.96, "TRACK B: REPRODUCIBLE AUDIT & KESTREL-7 3-ARM GAUNTLET (scripts/benchmark_gauntlet.py + scripts/test_pilot_harness.py)",
            ha="left", va="center", fontsize=7.6, fontweight="bold", color=RUST)

    box(ax, 0.38, 0.80, 2.60, 1.90, "1. Deterministic Suite",
        "20 sequential steps (K7-S01..F20)\n3 blind traps + 1 mass rule:\n• TRAP_1_BOW (+0.15 mm/spacer)\n• TRAP_2_VALVE (−1.8 L/min >55°C)\n• TRAP_3_DERATE (30% mixed)\n• TRAP_4_MASS (<= 420.0 g)",
        bg="white", ec=NAVY, tc=NAVY, title_fs=7.3, body_fs=5.9, title_y=0.87, body_y=0.40)

    # 3 Arms stacked cleanly in middle-left
    box(ax, 3.45, 2.15, 2.85, 0.56, "Arm A: ungated_full_history",
        "Unbounded chat replay (no token cap)", bg=SLATE_BG, ec=SLATE, tc=SLATE, title_fs=6.7, body_fs=5.7, title_y=0.69, body_y=0.25)
    box(ax, 3.45, 1.47, 2.85, 0.56, "Arm B: matched_token_hybrid_rag",
        "<= 2,200 tok · FTS5+TF-IDF (no [FALS])", bg=ROSE_BG, ec=RUST, tc=RUST, title_fs=6.7, body_fs=5.7, title_y=0.69, body_y=0.25)
    box(ax, 3.45, 0.79, 2.85, 0.56, "Arm C: sqlite_gated",
        "<= 2,200 tok · falsified_log + state_register", bg=SAGE_BG, ec=SAGE, tc=SAGE, title_fs=6.7, body_fs=5.7, title_y=0.69, body_y=0.25)

    box(ax, 6.78, 0.80, 3.00, 1.90, "3. Oracle & State Commit",
        "evaluate_ground_truth(step, mass)\nLogs exact payload input_tokens,\nvisible output_tokens, provider\nthoughts_token_count & wall_s;\nwrites falsified_log + edges +\nrunning cumulative_mass_g",
        bg="white", ec=AMBER, tc=AMBER, title_fs=7.3, body_fs=5.9, title_y=0.86, body_y=0.40)

    box(ax, 10.26, 0.80, 2.94, 1.90, "4. CI & Invariant Gate",
        "scripts/test_pilot_harness.py\n9/9 unittest integration checks:\n• Dedup, FTS5 & noise triage\n• Trigger & pycheck: lock (F2.2)\n• Atomic lock (F2.3) & splits\n• Defeasible reopen (F2.1)",
        bg=SAGE_BG, ec=SAGE, tc=SAGE, title_fs=7.3, body_fs=5.9, title_y=0.86, body_y=0.40)

    # Arrows in Track B
    for y_arm in (2.43, 1.75, 1.07):
        arrow(ax, (3.02, 1.75), (3.41, y_arm), color=NAVY, lw=1.1, scale=9)
        arrow(ax, (6.34, y_arm), (6.74, 1.75), color=AMBER, lw=1.1, scale=9)
    arrow(ax, (9.82, 1.75), (10.22, 1.75), color=SAGE, lw=1.4, scale=10)

    ax.text(6.8, 0.18,
            "Replication Entry Points: python3 scripts/benchmark_gauntlet.py --self-test   |   python3 -m unittest scripts/test_pilot_harness.py -v",
            ha="center", va="center", fontsize=7.3, color=MUTED, style="italic")

    out = ASSETS / "diag4_single_loop_gauntlet_runtime.png"
    fig.savefig(out, dpi=300)
    plt.close(fig)
    print(f"Saved {out}")


if __name__ == "__main__":
    build_diag1_end_to_end()
    build_diag2_ingestion_trigger()
    build_diag3_state_machine()
    build_diag4_runtime_gauntlet()
