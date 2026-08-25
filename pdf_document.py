"""Compose and write out/SPPI_CFPB_Complaint_Templating.pdf.

    python pdf_document.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from reportlab.lib.units import inch  # noqa: E402
from reportlab.pdfgen import canvas as rl_canvas  # noqa: E402
from reportlab.platypus import (BaseDocTemplate, Frame, Image, KeepTogether,  # noqa: E402
                                ListFlowable, ListItem, PageTemplate,
                                Paragraph, Spacer, Table, TableStyle)

import build_pdf as G  # noqa: E402
import sppi_brand as B  # noqa: E402
from build_pdf import FINDINGS, FOLLOWUPS, PLACEBO  # noqa: E402

OUT = G.OUT
ART = B.BRAND_DIR
PDF_PATH = OUT / "SPPI_CFPB_Complaint_Templating.pdf"
# Intermediates go to local cache, not the shared drive: Drive File Stream
# holds locks on recently written files and re-syncs every scratch artefact.
from cfpb_inspect import config as _cfg  # noqa: E402
TMP = _cfg.CACHE_DIR
ISSUE_DATE = "August 2026"

S = None  # styles, set in main()


# ---------------------------------------------------------------------------
# cover
# ---------------------------------------------------------------------------

def draw_cover(path: Path, art: Path) -> Path:
    c = rl_canvas.Canvas(str(path), pagesize=(B.PAGE_W, B.PAGE_H))
    c.drawImage(str(art), 0, 0, B.PAGE_W, B.PAGE_H,
                preserveAspectRatio=False, mask=None)
    c.drawImage(str(ART / "sppi_logo.png"), B.COVER_M, B.PAGE_H - 72 - 83,
                83, 83, mask="auto")

    c.setFillColorRGB(1, 1, 1)
    c.setFont("Minion-Bold", 10)
    c.drawRightString(B.PAGE_W - B.COVER_M, B.PAGE_H - 118, G.ISSUE)

    c.setFont("Minion-Bold", 30)
    c.drawString(B.COVER_M, B.PAGE_H - 239, G.TITLE)

    c.setFont("Minion-Bold", 18)
    wrap_at = B.PAGE_W - 2 * B.COVER_M
    words, line, lines = G.SUBTITLE.split(), "", []
    from reportlab.pdfbase.pdfmetrics import stringWidth
    for w in words:
        t = (line + " " + w).strip()
        if stringWidth(t, "Minion-Bold", 18) > wrap_at:
            lines.append(line); line = w
        else:
            line = t
    lines.append(line)
    y = B.PAGE_H - 281
    for ln in lines:
        c.drawString(B.COVER_M, y, ln)
        y -= 21.6

    c.setFont("Minion-BoldIt", 18)
    c.drawString(B.COVER_M, y - 22, G.AUTHORS)

    # centred pull quote
    c.setFont("Minion-It", 12)
    qw = 340
    words, line, qlines = G.QUOTE.split(), "", []
    for w in words:
        t = (line + " " + w).strip()
        if stringWidth(t, "Minion-It", 12) > qw:
            qlines.append(line); line = w
        else:
            line = t
    qlines.append(line)
    qy = 320
    for ln in qlines:
        c.drawCentredString(B.PAGE_W / 2, qy, ln)
        qy -= 14.4
    c.setFont("Minion-Bold", 12)
    c.drawCentredString(B.PAGE_W / 2, qy - 10, G.QUOTE_ATTR)

    c.setStrokeColorRGB(1, 1, 1)
    c.setLineWidth(0.7)
    c.line(B.COVER_M, 152, B.PAGE_W - B.COVER_M, 152)

    c.setFont("Minion", 10)
    c.drawCentredString(B.PAGE_W / 2, 131, G.SHORTURL)
    c.drawCentredString(B.PAGE_W / 2, 107,
                        "202.505.1769  |  southwestpolicy.com  |  info@southwestpolicy.com")
    c.drawCentredString(B.PAGE_W / 2, 95,
                        "PO Box 1746  |  Bernalillo, New Mexico 87004")
    c.setFont("Minion-Bold", 10)
    c.drawCentredString(B.PAGE_W / 2, 71,
                        "Southwest Public Policy Institute  |  Better living through better policy")
    c.showPage()
    c.save()
    return path


# ---------------------------------------------------------------------------
# body furniture
# ---------------------------------------------------------------------------

class Doc(BaseDocTemplate):
    def __init__(self, path, **kw):
        super().__init__(str(path), pagesize=(B.PAGE_W, B.PAGE_H),
                         leftMargin=B.BODY_L, rightMargin=B.BODY_R,
                         topMargin=100, bottomMargin=B.BODY_BOTTOM, **kw)
        frame = Frame(B.BODY_L, B.BODY_BOTTOM, B.BODY_W,
                      B.PAGE_H - 100 - B.BODY_BOTTOM, id="body",
                      leftPadding=0, rightPadding=0,
                      topPadding=0, bottomPadding=0)
        self.addPageTemplates([PageTemplate(id="body", frames=[frame],
                                            onPage=self._furniture)])

    def _furniture(self, c, doc):
        n = doc.page + 1  # cover is page 1 and is merged in separately
        c.saveState()
        c.setStrokeColor(B.RULE)
        c.setLineWidth(0.6)
        c.line(B.COVER_M, B.FOOTER_RULE_Y, B.PAGE_W - B.COVER_M, B.FOOTER_RULE_Y)
        c.setFont("Minion", 10)
        c.setFillColor(B.INK)
        c.drawString(B.COVER_M, B.FOOTER_TEXT_Y, f"{n}  |  {ISSUE_DATE}")
        c.drawRightString(B.PAGE_W - B.COVER_M, B.FOOTER_TEXT_Y,
                          "southwestpolicy.com")
        c.restoreState()


def P(text, style="body"):
    return Paragraph(text, S[style])


def H(text):
    return Paragraph(text.upper(), S["head"])


def SH(text):
    return Paragraph(text, S["sub"])


def bullets(items, numbered=False):
    return ListFlowable(
        [ListItem(P(t, "num" if numbered else "bullet"), leftIndent=20)
         for t in items],
        bulletType="1" if numbered else "bullet",
        bulletFormat="%s." if numbered else None,
        bulletFontName="Minion", bulletFontSize=B.BODY_SIZE,
        leftIndent=20, start="1" if numbered else None,
    )


def table(head, rows, widths, align_right=(), size=9.5):
    # Alignment must be set on the Paragraph, not the cell: a TableStyle ALIGN
    # positions the flowable, which already fills the column, so numerals stay
    # left-aligned unless the paragraph style itself is right-aligned.
    def cell_style(col, header=False):
        if col in align_right:
            return S["tableheadr"] if header else S["tablecellr"]
        return S["tablehead"] if header else S["tablecell"]

    data = [[Paragraph(h, cell_style(i, True)) for i, h in enumerate(head)]]
    for r in rows:
        data.append([Paragraph(str(c), cell_style(i)) for i, c in enumerate(r)])
    t = Table(data, colWidths=widths, hAlign="LEFT", repeatRows=1)
    style = [
        ("FONT", (0, 0), (-1, -1), "Minion", size),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 0), (-1, 0), 0.6, B.INK),
        ("LINEBELOW", (0, 1), (-1, -2), 0.25, B.HexColor("#c8ccd0")),
        ("LINEBELOW", (0, -1), (-1, -1), 0.6, B.INK),
        ("TOPPADDING", (0, 0), (-1, -1), 3.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
    ]
    t.setStyle(TableStyle(style))
    # Keep a table whole only when it is genuinely compact. Forcing a tall
    # table onto the next page leaves a half-empty one behind, which is worse
    # than a clean split with a repeated header.
    longest = max((len(str(c)) for r in rows for c in r), default=0)
    compact = len(rows) <= 8 and longest <= 40
    return KeepTogether(t) if compact else t


def figure(img_path, caption, width=B.BODY_W):
    from PIL import Image as PILImage
    iw, ih = PILImage.open(img_path).size
    h = width * ih / iw
    return KeepTogether([Image(str(img_path), width, h),
                         P(caption, "caption")])
