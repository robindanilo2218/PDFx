"""Utilidades de texto: normalizacion, limpieza y heuristicas ligeras."""

from __future__ import annotations

import re
import unicodedata

# Ligaduras y comillas tipograficas que ensucian el markdown.
_REPLACEMENTS = {
    "ﬀ": "ff", "ﬁ": "fi", "ﬂ": "fl", "ﬃ": "ffi", "ﬄ": "ffl",
    "‘": "'", "’": "'", "“": '"', "”": '"',
    "–": "-", "—": "-", "−": "-",
    " ": " ", " ": " ", " ": " ", "﻿": "",
    "…": "...",
}

_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_MULTISPACE = re.compile(r"[ \t]{2,}")

BULLETS = "•●▪■◦⁃∙·-*–—>"

_ORDERED_RE = re.compile(r"^\(?(\d{1,3}|[a-zA-Z]|[ivxIVX]{1,6})[\.\)\-]\s+")
_BULLET_RE = re.compile(rf"^[{re.escape(BULLETS)}]\s+")
_NUMBERED_HEADING_RE = re.compile(r"^(\d{1,2}(?:\.\d{1,2}){0,4})\.?\s+\S")


def clean(text: str) -> str:
    """Normaliza un fragmento de texto extraido del PDF."""
    if not text:
        return ""
    for bad, good in _REPLACEMENTS.items():
        text = text.replace(bad, good)
    text = _CTRL.sub("", text)
    text = _MULTISPACE.sub(" ", text)
    return text.strip()


def strip_accents(text: str) -> str:
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def fold(text: str) -> str:
    """Clave de comparacion: sin acentos, minusculas, espacios colapsados."""
    return re.sub(r"\s+", " ", strip_accents(text).lower()).strip()


def dehyphenate(prev: str, nxt: str) -> str | None:
    """Une 'inge-' + 'nieria' -> 'ingenieria'. Devuelve None si no aplica."""
    if not prev.endswith("-") or len(prev) < 3:
        return None
    stem = prev[:-1]
    if not stem[-1:].isalpha() or not nxt[:1].isalpha():
        return None
    if nxt[:1].isupper():        # probable nombre propio, no cortar
        return None
    return stem + nxt


# Fuentes de simbolos: su vineta se extrae como una letra cualquiera ("l", "n")
_SYMBOL_FONT_RE = re.compile(r"symbol|dingbat|wingding|webding|zapf", re.I)


def is_symbol_font(fontname: str) -> bool:
    return bool(fontname) and bool(_SYMBOL_FONT_RE.search(fontname))


def list_marker(text: str, first_word: str = "",
                first_font: str = "") -> tuple[str, bool] | None:
    """Devuelve (marcador, es_ordenada) si la linea abre un item de lista.

    Muchos PDF dibujan la vineta con una fuente de simbolos, de modo que el
    texto extraido es una letra suelta ("l Vibracion anomala..."); por eso se
    mira tambien la fuente de la primera palabra.
    """
    m = _BULLET_RE.match(text)
    if m:
        return m.group(0).strip(), False
    m = _ORDERED_RE.match(text)
    if m:
        # "1994. El ano en que..." no es una lista; exige marcador corto.
        if len(m.group(1)) <= 3:
            return m.group(0).strip(), True
    if first_word and len(first_word) == 1 and is_symbol_font(first_font):
        return first_word, False
    return None


def heading_number(text: str) -> str | None:
    """Devuelve '2.3.1' si la linea empieza con numeracion de apartado."""
    m = _NUMBERED_HEADING_RE.match(text)
    return m.group(1) if m else None


def is_probably_caption(text: str) -> bool:
    t = fold(text)
    return bool(re.match(r"^(fig(ura)?|tabla|cuadro|imagen|foto|graf(ico)?)\.?\s*\d", t))


def looks_like_garbage(text: str) -> bool:
    """Detecta capas de texto corruptas (PDFs con fuentes sin ToUnicode)."""
    if len(text) < 40:
        return False
    letters = sum(c.isalpha() for c in text)
    if letters / max(len(text), 1) < 0.35:
        return True
    # Muchos caracteres de reemplazo o del area de uso privado.
    weird = sum(1 for c in text if c == "�" or 0xE000 <= ord(c) <= 0xF8FF)
    return weird / max(len(text), 1) > 0.05


def escape_md(text: str) -> str:
    """Escapa solo lo imprescindible para no romper tablas ni enfasis."""
    return text.replace("\\", "\\\\").replace("|", "\\|")


def slugify(text: str, maxlen: int = 40) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", strip_accents(text)).strip("-").lower()
    return (s[:maxlen].rstrip("-")) or "sin-titulo"


def token_estimate(text: str) -> int:
    """Aproximacion rapida de tokens (~4 chars/token en espanol tecnico)."""
    return max(1, len(text) // 4)
