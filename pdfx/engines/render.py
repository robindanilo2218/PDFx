"""Rasterizado de paginas con PDFium (licencia BSD-3, sin dependencias de red)."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from PIL import Image

PT_PER_INCH = 72.0


@dataclass(slots=True)
class RenderedPage:
    image: Image.Image
    dpi: int
    scale: float          # pixeles por punto PDF
    width_pt: float
    height_pt: float

    def px_to_pt(self, value: float) -> float:
        return value / self.scale

    def box_to_pt(self, x0: float, top: float, x1: float, bottom: float):
        s = self.scale
        return (x0 / s, top / s, x1 / s, bottom / s)

    def to_gray_array(self) -> np.ndarray:
        img = self.image if self.image.mode == "L" else self.image.convert("L")
        return np.asarray(img, dtype=np.uint8)


def render_page(pdf_page, dpi: int = 300, grayscale: bool = False) -> RenderedPage:
    """Rasteriza una pagina de pypdfium2 a la resolucion pedida."""
    scale = dpi / PT_PER_INCH
    w_pt, h_pt = pdf_page.get_size()
    bitmap = pdf_page.render(scale=scale, grayscale=grayscale, draw_annots=True)
    image = bitmap.to_pil()
    if grayscale and image.mode != "L":
        image = image.convert("L")
    return RenderedPage(
        image=image,
        dpi=dpi,
        scale=scale,
        width_pt=w_pt,
        height_pt=h_pt,
    )


def cap_dpi_for_size(width_pt: float, height_pt: float, dpi: int,
                     max_pixels: int = 40_000_000) -> int:
    """Baja el DPI si la pagina es enorme (planos A0) para no agotar la RAM."""
    px = (width_pt / PT_PER_INCH * dpi) * (height_pt / PT_PER_INCH * dpi)
    if px <= max_pixels:
        return dpi
    factor = (max_pixels / px) ** 0.5
    return max(120, int(dpi * factor))
