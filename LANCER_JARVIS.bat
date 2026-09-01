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
echo Jarvis ouvrira l'interface seulement quand le serveur sera pret.
echo Ferme cette fenetre pour arreter Jarvis.
echo.

start "" powershell.exe -NoProfile -WindowStyle Hidden -Command "$u='http://127.0.0.1:8765'; for($i=0;$i -lt 120;$i++){try{$r=Invoke-WebRequest -UseBasicParsing -Uri ($u+'/health') -TimeoutSec 1;if($r.StatusCode -eq 200){Start-Process $u;exit 0}}catch{};Start-Sleep -Milliseconds 500}"

".venv\Scripts\python.exe" -m jarvis_papa.main
set "RC=%ERRORLEVEL%"

if not "%RC%"=="0" (
    echo.
    echo Jarvis s'est arrete avec une erreur.
    echo Lance DIAGNOSTIC_JARVIS.bat pour identifier la cause.
    pause
)
exit /b %RC%
