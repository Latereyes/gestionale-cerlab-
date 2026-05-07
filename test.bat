@echo off
title Test Gestionale (Modalita' Produzione)

:: Sposta il terminale nella cartella dove risiede questo file .bat
cd /d "%~dp0"

echo.
echo =======================================================
echo   Avvio del GESTIONALE in modalita' di produzione...
echo   (Simula l'esecuzione di Gestionale.exe)
echo =======================================================
echo.

:: Avvia lo script usando il file presente nella cartella corrente
python gestionale.py

echo.
echo Il processo del launcher e' terminato.
echo Se tutto ha funzionato, il server e' ora attivo in background.
pause