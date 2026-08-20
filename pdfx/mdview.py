"""Visor de Markdown sobre un widget Text de Tkinter.

Renderiza encabezados, negritas, cursivas, codigo, listas, citas, tablas,
lineas horizontales e imagenes en linea. No necesita ninguna libreria externa:
la app portable sigue siendo un solo paquete.
"""

from __future__ import annotations

import re
import tkinter as tk
import tkinter.font as tkfont
import webbrowser
from pathlib import Path

try:
    from PIL import Image, ImageTk
    _PIL = True
except ImportError:  # pragma: no cover
    _PIL = False

_FENCE_RE = re.compile(r"^\s*(```+|~~~+)\s*(\w+)?\s*$")
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
_HR_RE = re.compile(r"^\s*([-*_])\s*(?:\1\s*){2,}$")
_UL_RE = re.compile(r"^(\s*)[-*+]\s+(.*)$")
_OL_RE = re.compile(r"^(\s*)(\d{1,3})[.)]\s+(.*)$")
_QUOTE_RE = re.compile(r"^\s*>\s?(.*)$")
_TABLE_SEP_RE = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)+\|?\s*$")
_IMAGE_RE = re.compile(r"^\s*!\[([^\]]*)\]\(([^)]+)\)\s*$")
_FRONT_RE = re.compile(r"^---\s*$")

# En linea: `codigo`, **negrita**, *cursiva*, [texto](url), ![alt](src)
_INLINE_RE = re.compile(
    r"(?P<code>`[^`]+`)"
    r"|(?P<bold>\*\*[^*]+\*\*|__[^_]+__)"
    r"|(?P<italic>\*[^*\n]+\*|_[^_\n]+_)"
    r"|(?P<link>\[[^\]]*\]\([^)]+\))"
)

PALETTES = {
    "claro": {
        "bg": "#ffffff", "fg": "#1c1f24", "muted": "#6b737d",
        "rule": "#dfe3e8", "code_bg": "#f2f4f7", "code_fg": "#8a1f4b",
        "link": "#1a56c4", "quote": "#4a5563", "quote_bar": "#c8ced6",
        "th_bg": "#eef2f6", "sel": "#cfe3ff",
    },
    "oscuro": {
        "bg": "#16191d", "fg": "#e6e9ed", "muted": "#98a1ac",
        "rule": "#2c3138", "code_bg": "#22262c", "code_fg": "#ff9ec4",
        "link": "#7fb0ff", "quote": "#b3bcc6", "quote_bar": "#3a414a",
        "th_bg": "#232830", "sel": "#2a4a7a",
    },
}


class MarkdownView(tk.Text):
    """Text de solo lectura que pinta Markdown."""

    def __init__(self, master, theme: str = "claro", base_size: int = 11, **kw):
        super().__init__(
            master, wrap="word", relief="flat", borderwidth=0,
            padx=26, pady=18, spacing1=2, spacing3=6, cursor="arrow", **kw
        )
        self._theme = theme if theme in PALETTES else "claro"
        self._base_size = base_size
        self._images: list = []          # evita que el GC borre las imagenes
        self._base_dir = Path(".")
        self._source = ""
        self._build_fonts()
        self._build_tags()
        self.bind("<Key>", self._block_keys)

    # -- apariencia -------------------------------------------------------
    def _build_fonts(self) -> None:
        family = self._pick_family(
            ("Segoe UI", "Inter", "Helvetica Neue", "DejaVu Sans", "Arial")
        )
        mono = self._pick_family(
            ("Cascadia Mono", "Consolas", "DejaVu Sans Mono", "Menlo", "Courier New")
        )
        b = self._base_size
        self.f_body = tkfont.Font(family=family, size=b)
        self.f_bold = tkfont.Font(family=family, size=b, weight="bold")
        self.f_italic = tkfont.Font(family=family, size=b, slant="italic")
        self.f_mono = tkfont.Font(family=mono, size=b - 1)
        self.f_h = [
            tkfont.Font(family=family, size=b + delta, weight="bold")
            for delta in (10, 7, 4, 2, 1, 0)
        ]
        self.configure(font=self.f_body)

    def _pick_family(self, options: tuple[str, ...]) -> str:
        available = {f.lower() for f in tkfont.families()}
        for name in options:
            if name.lower() in available:
                return name
        return "TkDefaultFont"

    def _build_tags(self) -> None:
        c = PALETTES[self._theme]
        self.configure(background=c["bg"], foreground=c["fg"],
                       insertbackground=c["fg"], selectbackground=c["sel"])
        for i, font in enumerate(self.f_h, start=1):
            self.tag_configure(
                f"h{i}", font=font,
                spacing1=16 if i <= 2 else 12, spacing3=6,
                foreground=c["fg"],
            )
        self.tag_configure("h1", spacing3=10)
        self.tag_configure("bold", font=self.f_bold)
        self.tag_configure("italic", font=self.f_italic)
        self.tag_configure("code", font=self.f_mono,
                           background=c["code_bg"], foreground=c["code_fg"])
        self.tag_configure("codeblock", font=self.f_mono,
                           background=c["code_bg"], lmargin1=22, lmargin2=22,
                           spacing1=3, spacing3=3)
        self.tag_configure("link", foreground=c["link"], underline=True)
        self.tag_configure("quote", foreground=c["quote"], lmargin1=22,
                           lmargin2=22, font=self.f_italic)
        self.tag_configure("muted", foreground=c["muted"], font=self.f_mono)
        self.tag_configure("bullet", lmargin1=22, lmargin2=40)
        self.tag_configure("bullet2", lmargin1=48, lmargin2=66)
        self.tag_configure("hr", foreground=c["rule"])
        self.tag_configure("table", font=self.f_mono, lmargin1=14, lmargin2=14)
        self.tag_configure("thead", font=self.f_mono, background=c["th_bg"],
                           lmargin1=14, lmargin2=14)
        self.tag_configure("center", justify="center")
        self.tag_bind("link", "<Enter>", lambda e: self.configure(cursor="hand2"))
        self.tag_bind("link", "<Leave>", lambda e: self.configure(cursor="arrow"))
        self.tag_bind("link", "<Button-1>", self._open_link)

    def set_theme(self, theme: str) -> None:
        if theme not in PALETTES or theme == self._theme:
            return
        self._theme = theme
        self._build_tags()
        if self._source:
            self.render(self._source, self._base_dir)

    def set_base_size(self, size: int) -> None:
        self._base_size = max(7, min(24, size))
        self._build_fonts()
        self._build_tags()
        if self._source:
            self.render(self._source, self._base_dir)

    # -- interaccion ------------------------------------------------------
    def _block_keys(self, event):
        # Se permite copiar y navegar, pero no editar.
        if event.state & 0x4 and event.keysym.lower() in ("c", "a"):
            return None
        if event.keysym in ("Up", "Down", "Left", "Right", "Prior", "Next",
                            "Home", "End"):
            return None
        return "break"

    def _open_link(self, event):
        idx = self.index(f"@{event.x},{event.y}")
        for (start, end), target in self._links:
            if self.compare(idx, ">=", start) and self.compare(idx, "<", end):
                if target.startswith(("http://", "https://", "mailto:")):
                    webbrowser.open(target)
                else:
                    path = (self._base_dir / target).resolve()
                    if path.exists():
                        webbrowser.open(path.as_uri())
                return

    # -- render -----------------------------------------------------------
    def render(self, text: str, base_dir: Path | None = None) -> None:
        self._source = text
        self._base_dir = Path(base_dir or ".")
        self._images.clear()
        self._links: list[tuple[tuple[str, str], str]] = []

        self.configure(state="normal")
        self.delete("1.0", "end")

        lines = text.splitlines()
        i = 0
        # Front matter YAML al principio del fichero
        if lines and _FRONT_RE.match(lines[0]):
            j = 1
            while j < len(lines) and not _FRONT_RE.match(lines[j]):
                j += 1
            meta = "\n".join(lines[1:j])
            if meta.strip():
                self._insert(meta.strip() + "\n", ("muted",))
                self._hr()
            i = j + 1

        while i < len(lines):
            line = lines[i]

            fence = _FENCE_RE.match(line)
            if fence:
                i += 1
                buf = []
                closing = fence.group(1)[0] * 3
                while i < len(lines) and not lines[i].strip().startswith(closing):
                    buf.append(lines[i])
                    i += 1
                self._insert("\n".join(buf) + "\n", ("codeblock",))
                i += 1
                continue

            if not line.strip():
                self._insert("\n")
                i += 1
                continue

            if line.strip().startswith("<!--"):
                comment = line.strip().strip("<!->").strip()
                self._insert(f"{comment}\n", ("muted",))
                i += 1
                continue

            if _HR_RE.match(line):
                self._hr()
                i += 1
                continue

            img = _IMAGE_RE.match(line)
            if img:
                self._insert_image(img.group(1), img.group(2))
                i += 1
                continue

            head = _HEADING_RE.match(line)
            if head:
                level = len(head.group(1))
                self._insert_inline(head.group(2).strip() + "\n", (f"h{level}",))
                i += 1
                continue

            # Tabla: cabecera + separador
            if "|" in line and i + 1 < len(lines) and _TABLE_SEP_RE.match(lines[i + 1]):
                i = self._render_table(lines, i)
                continue

            quote = _QUOTE_RE.match(line)
            if quote:
                buf = []
                while i < len(lines) and (_QUOTE_RE.match(lines[i]) or
                                          (buf and lines[i].strip())):
                    m = _QUOTE_RE.match(lines[i])
                    buf.append(m.group(1) if m else lines[i].strip())
                    i += 1
                self._insert_inline(" ".join(buf).strip() + "\n", ("quote",))
                continue

            ul = _UL_RE.match(line)
            ol = _OL_RE.match(line)
            if ul or ol:
                indent = len((ul or ol).group(1))
                tag = "bullet2" if indent >= 2 else "bullet"
                marker = "• " if ul else f"{ol.group(2)}. "
                body = ul.group(2) if ul else ol.group(3)
                self._insert(marker, (tag, "bold"))
                self._insert_inline(body + "\n", (tag,))
                i += 1
                continue

            # Parrafo: une renglones hasta la siguiente linea en blanco
            buf = [line.strip()]
            i += 1
            while i < len(lines) and lines[i].strip() and not _is_block_start(lines[i]):
                buf.append(lines[i].strip())
                i += 1
            self._insert_inline(" ".join(buf) + "\n", ())

        self.configure(state="disabled")
        self.see("1.0")

    # -- primitivas -------------------------------------------------------
    def _insert(self, text: str, tags: tuple = ()) -> None:
        self.insert("end", text, tags)

    def _hr(self) -> None:
        self._insert("─" * 90 + "\n", ("hr",))

    def _insert_inline(self, text: str, base_tags: tuple) -> None:
        pos = 0
        for m in _INLINE_RE.finditer(text):
            if m.start() > pos:
                self._insert(text[pos:m.start()], base_tags)
            kind = m.lastgroup
            raw = m.group(0)
            if kind == "code":
                self._insert(raw[1:-1], base_tags + ("code",))
            elif kind == "bold":
                self._insert(raw[2:-2], base_tags + ("bold",))
            elif kind == "italic":
                self._insert(raw[1:-1], base_tags + ("italic",))
            elif kind == "link":
                label, _, target = raw[1:-1].partition("](")
                start = self.index("end-1c")
                self._insert(label, base_tags + ("link",))
                end = self.index("end-1c")
                self._links.append(((start, end), target))
            pos = m.end()
        if pos < len(text):
            self._insert(text[pos:], base_tags)

    def _insert_image(self, alt: str, src: str) -> None:
        path = Path(src)
        if not path.is_absolute():
            path = self._base_dir / src
        if not _PIL or not path.exists():
            self._insert(f"[imagen: {alt or src}]\n", ("muted", "center"))
            return
        try:
            img = Image.open(path)
            img.load()
            max_w = max(320, self.winfo_width() - 80)
            if img.width > max_w:
                ratio = max_w / img.width
                img = img.resize((int(img.width * ratio), int(img.height * ratio)),
                                 Image.LANCZOS)
            photo = ImageTk.PhotoImage(img)
            self._images.append(photo)
            self._insert("\n")
            self.image_create("end", image=photo)
            self._insert("\n")
            if alt:
                self._insert(alt + "\n", ("muted", "center"))
        except Exception:
            self._insert(f"[imagen no legible: {src}]\n", ("muted", "center"))

    def _render_table(self, lines: list[str], i: int) -> int:
        def cells(row: str) -> list[str]:
            row = row.strip()
            if row.startswith("|"):
                row = row[1:]
            if row.endswith("|"):
                row = row[:-1]
            return [c.strip().replace("\\|", "|").replace("<br>", " ")
                    for c in re.split(r"(?<!\\)\|", row)]

        header = cells(lines[i])
        i += 2
        body: list[list[str]] = []
        while i < len(lines) and "|" in lines[i] and lines[i].strip():
            body.append(cells(lines[i]))
            i += 1

        n = max([len(header)] + [len(r) for r in body] or [0])
        header += [""] * (n - len(header))
        body = [r + [""] * (n - len(r)) for r in body]
        widths = [
            max(len(header[c]), *(len(r[c]) for r in body)) if body else len(header[c])
            for c in range(n)
        ]
        widths = [min(w, 42) for w in widths]

        def fmt(row: list[str]) -> str:
            return "  ".join(
                (row[c][:widths[c]]).ljust(widths[c]) for c in range(n)
            ).rstrip()

        has_header = any(h for h in header)
        self._insert("\n")
        if has_header:
            self._insert(fmt(header) + "\n", ("thead",))
            self._insert("  ".join("-" * w for w in widths) + "\n", ("table", "muted"))
        for row in body:
            self._insert(fmt(row) + "\n", ("table",))
        self._insert("\n")
        return i


def _is_block_start(line: str) -> bool:
    return bool(
        _HEADING_RE.match(line) or _UL_RE.match(line) or _OL_RE.match(line)
        or _QUOTE_RE.match(line) or _HR_RE.match(line) or _FENCE_RE.match(line)
        or _IMAGE_RE.match(line) or line.strip().startswith(("|", "<!--"))
    )
