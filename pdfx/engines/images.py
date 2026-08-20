"""Extraccion de imagenes incrustadas en el PDF (via PDFium).

PDFium entrega las cajas en coordenadas PDF (origen abajo-izquierda); aqui se
convierten a top-down para encajar con el resto del modelo.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pypdfium2 as pdfium
import pypdfium2.raw as raw
from PIL import Image

from ..model import ImageRef

log = logging.getLogger(__name__)

# Formatos con canal alfa que no pueden guardarse como JPEG sin aplanar.
_ALPHA_MODES = {"RGBA", "LA", "P"}


def _to_topdown(bounds, page_height: float):
    x0, y0, x1, y1 = bounds
    left, right = min(x0, x1), max(x0, x1)
    bottom_pdf, top_pdf = min(y0, y1), max(y0, y1)
    return (left, page_height - top_pdf, right, page_height - bottom_pdf)


def _save(img: Image.Image, dest: Path, fmt: str) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if fmt == "jpg":
        if img.mode in _ALPHA_MODES:
            bg = Image.new("RGB", img.size, (255, 255, 255))
            rgba = img.convert("RGBA")
            bg.paste(rgba, mask=rgba.split()[-1])
            img = bg
        elif img.mode != "RGB":
            img = img.convert("RGB")
        img.save(dest, "JPEG", quality=88, optimize=True)
    else:
        img.save(dest, "PNG", optimize=True)


def extract_page_images(
    pdf_page: "pdfium.PdfPage",
    page_number: int,
    media_dir: Path,
    rel_prefix: str,
    min_px: int = 64,
    fmt: str = "png",
) -> list[ImageRef]:
    """Guarda cada imagen incrustada de la pagina y devuelve sus referencias."""
    refs: list[ImageRef] = []
    page_height = pdf_page.get_height()
    seen: set[tuple] = set()
    idx = 0

    try:
        objects = list(pdf_page.get_objects(max_depth=6))
    except Exception as exc:
        log.warning("No se pudieron listar objetos de la pagina %s: %s", page_number, exc)
        return refs

    for obj in objects:
        if getattr(obj, "type", None) != raw.FPDF_PAGEOBJ_IMAGE:
            continue
        try:
            w_px, h_px = obj.get_px_size()
        except Exception:
            continue
        if w_px < min_px or h_px < min_px:
            continue  # iconos, filetes, sellos diminutos

        try:
            bounds = obj.get_bounds()
        except Exception:
            bounds = (0.0, 0.0, 0.0, 0.0)
        bbox = _to_topdown(bounds, page_height)

        # Dedupe: mismo tamano y misma posicion => logo repetido en la pagina.
        key = (w_px, h_px, round(bbox[0], 1), round(bbox[1], 1))
        if key in seen:
            continue
        seen.add(key)

        idx += 1
        name = f"p{page_number:03d}_img{idx:02d}.{fmt}"
        dest = media_dir / name
        try:
            pil = obj.get_bitmap(render=False).to_pil()
            _save(pil, dest, fmt)
        except Exception as exc:
            log.debug("Bitmap directo fallo (%s); reintento con render", exc)
            try:
                pil = obj.get_bitmap(render=True).to_pil()
                _save(pil, dest, fmt)
            except Exception as exc2:
                log.warning("Imagen %s de pagina %s no extraida: %s", idx, page_number, exc2)
                idx -= 1
                continue

        refs.append(
            ImageRef(
                path=Path(rel_prefix) / name,
                abs_path=dest,
                bbox=bbox,
                width=w_px,
                height=h_px,
                kind="embedded",
            )
        )
    return refs


def save_page_render(
    rendered_image: Image.Image,
    page_number: int,
    media_dir: Path,
    rel_prefix: str,
    fmt: str = "png",
    max_width: int = 1600,
) -> ImageRef:
    """Guarda la pagina completa como imagen (paginas escaneadas sin objetos)."""
    img = rendered_image
    if img.width > max_width:
        ratio = max_width / img.width
        img = img.resize((max_width, int(img.height * ratio)), Image.LANCZOS)
    name = f"p{page_number:03d}_pagina.{fmt}"
    dest = media_dir / name
    _save(img, dest, fmt)
    return ImageRef(
        path=Path(rel_prefix) / name,
        abs_path=dest,
        bbox=(0.0, 0.0, 0.0, 0.0),
        width=img.width,
        height=img.height,
        kind="page-render",
    )
