@echo off
cd /d "%~dp0"
title Producao
cls
echo ==================================================
echo    PRODUCAO  -  do link ao roteiro pronto
echo ==================================================
echo.
python producao.py %*
