@echo off
cd /d "%~dp0"
title Revisor
cls
echo ==================================================
echo    REVISOR  -  acabamento da redacao
echo ==================================================
echo.
python revisor.py --colar
echo.
pause
