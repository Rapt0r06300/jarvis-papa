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
    echo [1/8] Creation de l'environnement Python...
    py -3.12 -m venv .venv
    if errorlevel 1 goto :error
) else (
    echo [1/8] Environnement Python deja present.
)

echo [2/8] Mise a jour de pip...
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto :error

echo [3/8] Installation de Jarvis et des dependances...
".venv\Scripts\python.exe" -m pip install -e ".[dev]"
if errorlevel 1 goto :error

if not exist ".env" (
    echo [4/8] Creation de la configuration locale...
    copy /Y ".env.example" ".env" >nul
) else (
    echo [4/8] Configuration locale deja presente.
)

echo [5/8] Installation de Chromium pour Playwright...
".venv\Scripts\python.exe" -m playwright install chromium
if errorlevel 1 (
    echo [AVERTISSEMENT] Chromium Playwright n'a pas pu etre installe.
)

echo [6/8] Preparation du pont Thunderbird...
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\INSTALLER_PONT_THUNDERBIRD.ps1"
if errorlevel 1 (
    echo [AVERTISSEMENT] Jarvis est installe, mais le pont Thunderbird n'a pas pu etre prepare.
    echo Tu pourras relancer scripts\INSTALLER_PONT_THUNDERBIRD.ps1 plus tard.
)

echo [7/8] Verification du moteur IA local...
where ollama >nul 2>&1
if errorlevel 1 (
    echo [INFO] Ollama n'est pas encore installe. Jarvis fonctionnera avec ses modes de secours.
    echo Pour activer l'IA locale, installe Ollama puis lance INSTALLER_IA_LOCALE.bat.
) else (
    echo [OK] Ollama est installe.
    ollama list | findstr /I "qwen3:4b" >nul 2>&1
    if errorlevel 1 (
        echo [INFO] Le modele qwen3:4b n'est pas encore telecharge.
        echo Lance INSTALLER_IA_LOCALE.bat pour l'installer.
    ) else (
        echo [OK] Le modele IA qwen3:4b est disponible.
    )
)

echo [8/8] Autodiagnostic initial de Jarvis...
".venv\Scripts\python.exe" -m jarvis_papa.diagnostics
if errorlevel 2 (
    echo [ERREUR] Le diagnostic a detecte un probleme critique.
    echo Lance DIAGNOSTIC_JARVIS.bat apres correction.
    goto :error
)

echo.
echo ==========================================
echo Installation terminee avec succes.
echo Lance maintenant LANCER_JARVIS.bat
echo En cas de probleme : DIAGNOSTIC_JARVIS.bat
echo ==========================================
pause
exit /b 0

:error
echo.
echo [ERREUR] L'installation n'a pas pu se terminer correctement.
echo Regarde le message ci-dessus pour identifier la cause.
echo Tu peux aussi lancer DIAGNOSTIC_JARVIS.bat.
pause
exit /b 1
