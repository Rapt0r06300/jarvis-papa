@echo off
setlocal
cd /d "%~dp0"
title Installation Jarvis Papa

echo ==========================================
echo        INSTALLATION DE JARVIS PAPA
echo ==========================================
echo.

where py >nul 2>&1
if errorlevel 1 (
    echo [ERREUR] Python n'est pas installe ou le lanceur py est introuvable.
    echo Installe Python 3.12 ou plus recent puis relance ce fichier.
    pause
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo [1/4] Creation de l'environnement Python...
    py -3.12 -m venv .venv
    if errorlevel 1 goto :error
) else (
    echo [1/4] Environnement Python deja present.
)

echo [2/4] Mise a jour de pip...
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto :error

echo [3/4] Installation de Jarvis et des dependances...
".venv\Scripts\python.exe" -m pip install -e ".[dev]"
if errorlevel 1 goto :error

if not exist ".env" (
    echo [4/4] Creation de la configuration locale...
    copy /Y ".env.example" ".env" >nul
) else (
    echo [4/4] Configuration locale deja presente.
)

echo.
echo ==========================================
echo Installation terminee avec succes.
echo Lance maintenant LANCER_JARVIS.bat
echo ==========================================
pause
exit /b 0

:error
echo.
echo [ERREUR] L'installation n'a pas pu se terminer.
echo Regarde le message ci-dessus pour identifier la cause.
pause
exit /b 1
