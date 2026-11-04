@echo off
setlocal EnableExtensions
chcp 65001 >nul
title StockPilot
cd /d "%~dp0"
rem Executa o programa direto do codigo-fonte (sem gerar instalador). Precisa de Python 3.11+ e internet na 1a vez.
set PY=
where py >nul 2>nul && set PY=py -3
if "%PY%"=="" ( where python >nul 2>nul && set PY=python )
if "%PY%"=="" ( echo Python nao encontrado. Instale o Python 3.12 em https://www.python.org/downloads/ ^(marque "Add to PATH"^). & pause & exit /b 1 )
if not exist .venv\Scripts\python.exe (
  echo Preparando o programa pela primeira vez, aguarde alguns minutos...
  %PY% -m venv .venv || ( pause & exit /b 1 )
  .venv\Scripts\python -m pip install --upgrade pip >nul
  .venv\Scripts\python -m pip install -r requirements.txt || ( pause & exit /b 1 )
)
start "" .venv\Scripts\pythonw run_stockpilot.py
endlocal
