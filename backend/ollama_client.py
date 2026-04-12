"""
Client pour communiquer avec Ollama en local.
Aucune donnée n'est envoyée sur le cloud.

Détection automatique du meilleur modèle disponible :
  1. mistral-nemo (12B, 128K contexte, excellent français/JSON)
  2. mistral (7B, fallback)
"""
import httpx

OLLAMA_URL = "http://localhost:11434"

# Modèles par ordre de préférence (le meilleur en premier)
MODEL_PREFERENCES = [
    "mistral-nemo",   # 12B, 128K contexte, meilleur en français + JSON
    "mistral-small",  # 22B, très bon mais nécessite plus de RAM
    "mistral",        # 7B, fallback
]

_active_model: str | None = None


async def _detect_best_model() -> str:
    """Détecte le meilleur modèle disponible dans Ollama."""
    global _active_model
    if _active_model:
        return _active_model

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"{OLLAMA_URL}/api/tags")
            if response.status_code == 200:
                installed = [m["name"].split(":")[0] for m in response.json().get("models", [])]
                for preferred in MODEL_PREFERENCES:
                    if preferred in installed:
                        _active_model = preferred
                        print(f"[LLM] Modèle sélectionné : {preferred}")
                        return preferred
    except Exception:
        pass

    _active_model = "mistral"
    print(f"[LLM] Fallback sur : mistral")
    return "mistral"


async def query_llm(
    prompt: str,
    system_prompt: str = "",
    temperature: float = 0.3,
    max_tokens: int = 4096,
) -> str:
    """Envoie une requête au LLM via Ollama."""
    model = await _detect_best_model()

    payload = {
        "model": model,
        "prompt": prompt,
        "system": system_prompt,
        "stream": False,
        "options": {
            "temperature": temperature,
            "num_predict": max_tokens,
            "num_ctx": 16384,  # Fenêtre de contexte élargie
        },
    }

    async with httpx.AsyncClient(timeout=600.0) as client:
        try:
            print(f"[LLM] Requête → {model} (temp={temperature}, max_tokens={max_tokens})")
            response = await client.post(f"{OLLAMA_URL}/api/generate", json=payload)
            response.raise_for_status()
            result = response.json()
            text = result.get("response", "").strip()
            tokens_used = result.get("eval_count", 0)
            duration = result.get("total_duration", 0) / 1e9  # nanosecondes → secondes
            print(f"[LLM] Réponse reçue : {tokens_used} tokens en {duration:.1f}s")
            return text
        except httpx.ConnectError:
            return (
                "ERREUR: Impossible de se connecter à Ollama. "
                "Assurez-vous qu'Ollama est en cours d'exécution "
                "(lancez 'ollama serve' dans un terminal)."
            )
        except httpx.ReadTimeout:
            return (
                "ERREUR: Le modèle a mis trop de temps à répondre. "
                "Cela peut arriver avec des documents volumineux. Réessayez."
            )
        except Exception as e:
            return f"ERREUR lors de la communication avec le modèle: {str(e)}"


async def check_ollama_status() -> dict:
    """Vérifie si Ollama est disponible et retourne les infos."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"{OLLAMA_URL}/api/tags")
            if response.status_code == 200:
                models = [m["name"] for m in response.json().get("models", [])]
                best = await _detect_best_model()
                return {
                    "available": True,
                    "models": models,
                    "active_model": best,
                }
    except Exception:
        pass
    return {"available": False, "models": [], "active_model": None}
