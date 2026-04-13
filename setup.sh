#!/bin/bash
set -e
echo "============================================"
echo "  AGENT IMPOTS - Installation automatique"
echo "============================================"
echo ""

OS="$(uname -s)"
echo "[INFO] Système détecté : $OS"
echo ""

# -----------------------------------------------
# 1. Vérifier Python
# -----------------------------------------------
echo "[1/4] Vérification de Python..."
if command -v python3 &> /dev/null; then
    PYTHON=python3
    PIP=pip3
elif command -v python &> /dev/null; then
    PYTHON=python
    PIP=pip
else
    echo "[ERREUR] Python 3 n'est pas installé."
    if [ "$OS" = "Darwin" ]; then
        echo "  → brew install python3"
        echo "  ou téléchargez depuis https://www.python.org/downloads/"
    else
        echo "  → sudo apt install python3 python3-pip   (Ubuntu/Debian)"
        echo "  → sudo dnf install python3 python3-pip   (Fedora)"
    fi
    exit 1
fi
echo "[OK] $($PYTHON --version)"

# -----------------------------------------------
# 2. Installer les dépendances Python
# -----------------------------------------------
echo ""
echo "[2/4] Installation des dépendances Python..."
cd "$(dirname "$0")"
$PIP install -r requirements.txt
echo "[OK] Dépendances Python installées"

# -----------------------------------------------
# 3. Vérifier / installer Ollama
# -----------------------------------------------
echo ""
echo "[3/4] Vérification d'Ollama..."

OLLAMA_CMD=""

if command -v ollama &> /dev/null; then
    OLLAMA_CMD="ollama"
    echo "[OK] Ollama détecté dans le PATH"
elif [ "$OS" = "Darwin" ] && [ -f "/usr/local/bin/ollama" ]; then
    OLLAMA_CMD="/usr/local/bin/ollama"
    echo "[OK] Ollama détecté dans /usr/local/bin/"
elif [ "$OS" = "Darwin" ] && [ -d "/Applications/Ollama.app" ]; then
    # L'app macOS installe le CLI ici
    if [ -f "/usr/local/bin/ollama" ]; then
        OLLAMA_CMD="/usr/local/bin/ollama"
    else
        echo "[INFO] L'app Ollama est installée mais le CLI n'est pas dans le PATH."
        echo "  → Lancez l'app Ollama une première fois depuis le Launchpad"
        echo "  → Puis relancez ce script"
        exit 1
    fi
fi

if [ -z "$OLLAMA_CMD" ]; then
    echo "[INFO] Ollama n'est pas installé."
    echo ""
    if [ "$OS" = "Darwin" ]; then
        echo "Option 1 (recommandé) : brew install ollama"
        echo "Option 2 : téléchargez depuis https://ollama.com/download/mac"
    else
        echo "Installation : curl -fsSL https://ollama.com/install.sh | sh"
    fi
    echo ""
    echo "Puis relancez ce script."
    exit 1
fi

# Démarrer Ollama si nécessaire
if ! $OLLAMA_CMD list &> /dev/null 2>&1; then
    echo "[INFO] Démarrage d'Ollama en arrière-plan..."
    $OLLAMA_CMD serve &> /dev/null &
    OLLAMA_PID=$!
    echo "[INFO] Attente du démarrage (PID: $OLLAMA_PID)..."
    sleep 5

    # Vérifier que ça a démarré
    if ! $OLLAMA_CMD list &> /dev/null 2>&1; then
        echo "[ATTENTION] Ollama ne répond pas encore, nouvelle tentative..."
        sleep 5
    fi
fi

echo "[OK] Ollama en cours d'exécution"

# -----------------------------------------------
# 4. Télécharger les modèles
# -----------------------------------------------
echo ""
echo "[4/4] Téléchargement des modèles..."
echo ""

echo "  → Mistral-Nemo 12B (~7 Go) — LLM principal (recommandé)"
echo "    Meilleur en français et en génération JSON que Mistral 7B"
echo "    Cela peut prendre 10-20 minutes selon votre connexion..."
if $OLLAMA_CMD pull mistral-nemo; then
    echo "[OK] Modèle Mistral-Nemo 12B installé"
else
    echo "[ATTENTION] Échec — téléchargement de Mistral 7B en secours..."
    $OLLAMA_CMD pull mistral
    echo "[OK] Modèle Mistral 7B installé (secours)"
fi

echo ""
echo "  → Mistral 7B (~4 Go) — modèle de secours"
$OLLAMA_CMD pull mistral 2>/dev/null && echo "[OK] Modèle Mistral 7B installé" || true


# -----------------------------------------------
# Terminé
# -----------------------------------------------
echo ""
echo "============================================"
echo "  Installation terminée avec succès !"
echo "============================================"
echo ""
echo "  Modèles installés :"
echo "    - Mistral-Nemo 12B (LLM principal)"
echo "    - Mistral 7B (modèle de secours)"
echo ""
echo "  Pour lancer l'agent :"
echo "    ./lancer.sh"
echo "    puis ouvrez http://localhost:8000"
echo ""
