"""Saneado de informacion sensible."""

import pytest

from pdfx.config import RedactionSettings
from pdfx.redact import DETECTORS, Redactor


def hacer(**kw) -> Redactor:
    base = dict(enabled=True, style="label")
    base.update(kw)
    return Redactor(RedactionSettings(**base))


def test_termino_de_varias_palabras():
    r = hacer(terms=["Talleres Munoz S.L."])
    out = r.scrub("Personal de Talleres Munoz S.L. reviso el equipo.")
    assert "Talleres" not in out
    assert "[CONFIDENCIAL_1]" in out


def test_pseudonimo_estable_entre_variantes():
    r = hacer(terms=["Muñoz Maquinaria"])
    out = r.scrub("MUNOZ MAQUINARIA y luego Muñoz  Maquinaria")
    assert out.count("[CONFIDENCIAL_1]") == 2


def test_punto_final_de_frase_se_conserva():
    r = hacer(terms=["ACME S.A."])
    assert r.scrub("Cliente ACME S.A. Siguiente frase.").endswith("Siguiente frase.")
    assert "[CONFIDENCIAL_1]." in r.scrub("Cliente ACME S.A. Otra.")


def test_detectores_con_validador():
    r = hacer(detectors=["phone", "serial", "card"])
    texto = ("tel 612 345 678, equipo S7-1200, cotas 12,50 30,00 45,75 mm, "
             "fecha 12/05/2024, tarjeta 4539 1488 0343 6467")
    out = r.scrub(texto)
    assert "612 345 678" not in out          # telefono oculto
    assert "S7-1200" not in out              # codigo de maquina oculto
    assert "4539 1488 0343 6467" not in out  # tarjeta valida por Luhn
    assert "12,50 30,00 45,75" in out        # cotas: no son un telefono
    assert "12/05/2024" in out               # fecha: no es un codigo


def test_estilos_de_sustitucion():
    assert "[OCULTO]" in hacer(terms=["ACME"], style="mask").scrub("de ACME")
    assert "[REF:" in hacer(terms=["ACME"], style="hash").scrub("de ACME")
    assert "ACME" not in hacer(terms=["ACME"], style="remove").scrub("de ACME")


def test_verificacion_detecta_fugas():
    r = hacer(terms=["ACME"])
    r.scrub("de ACME")
    assert r.verify("texto limpio") == []
    assert r.verify("todavia aparece acme aqui") == ["ACME"]


@pytest.mark.parametrize("nombre", sorted(DETECTORS))
def test_todos_los_detectores_compilan(nombre):
    hacer(detectors=[nombre]).scrub("prueba 123 a@b.com AB-12 192.168.1.1")
