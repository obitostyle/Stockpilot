@echo off
setlocal EnableExtensions
chcp 65001 >nul
title Gerar instalador do StockPilot
cd /d "%~dp0"

echo ============================================================
echo   StockPilot - gerar o instalador para Windows
echo ============================================================
echo.

rem --- 1. Python 3.11+ ---
set PY=
where py >nul 2>nul && set PY=py -3
if "%PY%"=="" ( where python >nul 2>nul && set PY=python )
if "%PY%"=="" (
  echo [ERRO] Python nao encontrado. Instale o Python 3.12 64 bits em https://www.python.org/downloads/
  echo        Marque a opcao "Add python.exe to PATH" na instalacao e rode este arquivo de novo.
  goto :fim
)
%PY% -c "import sys; sys.exit(0 if sys.version_info[:2] >= (3,11) else 1)"
if errorlevel 1 ( echo [ERRO] E preciso Python 3.11 ou mais novo. & goto :fim )

rem --- 2. ambiente virtual e dependencias ---
if not exist .venv\Scripts\python.exe (
  echo [1/5] Criando ambiente virtual...
  %PY% -m venv .venv || goto :erro
)
echo [2/5] Instalando dependencias (precisa de internet so nesta etapa)...
.venv\Scripts\python -m pip install --upgrade pip >nul
.venv\Scripts\python -m pip install -r requirements-dev.txt || goto :erro

rem --- 3. testes automaticos ---
echo [3/5] Rodando os testes automaticos...
set QT_QPA_PLATFORM=offscreen
.venv\Scripts\python -m pytest -q -x || ( echo [ERRO] Testes falharam. O instalador NAO foi gerado. & goto :fim )

rem --- 4. executavel ---
echo [4/5] Gerando o programa (PyInstaller)...
.venv\Scripts\python -m PyInstaller stockpilot.spec --noconfirm --clean || goto :erro
echo      Autoteste do executavel...
del "%TEMP%\stockpilot-selftest.txt" >nul 2>nul
start "" /wait dist\StockPilot\StockPilot.exe --selftest
if errorlevel 1 ( echo [ERRO] O executavel nao passou no autoteste: & type "%TEMP%\stockpilot-selftest.txt" & goto :fim )
type "%TEMP%\stockpilot-selftest.txt"

rem --- 5. instalador (Inno Setup) ---
set VER=
for /f "delims=" %%v in ('set "PYTHONPATH=src" ^& .venv\Scripts\python -c "from stockpilot import __version__; print(__version__)"') do set VER=%%v
if "%VER%"=="" set VER=0.7.0
set ISCC=
if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe
if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe
if exist "%ProgramFiles(x86)%\Inno Setup 7\ISCC.exe" set ISCC=%ProgramFiles(x86)%\Inno Setup 7\ISCC.exe
if exist "%ProgramFiles%\Inno Setup 7\ISCC.exe" set ISCC=%ProgramFiles%\Inno Setup 7\ISCC.exe
if exist "%LocalAppData%\Programs\Inno Setup 7\ISCC.exe" set ISCC=%LocalAppData%\Programs\Inno Setup 7\ISCC.exe
if exist "%LocalAppData%\Programs\Inno Setup 6\ISCC.exe" set ISCC=%LocalAppData%\Programs\Inno Setup 6\ISCC.exe
if "%ISCC%"=="" (
  echo.
  echo [AVISO] Inno Setup 6 ou 7 nao encontrado. O programa ja funciona em: dist\StockPilot\StockPilot.exe
  echo         Para gerar o instalador unico, instale o Inno Setup 6 ^(gratis^): https://jrsoftware.org/isdl.php
  echo         e rode este arquivo novamente.
  goto :fim
)
echo [5/5] Gerando o instalador...
"%ISCC%" /DAppVersion=%VER% installer\stockpilot.iss || goto :erro
echo.
echo ============================================================
echo   PRONTO!  Instalador em:  dist_installer\StockPilot-Setup-%VER%.exe
echo ============================================================
goto :fim

:erro
echo.
echo [ERRO] Algo falhou. Veja as mensagens acima.
:fim
echo.
pause
endlocal
