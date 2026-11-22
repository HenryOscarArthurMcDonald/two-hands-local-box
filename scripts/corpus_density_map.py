#!/usr/bin/env python3
"""Read-only local disciplinary density mapper for data/corpus.db ($0 API cost).

Loads all non-empty chunks via SQLite URI ?mode=ro, runs TF-IDF (1-2 ngrams)
plus NMF (k=30) locally, flags diffuse/low-confidence chunks as Miscellaneous /
Multi-Topic, maps the 30 latent clusters to disciplines in a single pass, and
writes:
  - chapters/corpus_density_map.png (300 dpi horizontal bar chart)
  - chapters/corpus_density_summary.md (discipline & cluster summary tables)
"""

from __future__ import annotations

import argparse
import re
import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Patch
import numpy as np
from sklearn.decomposition import NMF
from sklearn.feature_extraction.text import TfidfVectorizer

WORKSPACE_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = WORKSPACE_ROOT / "data" / "corpus.db"
DEFAULT_OUT_PNG = WORKSPACE_ROOT / "chapters" / "corpus_density_map.png"
DEFAULT_OUT_MD = WORKSPACE_ROOT / "chapters" / "corpus_density_summary.md"

UI_ECHO_PREFIX_RE = re.compile(r"^You said [^\n]*\n")
CANONICAL_BANNER = "Recovered canonical RPC text; original archive preserved."
CRAWLER_NOISE_RE = re.compile(
    r"^(?:Couldn['’]t sign you in\s+This browser or app may not be secure\.|"
    r"Enable JavaScript|404 Not Found|Access Denied)$",
    re.IGNORECASE,
)

# Single-pass discipline classification rules evaluated in order against each
# cluster's top-12 keywords (also matches exact structure of the k=30 NMF pass
# on the 31,060-chunk corpus.db).
DISCIPLINE_RULES: list[tuple[str, tuple[str, ...]]] = [
    (
        "Formal Methods & Lean 4 Verification",
        (
            "projection operator",
            "dialogue seed",
            "lean exported",
            "tactic",
            "seed_hash",
            "rfl",
            "h1_valid",
            "tier_1_formal",
        ),
    ),
    (
        "Physics, Cosmology & Thermodynamics",
        ("physics", "quantum", "universe", "carnot", "landauer", "spacetime"),
    ),
    (
        "Information Theory, Bayes & Graph Math",
        (
            "prior_odds",
            "bayes_factor",
            "shannon",
            "handshaking",
            "simplegraph",
            "comparison tree",
            "asymptotic comparison",
        ),
    ),
    (
        "Pharmacokinetics & Clearance Models",
        ("pharmacokinetic", "t_half", "k_el", "clearance half"),
    ),
    (
        "Mathematics, Number Theory & Quant/Viz",
        ("pi", "digits", "prime", "price", "sequence", "market"),
    ),
    (
        "Ontology & Knowledge-Layer Axioms",
        ("13_the_gold_syntropy", "sorted id", "timestamp 2025"),
    ),
    (
        "Biology, Neurodivergence & Cognitive Psych",
        ("brain", "pda", "adhd", "pain", "cognitive", "social"),
    ),
    (
        "Philosophy, Epistemology & Inquiry",
        ("exposed thoughts", "focusing", "exploring", "inquiry", "passage", "understanding"),
    ),
    (
        "AI / Systems & Software Architecture",
        (
            "python",
            "assertequal",
            "sqlite3",
            "conn execute",
            "valueerror",
            "codex",
            "api",
            "shutil",
            "atomic_json",
            "geminiaccountarchive",
            "archive",
            "related_skill_id",
            "source",
            "tests",
            "evidence",
        ),
    ),
]

MISC_DISCIPLINE = "Miscellaneous / Multi-Topic"

TIER_COLORS = {
    "Major": "#1f5a8a",
    "Minor": "#2a9d8f",
    "Miscellaneous": "#7f8c8d",
}


@dataclass
class ChunkRecord:
    chunk_id: int
    source_type: str
    word_count: int
    char_count: int
    clean_text: str


def clean_for_clustering(content: str) -> str:
    text = UI_ECHO_PREFIX_RE.sub("", content)
    text = text.replace(CANONICAL_BANNER, "")
    return text.strip()


def load_chunks_readonly(db_path: Path) -> tuple[list[ChunkRecord], int]:
    """Load non-empty chunks from SQLite in strict read-only (?mode=ro) mode."""
    if not db_path.exists():
        raise FileNotFoundError(f"Database not found: {db_path}")
    uri = f"file:{db_path.resolve()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=30.0)
    try:
        cols = {
            row[1]
            for row in conn.execute("PRAGMA table_info(chunks)").fetchall()
        }
        has_noise_col = "is_noise" in cols
        query = (
            "SELECT chunk_id, source_type, content "
            "FROM chunks "
            "WHERE content IS NOT NULL AND length(trim(content)) > 0 "
            + ("AND COALESCE(is_noise, 0) = 0 " if has_noise_col else "")
            + "ORDER BY chunk_id ASC"
        )
        records: list[ChunkRecord] = []
        skipped_noise = 0
        for chunk_id, source_type, content in conn.execute(query):
            stripped = content.strip()
            if not stripped or CRAWLER_NOISE_RE.match(stripped):
                skipped_noise += 1
                continue
            cleaned = clean_for_clustering(stripped)
            if not cleaned:
                skipped_noise += 1
                continue
            records.append(
                ChunkRecord(
                    chunk_id=int(chunk_id),
                    source_type=str(source_type),
                    word_count=len(stripped.split()),
                    char_count=len(stripped),
                    clean_text=cleaned,
                )
            )
        return records, skipped_noise
    finally:
        conn.close()


def label_cluster(keywords: list[str]) -> str:
    """Map a cluster's top keywords to its discipline in a single deterministic pass."""
    kw_blob = " | ".join(keywords).lower()
    kw_set = {k.lower() for k in keywords}
    for discipline, triggers in DISCIPLINE_RULES:
        for trig in triggers:
            if " " in trig:
                if trig in kw_blob:
                    return discipline
            elif trig in kw_set or re.search(rf"\b{re.escape(trig)}\b", kw_blob):
                return discipline
    return MISC_DISCIPLINE


def assign_tier(discipline: str, pct_chunks: float) -> str:
    if discipline == MISC_DISCIPLINE:
        return "Miscellaneous"
    return "Major" if pct_chunks >= 8.0 else "Minor"


def run_density_analysis(
    records: list[ChunkRecord],
    n_topics: int = 30,
    min_confidence: float = 0.28,
) -> dict[str, Any]:
    texts = [r.clean_text for r in records]
    vectorizer = TfidfVectorizer(
        ngram_range=(1, 2),
        stop_words="english",
        max_df=0.85,
        min_df=5,
        sublinear_tf=True,
    )
    tfidf_matrix = vectorizer.fit_transform(texts)
    terms = vectorizer.get_feature_names_out()

    nmf = NMF(
        n_components=n_topics,
        random_state=42,
        init="nndsvda",
        max_iter=300,
    )
    W = nmf.fit_transform(tfidf_matrix)
    H = nmf.components_

    row_sums = W.sum(axis=1)
    dominant_topic = W.argmax(axis=1)
    max_weight = W.max(axis=1)
    confidence = np.divide(
        max_weight,
        row_sums,
        out=np.zeros_like(max_weight),
        where=row_sums > 0,
    )

    total_chunks = len(records)
    total_words = sum(r.word_count for r in records)
    total_chars = sum(r.char_count for r in records)

    clusters: list[dict[str, Any]] = []
    discipline_stats: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "chunks": 0,
            "words": 0,
            "chars": 0,
            "cluster_ids": [],
            "keywords": [],
        }
    )

    for k in range(n_topics):
        top_idx = H[k].argsort()[::-1][:12]
        top_kws = [str(terms[i]) for i in top_idx]
        discipline = label_cluster(top_kws)

        mask = (dominant_topic == k) & (row_sums > 0) & (confidence >= min_confidence)
        idxs = np.where(mask)[0]
        c_chunks = int(len(idxs))
        c_words = sum(records[i].word_count for i in idxs)
        c_chars = sum(records[i].char_count for i in idxs)

        clusters.append(
            {
                "cluster_id": f"T{k:02d}",
                "discipline": discipline,
                "chunks": c_chunks,
                "pct_chunks": 100.0 * c_chunks / total_chunks,
                "words": c_words,
                "pct_words": 100.0 * c_words / total_words,
                "chars": c_chars,
                "keywords": top_kws,
            }
        )

        d_entry = discipline_stats[discipline]
        d_entry["chunks"] += c_chunks
        d_entry["words"] += c_words
        d_entry["chars"] += c_chars
        d_entry["cluster_ids"].append(f"T{k:02d}")
        for kw in top_kws[:6]:
            if kw not in d_entry["keywords"]:
                d_entry["keywords"].append(kw)

    # Flag diffuse / zero-weight chunks as Miscellaneous / Multi-Topic
    misc_mask = (row_sums <= 0) | (confidence < min_confidence)
    misc_idxs = np.where(misc_mask)[0]
    misc_chunks = int(len(misc_idxs))
    misc_words = sum(records[i].word_count for i in misc_idxs)
    misc_chars = sum(records[i].char_count for i in misc_idxs)

    misc_entry = discipline_stats[MISC_DISCIPLINE]
    misc_entry["chunks"] += misc_chunks
    misc_entry["words"] += misc_words
    misc_entry["chars"] += misc_chars
    misc_entry["cluster_ids"].append("Diffuse")
    if not misc_entry["keywords"]:
        misc_entry["keywords"] = ["multi-topic", "diffuse", "cross-domain", "conversational"]

    disciplines: list[dict[str, Any]] = []
    for name, info in discipline_stats.items():
        pct_c = 100.0 * info["chunks"] / total_chunks
        pct_w = 100.0 * info["words"] / total_words
        disciplines.append(
            {
                "discipline": name,
                "tier": assign_tier(name, pct_c),
                "chunks": info["chunks"],
                "pct_chunks": pct_c,
                "words": info["words"],
                "pct_words": pct_w,
                "chars": info["chars"],
                "cluster_ids": info["cluster_ids"],
                "keywords": info["keywords"][:12],
            }
        )

    tier_order = {"Major": 0, "Minor": 1, "Miscellaneous": 2}
    disciplines.sort(key=lambda d: (tier_order[d["tier"]], -d["pct_chunks"]))

    return {
        "total_chunks": total_chunks,
        "total_words": total_words,
        "total_chars": total_chars,
        "vocab_size": int(tfidf_matrix.shape[1]),
        "n_topics": n_topics,
        "min_confidence": min_confidence,
        "diffuse_chunks": misc_chunks,
        "diffuse_words": misc_words,
        "diffuse_chars": misc_chars,
        "clusters": clusters,
        "disciplines": disciplines,
    }


def render_chart(result: dict[str, Any], out_png: Path) -> None:
    out_png.parent.mkdir(parents=True, exist_ok=True)
    disciplines = list(reversed(result["disciplines"]))

    labels = [f"{d['discipline']}\n[{d['tier']}]" for d in disciplines]
    pct_chunks = [d["pct_chunks"] for d in disciplines]
    pct_words = [d["pct_words"] for d in disciplines]
    colors = [TIER_COLORS[d["tier"]] for d in disciplines]

    y = np.arange(len(disciplines))
    height = 0.36

    fig, ax = plt.subplots(figsize=(13.5, 8.2), dpi=300)
    fig.patch.set_facecolor("#ffffff")
    ax.set_facecolor("#fafafa")

    bars_chunks = ax.barh(
        y + height / 2,
        pct_chunks,
        height=height,
        color=colors,
        alpha=0.95,
        edgecolor="#222222",
        linewidth=0.5,
    )
    bars_words = ax.barh(
        y - height / 2,
        pct_words,
        height=height,
        color=colors,
        alpha=0.45,
        edgecolor=colors,
        linewidth=0.8,
        hatch="///",
    )

    max_val = max(max(pct_chunks), max(pct_words))
    ax.set_xlim(0, max_val * 1.24)
    ax.set_yticks(y)
    ax.set_yticklabels(labels, fontsize=9.5, fontweight="medium", color="#1a1a1a")
    ax.set_xlabel("Share of Corpus (%)", fontsize=10.5, fontweight="bold", color="#1a1a1a")
    ax.grid(axis="x", linestyle="--", alpha=0.35, color="#999999")
    ax.set_axisbelow(True)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    for bar, d in zip(bars_chunks, disciplines):
        w = bar.get_width()
        ax.text(
            w + 0.35,
            bar.get_y() + bar.get_height() / 2,
            f"{w:.1f}% ({d['chunks']:,} chunks)",
            va="center",
            ha="left",
            fontsize=8.2,
            fontweight="bold",
            color="#111111",
        )

    for bar, d in zip(bars_words, disciplines):
        w = bar.get_width()
        ax.text(
            w + 0.35,
            bar.get_y() + bar.get_height() / 2,
            f"{w:.1f}% ({d['words'] / 1e6:.2f}M words)" if d["words"] >= 100_000 else f"{w:.1f}% ({d['words'] / 1e3:.0f}k words)",
            va="center",
            ha="left",
            fontsize=7.8,
            color="#444444",
        )

    ax.set_title(
        "Corpus Disciplinary Density Map (Chunk Share vs. Word Volume)",
        fontsize=13.5,
        fontweight="bold",
        pad=26,
        loc="left",
        color="#111111",
    )
    fig.text(
        0.125,
        0.915,
        (
            f"N = {result['total_chunks']:,} non-empty chunks  |  "
            f"{result['total_words']:,} words  |  "
            f"TF-IDF (1-2 ngrams, {result['vocab_size']:,} terms) + NMF (k={result['n_topics']}, "
            f"conf >= {result['min_confidence']:.2f})  |  $0 Local"
        ),
        fontsize=8.8,
        color="#555555",
    )

    legend_handles = [
        Patch(facecolor=TIER_COLORS["Major"], edgecolor="#222222", label="Major (>= 8% chunks)"),
        Patch(facecolor=TIER_COLORS["Minor"], edgecolor="#222222", label="Minor (< 8% chunks)"),
        Patch(facecolor=TIER_COLORS["Miscellaneous"], edgecolor="#222222", label="Miscellaneous (Diffuse / Multi-Topic)"),
        Patch(facecolor="#555555", alpha=0.95, edgecolor="#222222", label="Solid Bar: % of Chunks"),
        Patch(facecolor="#555555", alpha=0.45, edgecolor="#555555", hatch="///", label="Hatched Bar: % of Word Volume"),
    ]
    ax.legend(
        handles=legend_handles,
        loc="lower right",
        frameon=True,
        facecolor="#ffffff",
        edgecolor="#cccccc",
        fontsize=8.5,
    )

    plt.tight_layout(rect=[0, 0, 1, 0.90])
    fig.savefig(out_png, dpi=300)
    plt.close(fig)


def write_summary_md(result: dict[str, Any], skipped_noise: int, out_md: Path, out_png: Path) -> None:
    out_md.parent.mkdir(parents=True, exist_ok=True)
    by_name = {d["discipline"]: d for d in result["disciplines"]}

    def sum_stats(names: list[str]) -> tuple[int, float, float]:
        chunks = sum(by_name[n]["chunks"] for n in names if n in by_name)
        pct_c = sum(by_name[n]["pct_chunks"] for n in names if n in by_name)
        pct_w = sum(by_name[n]["pct_words"] for n in names if n in by_name)
        return chunks, pct_c, pct_w

    r1_c, r1_pc, r1_pw = sum_stats(["Physics, Cosmology & Thermodynamics"])
    r2_c, r2_pc, r2_pw = sum_stats([
        "Formal Methods & Lean 4 Verification",
        "Mathematics, Number Theory & Quant/Viz",
        "Information Theory, Bayes & Graph Math",
    ])
    r3_c, r3_pc, r3_pw = sum_stats([
        "AI / Systems & Software Architecture",
        "Philosophy, Epistemology & Inquiry",
    ])
    r4_c, r4_pc, r4_pw = sum_stats([
        "Biology, Neurodivergence & Cognitive Psych",
        "Pharmacokinetics & Clearance Models",
        "Ontology & Knowledge-Layer Axioms",
    ])

    lines: list[str] = [
        "# Corpus Disciplinary Density Summary",
        "",
        f"> **Database:** `data/corpus.db` (`?mode=ro`, read-only)  ",
        f"> **Scope:** `{result['total_chunks']:,}` non-empty chunks (`{skipped_noise}` crawler/boilerplate chunks skipped), `{result['total_words']:,}` words, `{result['total_chars']:,}` characters  ",
        f"> **Method ($0 API):** `TfidfVectorizer(ngram_range=(1, 2), stop_words='english', max_df=0.85, min_df=5, sublinear_tf=True)` (`{result['vocab_size']:,}` features) + `NMF(n_components={result['n_topics']}, random_state=42)`; chunks with `max_topic_weight / sum < {result['min_confidence']:.2f}` flagged as `Miscellaneous / Multi-Topic`  ",
        f"> **Chart:** [{out_png.name}](file://{out_png.resolve().as_posix()})",
        "",
        "---",
        "",
        "## 1. Discipline Density (Merged Single-Pass Labels)",
        "",
        "| Discipline | Tier | Chunks | % Chunks | Words | % Words | Clusters | Representative Keywords |",
        "| :--- | :--- | ---: | ---: | ---: | ---: | :--- | :--- |",
    ]

    for d in result["disciplines"]:
        kw_str = ", ".join(f"`{k}`" for k in d["keywords"][:8])
        cl_str = ", ".join(d["cluster_ids"])
        lines.append(
            f"| **{d['discipline']}** | {d['tier']} | {d['chunks']:,} | {d['pct_chunks']:.2f}% | "
            f"{d['words']:,} | {d['pct_words']:.2f}% | {cl_str} | {kw_str} |"
        )

    lines.extend(
        [
            "",
            "---",
            "",
            "## 2. Raw Latent Clusters (`k = 30` NMF Topics + Diffuse Pool)",
            "",
            "| Cluster | Assigned Discipline | Chunks | % Chunks | Words | Chars | Top 12 Keywords |",
            "| :--- | :--- | ---: | ---: | ---: | ---: | :--- |",
        ]
    )

    for c in sorted(result["clusters"], key=lambda x: -x["chunks"]):
        kw_str = ", ".join(c["keywords"])
        lines.append(
            f"| `{c['cluster_id']}` | {c['discipline']} | {c['chunks']:,} | {c['pct_chunks']:.2f}% | "
            f"{c['words']:,} | {c['chars']:,} | {kw_str} |"
        )

    lines.append(
        f"| `Diffuse` | {MISC_DISCIPLINE} | {result['diffuse_chunks']:,} | "
        f"{100.0 * result['diffuse_chunks'] / result['total_chunks']:.2f}% | "
        f"{result['diffuse_words']:,} | {result['diffuse_chars']:,} | "
        f"chunks with dominant topic share < {result['min_confidence']:.2f} or zero TF-IDF overlap |"
    )

    lines.extend(
        [
            "",
            "---",
            "",
            "## 3. Sizing Implications for Rings 2–4",
            "",
            f"- **Ring 1 Baseline (`Physics, Cosmology & Thermodynamics`):** `{r1_c:,}` chunks (**{r1_pc:.2f}%** of chunks / **{r1_pw:.2f}%** of words), confirming substantial headroom beyond the `800`-chunk `physics_pilot` slice.",
            f"- **Ring 2 Candidate (`Formal Methods & Lean 4` + `Mathematics & Info Theory`):** `{r2_c:,}` chunks (**{r2_pc:.2f}%** of chunks / **{r2_pw:.2f}%** of words) across Lean 4 formal proofs, Number Theory/Quant, Bayes, Shannon, and Graph Math.",
            f"- **Ring 3 Candidate (`AI / Systems & Software Architecture` + `Philosophy, Epistemology & Inquiry`):** `{r3_c:,}` chunks (**{r3_pc:.2f}%** of chunks / **{r3_pw:.2f}%** of words) spanning agentic/software tooling and meta-reasoning traces.",
            f"- **Ring 4 Candidate (`Biology, Neurodivergence & Cognitive Psych` + `Pharmacokinetics` + `Ontology`):** `{r4_c:,}` chunks (**{r4_pc:.2f}%** of chunks / **{r4_pw:.2f}%** of words); note that `T29` also absorbs some personal/everyday life threads alongside neurobiology.",
            "",
        ]
    )

    out_md.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Local read-only corpus disciplinary density mapper.")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH, help="Path to corpus.db")
    parser.add_argument("--out-png", type=Path, default=DEFAULT_OUT_PNG, help="Output chart PNG path")
    parser.add_argument("--out-md", type=Path, default=DEFAULT_OUT_MD, help="Output summary markdown path")
    parser.add_argument("--k", type=int, default=30, help="Number of NMF latent topics (default: 30)")
    parser.add_argument(
        "--min-confidence",
        type=float,
        default=0.28,
        help="Minimum dominant-topic share to avoid Miscellaneous / Multi-Topic flagging",
    )
    args = parser.parse_args()

    records, skipped_noise = load_chunks_readonly(args.db)
    result = run_density_analysis(records, n_topics=args.k, min_confidence=args.min_confidence)
    render_chart(result, args.out_png)
    write_summary_md(result, skipped_noise, args.out_md, args.out_png)

    print(
        f"Mapped {result['total_chunks']:,} chunks ({result['total_words']:,} words, "
        f"{skipped_noise} skipped) into {len(result['disciplines'])} disciplines."
    )
    for d in result["disciplines"]:
        print(
            f"  [{d['tier']:13s}] {d['discipline']:42s} "
            f"{d['chunks']:6,d} ({d['pct_chunks']:5.2f}% chunks | {d['pct_words']:5.2f}% words)"
        )


if __name__ == "__main__":
    main()
