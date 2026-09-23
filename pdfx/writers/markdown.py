"""Salida Markdown (GitHub Flavored).

Pensada para dos usos a la vez:
  - lectura humana / control de versiones,
  - alimentar a un asistente sin subir el PDF original.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

from ..config import Settings
from ..model import Block, Document, ImageRef, Page, Table
from ..util.text import escape_md, fold, token_estimate

CLAUDE_HEADER = (
    "> **Documento convertido a texto plano.** Este fichero contiene el "
    "contenido completo del documento original (texto, tablas y referencias a "
    "las imagenes) ya extraido. Trabaja directamente sobre este texto: no hace "
    "falta el PDF ni ninguna herramienta adicional para leerlo.\n>\n"
    "> El campo `resumen` de la cabecera esta vacio porque PDFx no entiende "
    "el contenido, solo lo extrae. Si vas a trabajar con este documento, "
    "escribe ahi un resumen breve (2-4 lineas) de que trata y que preguntas "
    "responde, editando el fichero directamente. Asi, la proxima vez que "
    "alguien -tu u otro asistente- necesite saber si este documento sirve "
    "para algo, le basta con leer `esquema` y `resumen` en la cabecera, sin "
    "releer el fichero entero."
)

MAX_ITEMS_ESQUEMA = 60


def _yaml_escape(value: str) -> str:
    value = (value or "").replace('"', "'").replace("\n", " ").strip()
    return f'"{value}"' if value else '""'


def _esquema(doc: Document) -> list[str]:
    """Indice de encabezados: esto si lo puede sacar el conversor solo, a
    diferencia del resumen, porque son marcas de estructura (# ## ###...)
    que ya vienen del documento, no algo que haya que entender."""
    items: list[str] = []
    for page in doc.pages:
        for el in page.elements:
            if isinstance(el, Block) and el.kind == "heading":
                texto = el.text.strip()
                if texto:
                    nivel = max(1, min(6, el.level or 2))
                    items.append("#" * nivel + " " + texto)
    return items


def front_matter(doc: Document, settings: Settings, redaction_note: str = "") -> str:
    ocr_pages = doc.n_ocr_pages
    lines = [
        "---",
        f"origen: {_yaml_escape(doc.source_path.name)}",
        f"titulo: {_yaml_escape(doc.title or doc.source_path.stem)}",
    ]
    if doc.author:
        lines.append(f"autor: {_yaml_escape(doc.author)}")
    lines += [
        f"paginas: {doc.n_pages}",
        f"tablas: {doc.n_tables}",
        f"imagenes: {doc.n_images}",
        f"ocr: {'si' if ocr_pages else 'no'}"
        + (f" ({ocr_pages} de {doc.n_pages} paginas)" if ocr_pages else ""),
        f"convertido: {dt.datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "herramienta: PDFx (conversion local, sin conexion)",
    ]
    if redaction_note:
        lines.append(f"saneado: {_yaml_escape(redaction_note)}")
    esquema = _esquema(doc)
    if esquema:
        lines.append("esquema:")
        lines.extend(f"  - {_yaml_escape(h)}" for h in esquema[:MAX_ITEMS_ESQUEMA])
        if len(esquema) > MAX_ITEMS_ESQUEMA:
            lines.append(f'  - "(+{len(esquema) - MAX_ITEMS_ESQUEMA} encabezados mas)"')
    if settings.md_claude_header:
        lines.append('resumen: ""')
    lines.append("---")
    return "\n".join(lines)


def _table_md(table: Table) -> str:
    rows = table.normalized()
    if not rows:
        return ""
    n_cols = len(rows[0])

    def cell(text: str) -> str:
        return escape_md(text).replace("\n", "<br>").strip() or " "

    out: list[str] = []
    if table.has_header and len(rows) > 1:
        header, body = rows[0], rows[1:]
    else:
        header, body = [""] * n_cols, rows

    out.append("| " + " | ".join(cell(c) for c in header) + " |")
    out.append("|" + "|".join(["---"] * n_cols) + "|")
    for row in body:
        out.append("| " + " | ".join(cell(c) for c in row) + " |")
    return "\n".join(out)


def _image_md(ref: ImageRef) -> str:
    if ref.path is None:
        return ""
    rel = ref.path.as_posix()
    alt = ref.caption or f"Imagen {ref.path.stem}"
    return f"![{escape_md(alt)}]({rel})"


def _block_md(block: Block) -> str:
    text = block.text.strip()
    if not text:
        return ""
    if block.kind == "heading":
        return "#" * max(1, min(6, block.level or 2)) + " " + text
    if block.kind == "list_item":
        indent = "  " * min(block.indent, 4)
        bullet = "1." if block.ordered else "-"
        body = text
        if block.marker and body.startswith(block.marker):
            body = body[len(block.marker):].lstrip()
        return f"{indent}{bullet} {body}"
    if block.kind == "caption":
        return f"*{text}*"
    return text


def render_page(page: Page, settings: Settings) -> str:
    parts: list[str] = []
    if settings.keep_page_marks:
        parts.append(f"<!-- pagina {page.number} -->")

    prev_list = False
    for el in page.elements:
        if isinstance(el, Block):
            chunk = _block_md(el)
            is_list = el.kind == "list_item"
            if chunk:
                # los items consecutivos no llevan linea en blanco entre ellos
                if prev_list and is_list and parts:
                    parts[-1] = parts[-1] + "\n" + chunk
                else:
                    parts.append(chunk)
            prev_list = is_list
        elif isinstance(el, Table):
            chunk = _table_md(el)
            if chunk:
                parts.append(chunk)
            prev_list = False
        elif isinstance(el, ImageRef):
            chunk = _image_md(el)
            if chunk:
                parts.append(chunk)
            prev_list = False

    if page.source == "empty" and not page.blocks:
        parts.append("*(Pagina sin texto reconocible.)*")
    return "\n\n".join(p for p in parts if p.strip())


def _title_already_in_body(doc: Document, title: str) -> bool:
    """Evita el duplicado '# Informe' + '# Informe de mantenimiento...'."""
    for page in doc.pages[:1]:
        for el in page.elements:
            if isinstance(el, Block) and el.kind == "heading":
                a, b = fold(el.text), fold(title)
                return bool(a) and (a.startswith(b) or b.startswith(a))
            if isinstance(el, Block):
                return False
    return False


def render(doc: Document, settings: Settings, redaction_note: str = "") -> str:
    parts: list[str] = []
    if settings.md_claude_header or not settings.fast_mode:
        parts.append(front_matter(doc, settings, redaction_note))
    if settings.md_claude_header:
        parts.append(CLAUDE_HEADER)

    title = doc.title.strip() or doc.source_path.stem
    if not _title_already_in_body(doc, title):
        parts.append(f"# {title}")

    primera_pagina = True
    for page in doc.pages:
        body = render_page(page, settings)
        if body:
            if settings.md_slide_breaks and not primera_pagina:
                parts.append("---")
            parts.append(body)
            primera_pagina = False

    if doc.warnings:
        parts.append(
            "---\n\n**Avisos de la conversion**\n\n"
            + "\n".join(f"- {w}" for w in doc.warnings)
        )

    return "\n\n".join(p for p in parts if p.strip()).rstrip() + "\n"


def write(doc: Document, dest: Path, settings: Settings,
          redaction_note: str = "") -> Path:
    text = render(doc, settings, redaction_note)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(text, encoding="utf-8")
    return dest


def estimate_tokens(doc: Document, settings: Settings) -> int:
    return token_estimate(render(doc, settings))
