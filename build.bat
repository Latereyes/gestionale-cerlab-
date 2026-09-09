@echo off
title Build Gestionale Preventivi

echo.
echo ========================================
echo   AVVIO PROCESSO DI BUILD AUTOMATICO
echo ========================================
echo.

:: Spostati nella cartella dove si trova questo script .bat
:: Questo garantisce che tutti i file vengano trovati correttamente.
cd /d "%~dp0"

:: Attiva l'ambiente virtuale se presente
if exist ".venv\Scripts\activate.bat" (
    call .venv\Scripts\activate.bat
)

:: Chiude eventuali istanze in esecuzione di Gestionale per liberare i file in dist
taskkill /f /im Gestionale.exe 2>nul

:: Esegui lo script Python che fa tutto il lavoro pesante
python build.py

echo.
echo ========================================
echo    PROCESSO DI BUILD TERMINATO
echo ========================================
echo.

:: Metti in pausa per permettere di leggere l'output prima che la finestra si chiuda
pause