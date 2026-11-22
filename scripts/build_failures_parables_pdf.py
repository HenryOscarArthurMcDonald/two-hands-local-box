#!/usr/bin/env python3
"""
Build Companion Field Manual PDF:
  output/corpus_failures_and_parables.pdf (+ .sha256)
  Sage/corpus_failures_and_parables.pdf   (+ .sha256)

Matches the university-press ReportLab/STIX pipeline of Volumes I & II,
formatting all 9 verified engineering incidents in a dual-voice layout:
  1. CS-Literate Post-Mortem (Steel Navy left-accent technical card)
  2. Human-Translated Parable / "In Plain English" (Warm Amber parchment card)
"""

from __future__ import annotations

import hashlib
import html
import re
import shutil
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT
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
SRC_MD = ROOT / "chapters" / "corpus_failures_parables.md"
VOL1_PDF = ROOT / "output" / "two_hands_decentralized_whitepaper.pdf"
OUT_PDF = ROOT / "output" / "corpus_failures_and_parables.pdf"
OUT_SHA = ROOT / "output" / "corpus_failures_and_parables.pdf.sha256"
SAGE_PDF = ROOT / "Sage" / "corpus_failures_and_parables.pdf"
SAGE_SHA = ROOT / "Sage" / "corpus_failures_and_parables.pdf.sha256"

# Matched Companion Palette: Slate-Amber Field Manual paired with Vol I Navy/Sage & Vol II Oxblood
C_INK = colors.HexColor("#1C2127")
C_BODY = colors.HexColor("#22262A")
C_MUTED = colors.HexColor("#5B636B")
C_RULE = colors.HexColor("#CFC8BC")
C_NAVY = colors.HexColor("#1E3A5F")        # CS-Literate Post-Mortem spine
C_NAVY_TINT = colors.HexColor("#F2F6FA")
C_AMBER = colors.HexColor("#9C6B1D")       # Human-Translated Parable spine
C_AMBER_TINT = colors.HexColor("#FBF7EE")
C_SAGE = colors.HexColor("#2E6A5E")
C_CREAM = colors.HexColor("#F8F5EE")
C_ROW_ALT = colors.HexColor("#FAF8F4")
C_CODE_BG = colors.HexColor("#ECEFF3")

PAGE_W, PAGE_H = letter
M_LEFT = 0.78 * inch
M_RIGHT = 0.78 * inch
M_TOP = 0.78 * inch
M_BOTTOM = 0.72 * inch
USABLE_W = PAGE_W - M_LEFT - M_RIGHT


def _find_font_dir() -> Path:
    try:
        import matplotlib  # type: ignore

        p = Path(matplotlib.get_data_path()) / "fonts" / "ttf"
        if (p / "STIXGeneral.ttf").exists():
            return p
    except Exception:
        pass
    for cand in ROOT.glob(".venv/lib/python*/site-packages/matplotlib/mpl-data/fonts/ttf"):
        if (cand / "STIXGeneral.ttf").exists():
            return cand
    raise FileNotFoundError("Could not locate STIX/DejaVu TTF fonts (install matplotlib in .venv)")


def register_fonts() -> None:
    ttf_dir = _find_font_dir()
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
        pdfmetrics.registerFont(TTFont(name, str(path)))
    registerFontFamily("STIX", normal="STIX", bold="STIX-Bold", italic="STIX-Italic", boldItalic="STIX-BoldItalic")
    registerFontFamily("Sans", normal="Sans", bold="Sans-Bold", italic="Sans-Italic", boldItalic="Sans-BoldItalic")
    registerFontFamily("Mono", normal="Mono", bold="Mono-Bold", italic="Mono", boldItalic="Mono-Bold")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


INLINE_MATH_MAP = {
    r"O(T^2)": "<i>O</i>(<i>T</i><sup>2</sup>)",
    r"p = 0.282": "<i>p</i> = 0.282",
    r"p = 1.00": "<i>p</i> = 1.00",
    r"H(P) = 0": "<i>H</i>(<i>P</i>) = 0",
    r"I(P; X) = 0": "<i>I</i>(<i>P</i>; <i>X</i>) = 0",
    r"Q^*_{tok}": "<i>Q</i><sup>*</sup><sub>tok</sub>",
    r"Q^*_{USD}": "<i>Q</i><sup>*</sup><sub>USD</sub>",
}


def convert_inline_math(expr: str) -> str:
    expr = expr.strip()
    if expr in INLINE_MATH_MAP:
        return INLINE_MATH_MAP[expr]
    s = html.escape(expr)
    for k, v in [(r"\approx", "\u2248"), (r"\le", "\u2264"), (r"\ge", "\u2265"), (r"\to", "\u2192"), (r"\alpha", "\u03b1")]:
        s = s.replace(k, v)
    return f"<i>{s}</i>"


def md_inline_to_rl(text: str, code_size: float = 8.0, code_color: str = "#1E3A5F") -> str:
    placeholders: dict[str, str] = {}
    counter = [0]

    def stash(val: str) -> str:
        key = f"\x00PH{counter[0]}\x00"
        counter[0] += 1
        placeholders[key] = val
        return key

    def repl_code(m: re.Match[str]) -> str:
        inner = html.escape(m.group(1))
        return stash(f'<font name="Mono" size="{code_size}" color="{code_color}">{inner}</font>')

    text = re.sub(r"`([^`]+)`", repl_code, text)
    text = text.replace(r"\$", stash("$"))
    text = text.replace(r"\*", stash("*"))

    def repl_link(m: re.Match[str]) -> str:
        label_xml = md_inline_to_rl(m.group(1), code_size=code_size, code_color=code_color)
        url = m.group(2)
        if url.startswith("http://") or url.startswith("https://"):
            return stash(f'<link href="{html.escape(url, quote=True)}" color="#1E3A5F">{label_xml}</link>')
        return stash(f'<font color="#1E3A5F">{label_xml}</font>')

    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", repl_link, text)
    text = re.sub(r"\$([^$\n]+)\$", lambda m: stash(convert_inline_math(m.group(1))), text)
    text = html.escape(text)
    text = re.sub(r"\*\*\*((?:(?!\*\*\*).)+?)\*\*\*", r"<b><i>\1</i></b>", text)

    def repl_bold(m: re.Match[str]) -> str:
        inner = re.sub(r"(?<!\*)\*([^*\n]+?)\*(?!\*)", r"<i>\1</i>", m.group(1))
        return f"<b>{inner}</b>"

    text = re.sub(r"\*\*((?:(?!\*\*).)+?)\*\*", repl_bold, text)
    text = re.sub(r"(?<!\*)\*([^*\n]+?)\*(?!\*)", r"<i>\1</i>", text)
    for sym in ("\u2192", "\u2194", "\u2260", "\u2264", "\u2265", "\u2248", "\u00d7"):
        text = text.replace(sym, f'<font name="STIX">{sym}</font>')

    for k, v in reversed(list(placeholders.items())):
        text = text.replace(k, v)
    return text


class SectionBannerTracker(Flowable):
    def __init__(self, header_label: str):
        super().__init__()
        self.header_label = header_label
        self.width = 0
        self.height = 0

    def draw(self) -> None:
        pass


class BookmarkAnchor(Flowable):
    def __init__(self, title: str, level: int = 0, key: str = "", in_toc: bool = True):
        super().__init__()
        self.title = title
        self.level = level
        self.key = key or re.sub(r"[^a-zA-Z0-9_]+", "_", title)[:48]
        self.in_toc = in_toc
        self.keepWithNext = True
        self.width = 0
        self.height = 0

    def draw(self) -> None:
        self.canv.bookmarkPage(self.key)
        self.canv.addOutlineEntry(self.title, self.key, level=self.level, closed=(self.level >= 1))


class ParablesDocTemplate(BaseDocTemplate):
    def __init__(self, filename: str, **kwargs):
        super().__init__(filename, **kwargs)
        self._running_section = ""

        cover_frame = Frame(
            M_LEFT, M_BOTTOM, USABLE_W, PAGE_H - M_TOP - M_BOTTOM,
            leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0, id="cover",
        )
        body_frame = Frame(
            M_LEFT, M_BOTTOM, USABLE_W, PAGE_H - M_TOP - M_BOTTOM,
            leftPadding=0, rightPadding=0, topPadding=4, bottomPadding=4, id="body",
        )
        self.addPageTemplates([
            PageTemplate(id="Cover", frames=[cover_frame], onPage=self._draw_cover_bg),
            PageTemplate(id="Body", frames=[body_frame], onPage=self._draw_body_chrome),
        ])

    def handle_documentBegin(self) -> None:
        super().handle_documentBegin()
        self._running_section = ""

    def _draw_cover_bg(self, canvas, doc) -> None:
        canvas.saveState()
        canvas.setFillColor(C_CREAM)
        canvas.rect(0, PAGE_H - 1.35 * inch, PAGE_W, 1.35 * inch, fill=1, stroke=0)
        canvas.setFillColor(C_NAVY)
        canvas.rect(0, PAGE_H - 0.14 * inch, PAGE_W * 0.5, 0.14 * inch, fill=1, stroke=0)
        canvas.setFillColor(C_AMBER)
        canvas.rect(PAGE_W * 0.5, PAGE_H - 0.14 * inch, PAGE_W * 0.5, 0.14 * inch, fill=1, stroke=0)
        canvas.setStrokeColor(C_RULE)
        canvas.setLineWidth(0.7)
        canvas.line(0, PAGE_H - 1.35 * inch, PAGE_W, PAGE_H - 1.35 * inch)
        canvas.setFillColor(C_NAVY)
        canvas.rect(M_LEFT, 0.58 * inch, USABLE_W * 0.48, 2.0, fill=1, stroke=0)
        canvas.setFillColor(C_AMBER)
        canvas.rect(M_LEFT + USABLE_W * 0.52, 0.58 * inch, USABLE_W * 0.48, 2.0, fill=1, stroke=0)
        canvas.restoreState()

    def _draw_body_chrome(self, canvas, doc) -> None:
        canvas.saveState()
        sec = self._running_section or "Failures, Parables & Crash Reports"
        y_top = PAGE_H - 0.56 * inch
        canvas.setFont("Sans", 7.3)
        canvas.setFillColor(C_MUTED)
        canvas.drawString(M_LEFT, y_top + 5, "BUILDER'S COMPANION \u00b7 FAILURES, PARABLES & CRASH REPORTS")
        canvas.drawRightString(PAGE_W - M_RIGHT, y_top + 5, sec[:62])
        canvas.setStrokeColor(C_RULE)
        canvas.setLineWidth(0.45)
        canvas.line(M_LEFT, y_top, PAGE_W - M_RIGHT, y_top)

        y_bot = 0.52 * inch
        canvas.line(M_LEFT, y_bot + 11, PAGE_W - M_RIGHT, y_bot + 11)
        canvas.setFont("Sans", 7.2)
        canvas.drawString(M_LEFT, y_bot, "Dual-Voice Post-Mortems & Plain-English Field Guide (2026)")
        canvas.setFont("Sans-Bold", 7.5)
        canvas.setFillColor(C_INK)
        canvas.drawRightString(PAGE_W - M_RIGHT, y_bot, f"Page {doc.page}")
        canvas.restoreState()

    def afterFlowable(self, flowable) -> None:
        if isinstance(flowable, SectionBannerTracker):
            self._running_section = flowable.header_label
        elif isinstance(flowable, BookmarkAnchor):
            if flowable.in_toc:
                self.notify("TOCEntry", (flowable.level, flowable.title, self.page, flowable.key))


def build_styles() -> dict[str, ParagraphStyle]:
    s: dict[str, ParagraphStyle] = {}
    s["kicker"] = ParagraphStyle("kicker", fontName="Sans-Bold", fontSize=8.0, leading=11, textColor=C_NAVY, spaceAfter=6)
    s["cover_title"] = ParagraphStyle("cover_title", fontName="STIX-Bold", fontSize=25.5, leading=30.5, textColor=C_INK, spaceBefore=18, spaceAfter=10)
    s["cover_sub"] = ParagraphStyle("cover_sub", fontName="STIX-Italic", fontSize=12.6, leading=17.6, textColor=C_MUTED, spaceAfter=16)
    s["h1"] = ParagraphStyle("h1", fontName="STIX-Bold", fontSize=15.0, leading=19.2, textColor=C_INK, spaceBefore=4, spaceAfter=6, keepWithNext=True)
    s["h2"] = ParagraphStyle("h2", fontName="STIX-Bold", fontSize=12.4, leading=15.8, textColor=C_NAVY, spaceBefore=5, spaceAfter=4, keepWithNext=True)
    s["body"] = ParagraphStyle("body", fontName="STIX", fontSize=9.8, leading=13.7, textColor=C_BODY, alignment=TA_JUSTIFY, spaceAfter=5.2)
    s["card_kicker_cs"] = ParagraphStyle("card_kicker_cs", fontName="Sans-Bold", fontSize=7.4, leading=9.8, textColor=C_NAVY, spaceAfter=2.5)
    s["card_kicker_human"] = ParagraphStyle("card_kicker_human", fontName="Sans-Bold", fontSize=7.4, leading=9.8, textColor=C_AMBER, spaceAfter=2.5)
    s["card_body"] = ParagraphStyle("card_body", fontName="STIX", fontSize=8.8, leading=12.0, textColor=C_BODY, alignment=TA_JUSTIFY, spaceAfter=3.0)
    s["card_bullet"] = ParagraphStyle("card_bullet", fontName="STIX", fontSize=8.6, leading=11.7, textColor=C_BODY, alignment=TA_LEFT, leftIndent=12, firstLineIndent=-8, spaceAfter=2.2)
    s["card_subbullet"] = ParagraphStyle("card_subbullet", fontName="STIX", fontSize=8.3, leading=11.2, textColor=C_BODY, alignment=TA_LEFT, leftIndent=22, firstLineIndent=-8, spaceAfter=1.8)
    s["code_block"] = ParagraphStyle("code_block", fontName="Mono", fontSize=7.6, leading=10.6, textColor=C_INK, backColor=C_CODE_BG, leftIndent=6, rightIndent=6, spaceBefore=3, spaceAfter=4)
    s["bullet"] = ParagraphStyle("bullet", fontName="STIX", fontSize=9.6, leading=13.4, textColor=C_BODY, alignment=TA_LEFT, leftIndent=16, firstLineIndent=-10, spaceAfter=4.2)
    s["tbl_hdr"] = ParagraphStyle("tbl_hdr", fontName="Sans-Bold", fontSize=7.8, leading=10.4, textColor=colors.white, alignment=TA_LEFT)
    s["tbl_cell"] = ParagraphStyle("tbl_cell", fontName="STIX", fontSize=8.3, leading=11.2, textColor=C_BODY, alignment=TA_LEFT)
    s["tbl_cell_c"] = ParagraphStyle("tbl_cell_c", fontName="Sans-Bold", fontSize=8.0, leading=11.0, textColor=C_NAVY, alignment=TA_CENTER)
    s["toc0"] = ParagraphStyle("toc0", fontName="Sans-Bold", fontSize=8.6, leading=13.2, textColor=C_NAVY, leftIndent=0, spaceBefore=3.5, spaceAfter=1.2)
    s["colophon"] = ParagraphStyle("colophon", fontName="STIX", fontSize=8.8, leading=12.6, textColor=C_BODY, spaceAfter=4)
    return s


def make_dual_card(kind: str, body_flowables: list, styles: dict[str, ParagraphStyle]) -> Table:
    """Wrap a CS Post-Mortem or Plain-English Parable inside a distinct left-accented card."""
    if kind == "cs":
        kicker = Paragraph("CS-LITERATE POST-MORTEM  \u00b7  MECHANISM, TELEMETRY &amp; FIX", styles["card_kicker_cs"])
        accent = C_NAVY
        bg = C_NAVY_TINT
    else:
        kicker = Paragraph("IN PLAIN ENGLISH  \u00b7  HUMAN-TRANSLATED BUILDER PARABLE", styles["card_kicker_human"])
        accent = C_AMBER
        bg = C_AMBER_TINT

    # Use one row per item so ReportLab can split cleanly across pages if a post-mortem is tall
    rows = [[kicker]] + [[fl] for fl in body_flowables]
    tbl = Table(rows, colWidths=[USABLE_W], repeatRows=1)
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), bg),
        ("LINEBEFORE", (0, 0), (0, -1), 3.2, accent),
        ("LINEABOVE", (0, 0), (-1, 0), 0.4, C_RULE),
        ("LINEBELOW", (0, -1), (-1, -1), 0.4, C_RULE),
        ("LINEAFTER", (-1, 0), (-1, -1), 0.4, C_RULE),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 9),
        ("TOPPADDING", (0, 0), (-1, 0), 5.5),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 1.5),
        ("TOPPADDING", (0, 1), (-1, -1), 1.0),
        ("BOTTOMPADDING", (0, 1), (-1, -2), 1.0),
        ("BOTTOMPADDING", (0, -1), (-1, -1), 5.5),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    return tbl


def parse_markdown_table(lines: list[str], styles: dict[str, ParagraphStyle]) -> Table:
    rows_raw = []
    for ln in lines:
        s = ln.strip()
        if not s.startswith("|"):
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        if all(re.fullmatch(r":?-{2,}:?", c.replace(" ", "")) for c in cells):
            continue
        rows_raw.append(cells)

    if not rows_raw:
        return Spacer(1, 2)

    ncols = len(rows_raw[0])
    # Tailor column widths for the 4-column Quick-Reference Matrix
    if ncols == 4:
        col_widths = [0.38 * inch, 1.48 * inch, 2.15 * inch, USABLE_W - (0.38 + 1.48 + 2.15) * inch]
    else:
        col_widths = [USABLE_W / ncols] * ncols

    data = []
    for r_idx, row in enumerate(rows_raw):
        formatted = []
        for c_idx, cell in enumerate(row):
            if r_idx == 0:
                formatted.append(Paragraph(md_inline_to_rl(cell, code_size=7.4, code_color="#FFFFFF"), styles["tbl_hdr"]))
            elif c_idx == 0 and ncols == 4:
                formatted.append(Paragraph(md_inline_to_rl(cell, code_size=7.6), styles["tbl_cell_c"]))
            else:
                formatted.append(Paragraph(md_inline_to_rl(cell, code_size=7.4), styles["tbl_cell"]))
        data.append(formatted)

    tbl = Table(data, colWidths=col_widths, repeatRows=1)
    style_cmds = [
        ("BACKGROUND", (0, 0), (-1, 0), C_NAVY),
        ("GRID", (0, 0), (-1, -1), 0.35, C_RULE),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 4.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4.5),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]
    for r_idx in range(1, len(data)):
        if r_idx % 2 == 0:
            style_cmds.append(("BACKGROUND", (0, r_idx), (-1, r_idx), C_ROW_ALT))
    tbl.setStyle(TableStyle(style_cmds))
    return tbl


def parse_block_lines(lines: list[str], styles: dict[str, ParagraphStyle], in_card: bool = False) -> list:
    flow: list = []
    i = 0
    n = len(lines)
    p_style = styles["card_body"] if in_card else styles["body"]
    b_style = styles["card_bullet"] if in_card else styles["bullet"]
    sb_style = styles["card_subbullet"] if in_card else styles["bullet"]

    while i < n:
        ln = lines[i]
        stripped = ln.strip()
        if not stripped or stripped == "---":
            i += 1
            continue

        # Fenced code block
        if stripped.startswith("```"):
            code_lines = []
            i += 1
            while i < n and not lines[i].strip().startswith("```"):
                code_lines.append(lines[i])
                i += 1
            i += 1
            code_html = "<br/>".join(html.escape(cl) for cl in code_lines)
            flow.append(Paragraph(code_html, styles["code_block"]))
            continue

        # Markdown table
        if stripped.startswith("|") and i + 1 < n and lines[i + 1].strip().startswith("|"):
            tbl_lines = []
            while i < n and lines[i].strip().startswith("|"):
                tbl_lines.append(lines[i])
                i += 1
            flow.append(Spacer(1, 4))
            flow.append(parse_markdown_table(tbl_lines, styles))
            flow.append(Spacer(1, 6))
            continue

        # Indented sub-bullet
        if re.match(r"^\s{2,}[-*]\s+", ln) or re.match(r"^\s{2,}\d+\.\s+", ln):
            m = re.match(r"^\s+([-*]|\d+\.)\s+(.*)$", ln)
            bullet_mark = "\u25e6" if m.group(1) in ("-", "*") else m.group(1)
            flow.append(Paragraph(f"{bullet_mark} {md_inline_to_rl(m.group(2))}", sb_style))
            i += 1
            continue

        # Top-level bullet or numbered item
        if re.match(r"^[-*]\s+", stripped) or re.match(r"^\d+\.\s+", stripped):
            m = re.match(r"^([-*]|\d+\.)\s+(.*)$", stripped)
            bullet_mark = "\u2022" if m.group(1) in ("-", "*") else f"<b>{m.group(1)}</b>"
            flow.append(Paragraph(f"{bullet_mark} {md_inline_to_rl(m.group(2))}", b_style))
            i += 1
            continue

        # Regular paragraph (merge consecutive non-blank prose lines)
        para_lines = [stripped]
        i += 1
        while i < n:
            nxt = lines[i].strip()
            if not nxt or nxt == "---" or nxt.startswith(("```", "|", "## ", "### ", "- ", "* ")) or re.match(r"^\d+\.\s+", nxt):
                break
            para_lines.append(nxt)
            i += 1
        flow.append(Paragraph(md_inline_to_rl(" ".join(para_lines)), p_style))

    return flow


def build_pdf() -> None:
    register_fonts()
    styles = build_styles()
    md_text = SRC_MD.read_text(encoding="utf-8")

    vol1_sha = sha256_file(VOL1_PDF) if VOL1_PDF.exists() else "unbuilt"
    vol1_sha_short = vol1_sha[:16]

    OUT_PDF.parent.mkdir(parents=True, exist_ok=True)
    SAGE_PDF.parent.mkdir(parents=True, exist_ok=True)

    doc = ParablesDocTemplate(
        str(OUT_PDF),
        pagesize=letter,
        title="Failures, Parables & Crash Reports: A Builder's Companion to Local State Gating",
        author="McDonald, Henry Oscar Arthur (Compiler)",
        subject="Nine Verified Engineering Post-Mortems & Plain-English Builder Parables",
        creator="ReportLab + STIX Typography Pipeline",
    )

    story: list = []

    # --- COVER PAGE ---
    story.append(Spacer(1, 0.30 * inch))
    story.append(Paragraph("CORPUS COMPANION FIELD MANUAL  \u00b7  DUAL-VOICE ENGINEERING EDITION", styles["kicker"]))
    story.append(Paragraph("Failures, Parables &amp; Crash Reports", styles["cover_title"]))
    story.append(Paragraph("Nine Verified Post-Mortems &amp; Plain-English Field Lessons from Building a Local-First Epistemic LLM Stack", styles["cover_sub"]))
    story.append(HRFlowable(width="100%", thickness=0.8, color=C_RULE, spaceBefore=2, spaceAfter=14))

    meta_box = Table(
        [
            [Paragraph("<b>Compilation / Provenance:</b> Open synthesis of prior public work &amp; verified engineering crash logs (MIT code / CC BY 4.0 docs; machine provenance in <font name='Mono' size='7.8'>CITATION.cff</font> &amp; Zenodo DOI)", styles["colophon"])],
            [Paragraph("<b>Publication Date:</b> November 21, 2026 &nbsp;\u00b7&nbsp; <b>Format:</b> Dual-Voice Technical Post-Mortem + Plain-English Parable", styles["colophon"])],
            [Paragraph("<b>Companion Set:</b> Volume I (<i>Two Hands in a Local Box</i>) &amp; Volume II (<i>From Genesis Body to SQLite</i>)", styles["colophon"])],
            [Paragraph(f"<b>Volume I Anchor Digest:</b> <font name='Mono' size='7.8' color='#1E3A5F'>sha256:{vol1_sha_short}...</font>", styles["colophon"])],
            [Paragraph("<b>Strict Evidence Standard:</b> Every byte count, token bill, error traceback, and table tally is drawn verbatim from local repository artifacts (<font name='Mono' size='7.8'>archive.db?mode=ro</font>, <font name='Mono' size='7.8'>data/corpus.db?mode=ro</font>, <font name='Mono' size='7.8'>data/gauntlet_results.json</font>, <font name='Mono' size='7.8'>data/archive_backfill_report.json</font>, and <font name='Mono' size='7.8'>logs/closedloop_launchd.err.log</font>). Zero fabricated stories.", styles["colophon"])],
        ],
        colWidths=[USABLE_W],
    )
    meta_box.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), C_CREAM),
        ("BOX", (0, 0), (-1, -1), 0.6, C_RULE),
        ("LEFTPADDING", (0, 0), (-1, -1), 12),
        ("RIGHTPADDING", (0, 0), (-1, -1), 12),
        ("TOPPADDING", (0, 0), (-1, 0), 9),
        ("BOTTOMPADDING", (0, -1), (-1, -1), 9),
        ("TOPPADDING", (0, 1), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -2), 2),
    ]))
    story.append(meta_box)
    story.append(Spacer(1, 0.25 * inch))

    # Dual-voice legend on cover
    legend = Table(
        [[
            Paragraph("<b><font color='#1E3A5F'>STEEL-NAVY CARDS</font></b><br/>CS-Literate Post-Mortems: exact root cause, verified telemetry, failure signature, and code/SQLite fix.", styles["tbl_cell"]),
            Paragraph("<b><font color='#9C6B1D'>AMBER-PARCHMENT CARDS</font></b><br/>Human-Translated Parables: plain-English intuition, why the trap felt reasonable, and the builder takeaway.", styles["tbl_cell"]),
        ]],
        colWidths=[USABLE_W * 0.49, USABLE_W * 0.49],
    )
    legend.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, 0), C_NAVY_TINT),
        ("LINEBEFORE", (0, 0), (0, 0), 3.0, C_NAVY),
        ("BACKGROUND", (1, 0), (1, 0), C_AMBER_TINT),
        ("LINEBEFORE", (1, 0), (1, 0), 3.0, C_AMBER),
        ("BOX", (0, 0), (0, 0), 0.4, C_RULE),
        ("BOX", (1, 0), (1, 0), 0.4, C_RULE),
        ("LEFTPADDING", (0, 0), (-1, -1), 9),
        ("RIGHTPADDING", (0, 0), (-1, -1), 9),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    story.append(legend)
    story.append(NextPageTemplate("Body"))
    story.append(PageBreak())

    # --- TABLE OF CONTENTS ---
    story.append(SectionBannerTracker("Contents"))
    story.append(Paragraph("Contents", styles["h1"]))
    story.append(HRFlowable(width="100%", thickness=0.6, color=C_RULE, spaceAfter=10))
    toc = TableOfContents()
    toc.levelStyles = [styles["toc0"]]
    story.append(toc)
    story.append(PageBreak())

    # --- PARSE SECTIONS BY `## ` ---
    sections = re.split(r"(?m)^## ", md_text)
    for sec_idx, raw_sec in enumerate(sections[1:], start=1):
        sec_lines = raw_sec.splitlines()
        sec_title = sec_lines[0].strip()
        clean_title = sec_title.replace("`", "").replace("*", "")
        sec_body = sec_lines[1:]
        sec_key = f"sec_{sec_idx}"

        # Set running header BEFORE PageBreak so every Incident & Closing Matrix starts cleanly on its own page
        story.append(SectionBannerTracker(clean_title))
        if sec_title.startswith("Incident ") or sec_title.startswith("Closing Quick-Reference"):
            story.append(PageBreak())

        story.append(BookmarkAnchor(clean_title, level=0, key=sec_key, in_toc=True))
        story.append(Paragraph(md_inline_to_rl(sec_title), styles["h2"]))
        story.append(HRFlowable(width="100%", thickness=0.5, color=C_RULE, spaceAfter=5.5))

        # Split by `### ` sub-blocks (for dual-voice cards)
        joined = "\n".join(sec_body)
        sub_parts = re.split(r"(?m)^### ", joined)
        preamble = sub_parts[0].strip()
        if preamble:
            story.extend(parse_block_lines(preamble.splitlines(), styles, in_card=False))

        for sub in sub_parts[1:]:
            slines = sub.splitlines()
            stitle = slines[0].strip()
            sbody = slines[1:]
            if "CS-Literate Post-Mortem" in stitle:
                card_items = parse_block_lines(sbody, styles, in_card=True)
                story.append(make_dual_card("cs", card_items, styles))
                story.append(Spacer(1, 5.5))
            elif "Human-Translated Parable" in stitle or "Plain English" in stitle:
                card_items = parse_block_lines(sbody, styles, in_card=True)
                story.append(make_dual_card("human", card_items, styles))
                story.append(Spacer(1, 5.5))
            else:
                story.append(Paragraph(md_inline_to_rl(stitle), styles["h2"]))
                story.extend(parse_block_lines(sbody, styles, in_card=False))

    doc.multiBuild(story)

    digest = sha256_file(OUT_PDF)
    OUT_SHA.write_text(f"{digest}  {OUT_PDF.name}\n", encoding="utf-8")
    shutil.copy2(OUT_PDF, SAGE_PDF)
    SAGE_SHA.write_text(f"{digest}  {SAGE_PDF.name}\n", encoding="utf-8")
    print(f"Built {OUT_PDF} ({OUT_PDF.stat().st_size:,} bytes) | sha256={digest}")
    print(f"Staged {SAGE_PDF} + {SAGE_SHA}")


if __name__ == "__main__":
    build_pdf()
