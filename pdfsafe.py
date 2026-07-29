"""Keep xhtml2pdf from drawing black squares.

The PDF renderer draws with ReportLab's built-in Type1 fonts, which only carry
the WinAnsi character set. Anything outside it is drawn with ReportLab's
"notdef" glyph - the letter n in ZapfDingbats, a solid black square. Uploaded
CVs are full of characters that fall outside it: non-breaking hyphens in
compound words, typographic ligatures, the rupee sign. Each one became a black
spot in the exported resume.

Two fixes live here:

* ``safe_text`` rewrites those characters into WinAnsi equivalents before the
  HTML reaches the renderer.
* Importing this module repoints xhtml2pdf's list marker. Its default is U+2022
  BULLET, which ReportLab maps to byte 0x7F - undefined in WinAnsi, so every
  bullet came out blank or boxed. A middot is in the character set, still reads
  as a bullet, and survives text extraction, which is what ATS parsers do.
"""

import unicodedata

from reportlab.pdfbase import rl_codecs
from xhtml2pdf import tags as xhtml2pdf_tags

# Registers the "winansi" codec, which is the exact set of characters the
# built-in fonts can draw. Encoding against it is how safe_text decides.
rl_codecs.RL_Codecs.register()

BULLET = '·'

xhtml2pdf_tags._bullet = BULLET
for _marker in ('disc', 'circle', 'square'):
    xhtml2pdf_tags._list_style_type[_marker] = BULLET

# Characters worth spelling out rather than leaving to the generic fallback,
# either because they carry meaning that would be lost (the rupee sign) or
# because WinAnsi accepts them but ReportLab still cannot draw them (U+2022).
SUBSTITUTIONS = {
    '‐': '-',       # hyphen
    '‑': '-',       # non-breaking hyphen
    '‒': '-',       # figure dash
    '―': '-',       # horizontal bar
    '⁃': '-',       # hyphen bullet
    '−': '-',       # minus sign
    '•': BULLET,    # bullet - in WinAnsi, but drawn as an undefined byte
    '‣': BULLET,    # triangular bullet
    '▪': BULLET,    # black small square
    '●': BULLET,    # black circle
    '◦': BULLET,    # white bullet
    '′': "'",       # prime
    '″': '"',       # double prime
    '→': '->',
    '←': '<-',
    '⇒': '=>',
    '≤': '<=',
    '≥': '>=',
    '≠': '!=',
    '₹': 'Rs.',     # rupee
    '­': '',        # soft hyphen
    '​': '',        # zero-width space
    '‌': '',        # zero-width non-joiner
    '‍': '',        # zero-width joiner
    '﻿': '',        # byte order mark
    ' ': ' ',       # thin space
    ' ': ' ',       # figure space
    ' ': ' ',       # narrow no-break space
    ' ': ' ',       # line separator
    ' ': ' ',       # paragraph separator
}

_KEEP = '\n\r\t'


def _drawable(text):
    try:
        text.encode('winansi')
    except (UnicodeEncodeError, UnicodeDecodeError):
        return False
    return True


def safe_text(text):
    """Return text with every character the PDF fonts cannot draw replaced.

    Known characters are mapped to a readable equivalent. Anything else is
    decomposed - a fi ligature becomes "fi", an accented letter keeps its base
    letter if the composed form is unavailable. Characters with no Latin
    equivalent at all, such as CJK or Devanagari, are dropped: the built-in
    fonts have no glyph for them, and a run of black squares is worse than a
    gap.
    """
    if not text:
        return text

    out = []
    for char in text:
        replacement = SUBSTITUTIONS.get(char)
        if replacement is not None:
            out.append(replacement)
            continue
        if char in _KEEP or _drawable(char):
            out.append(char)
            continue

        decomposed = unicodedata.normalize('NFKD', char)
        stripped = ''.join(c for c in decomposed if not unicodedata.combining(c))
        out.append(stripped if stripped and _drawable(stripped) else '')

    return ''.join(out)
