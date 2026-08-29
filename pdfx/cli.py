"""Interfaz de linea de comandos de PDFx.

    pdfx documento.pdf                      -> documento.md
    pdfx *.pdf -f md,docx,xlsx -o salida/
    pdfx informe.pdf --rapido               -> informe.md junto al original
    pdfx revisar informe.pdf                -> lista de datos sensibles
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from . import APP_NAME, __version__
from .config import RedactionSettings, Settings
from .convert import FORMATS, convert_file
from .redact import DETECTORS
from .util.fs import human_size

log = logging.getLogger("pdfx")


# --------------------------------------------------------------------------
COMANDOS = ("convertir", "revisar", "interfaz", "info", "ayuda")

_EPILOGO = """ejemplos:
  pdfx informe.pdf
  pdfx informe.pdf -f md,docx,xlsx -o C:\\salida
  pdfx *.pdf --rapido
  pdfx plano.pdf --ocr always --idioma spa --dpi 400
  pdfx contrato.pdf --ocultar "ACME S.A." --ocultar-detector email,phone
  pdfx revisar contrato.pdf -o revision.json
  pdfx interfaz

comandos:
  convertir   (por defecto) convierte uno o varios PDF
  revisar     lista los datos sensibles candidatos de un PDF
  interfaz    abre la ventana grafica
  info        muestra el estado del OCR y datos del PDF
"""


def _base_parser(prog: str, desc: str) -> argparse.ArgumentParser:
    return argparse.ArgumentParser(
        prog=prog, description=desc,
        formatter_class=argparse.RawDescriptionHelpFormatter, epilog=_EPILOGO,
    )


def build_parser(comando: str = "convertir") -> argparse.ArgumentParser:
    """Un parser por comando: evita que dos positionals compitan entre si."""
    head = f"{APP_NAME} {__version__} - convierte PDF (incluidos escaneados) a "
    if comando == "revisar":
        p = _base_parser("pdfx revisar",
                         head + "texto. Lista los datos sensibles candidatos.")
        p.add_argument("entrada", nargs="+", type=Path)
        p.add_argument("-o", "--salida", type=Path, help="fichero JSON de salida")
        p.add_argument("--ocr", choices=("auto", "always", "never"), default="auto")
        p.add_argument("--idioma", default="spa+eng")
        p.add_argument("--top", type=int, default=60, help="cuantos mostrar")
        p.add_argument("-v", "--detalle", action="store_true")
        return p

    if comando == "info":
        p = _base_parser("pdfx info", head + "Muestra el estado del entorno.")
        p.add_argument("entrada", nargs="*", type=Path)
        p.add_argument("-v", "--detalle", action="store_true")
        return p

    if comando == "interfaz":
        p = _base_parser("pdfx interfaz", head + "Abre la ventana grafica.")
        p.add_argument("-v", "--detalle", action="store_true")
        return p

    p = _base_parser("pdfx", head + "Markdown, Word, Excel o HTML. Todo local.")
    p.add_argument("--version", action="version",
                   version=f"{APP_NAME} {__version__}")
    _add_convert_args(p)
    return p


def _add_convert_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("entrada", nargs="*", type=Path, help="ficheros PDF")
    p.add_argument("-o", "--salida", type=Path, metavar="DIR",
                   help="carpeta de salida (por defecto, junto al PDF)")
    p.add_argument("-f", "--formato", default="md",
                   help="md, docx, xlsx, html, json, txt (separados por comas)")
    p.add_argument("--rapido", action="store_true",
                   help="solo Markdown, junto al original, sin imagenes")

    g = p.add_argument_group("OCR")
    g.add_argument("--ocr", choices=("auto", "always", "never"), default="auto")
    g.add_argument("--idioma", default="spa+eng", metavar="LANG")
    g.add_argument("--dpi", type=int, default=300)
    g.add_argument("--psm", type=int, default=3, help="modo de segmentacion")
    g.add_argument("--sin-enderezar", action="store_true")
    g.add_argument("--tesseract", type=Path, help="ruta al binario")

    g = p.add_argument_group("extraccion")
    g.add_argument("--paginas", default="", metavar="RANGO", help="p.ej. 1-3,7")
    g.add_argument("--sin-imagenes", action="store_true")
    g.add_argument("--sin-tablas", action="store_true")
    g.add_argument("--sin-columnas", action="store_true")
    g.add_argument("--paginas-completas", action="store_true",
                   help="guarda tambien cada pagina escaneada como imagen")
    g.add_argument("--excel-modo", choices=("tables", "full"), default="tables")
    g.add_argument("--sin-marcas-pagina", action="store_true")

    g = p.add_argument_group("saneado de datos sensibles")
    g.add_argument("--ocultar", action="append", default=[], metavar="TEXTO",
                   help="termino a ocultar (repetible)")
    g.add_argument("--ocultar-fichero", type=Path, metavar="RUTA",
                   help="fichero .txt (un termino por linea) o .json de revision")
    g.add_argument("--ocultar-detector", default="", metavar="LISTA",
                   help="detectores: " + ",".join(DETECTORS))
    g.add_argument("--ocultar-regex", action="append", default=[], metavar="RE")
    g.add_argument("--ocultar-estilo", choices=("label", "mask", "hash", "remove"),
                   default="label")
    g.add_argument("--sin-imagenes-sensibles", action="store_true",
                   help="no exportar ninguna imagen")

    p.add_argument("-q", "--silencioso", action="store_true")
    p.add_argument("-v", "--detalle", action="store_true")


# --------------------------------------------------------------------------
def _load_terms(path: Path) -> tuple[list[str], list[str], list[str]]:
    """Lee terminos de un .txt (uno por linea) o del .json de `revisar`."""
    terms: list[str] = []
    patterns: list[str] = []
    detectors: list[str] = []
    if not path.exists():
        raise SystemExit(f"No existe el fichero de terminos: {path}")

    if path.suffix.lower() == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
        for item in data.get("seleccionados", data.get("candidatos", [])):
            if isinstance(item, str):
                terms.append(item)
            elif item.get("elegido", True):
                if item.get("tipo") in DETECTORS:
                    detectors.append(item["tipo"])
                else:
                    terms.append(item["texto"])
        terms += data.get("terminos", [])
        patterns += data.get("patrones", [])
        detectors += data.get("detectores", [])
    else:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("re:"):
                patterns.append(line[3:].strip())
            elif line.startswith("det:"):
                detectors.append(line[4:].strip())
            else:
                terms.append(line)
    return terms, patterns, sorted(set(detectors))


def settings_from_args(args) -> Settings:
    formats = [f.strip().lower() for f in str(args.formato).split(",") if f.strip()]
    unknown = [f for f in formats if f not in FORMATS]
    if unknown:
        raise SystemExit(f"Formato no reconocido: {', '.join(unknown)}. "
                         f"Validos: {', '.join(FORMATS)}")

    terms = list(args.ocultar)
    patterns = list(args.ocultar_regex)
    detectors = [d.strip() for d in args.ocultar_detector.split(",") if d.strip()]
    if args.ocultar_fichero:
        t, p, d = _load_terms(args.ocultar_fichero)
        terms += t
        patterns += p
        detectors += d
    bad = [d for d in detectors if d not in DETECTORS]
    if bad:
        raise SystemExit(f"Detector desconocido: {', '.join(bad)}. "
                         f"Validos: {', '.join(DETECTORS)}")

    redaction = RedactionSettings(
        enabled=bool(terms or patterns or detectors or args.sin_imagenes_sensibles),
        terms=terms, patterns=patterns, detectors=sorted(set(detectors)),
        style=args.ocultar_estilo,
        drop_images=args.sin_imagenes_sensibles,
    )

    if args.rapido:
        formats = ["md"]

    return Settings(
        inputs=[Path(p) for p in args.entrada],
        out_dir=args.salida,
        formats=formats,
        fast_mode=args.rapido,
        ocr=args.ocr,
        ocr_langs=args.idioma,
        ocr_dpi=args.dpi,
        ocr_psm=args.psm,
        deskew=not args.sin_enderezar,
        tesseract_path=args.tesseract,
        page_range=args.paginas,
        extract_images=not (args.sin_imagenes or args.rapido),
        detect_tables=not args.sin_tablas,
        detect_columns=not args.sin_columnas,
        keep_page_scans=args.paginas_completas,
        keep_page_marks=not args.sin_marcas_pagina,
        xlsx_mode=args.excel_modo,
        redaction=redaction,
        verbose=args.detalle,
    )


def _expand(paths: list[Path]) -> list[Path]:
    """Acepta carpetas y comodines sin depender del shell."""
    out: list[Path] = []
    for raw in paths:
        if raw.is_dir():
            out.extend(sorted(raw.glob("*.pdf")))
        elif any(ch in str(raw) for ch in "*?["):
            parent = raw.parent if str(raw.parent) else Path(".")
            out.extend(sorted(parent.glob(raw.name)))
        else:
            out.append(raw)
    seen, unique = set(), []
    for p in out:
        key = str(p.resolve()) if p.exists() else str(p)
        if key not in seen:
            seen.add(key)
            unique.append(p)
    return unique


# --------------------------------------------------------------------------
def cmd_convert(args) -> int:
    settings = settings_from_args(args)
    settings.inputs = _expand(settings.inputs)
    if not settings.inputs:
        raise SystemExit("No se indico ningun PDF.")

    quiet = args.silencioso
    # La barra de progreso solo tiene sentido en una terminal interactiva;
    # redirigida a un fichero o a un log solo ensucia la salida.
    # En Windows el ejecutable se compila sin consola (pdfx.spec), y entonces
    # sys.stdout es None: hay que sondear isatty sin darlo por hecho.
    interactive = bool(getattr(sys.stdout, "isatty", lambda: False)()) and not quiet
    failures = 0

    for i, src in enumerate(settings.inputs, start=1):
        if not src.exists():
            print(f"[{i}/{len(settings.inputs)}] {src}: no existe", file=sys.stderr)
            failures += 1
            continue

        last = [""]

        def progress(msg: str, frac: float) -> None:
            if not interactive:
                return
            bar = "#" * int(frac * 24)
            line = f"\r  [{bar:<24}] {msg[:52]:<52}"
            if line != last[0]:
                sys.stdout.write(line)
                sys.stdout.flush()
                last[0] = line

        if not quiet:
            print(f"[{i}/{len(settings.inputs)}] {src.name} "
                  f"({human_size(src.stat().st_size)})")
        result = convert_file(src, settings, progress=progress)
        if interactive:
            sys.stdout.write("\r" + " " * 82 + "\r")

        if result.errors:
            failures += 1
            for err in result.errors:
                print(f"  ERROR: {err}", file=sys.stderr)
        for w in result.warnings:
            print(f"  aviso: {w}", file=sys.stderr)

        if not quiet and result.document:
            d = result.document
            print(f"  {d.n_pages} pag | {d.n_tables} tablas | {d.n_images} img"
                  f" | OCR en {d.n_ocr_pages} | ~{result.tokens_estimate} tokens"
                  f" | {result.elapsed_s:.1f}s")
            if result.redaction and result.redaction.total:
                print(f"  saneado: {result.redaction.total} sustituciones")
            for fmt, path in result.outputs.items():
                print(f"    -> {path}")

    return 1 if failures else 0


def cmd_review(args) -> int:
    from .pipeline import build_document
    from .scan_sensitive import scan

    settings = Settings(ocr=args.ocr, ocr_langs=args.idioma, extract_images=False)
    payload = {"documentos": []}

    for src in _expand([Path(p) for p in args.entrada]):
        if not src.exists():
            print(f"{src}: no existe", file=sys.stderr)
            continue
        doc = build_document(src, settings)
        candidates = scan(doc)
        print(f"\n{src.name}: {len(candidates)} candidatos "
              f"({doc.n_pages} paginas)")
        print(f"  {'TIPO':<22} {'VECES':>5}  {'PAG':<12} TEXTO")
        print("  " + "-" * 74)
        for c in candidates[: args.top]:
            mark = "*" if c.suggested else " "
            print(f" {mark}{c.kind_label:<22} {c.count:>5}  "
                  f"{c.pages_str[:12]:<12} {c.text[:32]}")
        if len(candidates) > args.top:
            print(f"  ... y {len(candidates) - args.top} mas")
        print("  (* = sugerido para ocultar)")

        payload["documentos"].append({
            "origen": str(src),
            "candidatos": [
                {"texto": c.text, "tipo": c.kind, "veces": c.count,
                 "paginas": sorted(c.pages), "elegido": c.suggested,
                 "contexto": c.samples}
                for c in candidates
            ],
        })

    if args.salida:
        # Formato listo para --ocultar-fichero
        flat = [c for d in payload["documentos"] for c in d["candidatos"]]
        payload["seleccionados"] = flat
        args.salida.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"\nRevision guardada en {args.salida}")
        print("Edita el campo \"elegido\" y luego usa:")
        print(f"  pdfx documento.pdf --ocultar-fichero {args.salida}")
    return 0


def _gui_status() -> str:
    """Comprueba que la interfaz grafica puede abrirse en esta maquina."""
    try:
        import tkinter as tk
    except Exception as exc:
        return f"NO DISPONIBLE (tkinter no se pudo importar: {exc})"
    try:
        root = tk.Tk()
        root.withdraw()
        version = root.tk.call("info", "patchlevel")
        root.destroy()
        return f"disponible (Tcl/Tk {version})"
    except Exception as exc:
        return f"NO DISPONIBLE ({exc})"


def cmd_info(args) -> int:
    from .engines.ocr import available_languages, find_tesseract

    print(f"{APP_NAME} {__version__}")
    exe = find_tesseract()
    if exe:
        print(f"Tesseract: {exe}")
        print(f"Idiomas:   {', '.join(available_languages(exe)) or '(ninguno)'}")
    else:
        print("Tesseract: NO ENCONTRADO (los PDF escaneados no se podran leer)")

    print(f"Ventana:   {_gui_status()}")

    for src in _expand([Path(p) for p in (args.entrada or [])]):
        if not src.exists():
            continue
        import pdfplumber
        with pdfplumber.open(str(src)) as pdf:
            n = len(pdf.pages)
            chars = sum(len(p.chars) for p in pdf.pages[:10])
        tipo = "con capa de texto" if chars > 200 else "escaneado (necesita OCR)"
        print(f"\n{src.name}: {n} paginas, {human_size(src.stat().st_size)}, {tipo}")
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)

    comando = "convertir"
    if argv and argv[0] in COMANDOS:
        comando, argv = argv[0], argv[1:]
    if comando == "ayuda":
        build_parser().print_help()
        return 0

    # Doble clic en el ejecutable: sin argumentos se abre la ventana.
    if comando == "convertir" and not argv:
        try:
            from .gui import run
            return run()
        except Exception as exc:
            print(f"No se pudo abrir la ventana ({exc}).\n", file=sys.stderr)
            build_parser().print_help()
            return 1

    args = build_parser(comando).parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if getattr(args, "detalle", False) else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )

    if comando == "revisar":
        return cmd_review(args)
    if comando == "interfaz":
        from .gui import run
        return run()
    if comando == "info":
        return cmd_info(args)
    if not args.entrada:
        raise SystemExit("No se indico ningun PDF. Usa 'pdfx ayuda'.")
    return cmd_convert(args)


if __name__ == "__main__":
    sys.exit(main())
