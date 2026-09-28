@echo off
REM ============================================================
REM  Daniele Job Radar - one-click launcher for Windows
REM  Double-click this file to install (first time only) and
REM  start the dashboard. It opens automatically in your browser.
REM ============================================================

setlocal
cd /d "%~dp0"
title Daniele Job Radar

echo ============================================================
echo   Daniele Job Radar - avvio in corso...
echo ============================================================
echo.

set "PYTHON_CMD="
where py >nul 2>nul
if %ERRORLEVEL% == 0 (
    set "PYTHON_CMD=py"
) else (
    where python >nul 2>nul
    if %ERRORLEVEL% == 0 set "PYTHON_CMD=python"
)

if "%PYTHON_CMD%"=="" (
    echo [ERRORE] Python non e' stato trovato su questo computer.
    echo.
    echo   1. Vai su https://www.python.org/downloads/
    echo   2. Scarica e avvia l'installer per Windows
    echo   3. IMPORTANTE: spunta "Add python.exe to PATH" prima di Install
    echo   4. Richiudi questa finestra e fai doppio clic di nuovo su
    echo      start_job_radar.bat
    echo.
    pause
    exit /b 1
)

echo Trovato Python: %PYTHON_CMD%
echo.

if not exist ".venv\Scripts\python.exe" (
    echo Prima esecuzione: creo un ambiente Python isolato in .venv ...
    %PYTHON_CMD% -m venv .venv
    if not exist ".venv\Scripts\python.exe" (
        echo [ERRORE] Non sono riuscito a creare l'ambiente virtuale .venv
        pause
        exit /b 1
    )
)

set "VENV_PY=.venv\Scripts\python.exe"

echo Controllo e installazione delle librerie necessarie...
echo (la prima volta puo' richiedere 1-2 minuti, poi sara' istantaneo)
"%VENV_PY%" -m pip install --quiet --disable-pip-version-check --upgrade pip
"%VENV_PY%" -m pip install --quiet --disable-pip-version-check -r requirements.txt
if errorlevel 1 (
    echo [ERRORE] Installazione delle librerie non riuscita. Controlla la connessione internet.
    pause
    exit /b 1
)

echo.
echo ============================================================
echo   Avvio della dashboard... si aprira' nel browser a breve.
echo   Per chiudere: torna qui e premi CTRL+C, poi chiudi la finestra.
echo ============================================================
echo.

"%VENV_PY%" -m streamlit run app.py --server.headless false

pause
