#!/usr/bin/env sh
# Lanzador de la instalacion de PDFX para Linux.
# Ejecutalo y no hace falta nada mas:
#   ./INSTALAR_PDFX.sh          (o bien:  bash INSTALAR_PDFX.sh)
#
# Es el gemelo de INSTALAR_PDFX.bat. No tiene logica: solo llama al script
# real, que esta en build/setup-pdfx-linux.sh.
cd "$(dirname "$0")" || exit 1
echo ""
echo "  Preparando PDFX. Esto tarda entre 10 y 25 minutos."
echo "  No cierres esta ventana."
echo ""
exec bash build/setup-pdfx-linux.sh "$@"
