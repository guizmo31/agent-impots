@echo off
echo ============================================
echo   AGENT IMPOTS - Demarrage
echo ============================================
echo.

:: Chercher Ollama dans les chemins classiques
set OLLAMA_CMD=ollama
where ollama >nul 2>&1
if errorlevel 1 (
    if exist "%LOCALAPPDATA%\Programs\Ollama\ollama.exe" (
        set OLLAMA_CMD="%LOCALAPPDATA%\Programs\Ollama\ollama.exe"
    ) else if exist "%PROGRAMFILES%\Ollama\ollama.exe" (
        set OLLAMA_CMD="%PROGRAMFILES%\Ollama\ollama.exe"
    ) else if exist "%USERPROFILE%\AppData\Local\Ollama\ollama.exe" (
        set OLLAMA_CMD="%USERPROFILE%\AppData\Local\Ollama\ollama.exe"
    ) else (
        echo [ERREUR] Ollama n'est pas installe ou introuvable.
        echo.
        echo Installez Ollama depuis : https://ollama.com/download/windows
        echo Puis relancez ce script.
        echo.
        echo Si Ollama est deja installe, ajoutez-le au PATH :
        echo   1. Cherchez "Variables d'environnement" dans le menu Demarrer
        echo   2. Ajoutez le dossier contenant ollama.exe dans la variable PATH
        echo.
        start "" "https://ollama.com/download/windows"
        pause
        exit /b 1
    )
)

:: Verifier qu'Ollama tourne, sinon le demarrer
%OLLAMA_CMD% list >nul 2>&1
if errorlevel 1 (
    echo [INFO] Demarrage d'Ollama en arriere-plan...
    start /min "" %OLLAMA_CMD% serve
    echo [INFO] Attente du demarrage d'Ollama...
    timeout /t 5 /nobreak >nul

    :: Re-verifier
    %OLLAMA_CMD% list >nul 2>&1
    if errorlevel 1 (
        echo [ATTENTION] Ollama ne repond pas encore. Nouvelle tentative dans 5s...
        timeout /t 5 /nobreak >nul
    )
)

:: Verifier que le modele Mistral est present
%OLLAMA_CMD% list 2>nul | findstr /i "mistral" >nul 2>&1
if errorlevel 1 (
    echo [ATTENTION] Le modele Mistral n'est pas installe.
    echo [INFO] Lancez d'abord setup.bat pour installer les modeles.
    echo.
    pause
    exit /b 1
)

echo [OK] Ollama en cours d'execution
echo [OK] Modele Mistral detecte
echo.
echo [INFO] Demarrage du serveur web...
echo.
echo ============================================
echo   Ouvrez votre navigateur sur :
echo   http://localhost:8000
echo ============================================
echo.
echo Appuyez sur Ctrl+C pour arreter.
echo.

cd /d %~dp0
python backend\app.py
