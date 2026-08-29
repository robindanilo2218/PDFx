"""Ventana de PDFx: convertir, revisar datos sensibles y ver Markdown.

Tkinter a proposito: viaja dentro de la propia distribucion de Python, asi que
el ejecutable portable no arrastra ningun kit grafico extra.
"""

from __future__ import annotations

import json
import queue
import subprocess
import sys
import threading
import traceback
from dataclasses import dataclass
from pathlib import Path

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from . import APP_NAME, __version__
from .config import RedactionSettings, Settings
from .convert import FORMATS, convert_file
from .mdview import MarkdownView
from .redact import DETECTORS
from .util.fs import human_size

PAD = 8


# --------------------------------------------------------------------------
def open_in_explorer(path: Path) -> None:
    """Abre la carpeta (o el fichero) con el gestor del sistema."""
    path = Path(path)
    try:
        if sys.platform.startswith("win"):
            import os
            os.startfile(str(path))  # noqa: S606
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])
    except Exception:
        pass


def hay_manejador_md() -> bool:
    """Best-effort: hay alguna aplicacion asociada a los ficheros .md?

    En macOS no hay una forma sencilla de consultarlo sin dependencias
    extra, asi que ahi se asume que si (delega en el "open" del sistema,
    igual que antes).
    """
    try:
        if sys.platform.startswith("win"):
            import winreg
            with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, ".md"):
                pass
            return True
        elif sys.platform == "darwin":
            return True
        else:
            r = subprocess.run(
                ["xdg-mime", "query", "default", "text/markdown"],
                capture_output=True, text=True, timeout=3)
            return r.returncode == 0 and bool(r.stdout.strip())
    except Exception:
        return False


@dataclass
class Job:
    kind: str          # "convert" | "scan"
    payload: object = None


# --------------------------------------------------------------------------
class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(f"{APP_NAME} {__version__} - conversor de PDF sin conexion")
        self.geometry("1080x760")
        self.minsize(880, 620)

        self.files: list[Path] = []
        self.candidates: list = []
        self.checked: set[int] = set()
        self.queue: queue.Queue = queue.Queue()
        self.worker: threading.Thread | None = None
        self.cancel_flag = threading.Event()
        self.last_results: list = []
        self.last_md: Path | None = None

        self._init_style()
        self._build_vars()
        self._build_ui()
        self._check_ocr()
        self.after(80, self._drain_queue)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # -- apariencia -------------------------------------------------------
    def _init_style(self) -> None:
        style = ttk.Style(self)
        for theme in ("vista", "clam", "aqua", "default"):
            if theme in style.theme_names():
                style.theme_use(theme)
                break
        style.configure("Big.TButton", padding=(16, 10))
        style.configure("Head.TLabel", font=("TkDefaultFont", 11, "bold"))
        style.configure("Hint.TLabel", foreground="#6b737d")
        style.configure("Ok.TLabel", foreground="#1a7f37")
        style.configure("Bad.TLabel", foreground="#b42318")

    def _build_vars(self) -> None:
        self.v_outmode = tk.StringVar(value="junto")
        self.v_outdir = tk.StringVar(value="")
        self.v_formats = {
            "md": tk.BooleanVar(value=True),
            "docx": tk.BooleanVar(value=False),
            "xlsx": tk.BooleanVar(value=False),
            "html": tk.BooleanVar(value=False),
            "txt": tk.BooleanVar(value=False),
            "json": tk.BooleanVar(value=False),
        }
        self.v_ocr = tk.StringVar(value="auto")
        self.v_lang = tk.StringVar(value="spa+eng")
        self.v_dpi = tk.IntVar(value=300)
        self.v_pages = tk.StringVar(value="")
        self.v_images = tk.BooleanVar(value=True)
        self.v_tables = tk.BooleanVar(value=True)
        self.v_columns = tk.BooleanVar(value=True)
        self.v_pagemarks = tk.BooleanVar(value=True)
        self.v_claude = tk.BooleanVar(value=True)
        self.v_xlsxmode = tk.StringVar(value="tables")
        self.v_status = tk.StringVar(value="Listo.")
        self.v_ocrinfo = tk.StringVar(value="")

        self.v_redact = tk.BooleanVar(value=False)
        self.v_style = tk.StringVar(value="label")
        self.v_dropimg = tk.BooleanVar(value=False)
        self.v_detectors = {k: tk.BooleanVar(value=False) for k in DETECTORS}
        self.v_view_theme = tk.StringVar(value="claro")

    # -- construccion -----------------------------------------------------
    def _build_ui(self) -> None:
        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True, padx=PAD, pady=(PAD, 0))
        self.nb.add(self._tab_convert(), text="  1. Convertir  ")
        self.nb.add(self._tab_review(), text="  2. Revisar y ocultar  ")
        self.nb.add(self._tab_view(), text="  3. Ver Markdown  ")

        bar = ttk.Frame(self)
        bar.pack(fill="x", padx=PAD, pady=(2, 6))
        ttk.Label(bar, textvariable=self.v_status).pack(side="left")
        ttk.Label(bar, textvariable=self.v_ocrinfo, style="Hint.TLabel").pack(side="right")

    # ---------------- pestana 1: convertir ------------------------------
    def _tab_convert(self) -> ttk.Frame:
        tab = ttk.Frame(self, padding=PAD)

        top = ttk.Frame(tab)
        top.pack(fill="both", expand=True)

        # --- documentos ---
        box = ttk.LabelFrame(top, text=" Documentos PDF ", padding=PAD)
        box.pack(side="left", fill="both", expand=True)

        listwrap = ttk.Frame(box)
        listwrap.pack(fill="both", expand=True)
        self.lst = tk.Listbox(listwrap, selectmode="extended", activestyle="none",
                              height=10, borderwidth=1, relief="solid")
        sb = ttk.Scrollbar(listwrap, orient="vertical", command=self.lst.yview)
        self.lst.configure(yscrollcommand=sb.set)
        self.lst.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        btns = ttk.Frame(box)
        btns.pack(fill="x", pady=(PAD, 0))
        ttk.Button(btns, text="Anadir PDF...", command=self.add_files).pack(side="left")
        ttk.Button(btns, text="Anadir carpeta...", command=self.add_folder).pack(side="left", padx=4)
        ttk.Button(btns, text="Quitar", command=self.remove_selected).pack(side="left")
        ttk.Button(btns, text="Vaciar", command=self.clear_files).pack(side="left", padx=4)

        # --- opciones ---
        right = ttk.Frame(top)
        right.pack(side="left", fill="y", padx=(PAD, 0))

        fmt = ttk.LabelFrame(right, text=" Formatos de salida ", padding=PAD)
        fmt.pack(fill="x")
        for i, (key, (label, ext)) in enumerate(FORMATS.items()):
            ttk.Checkbutton(fmt, text=f"{label} ({ext})",
                            variable=self.v_formats[key]).grid(
                row=i // 2, column=i % 2, sticky="w", padx=(0, 12))

        dest = ttk.LabelFrame(right, text=" Donde guardar ", padding=PAD)
        dest.pack(fill="x", pady=(PAD, 0))
        ttk.Radiobutton(dest, text="Junto al PDF original", value="junto",
                        variable=self.v_outmode).pack(anchor="w")
        row = ttk.Frame(dest)
        row.pack(fill="x", pady=(2, 0))
        ttk.Radiobutton(row, text="Carpeta:", value="carpeta",
                        variable=self.v_outmode).pack(side="left")
        ttk.Entry(row, textvariable=self.v_outdir, width=22).pack(side="left", padx=4)
        ttk.Button(row, text="...", width=3, command=self.pick_outdir).pack(side="left")

        opt = ttk.LabelFrame(right, text=" Lectura ", padding=PAD)
        opt.pack(fill="x", pady=(PAD, 0))
        r = ttk.Frame(opt); r.pack(fill="x")
        ttk.Label(r, text="OCR:").pack(side="left")
        ttk.Combobox(r, textvariable=self.v_ocr, width=9, state="readonly",
                     values=("auto", "always", "never")).pack(side="left", padx=4)
        ttk.Label(r, text="Idioma:").pack(side="left", padx=(8, 0))
        ttk.Entry(r, textvariable=self.v_lang, width=9).pack(side="left", padx=4)
        r = ttk.Frame(opt); r.pack(fill="x", pady=(4, 0))
        ttk.Label(r, text="Calidad OCR (ppp):").pack(side="left")
        ttk.Spinbox(r, from_=150, to=600, increment=50, width=6,
                    textvariable=self.v_dpi).pack(side="left", padx=4)
        r = ttk.Frame(opt); r.pack(fill="x", pady=(4, 0))
        ttk.Label(r, text="Paginas:").pack(side="left")
        ttk.Entry(r, textvariable=self.v_pages, width=12).pack(side="left", padx=4)
        ttk.Label(r, text="(vacio = todas)", style="Hint.TLabel").pack(side="left")

        for text, var in (
            ("Extraer imagenes y esquemas", self.v_images),
            ("Detectar tablas", self.v_tables),
            ("Detectar columnas", self.v_columns),
            ("Marcar numeros de pagina", self.v_pagemarks),
            ("Cabecera para asistentes de IA", self.v_claude),
        ):
            ttk.Checkbutton(opt, text=text, variable=var).pack(anchor="w", pady=(3, 0))

        r = ttk.Frame(opt); r.pack(fill="x", pady=(4, 0))
        ttk.Label(r, text="Excel:").pack(side="left")
        ttk.Combobox(r, textvariable=self.v_xlsxmode, width=10, state="readonly",
                     values=("tables", "full")).pack(side="left", padx=4)
        ttk.Label(r, text="tablas / todo", style="Hint.TLabel").pack(side="left")

        # --- acciones ---
        act = ttk.Frame(tab)
        act.pack(fill="x", pady=(PAD, 0))
        self.btn_convert = ttk.Button(act, text="Convertir", style="Big.TButton",
                                      command=self.start_convert)
        self.btn_convert.pack(side="left")
        self.btn_fast = ttk.Button(
            act, text="Modo rapido:  PDF  ->  .md  al lado del original",
            style="Big.TButton", command=self.start_fast)
        self.btn_fast.pack(side="left", padx=PAD)
        self.btn_cancel = ttk.Button(act, text="Cancelar", command=self.cancel_job,
                                     state="disabled")
        self.btn_cancel.pack(side="left")
        self.lbl_redact = ttk.Label(act, text="", style="Hint.TLabel")
        self.lbl_redact.pack(side="right")

        self.pbar = ttk.Progressbar(tab, mode="determinate", maximum=1000)
        self.pbar.pack(fill="x", pady=(PAD, 4))

        logwrap = ttk.Frame(tab)
        logwrap.pack(fill="both", expand=True)
        self.log = tk.Text(logwrap, height=9, wrap="word", relief="solid",
                           borderwidth=1, font=("TkFixedFont", 9))
        sb2 = ttk.Scrollbar(logwrap, orient="vertical", command=self.log.yview)
        self.log.configure(yscrollcommand=sb2.set, state="disabled")
        self.log.pack(side="left", fill="both", expand=True)
        sb2.pack(side="right", fill="y")

        done = ttk.Frame(tab)
        done.pack(fill="x", pady=(4, 0))
        ttk.Button(done, text="Abrir carpeta de salida",
                   command=self.open_output).pack(side="left")
        ttk.Button(done, text="Ver el Markdown generado",
                   command=self.view_last_md).pack(side="left", padx=4)
        ttk.Button(done, text="Abrir en MDx",
                   command=self.open_in_mdx).pack(side="left", padx=4)
        return tab

    # ---------------- pestana 2: revisar --------------------------------
    def _tab_review(self) -> ttk.Frame:
        tab = ttk.Frame(self, padding=PAD)

        head = ttk.Frame(tab)
        head.pack(fill="x")
        ttk.Label(head, text="Que no debe salir del documento",
                  style="Head.TLabel").pack(side="left")
        ttk.Label(head, style="Hint.TLabel",
                  text="   Analiza el PDF, marca lo que sea confidencial y se "
                       "sustituira en todas las salidas.").pack(side="left")

        act = ttk.Frame(tab)
        act.pack(fill="x", pady=(PAD, 4))
        ttk.Button(act, text="Analizar documentos",
                   command=self.start_scan).pack(side="left")
        for text, cmd in (
            ("Marcar sugeridos", lambda: self._mark(lambda c: c.suggested)),
            ("Marcar todo", lambda: self._mark(lambda c: True)),
            ("Desmarcar todo", lambda: self._mark(lambda c: False)),
        ):
            ttk.Button(act, text=text, command=cmd).pack(side="left", padx=4)
        ttk.Button(act, text="Guardar lista...",
                   command=self.save_terms).pack(side="right")
        ttk.Button(act, text="Cargar lista...",
                   command=self.load_terms).pack(side="right", padx=4)

        mid = ttk.Frame(tab)
        mid.pack(fill="both", expand=True)

        cols = ("marca", "tipo", "veces", "paginas", "texto")
        self.tree = ttk.Treeview(mid, columns=cols, show="headings", height=13,
                                 selectmode="browse")
        for col, title, width, anchor in (
            ("marca", "", 34, "center"),
            ("tipo", "Tipo", 170, "w"),
            ("veces", "Veces", 55, "center"),
            ("paginas", "Paginas", 110, "w"),
            ("texto", "Texto detectado", 460, "w"),
        ):
            self.tree.heading(col, text=title)
            self.tree.column(col, width=width, anchor=anchor,
                             stretch=(col == "texto"))
        sb = ttk.Scrollbar(mid, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.tree.bind("<Button-1>", self._tree_click)
        self.tree.bind("<space>", self._tree_space)
        self.tree.bind("<<TreeviewSelect>>", self._show_context)

        ctx = ttk.LabelFrame(tab, text=" Contexto ", padding=6)
        ctx.pack(fill="x", pady=(4, 0))
        self.txt_ctx = tk.Text(ctx, height=3, wrap="word", relief="flat",
                               state="disabled", font=("TkDefaultFont", 9))
        self.txt_ctx.pack(fill="x")

        bottom = ttk.Frame(tab)
        bottom.pack(fill="x", pady=(PAD, 0))

        manual = ttk.LabelFrame(bottom, text=" Terminos propios (uno por linea) ",
                                padding=6)
        manual.pack(side="left", fill="both", expand=True)
        self.txt_terms = tk.Text(manual, height=6, wrap="none", relief="solid",
                                 borderwidth=1)
        self.txt_terms.pack(fill="both", expand=True)
        ttk.Label(manual, style="Hint.TLabel",
                  text="Prefijo re: para expresion regular").pack(anchor="w")

        opts = ttk.LabelFrame(bottom, text=" Como ocultarlo ", padding=6)
        opts.pack(side="left", fill="y", padx=(PAD, 0))
        ttk.Checkbutton(opts, text="Aplicar al convertir",
                        variable=self.v_redact,
                        command=self._update_redact_hint).pack(anchor="w")
        r = ttk.Frame(opts); r.pack(fill="x", pady=(6, 0))
        ttk.Label(r, text="Estilo:").pack(side="left")
        ttk.Combobox(r, textvariable=self.v_style, width=9, state="readonly",
                     values=("label", "mask", "hash", "remove")).pack(side="left", padx=4)
        ttk.Label(opts, style="Hint.TLabel", justify="left",
                  text="label  [CONFIDENCIAL_1]\nmask   [OCULTO]\n"
                       "hash   [REF:9F2A1C]\nremove se borra").pack(anchor="w", pady=(4, 0))
        ttk.Checkbutton(opts, text="No exportar ninguna imagen",
                        variable=self.v_dropimg).pack(anchor="w", pady=(6, 0))

        det = ttk.LabelFrame(bottom, text=" Detectores automaticos ", padding=6)
        det.pack(side="left", fill="y", padx=(PAD, 0))
        for i, (key, spec) in enumerate(DETECTORS.items()):
            ttk.Checkbutton(det, text=spec[1], variable=self.v_detectors[key]).grid(
                row=i % 5, column=i // 5, sticky="w", padx=(0, 10))
        return tab

    # ---------------- pestana 3: visor ----------------------------------
    def _tab_view(self) -> ttk.Frame:
        tab = ttk.Frame(self, padding=PAD)

        bar = ttk.Frame(tab)
        bar.pack(fill="x", pady=(0, 6))
        ttk.Button(bar, text="Abrir .md...", command=self.open_md).pack(side="left")
        ttk.Button(bar, text="Recargar", command=self.reload_md).pack(side="left", padx=4)
        ttk.Button(bar, text="Abrir en MDx",
                   command=self.open_in_mdx).pack(side="left", padx=4)
        ttk.Label(bar, text="Tema:").pack(side="left", padx=(12, 2))
        cb = ttk.Combobox(bar, textvariable=self.v_view_theme, width=8,
                          state="readonly", values=("claro", "oscuro"))
        cb.pack(side="left")
        cb.bind("<<ComboboxSelected>>",
                lambda e: self.viewer.set_theme(self.v_view_theme.get()))
        ttk.Button(bar, text="A-", width=4,
                   command=lambda: self._zoom(-1)).pack(side="left", padx=(12, 2))
        ttk.Button(bar, text="A+", width=4,
                   command=lambda: self._zoom(1)).pack(side="left")
        self.v_viewpath = tk.StringVar(value="(ningun fichero abierto)")
        ttk.Label(bar, textvariable=self.v_viewpath,
                  style="Hint.TLabel").pack(side="left", padx=12)

        wrap = ttk.Frame(tab, relief="solid", borderwidth=1)
        wrap.pack(fill="both", expand=True)
        self.viewer = MarkdownView(wrap, theme="claro")
        sb = ttk.Scrollbar(wrap, orient="vertical", command=self.viewer.yview)
        self.viewer.configure(yscrollcommand=sb.set)
        self.viewer.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.viewer.render(
            "# Visor de Markdown\n\nAbre un fichero `.md` con **Abrir .md...**, "
            "o convierte un PDF en la primera pestana y pulsa "
            "*Ver el Markdown generado*.\n\n"
            "Se muestran encabezados, listas, tablas, codigo e imagenes.\n\n"
            "Para seguir editando con mas herramientas (temas, matematicas, "
            "diagramas, sincronizacion), usa **Abrir en MDx**. Si no la tienes "
            "instalada, te manda a https://mdx.crgm.app/ para instalarla.\n"
        )
        return tab

    # -- ficheros ---------------------------------------------------------
    def add_files(self) -> None:
        paths = filedialog.askopenfilenames(
            title="Selecciona uno o varios PDF",
            filetypes=[("Documentos PDF", "*.pdf"), ("Todos", "*.*")])
        self._add([Path(p) for p in paths])

    def add_folder(self) -> None:
        folder = filedialog.askdirectory(title="Carpeta con PDF")
        if folder:
            self._add(sorted(Path(folder).glob("*.pdf")))

    def _add(self, paths) -> None:
        added = 0
        for p in paths:
            if p.suffix.lower() == ".pdf" and p not in self.files:
                self.files.append(p)
                try:
                    size = human_size(p.stat().st_size)
                except OSError:
                    size = "?"
                self.lst.insert("end", f"{p.name}   ({size})   -  {p.parent}")
                added += 1
        if added:
            self.v_status.set(f"{len(self.files)} documento(s) en la lista.")

    def remove_selected(self) -> None:
        for i in sorted(self.lst.curselection(), reverse=True):
            self.lst.delete(i)
            del self.files[i]
        self.v_status.set(f"{len(self.files)} documento(s) en la lista.")

    def clear_files(self) -> None:
        self.files.clear()
        self.lst.delete(0, "end")
        self.v_status.set("Lista vacia.")

    def pick_outdir(self) -> None:
        folder = filedialog.askdirectory(title="Carpeta de salida")
        if folder:
            self.v_outdir.set(folder)
            self.v_outmode.set("carpeta")

    # -- ajustes ----------------------------------------------------------
    def _collect_redaction(self) -> RedactionSettings:
        terms = [c.text for i, c in enumerate(self.candidates) if i in self.checked]
        patterns: list[str] = []
        for line in self.txt_terms.get("1.0", "end").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("re:"):
                patterns.append(line[3:].strip())
            else:
                terms.append(line)
        detectors = [k for k, v in self.v_detectors.items() if v.get()]
        return RedactionSettings(
            enabled=self.v_redact.get(),
            terms=terms, patterns=patterns, detectors=detectors,
            style=self.v_style.get(), drop_images=self.v_dropimg.get(),
        )

    def _settings(self, fast: bool = False) -> Settings:
        formats = [k for k, v in self.v_formats.items() if v.get()] or ["md"]
        out_dir = None
        if self.v_outmode.get() == "carpeta" and self.v_outdir.get().strip():
            out_dir = Path(self.v_outdir.get().strip())
        return Settings(
            inputs=list(self.files),
            out_dir=None if fast else out_dir,
            formats=["md"] if fast else formats,
            fast_mode=fast,
            ocr=self.v_ocr.get(),
            ocr_langs=self.v_lang.get().strip() or "spa+eng",
            ocr_dpi=int(self.v_dpi.get()),
            page_range=self.v_pages.get().strip(),
            extract_images=self.v_images.get() and not fast,
            detect_tables=self.v_tables.get(),
            detect_columns=self.v_columns.get(),
            keep_page_marks=self.v_pagemarks.get(),
            md_claude_header=self.v_claude.get(),
            xlsx_mode=self.v_xlsxmode.get(),
            redaction=self._collect_redaction(),
        )

    def _update_redact_hint(self) -> None:
        red = self._collect_redaction()
        n = len(red.terms) + len(red.patterns) + len(red.detectors)
        if red.enabled and n:
            self.lbl_redact.configure(text=f"Saneado activo: {n} regla(s)")
        elif red.enabled:
            self.lbl_redact.configure(text="Saneado activo pero sin reglas")
        else:
            self.lbl_redact.configure(text="")

    # -- trabajos ---------------------------------------------------------
    def _busy(self, busy: bool) -> None:
        state = "disabled" if busy else "normal"
        self.btn_convert.configure(state=state)
        self.btn_fast.configure(state=state)
        self.btn_cancel.configure(state="normal" if busy else "disabled")

    def start_convert(self) -> None:
        self._start(fast=False)

    def start_fast(self) -> None:
        self._start(fast=True)

    def _start(self, fast: bool) -> None:
        if self.worker and self.worker.is_alive():
            return
        if not self.files:
            messagebox.showinfo(APP_NAME, "Anade al menos un PDF.")
            return
        settings = self._settings(fast=fast)
        self._update_redact_hint()
        self._log_clear()
        self._log(f"Convirtiendo {len(self.files)} documento(s) "
                  f"a {', '.join(settings.formats)}"
                  + ("  [modo rapido]" if fast else ""))
        if settings.redaction.enabled:
            red = settings.redaction
            self._log(f"Saneado: {len(red.terms)} terminos, "
                      f"{len(red.detectors)} detectores, estilo {red.style}")
        self.cancel_flag.clear()
        self._busy(True)
        self.last_results = []
        self.worker = threading.Thread(
            target=self._run_convert, args=(settings,), daemon=True)
        self.worker.start()

    def _run_convert(self, settings: Settings) -> None:
        try:
            total = len(settings.inputs)
            for i, src in enumerate(settings.inputs):
                if self.cancel_flag.is_set():
                    break

                def progress(msg: str, frac: float, i=i, src=src) -> None:
                    self.queue.put(("progress",
                                    (i + max(0.0, min(frac, 1.0))) / total,
                                    f"[{i+1}/{total}] {src.name}: {msg}"))

                result = convert_file(src, settings, progress=progress,
                                      cancel=self.cancel_flag.is_set)
                self.queue.put(("result", result, None))
            self.queue.put(("done", None, None))
        except Exception:
            self.queue.put(("error", traceback.format_exc(), None))

    def start_scan(self) -> None:
        if self.worker and self.worker.is_alive():
            return
        if not self.files:
            messagebox.showinfo(APP_NAME, "Anade al menos un PDF en la pestana 1.")
            return
        self._busy(True)
        self.cancel_flag.clear()
        self.v_status.set("Analizando el documento...")
        settings = self._settings()
        settings.extract_images = False
        self.worker = threading.Thread(
            target=self._run_scan, args=(settings,), daemon=True)
        self.worker.start()

    def _run_scan(self, settings: Settings) -> None:
        try:
            from .pipeline import build_document
            from .scan_sensitive import scan

            merged: list = []
            total = len(settings.inputs)
            for i, src in enumerate(settings.inputs):
                if self.cancel_flag.is_set():
                    break

                def progress(msg: str, frac: float, i=i, src=src) -> None:
                    self.queue.put(("progress",
                                    (i + max(0.0, min(frac, 1.0))) / total,
                                    f"Analizando {src.name}: {msg}"))

                doc = build_document(src, settings, progress=progress,
                                     cancel=self.cancel_flag.is_set)
                merged.extend(scan(doc))

            # Une candidatos repetidos entre documentos.
            best: dict[tuple, object] = {}
            for c in merged:
                key = (c.kind, c.text.lower())
                if key in best:
                    best[key].count += c.count
                    best[key].pages |= c.pages
                else:
                    best[key] = c
            result = sorted(best.values(),
                            key=lambda c: (-c.score, -c.count, c.text.lower()))
            self.queue.put(("candidates", result, None))
        except Exception:
            self.queue.put(("error", traceback.format_exc(), None))

    def cancel_job(self) -> None:
        self.cancel_flag.set()
        self.v_status.set("Cancelando...")

    # -- cola de eventos --------------------------------------------------
    def _drain_queue(self) -> None:
        try:
            while True:
                kind, payload, extra = self.queue.get_nowait()
                if kind == "progress":
                    self.pbar["value"] = payload * 1000
                    self.v_status.set(extra)
                elif kind == "result":
                    self._on_result(payload)
                elif kind == "candidates":
                    self._fill_candidates(payload)
                    self._busy(False)
                    self.pbar["value"] = 0
                    self.v_status.set(f"{len(payload)} candidatos encontrados.")
                    self.nb.select(1)
                elif kind == "done":
                    self._busy(False)
                    self.pbar["value"] = 1000
                    self.v_status.set("Conversion terminada.")
                elif kind == "error":
                    self._busy(False)
                    self._log("ERROR INESPERADO\n" + str(payload))
                    messagebox.showerror(APP_NAME, str(payload)[-1500:])
        except queue.Empty:
            pass
        self.after(80, self._drain_queue)

    def _on_result(self, result) -> None:
        self.last_results.append(result)
        name = result.source.name
        if result.errors:
            self._log(f"{name}: ERROR")
            for e in result.errors:
                self._log(f"    {e}")
            return
        d = result.document
        self._log(
            f"{name}: {d.n_pages} pag | {d.n_tables} tablas | {d.n_images} img"
            f" | OCR en {d.n_ocr_pages} | ~{result.tokens_estimate} tokens"
            f" | {result.elapsed_s:.1f}s"
        )
        if result.redaction and result.redaction.total:
            self._log(f"    saneado: {result.redaction.total} sustituciones")
            if result.redaction.leaked:
                self._log("    ATENCION: quedaron terminos sin ocultar: "
                          + ", ".join(result.redaction.leaked))
        for w in result.warnings:
            self._log(f"    aviso: {w}")
        for fmt, path in result.outputs.items():
            self._log(f"    -> {path}")
            if fmt == "md":
                self.last_md = path

    # -- lista de candidatos ---------------------------------------------
    def _fill_candidates(self, candidates: list) -> None:
        self.candidates = candidates
        self.checked = {i for i, c in enumerate(candidates) if c.suggested}
        self.tree.delete(*self.tree.get_children())
        for i, c in enumerate(candidates):
            self.tree.insert(
                "", "end", iid=str(i),
                values=(self._mark_char(i), c.kind_label, c.count,
                        c.pages_str, c.text))
        self._update_redact_hint()

    def _mark_char(self, i: int) -> str:
        return "[x]" if i in self.checked else "[ ]"

    def _toggle(self, iid: str) -> None:
        i = int(iid)
        if i in self.checked:
            self.checked.discard(i)
        else:
            self.checked.add(i)
        self.tree.set(iid, "marca", self._mark_char(i))
        self._update_redact_hint()

    def _tree_click(self, event) -> None:
        if self.tree.identify_region(event.x, event.y) != "cell":
            return
        if self.tree.identify_column(event.x) != "#1":
            return
        iid = self.tree.identify_row(event.y)
        if iid:
            self._toggle(iid)

    def _tree_space(self, _event) -> str:
        sel = self.tree.selection()
        if sel:
            self._toggle(sel[0])
        return "break"

    def _mark(self, predicate) -> None:
        self.checked = {i for i, c in enumerate(self.candidates) if predicate(c)}
        for i in range(len(self.candidates)):
            self.tree.set(str(i), "marca", self._mark_char(i))
        self._update_redact_hint()

    def _show_context(self, _event=None) -> None:
        sel = self.tree.selection()
        self.txt_ctx.configure(state="normal")
        self.txt_ctx.delete("1.0", "end")
        if sel:
            c = self.candidates[int(sel[0])]
            self.txt_ctx.insert("end", "\n".join(c.samples) or "(sin contexto)")
        self.txt_ctx.configure(state="disabled")

    def save_terms(self) -> None:
        red = self._collect_redaction()
        path = filedialog.asksaveasfilename(
            title="Guardar lista de terminos", defaultextension=".json",
            filetypes=[("Lista PDFx", "*.json"), ("Texto", "*.txt")])
        if not path:
            return
        p = Path(path)
        if p.suffix.lower() == ".txt":
            lines = list(red.terms) + [f"re:{x}" for x in red.patterns]
            lines += [f"det:{d}" for d in red.detectors]
            p.write_text("\n".join(lines) + "\n", encoding="utf-8")
        else:
            p.write_text(json.dumps({
                "terminos": red.terms, "patrones": red.patterns,
                "detectores": red.detectors, "estilo": red.style,
            }, ensure_ascii=False, indent=2), encoding="utf-8")
        self.v_status.set(f"Lista guardada en {p.name}")

    def load_terms(self) -> None:
        path = filedialog.askopenfilename(
            title="Cargar lista de terminos",
            filetypes=[("Lista PDFx", "*.json"), ("Texto", "*.txt"),
                       ("Todos", "*.*")])
        if not path:
            return
        p = Path(path)
        terms: list[str] = []
        patterns: list[str] = []
        detectors: list[str] = []
        try:
            if p.suffix.lower() == ".json":
                data = json.loads(p.read_text(encoding="utf-8"))
                terms = data.get("terminos", [])
                patterns = data.get("patrones", [])
                detectors = data.get("detectores", [])
                if data.get("estilo"):
                    self.v_style.set(data["estilo"])
                for item in data.get("seleccionados", []):
                    if isinstance(item, dict) and item.get("elegido"):
                        terms.append(item.get("texto", ""))
            else:
                for line in p.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if line.startswith("re:"):
                        patterns.append(line[3:].strip())
                    elif line.startswith("det:"):
                        detectors.append(line[4:].strip())
                    else:
                        terms.append(line)
        except Exception as exc:
            messagebox.showerror(APP_NAME, f"No se pudo leer la lista:\n{exc}")
            return

        self.txt_terms.delete("1.0", "end")
        self.txt_terms.insert("1.0", "\n".join(
            [t for t in terms if t] + [f"re:{x}" for x in patterns]))
        for key, var in self.v_detectors.items():
            var.set(key in detectors)
        self.v_redact.set(True)
        self._update_redact_hint()
        self.v_status.set(f"Lista cargada de {p.name}")

    # -- visor ------------------------------------------------------------
    def open_md(self) -> None:
        path = filedialog.askopenfilename(
            title="Abrir Markdown",
            filetypes=[("Markdown", "*.md *.markdown *.txt"), ("Todos", "*.*")])
        if path:
            self._load_md(Path(path))

    def reload_md(self) -> None:
        if self.last_md and self.last_md.exists():
            self._load_md(self.last_md)

    def view_last_md(self) -> None:
        if not self.last_md or not self.last_md.exists():
            messagebox.showinfo(APP_NAME, "Todavia no hay ningun Markdown generado.")
            return
        self._load_md(self.last_md)

    def open_in_mdx(self) -> None:
        if not self.last_md or not self.last_md.exists():
            messagebox.showinfo(APP_NAME, "Todavia no hay ningun Markdown generado.")
            return
        if hay_manejador_md():
            open_in_explorer(self.last_md)
            return
        import webbrowser
        webbrowser.open("https://mdx.crgm.app/")
        messagebox.showinfo(
            APP_NAME,
            "No encontre ninguna aplicacion asociada a los ficheros .md en "
            "este equipo.\n\nSe abrio https://mdx.crgm.app/ - instala MDx "
            "ahi (o arrastra el archivo a la pagina) y vuelve a intentarlo."
        )

    def _load_md(self, path: Path) -> None:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            messagebox.showerror(APP_NAME, f"No se pudo abrir:\n{exc}")
            return
        self.last_md = path
        self.viewer.render(text, path.parent)
        self.v_viewpath.set(str(path))
        self.nb.select(2)

    def _zoom(self, delta: int) -> None:
        self.viewer.set_base_size(self.viewer._base_size + delta)

    def open_output(self) -> None:
        if self.last_results:
            for r in reversed(self.last_results):
                if r.outputs:
                    open_in_explorer(next(iter(r.outputs.values())).parent)
                    return
        messagebox.showinfo(APP_NAME, "Todavia no se ha generado nada.")

    # -- varios -----------------------------------------------------------
    def _check_ocr(self) -> None:
        from .engines.ocr import available_languages, find_tesseract
        exe = find_tesseract()
        if exe:
            langs = available_languages(exe)
            self.v_ocrinfo.set(f"OCR listo - idiomas: {', '.join(langs) or '?'}")
        else:
            self.v_ocrinfo.set("Sin Tesseract: los PDF escaneados no se leeran")

    def _log_clear(self) -> None:
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")

    def _log(self, text: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", text + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _on_close(self) -> None:
        self.cancel_flag.set()
        self.destroy()


def run() -> int:
    try:
        app = App()
    except tk.TclError as exc:
        print(f"No hay entorno grafico disponible: {exc}", file=sys.stderr)
        return 1
    app.mainloop()
    return 0
