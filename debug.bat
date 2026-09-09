@echo off
cd /d "%~dp0"
echo Avvio del GESTIONALE in modalita' DEBUG...

if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" gestionale.py --debug
) else (
    py -3.13 gestionale.py --debug 2>nul || python gestionale.py --debug
)
pause