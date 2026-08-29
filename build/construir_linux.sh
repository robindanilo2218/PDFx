#!/usr/bin/env bash
# Construye la version portable para Linux y la deja en dist/PDFx.
#
#   ./build/construir_linux.sh
#
# Delega en setup-pdfx-linux.sh, que ademas comprueba el equipo, prepara el
# entorno, trae el OCR y verifica que lo compilado funciona de verdad. Antes
# esto era un script aparte que solo empaquetaba y no comprobaba nada.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
exec bash "$DIR/setup-pdfx-linux.sh" "$@"
