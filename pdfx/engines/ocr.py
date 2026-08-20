"""Motor OCR: Tesseract 5 en modo TSV (palabras con caja y confianza).

Tesseract se invoca como proceso externo, sin pytesseract, para poder empaquetar
un binario portable junto al ejecutable y no depender de nada instalado.
"""

from __future__ import annotations

import csv
import io
import logging
import os
import platform
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from ..model import Word
from ..util.text import clean
from .preprocess import prepare_for_ocr

log = logging.getLogger(__name__)

_WINDOWS = platform.system() == "Windows"
_EXE = "tesseract.exe" if _WINDOWS else "tesseract"


class OcrUnavailable(RuntimeError):
    """No hay motor OCR disponible en esta maquina."""


@dataclass(slots=True)
class OcrResult:
    words: list[Word]
    mean_conf: float
    skew_angle: float
    engine: str


def _app_root() -> Path:
    """Carpeta del ejecutable (PyInstaller) o raiz del repo en desarrollo."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parents[2]


def _candidate_paths() -> list[Path]:
    root = _app_root()
    names = [
        root / "tools" / "tesseract" / _EXE,
        root / "tools" / "tesseract-win" / _EXE,
        root / "tools" / "tesseract-linux" / "tesseract.sh",
        root / "_internal" / "tools" / "tesseract" / _EXE,
    ]
    if _WINDOWS:
        names += [
            Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe"),
            Path(r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"),
            Path(os.environ.get("LOCALAPPDATA", "")) / "Tesseract-OCR" / "tesseract.exe",
        ]
    else:
        names += [Path("/usr/bin/tesseract"), Path("/usr/local/bin/tesseract")]
    return names


def find_tesseract(explicit: Path | None = None) -> Path | None:
    """Localiza el binario: parametro > copia portable > PATH > instalacion tipica."""
    if explicit:
        p = Path(explicit)
        if p.exists():
            return p
        log.warning("La ruta de Tesseract indicada no existe: %s", p)

    for cand in _candidate_paths():
        try:
            if cand.exists():
                return cand
        except OSError:
            continue

    found = shutil.which("tesseract")
    return Path(found) if found else None


def _run_env(exe: Path) -> dict[str, str]:
    env = os.environ.copy()
    tessdata = exe.parent / "tessdata"
    if tessdata.is_dir():
        env["TESSDATA_PREFIX"] = str(tessdata)
    env.setdefault("OMP_THREAD_LIMIT", "1")  # tesseract escala mal con OpenMP
    return env


def _no_window_kwargs() -> dict:
    """Evita que parpadee una consola negra al lanzar tesseract desde la GUI."""
    if not _WINDOWS:
        return {}
    si = subprocess.STARTUPINFO()
    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    return {"startupinfo": si, "creationflags": 0x08000000}  # CREATE_NO_WINDOW


def available_languages(exe: Path) -> list[str]:
    try:
        out = subprocess.run(
            [str(exe), "--list-langs"], capture_output=True, text=True,
            env=_run_env(exe), timeout=30, **_no_window_kwargs()
        )
        lines = (out.stdout or out.stderr).splitlines()
        return [ln.strip() for ln in lines[1:] if ln.strip()]
    except Exception as exc:
        log.warning("No se pudieron listar idiomas: %s", exc)
        return []


def resolve_langs(exe: Path, requested: str) -> str:
    """Filtra los idiomas pedidos a los que realmente estan instalados."""
    have = set(available_languages(exe))
    if not have:
        return requested
    want = [l for l in requested.split("+") if l]
    ok = [l for l in want if l in have]
    if not ok:
        fallback = "spa" if "spa" in have else ("eng" if "eng" in have else next(iter(have)))
        log.warning("Idiomas %s no instalados; se usara '%s'", requested, fallback)
        return fallback
    if len(ok) != len(want):
        log.warning("Idiomas no instalados: %s", set(want) - set(ok))
    return "+".join(ok)


def _parse_tsv(tsv_text: str, scale: float, min_conf: float) -> tuple[list[Word], float]:
    words: list[Word] = []
    confs: list[float] = []
    reader = csv.DictReader(io.StringIO(tsv_text), delimiter="\t", quoting=csv.QUOTE_NONE)
    for row in reader:
        try:
            if int(row.get("level", 0)) != 5:      # nivel 5 == palabra
                continue
            conf = float(row.get("conf", -1))
            text = clean(row.get("text", "") or "")
            if not text or conf < 0:
                continue
            left, top = float(row["left"]), float(row["top"])
            w, h = float(row["width"]), float(row["height"])
        except (ValueError, KeyError, TypeError):
            continue

        confs.append(conf)
        if conf < min_conf:
            continue
        words.append(
            Word(
                text=text,
                x0=left / scale,
                top=top / scale,
                x1=(left + w) / scale,
                bottom=(top + h) / scale,
                size=h / scale,
                conf=conf,
            )
        )
    mean_conf = sum(confs) / len(confs) if confs else 0.0
    return words, mean_conf


def ocr_text(
    image: Image.Image,
    exe: Path,
    langs: str = "spa+eng",
    psm_chain: tuple[int, ...] = (6, 7),
    min_height_px: int = 56,
    timeout: int = 60,
) -> str:
    """OCR de un recorte pequeno (una celda de tabla). Devuelve solo el texto.

    Se prueban varios modos de segmentacion porque un recorte con un unico
    numero necesita "linea suelta" y una cabecera de varias palabras necesita
    "bloque uniforme".
    """
    if image.width < 4 or image.height < 4:
        return ""
    work = image.convert("L")
    if work.height < min_height_px:
        factor = min(4.0, min_height_px / max(work.height, 1))
        work = work.resize(
            (max(1, int(work.width * factor)), max(1, int(work.height * factor))),
            Image.LANCZOS,
        )

    with tempfile.TemporaryDirectory(prefix="pdfx_cell_") as tmp:
        img_path = Path(tmp) / "cell.png"
        work.save(img_path, "PNG")
        for psm in psm_chain:
            out_base = Path(tmp) / f"out{psm}"
            cmd = [
                str(exe), str(img_path), str(out_base),
                "-l", langs, "--psm", str(psm), "--oem", "3",
            ]
            try:
                proc = subprocess.run(
                    cmd, capture_output=True, text=True, env=_run_env(exe),
                    timeout=timeout, **_no_window_kwargs()
                )
            except (subprocess.TimeoutExpired, OSError):
                return ""
            txt_file = out_base.with_suffix(".txt")
            if proc.returncode == 0 and txt_file.exists():
                text = clean(txt_file.read_text(encoding="utf-8", errors="replace")
                             .replace("\n", " "))
                if text:
                    return text
    return ""


def ocr_image(
    image: Image.Image,
    exe: Path,
    scale: float,
    langs: str = "spa+eng",
    psm: int = 3,
    min_conf: float = 40.0,
    do_deskew: bool = True,
    timeout: int = 300,
    preprocess: bool = True,
) -> OcrResult:
    """OCR de una pagina rasterizada. `scale` = pixeles por punto PDF.

    Con `preprocess=False` se asume que la imagen ya viene enderezada y con el
    contraste ajustado; asi el resto del analisis (rayado de tablas, recorte de
    figuras) trabaja exactamente sobre los mismos pixeles que vio el OCR.
    """
    if preprocess:
        prepared, angle = prepare_for_ocr(image, do_deskew=do_deskew)
    else:
        prepared, angle = image, 0.0

    with tempfile.TemporaryDirectory(prefix="pdfx_ocr_") as tmp:
        img_path = Path(tmp) / "page.png"
        prepared.save(img_path, "PNG")
        out_base = Path(tmp) / "out"
        cmd = [
            str(exe), str(img_path), str(out_base),
            "-l", langs,
            "--psm", str(psm),
            "--oem", "3",
            "-c", "preserve_interword_spaces=1",
            # Se pide el TSV por parametro y no con el fichero de configuracion
            # "tsv": asi no hace falta el directorio tessdata/configs, que
            # muchas copias portables de Tesseract no traen.
            "-c", "tessedit_create_tsv=1",
        ]
        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True, env=_run_env(exe),
                timeout=timeout, **_no_window_kwargs()
            )
        except subprocess.TimeoutExpired:
            raise RuntimeError(f"Tesseract excedio {timeout}s en una pagina")
        except OSError as exc:
            raise OcrUnavailable(f"No se pudo ejecutar Tesseract: {exc}") from exc

        tsv_file = out_base.with_suffix(".tsv")
        if proc.returncode != 0 or not tsv_file.exists():
            raise RuntimeError(
                f"Tesseract fallo (codigo {proc.returncode}): "
                f"{(proc.stderr or '').strip()[:400]}"
            )
        tsv_text = tsv_file.read_text(encoding="utf-8", errors="replace")

    words, mean_conf = _parse_tsv(tsv_text, scale, min_conf)
    return OcrResult(words=words, mean_conf=mean_conf, skew_angle=angle, engine="tesseract")
