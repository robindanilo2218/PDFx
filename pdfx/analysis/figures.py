"""Recorte de figuras y diagramas en paginas escaneadas.

En un PDF escaneado toda la pagina es una sola imagen, asi que no hay "imagenes
incrustadas" que extraer. Aqui se localizan las zonas con tinta que el OCR no
reconocio como texto (esquemas, planos, fotos, sellos) y se recortan.

Metodo: rejilla gruesa sobre la pagina binarizada -> se descartan las celdas
ocupadas por palabras -> las celdas restantes con tinta se agrupan por
conectividad y cada grupo se recorta.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from PIL import Image

from ..engines.preprocess import binarize
from ..model import Word


@dataclass(slots=True)
class FigureRegion:
    x0: float
    top: float
    x1: float
    bottom: float
    ink: float

    @property
    def bbox(self):
        return (self.x0, self.top, self.x1, self.bottom)

    @property
    def width(self) -> float:
        return self.x1 - self.x0

    @property
    def height(self) -> float:
        return self.bottom - self.top


def _label_components(mask: np.ndarray) -> tuple[np.ndarray, int]:
    """Etiquetado por conectividad-8 sobre una rejilla pequena (BFS iterativo)."""
    h, w = mask.shape
    labels = np.zeros((h, w), dtype=np.int32)
    current = 0
    neighbours = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]

    for sy in range(h):
        for sx in range(w):
            if not mask[sy, sx] or labels[sy, sx]:
                continue
            current += 1
            stack = [(sy, sx)]
            labels[sy, sx] = current
            while stack:
                y, x = stack.pop()
                for dy, dx in neighbours:
                    ny, nx = y + dy, x + dx
                    if 0 <= ny < h and 0 <= nx < w and mask[ny, nx] and not labels[ny, nx]:
                        labels[ny, nx] = current
                        stack.append((ny, nx))
    return labels, current


def find_figures(
    gray: np.ndarray,
    scale: float,
    words: list[Word],
    cell_pt: float = 6.0,
    min_width_pt: float = 45.0,
    min_height_pt: float = 40.0,
    min_area_ratio: float = 0.012,
    max_area_ratio: float = 0.92,
) -> list[FigureRegion]:
    """Zonas graficas de la pagina, en puntos PDF."""
    h_px, w_px = gray.shape
    page_w_pt, page_h_pt = w_px / scale, h_px / scale
    cell_px = max(4, int(cell_pt * scale))
    gy, gx = max(1, h_px // cell_px), max(1, w_px // cell_px)
    if gy < 4 or gx < 4:
        return []

    ink = binarize(gray)
    # Media de tinta por celda de la rejilla.
    trimmed = ink[: gy * cell_px, : gx * cell_px]
    density = trimmed.reshape(gy, cell_px, gx, cell_px).mean(axis=(1, 3))

    # Celdas ocupadas por texto reconocido (con un margen de una celda).
    text_cells = np.zeros((gy, gx), dtype=bool)
    for word in words:
        a = int(max(0, word.x0 * scale) // cell_px) - 1
        b = int(min(w_px, word.x1 * scale) // cell_px) + 1
        c = int(max(0, word.top * scale) // cell_px) - 1
        d = int(min(h_px, word.bottom * scale) // cell_px) + 1
        text_cells[max(0, c):min(gy, d + 1), max(0, a):min(gx, b + 1)] = True

    candidate = (density > 0.035) & ~text_cells
    # Descarta el marco del escaneo (bordes negros del cristal).
    candidate[0, :] = candidate[-1, :] = False
    candidate[:, 0] = candidate[:, -1] = False
    if not candidate.any():
        return []

    labels, count = _label_components(candidate)
    page_area = page_w_pt * page_h_pt
    regions: list[FigureRegion] = []

    for lab in range(1, count + 1):
        ys, xs = np.nonzero(labels == lab)
        if ys.size < 4:
            continue
        x0 = xs.min() * cell_px / scale
        x1 = (xs.max() + 1) * cell_px / scale
        top = ys.min() * cell_px / scale
        bottom = (ys.max() + 1) * cell_px / scale
        width, height = x1 - x0, bottom - top
        if width < min_width_pt or height < min_height_pt:
            continue
        area_ratio = (width * height) / page_area
        if not (min_area_ratio <= area_ratio <= max_area_ratio):
            continue
        # Filetes largos y finos: son rayas de tabla, no figuras.
        if width / max(height, 1) > 25 or height / max(width, 1) > 25:
            continue
        # La caja debe estar razonablemente llena; si no, son restos dispersos.
        fill = ys.size / max(1, (xs.max() - xs.min() + 1) * (ys.max() - ys.min() + 1))
        if fill < 0.18:
            continue
        regions.append(
            FigureRegion(x0, top, x1, bottom, float(density[ys, xs].mean()))
        )

    regions.sort(key=lambda r: (r.top, r.x0))
    return _merge_close(regions)


def _merge_close(regions: list[FigureRegion], gap_pt: float = 14.0) -> list[FigureRegion]:
    """Une trozos del mismo dibujo separados por huecos pequenos."""
    merged: list[FigureRegion] = []
    for reg in regions:
        placed = False
        for i, other in enumerate(merged):
            if (reg.x0 < other.x1 + gap_pt and other.x0 < reg.x1 + gap_pt
                    and reg.top < other.bottom + gap_pt and other.top < reg.bottom + gap_pt):
                merged[i] = FigureRegion(
                    min(reg.x0, other.x0), min(reg.top, other.top),
                    max(reg.x1, other.x1), max(reg.bottom, other.bottom),
                    max(reg.ink, other.ink),
                )
                placed = True
                break
        if not placed:
            merged.append(reg)
    return merged


def crop_region(image: Image.Image, region: FigureRegion, scale: float,
                pad_pt: float = 4.0) -> Image.Image:
    pad = pad_pt * scale
    box = (
        max(0, int(region.x0 * scale - pad)),
        max(0, int(region.top * scale - pad)),
        min(image.width, int(region.x1 * scale + pad)),
        min(image.height, int(region.bottom * scale + pad)),
    )
    return image.crop(box)
