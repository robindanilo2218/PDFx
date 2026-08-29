# Construye la version portable para Windows.
#   powershell -ExecutionPolicy Bypass -File build\construir_windows.ps1
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

$py = if ($env:PYTHON) { $env:PYTHON } else { ".venv\Scripts\python.exe" }
if (-not (Test-Path $py)) {
    Write-Host "No existe $py. Crea el entorno primero:" -ForegroundColor Yellow
    Write-Host "  py -3.12 -m venv .venv"
    Write-Host "  .venv\Scripts\pip install -r requirements-dev.txt"
    exit 1
}

Write-Host "== Limpiando ==" -ForegroundColor Cyan
Remove-Item -Recurse -Force build\build, dist\PDFx -ErrorAction SilentlyContinue

Write-Host "== Empaquetando con PyInstaller ==" -ForegroundColor Cyan
& $py -m PyInstaller build\pdfx.spec --noconfirm --distpath dist --workpath build\build

Write-Host "== Copiando Tesseract portable ==" -ForegroundColor Cyan
if (Test-Path tools\tesseract) {
    New-Item -ItemType Directory -Force -Path dist\PDFx\tools | Out-Null
    Copy-Item -Recurse -Force tools\tesseract dist\PDFx\tools\
} else {
    Write-Host "   (aviso) falta tools\tesseract; ejecuta build\obtener_tesseract.ps1" -ForegroundColor Yellow
}

Copy-Item README.md dist\PDFx\ -ErrorAction SilentlyContinue

# Acceso directo para arrastrar y soltar un PDF sobre el .bat
@'
@echo off
rem Arrastra uno o varios PDF sobre este fichero para convertirlos a .md
setlocal
cd /d "%~dp0"
if "%~1"=="" ( start "" "PDFx.exe" & exit /b )
"PDFx.exe" %* --rapido
pause
'@ | Set-Content -Encoding ASCII dist\PDFx\ARRASTRA_AQUI_PDF_A_MD.bat

$size = "{0:N0} MB" -f ((Get-ChildItem -Recurse dist\PDFx | Measure-Object Length -Sum).Sum / 1MB)
Write-Host ""
Write-Host "Listo: dist\PDFx  ($size)" -ForegroundColor Green
Write-Host "Comprime la carpeta en un ZIP y ya es portable."
