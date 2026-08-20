"""Deteccion de tablas en PDFs con capa de texto nativa (pdfplumber)."""

from __future__ import annotations

import logging

from ..model import Table
from ..util.text import clean

log = logging.getLogger(__name__)

# Primero por lineas de rayado; si no hay rayado, por alineacion de texto.
_STRATEGIES = (
    {"vertical_strategy": "lines", "horizontal_strategy": "lines"},
    {"vertical_strategy": "lines", "horizontal_strategy": "text",
     "text_y_tolerance": 3},
    {"vertical_strategy": "text", "horizontal_strategy": "text",
     "text_x_tolerance": 2, "text_y_tolerance": 3,
     "intersection_x_tolerance": 8},
)


def _clean_grid(raw_rows) -> list[list[str]]:
    rows: list[list[str]] = []
    for row in raw_rows or []:
        cells = [clean((c or "").replace("\n", " ")) for c in row]
        rows.append(cells)
    # quita filas y columnas totalmente vacias
    rows = [r for r in rows if any(c for c in r)]
    if not rows:
        return []
    n = max(len(r) for r in rows)
    rows = [r + [""] * (n - len(r)) for r in rows]
    keep = [i for i in range(n) if any(r[i] for r in rows)]
    if not keep:
        return []
    return [[r[i] for i in keep] for r in rows]


def _splits_words(rows: list[list[str]]) -> bool:
    """Una rejilla que parte palabras por la mitad no es una tabla real.

    pdfplumber, con la estrategia de alineacion de texto, a veces coloca un
    limite de columna dentro de una palabra: "Disposi | cion de motor".
    """
    if not rows:
        return False
    broken = 0
    for row in rows:
        for left, right in zip(row, row[1:]):
            left, right = left.rstrip(), right.lstrip()
            if left and right and left[-1].isalpha() and right[0].islower():
                broken += 1
                break
    return broken > len(rows) * 0.30


def _is_prose(rows: list[list[str]]) -> bool:
    """Celdas largas con puntuacion de frase: es texto corrido, no una tabla."""
    long_cells = sum(
        1 for row in rows for c in row
        if len(c) > 55 and any(ch in c for ch in ".;:")
    )
    return long_cells > len(rows) * 0.5


def _quality(rows: list[list[str]]) -> float:
    """0..1 - penaliza rejillas casi vacias o de una sola celda util."""
    if len(rows) < 2:
        return 0.0
    n_cols = max(len(r) for r in rows)
    if n_cols < 2:
        return 0.0
    total = len(rows) * n_cols
    filled = sum(1 for r in rows for c in r if c.strip())
    fill_ratio = filled / total if total else 0.0
    # Una tabla util tiene al menos un tercio de celdas con contenido.
    if fill_ratio < 0.30:
        return 0.0
    if _splits_words(rows) or _is_prose(rows):
        return 0.0
    consistent = sum(1 for r in rows if sum(1 for c in r if c.strip()) >= 2)
    return min(1.0, fill_ratio * 0.6 + (consistent / len(rows)) * 0.4)


def find_tables(plumber_page, min_quality: float = 0.35) -> list[Table]:
    """Devuelve las tablas de la pagina, sin solaparse entre estrategias."""
    found: list[Table] = []

    for settings in _STRATEGIES:
        try:
            candidates = plumber_page.find_tables(table_settings=settings)
        except Exception as exc:
            log.debug("find_tables fallo con %s: %s", settings, exc)
            continue

        for cand in candidates:
            try:
                rows = _clean_grid(cand.extract())
            except Exception:
                continue
            if len(rows) < 2:
                continue
            q = _quality(rows)
            if q < min_quality:
                continue

            bbox = tuple(float(v) for v in cand.bbox)  # (x0, top, x1, bottom)
            if any(_overlaps(bbox, t.bbox) for t in found):
                continue
            found.append(
                Table(rows=rows, bbox=bbox, source="native", confidence=q,
                      has_header=_looks_like_header(rows))
            )

        # Si el rayado ya dio tablas buenas, no forzamos la estrategia de texto.
        if found and settings is _STRATEGIES[0]:
            break

    return sorted(found, key=lambda t: (t.bbox[1], t.bbox[0]))


def _overlaps(a, b, thresh: float = 0.35) -> bool:
    ix0, iy0 = max(a[0], b[0]), max(a[1], b[1])
    ix1, iy1 = min(a[2], b[2]), min(a[3], b[3])
    if ix1 <= ix0 or iy1 <= iy0:
        return False
    inter = (ix1 - ix0) * (iy1 - iy0)
    smaller = min((a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1]))
    return smaller > 0 and inter / smaller > thresh


def _looks_like_header(rows: list[list[str]]) -> bool:
    """Cabecera probable: primera fila llena y sin numeros sueltos."""
    if len(rows) < 2:
        return False
    first = rows[0]
    if sum(1 for c in first if c.strip()) < max(2, len(first) * 0.6):
        return False
    numeric = sum(1 for c in first if c.strip().replace(",", "").replace(".", "").isdigit())
    return numeric <= len(first) * 0.3
