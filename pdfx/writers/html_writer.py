"""Salida HTML autocontenida: para ver e imprimir sin instalar nada."""

from __future__ import annotations

import base64
import datetime as dt
import html
import mimetypes
from pathlib import Path

from ..config import Settings
from ..model import Block, Document, ImageRef, Table

# Por encima de este total, las imagenes se enlazan en vez de incrustarse.
_EMBED_BUDGET = 12 * 1024 * 1024

_CSS = """
:root { color-scheme: light dark; }
* { box-sizing: border-box; }
body { margin: 0 auto; padding: 2.2rem 1.4rem 5rem; max-width: 52rem;
  font: 16px/1.65 -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  color: #1c1f24; background: #fff; }
h1,h2,h3,h4,h5,h6 { line-height:1.25; margin:2rem 0 .6rem; font-weight:650; }
h1 { font-size:1.9rem; border-bottom:2px solid #e3e6ea; padding-bottom:.4rem; }
h2 { font-size:1.45rem; } h3 { font-size:1.2rem; } h4 { font-size:1.05rem; }
p { margin: .7rem 0; }
ul,ol { margin:.6rem 0 .6rem 1.4rem; }
em.caption { display:block; text-align:center; color:#5b6470; font-size:.9rem; }
img { max-width:100%; height:auto; display:block; margin:1.2rem auto;
  border:1px solid #e3e6ea; border-radius:6px; }
.tablewrap { overflow-x:auto; margin:1.1rem 0; }
table { border-collapse:collapse; width:100%; font-size:.92rem; }
th,td { border:1px solid #d7dbe0; padding:.42rem .6rem; text-align:left;
  vertical-align:top; }
th { background:#eef2f6; font-weight:650; }
tbody tr:nth-child(even) { background:#fafbfc; }
.meta { background:#f5f7f9; border:1px solid #e3e6ea; border-radius:8px;
  padding:.9rem 1.1rem; font-size:.9rem; color:#48505a; margin-bottom:1.6rem; }
.meta b { color:#1c1f24; }
.pagemark { margin:2.4rem 0 .8rem; border-top:1px dashed #ccd2d8;
  padding-top:.4rem; font-size:.75rem; color:#98a1ac; letter-spacing:.05em; }
.warn { background:#fff6e5; border:1px solid #f0d5a0; border-radius:8px;
  padding:.9rem 1.1rem; margin-top:2rem; font-size:.9rem; }
@media (prefers-color-scheme: dark) {
  body { color:#e6e9ed; background:#16191d; }
  h1 { border-color:#2c3138; }
  th { background:#232830; } th,td { border-color:#2c3138; }
  tbody tr:nth-child(even) { background:#1b1f24; }
  .meta { background:#1b1f24; border-color:#2c3138; color:#aeb6c0; }
  .meta b { color:#e6e9ed; }
  img { border-color:#2c3138; }
  .warn { background:#2a2313; border-color:#5c4a1c; }
}
@media print {
  body { max-width:none; padding:0; color:#000; background:#fff; }
  .pagemark { break-before:page; }
  img,table { break-inside:avoid; }
}
"""


def _esc(text: str) -> str:
    return html.escape(text or "", quote=False)


def _img_src(ref: ImageRef, budget: list[int]) -> str:
    if not ref.abs_path or not ref.abs_path.exists():
        return ref.path.as_posix() if ref.path else ""
    try:
        size = ref.abs_path.stat().st_size
        if size <= budget[0]:
            mime = mimetypes.guess_type(ref.abs_path.name)[0] or "image/png"
            data = base64.b64encode(ref.abs_path.read_bytes()).decode("ascii")
            budget[0] -= size
            return f"data:{mime};base64,{data}"
    except OSError:
        pass
    return ref.path.as_posix() if ref.path else ""


def _table_html(table: Table) -> str:
    rows = table.normalized()
    if not rows:
        return ""
    out = ['<div class="tablewrap"><table>']
    body = rows
    if table.has_header and len(rows) > 1:
        out.append("<thead><tr>"
                   + "".join(f"<th>{_esc(c)}</th>" for c in rows[0])
                   + "</tr></thead>")
        body = rows[1:]
    out.append("<tbody>")
    for row in body:
        out.append("<tr>" + "".join(f"<td>{_esc(c)}</td>" for c in row) + "</tr>")
    out.append("</tbody></table></div>")
    return "".join(out)


def render(doc: Document, settings: Settings, redaction_note: str = "") -> str:
    budget = [_EMBED_BUDGET]
    title = doc.title.strip() or doc.source_path.stem
    parts = [
        "<!doctype html><html lang='es'><head><meta charset='utf-8'>",
        "<meta name='viewport' content='width=device-width,initial-scale=1'>",
        f"<title>{_esc(title)}</title><style>{_CSS}</style></head><body>",
        f"<h1>{_esc(title)}</h1>",
        "<div class='meta'>",
        f"<b>Origen:</b> {_esc(doc.source_path.name)} &nbsp;|&nbsp; ",
        f"<b>Paginas:</b> {doc.n_pages} &nbsp;|&nbsp; ",
        f"<b>Tablas:</b> {doc.n_tables} &nbsp;|&nbsp; ",
        f"<b>Imagenes:</b> {doc.n_images} &nbsp;|&nbsp; ",
        f"<b>OCR:</b> {doc.n_ocr_pages} paginas<br>",
        f"Convertido en local el {dt.datetime.now().strftime('%d/%m/%Y %H:%M')} "
        "con PDFX, sin conexion a internet.",
        (f"<br><b>Saneado:</b> {_esc(redaction_note)}" if redaction_note else ""),
        "</div>",
    ]

    open_list: str | None = None

    def close_list():
        nonlocal open_list
        if open_list:
            parts.append(f"</{open_list}>")
            open_list = None

    for page in doc.pages:
        if settings.keep_page_marks:
            close_list()
            parts.append(f"<div class='pagemark'>PAGINA {page.number}</div>")
        for el in page.elements:
            if isinstance(el, Block):
                text = el.text.strip()
                if not text:
                    continue
                if el.kind == "heading":
                    close_list()
                    lvl = max(1, min(6, el.level or 2)) + 1
                    lvl = min(lvl, 6)
                    parts.append(f"<h{lvl}>{_esc(text)}</h{lvl}>")
                elif el.kind == "list_item":
                    tag = "ol" if el.ordered else "ul"
                    if open_list != tag:
                        close_list()
                        parts.append(f"<{tag}>")
                        open_list = tag
                    body = text
                    if el.marker and body.startswith(el.marker):
                        body = body[len(el.marker):].lstrip()
                    parts.append(f"<li>{_esc(body)}</li>")
                elif el.kind == "caption":
                    close_list()
                    parts.append(f"<em class='caption'>{_esc(text)}</em>")
                else:
                    close_list()
                    parts.append(f"<p>{_esc(text)}</p>")
            elif isinstance(el, Table):
                close_list()
                parts.append(_table_html(el))
            elif isinstance(el, ImageRef):
                close_list()
                src = _img_src(el, budget)
                if src:
                    alt = _esc(el.caption or el.path.stem if el.path else "imagen")
                    parts.append(f"<img src='{src}' alt='{alt}'>")
                    if el.caption:
                        parts.append(f"<em class='caption'>{_esc(el.caption)}</em>")
    close_list()

    if doc.warnings:
        parts.append("<div class='warn'><b>Avisos de la conversion</b><ul>")
        parts += [f"<li>{_esc(w)}</li>" for w in doc.warnings]
        parts.append("</ul></div>")

    parts.append("</body></html>")
    return "".join(parts)


def write(doc: Document, dest: Path, settings: Settings,
          redaction_note: str = "") -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(render(doc, settings, redaction_note), encoding="utf-8")
    return dest
