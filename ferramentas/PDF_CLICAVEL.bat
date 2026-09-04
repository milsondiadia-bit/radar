@echo off
cd /d "%~dp0"
title PDF Clicavel
cls
echo ==================================================
echo    PDF CLICAVEL  -  faz o Ctrl+F funcionar
echo ==================================================
echo.
if "%~1"=="" (
  echo    Arraste um PDF em cima deste arquivo,
  echo    ou cole o link abaixo.
  echo.
  python pdf_clicavel.py
) else (
  python pdf_clicavel.py "%~1"
)
