"""Punto de entrada de alto nivel: PDF -> ficheros de salida.

    resultado = convert_file(Path("informe.pdf"), settings)

Aqui se encadena: construir el modelo, sanear, escribir cada formato y
verificar que la salida no contiene los terminos marcados.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .config import Settings
from .model import Document
from .pipeline import PdfxError, build_document
from .redact import RedactionReport, build_redactor
from .util.fs import safe_stem, unique_path
from .util.text import token_estimate
from .writers import data_writer, docx_writer, html_writer, markdown, xlsx_writer

log = logging.getLogger(__name__)

ProgressFn = Callable[[str, float], None]

FORMATS = {
    "md": ("Markdown", ".md"),
    "docx": ("Word", ".docx"),
    "xlsx": ("Excel", ".xlsx"),
    "html": ("HTML", ".html"),
    "json": ("JSON", ".json"),
    "txt": ("Texto plano", ".txt"),
}


@dataclass
class ConversionResult:
    source: Path
    outputs: dict[str, Path] = field(default_factory=dict)
    document: Document | None = None
    redaction: RedactionReport | None = None
    media_dir: Path | None = None
    elapsed_s: float = 0.0
    tokens_estimate: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return bool(self.outputs) and not self.errors

    @property
    def warnings(self) -> list[str]:
        return list(self.document.warnings) if self.document else []


def _noop(_m: str, _f: float) -> None:
    pass


def convert_file(
    src: Path,
    settings: Settings,
    progress: ProgressFn = _noop,
    cancel: Callable[[], bool] = lambda: False,
    document: Document | None = None,
) -> ConversionResult:
    """Convierte un PDF. Si `document` ya viene construido, se reutiliza."""
    src = Path(src)
    started = time.time()
    result = ConversionResult(source=src)

    out_dir = settings.resolve_out_dir(src)
    stem = safe_stem(src.stem)
    media_rel = f"{stem}_media" if settings.fast_mode else "media"
    media_dir = out_dir / media_rel
    result.media_dir = media_dir

    want_media = settings.extract_images and not settings.redaction.drop_images
    if want_media:
        media_dir.mkdir(parents=True, exist_ok=True)
    else:
        out_dir.mkdir(parents=True, exist_ok=True)

    # ---- 1. modelo -------------------------------------------------------
    if document is None:
        try:
            document = build_document(
                src, settings,
                media_dir=media_dir if want_media else None,
                rel_prefix=media_rel,
                progress=progress, cancel=cancel,
            )
        except PdfxError as exc:
            result.errors.append(str(exc))
            return result
        except Exception as exc:
            log.exception("Fallo inesperado convirtiendo %s", src)
            result.errors.append(f"Error inesperado: {exc}")
            return result
    result.document = document

    # ---- 2. saneado ------------------------------------------------------
    redaction_note = ""
    redactor = build_redactor(settings.redaction)
    if redactor is not None:
        progress("Saneando informacion sensible", 0.92)
        report = redactor.apply(document)
        result.redaction = report
        redaction_note = (
            f"{report.total} elemento(s) sensible(s) sustituido(s) "
            f"(estilo: {settings.redaction.style})"
        )
        if settings.redaction.drop_images:
            _purge_media(media_dir)
            redaction_note += "; imagenes excluidas"

    # ---- 3. escritura ----------------------------------------------------
    progress("Escribiendo ficheros", 0.95)
    writers = {
        "md": markdown.write,
        "docx": docx_writer.write,
        "xlsx": xlsx_writer.write,
        "html": html_writer.write,
        "json": data_writer.write_json,
        "txt": data_writer.write_txt,
    }
    for fmt in settings.formats:
        if fmt not in writers:
            result.errors.append(f"Formato desconocido: {fmt}")
            continue
        dest = unique_path(out_dir / f"{stem}{FORMATS[fmt][1]}")
        try:
            writers[fmt](document, dest, settings, redaction_note)
            result.outputs[fmt] = dest
        except Exception as exc:
            log.exception("Fallo escribiendo %s", fmt)
            result.errors.append(f"No se pudo escribir {FORMATS[fmt][0]}: {exc}")

    # ---- 4. verificacion del saneado -------------------------------------
    if redactor is not None and settings.redaction.verify_output:
        progress("Verificando el saneado", 0.98)
        haystack = []
        for fmt in ("md", "txt", "html", "json"):
            path = result.outputs.get(fmt)
            if path and path.exists():
                haystack.append(path.read_text(encoding="utf-8", errors="ignore"))
        if not haystack:
            haystack.append(markdown.render(document, settings, redaction_note))
        leaked = redactor.verify("\n".join(haystack))
        if leaked:
            document.warnings.append(
                "Saneado incompleto, revisar: " + ", ".join(leaked)
            )

    if redactor is not None and settings.redaction.report:
        report_path = out_dir / f"{stem}.saneado.txt"
        try:
            report_path.write_text(redactor.report.render(), encoding="utf-8")
            result.outputs["informe_saneado"] = report_path
        except OSError as exc:
            result.errors.append(f"No se pudo escribir el informe de saneado: {exc}")

    # ---- 5. limpieza -----------------------------------------------------
    if want_media and media_dir.exists() and not any(media_dir.iterdir()):
        try:
            media_dir.rmdir()
        except OSError:
            pass

    result.elapsed_s = time.time() - started
    result.tokens_estimate = token_estimate(
        markdown.render(document, settings, redaction_note)
    )
    progress("Completado", 1.0)
    return result


def convert_many(
    settings: Settings,
    progress: ProgressFn = _noop,
    cancel: Callable[[], bool] = lambda: False,
) -> list[ConversionResult]:
    """Convierte todos los PDF de `settings.inputs`."""
    results: list[ConversionResult] = []
    total = len(settings.inputs) or 1
    for i, src in enumerate(settings.inputs):
        if cancel():
            break

        def sub(msg: str, frac: float, i=i, src=src) -> None:
            progress(f"[{i + 1}/{total}] {src.name} - {msg}",
                     (i + max(0.0, min(frac, 1.0))) / total)

        results.append(convert_file(src, settings, progress=sub, cancel=cancel))
    return results


def _purge_media(media_dir: Path) -> None:
    """Borra las imagenes ya escritas cuando el saneado pide excluirlas."""
    if not media_dir.exists():
        return
    for child in media_dir.iterdir():
        try:
            if child.is_file():
                child.unlink()
        except OSError:
            pass
    try:
        media_dir.rmdir()
    except OSError:
        pass
