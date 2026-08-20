"""Tablas en paginas escaneadas.

Dos caminos complementarios:
  1. `find_ruled_tables`  - detecta el rayado en la imagen (morfologia 1-D con
     numpy) y reparte las palabras del OCR en las celdas de la rejilla.
  2. `find_whitespace_tables` - tablas sin bordes: busca columnas separadas por
     pasillos blancos consistentes en varios renglones seguidos.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass

import numpy as np

from typing import Callable

from ..model import Line, Table, Word

# (x0, top, x1, bottom) en puntos PDF -> texto releido de esa celda
CellOcr = Callable[[float, float, float, float], str]
from ..engines.preprocess import binarize
from ..util.text import clean


# --------------------------------------------------------------------------
# morfologia 1-D vectorizada (sin scipy/opencv)
# --------------------------------------------------------------------------
def _window_sum(mask: np.ndarray, k: int, axis: int) -> np.ndarray:
    """Suma deslizante de ventana k centrada, con relleno a cero."""
    k = max(1, int(k))
    before, after = k // 2, k - 1 - k // 2
    pads = [(0, 0)] * mask.ndim
    pads[axis] = (before, after)
    padded = np.pad(mask.astype(np.int32), pads)
    csum = np.cumsum(padded, axis=axis)
    zeros_shape = list(csum.shape)
    zeros_shape[axis] = 1
    csum = np.concatenate([np.zeros(zeros_shape, dtype=csum.dtype), csum], axis=axis)
    n = mask.shape[axis]
    hi = np.take(csum, np.arange(k, k + n), axis=axis)
    lo = np.take(csum, np.arange(0, n), axis=axis)
    return hi - lo


def _open_1d(mask: np.ndarray, k: int, axis: int) -> np.ndarray:
    """Apertura morfologica con kernel lineal: conserva solo trazos largos."""
    eroded = _window_sum(mask, k, axis) == k
    return _window_sum(eroded, k, axis) > 0


def _longest_run(flags: np.ndarray, max_gap: int = 4) -> tuple[int, int]:
    """Tramo contiguo mas largo de True (tolerando huecos de `max_gap`).

    Hay que medir el tramo, no la extension: una columna con dos trazos
    sueltos, uno arriba y otro abajo, no es un filete de tabla.
    """
    idx = np.flatnonzero(flags)
    if idx.size == 0:
        return (0, -1)
    best = (idx[0], idx[0])
    start = prev = idx[0]
    for i in idx[1:]:
        if i - prev <= max_gap:
            prev = i
        else:
            if prev - start > best[1] - best[0]:
                best = (start, prev)
            start = prev = i
    if prev - start > best[1] - best[0]:
        best = (start, prev)
    return (int(best[0]), int(best[1]))


@dataclass(slots=True)
class Ruling:
    pos: float        # y (horizontal) o x (vertical), en puntos PDF
    start: float
    end: float

    @property
    def length(self) -> float:
        return self.end - self.start


def _bands(indices: np.ndarray, max_gap: int = 3) -> list[tuple[int, int]]:
    """Agrupa indices consecutivos (con holgura) en bandas [inicio, fin]."""
    if indices.size == 0:
        return []
    out, start, prev = [], int(indices[0]), int(indices[0])
    for i in indices[1:]:
        i = int(i)
        if i - prev <= max_gap:
            prev = i
            continue
        out.append((start, prev))
        start = prev = i
    out.append((start, prev))
    return out


def find_rulings(gray: np.ndarray, scale: float,
                 min_h_len_pt: float = 40.0,
                 min_v_len_pt: float = 18.0) -> tuple[list[Ruling], list[Ruling]]:
    """Detecta filetes horizontales y verticales en la imagen binarizada.

    El nucleo de la apertura se mantiene corto (detecta trazos discontinuos y
    tolera un resto de inclinacion) y el descarte se hace despues, por longitud
    real del segmento en puntos PDF.
    """
    ink = binarize(gray)
    h, w = ink.shape
    if h < 40 or w < 40:
        return [], []

    hk = max(20, int(min_h_len_pt * scale * 0.5))
    vk = max(14, int(min_v_len_pt * scale * 0.5))
    h_mask = _open_1d(ink, hk, axis=1)
    v_mask = _open_1d(ink, vk, axis=0)

    # Una fila es candidata a filete si casi toda su tinta forma un trazo largo.
    h_rows = np.where(h_mask.sum(axis=1) >= hk)[0]
    v_cols = np.where(v_mask.sum(axis=0) >= vk)[0]

    gap_px = max(3, int(2.0 * scale))

    horizontals: list[Ruling] = []
    for a, b in _bands(h_rows, max_gap=2):
        c0, c1 = _longest_run(h_mask[a:b + 1].any(axis=0), gap_px)
        if c1 <= c0 or (c1 - c0) / scale < min_h_len_pt:
            continue
        horizontals.append(
            Ruling(((a + b) / 2) / scale, c0 / scale, c1 / scale)
        )

    verticals: list[Ruling] = []
    for a, b in _bands(v_cols, max_gap=2):
        r0, r1 = _longest_run(v_mask[:, a:b + 1].any(axis=1), gap_px)
        if r1 <= r0 or (r1 - r0) / scale < min_v_len_pt:
            continue
        verticals.append(
            Ruling(((a + b) / 2) / scale, r0 / scale, r1 / scale)
        )

    return horizontals, verticals


def _cluster_positions(values: list[float], tol: float) -> list[float]:
    if not values:
        return []
    values = sorted(values)
    groups, current = [], [values[0]]
    for v in values[1:]:
        if v - current[-1] <= tol:
            current.append(v)
        else:
            groups.append(sum(current) / len(current))
            current = [v]
    groups.append(sum(current) / len(current))
    return groups


def _cell_text(words: list[Word], x0: float, y0: float, x1: float, y1: float) -> str:
    """Texto de una celda, respetando el orden de lectura de sus renglones."""
    inside = [w for w in words if x0 <= w.cx < x1 and y0 <= w.cy < y1]
    if not inside:
        return ""
    # Agrupar en renglones antes de ordenar: comparar cy directamente desordena
    # palabras de la misma linea que difieren unas decimas.
    from .layout import group_words_into_lines
    lines = group_words_into_lines(inside)
    return clean(" ".join(ln.text for ln in lines))


def _plausible_cell(text: str) -> bool:
    """Descarta lo que devuelve el OCR al leer un dibujo: simbolos sueltos."""
    if not text:
        return False
    alnum = sum(c.isalnum() for c in text)
    return alnum >= max(1, int(len(text) * 0.45))


def _clean_rescued(text: str) -> str:
    """Quita el filete de la celda que el OCR lee como barra vertical."""
    return text.strip(" |¦l_").strip() if text else ""


def find_ruled_tables(gray: np.ndarray, scale: float, words: list[Word],
                      min_cells: int = 6,
                      cell_ocr: "CellOcr | None" = None,
                      max_rescues: int = 60) -> list[Table]:
    """Construye tablas a partir del rayado detectado en la imagen.

    `cell_ocr` es una funcion (x0, top, x1, bottom) -> str que relee una celda
    concreta. El OCR de pagina completa suele saltarse las cabeceras con fondo
    de color y las celdas con un numero suelto, asi que las celdas que quedan
    vacias se releen una a una recortando la imagen.
    """
    h_lines, v_lines = find_rulings(gray, scale)
    if len(h_lines) < 3 or len(v_lines) < 2:
        return []

    page_w = gray.shape[1] / scale
    page_h = gray.shape[0] / scale
    tol = max(2.0, page_h * 0.004)

    ys = _cluster_positions([r.pos for r in h_lines], tol)
    xs = _cluster_positions([r.pos for r in v_lines], tol)
    if len(ys) < 3 or len(xs) < 3:
        return []

    # Region de la rejilla: solo donde rayado horizontal y vertical coexisten.
    x0, x1 = xs[0], xs[-1]
    y0, y1 = ys[0], ys[-1]
    if (x1 - x0) < page_w * 0.15 or (y1 - y0) < page_h * 0.04:
        return []

    rows: list[list[str]] = []
    empty_cells: list[tuple[int, int]] = []
    for i in range(len(ys) - 1):
        row = []
        for j in range(len(xs) - 1):
            text = _cell_text(words, xs[j], ys[i], xs[j + 1], ys[i + 1])
            if not text:
                empty_cells.append((i, j))
            row.append(text)
        rows.append(row)

    n_cells = max(1, (len(ys) - 1) * (len(xs) - 1))
    main_filled = n_cells - len(empty_cells)

    # Un dibujo tecnico tambien produce una rejilla de lineas. Lo que lo
    # distingue de una tabla es que el OCR de pagina ya encontro texto dentro:
    # si casi todas las celdas llegan vacias, esto no es una tabla.
    words_in_grid = sum(1 for w in words if x0 <= w.cx <= x1 and y0 <= w.cy <= y1)
    if words_in_grid < 6 or main_filled < n_cells * 0.35:
        return []

    if cell_ocr is not None and 0 < len(empty_cells) <= max_rescues:
        for i, j in empty_cells:
            try:
                rescued = _clean_rescued(cell_ocr(xs[j], ys[i], xs[j + 1], ys[i + 1]))
            except Exception:
                rescued = ""
            if rescued and _plausible_cell(rescued):
                rows[i][j] = rescued

    rows = [r for r in rows if any(c for c in r)]
    filled = sum(1 for r in rows for c in r if c)
    if len(rows) < 2 or filled < min_cells:
        return []

    conf = min(1.0, filled / max(1, len(rows) * (len(xs) - 1)))
    if conf < 0.25:
        return []
    return [Table(rows=rows, bbox=(x0, y0, x1, y1), source="ruled",
                  confidence=conf, has_header=True)]


# --------------------------------------------------------------------------
# tablas sin bordes
# --------------------------------------------------------------------------
def _median_space(line: Line) -> float:
    widths = [w.x1 - w.x0 for w in line.words]
    chars = [len(w.text) for w in line.words]
    if not widths:
        return 4.0
    per_char = [wd / max(c, 1) for wd, c in zip(widths, chars)]
    return statistics.median(per_char) * 1.4


def find_whitespace_tables(lines: list[Line], page_width: float,
                           min_rows: int = 3,
                           min_cols: int = 2) -> list[Table]:
    """Detecta bloques tabulares sin rayado por alineacion de columnas."""
    tables: list[Table] = []
    n = len(lines)
    i = 0

    while i < n:
        # Un candidato empieza donde hay al menos 2 palabras con hueco grande.
        run = []
        j = i
        while j < n:
            ln = lines[j]
            if len(ln.words) < 2:
                break
            gaps = [
                b.x0 - a.x1
                for a, b in zip(ln.words, ln.words[1:])
            ]
            if not gaps or max(gaps) < _median_space(ln) * 2.2:
                break
            if run:
                prev = run[-1]
                v_gap = ln.bbox[1] - prev.bbox[3]
                if v_gap > max(prev.bbox[3] - prev.bbox[1], 6) * 2.2:
                    break
            run.append(ln)
            j += 1

        if len(run) >= min_rows:
            table = _build_whitespace_table(run, page_width, min_cols)
            if table:
                tables.append(table)
            i = j
        else:
            i = max(i + 1, j)

    return tables


def _build_whitespace_table(run: list[Line], page_width: float,
                            min_cols: int) -> Table | None:
    x0 = min(ln.bbox[0] for ln in run)
    x1 = max(ln.bbox[2] for ln in run)
    width = max(x1 - x0, 1.0)

    bins = 300
    step = width / bins
    occupancy = np.zeros(bins, dtype=np.int32)
    for ln in run:
        for w in ln.words:
            a = max(0, min(bins - 1, int((w.x0 - x0) / step)))
            b = max(0, min(bins - 1, int((w.x1 - x0) / step)))
            occupancy[a:b + 1] += 1

    min_gap_bins = max(2, int(bins * 0.012))
    separators: list[float] = []
    start = None
    for k in range(bins):
        if occupancy[k] == 0:
            if start is None:
                start = k
        else:
            if start is not None and k - start >= min_gap_bins and start > 0:
                separators.append(x0 + (start + k) / 2 * step)
            start = None

    if len(separators) + 1 < min_cols:
        return None

    edges = [x0 - 1.0] + separators + [x1 + 1.0]
    rows: list[list[str]] = []
    for ln in run:
        row = []
        for c in range(len(edges) - 1):
            cell = [w.text for w in ln.words if edges[c] <= w.cx < edges[c + 1]]
            row.append(clean(" ".join(cell)))
        rows.append(row)

    # Exige que la mayoria de filas usen realmente al menos dos columnas.
    multi = sum(1 for r in rows if sum(1 for c in r if c) >= 2)
    if multi < len(rows) * 0.7 or multi < min_cols:
        return None

    n_cols = len(edges) - 1
    # Cada columna debe estar poblada; si una casi siempre esta vacia, lo que
    # hay no es una tabla sino un parrafo con un hueco casual.
    for c in range(n_cols):
        if sum(1 for r in rows if r[c]) < len(rows) * 0.6:
            return None

    # Celdas con frases largas y puntuacion de prosa delatan texto corrido.
    prose = sum(
        1 for r in rows for c in r
        if len(c) > 55 and any(ch in c for ch in ".;:")
    )
    if prose > len(rows) * 0.5:
        return None

    filled = sum(1 for r in rows for c in r if c)
    total = len(rows) * n_cols
    conf = filled / total if total else 0.0
    if conf < 0.55:
        return None

    return Table(
        rows=rows,
        bbox=(x0, run[0].bbox[1], x1, run[-1].bbox[3]),
        source="whitespace",
        confidence=round(conf, 3),
        has_header=True,
    )
