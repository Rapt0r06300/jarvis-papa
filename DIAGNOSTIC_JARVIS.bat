@echo off
setlocal
cd /d "%~dp0"
title Diagnostic Jarvis Papa

if not exist ".venv\Scripts\python.exe" (
    echo [ERREUR] Jarvis n'est pas encore installe.
    echo Lance d'abord INSTALLER_JARVIS.bat
    pause
    exit /b 1
)

if not exist ".env" (
    copy /Y ".env.example" ".env" >nul
)

echo ==========================================
echo          DIAGNOSTIC JARVIS PAPA
echo ==========================================
echo.

".venv\Scripts\python.exe" -m jarvis_papa.diagnostics
set "RC=%ERRORLEVEL%"

echo.
if "%RC%"=="0" (
    echo Diagnostic termine : aucun probleme critique detecte.
) else (
    echo Diagnostic termine : une erreur critique doit etre corrigee.
)
echo.
pause
exit /b %RC%
