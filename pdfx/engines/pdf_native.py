"""Extraccion de la capa de texto nativa con pdfplumber (MIT / pdfminer.six).

Devuelve palabras con caja, tamano de fuente y estilo, en coordenadas
"top-down" (origen arriba-izquierda) que es lo que usa todo el modelo.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from ..model import Word
from ..util.text import clean, looks_like_garbage

log = logging.getLogger(__name__)

_BOLD_RE = re.compile(r"bold|black|heavy|semib|demi", re.I)
_ITALIC_RE = re.compile(r"italic|oblique", re.I)

WORD_ATTRS = ["size", "fontname", "upright"]


@dataclass(slots=True)
class NativeText:
    words: list[Word]
    char_count: int
    garbage: bool
    coverage: float          # fraccion del area de pagina cubierta por texto


def _style(fontname: str) -> tuple[bool, bool]:
    if not fontname:
        return False, False
    return bool(_BOLD_RE.search(fontname)), bool(_ITALIC_RE.search(fontname))


def extract_words(plumber_page) -> NativeText:
    """Palabras nativas de una pagina de pdfplumber."""
    try:
        raw = plumber_page.extract_words(
            keep_blank_chars=False,
            use_text_flow=False,
            extra_attrs=WORD_ATTRS,
            x_tolerance=1.6,
            y_tolerance=2.6,
        )
    except Exception as exc:  # pdfminer puede reventar en PDFs corruptos
        log.warning("extract_words fallo en pagina %s: %s", plumber_page.page_number, exc)
        return NativeText([], 0, False, 0.0)

    words: list[Word] = []
    area = 0.0
    for w in raw:
        text = clean(w.get("text", ""))
        if not text:
            continue
        fontname = w.get("fontname", "") or ""
        bold, italic = _style(fontname)
        word = Word(
            text=text,
            x0=float(w["x0"]),
            top=float(w["top"]),
            x1=float(w["x1"]),
            bottom=float(w["bottom"]),
            size=float(w.get("size") or 0.0),
            bold=bold,
            italic=italic,
            conf=100.0,
            font=fontname,
            upright=bool(w.get("upright", True)),
        )
        words.append(word)
        area += (word.x1 - word.x0) * (word.bottom - word.top)

    joined = " ".join(w.text for w in words)
    page_area = float(plumber_page.width or 1) * float(plumber_page.height or 1)
    return NativeText(
        words=words,
        char_count=len(joined.replace(" ", "")),
        garbage=looks_like_garbage(joined),
        coverage=area / page_area if page_area else 0.0,
    )


def page_has_usable_text(nt: NativeText, threshold: int) -> bool:
    """Decide si la capa nativa sirve o hay que pasar por OCR."""
    if nt.garbage:
        return False
    return nt.char_count >= threshold
