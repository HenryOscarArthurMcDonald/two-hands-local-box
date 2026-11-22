#!/usr/bin/env python3
"""
Build Companion Volume II PDF:
  output/corpus_history_companion_volume.pdf
and its SHA-256 companion checksum:
  output/corpus_history_companion_volume.pdf.sha256

Matches the exact university-press ReportLab pipeline of Volume I
(output/two_hands_decentralized_whitepaper.pdf), embedding:
  - Cover Page & Cross-Volume SHA-256 Colophon
  - Archival Title Plate (Woudanus / van Swanenburg Leiden University Library, 1610)
  - 2-Pass Exact Table of Contents & List of Figures
  - Complete Historiographical Monograph (chapters/corpus_history_companion_volume.md)
  - Figure 1 (Longitudinal Material History & Overkill Collapse)
  - Figure 2 (Epistemic Self-Audit & Tier Re-Tiering: v0.2.0 vs Schema v3)
  - Closing Cryptographic Integrity Manifest & Archival Credits
"""

import hashlib
import html
import os
import re
from pathlib import Path

from PIL import Image as PILImage
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

SRC_MD = ROOT / "chapters" / "corpus_history_companion_volume.md"
VOL1_PDF = ROOT / "output" / "two_hands_decentralized_whitepaper.pdf"
OUT_PDF = ROOT / "output" / "corpus_history_companion_volume.pdf"
OUT_SHA = ROOT / "output" / "corpus_history_companion_volume.pdf.sha256"

# Matched Companion Palette (Archival Oxblood/Rust spine paired with Volume I Navy & Sage)
C_INK = colors.HexColor("#1C2127")
C_BODY = colors.HexColor("#22262A")
C_MUTED = colors.HexColor("#5B636B")
C_RULE = colors.HexColor("#CFC8BC")
C_RULE_DARK = colors.HexColor("#8E8578")
C_ACCENT = colors.HexColor("#7F3426")     # Companion Vol II Primary Oxblood / Archival Terracotta
C_NAVY = colors.HexColor("#1E3A5F")
C_SAGE = colors.HexColor("#2E6A5E")
C_AMBER = colors.HexColor("#9C6B1D")
C_CREAM = colors.HexColor("#F8F5EE")
C_ACCENT_TINT = colors.HexColor("#F8EFEA")
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


INLINE_MATH_MAP = {
    r"\alpha": "\u03b1",
    r"\pi": "\u03c0",
    r"1/r^2": "1/<i>r</i><sup>2</sup>",
    r"g \in \mathbb{Z}_{\ge 0}": "<i>g</i> \u2208 \u2124<sub>\u2265 0</sub>",
    r"p \to 1": "<i>p</i> \u2192 1",
    r"p = 0.282": "<i>p</i> = 0.282",
    r"p = 1.00": "<i>p</i> = 1.00",
    r"H(P) = 0": "<i>H</i>(<i>P</i>) = 0",
    r"H(P)=0": "<i>H</i>(<i>P</i>) = 0",
    r"I(P; X) = 0": "<i>I</i>(<i>P</i>; <i>X</i>) = 0",
    r"H(P) \approx 0": "<i>H</i>(<i>P</i>) \u2248 0",
    r"F(g \circ f) = F(g) \circ F(f)": "<i>F</i>(<i>g</i> \u2218 <i>f</i>) = <i>F</i>(<i>g</i>) \u2218 <i>F</i>(<i>f</i>)",
    r"Q^* = 1,137": "<i>Q</i><sup>*</sup> = 1,137",
}


def convert_inline_math(expr: str) -> str:
    expr = expr.strip()
    if expr in INLINE_MATH_MAP:
        return INLINE_MATH_MAP[expr]
    s = html.escape(expr)
    for k, v in [(r"\approx", "\u2248"), (r"\le", "\u2264"), (r"\ge", "\u2265"), (r"\to", "\u2192"), (r"\pi", "\u03c0"), (r"\alpha", "\u03b1")]:
        s = s.replace(k, v)
    return f"<i>{s}</i>"


def md_inline_to_rl(text: str, code_size: float = 8.2, code_color: str = "#1E3A5F") -> str:
    placeholders = {}
    counter = [0]

    def stash(val: str) -> str:
        key = f"\x00PH{counter[0]}\x00"
        counter[0] += 1
        placeholders[key] = val
        return key

    def repl_code(m):
        inner = html.escape(m.group(1))
        return stash(f'<font name="Mono" size="{code_size}" color="{code_color}">{inner}</font>')

    text = re.sub(r"`([^`]+)`", repl_code, text)

    text = text.replace(r"\$", stash("$"))
    text = text.replace(r"\*", stash("*"))

    def repl_link(m):
        label_xml = md_inline_to_rl(m.group(1), code_size=code_size)
        url = m.group(2)
        if url.startswith("http://") or url.startswith("https://"):
            return stash(f'<link href="{html.escape(url, quote=True)}" color="#1E3A5F">{label_xml}</link>')
        return stash(f'<font color="#1E3A5F">{label_xml}</font>')

    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", repl_link, text)

    def repl_math(m):
        return stash(convert_inline_math(m.group(1)))

    text = re.sub(r"\$([^$\n]+)\$", repl_math, text)
    text = html.escape(text)
    text = re.sub(r"\*\*\*((?:(?!\*\*\*).)+?)\*\*\*", r"<b><i>\1</i></b>", text)

    def repl_bold(m):
        inner = m.group(1)
        inner = re.sub(r"(?<!\*)\*([^*\n]+?)\*(?!\*)", r"<i>\1</i>", inner)
        return f"<b>{inner}</b>"

    text = re.sub(r"\*\*((?:(?!\*\*).)+?)\*\*", repl_bold, text)
    text = re.sub(r"(?<!\*)\*([^*\n]+?)\*(?!\*)", r"<i>\1</i>", text)
    for _sym in ("\u2192", "\u2194", "\u2260", "\u2264", "\u2265", "\u2248"):
        text = text.replace(_sym, f'<font name="STIX">{_sym}</font>')

    for k, v in reversed(list(placeholders.items())):
        text = text.replace(k, v)
    return text


class SectionBannerTracker(Flowable):
    def __init__(self, header_label: str):
        super().__init__()
        self.header_label = header_label
        self.width = 0
        self.height = 0

    def draw(self):
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

    def draw(self):
        self.canv.bookmarkPage(self.key)
        self.canv.addOutlineEntry(self.title, self.key, level=self.level, closed=(self.level >= 1))


class HistoryVolumeDocTemplate(BaseDocTemplate):
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
            PageTemplate(id="TitlePlate", frames=[plate_frame], onPage=self._draw_plate_bg),
            PageTemplate(id="Body", frames=[body_frame], onPage=self._draw_body_chrome),
        ])

    def handle_documentBegin(self):
        super().handle_documentBegin()
        self._running_section = ""

    def _draw_cover_bg(self, canvas, doc):
        canvas.saveState()
        canvas.setFillColor(C_CREAM)
        canvas.rect(0, PAGE_H - 1.35 * inch, PAGE_W, 1.35 * inch, fill=1, stroke=0)
        canvas.setFillColor(C_ACCENT)
        canvas.rect(0, PAGE_H - 0.14 * inch, PAGE_W, 0.14 * inch, fill=1, stroke=0)
        canvas.setStrokeColor(C_RULE)
        canvas.setLineWidth(0.7)
        canvas.line(0, PAGE_H - 1.35 * inch, PAGE_W, PAGE_H - 1.35 * inch)
        canvas.setFillColor(C_ACCENT)
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
        sec = self._running_section or "The Age of Overkill and the Grounded Wire"
        y_top = PAGE_H - 0.58 * inch
        canvas.setFont("Sans", 7.4)
        canvas.setFillColor(C_MUTED)
        canvas.drawString(M_LEFT, y_top + 5, "COMPANION VOLUME II \u00b7 CORPUS HISTORIOGRAPHY")
        canvas.drawRightString(PAGE_W - M_RIGHT, y_top + 5, sec)
        canvas.setStrokeColor(C_RULE)
        canvas.setLineWidth(0.45)
        canvas.line(M_LEFT, y_top, PAGE_W - M_RIGHT, y_top)

        y_bot = 0.54 * inch
        canvas.line(M_LEFT, y_bot + 11, PAGE_W - M_RIGHT, y_bot + 11)
        canvas.setFont("Sans", 7.3)
        canvas.drawString(M_LEFT, y_bot, "Material & Intellectual History (2025\u20132026) \u00b7 Read-Only Archival Forensics")
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


def build_styles():
    s = {}
    s["kicker"] = ParagraphStyle("kicker", fontName="Sans-Bold", fontSize=8.0, leading=11, textColor=C_ACCENT, spaceAfter=6)
    s["cover_title"] = ParagraphStyle("cover_title", fontName="STIX-Bold", fontSize=26.5, leading=31.5, textColor=C_INK, spaceBefore=20, spaceAfter=10)
    s["cover_sub"] = ParagraphStyle("cover_sub", fontName="STIX-Italic", fontSize=13.0, leading=18.2, textColor=C_MUTED, spaceAfter=16)
    s["plate_kicker"] = ParagraphStyle("plate_kicker", fontName="Sans-Bold", fontSize=8.6, leading=12, textColor=C_ACCENT, alignment=TA_CENTER, spaceBefore=14, spaceAfter=7)
    s["plate_title"] = ParagraphStyle("plate_title", fontName="STIX-Bold", fontSize=20.5, leading=25.0, textColor=C_INK, alignment=TA_CENTER, spaceAfter=6)
    s["plate_sub"] = ParagraphStyle("plate_sub", fontName="STIX-Italic", fontSize=11.0, leading=15.0, textColor=C_MUTED, alignment=TA_CENTER, spaceAfter=14)
    s["plate_cap"] = ParagraphStyle("plate_cap", fontName="STIX-Italic", fontSize=8.6, leading=12.4, textColor=C_MUTED, alignment=TA_CENTER, leftIndent=14, rightIndent=14, spaceBefore=10)
    s["h1"] = ParagraphStyle("h1", fontName="STIX-Bold", fontSize=15.6, leading=20.0, textColor=C_ACCENT, spaceBefore=6, spaceAfter=7, keepWithNext=True)
    s["h2"] = ParagraphStyle("h2", fontName="STIX-Bold", fontSize=13.0, leading=16.8, textColor=C_ACCENT, spaceBefore=13, spaceAfter=5, keepWithNext=True)
    s["h3"] = ParagraphStyle("h3", fontName="Sans-Bold", fontSize=9.8, leading=13.5, textColor=C_NAVY, spaceBefore=10, spaceAfter=4, keepWithNext=True)
    s["body"] = ParagraphStyle("body", fontName="STIX", fontSize=10.0, leading=14.1, textColor=C_BODY, alignment=TA_JUSTIFY, spaceAfter=5.8)
    s["body_left"] = ParagraphStyle("body_left", fontName="STIX", fontSize=10.0, leading=14.1, textColor=C_BODY, alignment=TA_LEFT, spaceAfter=5.8)
    s["bullet"] = ParagraphStyle("bullet", fontName="STIX", fontSize=9.7, leading=13.5, textColor=C_BODY, alignment=TA_LEFT, leftIndent=16, firstLineIndent=-10, spaceAfter=4.2)
    s["bullet_compact"] = ParagraphStyle("bullet_compact", fontName="STIX", fontSize=8.7, leading=12.0, textColor=C_BODY, alignment=TA_LEFT, leftIndent=14, firstLineIndent=-9, spaceAfter=3.0)
    s["quote"] = ParagraphStyle("quote", fontName="STIX-Italic", fontSize=9.8, leading=14.0, textColor=C_INK, alignment=TA_JUSTIFY, leftIndent=10, rightIndent=10, spaceAfter=2)
    s["table_cap"] = ParagraphStyle("table_cap", fontName="STIX-Italic", fontSize=8.8, leading=12.0, textColor=C_MUTED, alignment=TA_LEFT, spaceBefore=8, spaceAfter=4, keepWithNext=True)
    s["fig_cap"] = ParagraphStyle("fig_cap", fontName="STIX-Italic", fontSize=8.4, leading=11.6, textColor=C_MUTED, alignment=TA_LEFT, spaceBefore=5, spaceAfter=9)
    s["toc0"] = ParagraphStyle("toc0", fontName="Sans-Bold", fontSize=8.0, leading=11.6, textColor=C_ACCENT, leftIndent=0, spaceBefore=3.5, spaceAfter=0.8)
    s["toc1"] = ParagraphStyle("toc1", fontName="STIX", fontSize=8.3, leading=11.0, textColor=C_BODY, leftIndent=14, spaceBefore=0.3, spaceAfter=0.3)
    s["cell_hdr"] = ParagraphStyle("cell_hdr", fontName="Sans-Bold", fontSize=7.5, leading=9.8, textColor=colors.white, alignment=TA_LEFT)
    s["cell_hdr_c"] = ParagraphStyle("cell_hdr_c", fontName="Sans-Bold", fontSize=7.5, leading=9.8, textColor=colors.white, alignment=TA_CENTER)
    s["cell"] = ParagraphStyle("cell", fontName="STIX", fontSize=8.1, leading=10.9, textColor=C_BODY, alignment=TA_LEFT)
    s["cell_c"] = ParagraphStyle("cell_c", fontName="STIX", fontSize=8.1, leading=10.9, textColor=C_BODY, alignment=TA_CENTER)
    s["cell_sm_hdr"] = ParagraphStyle("cell_sm_hdr", fontName="Sans-Bold", fontSize=6.3, leading=8.2, textColor=colors.white, alignment=TA_CENTER)
    s["cell_sm"] = ParagraphStyle("cell_sm", fontName="STIX", fontSize=6.6, leading=8.6, textColor=C_BODY, alignment=TA_CENTER)
    s["cell_sm_l"] = ParagraphStyle("cell_sm_l", fontName="STIX", fontSize=6.6, leading=8.6, textColor=C_BODY, alignment=TA_LEFT)
    return s


def scaled_image(path: Path, max_w: float, max_h: float) -> Image:
    with PILImage.open(path) as im:
        iw, ih = im.size
    ratio = min(max_w / iw, max_h / ih)
    return Image(str(path), width=iw * ratio, height=ih * ratio)


def make_callout(paragraphs, bg=C_CREAM, border_color=C_ACCENT):
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


def make_figure_block(img_path: Path, caption: str, styles, max_h: float = 4.2 * inch):
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


def split_md_table_row(line: str) -> list[str]:
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|") and not s.endswith(r"\|"):
        s = s[:-1]
    return [c.strip() for c in re.split(r"(?<!\\)\|", s)]


def build_styled_table(headers, rows, alignments, styles, accent_color=C_ACCENT):
    ncols = len(headers)
    is_dense = False
    if ncols == 5:
        if "Physical Scale" in headers[1]:
            weights = [1.20, 0.70, 2.02, 1.00, 1.10]
        else:
            # Table 3 (Schema v3 forensic diff)
            weights = [1.45, 0.90, 0.90, 0.95, 1.55]
    elif ncols == 4:
        if "Falsified Node" in headers[0]:
            weights = [0.75, 0.72, 1.75, 1.85]
        else:
            # Table 4 (Five-fold inversion)
            weights = [0.85, 1.65, 1.65, 0.95]
    elif ncols == 3:
        if "Date / Stratum" in headers[0]:
            weights = [1.12, 2.38, 1.62]
            is_dense = True
        else:
            # Table 5 (Intentional vs Forced)
            weights = [1.32, 1.24, 2.44]
            is_dense = True
    else:
        weights = [1.0] * ncols

    tot_w = sum(weights)
    col_widths = [USABLE_W * (w / tot_w) for w in weights]
    code_sz = 6.5 if is_dense else 6.8
    pad_y = 2.9 if is_dense else 3.8
    cell_st_l = ParagraphStyle("c_dl", parent=styles["cell"], fontSize=7.5, leading=10.0) if is_dense else styles["cell"]
    cell_st_c = ParagraphStyle("c_dc", parent=styles["cell_c"], fontSize=7.5, leading=10.0) if is_dense else styles["cell_c"]

    data = []
    hdr_row = []
    for j, h in enumerate(headers):
        al = alignments[j] if j < len(alignments) else "L"
        st = styles["cell_hdr_c"] if al == "C" else styles["cell_hdr"]
        hdr_row.append(Paragraph(md_inline_to_rl(h, code_size=code_sz, code_color="#FFFFFF"), st))
    data.append(hdr_row)

    for r in rows:
        row_cells = []
        for j in range(ncols):
            val = r[j] if j < len(r) else ""
            al = alignments[j] if j < len(alignments) else "L"
            st = cell_st_c if al == "C" else cell_st_l
            row_cells.append(Paragraph(md_inline_to_rl(val, code_size=code_sz), st))
        data.append(row_cells)

    tbl = Table(data, colWidths=col_widths, repeatRows=1)
    style_cmds = [
        ("BACKGROUND", (0, 0), (-1, 0), accent_color),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 0), (-1, 0), 1.0, accent_color),
        ("LINEBELOW", (0, -1), (-1, -1), 0.9, C_INK),
        ("LINEBELOW", (0, 1), (-1, -2), 0.35, C_RULE),
        ("LEFTPADDING", (0, 0), (-1, -1), 4.5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4.5),
        ("TOPPADDING", (0, 0), (-1, -1), pad_y),
        ("BOTTOMPADDING", (0, 0), (-1, -1), pad_y),
    ]
    for i in range(1, len(data)):
        if i % 2 == 0:
            style_cmds.append(("BACKGROUND", (0, i), (-1, i), C_ROW_ALT))
    tbl.setStyle(TableStyle(style_cmds))
    return tbl


def parse_history_markdown(md_path: Path, styles, inject_after_h3=None, inject_after_table=None):
    inject_after_h3 = inject_after_h3 or {}
    inject_after_table = inject_after_table or {}
    lines = md_path.read_text(encoding="utf-8").splitlines()
    flowables = []
    current_h3 = None
    pending_table_cap = None
    table_count = 0
    i = 0
    n = len(lines)

    def maybe_inject_h3(h3):
        if h3 and h3 in inject_after_h3:
            flowables.extend(inject_after_h3.pop(h3))

    while i < n:
        raw = lines[i]
        stripped = raw.strip()

        if not stripped:
            i += 1
            continue
        if stripped.startswith("# ") and not stripped.startswith("## "):
            i += 1
            continue
        if i < 6 and stripped.startswith("*Companion Historiographical Volume"):
            i += 1
            continue

        if stripped == "---":
            maybe_inject_h3(current_h3)
            current_h3 = None
            flowables.append(Spacer(1, 3))
            flowables.append(HRFlowable(width="100%", thickness=0.5, color=C_RULE, spaceBefore=2, spaceAfter=5))
            i += 1
            continue

        if stripped.startswith("## "):
            maybe_inject_h3(current_h3)
            current_h3 = None
            title = stripped[3:].strip()
            # Clean running header label for major chapters
            short_hdr = title.split("(", 1)[0].strip()
            if len(short_hdr) > 54:
                short_hdr = short_hdr[:51] + "\u2026"
            if title.startswith("Chapter ") or title.startswith("Appendix:"):
                flowables.append(SectionBannerTracker(short_hdr))
                flowables.append(PageBreak())
            else:
                flowables.append(SectionBannerTracker(short_hdr))
            bm_key = f"h2_{i}"
            clean_toc = title.replace("`", "").replace("*", "")
            # Strip trailing long parenthetical date clauses from Chapter headings in TOC so every
            # Chapter line fits cleanly on 1 line with zero wrapped/orphaned leader-dot lines.
            if clean_toc.startswith("Chapter ") and " (" in clean_toc:
                clean_toc = clean_toc.rsplit(" (", 1)[0].strip()
            flowables.append(BookmarkAnchor(clean_toc, level=0, key=bm_key, in_toc=True))
            flowables.append(Paragraph(md_inline_to_rl(title, code_size=9.4), styles["h2"]))
            i += 1
            continue

        if stripped.startswith("### "):
            maybe_inject_h3(current_h3)
            title = stripped[4:].strip()
            current_h3 = title
            bm_key = f"h3_{i}"
            clean_toc = title.replace("`", "").replace("*", "")
            flowables.append(BookmarkAnchor(clean_toc, level=1, key=bm_key, in_toc=True))
            # Don't force keepWithNext on A.1 before the 12-row chronology table so the table starts immediately on the Appendix page!
            h3_st = ParagraphStyle("h3_no_kwn", parent=styles["h3"], keepWithNext=False) if title.startswith("A.1 ") else styles["h3"]
            flowables.append(Paragraph(md_inline_to_rl(title, code_size=8.6), h3_st))
            i += 1
            continue

        if stripped.startswith("*Table ") and stripped.endswith("*"):
            pending_table_cap = Paragraph(md_inline_to_rl(stripped, code_size=7.9), styles["table_cap"])
            i += 1
            continue

        if stripped.startswith("|") and i + 1 < n and lines[i + 1].strip().startswith("|") and "---" in lines[i + 1]:
            hdr_cells = split_md_table_row(stripped)
            align_raw = split_md_table_row(lines[i + 1])
            alignments = ["C" if (a.startswith(":") and a.endswith(":")) else ("R" if a.endswith(":") else "L") for a in align_raw]
            i += 2
            rows = []
            while i < n and lines[i].strip().startswith("|"):
                rows.append(split_md_table_row(lines[i]))
                i += 1
            table_count += 1
            tbl = build_styled_table(hdr_cells, rows, alignments, styles, accent_color=C_ACCENT if table_count != 3 else C_NAVY)
            block = []
            if pending_table_cap is not None:
                block.append(pending_table_cap)
                pending_table_cap = None
            block.append(tbl)
            block.append(Spacer(1, 6))
            if len(rows) <= 9:
                flowables.append(KeepTogether(block))
            else:
                flowables.extend(block)
            if table_count in inject_after_table:
                flowables.extend(inject_after_table.pop(table_count))
            continue

        if pending_table_cap is not None:
            flowables.append(pending_table_cap)
            pending_table_cap = None

        if stripped.startswith("> "):
            q_lines = []
            while i < n and lines[i].strip().startswith(">"):
                q_lines.append(lines[i].strip().lstrip(">").strip())
                i += 1
            q_p = Paragraph(md_inline_to_rl(" ".join(q_lines), code_size=8.2), styles["quote"])
            flowables.append(Spacer(1, 2))
            flowables.append(make_callout([q_p], bg=C_ACCENT_TINT, border_color=C_ACCENT))
            flowables.append(Spacer(1, 6))
            continue

        if re.match(r"^(\s*)[-*]\s+", raw):
            m = re.match(r"^(\s*)[-*]\s+(.*)$", raw)
            content = m.group(2).strip()
            flowables.append(Paragraph(f"\u2022&nbsp;&nbsp;{md_inline_to_rl(content, code_size=8.1)}", styles["bullet"]))
            i += 1
            continue

        if re.match(r"^\d+\.\s+", stripped):
            m = re.match(r"^(\d+\.)\s+(.*)$", stripped)
            flowables.append(Paragraph(f"<b>{m.group(1)}</b>&nbsp;&nbsp;{md_inline_to_rl(m.group(2).strip(), code_size=8.1)}", styles["bullet"]))
            i += 1
            continue

        para_lines = [stripped]
        i += 1
        while i < n:
            nxt = lines[i].strip()
            if (not nxt or nxt.startswith("#") or nxt == "---" or nxt.startswith("|")
                    or nxt.startswith(">") or (nxt.startswith("*Table ") and nxt.endswith("*"))
                    or re.match(r"^(\s*)[-*]\s+", lines[i]) or re.match(r"^\d+\.\s+", nxt)):
                break
            para_lines.append(nxt)
            i += 1
        flowables.append(Paragraph(md_inline_to_rl(" ".join(para_lines), code_size=8.1), styles["body"]))

    maybe_inject_h3(current_h3)
    return flowables


def build_volume():
    register_fonts()
    styles = build_styles()

    plate_leiden = ASSETS / "plate_vol2_leiden_library_1610.jpg"
    fig1 = ASSETS / "hist_fig1_longitudinal_timeline.png"
    fig2 = ASSETS / "hist_fig2_epistemic_tier_audit.png"
    j_arch = ROOT / "data" / "archive_ro_forensics.json"
    j_loc = ROOT / "data" / "local_corpus_forensics.json"

    vol1_pages = 52
    try:
        import pymupdf
        with pymupdf.open(str(VOL1_PDF)) as v1_doc:
            vol1_pages = len(v1_doc)
    except Exception:
        pass
    vol1_bytes = VOL1_PDF.stat().st_size

    manifest_items = [
        ("Volume II Source Manuscript", "chapters/corpus_history_companion_volume.md", SRC_MD),
        (f"Companion Volume I ({vol1_pages} pp.)", "output/two_hands_decentralized_whitepaper.pdf", VOL1_PDF),
        ("Read-Only Archive Forensics", "data/archive_ro_forensics.json", j_arch),
        ("Read-Only Local Kernel Forensics", "data/local_corpus_forensics.json", j_loc),
        ("Title Plate (Leiden Library, 1610)", "output/whitepaper_assets/plate_vol2_leiden_library_1610.jpg", plate_leiden),
        ("Figure 1 (Longitudinal History)", "output/whitepaper_assets/hist_fig1_longitudinal_timeline.png", fig1),
        ("Figure 2 (Epistemic Tier Audit)", "output/whitepaper_assets/hist_fig2_epistemic_tier_audit.png", fig2),
    ]
    hashes = {rel: sha256_file(path) for _, rel, path in manifest_items}
    build_date_str = "November 21, 2026"
    build_iso = "2026-11-21"

    story = []

    # =========================================================================
    # 1. COVER / TITLE PAGE & CROSS-VOLUME COLOPHON
    # =========================================================================
    story.append(Spacer(1, 0.08 * inch))
    story.append(Paragraph("COMPANION VOLUME II  \u00b7  MATERIAL &amp; INTELLECTUAL HISTORIOGRAPHY", styles["kicker"]))
    story.append(Spacer(1, 0.38 * inch))
    story.append(Paragraph("The Age of Overkill and the Grounded Wire", styles["cover_title"]))
    story.append(Paragraph(
        "A Material and Intellectual History of the Corpus (2025\u20132026) and a Forensic Assessment "
        "of Teleology vs. Contingency in <i>Two Hands in a Local Box</i>",
        styles["cover_sub"],
    ))
    story.append(HRFlowable(width="100%", thickness=1.2, color=C_ACCENT, spaceBefore=2, spaceAfter=14))

    cover_blurb = Paragraph(
        "Written in the anti-Whig materialist historiographical tradition of Eric Hobsbawm, this companion volume "
        "reconstructs how physical scarcity\u2014a 189.57 GB recursive disk catastrophe, HTTP 429 cloud rate limits, "
        "31.45-million-token swarm bills, 8 GB consumer silicon, and two separate outbreaks of self-certifying "
        "\"verifier theater\"\u2014actively reshaped a speculative late-2025 grand-unification archive into a bounded, "
        "defeasible, anti-oracle local SQLite ledger.",
        ParagraphStyle("cb2", parent=styles["body"], fontSize=10.4, leading=15.0),
    )
    story.append(make_callout([cover_blurb], bg=C_CREAM, border_color=C_ACCENT))
    story.append(Spacer(1, 0.24 * inch))

    era_rows = [
        [Paragraph("<b>Era I (Late 2025\u2013Early 2026)</b>", styles["cell"]),
         Paragraph("<i>The Age of Speculative Sprawl &amp; Grand Unification</i> \u2014 AuDHD/PDA schematics, 638k-word megathreads, <i>Genesis Body</i>, and Pi numerology.", styles["cell"])],
        [Paragraph("<b>Era II (Mid\u2013Oct 26\u201327, 2026)</b>", styles["cell"]),
         Paragraph("<i>System-Building, Archival Harvest &amp; Overkill</i> \u2014 Playwright/CDP harvest (342 threads, 2.16M verbatim words), 189.57 GB hypergraph bloat, and HTTP 429 walls.", styles["cell"])],
        [Paragraph("<b>Era III (Oct 26\u201331 Codex \u2192 Nov 16\u201318)</b>", styles["cell"]),
         Paragraph("<i>The Codex Grounding Turn &amp; Falsification Sprint</i> \u2014 \"Ground the wire\", 644\u00d7 CAS collapse, 893 compiled nodes, 267 falsified pivots, and 174\u00d7 single-loop compression.", styles["cell"])],
        [Paragraph("<b>Era IV (Nov 11\u201320, 2026)</b>", styles["cell"]),
         Paragraph("<i>Self-Audit Crucible, Live DOI Remediation &amp; Two-Hands Consolidation</i> \u2014 Schema v3 self-demotion, live verification of 1,122 atomic nodes (0 open flags), Kestrel-7 knee, and teleology verdict.", styles["cell"])],
    ]
    era_tbl = Table(era_rows, colWidths=[1.92 * inch, USABLE_W - 1.92 * inch])
    era_tbl.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEABOVE", (0, 0), (-1, 0), 0.7, C_ACCENT),
        ("LINEBELOW", (0, 0), (-1, -2), 0.35, C_RULE),
        ("LINEBELOW", (0, -1), (-1, -1), 0.7, C_ACCENT),
        ("TOPPADDING", (0, 0), (-1, -1), 5.0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5.0),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(era_tbl)
    story.append(Spacer(1, 0.34 * inch))

    story.append(Paragraph("COLOPHON &amp; CROSS-VOLUME CRYPTOGRAPHIC ANCHORS (SHA-256)",
                           ParagraphStyle("ch2", fontName="Sans-Bold", fontSize=7.4, leading=10, textColor=C_MUTED, spaceAfter=5)))
    col_data = [
        [Paragraph("<b>Compilation / Provenance</b>", styles["cell_sm_l"]),
         Paragraph("Open archival synthesis \u00b7 CC BY 4.0 \u00b7 Official deposit provenance in CITATION.cff / Zenodo DOI", styles["cell_sm_l"])],
        [Paragraph("<b>Companion Edition</b>", styles["cell_sm_l"]),
         Paragraph(f"Volume II (Historiographical Audit \u00b7 Rev. 3 Sync Edition) \u00b7 {build_date_str} ({build_iso}) \u00b7 Read-Only Primary Extraction (?mode=ro)", styles["cell_sm_l"])],
        [Paragraph("<b>Volume I Anchor</b>", styles["cell_sm_l"]),
         Paragraph(f'<font name="Mono" size="6.0">{hashes["output/two_hands_decentralized_whitepaper.pdf"]}</font>  ({vol1_pages} pp., {vol1_bytes:,} bytes)', styles["cell_sm_l"])],
        [Paragraph("<b>Volume II Source</b>", styles["cell_sm_l"]),
         Paragraph(f'<font name="Mono" size="6.2">{hashes["chapters/corpus_history_companion_volume.md"]}</font>  (corpus_history_companion_volume.md)', styles["cell_sm_l"])],
        [Paragraph("<b>Forensic Snapshots</b>", styles["cell_sm_l"]),
         Paragraph(f'<font name="Mono" size="6.2">{hashes["data/archive_ro_forensics.json"][:24]}\u2026</font> (archive_ro) \u00b7 '
                   f'<font name="Mono" size="6.2">{hashes["data/local_corpus_forensics.json"][:24]}\u2026</font> (local_corpus)', styles["cell_sm_l"])],
        [Paragraph("<b>Verify Container</b>", styles["cell_sm_l"]),
         Paragraph('<font name="Mono" size="6.2">cd output &amp;&amp; shasum -a 256 -c corpus_history_companion_volume.pdf.sha256</font>', styles["cell_sm_l"])],
    ]
    col_tbl = Table(col_data, colWidths=[1.30 * inch, USABLE_W - 1.30 * inch])
    col_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), C_ROW_ALT),
        ("BOX", (0, 0), (-1, -1), 0.5, C_RULE),
        ("LINEBELOW", (0, 0), (-1, -2), 0.3, C_RULE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 3.6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3.6),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(col_tbl)

    # =========================================================================
    # 2. ARCHIVAL TITLE PLATE PAGE (LEIDEN UNIVERSITY LIBRARY, 1610)
    # =========================================================================
    story.append(SectionBannerTracker("Frontispiece Plate"))
    story.append(NextPageTemplate("TitlePlate"))
    story.append(PageBreak())
    story.append(BookmarkAnchor("Frontispiece Plate: Leiden University Library (1610)", level=0, key="plate_leiden", in_toc=False))

    story.append(Spacer(1, 0.20 * inch))
    story.append(Paragraph("FRONTISPIECE ARCHIVAL PLATE  \u00b7  COMPANION VOLUME II", styles["plate_kicker"]))
    story.append(Paragraph("The Chained Ledger and the Disciplinary Shelf", styles["plate_title"]))
    story.append(Paragraph("From Unbounded Sprawl to Indexed Provenance", styles["plate_sub"]))
    story.append(HRFlowable(width="34%", thickness=1.1, color=C_ACCENT, hAlign="CENTER", spaceBefore=2, spaceAfter=16))

    img_l = scaled_image(plate_leiden, USABLE_W - 0.20 * inch, 5.15 * inch)
    mat = Table([[img_l]], colWidths=[img_l.drawWidth + 14])
    mat.setStyle(TableStyle([
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("BACKGROUND", (0, 0), (-1, -1), C_CREAM),
        ("BOX", (0, 0), (-1, -1), 0.75, C_RULE_DARK),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ("LEFTPADDING", (0, 0), (-1, -1), 7),
        ("RIGHTPADDING", (0, 0), (-1, -1), 7),
    ]))
    story.append(mat)
    story.append(Paragraph(md_inline_to_rl(
        "**Frontispiece Plate.** Willem van Swanenburg after Jan Cornelisz. van 't Woudt (Woudanus), "
        "*Bibliothecae Lugduno-Batavae cum Pulpitis et Arcis Vera Ixnographia* (Leiden University Library, 1610; "
        "hand-colored impression from Willem Blaeu's *Stedeboeck der Nederlanden*, 1649; Public Domain via Wikimedia Commons). "
        "Chained reference folios arranged across disciplined faculty shelves (*Mathematici, Philosophi, Literatores, Theologi, "
        "Historici, Medici, Iurisconsulti*) prefigure the central historical transition traced in this volume: turning an "
        "unruly, unbounded accumulation of private transcripts into a bounded, auditable, public-facing index.",
        code_size=7.6,
    ), styles["plate_cap"]))

    # =========================================================================
    # 3. TABLE OF CONTENTS (2-Pass Exact Page Numbers)
    # =========================================================================
    story.append(SectionBannerTracker("Contents"))
    story.append(NextPageTemplate("Body"))
    story.append(PageBreak())
    story.append(BookmarkAnchor("Contents", level=0, key="toc_vol2", in_toc=False))
    story.append(Paragraph("Contents", styles["h1"]))
    story.append(HRFlowable(width="100%", thickness=0.8, color=C_ACCENT, spaceBefore=2, spaceAfter=8))

    toc = TableOfContents()
    toc.dotsMinLevel = 0
    toc.levelStyles = [styles["toc0"], styles["toc1"]]
    story.append(toc)

    story.append(Spacer(1, 0.24 * inch))
    story.append(Paragraph("Plates &amp; Quantitative Figures", styles["h2"]))
    fig_list = [
        ("<b>Frontispiece Plate</b>", "Willem van Swanenburg after Woudanus, <i>Leiden University Library</i> (1610 / Blaeu 1649, Public Domain)"),
        ("<b>Figure 1</b>", "Longitudinal Material History of the Corpus: Conversational Stratigraphy (342 Threads, 2.16M Verbatim Words) &amp; the 26-Day 189.57 GB Overkill-to-SQLite Crucible (Chapter 2, \u00a72.3)"),
        ("<b>Figure 2</b>", "The Self-Audit &amp; Live Remediation Arc: Pre-Audit v0.2.0 (893) \u2192 Schema v3 Demotion (893) \u2192 Post-Part-1 Live DOI Ledger (1,122 Nodes, 0 Open Flags) (Chapter 4, \u00a74.2)"),
    ]
    for lbl, desc in fig_list:
        story.append(Paragraph(f"{lbl} \u2014 {desc}", styles["bullet_compact"]))

    # =========================================================================
    # 4. COMPLETE HISTORIOGRAPHICAL MONOGRAPH (+ Embedded Figures 1 & 2)
    # =========================================================================
    story.append(SectionBannerTracker("Abstract & Prologue"))
    story.append(PageBreak())

    inject_h3 = {
        "2.3 The Material Counter-Revolution: `overkill_migrate.py` (`644×` Collapse)": [
            make_figure_block(
                fig1,
                "**Figure 1.** Direct read-only primary reconstruction from `archive.db` (`342` conversations, `8,922` turns, `2.16M` verbatim words / `16.83M` cleaned chars, `166,915` `file_trail` records) "
                "and `data/corpus.db`. Panel A charts conversational stratigraphy from oldest pre-history through *Genesis Body* (`2025-12-16`) and the November 11\u201315 "
                "reckoning; Panel B plots the October 27 **`186.30 GB`** single-day Overkill spike collapsing `644\u00d7` via `overkill_migrate.py` (`294.3 MB` CAS) into the `77.1 MB` local kernel.",
                styles,
                max_h=4.15 * inch,
            ),
        ],
    }
    inject_tbl = {
        3: [
            make_figure_block(
                fig2,
                "**Figure 2.** Three-stage read-only forensic evolution across `corpus.db.bak.20261119_pre_v3` (`v0.2.0`, `893` nodes), `corpus.db.bak.20261120_152209` (`Schema v3`, `893` nodes / `539` flags), "
                "and live remediated `data/corpus.db` (`1,122` atomic nodes, `537` EV, `382` FALSIFIED, `163` RAW, `28` CONTESTED, `12` SIM, `0/539` open flags). "
                "Panel B contrasts initial `v3` collapse against live HTTP-200 primary DOI/URL recovery (`97.9%` in Formal Math, `94.7%` in Physics, `90.4%` in Bio/Neuro, `79.6%` in AI Systems).",
                styles,
                max_h=2.95 * inch,
            ),
        ],
    }

    story.extend(parse_history_markdown(SRC_MD, styles, inject_after_h3=inject_h3, inject_after_table=inject_tbl))

    # =========================================================================
    # 5. CLOSING CRYPTOGRAPHIC INTEGRITY MANIFEST & ARCHIVAL CREDITS
    # =========================================================================
    story.append(SectionBannerTracker("Cryptographic Integrity Manifest"))
    story.append(PageBreak())
    story.append(BookmarkAnchor("Cryptographic Integrity Manifest & Archival Credits", level=0, key="manifest_vol2", in_toc=True))
    story.append(Paragraph("Cryptographic Integrity Manifest &amp; Archival Credits", styles["h1"]))
    story.append(HRFlowable(width="100%", thickness=0.8, color=C_ACCENT, spaceBefore=1, spaceAfter=7))

    story.append(Paragraph(
        f"This standalone Companion Volume II PDF was compiled deterministically on <b>{build_date_str}</b> ({build_iso}) "
        "from read-only primary archival audits of Desktop <font name=\"Mono\" size=\"8.0\" color=\"#1E3A5F\">archive.db</font> "
        "and workspace <font name=\"Mono\" size=\"8.0\" color=\"#1E3A5F\">data/corpus.db</font>. It cross-anchors the exact "
        f"SHA-256 digest of Volume I (<font name=\"Mono\" size=\"8.0\" color=\"#1E3A5F\">two_hands_decentralized_whitepaper.pdf</font>, "
        f"<b>{vol1_pages} pages</b>, <b>{vol1_bytes:,} bytes</b>) so both volumes form a verified, tamper-evident pair. Verify this container via:",
        ParagraphStyle("m2_i", parent=styles["body"], fontSize=9.3, leading=13.2, spaceAfter=5),
    ))
    cmd_box = Paragraph(
        '<font name="Mono" size="8.0" color="#1E3A5F">cd output &amp;&amp; shasum -a 256 -c corpus_history_companion_volume.pdf.sha256</font>',
        ParagraphStyle("cmd2", parent=styles["body_left"], spaceAfter=0),
    )
    story.append(make_callout([cmd_box], bg=C_CODE_BG, border_color=C_ACCENT))
    story.append(Spacer(1, 8))

    m_data = [[
        Paragraph("<b>Artifact Role</b>", styles["cell_sm_hdr"]),
        Paragraph("<b>Relative Path</b>", styles["cell_sm_hdr"]),
        Paragraph("<b>Size</b>", styles["cell_sm_hdr"]),
        Paragraph("<b>SHA-256 Digest</b>", styles["cell_sm_hdr"]),
    ]]
    for role, rel, path in manifest_items:
        sz_kb = path.stat().st_size / 1024.0
        m_data.append([
            Paragraph(html.escape(role), styles["cell_sm_l"]),
            Paragraph(f'<font name="Mono" size="5.6">{html.escape(rel)}</font>', styles["cell_sm_l"]),
            Paragraph(f"{sz_kb:,.1f} KB", styles["cell_sm"]),
            Paragraph(f'<font name="Mono" size="5.4">{hashes[rel]}</font>', styles["cell_sm_l"]),
        ])
    m_tbl = Table(m_data, colWidths=[1.36 * inch, 1.72 * inch, 0.56 * inch, USABLE_W - 3.64 * inch], repeatRows=1)
    m_style = [
        ("BACKGROUND", (0, 0), (-1, 0), C_ACCENT),
        ("LINEBELOW", (0, 0), (-1, 0), 0.9, C_ACCENT),
        ("LINEBELOW", (0, -1), (-1, -1), 0.9, C_INK),
        ("LINEBELOW", (0, 1), (-1, -2), 0.35, C_RULE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 3.8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3.8),
        ("TOPPADDING", (0, 0), (-1, -1), 3.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5),
    ]
    for idx in range(1, len(m_data)):
        if idx % 2 == 0:
            m_style.append(("BACKGROUND", (0, idx), (-1, idx), C_ROW_ALT))
    m_tbl.setStyle(TableStyle(m_style))
    story.append(m_tbl)
    story.append(Spacer(1, 12))

    story.append(Paragraph("Archival Plate &amp; Quantitative Provenance Credits",
                           ParagraphStyle("h2_m2", parent=styles["h2"], fontSize=11.4, spaceBefore=4, spaceAfter=4)))
    credits = [
        ("Frontispiece Plate (Leiden University Library, 1610):",
         "Willem van Swanenburg after Jan Cornelisz. van 't Woudt (Woudanus), *Bibliothecae Lugduno-Batavae cum Pulpitis et Arcis "
         "Vera Ixnographia* (Leiden, 1610; Blaeu *Stedeboeck* hand-colored edition, 1649). Public Domain (PD-old-100) via Wikimedia "
         "Commons (`File:Leiden_1610.jpg`)."),
        ("Quantitative Figures 1 & 2:",
         "Generated reproducibly at 300 DPI via `scripts/generate_history_figures.py` strictly from read-only forensic extractions "
         "of Desktop `archive.db` (`?mode=ro`), `data/corpus.db.bak.20261119_pre_v3` (`?mode=ro`), and `data/corpus.db` (`?mode=ro`)."),
        ("Companion Container Pairing:",
         "Designed as a matched typographic twin to Volume I (`output/two_hands_decentralized_whitepaper.pdf`) using embedded STIX General, "
         "DejaVu Sans, and DejaVu Sans Mono TrueType fonts, 2-pass exact pagination, and hierarchical PDF outline bookmarks."),
    ]
    for c_hdr, c_txt in credits:
        story.append(Paragraph(f"\u2022&nbsp;&nbsp;<b>{html.escape(c_hdr)}</b> {md_inline_to_rl(c_txt, code_size=7.4)}", styles["bullet_compact"]))

    doc = HistoryVolumeDocTemplate(
        str(OUT_PDF),
        pagesize=letter,
        leftMargin=M_LEFT,
        rightMargin=M_RIGHT,
        topMargin=M_TOP,
        bottomMargin=M_BOTTOM,
        title="The Age of Overkill and the Grounded Wire: A Material and Intellectual History of the Corpus (2025-2026)",
        author="McDonald, Henry Oscar Arthur (Compiler)",
        subject="Material & Intellectual History of the Corpus and Forensic Teleology Verdict",
        creator="scripts/build_history_volume_pdf.py (ReportLab 5.1)",
    )
    doc.multiBuild(story)

    pdf_sha = sha256_file(OUT_PDF)
    OUT_SHA.write_text(f"{pdf_sha}  {OUT_PDF.name}\n", encoding="utf-8")
    print(f"BUILT VOLUME II PDF: {OUT_PDF} ({OUT_PDF.stat().st_size:,} bytes)")
    print(f"PDF SHA-256: {pdf_sha}")
    print(f"WROTE CHECKSUM: {OUT_SHA}")


if __name__ == "__main__":
    build_volume()
