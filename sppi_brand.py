"""SPPI house style for generated PDFs.

Specification reverse-engineered from
Collateral/Whitepapers/010 Bank Charters August 2026/SPPI Report Application Pending.pdf:

  page          US Letter, 612 x 792 pt
  cover         full-bleed image; navy SPPI mark 83pt square at (54, 72 from top);
                issue line 10pt semibold; title 30pt; subtitle 18pt; authors 18pt
                italic; centred pull quote 12pt italic; rule at y-from-top 640;
                URL / contact / tagline centred beneath
  body          text block x 108..504 (396pt measure), 12pt on ~14.5pt leading
  headings      ALL CAPS, 16pt
  footer        rule at y-from-top 700; "<page>  |  <month year>" left,
                "southwestpolicy.com" right, 10pt
  typeface      Minion Pro throughout

FONT NOTE. Minion Pro ships with Acrobat as CFF-flavoured OpenType, which
ReportLab cannot embed ("postscript outlines are not supported"). The faces are
therefore converted to quadratic TrueType once, into brand/, and registered from
there. The template also uses Semibold and SemiboldIt, which are not among the
faces Acrobat installs; Bold and BoldItalic stand in for them.
"""
from __future__ import annotations

from pathlib import Path

from reportlab.lib.colors import HexColor

BRAND_DIR = Path(__file__).resolve().parent / "brand"
BRAND_DIR.mkdir(exist_ok=True)

# --- palette, sampled from the template cover and the logo asset -----------
NAVY = HexColor("#002856")       # SPPI mark background
BLUE = HexColor("#345c8a")       # cover duotone midtone
BLUE_LT = HexColor("#8fb4d9")
PALE = HexColor("#eaf3ff")       # cover duotone highlight
INK = HexColor("#000000")
INK_75 = HexColor("#404040")     # template uses 75% black for secondary text
RULE = HexColor("#000000")

# --- page geometry ---------------------------------------------------------
PAGE_W, PAGE_H = 612.0, 792.0
BODY_L, BODY_R = 108.0, 108.0
BODY_W = PAGE_W - BODY_L - BODY_R          # 396pt
BODY_TOP = PAGE_H - 100.0                  # first baseline area
BODY_BOTTOM = 102.0
FOOTER_RULE_Y = PAGE_H - 700.0             # 92
FOOTER_TEXT_Y = 74.0
COVER_M = 54.0

BODY_SIZE = 12.0
BODY_LEAD = 14.6
HEAD_SIZE = 16.0

ACROBAT_FONTS = Path(r"C:\Program Files\Adobe\Acrobat DC\Resource\Font")
FACES = {
    "Minion": "MinionPro-Regular.otf",
    "Minion-It": "MinionPro-It.otf",
    "Minion-Bold": "MinionPro-Bold.otf",
    "Minion-BoldIt": "MinionPro-BoldIt.otf",
}


def _otf_to_ttf(src: Path, dst: Path, max_err: float = 1.0) -> None:
    """Convert a CFF OpenType face to quadratic TrueType.

    ReportLab embeds TrueType outlines only. This is the standard otf2ttf
    recipe: redraw every glyph through a cubic-to-quadratic pen into a new
    glyf table, drop CFF, and re-stamp the sfnt version.
    """
    from fontTools.pens.cu2quPen import Cu2QuPen
    from fontTools.pens.ttGlyphPen import TTGlyphPen
    from fontTools.ttLib import TTFont, newTable

    font = TTFont(str(src))
    if font.sfntVersion != "OTTO":
        font.save(str(dst))
        return

    glyph_set = font.getGlyphSet()
    quad = {}
    for name in font.getGlyphOrder():
        pen = TTGlyphPen(glyph_set)
        glyph_set[name].draw(Cu2QuPen(pen, max_err))
        quad[name] = pen.glyph()

    font["loca"] = newTable("loca")
    glyf = newTable("glyf")
    glyf.glyphOrder = font.getGlyphOrder()
    glyf.glyphs = quad
    font["glyf"] = glyf
    del font["CFF "]

    # A CFF font carries maxp v0.5, which has none of the TrueType hinting
    # fields. Promoting the version without seeding them makes compile() raise
    # KeyError: 'maxZones'. The glyph-derived maxima are filled by recalc.
    maxp = font["maxp"]
    maxp.tableVersion = 0x00010000
    for field, value in (
        ("maxZones", 1), ("maxTwilightPoints", 0), ("maxStorage", 0),
        ("maxFunctionDefs", 0), ("maxInstructionDefs", 0),
        ("maxStackElements", 0), ("maxSizeOfInstructions", 0),
        ("maxComponentElements", 0), ("maxComponentDepth", 0),
        ("maxPoints", 0), ("maxContours", 0),
        ("maxCompositePoints", 0), ("maxCompositeContours", 0),
    ):
        setattr(maxp, field, value)

    glyf.compile(font)
    maxp.recalc(font)
    if "post" in font:
        # Format 3.0 omits glyph names, which TrueType permits and ReportLab
        # does not need. Format 2.0 would require rebuilding extraNames.
        font["post"].formatType = 3.0
    font.sfntVersion = "\000\001\000\000"
    font.save(str(dst))


def register_fonts() -> bool:
    """Register Minion Pro with ReportLab. Returns True if the real faces
    were available; False if a fallback serif had to be used."""
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.pdfmetrics import registerFontFamily
    from reportlab.pdfbase.ttfonts import TTFont as RLFont

    ok = True
    for name, filename in FACES.items():
        src = ACROBAT_FONTS / filename
        dst = BRAND_DIR / f"{name}.ttf"
        if not dst.exists():
            if not src.exists():
                ok = False
                continue
            _otf_to_ttf(src, dst)
        pdfmetrics.registerFont(RLFont(name, str(dst)))

    if not ok:
        # Constantia is the closest humanist serif Windows ships; only used if
        # Acrobat's Minion faces are missing on this machine.
        win = Path(r"C:\Windows\Fonts")
        for name, filename in [("Minion", "constan.ttf"), ("Minion-It", "constani.ttf"),
                               ("Minion-Bold", "constanb.ttf"),
                               ("Minion-BoldIt", "constanz.ttf")]:
            pdfmetrics.registerFont(RLFont(name, str(win / filename)))

    registerFontFamily("Minion", normal="Minion", bold="Minion-Bold",
                       italic="Minion-It", boldItalic="Minion-BoldIt")
    return ok


def styles():
    """Paragraph styles matching the template's typographic scale."""
    from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY
    from reportlab.lib.styles import ParagraphStyle

    base = ParagraphStyle(
        "body", fontName="Minion", fontSize=BODY_SIZE, leading=BODY_LEAD,
        alignment=TA_JUSTIFY, textColor=INK, spaceAfter=BODY_LEAD * 0.55,
    )
    return {
        "body": base,
        "first": ParagraphStyle("first", parent=base, spaceBefore=0),
        "head": ParagraphStyle(
            "head", parent=base, fontName="Minion-Bold", fontSize=HEAD_SIZE,
            leading=HEAD_SIZE * 1.2, alignment=0, spaceBefore=BODY_LEAD * 1.5,
            spaceAfter=BODY_LEAD * 0.7, keepWithNext=1,
        ),
        "sub": ParagraphStyle(
            "sub", parent=base, fontName="Minion-Bold", fontSize=12.5,
            leading=15, alignment=0, spaceBefore=BODY_LEAD * 0.9,
            spaceAfter=BODY_LEAD * 0.3, keepWithNext=1,
        ),
        "quote": ParagraphStyle(
            "quote", parent=base, fontName="Minion-It", fontSize=11,
            leading=13.6, leftIndent=22, rightIndent=22,
            spaceBefore=BODY_LEAD * 0.5, spaceAfter=BODY_LEAD * 0.6,
        ),
        "bullet": ParagraphStyle(
            "bullet", parent=base, leftIndent=18, bulletIndent=4,
            spaceAfter=BODY_LEAD * 0.35,
        ),
        "num": ParagraphStyle(
            "num", parent=base, leftIndent=20, bulletIndent=0,
            spaceAfter=BODY_LEAD * 0.45,
        ),
        "caption": ParagraphStyle(
            "caption", parent=base, fontSize=9.5, leading=11.6,
            textColor=INK_75, alignment=0, spaceBefore=4,
            spaceAfter=BODY_LEAD * 0.8,
        ),
        "note": ParagraphStyle(
            "note", parent=base, fontSize=9.5, leading=11.6, alignment=0,
            leftIndent=14, bulletIndent=0, spaceAfter=5,
        ),
        "tablecellr": ParagraphStyle(
            "tablecellr", parent=base, fontSize=9.5, leading=11.4,
            alignment=2, spaceAfter=0,
        ),
        "tableheadr": ParagraphStyle(
            "tableheadr", parent=base, fontName="Minion-Bold", fontSize=9.5,
            leading=11.4, alignment=2, spaceAfter=0,
        ),
        "tablecell": ParagraphStyle(
            "tablecell", parent=base, fontSize=9.5, leading=11.4,
            alignment=0, spaceAfter=0,
        ),
        "tablehead": ParagraphStyle(
            "tablehead", parent=base, fontName="Minion-Bold", fontSize=9.5,
            leading=11.4, alignment=0, spaceAfter=0,
        ),
    }
