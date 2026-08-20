"""Utilidades de texto y deteccion de listas / titulos."""

from pdfx.util.text import (
    clean, dehyphenate, fold, heading_number, is_probably_caption,
    list_marker, looks_like_garbage, slugify, token_estimate,
)


def test_clean_normaliza_ligaduras_y_comillas():
    assert clean("eﬁcaz  “texto”  –  ") == 'eficaz "texto" -'


def test_fold_ignora_acentos_y_mayusculas():
    assert fold("  Muñoz   MAQUINARIA ") == "munoz maquinaria"


def test_dehyphenate_une_palabra_partida():
    assert dehyphenate("inge-", "nieria") == "ingenieria"
    assert dehyphenate("linea", "nueva") is None
    # No se unen nombres propios: podria ser un guion real.
    assert dehyphenate("Talleres-", "Munoz") is None


def test_list_marker_reconoce_vinetas_y_numeracion():
    assert list_marker("- primer punto") == ("-", False)
    assert list_marker("1. primer punto") == ("1.", True)
    assert list_marker("Texto normal de un parrafo") is None
    # 1994 es un ano, no el numero de un item
    assert list_marker("1994. El ano en que todo cambio") is None


def test_list_marker_detecta_vineta_en_fuente_de_simbolos():
    assert list_marker("l Vibracion anomala", "l", "ZapfDingbats") == ("l", False)
    assert list_marker("l Vibracion anomala", "l", "Helvetica") is None


def test_heading_number():
    assert heading_number("2.3.1 Alcance") == "2.3.1"
    assert heading_number("Alcance general") is None


def test_caption():
    assert is_probably_caption("Figura 1. Esquema del grupo")
    assert not is_probably_caption("El equipo queda operativo")


def test_garbage_detecta_capa_de_texto_corrupta():
    assert looks_like_garbage(" " * 20)
    assert not looks_like_garbage("Un parrafo normal de texto tecnico en espanol.")


def test_slugify_y_tokens():
    assert slugify("Informe de Mantenimiento Preventivo") == "informe-de-mantenimiento-preventivo"
    assert token_estimate("a" * 400) == 100
