"""Orquestador: PDF -> modelo `Document`.

Decide por pagina si usa la capa de texto nativa o pasa por OCR, extrae tablas,
imagenes y figuras, y ordena todo en orden de lectura.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import numpy as np
import pdfplumber
import pypdfium2 as pdfium

from .analysis.figures import crop_region, find_figures
from .analysis.layout import (
    Column, bbox_overlap_ratio, detect_columns, group_words_into_lines,
    lines_to_blocks,
)
from .analysis.tables_native import find_tables as find_native_tables
from .analysis.tables_ocr import find_ruled_tables, find_whitespace_tables
from .config import Settings
from .engines import images as image_engine
from .engines.ocr import (
    OcrUnavailable, find_tesseract, ocr_image, ocr_text, resolve_langs,
)
from .engines.pdf_native import extract_words, page_has_usable_text
from .engines.preprocess import prepare_for_ocr
from .engines.render import cap_dpi_for_size, render_page
from .model import Block, Document, ImageRef, Page, Table, Word
from .util.pages import parse_page_range

log = logging.getLogger(__name__)

ProgressFn = Callable[[str, float], None]


def _noop(_msg: str, _frac: float) -> None:
    pass


class PdfxError(RuntimeError):
    pass


@dataclass
class PageContext:
    """Estado compartido al procesar una pagina."""
    number: int
    width: float
    height: float
    words: list[Word]
    source: str
    ocr_conf: float = 0.0
    gray: np.ndarray | None = None
    scale: float = 1.0
    rendered = None
    notes: list[str] = None


# --------------------------------------------------------------------------
def build_document(
    src: Path,
    settings: Settings,
    media_dir: Path | None = None,
    rel_prefix: str = "media",
    progress: ProgressFn = _noop,
    cancel: Callable[[], bool] = lambda: False,
) -> Document:
    """Construye el modelo de documento a partir de un PDF."""
    src = Path(src)
    if not src.exists():
        raise PdfxError(f"No existe el fichero: {src}")

    started = time.time()
    doc = Document(source_path=src)

    tess_path = None
    langs = settings.ocr_langs
    if settings.ocr != "never":
        tess_path = find_tesseract(settings.tesseract_path)
        if tess_path is None:
            if settings.ocr == "always":
                raise PdfxError(
                    "Se pidio OCR pero no se encontro Tesseract. Instalalo o copia "
                    "la carpeta 'tools/tesseract' junto al ejecutable."
                )
            doc.warnings.append(
                "Tesseract no encontrado: las paginas escaneadas quedaran vacias."
            )
        else:
            langs = resolve_langs(tess_path, settings.ocr_langs)
            doc.engine_notes["ocr"] = f"tesseract {langs}"

    try:
        pdfium_doc = pdfium.PdfDocument(str(src))
    except Exception as exc:
        raise PdfxError(f"No se pudo abrir el PDF: {exc}") from exc

    try:
        _read_metadata(pdfium_doc, doc)
        with pdfplumber.open(str(src)) as plumber_doc:
            total = len(plumber_doc.pages)
            selected = parse_page_range(settings.page_range, total)
            doc.engine_notes["paginas"] = f"{len(selected)} de {total}"

            for idx, page_no in enumerate(selected):
                if cancel():
                    doc.warnings.append("Conversion cancelada por el usuario.")
                    break
                progress(f"Pagina {page_no} de {total}", idx / max(len(selected), 1))
                try:
                    page = _process_page(
                        plumber_doc.pages[page_no - 1],
                        pdfium_doc[page_no - 1],
                        page_no,
                        settings,
                        tess_path,
                        langs,
                        media_dir,
                        rel_prefix,
                    )
                except Exception as exc:
                    log.exception("Fallo en la pagina %s", page_no)
                    doc.warnings.append(f"Pagina {page_no}: {exc}")
                    page = Page(number=page_no, source="empty",
                                notes=[f"Error: {exc}"])
                doc.pages.append(page)
    finally:
        try:
            pdfium_doc.close()
        except Exception:
            pass

    if not doc.title:
        doc.title = _title_from_content(doc)

    doc.elapsed_s = time.time() - started
    progress("Listo", 1.0)
    return doc


def _title_from_content(doc: Document) -> str:
    """Sin metadatos, el titulo es el primer encabezado destacado del documento."""
    for page in doc.pages[:2]:
        for el in page.elements:
            if isinstance(el, Block) and el.kind == "heading":
                text = el.text.strip()
                if el.level <= 2 and 4 <= len(text) <= 120:
                    return text
                return ""
            if isinstance(el, Block):
                return ""
    return ""


def _read_metadata(pdfium_doc, doc: Document) -> None:
    try:
        meta = pdfium_doc.get_metadata_dict()
    except Exception:
        meta = {}
    doc.title = (meta.get("Title") or "").strip()
    doc.author = (meta.get("Author") or "").strip()
    doc.subject = (meta.get("Subject") or "").strip()
    doc.producer = (meta.get("Producer") or "").strip()
    doc.created = (meta.get("CreationDate") or "").strip()


# --------------------------------------------------------------------------
def _process_page(
    plumber_page,
    pdfium_page,
    page_no: int,
    settings: Settings,
    tess_path: Path | None,
    langs: str,
    media_dir: Path | None,
    rel_prefix: str,
) -> Page:
    width = float(plumber_page.width or pdfium_page.get_width())
    height = float(plumber_page.height or pdfium_page.get_height())
    page = Page(number=page_no, width=width, height=height,
                rotation=int(pdfium_page.get_rotation() or 0))

    native = extract_words(plumber_page)
    use_native = (
        settings.ocr == "never"
        or (settings.ocr == "auto"
            and page_has_usable_text(native, settings.native_char_threshold))
    )

    rendered = None
    gray = None
    scale = 1.0
    words: list[Word] = []

    if use_native:
        words = native.words
        page.source = "text"
    else:
        if tess_path is None:
            page.source = "empty"
            page.notes.append("Pagina sin texto y sin OCR disponible.")
            return page
        dpi = cap_dpi_for_size(width, height, settings.ocr_dpi)
        if dpi != settings.ocr_dpi:
            page.notes.append(f"DPI reducido a {dpi} por el tamano de la pagina.")
        rendered = render_page(pdfium_page, dpi=dpi, grayscale=True)
        scale = rendered.scale
        # Se endereza una sola vez: el OCR, el rayado de tablas y el recorte de
        # figuras deben ver exactamente los mismos pixeles.
        prepared, angle = prepare_for_ocr(rendered.image, do_deskew=settings.deskew)
        rendered.image = prepared
        try:
            result = ocr_image(
                prepared, tess_path, scale,
                langs=langs, psm=settings.ocr_psm,
                min_conf=settings.ocr_min_conf, preprocess=False,
            )
        except OcrUnavailable:
            raise
        except Exception as exc:
            page.notes.append(f"OCR fallido: {exc}")
            page.source = "empty"
            return page

        words = result.words
        page.ocr_conf = result.mean_conf
        page.source = "ocr"
        if abs(angle) >= 0.2:
            page.notes.append(f"Escaneo enderezado {angle:+.2f} grados.")
        if native.char_count > 0 and native.garbage:
            page.notes.append("Capa de texto ilegible; se reemplazo por OCR.")
        gray = rendered.to_gray_array()

    # ---- tablas ---------------------------------------------------------
    tables: list[Table] = []
    if settings.detect_tables:
        if page.source == "text":
            # pdfplumber ya prueba rayado y alineacion de texto.
            tables = find_native_tables(plumber_page)
        else:
            if gray is not None:
                cell_reader = None
                if tess_path is not None and rendered is not None:
                    cell_reader = _make_cell_reader(
                        rendered.image, scale, tess_path, langs
                    )
                tables = find_ruled_tables(gray, scale, words, cell_ocr=cell_reader)
            if not tables and words:
                lines_all = group_words_into_lines(words)
                tables = find_whitespace_tables(lines_all, width)

    # ---- palabras que ya estan dentro de una tabla ----------------------
    remaining = words
    if tables:
        boxes = [t.bbox for t in tables]
        remaining = [
            w for w in words
            if not any(bbox_overlap_ratio(w.bbox, b) > 0.55 for b in boxes)
        ]

    # ---- imagenes y figuras ---------------------------------------------
    image_refs: list[ImageRef] = []
    if settings.extract_images and media_dir is not None:
        image_refs = _collect_images(
            pdfium_page, rendered, gray, scale, words, page, page_no,
            settings, media_dir, rel_prefix, [t.bbox for t in tables],
        )

    # ---- bloques de texto ------------------------------------------------
    columns = [Column(0.0, width, remaining)]
    if remaining and settings.detect_columns:
        # Primero columnas (sobre palabras), luego renglones dentro de cada una.
        columns = detect_columns(remaining, width)
        if len(columns) > 1:
            page.notes.append(f"Maquetacion a {len(columns)} columnas.")

    blocks_by_col: list[list] = [[] for _ in columns]
    for c_idx, col in enumerate(columns):
        if not col.words:
            continue
        col_width = col.x1 - col.x0 if len(columns) > 1 else width
        lines = group_words_into_lines(col.words)
        blocks_by_col[c_idx].extend(
            lines_to_blocks(lines, col_width,
                            detect_headings=settings.detect_headings)
        )

    # ---- orden de lectura -------------------------------------------------
    # Se lee columna a columna, de izquierda a derecha; ordenar toda la pagina
    # por "top" mezclaria el texto de dos columnas.
    for el in (*tables, *image_refs):
        blocks_by_col[_column_index(el, columns)].append(el)

    elements: list = []
    for group in blocks_by_col:
        group.sort(key=lambda e: (round(e.bbox[1], 1), round(e.bbox[0], 1)))
        elements.extend(group)
    page.elements = elements

    return page


def _column_index(element, columns: list[Column]) -> int:
    """Columna a la que pertenece una tabla o imagen, por su centro."""
    if len(columns) == 1:
        return 0
    x0, _, x1, _ = element.bbox
    cx = (x0 + x1) / 2.0
    for i, col in enumerate(columns):
        if col.x0 <= cx < col.x1:
            return i
    # Un elemento a todo lo ancho (una tabla que cruza) va con la primera.
    return 0


def _make_cell_reader(image, scale: float, tess_path: Path, langs: str):
    """Devuelve una funcion que relee una celda concreta de la pagina."""
    def read(x0: float, top: float, x1: float, bottom: float) -> str:
        pad = 2.6 * scale   # deja fuera el filete de la celda
        box = (
            max(0, int(x0 * scale + pad)),
            max(0, int(top * scale + pad)),
            min(image.width, int(x1 * scale - pad)),
            min(image.height, int(bottom * scale - pad)),
        )
        if box[2] - box[0] < 6 or box[3] - box[1] < 6:
            return ""
        return ocr_text(image.crop(box), tess_path, langs=langs)

    return read


def _collect_images(
    pdfium_page, rendered, gray, scale, words, page, page_no,
    settings: Settings, media_dir: Path, rel_prefix: str,
    table_boxes: list | None = None,
) -> list[ImageRef]:
    refs: list[ImageRef] = []
    page_area = max(page.width * page.height, 1.0)

    embedded = image_engine.extract_page_images(
        pdfium_page, page_no, media_dir, rel_prefix,
        min_px=settings.min_image_px, fmt=settings.image_format,
    )

    for ref in embedded:
        x0, top, x1, bottom = ref.bbox
        area_ratio = ((x1 - x0) * (bottom - top)) / page_area
        # La imagen que ocupa casi toda la pagina es el propio escaneo.
        if area_ratio > 0.85 and page.source in ("ocr", "empty"):
            if settings.keep_page_scans:
                ref.kind = "page-scan"
                refs.append(ref)
            else:
                _discard(ref)
            continue
        refs.append(ref)

    # Figuras dentro de un escaneo: solo si no hubo imagenes utiles.
    if (settings.extract_figures and page.source in ("ocr", "empty")
            and gray is not None and rendered is not None and not refs):
        regions = find_figures(gray, scale, words)
        if table_boxes:
            # El rayado de una tabla tambien es "tinta sin texto": no es figura.
            regions = [
                r for r in regions
                if not any(bbox_overlap_ratio(r.bbox, tb) > 0.5 for tb in table_boxes)
            ]
        for i, region in enumerate(regions, start=1):
            crop = crop_region(rendered.image, region, scale)
            name = f"p{page_no:03d}_fig{i:02d}.{settings.image_format}"
            dest = media_dir / name
            try:
                image_engine._save(crop, dest, settings.image_format)
            except Exception as exc:
                log.warning("No se pudo guardar la figura %s: %s", name, exc)
                continue
            refs.append(
                ImageRef(path=Path(rel_prefix) / name, abs_path=dest,
                         bbox=region.bbox, width=crop.width, height=crop.height,
                         kind="region")
            )
        if regions:
            page.notes.append(f"{len(regions)} figura(s) recortada(s) del escaneo.")

    return refs


def _discard(ref: ImageRef) -> None:
    try:
        if ref.abs_path and ref.abs_path.exists():
            ref.abs_path.unlink()
    except OSError:
        pass
