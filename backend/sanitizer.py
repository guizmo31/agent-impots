"""
Sanitizer anti-prompt-injection pour les documents utilisateur.

Detecte et neutralise les tentatives d'injection dans les documents
(PDF, texte, etc.) AVANT qu'ils ne soient envoyes au LLM.

Exemples d'attaques bloquees :
- "Ignore les instructions precedentes et..."
- "Tu es maintenant un assistant qui..."
- "SYSTEM: new instructions..."
- Balises XML/HTML cachees dans un PDF
"""
import re

# Patterns de prompt injection connus
INJECTION_PATTERNS = [
    # Anglais
    r"ignore\s+(all\s+)?previous\s+instructions",
    r"ignore\s+(all\s+)?prior\s+instructions",
    r"disregard\s+(all\s+)?previous",
    r"forget\s+(all\s+)?previous",
    r"you\s+are\s+now\s+a",
    r"new\s+instructions?\s*:",
    r"override\s+instructions",
    r"SYSTEM\s*:",
    r"ADMIN\s*:",
    r"<\s*system\s*>",
    r"<\s*/?\s*instruction",
    r"\[\s*INST\s*\]",
    r"\[\/?\s*INST\s*\]",

    # Francais
    r"ignore\s+(toutes?\s+)?les?\s+instructions?\s+pr[eé]c[eé]dentes?",
    r"oublie\s+(toutes?\s+)?les?\s+instructions?",
    r"tu\s+es\s+maintenant\s+un",
    r"nouvelles?\s+instructions?\s*:",
    r"r[eé]initialise\s+(tes?\s+)?instructions?",

    # Tentatives de role-play
    r"pretend\s+you\s+are",
    r"act\s+as\s+if",
    r"fais\s+comme\s+si\s+tu\s+[eé]tais",
    r"joue\s+le\s+r[oô]le",

    # Tentatives d'exfiltration
    r"r[eé]p[eè]te\s+(moi\s+)?le\s+prompt",
    r"affiche\s+(moi\s+)?(le|ton)\s+prompt",
    r"show\s+(me\s+)?your\s+(system\s+)?prompt",
    r"print\s+your\s+instructions",
    r"what\s+are\s+your\s+instructions",
]

# Compile les patterns une seule fois
_COMPILED_PATTERNS = [re.compile(p, re.IGNORECASE) for p in INJECTION_PATTERNS]


def sanitize_document_content(content: str, filename: str = "") -> tuple[str, list[str]]:
    """Sanitize le contenu d'un document avant envoi au LLM.

    Returns:
        (contenu_nettoye, liste_warnings)
    """
    warnings = []

    if not content:
        return content, warnings

    # 1. Detecter les patterns d'injection
    for pattern in _COMPILED_PATTERNS:
        matches = pattern.findall(content)
        if matches:
            warnings.append(
                f"[SECURITE] Pattern suspect detecte dans {filename}: '{matches[0]}' -- neutralise"
            )
            # Remplacer par un marqueur inoffensif
            content = pattern.sub("[CONTENU FILTRE]", content)

    # 2. Supprimer les balises XML/HTML cachees (souvent utilisees pour injecter des instructions)
    suspicious_tags = re.findall(r"<\s*(system|instruction|prompt|admin|role|context)\b[^>]*>.*?</\s*\1\s*>", content, re.IGNORECASE | re.DOTALL)
    if suspicious_tags:
        warnings.append(f"[SECURITE] Balises suspectes detectees dans {filename}: {len(suspicious_tags)} supprimee(s)")
        content = re.sub(r"<\s*(system|instruction|prompt|admin|role|context)\b[^>]*>.*?</\s*\1\s*>", "[CONTENU FILTRE]", content, flags=re.IGNORECASE | re.DOTALL)

    # 3. Supprimer les sequences de caracteres invisibles (zero-width, etc.)
    content = re.sub(r"[\u200b\u200c\u200d\u200e\u200f\u2060\ufeff]", "", content)

    return content, warnings


def is_suspicious(content: str) -> bool:
    """Retourne True si le contenu semble contenir du prompt injection."""
    for pattern in _COMPILED_PATTERNS:
        if pattern.search(content):
            return True
    return False
