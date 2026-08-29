#!/usr/bin/env sh
# Lanzador de la instalacion de PDFx para Linux.
# Ejecutalo y no hace falta nada mas:
#   ./INSTALAR_PDFx.sh          (o bien:  bash INSTALAR_PDFx.sh)
#
# Es el gemelo de INSTALAR_PDFx.bat. No tiene logica: solo llama al script
# real, que esta en build/setup-pdfx-linux.sh.
cd "$(dirname "$0")" || exit 1
echo ""
echo "  Preparando PDFx. Esto tarda entre 10 y 25 minutos."
echo "  No cierres esta ventana."
echo ""
exec bash build/setup-pdfx-linux.sh "$@"
