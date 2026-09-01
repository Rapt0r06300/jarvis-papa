@echo off
setlocal
title Installation IA locale Jarvis

echo ==========================================
echo       IA LOCALE DE JARVIS PAPA
echo ==========================================
echo.

where ollama >nul 2>&1
if errorlevel 1 (
    echo [ERREUR] Ollama n'est pas installe.
    echo Installe Ollama depuis son site officiel puis relance ce fichier.
    pause
    exit /b 1
)

echo Telechargement ou mise a jour de qwen3:4b...
ollama pull qwen3:4b
if errorlevel 1 (
    echo [ERREUR] Le modele n'a pas pu etre installe.
    pause
    exit /b 1
)

echo.
echo [OK] L'IA locale de Jarvis est prete.
echo Aucune cle cloud n'est necessaire.
pause
