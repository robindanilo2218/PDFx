"""Saneado de informacion sensible.

Se aplica sobre el modelo `Document` ya construido, justo antes de escribir la
salida, de modo que afecta por igual a Markdown, Word, Excel, HTML y JSON.

Estilos de sustitucion:
  label   [EMPRESA_1]      pseudonimo estable: el mismo termino siempre recibe
                           la misma etiqueta, asi el documento sigue teniendo
                           sentido para quien (o lo que) lo lea despues.
  mask    [OCULTO]         se pierde la distincion entre terminos.
  hash    [REF:9f2a1c]     identificador corto e irreversible.
  remove  (vacio)          se borra sin dejar rastro.
"""

from __future__ import annotations

import hashlib
import re
from collections import Counter
from dataclasses import dataclass, field

from .config import RedactionSettings
from .model import Block, Document, ImageRef, Table
from .util.text import fold, strip_accents

# --------------------------------------------------------------------------
# detectores predefinidos
# --------------------------------------------------------------------------
def _digits(text: str) -> str:
    return "".join(c for c in text if c.isdigit())


def _valid_phone(text: str) -> bool:
    """Evita confundir un telefono con importes, cotas o referencias."""
    d = _digits(text)
    if not 9 <= len(d) <= 15:
        return False
    # "12,50 30,00 45,75" no es un telefono
    return not re.search(r"\d[,.]\d", text)


def _luhn(text: str) -> bool:
    d = [int(c) for c in _digits(text)]
    if len(d) not in (13, 14, 15, 16, 19):
        return False
    total, parity = 0, len(d) % 2
    for i, n in enumerate(d):
        if i % 2 == parity:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0


def _valid_iban(text: str) -> bool:
    compact = re.sub(r"\s", "", text)
    return 15 <= len(compact) <= 34 and compact[:2].isalpha()


def _valid_serial(text: str) -> bool:
    """Codigo de maquina: mezcla de letras y digitos, no una fecha ni un rango."""
    if not any(c.isdigit() for c in text) or not any(c.isalpha() for c in text):
        return False
    return not re.fullmatch(r"\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4}", text)


def _valid_ip(text: str) -> bool:
    parts = text.split(".")
    return len(parts) == 4 and all(p.isdigit() and int(p) <= 255 for p in parts)


# nombre -> (patron, descripcion, validador opcional)
DETECTORS: dict[str, tuple[str, str, object]] = {
    "email": (
        r"\b[\w.+-]+@[\w-]+\.[\w.-]{2,}\b",
        "Correos electronicos",
        None,
    ),
    "phone": (
        r"(?<![\d-])(?:\+?\d{1,3}[ .\-]?)?(?:\(\d{2,4}\)[ .\-]?)?"
        r"\d{2,4}(?:[ .\-]\d{2,4}){1,4}(?![\d-])",
        "Telefonos",
        _valid_phone,
    ),
    "iban": (
        r"\b[A-Z]{2}\d{2}[ ]?(?:[A-Z0-9]{4}[ ]?){3,7}[A-Z0-9]{1,4}\b",
        "Cuentas bancarias IBAN",
        _valid_iban,
    ),
    "card": (
        r"\b(?:\d{4}[ -]?){3}\d{1,4}\b",
        "Tarjetas de credito",
        _luhn,
    ),
    "url": (
        r"\bhttps?://[^\s<>\"')]+|\bwww\.[^\s<>\"')]+",
        "Direcciones web",
        None,
    ),
    "ip": (
        r"\b(?:\d{1,3}\.){3}\d{1,3}\b",
        "Direcciones IP",
        _valid_ip,
    ),
    "id_fiscal": (
        # NIF/NIE/CIF (ES), RFC y CURP (MX)
        r"\b(?:[0-9]{8}[A-Za-z]|[XYZxyz][0-9]{7}[A-Za-z]|[A-Za-z][0-9]{7}[A-Za-z0-9]"
        r"|[A-Za-z]{3,4}\d{6}[A-Za-z0-9]{2,3})\b",
        "Identificadores fiscales (NIF/CIF/RFC/CURP)",
        None,
    ),
    "serial": (
        # Codigos de maquina / modelo: SIE-4520B, S7-1200, MOD.884521
        # El lookahead debe poder cruzar los separadores: en "SIE-4520B" el
        # digito esta despues del guion.
        r"\b(?=[A-Za-z0-9./-]*\d)[A-Z][A-Za-z0-9]*(?:[-/.][A-Za-z0-9]+){1,4}\b",
        "Codigos de maquina, modelo o serie",
        _valid_serial,
    ),
    "coord": (
        r"\b-?\d{1,3}\.\d{4,}\s*,\s*-?\d{1,3}\.\d{4,}\b",
        "Coordenadas geograficas",
        None,
    ),
}


@dataclass
class RedactionReport:
    counts: Counter = field(default_factory=Counter)      # termino -> veces
    labels: dict[str, str] = field(default_factory=dict)  # termino -> etiqueta
    kinds: dict[str, str] = field(default_factory=dict)   # termino -> detector
    leaked: list[str] = field(default_factory=list)       # sobrevivio a la verificacion

    @property
    def total(self) -> int:
        return sum(self.counts.values())

    def render(self) -> str:
        lines = [
            "INFORME DE SANEADO",
            "=" * 60,
            f"Sustituciones totales: {self.total}",
            "",
        ]
        if self.counts:
            lines.append(f"{'ORIGINAL':<34} {'REEMPLAZO':<22} VECES")
            lines.append("-" * 66)
            for term, n in self.counts.most_common():
                shown = term if len(term) <= 32 else term[:29] + "..."
                lines.append(f"{shown:<34} {self.labels.get(term, ''):<22} {n}")
        else:
            lines.append("No se encontro ninguna coincidencia.")
        if self.leaked:
            lines += [
                "",
                "!! AVISO: estos terminos siguen apareciendo en la salida:",
                *(f"   - {t}" for t in self.leaked),
            ]
        else:
            lines += ["", "Verificacion: ningun termino marcado quedo en la salida."]
        return "\n".join(lines)


# --------------------------------------------------------------------------
# motor
# --------------------------------------------------------------------------
class Redactor:
    """Compila las reglas una vez y las aplica a todo el documento."""

    def __init__(self, settings: RedactionSettings):
        self.s = settings
        self.report = RedactionReport()
        self._counter = 0
        # (patron, tipo, validador)
        self._rules: list[tuple[re.Pattern, str, object]] = []
        self._alias: dict[str, str] = {}     # clave canonica -> token
        self._surface: dict[str, str] = {}   # clave canonica -> primera forma vista
        self._build()

    # -- construccion de reglas ------------------------------------------
    def _build(self) -> None:
        flags = re.IGNORECASE if self.s.fuzzy else 0

        for term in self.s.terms:
            term = term.strip()
            if not term:
                continue
            if self.s.fuzzy:
                body = self._accent_insensitive(term)
                # cualquier espacio del termino casa con uno o varios reales
                body = re.sub(r"(?:\\ )+", r"\\s+", body)
            else:
                body = re.escape(term)
            # El limite de palabra solo tiene sentido si el borde es alfanumerico:
            # "ACME S.A." termina en punto y un \b final impediria la coincidencia.
            left = r"\b" if self.s.whole_word and term[0].isalnum() else ""
            right = r"\b" if self.s.whole_word and term[-1].isalnum() else ""
            try:
                self._rules.append((re.compile(left + body + right, flags), "termino", None))
            except re.error:
                self._rules.append((re.compile(re.escape(term), flags), "termino", None))

        for name in self.s.detectors:
            spec = DETECTORS.get(name)
            if not spec:
                continue
            pattern, _desc, validator = spec
            self._rules.append((re.compile(pattern), name, validator))

        for raw in self.s.patterns:
            raw = raw.strip()
            if not raw:
                continue
            try:
                self._rules.append((re.compile(raw, flags), "regex", None))
            except re.error:
                continue

    @staticmethod
    def _accent_insensitive(term: str) -> str:
        """a -> [aaaaa], para que 'Munoz' encuentre tambien 'Munoz' con enye."""
        groups = {
            "a": "a\u00e1\u00e0\u00e4\u00e2\u00e3", "e": "e\u00e9\u00e8\u00eb\u00ea",
            "i": "i\u00ed\u00ec\u00ef\u00ee", "o": "o\u00f3\u00f2\u00f6\u00f4\u00f5",
            "u": "u\u00fa\u00f9\u00fc\u00fb", "n": "n\u00f1", "c": "c\u00e7",
        }
        out = []
        for ch in term:
            base = strip_accents(ch).lower()
            if ch.isalpha() and base in groups:
                chars = groups[base]
                out.append(f"[{chars}{chars.upper()}]")
            elif ch.isspace():
                out.append("\\ ")
            else:
                out.append(re.escape(ch))
        return "".join(out)

    # -- sustitucion ------------------------------------------------------
    def _canon(self, text: str) -> str:
        """Clave estable: la misma entidad recibe siempre el mismo pseudonimo,
        escriba el documento MUNOZ, Munoz o Mu\u00f1oz."""
        collapsed = re.sub(r"\s+", " ", text).strip()
        return fold(collapsed) if self.s.fuzzy else collapsed

    def _replacement(self, matched: str, kind: str) -> str:
        surface = re.sub(r"\s+", " ", matched).strip()
        canon = self._canon(surface)
        display = self._surface.setdefault(canon, surface)

        self.report.counts[display] += 1
        self.report.kinds.setdefault(display, kind)

        if canon in self._alias:
            return self._alias[canon]

        style = self.s.style
        if style == "remove":
            token = ""
        elif style == "mask":
            token = "[OCULTO]"
        elif style == "hash":
            digest = hashlib.sha256(canon.encode("utf-8")).hexdigest()[:6].upper()
            token = f"[REF:{digest}]"
        else:  # label
            self._counter += 1
            base = self.s.label_prefix if kind in ("termino", "regex") else kind.upper()
            token = f"[{base}_{self._counter}]"

        self._alias[canon] = token
        self.report.labels[display] = token
        return token

    def scrub(self, text: str) -> str:
        if not text or not self._rules:
            return text
        out = text
        for pattern, kind, validator in self._rules:
            def _sub(m, kind=kind, validator=validator):
                hit = m.group(0)
                if validator is not None and not validator(hit):
                    return hit          # falso positivo: se deja intacto
                token = self._replacement(hit, kind)
                # "Talleres Munoz S.L." incluye el punto: sin esto la frase
                # siguiente se quedaria pegada sin punto final.
                if token and hit.endswith(".") and not token.endswith("."):
                    token += "."
                return token
            out = pattern.sub(_sub, out)
        return out

    # -- aplicacion al documento -----------------------------------------
    def apply(self, doc: Document) -> RedactionReport:
        if not self._rules and not self.s.drop_images:
            return self.report

        if self.s.scrub_metadata:
            doc.title = self.scrub(doc.title)
            doc.author = self.scrub(doc.author)
            doc.subject = self.scrub(doc.subject)

        for page in doc.pages:
            kept = []
            for el in page.elements:
                if isinstance(el, Block):
                    # Sobre el texto completo del bloque, no palabra a palabra:
                    # de lo contrario ningun termino de varias palabras (ni un
                    # telefono con espacios) llegaria a coincidir.
                    el.text_override = self.scrub(el.text)
                    kept.append(el)
                elif isinstance(el, Table):
                    el.rows = [[self.scrub(c) for c in row] for row in el.rows]
                    kept.append(el)
                elif isinstance(el, ImageRef):
                    if self.s.drop_images:
                        continue          # la imagen no llega a la salida
                    el.caption = self.scrub(el.caption)
                    kept.append(el)
                else:
                    kept.append(el)
            page.elements = kept
        return self.report

    # -- verificacion -----------------------------------------------------
    def verify(self, text: str) -> list[str]:
        """Relee la salida y devuelve los terminos literales que sobrevivieron."""
        leaked = []
        haystack = strip_accents(text).lower() if self.s.fuzzy else text
        for term in self.s.terms:
            term = term.strip()
            if not term:
                continue
            needle = strip_accents(term).lower() if self.s.fuzzy else term
            if needle and needle in haystack:
                leaked.append(term)
        self.report.leaked = leaked
        return leaked


def build_redactor(settings: RedactionSettings) -> Redactor | None:
    if not settings.enabled:
        return None
    if not (settings.terms or settings.patterns or settings.detectors
            or settings.drop_images):
        return None
    return Redactor(settings)
