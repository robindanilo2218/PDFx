# Deja el OCR Tesseract portable en tools\tesseract.
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File build\obtener_tesseract.ps1
#
# Aqui no hay logica a proposito. La descarga y la extraccion del OCR viven en
# setup-pdfx-windows.ps1 y solo ahi: este fichero llego a tener su propia copia
# y se quedo atras, con el fallo que dejaba tools\tesseract vacia porque
# intentaba abrir el instalador NSIS ejecutandolo, cosa que exige permisos de
# administrador. Mantener una sola version evita que vuelva a pasar.
$ErrorActionPreference = 'Stop'

$principal = Join-Path $PSScriptRoot 'setup-pdfx-windows.ps1'
if (-not (Test-Path $principal)) {
    Write-Host ''
    Write-Host '  No encuentro setup-pdfx-windows.ps1 al lado de este script.' -ForegroundColor Red
    Write-Host '  Ejecutalo desde la carpeta del proyecto:'
    Write-Host '    powershell -NoProfile -ExecutionPolicy Bypass -File build\obtener_tesseract.ps1'
    Write-Host ''
    exit 1
}

& $principal -SoloTesseract @args
exit $LASTEXITCODE
