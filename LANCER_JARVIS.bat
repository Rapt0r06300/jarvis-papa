@echo off
setlocal
cd /d "%~dp0"
title Jarvis Papa

if not exist ".venv\Scripts\python.exe" (
    echo Jarvis n'est pas encore installe.
    echo Lance d'abord INSTALLER_JARVIS.bat
    pause
    exit /b 1
)

if not exist ".env" (
    copy /Y ".env.example" ".env" >nul
)

echo Demarrage de Jarvis Papa...
echo Interface locale : http://127.0.0.1:8765
echo Ferme cette fenetre pour arreter Jarvis.
echo.

start "" "http://127.0.0.1:8765"
".venv\Scripts\python.exe" -m jarvis_papa.main

if errorlevel 1 (
    echo.
    echo Jarvis s'est arrete avec une erreur.
    pause
)
