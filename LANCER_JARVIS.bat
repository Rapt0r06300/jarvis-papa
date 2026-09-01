@echo off
setlocal
cd /d "%~dp0"
title Jarvis Papa

if exist "Jarvis.exe" (
    start "" "%~dp0Jarvis.exe"
    exit /b 0
)

if not exist ".venv\Scripts\python.exe" (
    echo Jarvis n'est pas encore installe.
    echo Utilise de preference JarvisPapa-Setup.exe.
    echo Pour le mode developpeur, lance d'abord INSTALLER_JARVIS.bat.
    pause
    exit /b 1
)

if not exist ".env" (
    copy /Y ".env.example" ".env" >nul
)

echo Demarrage de la fenetre native Jarvis...
echo Aucun navigateur ne sera ouvert.
echo.

".venv\Scripts\python.exe" -m jarvis_papa.desktop_app
set "RC=%ERRORLEVEL%"

if not "%RC%"=="0" (
    echo.
    echo Jarvis s'est arrete avec une erreur.
    echo Lance DIAGNOSTIC_JARVIS.bat pour identifier la cause.
    pause
)
exit /b %RC%
