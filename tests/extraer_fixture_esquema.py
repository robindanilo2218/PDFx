"""Recorta una sola pagina del manual real del cliente (untracked, no se sube)
para usarla como fixture del test de deteccion de esquemas electricos
(analysis/schematic.py). No se ejecuta como parte de la suite normal: los
41 tests de siempre no dependen del PDF de 452 paginas, que ademas no esta
en git (ver PDFx/AGENTS.md, seccion de datos de cliente).

Uso manual, una sola vez (o si hay que regenerar la fixture):

    .venv-dev/bin/python tests/extraer_fixture_esquema.py

Genera tests/data/esquema_motor.pdf: pagina 18 (indice 17, 0-based) del PDF
original -- circuito de motores -M6.1/-M6.2 con contactores -K6.1..-K6.4,
guardamotores -Q6.1/-Q6.2, bornes -X0.0A/-X0.2/-X8/-X9 y cables 6.10-6.26.
Es la pagina usada para diagnosticar el bug de texto rotado (upright=False)
y para disenar analysis/schematic.py.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pypdfium2 as pdfium

HERE = Path(__file__).parent
SRC = HERE / "data" / "DocC080280_359419DIAGRAMAS.pdf"
DEST = HERE / "data" / "esquema_motor.pdf"
PAGE_INDEX = 17  # pagina 18, 1-indexada


def main() -> int:
    if not SRC.exists():
        print(f"No esta el PDF de origen: {SRC} (es del cliente, no se versiona).")
        return 1

    src = pdfium.PdfDocument(str(SRC))
    dst = pdfium.PdfDocument.new()
    dst.import_pages(src, pages=[PAGE_INDEX])
    dst.save(str(DEST))
    src.close()
    dst.close()

    print(f"{DEST.name}: {DEST.stat().st_size / 1024:.1f} KB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
