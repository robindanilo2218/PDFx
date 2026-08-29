"""Salidas de datos: JSON estructurado y texto plano."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from ..config import Settings
from ..model import Block, Document, ImageRef, Table


def to_dict(doc: Document, redaction_note: str = "") -> dict:
    return {
        "origen": doc.source_path.name,
        "titulo": doc.title,
        "autor": doc.author,
        "convertido": dt.datetime.now().isoformat(timespec="seconds"),
        "herramienta": "PDFx",
        "saneado": redaction_note or None,
        "resumen": {
            "paginas": doc.n_pages,
            "tablas": doc.n_tables,
            "imagenes": doc.n_images,
            "paginas_ocr": doc.n_ocr_pages,
            "caracteres": doc.char_count,
            "segundos": round(doc.elapsed_s, 2),
        },
        "avisos": doc.warnings,
        "paginas": [
            {
                "numero": p.number,
                "origen": p.source,
                "confianza_ocr": round(p.ocr_conf, 1) if p.ocr_conf else None,
                "notas": p.notes,
                "elementos": [_element_dict(e) for e in p.elements],
            }
            for p in doc.pages
        ],
    }


def _element_dict(el) -> dict:
    if isinstance(el, Block):
        return {
            "tipo": el.kind, "nivel": el.level or None, "texto": el.text,
            "caja": [round(v, 1) for v in el.bbox],
        }
    if isinstance(el, Table):
        return {
            "tipo": "tabla", "filas": el.normalized(),
            "deteccion": el.source, "fiabilidad": round(el.confidence, 3),
            "caja": [round(v, 1) for v in el.bbox],
        }
    if isinstance(el, ImageRef):
        return {
            "tipo": "imagen", "ruta": el.path.as_posix() if el.path else None,
            "ancho": el.width, "alto": el.height, "clase": el.kind,
            "caja": [round(v, 1) for v in el.bbox],
        }
    return {"tipo": "desconocido"}


def write_json(doc: Document, dest: Path, settings: Settings,
               redaction_note: str = "") -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(
        json.dumps(to_dict(doc, redaction_note), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return dest


def write_txt(doc: Document, dest: Path, settings: Settings,
              redaction_note: str = "") -> Path:
    parts: list[str] = []
    for page in doc.pages:
        if settings.keep_page_marks:
            parts.append(f"===== PAGINA {page.number} =====")
        for el in page.elements:
            if isinstance(el, Block):
                if el.text.strip():
                    parts.append(el.text)
            elif isinstance(el, Table):
                for row in el.normalized():
                    parts.append("\t".join(row))
                parts.append("")
            elif isinstance(el, ImageRef) and el.path:
                parts.append(f"[imagen: {el.path.as_posix()}]")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text("\n\n".join(parts).rstrip() + "\n", encoding="utf-8")
    return dest
