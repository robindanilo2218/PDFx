@echo off
rem Lanzador de la instalacion de PDFX para Windows.
rem Haz doble clic en este fichero. No hace falta nada mas.
title Instalador de PDFX
cd /d "%~dp0"
echo.
echo   Preparando PDFX. Esto tarda entre 10 y 25 minutos.
echo   No cierres esta ventana.
echo.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0build\setup-pdfx-windows.ps1" %*
set RC=%ERRORLEVEL%
echo.
if not "%RC%"=="0" (
  echo   Ha fallado. El motivo esta mas arriba.
  echo   Registro completo: build\registro-instalacion.txt
  pause
)
