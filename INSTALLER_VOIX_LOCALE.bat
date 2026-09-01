@echo off
setlocal
cd /d "%~dp0"
title Installation voix locale Jarvis

echo ==========================================
echo       VOIX LOCALE DE JARVIS - QWEN3-TTS
echo ==========================================
echo.
echo Cette installation est optionnelle.
echo Elle permet a Jarvis de continuer a parler sans Internet.
echo Le premier telechargement du modele peut etre volumineux.
echo.

where py >nul 2>&1
if errorlevel 1 (
    echo [ERREUR] Python 3.12 est necessaire.
    pause
    exit /b 1
)

if not exist ".venv-qwen-tts\Scripts\python.exe" (
    echo [1/4] Creation de l'environnement vocal isole...
    py -3.12 -m venv .venv-qwen-tts
    if errorlevel 1 goto :error
) else (
    echo [1/4] Environnement vocal deja present.
)

echo [2/4] Mise a jour de pip...
".venv-qwen-tts\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto :error

echo [3/4] Installation de Qwen3-TTS...
".venv-qwen-tts\Scripts\python.exe" -m pip install -U qwen-tts soundfile
if errorlevel 1 goto :error

echo [4/4] Verification...
".venv-qwen-tts\Scripts\python.exe" -c "import qwen_tts, soundfile, torch; print('Qwen3-TTS OK - CUDA disponible:', torch.cuda.is_available())"
if errorlevel 1 goto :error

echo.
echo ==========================================
echo Voix locale installee.
echo Le modele sera telecharge automatiquement
 echo lors de la premiere utilisation de Qwen3-TTS.
echo ==========================================
pause
exit /b 0

:error
echo.
echo [ERREUR] La voix locale n'a pas pu etre installee.
echo Jarvis pourra toujours utiliser ElevenLabs, Azure
 echo ou sa voix Windows de secours si disponibles.
pause
exit /b 1
