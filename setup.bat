@echo off
echo ============================================
echo   AGENT IMPOTS - Installation automatique
echo ============================================
echo.

:: Verifier Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERREUR] Python n'est pas installe. Installez Python 3.10+ depuis python.org
    pause
    exit /b 1
)
echo [OK] Python detecte

:: Installer les dependances Python
echo.
echo [1/4] Installation des dependances Python...
cd /d %~dp0
pip install -r requirements.txt
if errorlevel 1 (
    echo [ERREUR] Echec de l'installation des dependances Python
    pause
    exit /b 1
)
echo [OK] Dependances Python installees

:: Chercher Ollama
echo.
echo [2/4] Verification d'Ollama...
set OLLAMA_CMD=ollama
where ollama >nul 2>&1
if errorlevel 1 (
    if exist "%LOCALAPPDATA%\Programs\Ollama\ollama.exe" (
        set OLLAMA_CMD="%LOCALAPPDATA%\Programs\Ollama\ollama.exe"
        echo [OK] Ollama trouve dans %LOCALAPPDATA%\Programs\Ollama
    ) else if exist "%PROGRAMFILES%\Ollama\ollama.exe" (
        set OLLAMA_CMD="%PROGRAMFILES%\Ollama\ollama.exe"
        echo [OK] Ollama trouve dans %PROGRAMFILES%\Ollama
    ) else if exist "%USERPROFILE%\AppData\Local\Ollama\ollama.exe" (
        set OLLAMA_CMD="%USERPROFILE%\AppData\Local\Ollama\ollama.exe"
        echo [OK] Ollama trouve dans %USERPROFILE%\AppData\Local\Ollama
    ) else (
        echo [INFO] Ollama n'est pas installe.
        echo.
        echo Veuillez installer Ollama depuis : https://ollama.com/download/windows
        echo Puis RELANCEZ ce script.
        echo.
        start "" "https://ollama.com/download/windows"
        pause
        exit /b 1
    )
) else (
    echo [OK] Ollama detecte dans le PATH
)

:: S'assurer qu'Ollama tourne
%OLLAMA_CMD% list >nul 2>&1
if errorlevel 1 (
    echo [INFO] Demarrage d'Ollama...
    start /min "" %OLLAMA_CMD% serve
    timeout /t 5 /nobreak >nul
)

:: Telecharger le modele LLM principal
echo.
echo [3/5] Telechargement de Mistral-Nemo 12B (environ 7 Go)...
echo C'est le modele recommande : meilleur en francais et en generation JSON.
echo Cela peut prendre 10-20 minutes selon votre connexion...
%OLLAMA_CMD% pull mistral-nemo
if errorlevel 1 (
    echo [ATTENTION] Echec du telechargement de Mistral-Nemo.
    echo Telechargement du modele de secours Mistral 7B...
    %OLLAMA_CMD% pull mistral
    if errorlevel 1 (
        echo [ERREUR] Echec du telechargement du modele.
        pause
        exit /b 1
    )
    echo [OK] Modele Mistral 7B installe (modele de secours)
) else (
    echo [OK] Modele Mistral-Nemo 12B installe
)

:: Telecharger aussi Mistral 7B comme fallback
echo.
echo [4/5] Telechargement de Mistral 7B en secours (environ 4 Go)...
%OLLAMA_CMD% pull mistral
if errorlevel 1 (
    echo [INFO] Mistral 7B non telecharge, ce n'est pas grave si Nemo est installe.
) else (
    echo [OK] Modele Mistral 7B installe
)

:: Telecharger le modele d'embeddings pour le RAG
echo.
echo [5/5] Telechargement du modele d'embeddings nomic-embed-text (environ 270 Mo)...
echo Ce modele permet la recherche semantique dans les connaissances fiscales...
%OLLAMA_CMD% pull nomic-embed-text
if errorlevel 1 (
    echo [ATTENTION] Echec du telechargement du modele d'embeddings
    echo L'application fonctionnera quand meme en mode TF-IDF (mots-cles)
    echo Vous pourrez relancer : %OLLAMA_CMD% pull nomic-embed-text
) else (
    echo [OK] Modele d'embeddings installe
)

echo.
echo ============================================
echo   Installation terminee avec succes !
echo ============================================
echo.
echo Modeles installes :
echo   - Mistral 7B (LLM principal, ~4 Go)
echo   - nomic-embed-text (embeddings RAG, ~270 Mo)
echo.
echo Pour lancer l'application :
echo   Double-cliquez sur lancer.bat
echo   Puis ouvrez http://localhost:8000
echo.
pause
