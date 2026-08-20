"""Propuesta de terminos sensibles para que el usuario revise antes de exportar.

No decide nada por su cuenta: solo lista candidatos con su recuento, las paginas
donde aparecen y un fragmento de contexto, para que la persona marque cuales
quiere ocultar.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field

from .model import Block, Document, Table
from .redact import DETECTORS
from .util.text import fold

# Palabras que empiezan frase o son genericas: nunca son "entidad sensible".
_STOPWORDS = {
    # espanol
    "el", "la", "los", "las", "un", "una", "unos", "unas", "de", "del", "al",
    "y", "o", "u", "e", "en", "con", "sin", "por", "para", "segun", "sobre",
    "que", "se", "su", "sus", "este", "esta", "estos", "estas", "ese", "esa",
    "como", "mas", "pero", "si", "no", "es", "son", "fue", "ser", "hay",
    "tabla", "figura", "pagina", "anexo", "capitulo", "apartado", "seccion",
    "nota", "aviso", "total", "fecha", "hora", "codigo", "numero", "cantidad",
    "descripcion", "observaciones", "resultado", "valor", "unidad", "tipo",
    "modelo", "referencia", "version", "revision", "documento", "informe",
    "manual", "indice", "general", "sistema", "equipo", "maquina", "linea",
    "proceso", "control", "seguridad", "mantenimiento", "operacion",
    # ingles
    "the", "and", "of", "in", "for", "with", "to", "from", "by", "on", "at",
    "is", "are", "was", "this", "that", "page", "table", "figure", "note",
    "total", "date", "code", "number", "type", "model", "value", "unit",
    "description", "report", "manual", "index", "general", "system",
}

_WORD_RE = re.compile(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ][\wÁÉÍÓÚÜÑáéíóúüñ.&'-]*")
# Secuencia de 1-4 palabras capitalizadas: "Muñoz Maquinaria S.L."
# [^\S\n] = espacio que no sea salto de linea: una entidad no cruza renglones
# ni celdas de tabla, y sin esto se pegan "ABB-7710" y "Contactor" de dos celdas.
_PROPER_RE = re.compile(
    r"\b(?:[A-ZÁÉÍÓÚÜÑ][\wáéíóúüñ.&'-]{1,}[^\S\n]+){0,3}"
    r"[A-ZÁÉÍÓÚÜÑ][\wáéíóúüñ.&'-]{1,}\b"
)
_ALLCAPS_RE = re.compile(r"\b[A-ZÁÉÍÓÚÜÑ][A-ZÁÉÍÓÚÜÑ0-9&.\-]{2,}\b")

# Sufijos societarios: elevan mucho la probabilidad de ser una empresa.
_COMPANY_HINTS = (
    "s.l", "sl", "s.a", "sa", "sau", "slu", "s.l.u", "s.a.u", "srl", "s.r.l",
    "gmbh", "ag", "ltd", "llc", "inc", "corp", "bv", "nv", "spa", "oy", "ab",
    "cia", "cv", "s.a.p.i", "sapi", "sas",
)

RISK_LABELS = {
    "email": "Correo",
    "phone": "Telefono",
    "iban": "Cuenta bancaria",
    "card": "Tarjeta",
    "url": "Web",
    "ip": "IP",
    "id_fiscal": "ID fiscal",
    "serial": "Codigo/Modelo",
    "coord": "Coordenadas",
    "empresa": "Empresa (probable)",
    "nombre": "Nombre propio",
    "marca": "Marca / sigla",
    "encabezado": "Encabezado o pie repetido",
}


@dataclass
class Candidate:
    text: str
    kind: str
    count: int = 0
    pages: set[int] = field(default_factory=set)
    samples: list[str] = field(default_factory=list)
    score: float = 0.0
    suggested: bool = False

    @property
    def kind_label(self) -> str:
        return RISK_LABELS.get(self.kind, self.kind)

    @property
    def pages_str(self) -> str:
        pgs = sorted(self.pages)
        if len(pgs) <= 6:
            return ", ".join(str(p) for p in pgs)
        return ", ".join(str(p) for p in pgs[:6]) + f"... (+{len(pgs) - 6})"


def _page_texts(doc: Document) -> list[tuple[int, str]]:
    out = []
    for page in doc.pages:
        parts = []
        for el in page.elements:
            if isinstance(el, Block):
                parts.append(el.text)
            elif isinstance(el, Table):
                parts.extend(c for row in el.rows for c in row if c)
        out.append((page.number, "\n".join(p for p in parts if p)))
    return out


def _context(text: str, start: int, end: int, width: int = 46) -> str:
    a = max(0, start - width)
    b = min(len(text), end + width)
    frag = text[a:b].replace("\n", " ")
    return ("..." if a > 0 else "") + re.sub(r"\s+", " ", frag).strip() + ("..." if b < len(text) else "")


def _trim_stopwords(phrase: str) -> str:
    """Recorta articulos y preposiciones de los extremos.

    El patron de nombres propios se lleva por delante la primera palabra de la
    frase siguiente ("Talleres Munoz S.L. La"), porque tras el punto tambien va
    en mayuscula. Quitando esos extremos queda la entidad sola.
    """
    tokens = phrase.split()
    while tokens and fold(tokens[0]).strip(".,") in _STOPWORDS:
        tokens.pop(0)
    while tokens and fold(tokens[-1]).strip(".,") in _STOPWORDS:
        tokens.pop()
    return " ".join(tokens)


def _looks_like_company(phrase: str) -> bool:
    tail = fold(phrase).replace(",", " ").split()
    return bool(tail) and tail[-1].strip(".") in _COMPANY_HINTS


def scan(doc: Document, max_candidates: int = 400) -> list[Candidate]:
    """Devuelve candidatos ordenados por probabilidad de ser sensibles."""
    found: dict[tuple[str, str], Candidate] = {}
    pages = _page_texts(doc)
    n_pages = max(len(pages), 1)

    def add(text: str, kind: str, page: int, context: str) -> None:
        text = re.sub(r"\s+", " ", text).strip(" .,;:")
        if not text or len(text) < 3 or len(text) > 90:
            return
        key = (kind, fold(text))
        cand = found.get(key)
        if cand is None:
            cand = Candidate(text=text, kind=kind)
            found[key] = cand
        cand.count += 1
        cand.pages.add(page)
        if len(cand.samples) < 3:
            cand.samples.append(context)

    # --- 1. detectores deterministas -----------------------------------
    for name, (pattern, _desc, validator) in DETECTORS.items():
        rx = re.compile(pattern)
        for page_no, text in pages:
            for m in rx.finditer(text):
                hit = m.group(0)
                if validator is not None and not validator(hit):
                    continue
                add(hit, name, page_no, _context(text, m.start(), m.end()))

    # --- 2. nombres propios y empresas ---------------------------------
    for page_no, text in pages:
        for m in _PROPER_RE.finditer(text):
            phrase = _trim_stopwords(m.group(0).strip())
            if not phrase:
                continue
            words = phrase.split()
            if len(words) > 4:
                continue
            useful = [w for w in words if fold(w).strip(".") not in _STOPWORDS]
            if not useful:
                continue
            # Una sola palabra capitalizada tras un punto suele ser inicio de frase.
            if len(words) == 1:
                before = text[max(0, m.start() - 2):m.start()]
                if m.start() == 0 or before.strip().endswith((".", ":", "\n")) or not before.strip():
                    continue
                if fold(phrase) in _STOPWORDS:
                    continue
            kind = "empresa" if _looks_like_company(phrase) else "nombre"
            add(phrase, kind, page_no, _context(text, m.start(), m.end()))

        for m in _ALLCAPS_RE.finditer(text):
            token = m.group(0)
            if fold(token) in _STOPWORDS or token.isdigit():
                continue
            add(token, "marca", page_no, _context(text, m.start(), m.end()))

    # --- 3. encabezados y pies repetidos --------------------------------
    line_pages: dict[str, set[int]] = defaultdict(set)
    line_text: dict[str, str] = {}
    for page_no, text in pages:
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        for ln in lines[:2] + lines[-2:]:
            if 6 <= len(ln) <= 110:
                k = fold(ln)
                line_pages[k].add(page_no)
                line_text.setdefault(k, ln)
    if n_pages >= 3:
        for k, pgs in line_pages.items():
            if len(pgs) >= max(2, n_pages * 0.5):
                cand = Candidate(text=line_text[k], kind="encabezado",
                                 count=len(pgs), pages=set(pgs),
                                 samples=[line_text[k]])
                found[("encabezado", k)] = cand

    # --- 4. puntuacion ---------------------------------------------------
    hard = {"email", "phone", "iban", "card", "id_fiscal", "coord"}
    for cand in found.values():
        spread = len(cand.pages) / n_pages
        base = {
            "email": 100, "iban": 100, "card": 100, "id_fiscal": 95,
            "coord": 90, "phone": 85, "empresa": 80, "encabezado": 70,
            "serial": 60, "url": 55, "ip": 55, "marca": 45, "nombre": 30,
        }.get(cand.kind, 25)
        cand.score = base + min(20, cand.count * 2) + spread * 15
        cand.suggested = cand.kind in hard or cand.kind == "empresa" or (
            cand.kind == "encabezado" and len(cand.pages) >= 3
        )

    # Los nombres propios de una sola aparicion suelen ser ruido (cualquier
    # palabra tras un punto va en mayuscula), salvo que sean de varias
    # palabras: "Javier Ortega" si interesa aunque aparezca una vez.
    result = [
        c for c in found.values()
        if c.count >= 2
        or c.kind not in ("nombre", "marca")
        or (c.kind == "nombre" and len(c.text.split()) >= 2)
    ]

    # Un mismo texto puede encajar en varios detectores ("P-14" es codigo y
    # tambien nombre propio): se queda con el de mayor puntuacion.
    best: dict[str, Candidate] = {}
    for cand in result:
        key = fold(cand.text)
        current = best.get(key)
        if current is None or cand.score > current.score:
            if current is not None:
                cand.count = max(cand.count, current.count)
                cand.pages |= current.pages
                cand.samples = cand.samples or current.samples
            best[key] = cand
        else:
            current.count = max(current.count, cand.count)
            current.pages |= cand.pages

    result = list(best.values())
    result.sort(key=lambda c: (-c.score, -c.count, c.text.lower()))
    return result[:max_candidates]


def group_by_kind(candidates: list[Candidate]) -> dict[str, list[Candidate]]:
    groups: dict[str, list[Candidate]] = defaultdict(list)
    for c in candidates:
        groups[c.kind].append(c)
    return dict(groups)
