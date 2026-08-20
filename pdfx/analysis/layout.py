"""Analisis de maquetacion: palabras -> renglones -> columnas -> bloques.

Funciona igual con palabras nativas y con palabras de OCR, porque ambas llegan
al modelo con caja, tamano y confianza.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass

from ..model import BBox, Block, Line, Word
from ..util.text import dehyphenate, heading_number, is_probably_caption, list_marker

# El OCR no conoce la fuente, asi que una vineta llega como una letra suelta.
# Estos son los caracteres en los que Tesseract suele convertirla.
_OCR_BULLET_CHARS = set("oO0eEcCdDQ@©°ºªnNuUlIiI|*+-=~^\u25a0\u25aa\u25cf\u2022")


def detect_ocr_bullets(lines: list[Line], tol: float = 4.0,
                       min_group: int = 2) -> set[int]:
    """Indices de renglones que empiezan por una vineta leida como letra.

    Criterio: primera palabra de un solo caracter sospechoso, separada del
    resto, y alineada en x con al menos otro renglon igual. La alineacion es
    lo que evita confundirla con una palabra real de una letra.
    """
    candidates: list[tuple[int, float]] = []
    for i, ln in enumerate(lines):
        if len(ln.words) < 2:
            continue
        first, second = ln.words[0], ln.words[1]
        if len(first.text) != 1 or first.text not in _OCR_BULLET_CHARS:
            continue
        gap = second.x0 - first.x1
        if gap < max(first.height, 1.0) * 0.20:
            continue
        candidates.append((i, first.x0))

    marked: set[int] = set()
    for i, x in candidates:
        same = [j for j, xx in candidates if abs(xx - x) <= tol]
        if len(same) >= min_group:
            marked.update(same)
    return marked


# --------------------------------------------------------------------------
# palabras -> renglones
# --------------------------------------------------------------------------
def group_words_into_lines(words: list[Word], tol_ratio: float = 0.55) -> list[Line]:
    """Agrupa por banda vertical. tol_ratio se mide contra la altura de palabra."""
    if not words:
        return []

    ordered = sorted(words, key=lambda w: (round(w.cy, 1), w.x0))
    lines: list[list[Word]] = []
    current: list[Word] = [ordered[0]]
    cur_cy = ordered[0].cy
    cur_h = max(ordered[0].height, 1.0)

    for w in ordered[1:]:
        tol = max(cur_h, w.height) * tol_ratio
        if abs(w.cy - cur_cy) <= tol:
            current.append(w)
            # media movil: evita que un renglon "derive" con super/subindices
            cur_cy = sum(x.cy for x in current) / len(current)
            cur_h = statistics.median([x.height for x in current]) or cur_h
        else:
            lines.append(current)
            current = [w]
            cur_cy, cur_h = w.cy, max(w.height, 1.0)
    lines.append(current)

    out = [Line(words=sorted(ws, key=lambda w: w.x0)) for ws in lines]
    return sorted(out, key=lambda ln: (ln.bbox[1], ln.bbox[0]))


# --------------------------------------------------------------------------
# deteccion de columnas
# --------------------------------------------------------------------------
@dataclass(slots=True)
class Column:
    x0: float
    x1: float
    words: list[Word]


def detect_columns(words: list[Word], page_width: float,
                   min_gutter_ratio: float = 0.028,
                   min_span_ratio: float = 0.55,
                   max_columns: int = 3,
                   crossing_tolerance: float = 0.04) -> list[Column]:
    """Divide la pagina en columnas si hay un pasillo blanco vertical claro.

    Trabaja sobre palabras y no sobre renglones a proposito: si primero se
    agrupan los renglones, las dos columnas quedan unidas en una misma linea
    (comparten banda vertical) y el pasillo deja de ser visible.
    """
    single = [Column(0.0, page_width, words)]
    if len(words) < 40 or page_width <= 0:
        return single

    bins = 400
    step = page_width / bins
    occupancy = [0] * bins
    for w in words:
        a = max(0, min(bins - 1, int(w.x0 / step)))
        b = max(0, min(bins - 1, int(w.x1 / step)))
        for i in range(a, b + 1):
            occupancy[i] += 1

    content_top = min(w.top for w in words)
    content_bottom = max(w.bottom for w in words)
    content_h = max(content_bottom - content_top, 1.0)

    # Pasillos candidatos: rachas de bins vacios lejos de los margenes.
    min_gutter_bins = max(3, int(bins * min_gutter_ratio))
    margin = int(bins * 0.15)
    gutters: list[tuple[int, int]] = []
    run_start = None
    for i in range(bins):
        if occupancy[i] == 0:
            if run_start is None:
                run_start = i
        else:
            if run_start is not None and i - run_start >= min_gutter_bins:
                gutters.append((run_start, i))
            run_start = None
    if run_start is not None and bins - run_start >= min_gutter_bins:
        gutters.append((run_start, bins))

    gutters = [g for g in gutters if g[0] > margin and g[1] < bins - margin]
    if not gutters:
        return single

    valid: list[float] = []
    for a, b in gutters:
        gx0, gx1 = a * step, b * step
        # Un titulo a todo lo ancho puede cruzar el pasillo: se tolera un poco.
        crossing = sum(1 for w in words if w.x0 < gx1 and w.x1 > gx0)
        if crossing > max(2, len(words) * crossing_tolerance):
            continue
        left = [w for w in words if w.x1 <= gx0]
        right = [w for w in words if w.x0 >= gx1]
        if len(left) < 15 or len(right) < 15:
            continue
        span = max(
            (max(w.bottom for w in side) - min(w.top for w in side))
            for side in (left, right)
        )
        if span / content_h >= min_span_ratio:
            valid.append((gx0 + gx1) / 2.0)

    if not valid:
        return single
    valid = sorted(valid)[: max_columns - 1]

    edges = [0.0] + valid + [page_width]
    cols: list[Column] = []
    for i in range(len(edges) - 1):
        lo, hi = edges[i], edges[i + 1]
        members = [w for w in words if lo <= w.cx < hi]
        if members:
            cols.append(Column(lo, hi, members))
    return cols if len(cols) > 1 else single


# --------------------------------------------------------------------------
# renglones -> bloques
# --------------------------------------------------------------------------
def _body_size(lines: list[Line]) -> float:
    """Tamano de cuerpo: mediana ponderada por numero de caracteres."""
    samples: list[float] = []
    for ln in lines:
        n = len(ln.text)
        if n >= 12 and ln.size > 0:
            samples.extend([ln.size] * max(1, n // 12))
    if not samples:
        samples = [ln.size for ln in lines if ln.size > 0]
    return statistics.median(samples) if samples else 10.0


def _median_gap(lines: list[Line]) -> float:
    gaps = []
    for a, b in zip(lines, lines[1:]):
        gap = b.bbox[1] - a.bbox[3]
        if -2 < gap < 60:
            gaps.append(gap)
    return statistics.median(gaps) if gaps else 2.0


def _is_heading(ln: Line, body: float, page_width: float) -> bool:
    text = ln.text.strip()
    if not text or len(text) > 160:
        return False
    if text.endswith((".", ";", ",")) and len(text) > 60:
        return False

    size_ratio = ln.size / body if body else 1.0
    width_ratio = (ln.bbox[2] - ln.bbox[0]) / page_width if page_width else 1.0
    short = width_ratio < 0.85 and len(text) <= 120

    if size_ratio >= 1.18 and short:
        return True
    if ln.bold_ratio > 0.65 and short and size_ratio >= 0.98:
        return True
    if heading_number(text) and short and (size_ratio >= 1.05 or ln.bold_ratio > 0.4):
        return True
    letters = [c for c in text if c.isalpha()]
    if (letters and sum(c.isupper() for c in letters) / len(letters) > 0.85
            and 3 <= len(text) <= 80 and size_ratio >= 1.02):
        return True
    return False


def _heading_level(ln: Line, body: float, size_ranks: list[float]) -> int:
    num = heading_number(ln.text.strip())
    if num:
        # El h1 se reserva para el titulo del documento.
        return min(6, num.count(".") + 2)
    for idx, size in enumerate(size_ranks):
        if abs(ln.size - size) < 0.35:
            return min(6, idx + 1)
    ratio = ln.size / body if body else 1.0
    if ratio >= 1.6:
        return 1
    if ratio >= 1.35:
        return 2
    if ratio >= 1.15:
        return 3
    return 4


def _join_lines_text(lines: list[Line]) -> str:
    """Texto de un parrafo, uniendo palabras cortadas por guion."""
    parts: list[str] = []
    for ln in lines:
        t = ln.text.strip()
        if not t:
            continue
        if parts:
            merged = dehyphenate(parts[-1], t)
            if merged is not None:
                parts[-1] = merged
                continue
        parts.append(t)
    return " ".join(parts)


def lines_to_blocks(lines: list[Line], page_width: float,
                    detect_headings: bool = True) -> list[Block]:
    """Convierte renglones en parrafos, titulos y elementos de lista."""
    if not lines:
        return []

    body = _body_size(lines)
    gap = _median_gap(lines)
    heading_sizes = sorted(
        {round(ln.size, 1) for ln in lines
         if detect_headings and _is_heading(ln, body, page_width)},
        reverse=True,
    )

    blocks: list[Block] = []
    buffer: list[Line] = []
    buf_marker = ""
    buf_ordered = False
    buf_indent = 0

    def flush(kind: str | None = None):
        """kind=None -> deduce lista o parrafo segun el marcador acumulado."""
        nonlocal buffer, buf_marker, buf_ordered, buf_indent
        if not buffer:
            return
        text = _join_lines_text(buffer)
        if text:
            k = kind or ("list_item" if buf_marker else "paragraph")
            if k == "paragraph" and is_probably_caption(text) and len(text) < 200:
                k = "caption"
            blocks.append(
                Block(kind=k, lines=list(buffer), marker=buf_marker,
                      ordered=buf_ordered, indent=buf_indent)
            )
        buffer, buf_marker, buf_ordered, buf_indent = [], "", False, 0

    left_edge = min(ln.bbox[0] for ln in lines)
    ocr_bullets = detect_ocr_bullets(lines)
    prev: Line | None = None

    for line_idx, ln in enumerate(lines):
        text = ln.text.strip()
        if not text:
            continue

        if detect_headings and _is_heading(ln, body, page_width):
            lvl = _heading_level(ln, body, heading_sizes)
            # Un titulo largo ocupa dos renglones: se une al anterior en vez de
            # generar dos encabezados sueltos.
            if (blocks and blocks[-1].kind == "heading"
                    and blocks[-1].level == lvl and prev is not None
                    and ln.bbox[1] - prev.bbox[3] < max(ln.size, 6) * 0.9
                    and abs(ln.size - blocks[-1].lines[-1].size) < 0.4):
                blocks[-1].lines.append(ln)
                prev = ln
                continue
            flush()
            blocks.append(Block(kind="heading", level=lvl, lines=[ln]))
            prev = ln
            continue

        first = ln.words[0] if ln.words else None
        marker = list_marker(text, first.text if first else "",
                             first.font if first else "")
        if marker is None and line_idx in ocr_bullets and first is not None:
            marker = (first.text, False)
        if marker:
            flush()
            buffer = [ln]
            buf_marker, buf_ordered = marker
            buf_indent = int(max(0, (ln.bbox[0] - left_edge)) // 18)
            prev = ln
            continue

        if prev is not None:
            v_gap = ln.bbox[1] - prev.bbox[3]
            new_para = v_gap > max(gap * 1.8, gap + 3.0)
            # sangria de primera linea tras un punto final
            indent_break = (
                ln.bbox[0] - prev.bbox[0] > 10
                and prev.text.rstrip().endswith((".", ":", "?", "!"))
            )
            if new_para or indent_break:
                flush()

        buffer.append(ln)
        prev = ln

    flush()
    return blocks


def bbox_overlap_ratio(a: BBox, b: BBox) -> float:
    """Fraccion del area de `a` que cae dentro de `b`."""
    ix0, iy0 = max(a[0], b[0]), max(a[1], b[1])
    ix1, iy1 = min(a[2], b[2]), min(a[3], b[3])
    if ix1 <= ix0 or iy1 <= iy0:
        return 0.0
    inter = (ix1 - ix0) * (iy1 - iy0)
    area_a = max((a[2] - a[0]) * (a[3] - a[1]), 1e-6)
    return inter / area_a
