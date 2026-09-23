"""Modelo de documento intermedio.

El pipeline convierte cualquier PDF (nativo, escaneado o mixto) a estas
estructuras; los writers solo saben de esto, nunca de PDF ni de OCR.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Literal, Optional, Union

BBox = tuple[float, float, float, float]  # (x0, top, x1, bottom) en puntos PDF


def merge_bbox(boxes: Iterable[BBox]) -> BBox:
    boxes = list(boxes)
    if not boxes:
        return (0.0, 0.0, 0.0, 0.0)
    return (
        min(b[0] for b in boxes),
        min(b[1] for b in boxes),
        max(b[2] for b in boxes),
        max(b[3] for b in boxes),
    )


@dataclass(slots=True)
class Word:
    """Palabra con su caja. Origen nativo (pdfminer) u OCR (tesseract)."""

    text: str
    x0: float
    top: float
    x1: float
    bottom: float
    size: float = 0.0
    bold: bool = False
    italic: bool = False
    conf: float = 100.0
    font: str = ""
    # False = texto rotado (pdfplumber). Los planos electricos rotan etiquetas
    # 90 grados junto a los cables; una palabra asi no debe mezclarse caracter
    # por caracter con el flujo horizontal (ver analysis/layout.py).
    upright: bool = True

    @property
    def bbox(self) -> BBox:
        return (self.x0, self.top, self.x1, self.bottom)

    @property
    def height(self) -> float:
        return self.bottom - self.top

    @property
    def cx(self) -> float:
        return (self.x0 + self.x1) / 2.0

    @property
    def cy(self) -> float:
        return (self.top + self.bottom) / 2.0


@dataclass(slots=True)
class Line:
    """Renglon: palabras ordenadas por x."""

    words: list[Word] = field(default_factory=list)

    @property
    def text(self) -> str:
        return " ".join(w.text for w in self.words if w.text)

    @property
    def bbox(self) -> BBox:
        return merge_bbox(w.bbox for w in self.words)

    @property
    def size(self) -> float:
        """Tamano representativo: mediana de las palabras (robusto a super/subindices)."""
        sizes = sorted(w.size for w in self.words if w.size > 0)
        if not sizes:
            hs = sorted(w.height for w in self.words)
            return hs[len(hs) // 2] if hs else 0.0
        return sizes[len(sizes) // 2]

    @property
    def bold_ratio(self) -> float:
        if not self.words:
            return 0.0
        chars = sum(len(w.text) for w in self.words) or 1
        return sum(len(w.text) for w in self.words if w.bold) / chars

    @property
    def conf(self) -> float:
        if not self.words:
            return 0.0
        return sum(w.conf for w in self.words) / len(self.words)


BlockKind = Literal["paragraph", "heading", "list_item", "code", "caption"]


@dataclass(slots=True)
class Block:
    kind: BlockKind = "paragraph"
    level: int = 0            # 1..6 si kind == "heading"
    lines: list[Line] = field(default_factory=list)
    marker: str = ""          # vineta o numeracion detectada en list_item
    ordered: bool = False
    indent: int = 0           # nivel de anidamiento de lista
    # Texto ya procesado que sustituye al de las lineas. Lo usa el saneado:
    # un termino como "Talleres Munoz S.L." abarca varias palabras, asi que
    # solo puede reconocerse sobre el texto completo del bloque.
    text_override: str | None = None

    @property
    def text(self) -> str:
        if self.text_override is not None:
            return self.text_override
        return " ".join(ln.text for ln in self.lines).strip()

    @property
    def bbox(self) -> BBox:
        return merge_bbox(ln.bbox for ln in self.lines)


@dataclass(slots=True)
class Table:
    rows: list[list[str]] = field(default_factory=list)
    bbox: BBox = (0.0, 0.0, 0.0, 0.0)
    has_header: bool = True
    source: str = "native"    # native | ruled | whitespace
    confidence: float = 1.0

    @property
    def n_rows(self) -> int:
        return len(self.rows)

    @property
    def n_cols(self) -> int:
        return max((len(r) for r in self.rows), default=0)

    def normalized(self) -> list[list[str]]:
        """Rellena filas cortas para que la matriz sea rectangular."""
        n = self.n_cols
        return [list(r) + [""] * (n - len(r)) for r in self.rows]


@dataclass(slots=True)
class ImageRef:
    path: Optional[Path] = None   # ruta relativa al directorio de salida
    abs_path: Optional[Path] = None
    bbox: BBox = (0.0, 0.0, 0.0, 0.0)
    width: int = 0
    height: int = 0
    caption: str = ""
    kind: str = "embedded"        # embedded | page-render | region


Element = Union[Block, Table, ImageRef]


# --------------------------------------------------------------------------
# Esquemas electricos unifilares (convencion EPLAN): la conectividad viene
# codificada en el propio texto de la pagina (tags, referencias cruzadas
# pagina.linea, numero+color+calibre de cable), no hace falta geometria.
# Ver analysis/schematic.py. Una lista de componentes + una lista de cables
# (aristas) basta; no hace falta una clase de grafo propia.
ComponentKind = Literal[
    "interruptor", "contactor", "motor", "borne", "fusible", "sensor", "plc",
]


@dataclass(slots=True)
class Component:
    """Un elemento del esquema con su tag EPLAN (`-K6.2`, `-M6.1`...)."""

    tag: str
    kind: ComponentKind
    # Denominacion comercial ("PKZM0-6,3", "DILM17-01") o descripcion libre
    # (motores: "Motor soplo sobre hendedores"). Vacio si no hay confianza.
    label: str = ""
    # Atributos sueltos ya formateados: Ir=4.8A, bobina=24Vdc, potencia=2.2kW...
    attrs: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class Wire:
    """Un cable/hilo identificado por su numero (convencion `pagina.linea`)."""

    number: str
    color: str = ""     # codigo de 2 letras: BK, BU, GNYE...
    gauge: str = ""      # seccion en mm2, notacion europea: "1,5"
    frm: str = ""         # extremo origen: "-Q6.1" o "-Q6.1:T1" si se sabe el pin
    to: str = ""            # extremo destino


@dataclass(slots=True)
class CrossRef:
    """Referencia cruzada `-K6.2 /6.4`: el otro extremo esta en pagina 6, linea 4."""

    tag: str
    page: str
    line: str


@dataclass(slots=True)
class Schematic:
    """Resultado de analysis/schematic.py para una pagina densa en patrones
    EPLAN. `None` en Page.schematic significa "esta pagina no es un esquema"."""

    source: str = ""      # "L1 L2 L3 480V 50Hz" si se detecto la acometida
    components: list[Component] = field(default_factory=list)
    wires: list[Wire] = field(default_factory=list)
    crossrefs: list[CrossRef] = field(default_factory=list)

    @property
    def density(self) -> int:
        return len(self.components) + len(self.wires) + len(self.crossrefs)


@dataclass(slots=True)
class Page:
    number: int                      # 1-based
    width: float = 0.0
    height: float = 0.0
    elements: list[Element] = field(default_factory=list)
    source: str = "text"             # text | ocr | mixed | empty
    rotation: int = 0
    ocr_conf: float = 0.0
    notes: list[str] = field(default_factory=list)
    # Si no es None, esta pagina se detecto como esquema unifilar y el
    # writer de markdown debe emitir un bloque ```unifilar en vez de prosa.
    schematic: Optional[Schematic] = None

    @property
    def tables(self) -> list[Table]:
        return [e for e in self.elements if isinstance(e, Table)]

    @property
    def images(self) -> list[ImageRef]:
        return [e for e in self.elements if isinstance(e, ImageRef)]

    @property
    def blocks(self) -> list[Block]:
        return [e for e in self.elements if isinstance(e, Block)]

    @property
    def text(self) -> str:
        return "\n".join(b.text for b in self.blocks)


@dataclass(slots=True)
class Document:
    source_path: Path
    pages: list[Page] = field(default_factory=list)
    title: str = ""
    author: str = ""
    subject: str = ""
    producer: str = ""
    created: str = ""
    encrypted: bool = False
    warnings: list[str] = field(default_factory=list)
    elapsed_s: float = 0.0
    engine_notes: dict[str, str] = field(default_factory=dict)

    @property
    def n_pages(self) -> int:
        return len(self.pages)

    @property
    def n_tables(self) -> int:
        return sum(len(p.tables) for p in self.pages)

    @property
    def n_images(self) -> int:
        return sum(len(p.images) for p in self.pages)

    @property
    def n_ocr_pages(self) -> int:
        return sum(1 for p in self.pages if p.source in ("ocr", "mixed"))

    @property
    def char_count(self) -> int:
        return sum(len(p.text) for p in self.pages)
