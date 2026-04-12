#!/bin/bash
echo "============================================"
echo "  AGENT IMPOTS - Démarrage"
echo "============================================"
echo ""

OS="$(uname -s)"

# Trouver Python
if command -v python3 &> /dev/null; then
    PYTHON=python3
elif command -v python &> /dev/null; then
    PYTHON=python
else
    echo "[ERREUR] Python 3 non trouvé. Lancez d'abord setup.sh"
    exit 1
fi

# Trouver Ollama
OLLAMA_CMD=""
if command -v ollama &> /dev/null; then
    OLLAMA_CMD="ollama"
elif [ -f "/usr/local/bin/ollama" ]; then
    OLLAMA_CMD="/usr/local/bin/ollama"
fi

if [ -z "$OLLAMA_CMD" ]; then
    echo "[ERREUR] Ollama non trouvé. Lancez d'abord setup.sh"
    exit 1
fi

# Démarrer Ollama si nécessaire
if ! $OLLAMA_CMD list &> /dev/null 2>&1; then
    echo "[INFO] Démarrage d'Ollama en arrière-plan..."
    $OLLAMA_CMD serve &> /dev/null &
    sleep 5

    if ! $OLLAMA_CMD list &> /dev/null 2>&1; then
        echo "[ATTENTION] Ollama ne répond pas encore, nouvelle tentative..."
        sleep 5
    fi
fi

# Vérifier le modèle
if ! $OLLAMA_CMD list 2>/dev/null | grep -qi "mistral"; then
    echo "[ERREUR] Le modèle Mistral n'est pas installé."
    echo "  Lancez d'abord : ./setup.sh"
    exit 1
fi

echo "[OK] Ollama en cours d'exécution"
echo "[OK] Modèle Mistral détecté"
echo ""
echo "============================================"
echo "  Ouvrez votre navigateur sur :"
echo "  http://localhost:8000"
echo "============================================"
echo ""
echo "Appuyez sur Ctrl+C pour arrêter."
echo ""

cd "$(dirname "$0")"
$PYTHON backend/app.py
