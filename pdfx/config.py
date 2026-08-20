"""Configuracion del pipeline. Un unico objeto viaja de la GUI/CLI al motor."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

OcrMode = Literal["auto", "always", "never"]
XlsxMode = Literal["tables", "full"]
RedactStyle = Literal["label", "mask", "remove", "hash"]


@dataclass
class RedactionSettings:
    """Saneado de informacion sensible antes de escribir la salida."""

    enabled: bool = False
    # Terminos literales a ocultar (empresa, maquina, cliente, personas...).
    terms: list[str] = field(default_factory=list)
    # Expresiones regulares avanzadas (usuario experto).
    patterns: list[str] = field(default_factory=list)
    # Detectores predefinidos activos: email, phone, iban, card, url, ip,
    # id_fiscal, serial, coord.
    detectors: list[str] = field(default_factory=list)
    style: RedactStyle = "label"
    # Etiqueta base cuando style == "label"  ->  [CONFIDENCIAL_1]
    label_prefix: str = "CONFIDENCIAL"
    # Coincidencia solo en palabra completa (evita ocultar trozos de otras palabras).
    whole_word: bool = True
    # Ignorar mayusculas y acentos al comparar.
    fuzzy: bool = True
    # Tambien sanear metadatos del PDF (titulo, autor, asunto).
    scrub_metadata: bool = True
    # No exportar ninguna imagen (las fotos suelen ser lo mas delicado).
    drop_images: bool = False
    # Generar informe .redaccion.txt con el recuento por termino.
    report: bool = True
    # Releer el fichero escrito y avisar si algun termino sobrevivio.
    verify_output: bool = True


@dataclass
class Settings:
    # --- entrada / salida -------------------------------------------------
    inputs: list[Path] = field(default_factory=list)
    out_dir: Path | None = None          # None -> junto al PDF de origen
    formats: list[str] = field(default_factory=lambda: ["md"])  # md, docx, xlsx, json, txt

    # --- OCR --------------------------------------------------------------
    ocr: OcrMode = "auto"
    ocr_langs: str = "spa+eng"
    ocr_dpi: int = 300
    ocr_psm: int = 3
    ocr_min_conf: float = 40.0
    deskew: bool = True
    # Umbral: si una pagina tiene menos caracteres nativos que esto, se OCRea.
    native_char_threshold: int = 60

    # --- extraccion -------------------------------------------------------
    extract_images: bool = True
    min_image_px: int = 64               # descarta iconos / lineas decorativas
    image_format: Literal["png", "jpg"] = "png"
    # En paginas escaneadas: recorta esquemas y fotos que el OCR no leyo.
    extract_figures: bool = True
    # Guardar ademas la pagina escaneada entera como imagen (pesa mucho).
    keep_page_scans: bool = False
    detect_tables: bool = True
    detect_columns: bool = True
    detect_headings: bool = True
    page_range: str = ""                 # "1-5,8,12-" ; vacio = todo
    keep_page_marks: bool = True         # <!-- pagina N --> en el markdown

    # --- salida especifica ------------------------------------------------
    xlsx_mode: XlsxMode = "tables"
    md_claude_header: bool = True        # cabecera que evita el "esto es un PDF"
    md_single_file: bool = True
    docx_page_breaks: bool = True

    # --- modo rapido ------------------------------------------------------
    # Deja el .md al lado del PDF, mismo nombre, sin carpeta extra.
    fast_mode: bool = False

    # --- saneado ----------------------------------------------------------
    redaction: RedactionSettings = field(default_factory=RedactionSettings)

    # --- runtime ----------------------------------------------------------
    tesseract_path: Path | None = None   # None -> autodeteccion
    jobs: int = 0                        # 0 -> auto (cpu_count - 1)
    verbose: bool = False

    def resolve_out_dir(self, src: Path) -> Path:
        if self.fast_mode:
            return src.parent
        if self.out_dir:
            return self.out_dir
        return src.parent / f"{src.stem}_convertido"
