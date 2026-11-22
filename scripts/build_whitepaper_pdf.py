#!/usr/bin/env python3
"""
Build the complete, standalone, publication-grade white paper PDF:
  output/two_hands_decentralized_whitepaper.pdf
and companion SHA-256 checksum file:
  output/two_hands_decentralized_whitepaper.pdf.sha256

Assembles:
  - Cover / Title Page & Colophon Metadata (with live source SHA-256 fingerprints)
  - 2-Pass Table of Contents & List of Plates / Figures
  - Executive Summary (+ Key Metrics Strip + Figure 3 Chiral Parity Architecture)
  - Part I: Uncontexted Reader's Guide (Plate I + chapters/two_hands_reader_guide.md)
  - Part II: The Right Hand — Systems Thesis (Plate II + chapters/decoupled_state_gating_thesis.md + Figs 1 & 2)
  - Part III: The Left Hand — Chiral Humanities Companion (Plate III + chapters/liturgy_chiral_companion.md)
  - Closing Cryptographic Integrity Manifest & Archival Image Attributions
"""

import hashlib
import html
import os
import re
import textwrap
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", "/tmp/mpl_corpus_whitepaper")

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from PIL import Image as PILImage

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.pdfmetrics import registerFontFamily
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    BaseDocTemplate,
    Flowable,
    Frame,
    HRFlowable,
    Image,
    KeepTogether,
    NextPageTemplate,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)
from reportlab.platypus.tableofcontents import TableOfContents

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "output" / "whitepaper_assets"
EQ_DIR = ASSETS / "equations"
EQ_DIR.mkdir(parents=True, exist_ok=True)

OUT_PDF = ROOT / "output" / "two_hands_decentralized_whitepaper.pdf"
OUT_SHA = ROOT / "output" / "two_hands_decentralized_whitepaper.pdf.sha256"

# Museum / University-Press Palette
C_INK = colors.HexColor("#1C2127")
C_BODY = colors.HexColor("#22262A")
C_MUTED = colors.HexColor("#5B636B")
C_RULE = colors.HexColor("#CFC8BC")
C_RULE_DARK = colors.HexColor("#8E8578")
C_NAVY = colors.HexColor("#1E3A5F")
C_SAGE = colors.HexColor("#2E6A5E")
C_RUST = colors.HexColor("#B55239")
C_AMBER = colors.HexColor("#9C6B1D")
C_CREAM = colors.HexColor("#F8F5EE")
C_NAVY_TINT = colors.HexColor("#EEF3F8")
C_SAGE_TINT = colors.HexColor("#EDF4F1")
C_ROW_ALT = colors.HexColor("#FAF8F4")
C_CODE_BG = colors.HexColor("#F2EFEA")

PAGE_W, PAGE_H = letter
M_LEFT = 0.85 * inch
M_RIGHT = 0.85 * inch
M_TOP = 0.90 * inch
M_BOTTOM = 0.82 * inch
USABLE_W = PAGE_W - M_LEFT - M_RIGHT


def register_fonts():
    ttf_dir = ROOT / ".venv" / "lib" / "python3.14" / "site-packages" / "matplotlib" / "mpl-data" / "fonts" / "ttf"
    fonts = {
        "STIX": ttf_dir / "STIXGeneral.ttf",
        "STIX-Bold": ttf_dir / "STIXGeneralBol.ttf",
        "STIX-Italic": ttf_dir / "STIXGeneralItalic.ttf",
        "STIX-BoldItalic": ttf_dir / "STIXGeneralBolIta.ttf",
        "Sans": ttf_dir / "DejaVuSans.ttf",
        "Sans-Bold": ttf_dir / "DejaVuSans-Bold.ttf",
        "Sans-Italic": ttf_dir / "DejaVuSans-Oblique.ttf",
        "Sans-BoldItalic": ttf_dir / "DejaVuSans-BoldOblique.ttf",
        "Mono": ttf_dir / "DejaVuSansMono.ttf",
        "Mono-Bold": ttf_dir / "DejaVuSansMono-Bold.ttf",
    }
    for name, path in fonts.items():
        if not path.exists():
            raise FileNotFoundError(f"Missing required font: {path}")
        pdfmetrics.registerFont(TTFont(name, str(path)))

    registerFontFamily("STIX", normal="STIX", bold="STIX-Bold", italic="STIX-Italic", boldItalic="STIX-BoldItalic")
    registerFontFamily("Sans", normal="Sans", bold="Sans-Bold", italic="Sans-Italic", boldItalic="Sans-BoldItalic")
    registerFontFamily("Mono", normal="Mono", bold="Mono-Bold", italic="Mono", boldItalic="Mono-Bold")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def render_display_equation(latex_str: str, tag: str) -> tuple[Path, float, float]:
    """Render display LaTeX equation at 600 DPI with matplotlib STIX mathtext and return physical pt size."""
    out = EQ_DIR / f"eq_{tag}.png"
    fig = plt.figure(figsize=(8.0, 1.0), dpi=600)
    fig.patch.set_alpha(0.0)
    plt.rcParams["mathtext.fontset"] = "stix"
    plt.rcParams["font.family"] = "serif"
    ax = fig.add_axes([0, 0, 1, 1])
    ax.axis("off")
    ax.text(0.5, 0.5, f"${latex_str}$", ha="center", va="center", fontsize=12.5, color="#1C2127")
    fig.savefig(out, dpi=600, transparent=True, bbox_inches="tight", pad_inches=0.04)
    plt.close(fig)
    with PILImage.open(out) as im:
        iw, ih = im.size
    # Exact physical size at 600 DPI (72 pt / 600 px)
    w_pt = iw * (72.0 / 600.0)
    h_pt = ih * (72.0 / 600.0)
    if w_pt > USABLE_W * 0.90:
        scale = (USABLE_W * 0.90) / w_pt
        w_pt *= scale
        h_pt *= scale
    return out, w_pt, h_pt


# ---------------------------------------------------------------------------
# Inline Markdown + LaTeX -> ReportLab XML converter (100% BMP-safe STIX)
# ---------------------------------------------------------------------------
INLINE_MATH_MAP = {
    r"0 + x = x": "<i>0 + x = x</i>",
    r"1/f": "<i>1/f</i>",
    r"A \in (0, 1)^{n \times n}": "<i>A</i> \u2208 (0, 1)<sup><i>n</i>\u00d7<i>n</i></sup>",
    r"C_{\text{total}}(Q) = C_{\text{compile}} + Q \cdot C_{\text{query}}": "<i>C</i><sub>total</sub>(<i>Q</i>) = <i>C</i><sub>compile</sub> + <i>Q</i> \u00b7 <i>C</i><sub>query</sub>",
    r"F": "<i>F</i>",
    r"F(g \circ f) = F(g) \circ F(f)": "<i>F</i>(<i>g</i> \u2218 <i>f</i>) = <i>F</i>(<i>g</i>) \u2218 <i>F</i>(<i>f</i>)",
    r"A \in (0,1)^{n \times n}": '<i>A</i> <font name="STIX">\u2208</font> (0, 1)<sup><i>n</i><font name="STIX">\u00d7</font><i>n</i></sup>',
    r"H(P) = -p \log_2 p - (1 - p)\log_2(1 - p)": "<i>H</i>(<i>P</i>) = \u2212<i>p</i> log<sub>2</sub> <i>p</i> \u2212 (1 \u2212 <i>p</i>) log<sub>2</sub>(1 \u2212 <i>p</i>)",
    r"H(P) = 0": "<i>H</i>(<i>P</i>) = 0",
    r"H(P) = 0, I(P; X) = 0": "<i>H</i>(<i>P</i>) = 0, <i>I</i>(<i>P</i>; <i>X</i>) = 0",
    r"H(P) \approx 0": "<i>H</i>(<i>P</i>) \u2248 0",
    r"H(\alpha) \to \log_2 n": "<i>H</i>(\u03b1) \u2192 log<sub>2</sub> <i>n</i>",
    r"H(\alpha) \to \log_2 n, I(Q; K) \to 0": "<i>H</i>(\u03b1) \u2192 log<sub>2</sub> <i>n</i>, <i>I</i>(<i>Q</i>; <i>K</i>) \u2192 0",
    r"H(\alpha_i) \to \log_2 n": "<i>H</i>(\u03b1<sub><i>i</i></sub>) \u2192 log<sub>2</sub> <i>n</i>",
    r"I(P; X) = 0": "<i>I</i>(<i>P</i>; <i>X</i>) = 0",
    r"I(P; X) \to 0": "<i>I</i>(<i>P</i>; <i>X</i>) \u2192 0",
    r"I(Q; K) \to 0": "<i>I</i>(<i>Q</i>; <i>K</i>) \u2192 0",
    r"\ne": '<font name="STIX">\u2260</font>',
    r"\neq": '<font name="STIX">\u2260</font>',
    r"L(H) + L(D \mid H)": "<i>L</i>(<i>H</i>) + <i>L</i>(<i>D</i> \u2223 <i>H</i>)",
    r"N = 20": "<i>N</i> = 20",
    r"N \ge 50": '<i>N</i> <font name="STIX">\u2265</font> 50',
    r"N \ge 100": '<i>N</i> <font name="STIX">\u2265</font> 100',
    r"O(N)": "<i>O</i>(<i>N</i>)",
    r"P": "<i>P</i>",
    r"P \land \neg P \vdash Q": "<i>P</i> \u2227 \u00ac<i>P</i> \u22a2 <i>Q</i>",
    r"P: \mathcal{X} \to \{0, 1\}": "<i>P</i>: <i>X</i> \u2192 {0, 1}",
    r"Q^*": "<i>Q</i><sup>*</sup>",
    r"Q^* \approx 1,137": '<i>Q</i><sup>*</sup> <font name="STIX">\u2248</font> 1,137',
    r"Q^*_{\text{tok}}": "<i>Q</i><sup>*</sup><sub>tok</sub>",
    r"Q^*_{\text{tok}} \approx 1,137": '<i>Q</i><sup>*</sup><sub>tok</sub> <font name="STIX">\u2248</font> 1,137',
    r"Q^*_{\text{tok}} \approx 1,428": '<i>Q</i><sup>*</sup><sub>tok</sub> <font name="STIX">\u2248</font> 1,428',
    r"Q^*_{\text{USD}}": "<i>Q</i><sup>*</sup><sub>USD</sub>",
    r"Q^*_{\text{USD}} \approx 2,758": '<i>Q</i><sup>*</sup><sub>USD</sub> <font name="STIX">\u2248</font> 2,758',
    r"Q^*_{\text{USD}} \approx 3,465": '<i>Q</i><sup>*</sup><sub>USD</sub> <font name="STIX">\u2248</font> 3,465',
    r"S \cup \{P\} \vdash \bot": "<i>S</i> \u222a {<i>P</i>} \u22a2 \u22a5",
    r"\alpha_{ij} \to 1/n": "\u03b1<sub><i>ij</i></sub> \u2192 1/<i>n</i>",
    r"\beta = 8/3": "\u03b2 = 8/3",
    r"\lambda_1 \approx 0.906": "\u03bb<sub>1</sub> \u2248 0.906",
    r"\le 2,200": "\u2264 2,200",
    r"\mathbb{R}^d": "\u211d<sup><i>d</i></sup>",
    r"\mathcal{X}": "<i>X</i>",
    r"\rho = 28": "\u03c1 = 28",
    r"\sigma = 10": "\u03c3 = 10",
    r"\text{H–O–H}": "H\u2013O\u2013H",
    r"\text{R–O–H}": "R\u2013O\u2013H",
    r"\|\hat{y} - y_{\text{obs}}\| > \epsilon": "\u2016\u0177 \u2212 <i>y</i><sub>obs</sub>\u2016 &gt; \u03b5",
    r"k_B T \ln 2": "<i>k</i><sub><i>B</i></sub> <i>T</i> ln 2",
    r"p = 0.282": "<i>p</i> = 0.282",
    r"p = 1.00": "<i>p</i> = 1.00",
    r"p = \Pr(P(X) = 1)": "<i>p</i> = Pr(<i>P</i>(<i>X</i>) = 1)",
    r"p \to 1": "<i>p</i> \u2192 1",
    r"y = f_\theta(x)": "<i>y</i> = <i>f</i><sub>\u03b8</sub>(<i>x</i>)",
}


def convert_inline_math(expr: str) -> str:
    expr = expr.strip()
    if expr in INLINE_MATH_MAP:
        return INLINE_MATH_MAP[expr]
    s = html.escape(expr)
    reps = [
        (r"\approx", "\u2248"), (r"\le", "\u2264"), (r"\ge", "\u2265"),
        (r"\to", "\u2192"), (r"\times", "\u00d7"), (r"\cdot", "\u00b7"),
        (r"\lambda", "\u03bb"), (r"\alpha", "\u03b1"), (r"\beta", "\u03b2"),
        (r"\sigma", "\u03c3"), (r"\rho", "\u03c1"), (r"\epsilon", "\u03b5"),
    ]
    for k, v in reps:
        s = s.replace(k, v)
    return f"<i>{s}</i>"


def md_inline_to_rl(text: str, code_size: float = 8.4) -> str:
    """Convert markdown inline formatting (including nested *italic* inside **bold**), links, code spans, escaped $, and $math$."""
    placeholders = {}
    counter = [0]

    def stash(val: str) -> str:
        key = f"\x00PH{counter[0]}\x00"
        counter[0] += 1
        placeholders[key] = val
        return key

    # 1. Inline code spans `...` FIRST (so escapes like \$ inside code stay intact and never nest placeholders)
    def repl_code(m):
        inner = html.escape(m.group(1))
        return stash(f'<font name="Mono" size="{code_size}" color="#1E3A5F">{inner}</font>')

    text = re.sub(r"`([^`]+)`", repl_code, text)

    # 2. Escape literal \$ and \* in prose
    text = text.replace(r"\$", stash("$"))
    text = text.replace(r"\*", stash("*"))

    # 3. Markdown links [label](url)
    def repl_link(m):
        label = m.group(1)
        url = m.group(2)
        label_xml = md_inline_to_rl(label, code_size=code_size)
        if url.startswith("http://") or url.startswith("https://"):
            return stash(f'<link href="{html.escape(url, quote=True)}" color="#1E3A5F">{label_xml}</link>')
        return stash(f'<font color="#1E3A5F">{label_xml}</font>')

    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", repl_link, text)

    # 4. Inline math $...$
    def repl_math(m):
        return stash(convert_inline_math(m.group(1)))

    text = re.sub(r"\$([^$\n]+)\$", repl_math, text)

    # 5. HTML escape remaining raw text
    text = html.escape(text)

    # 6. Bold + Italic ***...***
    text = re.sub(r"\*\*\*((?:(?!\*\*\*).)+?)\*\*\*", r"<b><i>\1</i></b>", text)

    # 7. Bold **...** (supports nested *italic* inside bold!)
    def repl_bold(m):
        inner = m.group(1)
        inner = re.sub(r"(?<!\*)\*([^*\n]+?)\*(?!\*)", r"<i>\1</i>", inner)
        return f"<b>{inner}</b>"

    text = re.sub(r"\*\*((?:(?!\*\*).)+?)\*\*", repl_bold, text)

    # 8. Remaining Italic *...*
    text = re.sub(r"(?<!\*)\*([^*\n]+?)\*(?!\*)", r"<i>\1</i>", text)

    # 8b. Protect arrow & relation glyphs missing in STIXGeneralItalic / STIXGeneralBolIta
    text = text.replace("\u2192", '<font name="STIX">\u2192</font>')
    text = text.replace("\u2194", '<font name="STIX">\u2194</font>')
    text = text.replace("\u2260", '<font name="STIX">\u2260</font>')

    # 9. Restore stashed placeholders in reverse order so nested placeholders always expand cleanly
    for k, v in reversed(list(placeholders.items())):
        text = text.replace(k, v)

    return text


# ---------------------------------------------------------------------------
# Custom Flowables & Document Template
# ---------------------------------------------------------------------------
class SectionBannerTracker(Flowable):
    """Zero-height flowable updating the running header label cleanly BEFORE PageBreak."""
    def __init__(self, header_label: str):
        super().__init__()
        self.header_label = header_label
        self.width = 0
        self.height = 0

    def draw(self):
        pass


class BookmarkAnchor(Flowable):
    """Zero-height flowable emitting a PDF outline bookmark with keepWithNext=True to prevent orphaned headings."""
    def __init__(self, title: str, level: int = 0, key: str = "", in_toc: bool = True):
        super().__init__()
        self.title = title
        self.level = level
        self.key = key or re.sub(r"[^a-zA-Z0-9_]+", "_", title)[:48]
        self.in_toc = in_toc
        self.keepWithNext = True
        self.width = 0
        self.height = 0

    def draw(self):
        self.canv.bookmarkPage(self.key)
        self.canv.addOutlineEntry(self.title, self.key, level=self.level, closed=(self.level >= 1))


class WhitePaperDocTemplate(BaseDocTemplate):
    def __init__(self, filename, **kwargs):
        super().__init__(filename, **kwargs)
        self._running_section = ""

        cover_frame = Frame(M_LEFT, M_BOTTOM, USABLE_W, PAGE_H - M_TOP - M_BOTTOM,
                            leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0, id="cover")
        plate_frame = Frame(M_LEFT, M_BOTTOM, USABLE_W, PAGE_H - M_TOP - M_BOTTOM,
                            leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0, id="plate")
        body_frame = Frame(M_LEFT, M_BOTTOM, USABLE_W, PAGE_H - M_TOP - M_BOTTOM,
                           leftPadding=0, rightPadding=0, topPadding=4, bottomPadding=4, id="body")

        self.addPageTemplates([
            PageTemplate(id="Cover", frames=[cover_frame], onPage=self._draw_cover_bg),
            PageTemplate(id="PartPlate", frames=[plate_frame], onPage=self._draw_plate_bg),
            PageTemplate(id="Body", frames=[body_frame], onPage=self._draw_body_chrome),
        ])

    def handle_documentBegin(self):
        super().handle_documentBegin()
        self._running_section = ""

    def _draw_cover_bg(self, canvas, doc):
        canvas.saveState()
        canvas.setFillColor(C_CREAM)
        canvas.rect(0, PAGE_H - 1.35 * inch, PAGE_W, 1.35 * inch, fill=1, stroke=0)
        canvas.setFillColor(C_NAVY)
        canvas.rect(0, PAGE_H - 0.14 * inch, PAGE_W, 0.14 * inch, fill=1, stroke=0)
        canvas.setStrokeColor(C_RULE)
        canvas.setLineWidth(0.7)
        canvas.line(0, PAGE_H - 1.35 * inch, PAGE_W, PAGE_H - 1.35 * inch)
        canvas.setFillColor(C_SAGE)
        canvas.rect(M_LEFT, 0.58 * inch, USABLE_W * 0.48, 2.0, fill=1, stroke=0)
        canvas.setFillColor(C_NAVY)
        canvas.rect(M_LEFT + USABLE_W * 0.52, 0.58 * inch, USABLE_W * 0.48, 2.0, fill=1, stroke=0)
        canvas.restoreState()

    def _draw_plate_bg(self, canvas, doc):
        canvas.saveState()
        canvas.setStrokeColor(C_RULE)
        canvas.setLineWidth(0.6)
        canvas.line(M_LEFT, PAGE_H - 0.58 * inch, PAGE_W - M_RIGHT, PAGE_H - 0.58 * inch)
        canvas.setFont("Sans", 7.8)
        canvas.setFillColor(C_MUTED)
        canvas.drawCentredString(PAGE_W / 2.0, 0.48 * inch, f"\u2014  {doc.page}  \u2014")
        canvas.restoreState()

    def _draw_body_chrome(self, canvas, doc):
        canvas.saveState()
        sec = self._running_section or "Two Hands in a Local Box"
        y_top = PAGE_H - 0.58 * inch
        canvas.setFont("Sans", 7.5)
        canvas.setFillColor(C_MUTED)
        canvas.drawString(M_LEFT, y_top + 5, "TWO HANDS IN A LOCAL BOX")
        canvas.drawRightString(PAGE_W - M_RIGHT, y_top + 5, sec)
        canvas.setStrokeColor(C_RULE)
        canvas.setLineWidth(0.45)
        canvas.line(M_LEFT, y_top, PAGE_W - M_RIGHT, y_top)

        y_bot = 0.54 * inch
        canvas.line(M_LEFT, y_bot + 11, PAGE_W - M_RIGHT, y_bot + 11)
        canvas.setFont("Sans", 7.4)
        canvas.drawString(M_LEFT, y_bot, "Two Hands in a Local Box \u00b7 Decentralized Open-Source White Paper \u00b7 Local ACID SQLite State Gating")
        canvas.setFont("Sans-Bold", 7.6)
        canvas.setFillColor(C_INK)
        canvas.drawRightString(PAGE_W - M_RIGHT, y_bot, f"Page {doc.page}")
        canvas.restoreState()

    def afterFlowable(self, flowable):
        if isinstance(flowable, SectionBannerTracker):
            self._running_section = flowable.header_label
        elif isinstance(flowable, BookmarkAnchor):
            if flowable.in_toc:
                self.notify("TOCEntry", (flowable.level, flowable.title, self.page, flowable.key))


# ---------------------------------------------------------------------------
# Typography Stylesheet
# ---------------------------------------------------------------------------
def build_styles():
    s = {}
    s["kicker"] = ParagraphStyle(
        "kicker", fontName="Sans-Bold", fontSize=8.0, leading=11,
        textColor=C_NAVY, alignment=TA_LEFT, spaceAfter=6,
    )
    s["cover_title"] = ParagraphStyle(
        "cover_title", fontName="STIX-Bold", fontSize=28.0, leading=33.0,
        textColor=C_INK, alignment=TA_LEFT, spaceBefore=22, spaceAfter=10,
    )
    s["cover_sub"] = ParagraphStyle(
        "cover_sub", fontName="STIX-Italic", fontSize=13.5, leading=19.0,
        textColor=C_MUTED, alignment=TA_LEFT, spaceAfter=18,
    )
    s["plate_kicker"] = ParagraphStyle(
        "plate_kicker", fontName="Sans-Bold", fontSize=8.8, leading=12,
        textColor=C_NAVY, alignment=TA_CENTER, spaceBefore=18, spaceAfter=8,
    )
    s["plate_title"] = ParagraphStyle(
        "plate_title", fontName="STIX-Bold", fontSize=22.0, leading=26.5,
        textColor=C_INK, alignment=TA_CENTER, spaceAfter=8,
    )
    s["plate_sub"] = ParagraphStyle(
        "plate_sub", fontName="STIX-Italic", fontSize=11.5, leading=15.5,
        textColor=C_MUTED, alignment=TA_CENTER, spaceAfter=16,
    )
    s["plate_cap"] = ParagraphStyle(
        "plate_cap", fontName="STIX-Italic", fontSize=8.7, leading=12.5,
        textColor=C_MUTED, alignment=TA_CENTER, leftIndent=18, rightIndent=18, spaceBefore=10,
    )
    s["h1"] = ParagraphStyle(
        "h1", fontName="STIX-Bold", fontSize=16.0, leading=20.5,
        textColor=C_NAVY, spaceBefore=6, spaceAfter=7, keepWithNext=True,
    )
    s["h2"] = ParagraphStyle(
        "h2", fontName="STIX-Bold", fontSize=12.8, leading=16.5,
        textColor=C_NAVY, spaceBefore=13, spaceAfter=5, keepWithNext=True,
    )
    s["h3"] = ParagraphStyle(
        "h3", fontName="Sans-Bold", fontSize=9.8, leading=13.6,
        textColor=C_INK, spaceBefore=10, spaceAfter=4, keepWithNext=True,
    )
    s["body"] = ParagraphStyle(
        "body", fontName="STIX", fontSize=10.0, leading=14.0,
        textColor=C_BODY, alignment=TA_JUSTIFY, spaceAfter=5.8,
    )
    s["body_left"] = ParagraphStyle(
        "body_left", fontName="STIX", fontSize=10.0, leading=14.0,
        textColor=C_BODY, alignment=TA_LEFT, spaceAfter=5.8,
    )
    # Left-aligned bullets prevent stretched whitespace rivers around mono identifiers/paths
    s["bullet"] = ParagraphStyle(
        "bullet", fontName="STIX", fontSize=9.8, leading=13.6,
        textColor=C_BODY, alignment=TA_LEFT, leftIndent=16, firstLineIndent=-10, spaceAfter=4.2,
    )
    s["bullet_compact"] = ParagraphStyle(
        "bullet_compact", fontName="STIX", fontSize=8.9, leading=12.2,
        textColor=C_BODY, alignment=TA_LEFT, leftIndent=14, firstLineIndent=-9, spaceAfter=3.2,
    )
    s["quote"] = ParagraphStyle(
        "quote", fontName="STIX-Italic", fontSize=10.0, leading=14.4,
        textColor=C_INK, alignment=TA_JUSTIFY, leftIndent=12, rightIndent=12, spaceAfter=3,
    )
    s["table_cap"] = ParagraphStyle(
        "table_cap", fontName="STIX-Italic", fontSize=8.8, leading=12.0,
        textColor=C_MUTED, alignment=TA_LEFT, spaceBefore=8, spaceAfter=4, keepWithNext=True,
    )
    s["fig_cap"] = ParagraphStyle(
        "fig_cap", fontName="STIX-Italic", fontSize=8.5, leading=11.8,
        textColor=C_MUTED, alignment=TA_LEFT, spaceBefore=5, spaceAfter=9,
    )
    s["footnote"] = ParagraphStyle(
        "footnote", fontName="STIX-Italic", fontSize=8.1, leading=11.2,
        textColor=C_MUTED, alignment=TA_LEFT, spaceBefore=2, spaceAfter=7,
    )
    s["ref"] = ParagraphStyle(
        "ref", fontName="STIX", fontSize=8.7, leading=12.1,
        textColor=C_BODY, alignment=TA_LEFT, leftIndent=20, firstLineIndent=-20, spaceAfter=3.6,
    )
    s["toc0"] = ParagraphStyle(
        "toc0", fontName="Sans-Bold", fontSize=9.1, leading=13.6,
        textColor=C_NAVY, leftIndent=0, firstLineIndent=0, spaceBefore=5, spaceAfter=1.5,
    )
    s["toc1"] = ParagraphStyle(
        "toc1", fontName="STIX", fontSize=8.9, leading=12.3,
        textColor=C_BODY, leftIndent=14, firstLineIndent=0, spaceBefore=0.5, spaceAfter=0.5,
    )
    s["toc2"] = ParagraphStyle(
        "toc2", fontName="STIX-Italic", fontSize=8.3, leading=11.2,
        textColor=C_MUTED, leftIndent=26, firstLineIndent=0, spaceBefore=0, spaceAfter=0.5,
    )
    s["cell_hdr"] = ParagraphStyle(
        "cell_hdr", fontName="Sans-Bold", fontSize=7.7, leading=10.0,
        textColor=colors.white, alignment=TA_LEFT,
    )
    s["cell_hdr_c"] = ParagraphStyle(
        "cell_hdr_c", fontName="Sans-Bold", fontSize=7.7, leading=10.0,
        textColor=colors.white, alignment=TA_CENTER,
    )
    s["cell"] = ParagraphStyle(
        "cell", fontName="STIX", fontSize=8.3, leading=11.1,
        textColor=C_BODY, alignment=TA_LEFT,
    )
    s["cell_c"] = ParagraphStyle(
        "cell_c", fontName="STIX", fontSize=8.3, leading=11.1,
        textColor=C_BODY, alignment=TA_CENTER,
    )
    s["cell_sm_hdr"] = ParagraphStyle(
        "cell_sm_hdr", fontName="Sans-Bold", fontSize=6.2, leading=8.0,
        textColor=colors.white, alignment=TA_CENTER,
    )
    s["cell_sm"] = ParagraphStyle(
        "cell_sm", fontName="STIX", fontSize=6.6, leading=8.6,
        textColor=C_BODY, alignment=TA_CENTER,
    )
    s["cell_sm_l"] = ParagraphStyle(
        "cell_sm_l", fontName="STIX", fontSize=6.6, leading=8.6,
        textColor=C_BODY, alignment=TA_LEFT,
    )
    s["code_block"] = ParagraphStyle(
        "code_block", fontName="Mono", fontSize=6.3, leading=8.5,
        textColor=C_INK, alignment=TA_LEFT, spaceAfter=0,
    )
    s["code_lang"] = ParagraphStyle(
        "code_lang", fontName="Sans-Bold", fontSize=6.3, leading=8.2,
        textColor=C_NAVY, alignment=TA_LEFT, spaceAfter=2,
    )
    return s


# ---------------------------------------------------------------------------
# Helpers: Framed Images, Callouts, Tables
# ---------------------------------------------------------------------------
def scaled_image(path: Path, max_w: float, max_h: float) -> Image:
    with PILImage.open(path) as im:
        iw, ih = im.size
    ratio = min(max_w / iw, max_h / ih)
    return Image(str(path), width=iw * ratio, height=ih * ratio)


def make_callout(paragraphs, bg=C_CREAM, border_color=C_NAVY):
    t = Table([[paragraphs]], colWidths=[USABLE_W])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), bg),
        ("LINEBEFORE", (0, 0), (0, -1), 3.0, border_color),
        ("BOX", (0, 0), (-1, -1), 0.5, C_RULE),
        ("LEFTPADDING", (0, 0), (-1, -1), 12),
        ("RIGHTPADDING", (0, 0), (-1, -1), 12),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ]))
    return t


def make_code_blocks(code_lines: list[str], lang: str, styles, border_color=C_NAVY) -> list[Flowable]:
    """Render a fenced code block cleanly across page-safe archival boxes (zero LayoutError)."""
    wrapped: list[str] = []
    for raw_ln in code_lines:
        if not raw_ln:
            wrapped.append("")
        elif len(raw_ln) <= 112:
            wrapped.append(raw_ln)
        else:
            lead = len(raw_ln) - len(raw_ln.lstrip(" "))
            sub_ind = " " * min(lead + 6, 22)
            parts = textwrap.wrap(
                raw_ln, width=112, subsequent_indent=sub_ind, expand_tabs=True, tabsize=4,
                replace_whitespace=False, drop_whitespace=False,
                break_long_words=True, break_on_hyphens=False,
            )
            wrapped.extend(parts if parts else [""])
    chunks = [wrapped[k : k + 34] for k in range(0, len(wrapped), 34)] or [[""]]
    out: list[Flowable] = [Spacer(1, 3)]
    lang_lbl = lang.strip().upper() if lang.strip() else "CODE"
    for c_idx, ch_lines in enumerate(chunks):
        body_xml = "<br/>".join(html.escape(ln).replace(" ", "&nbsp;") for ln in ch_lines)
        cell_items = []
        if c_idx == 0 and lang_lbl != "TEXT":
            cell_items.append(Paragraph(f"{html.escape(lang_lbl)} LISTING", styles["code_lang"]))
        cell_items.append(Paragraph(body_xml, styles["code_block"]))
        t = Table([[cell_items]], colWidths=[USABLE_W])
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), C_CODE_BG),
            ("LINEBEFORE", (0, 0), (0, -1), 2.4, border_color),
            ("BOX", (0, 0), (-1, -1), 0.45, C_RULE),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ("TOPPADDING", (0, 0), (-1, -1), 5 if c_idx == 0 else 2.5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5 if c_idx == len(chunks) - 1 else 2.5),
        ]))
        out.append(t)
    out.append(Spacer(1, 5))
    return out


def build_styled_table(headers, rows, alignments, styles, accent_color=C_NAVY):
    ncols = len(headers)
    display_headers = list(headers)

    if ncols == 12:
        # Table 5 (Kestrel-7 12-column gauntlet) — crisp headers & zero 1-letter wraps
        display_headers = [
            "Model", "Mode", "Arm", "Step\nAcc.", "Recur-\nrence",
            "JSON\nValid", "Prompt\nIn", "Vis.\nOut", "Provider\nThinking",
            "Total\n(Incl. Thk.)", "Max\nIn", "Wall\nTime",
        ]
        weights = [1.24, 1.07, 1.56, 0.86, 0.84, 0.56, 0.65, 0.56, 0.82, 0.84, 0.52, 0.68]
        hdr_st_c = styles["cell_sm_hdr"]
        cell_l = styles["cell_sm_l"]
        cell_c = styles["cell_sm"]
        code_sz = 5.7
        pad_x, pad_y = 2.2, 3.2
    elif ncols == 5:
        if "Preserved Morphism" in headers[-1]:
            weights = [0.78, 1.15, 1.15, 1.25, 1.07]
        else:
            weights = [1.65, 1.0, 1.0, 1.0, 1.1]
        hdr_st_c = styles["cell_hdr_c"]
        cell_l = styles["cell"]
        cell_c = styles["cell_c"]
        code_sz = 7.2
        pad_x, pad_y = 5.0, 4.4
    elif ncols == 4:
        if "Substrate" in headers[2]:
            weights = [0.95, 1.35, 1.25, 1.85]
        elif "Parity Inversion" in headers[-1]:
            weights = [0.85, 1.55, 1.55, 1.45]
        else:
            weights = [1.75, 1.35, 1.35, 1.25]
        hdr_st_c = styles["cell_hdr_c"]
        cell_l = styles["cell"]
        cell_c = styles["cell_c"]
        code_sz = 7.4
        pad_x, pad_y = 5.5, 4.6
    elif ncols == 3:
        if headers[0].strip() == "#" and "Test Method" in headers[1]:
            weights = [0.28, 2.58, 2.44]
            hdr_st_c = styles["cell_hdr_c"]
            cell_l = ParagraphStyle("c_t6", parent=styles["cell"], fontSize=7.4, leading=10.0)
            cell_c = ParagraphStyle("c_t6c", parent=styles["cell_c"], fontSize=7.4, leading=10.0)
            code_sz = 6.2
            pad_x, pad_y = 4.2, 3.2
        else:
            weights = [1.0, 2.0, 2.0]
            hdr_st_c = styles["cell_hdr_c"]
            cell_l = styles["cell"]
            cell_c = styles["cell_c"]
            code_sz = 7.6
            pad_x, pad_y = 6.0, 5.0
    else:
        weights = [1.0] * ncols
        hdr_st_c = styles["cell_hdr_c"]
        cell_l = styles["cell"]
        cell_c = styles["cell_c"]
        code_sz = 7.6
        pad_x, pad_y = 6.0, 5.0

    tot_w = sum(weights)
    col_widths = [USABLE_W * (w / tot_w) for w in weights]

    data = []
    hdr_row = []
    for j, h in enumerate(display_headers):
        al = alignments[j] if j < len(alignments) else "L"
        st = hdr_st_c if (al == "C" or ncols == 12) else styles["cell_hdr"]
        hdr_xml = md_inline_to_rl(h, code_size=code_sz).replace("\n", "<br/>").replace('color="#1E3A5F"', 'color="#DCE8F5"')
        hdr_row.append(Paragraph(hdr_xml, st))
    data.append(hdr_row)

    for r in rows:
        row_cells = []
        for j in range(ncols):
            val = r[j] if j < len(r) else ""
            al = alignments[j] if j < len(alignments) else "L"
            if ncols == 12:
                st = cell_l if j < 3 else cell_c
            else:
                st = cell_c if al == "C" else cell_l
            row_cells.append(Paragraph(md_inline_to_rl(val, code_size=code_sz), st))
        data.append(row_cells)

    tbl = Table(data, colWidths=col_widths, repeatRows=1)
    style_cmds = [
        ("BACKGROUND", (0, 0), (-1, 0), accent_color),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 0), (-1, 0), 1.0, accent_color),
        ("LINEBELOW", (0, -1), (-1, -1), 0.9, C_INK),
        ("LINEBELOW", (0, 1), (-1, -2), 0.35, C_RULE),
        ("LEFTPADDING", (0, 0), (-1, -1), pad_x),
        ("RIGHTPADDING", (0, 0), (-1, -1), pad_x),
        ("TOPPADDING", (0, 0), (-1, -1), pad_y),
        ("BOTTOMPADDING", (0, 0), (-1, -1), pad_y),
    ]
    for i in range(1, len(data)):
        if i % 2 == 0:
            style_cmds.append(("BACKGROUND", (0, i), (-1, i), C_ROW_ALT))
    tbl.setStyle(TableStyle(style_cmds))
    return tbl


def make_figure_block(img_path: Path, caption: str, styles, max_h: float = 3.55 * inch):
    img = scaled_image(img_path, USABLE_W - 8, max_h)
    frame_tbl = Table([[img]], colWidths=[USABLE_W])
    frame_tbl.setStyle(TableStyle([
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("BOX", (0, 0), (-1, -1), 0.5, C_RULE),
        ("BACKGROUND", (0, 0), (-1, -1), colors.white),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
    ]))
    cap_p = Paragraph(md_inline_to_rl(caption, code_size=7.6), styles["fig_cap"])
    return KeepTogether([Spacer(1, 5), frame_tbl, cap_p, Spacer(1, 3)])


def make_part_plate(part_num: str, running_label: str, kicker: str, title: str, subtitle: str,
                    img_path: Path, plate_caption: str, styles,
                    accent_color=C_NAVY, bm_key="", toc_title=""):
    """Construct a full, restrained museum-monograph Title Plate page with exact running-header staging."""
    elems = []
    elems.append(SectionBannerTracker(running_label))
    elems.append(NextPageTemplate("PartPlate"))
    elems.append(PageBreak())
    elems.append(BookmarkAnchor(toc_title or f"{part_num}: {title}", level=0, key=bm_key, in_toc=True))

    kicker_st = ParagraphStyle("pk_tmp", parent=styles["plate_kicker"], textColor=accent_color)
    elems.append(Spacer(1, 0.22 * inch))
    elems.append(Paragraph(kicker, kicker_st))
    elems.append(Paragraph(title, styles["plate_title"]))
    elems.append(Paragraph(subtitle, styles["plate_sub"]))
    elems.append(HRFlowable(width="34%", thickness=1.1, color=accent_color, hAlign="CENTER", spaceBefore=2, spaceAfter=18))

    img = scaled_image(img_path, USABLE_W - 0.30 * inch, 5.10 * inch)
    mat_tbl = Table([[img]], colWidths=[img.drawWidth + 14])
    mat_tbl.setStyle(TableStyle([
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("BACKGROUND", (0, 0), (-1, -1), C_CREAM),
        ("BOX", (0, 0), (-1, -1), 0.75, C_RULE_DARK),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ("LEFTPADDING", (0, 0), (-1, -1), 7),
        ("RIGHTPADDING", (0, 0), (-1, -1), 7),
    ]))
    elems.append(mat_tbl)
    elems.append(Paragraph(md_inline_to_rl(plate_caption, code_size=7.6), styles["plate_cap"]))

    elems.append(SectionBannerTracker(running_label))
    elems.append(NextPageTemplate("Body"))
    elems.append(PageBreak())
    return elems


# ---------------------------------------------------------------------------
# Markdown -> ReportLab Flowables Parser (tailored to our 3 chapters)
# ---------------------------------------------------------------------------
def split_md_table_row(line: str) -> list[str]:
    """Split a Markdown table row strictly on unescaped '|' so math norm '\\|' stays intact."""
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|") and not s.endswith(r"\|"):
        s = s[:-1]
    return [c.strip() for c in re.split(r"(?<!\\)\|", s)]


def parse_markdown_chapter(
    md_path: Path,
    styles,
    part_prefix: str,
    accent_color=C_NAVY,
    inject_after_h3=None,
):
    """Parse a markdown chapter cleanly into ReportLab flowables with TOC bookmarks, equations & zero orphaned captions."""
    inject_after_h3 = inject_after_h3 or {}
    lines = md_path.read_text(encoding="utf-8").splitlines()
    flowables = []
    in_references = False
    current_h3 = None
    eq_idx = 0
    pending_table_cap = None
    i = 0
    n = len(lines)

    h2_style = ParagraphStyle(f"h2_{part_prefix}", parent=styles["h2"], textColor=accent_color)

    def maybe_inject_pending(closing_h3):
        if closing_h3 and closing_h3 in inject_after_h3:
            flowables.extend(inject_after_h3[closing_h3])
            inject_after_h3.pop(closing_h3, None)

    while i < n:
        raw = lines[i]
        stripped = raw.strip()

        if not stripped:
            i += 1
            continue

        # Skip top-level # H1 title (rendered on Part Title Plate)
        if stripped.startswith("# ") and not stripped.startswith("## "):
            i += 1
            continue

        # Horizontal rule ---
        if stripped == "---":
            maybe_inject_pending(current_h3)
            current_h3 = None
            flowables.append(Spacer(1, 3))
            flowables.append(HRFlowable(width="100%", thickness=0.5, color=C_RULE, spaceBefore=2, spaceAfter=5))
            i += 1
            continue

        # Section headings ##
        if stripped.startswith("## "):
            maybe_inject_pending(current_h3)
            current_h3 = None
            title = stripped[3:].strip()
            # Frontispiece is rendered on its own standalone page immediately before Executive Summary
            if title.startswith("Frontispiece:"):
                i += 1
                while i < n and not lines[i].strip().startswith("## "):
                    i += 1
                continue
            in_references = title.lower().startswith("references")
            # Give Appendix A (standalone 1-page challenge) and Appendix B (How-To & Diagrams) clean fresh pages
            if title.startswith("Appendix A:") or title.startswith("Appendix B:"):
                flowables.append(PageBreak())
            elif in_references or title.lower().startswith("appendix"):
                flowables.append(Spacer(1, 5))
            bm_key = f"{part_prefix}_h2_{i}"
            toc_label = title.replace("`", "")
            flowables.append(BookmarkAnchor(toc_label, level=1, key=bm_key, in_toc=True))
            flowables.append(Paragraph(md_inline_to_rl(title, code_size=9.5), h2_style))
            i += 1
            continue

        # Fenced code blocks ```lang ... ```
        if stripped.startswith("```"):
            lang = stripped[3:].strip()
            code_lines = []
            i += 1
            while i < n and not lines[i].strip().startswith("```"):
                code_lines.append(lines[i])
                i += 1
            if i < n and lines[i].strip().startswith("```"):
                i += 1
            flowables.extend(make_code_blocks(code_lines, lang, styles, border_color=accent_color))
            continue

        # Subsection headings ###
        if stripped.startswith("### "):
            maybe_inject_pending(current_h3)
            title = stripped[4:].strip()
            current_h3 = title
            bm_key = f"{part_prefix}_h3_{i}"
            flowables.append(BookmarkAnchor(title.replace("`", ""), level=2, key=bm_key, in_toc=False))
            flowables.append(Paragraph(md_inline_to_rl(title, code_size=8.6), styles["h3"]))
            i += 1
            continue

        # Display math block $$...$$
        if stripped.startswith("$$"):
            eq_lines = [stripped]
            while not stripped.endswith("$$") or (len(eq_lines) == 1 and stripped == "$$"):
                i += 1
                if i >= n:
                    break
                stripped = lines[i].strip()
                eq_lines.append(stripped)
            expr = " ".join(eq_lines).strip()
            if expr.startswith("$$"):
                expr = expr[2:]
            if expr.endswith("$$"):
                expr = expr[:-2]
            eq_idx += 1
            eq_png, w_pt, h_pt = render_display_equation(expr.strip(), f"{part_prefix}_{eq_idx}")
            eq_img = Image(str(eq_png), width=w_pt, height=h_pt)
            eq_tbl = Table([[eq_img]], colWidths=[USABLE_W])
            eq_tbl.setStyle(TableStyle([
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]))
            flowables.append(eq_tbl)
            i += 1
            continue

        # Table caption (*Table N. ...*) — hold so it binds directly to its Table with zero intervening Spacer!
        if stripped.startswith("*Table ") and stripped.endswith("*"):
            pending_table_cap = Paragraph(md_inline_to_rl(stripped, code_size=8.0), styles["table_cap"])
            i += 1
            continue

        # Markdown Table (split on UNESCAPED pipes only!)
        if stripped.startswith("|") and i + 1 < n and lines[i + 1].strip().startswith("|") and "---" in lines[i + 1]:
            hdr_cells = split_md_table_row(stripped)
            align_raw = split_md_table_row(lines[i + 1])
            alignments = []
            for a in align_raw:
                if a.startswith(":") and a.endswith(":"):
                    alignments.append("C")
                elif a.endswith(":"):
                    alignments.append("R")
                else:
                    alignments.append("L")
            i += 2
            rows = []
            while i < n and lines[i].strip().startswith("|"):
                rows.append(split_md_table_row(lines[i]))
                i += 1
            tbl = build_styled_table(hdr_cells, rows, alignments, styles, accent_color=accent_color)

            # Check for immediate table footnote (*\*...*)
            tbl_fn = None
            k = i
            while k < n and not lines[k].strip():
                k += 1
            if k < n and lines[k].strip().startswith("*\\*") and lines[k].strip().endswith("*"):
                tbl_fn = Paragraph(md_inline_to_rl(lines[k].strip(), code_size=7.4), styles["footnote"])
                i = k + 1

            # Keep compact tables (<= 11 rows) + caption + footnote cleanly together so Table 5 never splits awkwardly
            block = []
            if pending_table_cap is not None:
                block.append(pending_table_cap)
                pending_table_cap = None
            block.append(tbl)
            if tbl_fn is not None:
                block.append(tbl_fn)
            else:
                block.append(Spacer(1, 6))

            if len(rows) <= 11:
                flowables.append(KeepTogether(block))
            else:
                flowables.extend(block)
            continue

        # Flush stray pending caption if somehow not followed by a table
        if pending_table_cap is not None:
            flowables.append(pending_table_cap)
            pending_table_cap = None

        # Blockquote > ... (supports both classic single-paragraph epigraphs and structured multi-paragraph callout boxes)
        if stripped.startswith("> "):
            q_blocks: list[list[str]] = [[]]
            while i < n and lines[i].strip().startswith(">"):
                inner = lines[i].strip()[1:].strip()
                if not inner:
                    if q_blocks[-1]:
                        q_blocks.append([])
                else:
                    q_blocks[-1].append(inner)
                i += 1
            q_blocks = [b for b in q_blocks if b]

            if len(q_blocks) > 1 or (q_blocks and q_blocks[0][0].startswith("**Contemporary Case Study")):
                callout_elems = []
                hdr_st = ParagraphStyle(
                    "cs_hdr", fontName="Sans-Bold", fontSize=8.8, leading=12.4,
                    textColor=accent_color, alignment=TA_LEFT, spaceAfter=4.0,
                )
                body_st = ParagraphStyle(
                    "cs_body", fontName="STIX", fontSize=9.1, leading=12.9,
                    textColor=C_BODY, alignment=TA_JUSTIFY, spaceAfter=3.6,
                )
                step_st = ParagraphStyle(
                    "cs_step", fontName="STIX", fontSize=9.0, leading=12.7,
                    textColor=C_BODY, alignment=TA_LEFT, leftIndent=13, firstLineIndent=-13, spaceAfter=3.2,
                )
                for b_idx, blk in enumerate(q_blocks):
                    for ln in blk:
                        m_num = re.match(r"^(\d+\.)\s+(.*)$", ln)
                        if b_idx == 0 and ln.startswith("**") and ln.endswith("**") and len(blk) == 1:
                            clean_title = ln[2:-2].strip()
                            callout_elems.append(Paragraph(md_inline_to_rl(clean_title, code_size=8.0), hdr_st))
                        elif m_num:
                            callout_elems.append(
                                Paragraph(f"<b>{m_num.group(1)}</b>&nbsp;{md_inline_to_rl(m_num.group(2).strip(), code_size=7.9)}", step_st)
                            )
                        else:
                            callout_elems.append(Paragraph(md_inline_to_rl(ln, code_size=7.9), body_st))
                bg_col = C_NAVY_TINT if accent_color == C_NAVY else (C_SAGE_TINT if accent_color == C_SAGE else C_CREAM)
                flowables.append(Spacer(1, 4))
                flowables.append(KeepTogether([make_callout(callout_elems, bg=bg_col, border_color=accent_color)]))
                flowables.append(Spacer(1, 7))
            else:
                q_text = " ".join(q_blocks[0]) if q_blocks else ""
                q_p = Paragraph(md_inline_to_rl(q_text, code_size=8.4), styles["quote"])
                flowables.append(Spacer(1, 2))
                flowables.append(make_callout([q_p], bg=C_SAGE_TINT if accent_color == C_SAGE else C_CREAM, border_color=accent_color))
                flowables.append(Spacer(1, 6))
            continue

        # Bullet list (- or * or indented sub-bullet)
        if re.match(r"^(\s*)[-*]\s+", raw):
            m = re.match(r"^(\s*)[-*]\s+(.*)$", raw)
            indent_sp = len(m.group(1))
            content = m.group(2).strip()
            bullet_char = "\u25e6" if indent_sp >= 2 else "\u2022"
            extra_ind = 14 if indent_sp >= 2 else 0
            b_style = ParagraphStyle(
                f"b_{extra_ind}", parent=styles["bullet"],
                leftIndent=16 + extra_ind, firstLineIndent=-10,
            )
            flowables.append(Paragraph(f"{bullet_char}&nbsp;&nbsp;{md_inline_to_rl(content, code_size=8.1)}", b_style))
            i += 1
            continue

        # Numbered list (1. 2. 3.)
        if re.match(r"^\d+\.\s+", stripped):
            m = re.match(r"^(\d+\.)\s+(.*)$", stripped)
            num_lbl = m.group(1)
            item_lines = [m.group(2).strip()]
            i += 1
            eq_inside = None
            while i < n and (lines[i].startswith("   ") or lines[i].startswith("\t")):
                sub = lines[i].strip()
                if sub.startswith("$$") and sub.endswith("$$"):
                    eq_inside = sub[2:-2].strip()
                elif sub:
                    if eq_inside is not None:
                        flowables.append(Paragraph(f"<b>{num_lbl}</b>&nbsp;&nbsp;{md_inline_to_rl(' '.join(item_lines), code_size=8.1)}", styles["bullet"]))
                        eq_idx += 1
                        eq_png, w_pt, h_pt = render_display_equation(eq_inside, f"{part_prefix}_{eq_idx}")
                        eq_img = Image(str(eq_png), width=w_pt, height=h_pt)
                        eq_tbl = Table([[eq_img]], colWidths=[USABLE_W])
                        eq_tbl.setStyle(TableStyle([("ALIGN", (0, 0), (-1, -1), "CENTER"), ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
                        flowables.append(eq_tbl)
                        eq_inside = None
                        item_lines = [sub]
                        num_lbl = ""
                    else:
                        item_lines.append(sub)
                i += 1
            if item_lines:
                prefix = f"<b>{num_lbl}</b>&nbsp;&nbsp;" if num_lbl else ""
                st = styles["bullet"] if num_lbl else ParagraphStyle("b_cont", parent=styles["bullet"], firstLineIndent=0)
                flowables.append(Paragraph(f"{prefix}{md_inline_to_rl(' '.join(item_lines), code_size=8.1)}", st))
            if eq_inside:
                eq_idx += 1
                eq_png, w_pt, h_pt = render_display_equation(eq_inside, f"{part_prefix}_{eq_idx}")
                eq_img = Image(str(eq_png), width=w_pt, height=h_pt)
                eq_tbl = Table([[eq_img]], colWidths=[USABLE_W])
                eq_tbl.setStyle(TableStyle([("ALIGN", (0, 0), (-1, -1), "CENTER"), ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]))
                flowables.append(eq_tbl)
            continue

        # Standalone footnote
        if stripped.startswith("*\\*") and stripped.endswith("*"):
            flowables.append(Paragraph(md_inline_to_rl(stripped, code_size=7.4), styles["footnote"]))
            i += 1
            continue

        # Normal paragraph or Reference entry
        para_lines = [stripped]
        i += 1
        while i < n:
            nxt = lines[i].strip()
            if (not nxt or nxt.startswith("#") or nxt == "---" or nxt.startswith("|")
                    or nxt.startswith(">") or nxt.startswith("$$") or nxt.startswith("```")
                    or (nxt.startswith("*Table ") and nxt.endswith("*"))
                    or re.match(r"^(\s*)[-*]\s+", lines[i]) or re.match(r"^\d+\.\s+", nxt)):
                break
            para_lines.append(nxt)
            i += 1
        full_p = " ".join(para_lines)
        st = styles["ref"] if in_references else styles["body"]
        flowables.append(Paragraph(md_inline_to_rl(full_p, code_size=8.1), st))

    maybe_inject_pending(current_h3)
    return flowables


# ---------------------------------------------------------------------------
# Assemble Complete White Paper Story
# ---------------------------------------------------------------------------
def build_whitepaper():
    register_fonts()
    styles = build_styles()

    p_guide = ROOT / "chapters" / "two_hands_reader_guide.md"
    p_thesis = ROOT / "chapters" / "decoupled_state_gating_thesis.md"
    p_liturgy = ROOT / "chapters" / "liturgy_chiral_companion.md"
    p_gauntlet = ROOT / "data" / "gauntlet_results.json"
    p_bench = ROOT / "data" / "benchmark_results.json"

    plate1 = ASSETS / "plate_part1_workbench.jpg"
    plate2 = ASSETS / "plate_part2_antikythera.jpg"
    plate3 = ASSETS / "plate_part3_hevelius_ophiuchus.jpg"
    fig1 = ASSETS / "fig1_kestrel7_capability_knee.png"
    fig2 = ASSETS / "fig2_amortization_compression.png"
    fig3 = ASSETS / "fig3_chiral_architecture_clasp.png"
    diag1 = ASSETS / "diag1_end_to_end_architecture.png"
    diag2 = ASSETS / "diag2_ingestion_trigger_gating.png"
    diag3 = ASSETS / "diag3_defeasible_state_machine.png"
    diag4 = ASSETS / "diag4_single_loop_gauntlet_runtime.png"

    manifest_items = [
        ("Part I Source (Reader's Guide)", "chapters/two_hands_reader_guide.md", p_guide),
        ("Part II Source (Systems Thesis + App. A–C)", "chapters/decoupled_state_gating_thesis.md", p_thesis),
        ("Part III Source (Chiral Companion)", "chapters/liturgy_chiral_companion.md", p_liturgy),
        ("Live Gauntlet Dataset (Exp. 3)", "data/gauntlet_results.json", p_gauntlet),
        ("Live Retrieval Benchmark (Exp. 1)", "data/benchmark_results.json", p_bench),
        ("Plate I (Workbench Editorial)", "output/whitepaper_assets/plate_part1_workbench.jpg", plate1),
        ("Plate II (Antikythera Fragment A)", "output/whitepaper_assets/plate_part2_antikythera.jpg", plate2),
        ("Plate III (Hevelius Ophiuchus, 1690)", "output/whitepaper_assets/plate_part3_hevelius_ophiuchus.jpg", plate3),
        ("Figure 1 (Chiral Architecture & Clasp)", "output/whitepaper_assets/fig3_chiral_architecture_clasp.png", fig3),
        ("Figure 2 (Amortization & Compression)", "output/whitepaper_assets/fig2_amortization_compression.png", fig2),
        ("Figure 3 (Kestrel-7 Capability Knee)", "output/whitepaper_assets/fig1_kestrel7_capability_knee.png", fig1),
        ("Diagram 1 (End-to-End Architecture)", "output/whitepaper_assets/diag1_end_to_end_architecture.png", diag1),
        ("Diagram 2 (Ingestion & Trigger Lock)", "output/whitepaper_assets/diag2_ingestion_trigger_gating.png", diag2),
        ("Diagram 3 (Defeasible State Machine)", "output/whitepaper_assets/diag3_defeasible_state_machine.png", diag3),
        ("Diagram 4 (Runtime & Gauntlet Loop)", "output/whitepaper_assets/diag4_single_loop_gauntlet_runtime.png", diag4),
    ]
    hashes = {rel: sha256_file(path) for _, rel, path in manifest_items}
    build_date_str = "November 21, 2026"
    build_iso = "2026-11-21"

    story = []

    # =========================================================================
    # 1. COVER / TITLE PAGE & COLOPHON METADATA
    # =========================================================================
    story.append(Spacer(1, 0.08 * inch))
    story.append(Paragraph("OPEN-SOURCE DECENTRALIZED AI ARCHITECTURE  \u00b7  MONOGRAPH WHITE PAPER", styles["kicker"]))
    story.append(Spacer(1, 0.42 * inch))
    story.append(Paragraph("Two Hands in a Local Box", styles["cover_title"]))
    story.append(Paragraph(
        "A Decentralized, Open-Source Alternative to Centralized Cloud Computing: "
        "Local SQLite State Gating, Defeasible Negative Provenance, and the Chiral Humanities Companion",
        styles["cover_sub"],
    ))
    story.append(HRFlowable(width="100%", thickness=1.2, color=C_NAVY, spaceBefore=2, spaceAfter=16))

    cover_blurb = Paragraph(
        "Instead of renting massive centralized cloud compute to brute-force million-token chat histories\u2014paying for "
        "consensus noise, sycophancy, and synthetic drift\u2014this monograph presents a portable, local-first architecture: "
        "own state, adversarial verification, and defeasible negative provenance inside a single ACID SQLite file, "
        "treat the language model itself as a lightweight, swappable front-end, and pair empirical pruning with "
        "integration-first communal stewardship so decentralization does not fracture into atomized silos.",
        ParagraphStyle("c_blurb", parent=styles["body"], fontSize=10.5, leading=15.2, textColor=C_BODY),
    )
    story.append(make_callout([cover_blurb], bg=C_CREAM, border_color=C_NAVY))
    story.append(Spacer(1, 0.20 * inch))

    vol_rows = [
        [
            Paragraph("<b>Frontispiece Manifesto</b>", styles["cell"]),
            Paragraph("<i>Attention Is Half of What You Need</i> \u2014 Why stateless transformers need a broken-ideas bucket.", styles["cell"]),
        ],
        [
            Paragraph("<b>Executive Summary</b>", styles["cell"]),
            Paragraph("Decentralized thesis, benchmark frontier, and master chiral architecture diagram (Figure 1).", styles["cell"]),
        ],
        [
            Paragraph("<b>Part I \u00b7 Uncontexted Bridge</b>", styles["cell"]),
            Paragraph("<i>Two Hands in One Box</i> \u2014 Plain-English guide translating the full stack for non-specialists.", styles["cell"]),
        ],
        [
            Paragraph("<b>Part II \u00b7 The Right Hand</b>", styles["cell"]),
            Paragraph("<i>Decoupled Neuro-Symbolic State Gating</i> \u2014 Formal systems thesis, Schema v3, live benchmarks (Figures 2 &amp; 3), Open Falsification Challenge (Appendix A), and Reproducible System How-To (Appendix B, Diagrams 1\u20134).", styles["cell"]),
        ],
        [
            Paragraph("<b>Part III \u00b7 The Left Hand</b>", styles["cell"]),
            Paragraph("<i>Liturgical Form and Chiral Error Correction</i> \u2014 Integration-first humanities and moral-psychology companion.", styles["cell"]),
        ],
    ]
    vol_tbl = Table(vol_rows, colWidths=[1.75 * inch, USABLE_W - 1.75 * inch])
    vol_tbl.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 0), (-1, -2), 0.35, C_RULE),
        ("LINEABOVE", (0, 0), (-1, 0), 0.7, C_NAVY),
        ("LINEBELOW", (0, -1), (-1, -1), 0.7, C_NAVY),
        ("TOPPADDING", (0, 0), (-1, -1), 4.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4.5),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(vol_tbl)
    story.append(Spacer(1, 0.24 * inch))

    story.append(Paragraph("COLOPHON &amp; TAMPER-EVIDENT SOURCE FINGERPRINTS (SHA-256)",
                           ParagraphStyle("col_hdr", fontName="Sans-Bold", fontSize=7.5, leading=10, textColor=C_MUTED, spaceAfter=5)))
    col_data = [
        [Paragraph("<b>Compilation / Provenance</b>", styles["cell_sm_l"]),
         Paragraph("Open compilation &amp; synthesis of prior public work \u00b7 MIT (code) / CC BY 4.0 (docs) \u00b7 Zenodo DOI &amp; upstream attributions in References / README.md", styles["cell_sm_l"])],
        [Paragraph("<b>Edition &amp; Build Date</b>", styles["cell_sm_l"]),
         Paragraph(f"Standalone Portable Monograph PDF (Rev. 3 \u2014 Frontispiece &amp; Appendices A\u2013B Edition) \u00b7 {build_date_str} ({build_iso}) \u00b7 Embedded STIX / DejaVu Fonts", styles["cell_sm_l"])],
        [Paragraph("<b>Part I Source</b>", styles["cell_sm_l"]),
         Paragraph(f'<font name="Mono" size="6.3">{hashes["chapters/two_hands_reader_guide.md"]}</font>  (two_hands_reader_guide.md)', styles["cell_sm_l"])],
        [Paragraph("<b>Part II Source</b>", styles["cell_sm_l"]),
         Paragraph(f'<font name="Mono" size="6.3">{hashes["chapters/decoupled_state_gating_thesis.md"]}</font>  (decoupled_state_gating_thesis.md)', styles["cell_sm_l"])],
        [Paragraph("<b>Part III Source</b>", styles["cell_sm_l"]),
         Paragraph(f'<font name="Mono" size="6.3">{hashes["chapters/liturgy_chiral_companion.md"]}</font>  (liturgy_chiral_companion.md)', styles["cell_sm_l"])],
        [Paragraph("<b>Live Datasets</b>", styles["cell_sm_l"]),
         Paragraph(f'<font name="Mono" size="6.3">{hashes["data/gauntlet_results.json"][:24]}\u2026</font> (gauntlet_results.json) \u00b7 '
                   f'<font name="Mono" size="6.3">{hashes["data/benchmark_results.json"][:24]}\u2026</font> (benchmark_results.json)', styles["cell_sm_l"])],
        [Paragraph("<b>Container Checksum</b>", styles["cell_sm_l"]),
         Paragraph('Verify digest via <font name="Mono" size="6.3">cd output &amp;&amp; shasum -a 256 -c two_hands_decentralized_whitepaper.pdf.sha256</font>', styles["cell_sm_l"])],
    ]
    col_tbl = Table(col_data, colWidths=[1.30 * inch, USABLE_W - 1.30 * inch])
    col_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), C_ROW_ALT),
        ("BOX", (0, 0), (-1, -1), 0.5, C_RULE),
        ("LINEBELOW", (0, 0), (-1, -2), 0.3, C_RULE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 3.8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3.8),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(col_tbl)

    # =========================================================================
    # 2. TABLE OF CONTENTS (Set running banner BEFORE PageBreak!)
    # =========================================================================
    story.append(SectionBannerTracker("Contents"))
    story.append(NextPageTemplate("Body"))
    story.append(PageBreak())
    story.append(BookmarkAnchor("Contents", level=0, key="toc_page", in_toc=False))
    story.append(Paragraph("Contents", styles["h1"]))
    story.append(HRFlowable(width="100%", thickness=0.8, color=C_NAVY, spaceBefore=2, spaceAfter=8))

    toc = TableOfContents()
    toc.dotsMinLevel = 0
    toc.levelStyles = [styles["toc0"], styles["toc1"], styles["toc2"]]
    story.append(toc)

    story.append(Spacer(1, 0.14 * inch))
    story.append(Paragraph("Plates, Figures &amp; System Architecture Diagrams", styles["h2"]))
    plates_list = [
        ("<b>Figure 1</b>", "Chiral Parity Architecture: Decoupled Neuro-Symbolic State Gating vs. Integration-First Liturgy &amp; The Clasp (Executive Summary)"),
        ("<b>Plate I</b>", "Carpenter's Workbench, Stitched Ledger Notebook, Weathered Galvanized Tin &amp; Mirrored Five-Digit Leather Work Gloves (Part I Title Plate)"),
        ("<b>Plate II</b>", "Antikythera Mechanism, Fragment A, c. 2nd\u20131st c. BCE, National Archaeological Museum of Athens (Part II Title Plate)"),
        ("<b>Figure 2</b>", "Retrieval Compression vs. Latency Trade-Off, Compilation Context Reduction, and Amortization Thresholds <i>Q</i><sup>*</sup><sub>tok</sub> = 1,428 / <i>Q</i><sup>*</sup><sub>USD</sub> = 3,465 (Part II, \u00a75.2)"),
        ("<b>Figure 3</b>", "Kestrel-7 Stateful Contradiction Gauntlet: Three-Regime Capability Knee Across Local &amp; Cloud Tiers (Part II, \u00a75.3)"),
        ("<b>Diagram 1</b>", "End-to-End Decoupled Architecture: Stateless LLM Front-End, Python Gatekeeper &amp; Local ACID SQLite (Appendix B, \u00a7B.1)"),
        ("<b>Diagram 2</b>", "Stage 1 &amp; 2 Ingestion, Atomic Claim Lock &amp; SQLite Trigger Enforcement Matrix (Appendix B, \u00a7B.2)"),
        ("<b>Diagram 3</b>", "Stage 3 Defeasible Negative Provenance State Machine &amp; Anti-Spin Branch Halting (Appendix B, \u00a7B.3)"),
        ("<b>Diagram 4</b>", "Stage 4 Stateless Single-Loop Compilation Runtime &amp; Kestrel-7 / Harness Verification Loop (Appendix B, \u00a7B.4)"),
        ("<b>Plate III</b>", "Johannes Hevelius, <i>Serpens et Serpentarius</i> (Ophiuchus), <i>Firmamentum Sobiescianum</i>, Plate P, Gda\u0144sk, 1690 (Part III Title Plate)"),
    ]
    for lbl, desc in plates_list:
        story.append(Paragraph(f"{lbl} \u2014 {desc}", styles["bullet_compact"]))

    # =========================================================================
    # 2B. FRONTISPIECE MANIFESTO ("ATTENTION IS HALF OF WHAT YOU NEED")
    # =========================================================================
    story.append(SectionBannerTracker("Frontispiece \u00b7 Attention Is Half of What You Need"))
    story.append(PageBreak())
    story.append(BookmarkAnchor("Frontispiece \u2014 Attention Is Half of What You Need", level=0, key="frontispiece", in_toc=True))
    story.append(Spacer(1, 0.28 * inch))
    story.append(Paragraph(
        "FRONTISPIECE MANIFESTO  \u00b7  THE CHIRAL ENANTIOMER",
        ParagraphStyle("fp_kicker", fontName="Sans-Bold", fontSize=8.0, leading=11,
                       textColor=C_MUTED, alignment=TA_LEFT, spaceAfter=6),
    ))
    story.append(Paragraph(
        "Attention Is Half of What You Need",
        ParagraphStyle("fp_title", fontName="STIX-Bold", fontSize=23.5, leading=28.0,
                       textColor=C_NAVY, alignment=TA_LEFT, spaceAfter=7),
    ))
    story.append(Paragraph(
        "<i>Why Stateless Transformers Need a Broken-Ideas Bucket\u2014and Why Softmax Is Not a Filing Cabinet</i>",
        ParagraphStyle("fp_sub", fontName="STIX-Italic", fontSize=12.2, leading=16.5,
                       textColor=C_MUTED, alignment=TA_LEFT, spaceAfter=14),
    ))

    # Two-Handed Chiral Accent Bar (Sage Green + Deep Navy)
    fp_bar = Table([[ "", "" ]], colWidths=[USABLE_W * 0.48, USABLE_W * 0.52], rowHeights=[2.2])
    fp_bar.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, 0), C_SAGE),
        ("BACKGROUND", (1, 0), (1, 0), C_NAVY),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    story.append(fp_bar)
    story.append(Spacer(1, 0.24 * inch))

    fp_body_style = ParagraphStyle(
        "fp_body", parent=styles["body"], fontSize=11.0, leading=17.0,
        textColor=C_BODY, alignment=TA_JUSTIFY, spaceAfter=11,
    )
    fp_p1 = Paragraph(
        "In 2017, Vaswani et al. proved that attention is all you need to build a fluent, parallelizable sequence "
        "model\u2014replacing brittle recurrence with dense, continuous attention matrices "
        '<i>A</i> <font name="STIX">\u2208</font> (0, 1)<sup><i>n</i><font name="STIX">\u00d7</font><i>n</i></sup>. '
        "Unfortunately, the industry spent the next decade trying to make that same ephemeral softmax layer double as "
        "a permanent memory warehouse, a truth-value referee, and a moral conscience. The predictable result is "
        "million-token context bills, polite RLHF sycophancy, \"lost-in-the-middle\" amnesia, and agents that grade "
        "their own homework with 99.89% self-certified verifier theater.",
        fp_body_style,
    )
    fp_p2 = Paragraph(
        "This white paper introduces the chiral enantiomer of <i>Attention Is All You Need</i>: same problem space, "
        "inverted handedness. Where continuous attention thrives on soft, dense association (and dies by uniform "
        'over-smoothing as <i>H</i>(\u03b1) <font name="STIX">\u2192</font> log<sub>2</sub> <i>n</i>), durable '
        "truth-tracking lives on the opposite side of the mirror\u2014in discrete sparsity "
        "(<i>H</i>(<i>P</i>) = 0 if you let everything connect), engine-enforced "
        '<font name="Mono" size="8.8" color="#1E3A5F">BEFORE INSERT</font> triggers, and defeasible '
        '<font name="Mono" size="8.8" color="#1E3A5F">[FALSIFIED]</font> negative provenance that pins dead ends to '
        'the wall alongside an appeal hatch (<font name="Mono" size="8.8" color="#1E3A5F">reopens</font>) so the '
        "ledger never calcifies into dogma. Above the basic comprehension knee, bolting a "
        '<font name="STIX">\u2264</font> 2,200-token local SQLite ledger onto lightweight '
        '<font name="Mono" size="8.8" color="#1E3A5F">flash_lite</font> slashes total payload and thinking tokens by '
        "<b>56.5%</b>, lifts true semantic accuracy from <b>45% to 80%</b> (85% raw), and matches heavyweight "
        '<font name="Mono" size="8.8" color="#1E3A5F">flash</font> <b>6\u00d7 faster</b>\u2014while honestly proving '
        'that an 8 GB <font name="Mono" size="8.8" color="#1E3A5F">llama2:7B</font> checkpoint still can\'t read the '
        "notebook without a bigger brain. <b>Attention gives you the voice; the ledger keeps the receipts. You can't "
        "clap with one hand.</b>",
        ParagraphStyle("fp_body_last", parent=fp_body_style, spaceAfter=0),
    )
    fp_box = Table([[ [fp_p1, fp_p2] ]], colWidths=[USABLE_W])
    fp_box.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), C_CREAM),
        ("LINEBEFORE", (0, 0), (0, -1), 3.2, C_NAVY),
        ("BOX", (0, 0), (-1, -1), 0.55, C_RULE),
        ("LEFTPADDING", (0, 0), (-1, -1), 16),
        ("RIGHTPADDING", (0, 0), (-1, -1), 16),
        ("TOPPADDING", (0, 0), (-1, -1), 16),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 16),
    ]))
    story.append(fp_box)
    story.append(Spacer(1, 0.30 * inch))

    # Minimalist Chiral Mirror Summary Plaque beneath the Manifesto
    plaque_hdr_l = ParagraphStyle("pq_hl", fontName="Sans-Bold", fontSize=7.6, leading=10, textColor=C_NAVY, spaceAfter=4)
    plaque_hdr_r = ParagraphStyle("pq_hr", fontName="Sans-Bold", fontSize=7.6, leading=10, textColor=C_SAGE, spaceAfter=4)
    plaque_txt = ParagraphStyle("pq_tx", fontName="STIX", fontSize=8.7, leading=12.6, textColor=C_BODY)
    plaque_tbl = Table(
        [[
            [
                Paragraph("CONTINUOUS ATTENTION  \u00b7  THE VOICE", plaque_hdr_l),
                Paragraph(
                    'Dense softmax matrix <i>A</i> <font name="STIX">\u2208</font> (0, 1)<sup><i>n</i>\u00d7<i>n</i></sup><br/>'
                    "Soft association &amp; fluent synthesis<br/>"
                    'Failure mode: over-smoothing (<i>H</i>(\u03b1) <font name="STIX">\u2192</font> log<sub>2</sub> <i>n</i>) &amp; sycophancy',
                    plaque_txt,
                ),
            ],
            [
                Paragraph("DISCRETE SQLITE LEDGER  \u00b7  THE RECEIPTS", plaque_hdr_r),
                Paragraph(
                    "Sparse relational state (<i>H</i>(<i>P</i>) &gt; 0) in local ACID SQLite<br/>"
                    '<font name="Mono" size="7.4" color="#1E3A5F">BEFORE INSERT</font> verifier-scope coupling<br/>'
                    'Defeasible <font name="Mono" size="7.4" color="#1E3A5F">[FALSIFIED]</font> <font name="STIX">\u2192</font> <font name="Mono" size="7.4" color="#1E3A5F">reopens</font> appeal hatch',
                    plaque_txt,
                ),
            ],
        ]],
        colWidths=[USABLE_W * 0.49, USABLE_W * 0.51],
    )
    plaque_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, 0), C_NAVY_TINT),
        ("BACKGROUND", (1, 0), (1, 0), C_SAGE_TINT),
        ("BOX", (0, 0), (-1, -1), 0.55, C_RULE),
        ("LINEBEFORE", (1, 0), (1, 0), 0.55, C_RULE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 11),
        ("RIGHTPADDING", (0, 0), (-1, -1), 11),
        ("TOPPADDING", (0, 0), (-1, -1), 9),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
    ]))
    story.append(plaque_tbl)
    story.append(Spacer(1, 0.24 * inch))
    story.append(Paragraph(
        "\u2014 <i>Two Hands in a Local Box</i> (2026)",
        ParagraphStyle("fp_sig", fontName="STIX", fontSize=9.2, leading=13, textColor=C_MUTED, alignment=TA_RIGHT),
    ))

    # =========================================================================
    # 3. EXECUTIVE SUMMARY (+ Metrics Strip + Figure 1)
    # =========================================================================
    story.append(SectionBannerTracker("Executive Summary"))
    story.append(PageBreak())
    story.append(BookmarkAnchor("Executive Summary", level=0, key="exec_summary", in_toc=True))
    story.append(Paragraph("Executive Summary", styles["h1"]))
    story.append(HRFlowable(width="100%", thickness=0.8, color=C_NAVY, spaceBefore=1, spaceAfter=9))

    exec_lead = Paragraph(
        "Centralized cloud AI forces an increasingly untenable trade-off: either rent massive data-center compute to "
        "brute-force million-token chat histories\u2014paying continuously for consensus noise, sycophancy, and synthetic "
        "drift\u2014or run small local models that forget yesterday's fixes and loop. Together, these three companion papers "
        "outline a <b>decentralized, open-source alternative</b>: instead of surrendering persistent memory and verification "
        "state to a centralized cloud vendor, own state, verification gates, and negative provenance locally inside a portable "
        "SQLite ledger, and treat the language model itself as a lightweight, swappable, commodity front-end.",
        ParagraphStyle("ex_lead", parent=styles["body"], fontSize=10.3, leading=14.8),
    )
    story.append(make_callout([exec_lead], bg=C_NAVY_TINT, border_color=C_NAVY))
    story.append(Spacer(1, 9))

    exec_bullets = [
        (
            "Engineering Spine (Right Hand \u2014 Part II):",
            "Moves persistent memory, relational schema constraints, and adversarial verification into a single local "
            "ACID SQLite file (live remediated ledger: <b>1,122 atomic nodes</b>, <b>537</b> DOI/law-verified, <b>0</b> open "
            "audit flags; working hydration packets capped at \u2264 2,200 tokens; <b>\u221255.2%</b> query-time input tokens; "
            "<b>174.0\u00d7\u2013235.5\u00d7</b> lower compilation prompt context per committed node relative to stateful multi-agent "
            "swarm replay). Schema v3 enforces engine-level verifier-type/scope coupling (closing self-certifying \"verifier "
            "theater\") and defeasible <font name=\"Mono\" size=\"8.0\" color=\"#1E3A5F\">FALSIFIED</font> provenance chains equipped with a formal "
            "<font name=\"Mono\" size=\"8.0\" color=\"#1E3A5F\">reopens</font> appeal hatch so refuted claims never ossify into dogma. "
            "On the live 20-step private Kestrel-7 tolerance gauntlet, SQLite gating lifted lightweight "
            "<font name=\"Mono\" size=\"8.0\" color=\"#1E3A5F\">flash_lite</font> from <b>55.0%</b> to <b>85.0%</b> raw "
            "(<b>45.0% \u2192 80.0%</b> true semantic accuracy after auditing a lucky Step 3 guess and Step 13 comparison slip), "
            "cut total payload + output + provider thinking tokens by <b>56.5%</b>, and ran <b>6.0\u00d7 faster</b> than ungated "
            "<font name=\"Mono\" size=\"8.0\" color=\"#1E3A5F\">flash</font> (35.0 s vs. 208.2 s)\u2014while honestly proving that local "
            "<font name=\"Mono\" size=\"8.0\" color=\"#1E3A5F\">llama2:7B</font> on 8 GB RAM sits below the semantic comprehension knee "
            "(<b>100.0%</b> contradiction recurrence despite rescuing JSON syntax validity from 0.0% to 85.0%).",
        ),
        (
            "Cultural &amp; Ethical Twin (Left Hand \u2014 Part III):",
            "Confronts the primary human risk of technical decentralization\u2014fragmentation into atomized, cynical silos\u2014by "
            "contrasting falsification-first engineering against integration-first communal and liturgical forms that share "
            "a mirror four-stage geometry (<i>Substrate</i> \u2192 <i>Binding Commit</i> \u2192 <i>Opening/Fraction</i> \u2192 <i>Assimilation</i>). "
            "Keeping the Stage 3 boundary between empirical falsification and sacramental fraction razor-sharp avoids vacuous "
            "<i>H</i>(<i>P</i>) \u2248 0 collapse, while demonstrating how unobserved-cost stewardship (bounded honestly against "
            "internalized self-signaling) replaces centralized surveillance and how closed-loop infallibility destroys both "
            "science and genuine ethics.",
        ),
        (
            "Uncontexted Bridge (Reader's Guide \u2014 Part I):",
            "Translates the complete engineering and humanities architecture into plain, jargon-free prose "
            "(<i>workbench notebook + broken-ideas bucket + the Clasp</i>) so readers without background in AI engineering, "
            "SQLite, category theory, or comparative religion can inspect, critique, and apply a local-first architecture.",
        ),
        (
            "Current Frontier &amp; Honest Limits:",
            "Decoupled local state gating solves <b>state and verification sovereignty today</b>, cuts total payload + thinking "
            "fuel roughly in half on lightweight reasoning tiers, and outperforms matched-token Hybrid RAG (which tripped even "
            "heavyweight <font name=\"Mono\" size=\"8.0\" color=\"#1E3A5F\">flash</font> from 85.0% to 80.0% by dropping running mass state). "
            "Closing the final gap to zero-cloud, fully offline execution requires sweeping modern <b>1.5B\u201314B</b> open-weight "
            "checkpoints on <b>\u2265 16 GB</b> hardware (Ollama \u2265 0.3) and pairing the SQLite ledger with hybrid "
            "<i>Self-Route</i> escalation above the amortization threshold (<b><i>Q</i><sup>*</sup><sub>tok</sub> \u2248 1,428</b> "
            "raw / <b><i>Q</i><sup>*</sup><sub>USD</sub> \u2248 3,465</b> dollar-weighted queries on the live 1,122-node ledger).",
        ),
    ]
    for head, body in exec_bullets:
        story.append(Paragraph(f"\u2022&nbsp;&nbsp;<b>{head}</b> {body}", styles["bullet"]))

    story.append(Spacer(1, 8))

    # Compact Executive KPI Strip (tuned font size so every KPI stays cleanly on 1 unbroken line!)
    kpi_data = [
        [
            Paragraph("<b>\u221255.2%</b>", ParagraphStyle("k1", fontName="Sans-Bold", fontSize=10.5, leading=13, textColor=C_NAVY, alignment=TA_CENTER)),
            Paragraph("<b>174\u00d7\u2013235.5\u00d7</b>", ParagraphStyle("k2", fontName="Sans-Bold", fontSize=10.2, leading=13, textColor=C_NAVY, alignment=TA_CENTER)),
            Paragraph("<b>45% \u2192 80%</b>", ParagraphStyle("k3", fontName="Sans-Bold", fontSize=10.5, leading=13, textColor=C_SAGE, alignment=TA_CENTER)),
            Paragraph("<b>\u221256.5% / 6\u00d7</b>", ParagraphStyle("k4", fontName="Sans-Bold", fontSize=10.2, leading=13, textColor=C_SAGE, alignment=TA_CENTER)),
            Paragraph("<b>1,428 / 3,465</b>", ParagraphStyle("k5", fontName="Sans-Bold", fontSize=10.0, leading=13, textColor=C_RUST, alignment=TA_CENTER)),
        ],
        [
            Paragraph("Query input tokens<br/>(Exp. 1, N = 20)", styles["cell_sm"]),
            Paragraph("Compilation context<br/>reduction (Exp. 2)", styles["cell_sm"]),
            Paragraph("flash_lite semantic acc.<br/>(55%\u219285% raw, Exp. 3)", styles["cell_sm"]),
            Paragraph("Total fuel incl. thinking<br/>&amp; speed vs. flash", styles["cell_sm"]),
            Paragraph("Q* tok / Q* USD parity<br/>(1,122-node ledger)", styles["cell_sm"]),
        ],
    ]
    kpi_widths = [USABLE_W * w for w in (0.19, 0.21, 0.20, 0.20, 0.20)]
    kpi_tbl = Table(kpi_data, colWidths=kpi_widths)
    kpi_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), C_CREAM),
        ("BOX", (0, 0), (-1, -1), 0.7, C_RULE_DARK),
        ("INNERGRID", (0, 0), (-1, -1), 0.4, C_RULE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, 0), 7),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 2),
        ("TOPPADDING", (0, 1), (-1, 1), 2),
        ("BOTTOMPADDING", (0, 1), (-1, 1), 6),
    ]))
    story.append(kpi_tbl)
    story.append(Spacer(1, 10))

    # Master Architectural Map (Figure 1) cleanly presented right after Executive Summary
    story.append(make_figure_block(
        fig3,
        "**Figure 1 (Master Architecture).** Mirror symmetry between the Right-Handed falsification-first SQLite state ledger "
        "(Schema v3 with engine-enforced verifier-scope coupling and defeasible `reopens` appeal hatch) and the "
        "Left-Handed integration-first liturgical sequence, separated by the Stage 3 non-superimposable parity break and locked "
        "into standing equilibrium via **The Clasp**.",
        styles,
        max_h=4.35 * inch,
    ))

    # =========================================================================
    # 4. PART I — UNCONTEXTED READER'S GUIDE
    # =========================================================================
    story.extend(make_part_plate(
        part_num="Part I",
        running_label="Part I \u00b7 Uncontexted Reader's Guide",
        kicker="PART I  \u00b7  THE UNCONTEXTED BRIDGE",
        title="Two Hands in One Box",
        subtitle="A Plain-English Guide to Both Papers",
        img_path=plate1,
        plate_caption=(
            "**Plate I.** *Workbench, Stitched Ledger, Weathered Tin, and Mirrored Work Gloves.* "
            "Editorial still-life plate prepared for Part I illustrating the three everyday intuitions governing this monograph: "
            "a disciplined local notebook, a dedicated container for broken parts, and two anatomically mirrored five-digit hands "
            "built for opposite jobs yet shaped to clasp."
        ),
        styles=styles,
        accent_color=C_AMBER,
        bm_key="part1_guide",
        toc_title="Part I \u2014 Uncontexted Reader's Guide: Two Hands in One Box",
    ))
    story.extend(parse_markdown_chapter(p_guide, styles, part_prefix="p1", accent_color=C_AMBER))

    # =========================================================================
    # 5. PART II — THE RIGHT HAND (SYSTEMS THESIS)
    # =========================================================================
    story.extend(make_part_plate(
        part_num="Part II",
        running_label="Part II \u00b7 Decoupled Neuro-Symbolic State Gating",
        kicker="PART II  \u00b7  THE RIGHT HAND (SYSTEMS THESIS)",
        title="Decoupled Neuro-Symbolic State Gating",
        subtitle="Sparsity, Defeasible Negative Provenance, and Empirical Capability-Floor Boundaries",
        img_path=plate2,
        plate_caption=(
            "**Plate II.** *Antikythera Mechanism, Fragment A* (c. 2nd\u20131st century BCE; bronze epicyclic gearwork, "
            "National Archaeological Museum of Athens, Inv. X 15087). Photograph by Marsyas, licensed under CC BY 2.5 via Wikimedia Commons. "
            "Grounding deterministic constraint compilation in physical history: classical mechanical gear trains encode durable relational "
            "state outside fallible human recall (strictly bounded to classical $O(N)$ kinematics)."
        ),
        styles=styles,
        accent_color=C_NAVY,
        bm_key="part2_thesis",
        toc_title="Part II \u2014 The Right Hand: Decoupled Neuro-Symbolic State Gating",
    ))

    p2_injections = {
        "5.2 Experiment 2: Stateless Single-Loop Compilation vs. Stateful Multi-Agent Swarm": [
            make_figure_block(
                fig2,
                "**Figure 2.** Empirical retrieval compression vs. latency trade-off (Experiment 1, $N = 20$), log-scale prompt context "
                "reduction per committed node (Experiment 2: `174.0\u00d7\u2013235.5\u00d7` lower context), and single-loop compilation amortization "
                "curve identifying break-even thresholds $Q^*_{\\text{tok}} \\approx 1,428$ raw tokens / $Q^*_{\\text{USD}} \\approx 3,465$ "
                "dollar-weighted queries on the live 1,122-node remediated ledger (1,137 / 2,758 at the earlier 893-node baseline).",
                styles,
                max_h=2.75 * inch,
            ),
        ],
        "5.3 Experiment 3: Live 20-Step Private Stateful Contradiction Gauntlet (Kestrel-7)": [
            make_figure_block(
                fig1,
                "**Figure 3.** Live Kestrel-7 stateful contradiction gauntlet uncovering the three-regime capability knee across "
                "local `llama2:7B` (syntax rescued `0% \u2192 85%`, yet `100%` semantic recurrence), `cloud:flash_lite` "
                "(`55.0% \u2192 85.0%` raw / `45.0% \u2192 80.0%` true semantic accuracy and `\u221256.5%` total payload + thinking fuel), and "
                "`cloud:flash` (preserving `85.0%` ceiling at `\u221246.7%` total fuel while matched-token Hybrid RAG regresses to `80.0%`).",
                styles,
                max_h=2.85 * inch,
            ),
        ],
        "B.1 Minimal Directory Layout & Zero-Cloud Dependencies": [
            make_figure_block(
                diag1,
                "**Diagram 1.** End-to-end decoupled architecture separating the swappable stateless LLM front-end (`<= 2,200`-token working "
                "packets, JSON-only output, zero direct DB writes) from the deterministic Python gatekeeper (`scripts/db_utils.py`, "
                "`scripts/compile_digest.py`), local ACID SQLite ledger (`data/corpus.db`), and external primary/sandbox verification oracles.",
                styles,
                max_h=2.98 * inch,
            ),
        ],
        "B.2 Core SQLite DDL & Anti-Theater Trigger (`schema/schema.sql`)": [
            make_figure_block(
                diag2,
                "**Diagram 2.** Stage 1 & 2 ingestion pipeline, mandatory `node_provenance` anchoring, single-claim atomicity lock "
                "(`validate_atomic_claim()`), and exact allowed vs. `RAISE(ABORT)` blocked `(verifier_type \u00d7 verification_scope \u00d7 external_ref)` "
                "coupling matrix enforced inside SQLite by `trg_verif_scope_coupling`.",
                styles,
                max_h=3.35 * inch,
            ),
        ],
        "B.3 Atomic Gating, Packet Budgeting (`<= 2,200` Tokens) & Defeasible Appeal Workflow": [
            make_figure_block(
                diag3,
                "**Diagram 3.** Complete Stage 3 defeasible negative provenance state machine covering all 7 `nodes.epistemic_tier` states, "
                "all 9 directed `edges.relation_type` transitions (including `splits_from`, `pivoted_to`, `challenges_falsification`, and "
                "`reopens`), and the `research_branches` anti-spin halting budget (`max_dry_hops = 3`).",
                styles,
                max_h=3.35 * inch,
            ),
        ],
        "B.4 Step-by-Step Build, Single-Loop Runtime, Kestrel-7 Gauntlet & 11/11 Test Suite": [
            make_figure_block(
                diag4,
                "**Diagram 4.** Stage 4 runtime architecture contrasting the isolated stateless Single-Loop compilation cycle "
                "(`scripts/single_loop_runner.py`, Track A) with the 20-step 3-arm Kestrel-7 gauntlet (`scripts/benchmark_gauntlet.py`) "
                "and 11-test CI invariant suite (`scripts/test_pilot_harness.py`, Track B).",
                styles,
                max_h=3.30 * inch,
            ),
        ],
    }
    story.extend(parse_markdown_chapter(
        p_thesis, styles, part_prefix="p2", accent_color=C_NAVY, inject_after_h3=p2_injections
    ))

    # =========================================================================
    # 6. PART III — THE LEFT HAND (CHIRAL HUMANITIES COMPANION)
    # =========================================================================
    story.extend(make_part_plate(
        part_num="Part III",
        running_label="Part III \u00b7 Liturgical Form and Chiral Error Correction",
        kicker="PART III  \u00b7  THE LEFT HAND (CHIRAL HUMANITIES COMPANION)",
        title="Liturgical Form and Chiral Error Correction",
        subtitle="An Integration-First Companion to Decoupled State Gating",
        img_path=plate3,
        plate_caption=(
            "**Plate III.** Johannes Hevelius, *Serpens et Serpentarius* (Ophiuchus, the Serpent-Bearer), Plate P from "
            "*Firmamentum Sobiescianum, sive Uranographia* (Gda\u0144sk, 1690; copperplate star-atlas engraving, Public Domain via "
            "Wikimedia Commons). Depicts Ophiuchus (identified in classical antiquity with Asclepius) positioned between Scorpius, "
            "Sagittarius, Libra, and *Scutum Sobiescianum*\u2014the exact celestial diagram synthesized by second-century Peratic "
            "interpreters documented in Hippolytus of Rome's *Refutation of All Heresies* (Books IV\u2013V)."
        ),
        styles=styles,
        accent_color=C_SAGE,
        bm_key="part3_liturgy",
        toc_title="Part III \u2014 The Left Hand: Liturgical Form and Chiral Error Correction",
    ))
    story.extend(parse_markdown_chapter(p_liturgy, styles, part_prefix="p3", accent_color=C_SAGE))

    # =========================================================================
    # 6B. MAINTAINER'S REVIEW PRIOR TO PUBLICATION (4-Document 15-Anchor Synthesis)
    # =========================================================================
    story.append(SectionBannerTracker("Maintainer's Review Prior to Publication"))
    story.append(PageBreak())
    story.append(BookmarkAnchor("Maintainer's Review Prior to Publication", level=0, key="maintainers_review", in_toc=True))
    story.append(Paragraph("Maintainer's Review Prior to Publication", styles["h1"]))
    story.append(HRFlowable(width="100%", thickness=0.8, color=C_NAVY, spaceBefore=1, spaceAfter=7))

    rev_body = ParagraphStyle("rev_body", parent=styles["body"], fontSize=9.4, leading=13.2, spaceAfter=5.0)
    rev_bul = ParagraphStyle("rev_bul", parent=styles["bullet"], fontSize=9.1, leading=12.7, spaceAfter=3.6)
    rev_h2 = ParagraphStyle("rev_h2", parent=styles["h2"], fontSize=11.0, leading=14.4, textColor=C_NAVY, spaceBefore=7, spaceAfter=3.5)
    rev_quote = ParagraphStyle("rev_quote", parent=styles["quote"], fontSize=9.1, leading=12.9, leftIndent=6, rightIndent=6, spaceAfter=0)

    story.append(Paragraph(
        "Before releasing this open-source suite\u2014<b>Volume I</b> (<i>Two Hands in a Local Box</i>), "
        "<b>Volume II</b> (<i>The Age of Overkill and the Grounded Wire</i>), the dual-voice builder's manual "
        "<b><i>Failures, Parables &amp; Crash Reports</i></b> (nine verified engineering post-mortems paired with plain-English "
        "parables), and the gated archival record <b><i>The Overkill Crucible: Extended Archival History (2025\u20132026)</i></b>\u2014the "
        "following pre-publication review distills the four volumes through fifteen primary textual anchors governing "
        "their formal boundaries, privacy posture, material transformation, and self-audit record.",
        rev_body,
    ))

    # Group I: Volume I Chiral & Civic Boundaries (Anchors 1–2)
    story.append(Paragraph("I. Formal Chirality &amp; Public-Square Parity (Volume I)", rev_h2))
    story.append(Paragraph(
        "\u2022&nbsp;&nbsp;<b>1. Non-Falsifiable Contrast (<i>Two Hands</i>, Part II \u00a74.2):</b> "
        "Strict adherence to functoriality establishes that <i>\u201cliturgy is a contrasting foil rather than a third isomorphic "
        "instance.\u201d</i> Keeping Stage 3 truth-value breakability distinct from liturgical fraction prevents the framework from "
        "collapsing into a vacuous <i>H</i>(<i>P</i>) \u2248 0 universal template.",
        rev_bul,
    ))
    story.append(Paragraph(
        "\u2022&nbsp;&nbsp;<b>2. Performative Flooding &amp; the Civic Parity Trap (<i>Two Hands</i>, Part III \u00a75.1):</b> "
        "<i>\u201cWhen performative gestures flood a public square, citizens can no longer distinguish genuine solidarity from status "
        "extraction.\u201d</i> The same parity trap governs polarized parliamentary and civic debates\u2014for example, recurring "
        "rhetorical deadlocks over humanitarian policy and domestic scarcity. When universal humanitarian appeals are experienced "
        "by economically strained communities as costless elite signaling decoupled from local stewardship, populist counter-framing "
        "weaponizes that perceived hypocrisy, locking both factions into a symmetrical, mutually reinforcing loop in which each side "
        "requires the other as a moral foil while real material problems go unaddressed.",
        rev_bul,
    ))

    # Group II: Archival Origin & Ambient Privacy Risk (Anchors 3–4)
    story.append(Paragraph("II. Speculative Sprawl, Failures &amp; Ambient Privacy Risk (Volume II, Failures &amp; Extended History)", rev_h2))
    story.append(Paragraph(
        "\u2022&nbsp;&nbsp;<b>3. Sycophancy-Amplified Cloud Sprawl (Volume II, Ch. 1 \u00a71.2):</b> "
        "Without a durable external state store, early consumer-cloud dialogue escalated into "
        "<i>\u201cunbounded speculative sprawl inside colossal, sycophancy-amplified threads\u201d</i>\u2014the failure mode whose "
        "operational post-mortems (including 5,801 DOM-virtualized empty turn stubs, 189.57 GB disk bloat, and 31.45M-token swarms) "
        "are cataloged in plain English inside <i>Failures, Parables &amp; Crash Reports</i>.",
        rev_bul,
    ))
    story.append(Paragraph(
        "\u2022&nbsp;&nbsp;<b>4. Accidental Mic Captures &amp; Reconstructive Privacy Exposure (<i>The Overkill Crucible</i>, Era II \u00a7S2.5 &amp; Chron 089):</b> "
        "Inspecting the full raw archive surfaced an easily verifiable privacy risk: consumer voice assistants routinely log "
        "<i>\u201clistening to conversations through accidental mic activations\u201d</i>\u2014ranging from stray ten-word household "
        "snippets and brief spoken remarks in S2.5 to Chron 089's ambient afternoon parenting voice capture reminding a toddler to "
        "play in the shade. Scraping and reconstructing multi-month chat histories demonstrates how effortlessly seemingly mundane "
        "transcripts can reconstruct intimate parts of a person's private life, which is precisely why the raw verbatim archive and "
        "extended archival monograph remain strictly gated while the open-source SQLite kernel ships cleanly.",
        rev_bul,
    ))

    # Group III: From Primitive Accumulation to Audited Ledger (Anchors 5–9)
    story.append(Paragraph("III. Material Constraint, Provenance &amp; the Industrial Crucible (Extended History, Eras III\u2013IV)", rev_h2))
    story.append(Paragraph(
        "\u2022&nbsp;&nbsp;<b>5. Deterministic Ordering (<i>The Overkill Crucible</i>, Era III \u00a7S3.2):</b> "
        "<b>\u201cProvenance Before Inference\u201d</b>\u2014requiring message IDs, content hashes, deduplication, and replayable "
        "evidence traceability before spending another model call.",
        rev_bul,
    ))
    story.append(Paragraph(
        "\u2022&nbsp;&nbsp;<b>6. Auditing Recurring Speculation (<i>The Overkill Crucible</i>, Era IV \u00a7S4.1):</b> "
        "Speculative leaps did not vanish automatically in Era IV\u2014re-pasting the <i>\u201centropy chain-reaction\u201d</i> "
        "premise still surfaced in late threads\u2014yet external auditing now caught the overreach cleanly, falsifying overclaiming "
        "nodes while preserving bounded physical baselines.",
        rev_bul,
    ))
    story.append(Paragraph(
        "\u2022&nbsp;&nbsp;<b>7. The Institutional Turn (<i>The Overkill Crucible</i>, Era IV \u00a7S4.1):</b> "
        "<i>\u201cWhat changed across the long arc from S1.1's stateless browser tab to November 20's audited relational ledger was "
        "institutional: by pairing OVERKILL CAS storage with an explicit falsification sieve, Henry finally forged an external "
        "memory where claims no longer survived through chatbot flattery or context amnesia, but only by surviving the test.\u201d</i>",
        rev_bul,
    ))
    story.append(Paragraph(
        "\u2022&nbsp;&nbsp;<b>8. Beyond Primitive Accumulation (<i>The Overkill Crucible</i>, Era IV \u00a7S4.2):</b> "
        "<i>\u201cYet archiving a multi-million-word trail was only primitive accumulation. Converting raw transcripts into a "
        "falsifiable scientific ledger required an industrial crucible built on local SQLite, Python harnesses, and adversarial "
        "verification.\u201d</i>",
        rev_bul,
    ))
    story.append(Paragraph(
        "\u2022&nbsp;&nbsp;<b>9. Empirical Legibility at $0 API Cost (<i>The Overkill Crucible</i>, Era IV \u00a7S4.2):</b> "
        "<i>\u201cPaired with a $0-API TF-IDF (121,708 features) and NMF (k=30) topic census recorded in "
        "chapters/corpus_density_summary.md, the corpus finally became legible as an empirical distribution rather than subjective "
        "memory.\u201d</i>",
        rev_bul,
    ))

    # Group IV: Necessity, Chirality & Final Verdict (Anchors 10–13)
    story.append(Paragraph("IV. Necessity, Defeasible Chirality &amp; Closing Verdict (Extended History, Ch. 5)", rev_h2))
    story.append(Paragraph(
        "\u2022&nbsp;&nbsp;<b>10. Necessity as the Mother of Invention (<i>The Overkill Crucible</i>, Ch. 5):</b> "
        "<i>\u201cWhat connects Era I's browser chats to Era IV's local workstation is not prescience, but conceptual mutation under "
        "relentless material constraint\u201d</i>\u2014an empirical restatement of the adage that <i>\u201cNecessity is the mother of "
        "all invention.\u201d</i>",
        rev_bul,
    ))
    story.append(Paragraph(
        "\u2022&nbsp;&nbsp;<b>11. From Stalled Prose Rules to Defeasible Chirality (<i>The Overkill Crucible</i>, Ch. 5 \u00a75.1):</b> "
        "Early anti-sycophancy skepticism <i>\u201c...which repeatedly stalled inside stateless browser tabs because prose rules "
        "could not restrain chatbot flattery.\u201d</i> In Eras III\u2013IV, skepticism moved into auditable graph transitions, "
        "converting refuted hypotheses into explicit <font name=\"Mono\" size=\"7.8\" color=\"#1E3A5F\">FALSIFIED</font> "
        "<font name=\"STIX\">\u2192</font> <font name=\"Mono\" size=\"7.8\" color=\"#1E3A5F\">pivoted_to</font> adversarial "
        "pipelines rather than vanished scrollback. On November 19, <font name=\"Mono\" size=\"7.8\" color=\"#1E3A5F\">elenchus.txt</font> "
        "and Audit F4.1 broke the final syncretic temptation: dismantling na\u00efve unified science-liturgy functors\u2014most sharply "
        "#518 (<i>H</i>(<i>P</i>) = 0)\u2014that smuggled metaphysical totalization through mathematical symbols. Refusing both "
        "sloppy syncretism and positivist erasure, Henry instituted non-superimposable \u201cchirality\u201d (incorporating five "
        "patristic fixes across Rev. 2/3 PDFs) coupled with a defeasible <font name=\"Mono\" size=\"7.8\" color=\"#1E3A5F\">reopens</font> "
        "appeal hatch that replaces permanent dogma with auditable revision, explicitly honoring hostile-redline boundary R22.",
        rev_bul,
    ))
    story.append(Paragraph(
        "\u2022&nbsp;&nbsp;<b>12. The Saving Reflex (<i>The Overkill Crucible</i>, Ch. 5 \u00a75.3):</b> "
        "Across every era, <i>\u201c...the archive's saving reflex was never infallibility, but relentless "
        "self-cross-examination.\u201d</i>",
        rev_bul,
    ))
    story.append(Spacer(1, 3))
    story.append(make_callout([
        Paragraph(
            "<b>13. Closing Forensic Verdict (<i>The Overkill Crucible</i>, Ch. 5 \u00a75.3):</b> "
            "\u201cSecond, cynical dismissal collapses just as thoroughly. Between "
            "<font name=\"Mono\" size=\"7.6\" color=\"#1E3A5F\">archive.db</font>'s 39,093-node, 22,246-edge, 120,215-incidence "
            "fossil hypergraph (23 bridges) and <font name=\"Mono\" size=\"7.6\" color=\"#1E3A5F\">corpus.db</font>'s 0/539 open "
            "audit flags stands a rare, verifiable act of historical self-correction. When the disk hit 189.57 GB, when Wave 1 "
            "burned 31.45 million tokens, and when his own audit convicted 99.89% of his verifications as \u201cverifier "
            "theater\u201d, Henry neither buried the wreckage nor retreated into myth. He left the unfinished borders plain on the "
            "ledger\u2014382 falsified nodes, 149 pending Ring 4A chunks, 28 contested claims, 5 open redline boundaries, and "
            "8 GB consumer-silicon limits\u2014and forged a compact local workshop that remembers what the cloud forgets. Human "
            "beings build their own epistemic instruments, though never under circumstances of their choosing: this archive endures "
            "not because its author foresaw the end from the beginning, but because he let material failure teach him what to burn "
            "and what to wire to the ground.\u201d",
            rev_quote,
        ),
    ], bg=C_CREAM, border_color=C_NAVY))

    # Group V: Archival Ledger Witnesses (Anchors 14–15)
    story.append(Paragraph("V. Archival Ledger Witnesses (Extended History, Appendix A)", rev_h2))
    story.append(Paragraph(
        "\u2022&nbsp;&nbsp;<b>14. Prototype Sycophancy Breakdown (<i>The Overkill Crucible</i>, Chron 058):</b> "
        "<i>\u201cHeavily virtualized megathread (9/296 turns, 6,274 words) mutating from AI abduction into sycophantic grand-unified "
        "flattery; later verified #564/#430 and falsified #393/#983.\u201d</i>",
        rev_bul,
    ))
    story.append(Paragraph(
        "\u2022&nbsp;&nbsp;<b>15. Poetic Compression Benchmark (<i>The Overkill Crucible</i>, Chron 079):</b> "
        "<i>\u201cSingle-turn reflection likening poetic prose generation to high-dimensional differential calculus, answered by "
        "442 AI words framing poetry as high-density information compression.\u201d</i>",
        rev_bul,
    ))

    # =========================================================================
    # 7. CLOSING CRYPTOGRAPHIC INTEGRITY MANIFEST & ARCHIVAL ATTRIBUTIONS (1 clean page)
    # =========================================================================
    story.append(SectionBannerTracker("Cryptographic Integrity Manifest"))
    story.append(PageBreak())
    story.append(BookmarkAnchor("Cryptographic Integrity Manifest & Archival Credits", level=0, key="manifest", in_toc=True))
    story.append(Paragraph("Cryptographic Integrity Manifest &amp; Archival Credits",
                           ParagraphStyle("h1_man", parent=styles["h1"], fontSize=15.0, spaceAfter=4)))
    story.append(HRFlowable(width="100%", thickness=0.8, color=C_NAVY, spaceBefore=0, spaceAfter=5))

    story.append(Paragraph(
        f"This standalone PDF container was compiled deterministically on <b>{build_date_str}</b> ({build_iso}) from the "
        "exact source manuscripts, live benchmark JSON artifacts, archival plates, and 300 DPI quantitative figures listed below. "
        "Every SHA-256 digest was computed directly from disk prior to container assembly. To verify the assembled PDF against its "
        "companion checksum file, run:",
        ParagraphStyle("man_intro", parent=styles["body"], fontSize=8.8, leading=12.0, spaceAfter=4),
    ))
    cmd_box = Paragraph(
        '<font name="Mono" size="7.8" color="#1E3A5F">cd output &amp;&amp; shasum -a 256 -c two_hands_decentralized_whitepaper.pdf.sha256</font>',
        ParagraphStyle("cmd_p", parent=styles["body_left"], spaceAfter=0),
    )
    cmd_tbl = make_callout([cmd_box], bg=C_CODE_BG, border_color=C_NAVY)
    cmd_tbl.setStyle(TableStyle([("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]))
    story.append(cmd_tbl)
    story.append(Spacer(1, 5))

    man_cell_l = ParagraphStyle("man_cl", parent=styles["cell_sm_l"], fontSize=6.1, leading=7.5)
    man_cell_c = ParagraphStyle("man_cc", parent=styles["cell_sm"], fontSize=6.1, leading=7.5)
    m_data = [[
        Paragraph("<b>Artifact Role</b>", styles["cell_sm_hdr"]),
        Paragraph("<b>Relative Path</b>", styles["cell_sm_hdr"]),
        Paragraph("<b>Size</b>", styles["cell_sm_hdr"]),
        Paragraph("<b>SHA-256 Digest</b>", styles["cell_sm_hdr"]),
    ]]
    for role, rel, path in manifest_items:
        sz_kb = path.stat().st_size / 1024.0
        m_data.append([
            Paragraph(html.escape(role), man_cell_l),
            Paragraph(f'<font name="Mono" size="5.3">{html.escape(rel)}</font>', man_cell_l),
            Paragraph(f"{sz_kb:,.1f} KB", man_cell_c),
            Paragraph(f'<font name="Mono" size="5.2">{hashes[rel]}</font>', man_cell_l),
        ])
    m_tbl = Table(m_data, colWidths=[1.30 * inch, 1.88 * inch, 0.52 * inch, USABLE_W - 3.70 * inch], repeatRows=1)
    m_style = [
        ("BACKGROUND", (0, 0), (-1, 0), C_NAVY),
        ("LINEBELOW", (0, 0), (-1, 0), 0.9, C_NAVY),
        ("LINEBELOW", (0, -1), (-1, -1), 0.9, C_INK),
        ("LINEBELOW", (0, 1), (-1, -2), 0.35, C_RULE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 3.0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3.0),
        ("TOPPADDING", (0, 0), (-1, -1), 1.9),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1.9),
    ]
    for idx in range(1, len(m_data)):
        if idx % 2 == 0:
            m_style.append(("BACKGROUND", (0, idx), (-1, idx), C_ROW_ALT))
    m_tbl.setStyle(TableStyle(m_style))
    story.append(m_tbl)
    story.append(Spacer(1, 6))

    story.append(Paragraph("Archival Plates &amp; Licensing Attributions",
                           ParagraphStyle("h2_man", parent=styles["h2"], fontSize=10.8, spaceBefore=2, spaceAfter=3)))
    man_bul = ParagraphStyle("man_bul", parent=styles["bullet_compact"], fontSize=8.0, leading=10.9, spaceAfter=2.2)
    credits = [
        ("Plate I (Part I Title Plate):",
         "Original editorial still-life composition prepared for this monograph depicting a walnut workbench, blank stitched "
         "linen ledger notebook, cedar pencil, matte galvanized tin box, and anatomically mirrored five-digit leather work gloves."),
        ("Plate II (Part II Title Plate):",
         "*Antikythera Mechanism, Fragment A* (c. 2nd\u20131st century BCE, National Archaeological Museum of Athens, Inv. X 15087). "
         "Archival photograph by Wikimedia Commons contributor **Marsyas** (`NAMA_Machine_d'Anticyth\u00e8re_1.jpg`), "
         "used under Creative Commons Attribution 2.5 Generic (CC BY 2.5) / GFDL."),
        ("Plate III (Part III Title Plate):",
         "Johannes Hevelius, *Serpens et Serpentarius* (Ophiuchus), Plate P from *Firmamentum Sobiescianum, sive Uranographia* "
         "(published posthumously by Elisabeth Hevelius, Gda\u0144sk, 1690). Public Domain (PD-old-100) via Wikimedia Commons "
         "(`Serpens_et_Serpentarius_-_Prodromus_astronomiae_1690_(5590345).jpg`)."),
        ("Figures 1\u20133 & Diagrams 1\u20134:",
         "Generated reproducibly at 300 DPI via `scripts/generate_whitepaper_figures.py` and `scripts/generate_appendix_diagrams.py` "
         "directly from verified live benchmark records (`data/gauntlet_results.json`, `data/benchmark_results.json`) and live "
         "repository architecture (`schema/schema.sql`, `scripts/db_utils.py`, `scripts/single_loop_runner.py`)."),
        ("Typography & Container:",
         "Typeset in embedded STIX General, DejaVu Sans, and DejaVu Sans Mono TrueType fonts via ReportLab 5.1 with full "
         "hierarchical PDF outline bookmarks and 2-pass exact Table of Contents pagination."),
    ]
    for c_hdr, c_txt in credits:
        story.append(Paragraph(f"\u2022&nbsp;&nbsp;<b>{html.escape(c_hdr)}</b> {md_inline_to_rl(c_txt, code_size=7.0)}", man_bul))

    doc = WhitePaperDocTemplate(
        str(OUT_PDF),
        pagesize=letter,
        leftMargin=M_LEFT,
        rightMargin=M_RIGHT,
        topMargin=M_TOP,
        bottomMargin=M_BOTTOM,
        title="Two Hands in a Local Box: A Decentralized, Open-Source Alternative to Centralized Cloud AI",
        author="McDonald, Henry Oscar Arthur (Compiler)",
        subject="Decoupled Neuro-Symbolic State Gating, Defeasible Negative Provenance, and Chiral Humanities Companion",
        creator="scripts/build_whitepaper_pdf.py (ReportLab 5.1)",
    )
    doc.multiBuild(story)

    pdf_sha = sha256_file(OUT_PDF)
    OUT_SHA.write_text(f"{pdf_sha}  {OUT_PDF.name}\n", encoding="utf-8")
    print(f"BUILT PDF: {OUT_PDF} ({OUT_PDF.stat().st_size:,} bytes)")
    print(f"PDF SHA-256: {pdf_sha}")
    print(f"WROTE CHECKSUM: {OUT_SHA}")


if __name__ == "__main__":
    build_whitepaper()
