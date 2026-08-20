#!/usr/bin/env bash
# Deja el OCR Tesseract portable en tools/tesseract-linux.
#
#   ./build/obtener_tesseract.sh
#
# Aqui no hay logica a proposito. La descarga y la extraccion del OCR viven en
# setup-pdfx-linux.sh y solo ahi: mantener dos copias de lo mismo es como el
# lado de Windows acabo arrastrando un fallo que dejaba la carpeta del OCR
# vacia sin que nadie se diera cuenta.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
exec bash "$DIR/setup-pdfx-linux.sh" --solo-ocr "$@"
