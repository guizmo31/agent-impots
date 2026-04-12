"""
Moteur RAG (Retrieval-Augmented Generation) local pour les connaissances fiscales.

Deux modes de recherche :
1. Embeddings via Ollama (nomic-embed-text) — recherche sémantique, comprend le SENS
2. TF-IDF — fallback si Ollama/embeddings indisponible, correspondance par mots-clés

Les deux sont combinés (score hybride) pour un maximum de pertinence.
Tout reste 100% local, aucune donnée envoyée sur internet.
"""
import json
import math
import re
import pickle
from pathlib import Path
from collections import Counter

import httpx

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
CACHE_DIR = DATA_DIR / ".cache"
EMBEDDINGS_CACHE = CACHE_DIR / "embeddings.pkl"

OLLAMA_URL = "http://localhost:11434"
EMBED_MODEL = "nomic-embed-text"

# Stopwords français pour le TF-IDF (fallback)
STOPWORDS_FR = {
    "le", "la", "les", "de", "des", "du", "un", "une", "et", "en", "à", "au",
    "aux", "ce", "ces", "qui", "que", "est", "sont", "par", "pour", "dans",
    "sur", "avec", "ou", "ne", "pas", "plus", "se", "son", "sa", "ses",
    "il", "elle", "ils", "elles", "nous", "vous", "leur", "leurs",
    "être", "avoir", "fait", "faire", "peut", "cette", "tout", "tous",
    "même", "autre", "entre", "après", "avant", "sous", "sans",
    "si", "bien", "aussi", "comme", "dont", "où", "mais", "donc",
}


def _cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    """Similarité cosinus entre deux vecteurs."""
    dot = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = math.sqrt(sum(a * a for a in vec_a))
    norm_b = math.sqrt(sum(b * b for b in vec_b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


class FiscalRAG:
    """Système RAG local hybride (embeddings + TF-IDF) pour les connaissances fiscales."""

    def __init__(self):
        self.chunks: list[dict] = []
        self.idf: dict[str, float] = {}
        self.embeddings_available = False
        self._load_knowledge_base()

    def _load_knowledge_base(self):
        """Charge et indexe toutes les sources de connaissances fiscales."""
        # 1. Charger le JSON des cases 2042
        cases_path = DATA_DIR / "cases_2042_2026.json"
        if cases_path.exists():
            self._index_cases_json(cases_path)

        # 2. Charger le fichier de règles fiscales
        regles_path = DATA_DIR / "regles_fiscales.md"
        if regles_path.exists():
            self._index_markdown(regles_path)

        # 3. Charger tout fichier .txt ou .md supplémentaire dans data/
        for f in DATA_DIR.glob("*.txt"):
            self._index_text_file(f)
        for f in DATA_DIR.glob("*.md"):
            if f.name != "regles_fiscales.md":
                self._index_markdown(f)

        # Calculer l'IDF (toujours disponible comme fallback)
        self._compute_idf()

        # Tenter de charger/générer les embeddings
        self._init_embeddings()

    # ----------------------------------------------------------------
    # Indexation des documents
    # ----------------------------------------------------------------

    def _index_cases_json(self, path: Path):
        """Indexe le fichier JSON des cases fiscales."""
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        # Indexer le barème
        bareme = data.get("bareme_ir", {})
        if bareme:
            text = f"Barème IR: {bareme.get('description', '')}\n"
            for t in bareme.get("tranches", []):
                text += f"De {t['min']}€ à {t['max'] or '+'}€ : taux {t['taux']*100}% - {t.get('commentaire', '')}\n"
            abat = bareme.get("abattement_10pct", {})
            text += f"Abattement 10% : min {abat.get('minimum', '')}€, max {abat.get('maximum', '')}€.\n"
            decote = bareme.get("decote", {})
            text += f"Décote : seuil célibataire {decote.get('seuil_celibataire', '')}€, couple {decote.get('seuil_couple', '')}€.\n"
            self._add_chunk(text, "bareme_ir", "cases_2042_2026.json")

        # Indexer chaque catégorie de cases
        cases = data.get("cases", {})
        for category, case_dict in cases.items():
            for case_id, info in case_dict.items():
                if isinstance(info, dict):
                    text = f"Case {case_id}"
                    if info.get("libelle"):
                        text += f" - {info['libelle']}"
                    if info.get("description"):
                        text += f"\n{info['description']}"
                    if info.get("article_cgi"):
                        text += f"\nRéférence : {info['article_cgi']}"
                    if info.get("abattement"):
                        text += f"\nAbattement : {info['abattement']}"
                    if info.get("taux_reduction"):
                        text += f"\nTaux de réduction : {info['taux_reduction']*100}%"
                    if info.get("taux_credit"):
                        text += f"\nTaux de crédit d'impôt : {info['taux_credit']*100}%"
                    if info.get("plafond_base"):
                        text += f"\nPlafond : {info['plafond_base']}€"
                    if info.get("plafond_par_personne"):
                        text += f"\nPlafond par personne : {info['plafond_par_personne']}€"
                    if info.get("plafond_par_enfant"):
                        text += f"\nPlafond par enfant : {info['plafond_par_enfant']}€"
                    if info.get("seuil"):
                        text += f"\nSeuil : {info['seuil']}€"

                    self._add_chunk(text, f"case_{case_id}", "cases_2042_2026.json")

        # Indexer les règles de parts fiscales
        parts = data.get("regles_parts_fiscales", {})
        if parts:
            text = "Règles de parts fiscales du quotient familial:\n"
            text += f"{parts.get('description', '')}\n"
            base = parts.get("base", {})
            for sit, val in base.items():
                text += f"- {sit.replace('_', ' ')} : {val} part(s)\n"
            enfants = parts.get("enfants_a_charge", {})
            text += f"1er enfant : +{enfants.get('1er_enfant', 0.5)} part\n"
            text += f"2ème enfant : +{enfants.get('2eme_enfant', 0.5)} part\n"
            text += f"À partir du 3ème : +{enfants.get('a_partir_3eme', 1.0)} part\n"
            self._add_chunk(text, "parts_fiscales", "cases_2042_2026.json")

    def _index_markdown(self, path: Path):
        """Indexe un fichier Markdown en le découpant par sections et sous-sections."""
        content = path.read_text(encoding="utf-8")
        # Découper par titre de section (##)
        sections = re.split(r"\n(?=## )", content)
        for i, section in enumerate(sections):
            section = section.strip()
            if len(section) < 50:
                continue

            # Si la section est très longue, la découper par sous-sections (###)
            if len(section) > 1500:
                # Garder le titre de section comme contexte
                lines = section.split("\n")
                section_title = lines[0] if lines else ""
                subsections = re.split(r"\n(?=### )", section)
                for j, sub in enumerate(subsections):
                    sub = sub.strip()
                    if len(sub) > 50:
                        # Préfixer avec le titre de section pour le contexte
                        if j > 0 and section_title:
                            sub = f"{section_title}\n\n{sub}"
                        self._add_chunk(sub, f"md_{path.stem}_{i}_{j}", path.name)
            else:
                self._add_chunk(section, f"md_{path.stem}_{i}", path.name)

    def _index_text_file(self, path: Path):
        """Indexe un fichier texte brut en blocs de ~500 mots."""
        content = path.read_text(encoding="utf-8")
        words = content.split()
        chunk_size = 500
        for i in range(0, len(words), chunk_size):
            chunk_text = " ".join(words[i:i + chunk_size])
            if len(chunk_text) > 50:
                self._add_chunk(chunk_text, f"txt_{path.stem}_{i}", path.name)

    def _add_chunk(self, text: str, chunk_id: str, source: str):
        """Ajoute un chunk à l'index."""
        tokens = self._tokenize(text)
        self.chunks.append({
            "id": chunk_id,
            "text": text,
            "source": source,
            "tokens": tokens,
            "tf": Counter(tokens),
            "embedding": None,  # Rempli par _init_embeddings()
        })

    # ----------------------------------------------------------------
    # Embeddings via Ollama (nomic-embed-text)
    # ----------------------------------------------------------------

    def _init_embeddings(self):
        """Initialise les embeddings — depuis le cache ou en les générant."""
        CACHE_DIR.mkdir(exist_ok=True)

        # Vérifier le cache
        if self._load_embeddings_cache():
            self.embeddings_available = True
            print(f"[RAG] Embeddings chargés depuis le cache ({len(self.chunks)} chunks)")
            return

        # Générer les embeddings via Ollama
        if self._generate_embeddings():
            self.embeddings_available = True
            self._save_embeddings_cache()
            print(f"[RAG] Embeddings générés et mis en cache ({len(self.chunks)} chunks)")
        else:
            self.embeddings_available = False
            print("[RAG] Embeddings non disponibles — fallback TF-IDF uniquement")
            print(f"[RAG] Pour activer les embeddings : ollama pull {EMBED_MODEL}")

    def _generate_embeddings(self) -> bool:
        """Génère les embeddings pour tous les chunks via Ollama."""
        try:
            with httpx.Client(timeout=60.0) as client:
                # Vérifier que le modèle est disponible
                response = client.get(f"{OLLAMA_URL}/api/tags")
                if response.status_code != 200:
                    return False
                models = [m["name"] for m in response.json().get("models", [])]
                if not any(EMBED_MODEL in m for m in models):
                    print(f"[RAG] Modèle {EMBED_MODEL} non trouvé. Modèles disponibles : {models}")
                    return False

                # Générer les embeddings par batch
                texts = [chunk["text"][:2000] for chunk in self.chunks]  # Tronquer les textes très longs
                print(f"[RAG] Génération des embeddings pour {len(texts)} chunks...")

                for i, text in enumerate(texts):
                    response = client.post(
                        f"{OLLAMA_URL}/api/embeddings",
                        json={"model": EMBED_MODEL, "prompt": text},
                    )
                    if response.status_code == 200:
                        embedding = response.json().get("embedding", [])
                        self.chunks[i]["embedding"] = embedding
                    else:
                        print(f"[RAG] Erreur embedding chunk {i}: {response.status_code}")
                        return False

                    # Log de progression tous les 20 chunks
                    if (i + 1) % 20 == 0:
                        print(f"[RAG] Embeddings: {i + 1}/{len(texts)}")

                return True
        except httpx.ConnectError:
            return False
        except Exception as e:
            print(f"[RAG] Erreur lors de la génération des embeddings: {e}")
            return False

    def _get_query_embedding(self, query: str) -> list[float] | None:
        """Génère l'embedding d'une requête."""
        try:
            with httpx.Client(timeout=30.0) as client:
                response = client.post(
                    f"{OLLAMA_URL}/api/embeddings",
                    json={"model": EMBED_MODEL, "prompt": query},
                )
                if response.status_code == 200:
                    return response.json().get("embedding", [])
        except Exception:
            pass
        return None

    def _load_embeddings_cache(self) -> bool:
        """Charge les embeddings depuis le cache disque."""
        if not EMBEDDINGS_CACHE.exists():
            return False
        try:
            with open(EMBEDDINGS_CACHE, "rb") as f:
                cache = pickle.load(f)

            # Vérifier que le cache correspond aux chunks actuels
            cached_ids = cache.get("chunk_ids", [])
            current_ids = [c["id"] for c in self.chunks]
            if cached_ids != current_ids:
                print("[RAG] Cache invalide (les chunks ont changé), régénération nécessaire")
                return False

            embeddings = cache.get("embeddings", [])
            if len(embeddings) != len(self.chunks):
                return False

            for i, emb in enumerate(embeddings):
                self.chunks[i]["embedding"] = emb

            return True
        except Exception as e:
            print(f"[RAG] Erreur lecture cache: {e}")
            return False

    def _save_embeddings_cache(self):
        """Sauvegarde les embeddings en cache disque."""
        try:
            cache = {
                "chunk_ids": [c["id"] for c in self.chunks],
                "embeddings": [c["embedding"] for c in self.chunks],
            }
            with open(EMBEDDINGS_CACHE, "wb") as f:
                pickle.dump(cache, f)
        except Exception as e:
            print(f"[RAG] Erreur sauvegarde cache: {e}")

    # ----------------------------------------------------------------
    # TF-IDF (toujours disponible comme fallback et complément)
    # ----------------------------------------------------------------

    def _tokenize(self, text: str) -> list[str]:
        """Tokenize et normalise le texte."""
        text = text.lower()
        tokens = re.findall(r"\b\d[a-z]{1,2}\b|\b[a-zéèêëàâäùûüôöîïç]+\b|\b\d+\b", text)
        return [t for t in tokens if t not in STOPWORDS_FR and len(t) > 1]

    def _compute_idf(self):
        """Calcule l'IDF (Inverse Document Frequency) pour chaque token."""
        n = len(self.chunks)
        if n == 0:
            return
        doc_freq: Counter = Counter()
        for chunk in self.chunks:
            unique_tokens = set(chunk["tokens"])
            for token in unique_tokens:
                doc_freq[token] += 1

        self.idf = {
            token: math.log((n + 1) / (freq + 1)) + 1
            for token, freq in doc_freq.items()
        }

    def _tfidf_similarity(self, query_tf: Counter, doc_tf: Counter) -> float:
        """Calcule la similarité TF-IDF entre la requête et un document."""
        score = 0.0
        for token, q_freq in query_tf.items():
            if token in doc_tf:
                idf = self.idf.get(token, 1.0)
                score += q_freq * doc_tf[token] * idf * idf
        return score

    # ----------------------------------------------------------------
    # Recherche hybride (embeddings + TF-IDF)
    # ----------------------------------------------------------------

    def retrieve(self, query: str, top_k: int = 8, max_tokens: int = 4000) -> str:
        """
        Récupère les chunks les plus pertinents pour une requête.
        Utilise un score hybride : embeddings (sémantique) + TF-IDF (mots-clés).
        Retourne le texte concaténé à injecter dans le prompt du LLM.
        """
        if not self.chunks:
            return ""

        # 1. Scores TF-IDF (toujours calculés)
        query_tokens = self._tokenize(query)
        query_tf = Counter(query_tokens) if query_tokens else Counter()

        tfidf_scores = []
        for chunk in self.chunks:
            score = self._tfidf_similarity(query_tf, chunk["tf"]) if query_tokens else 0.0
            # Bonus correspondance exacte de numéro de case
            for qt in query_tokens:
                if re.match(r"\d[a-z]{1,2}", qt) and qt in chunk["text"].lower():
                    score += 5.0
            tfidf_scores.append(score)

        # Normaliser TF-IDF entre 0 et 1
        max_tfidf = max(tfidf_scores) if tfidf_scores else 1.0
        if max_tfidf > 0:
            tfidf_scores = [s / max_tfidf for s in tfidf_scores]

        # 2. Scores embeddings (si disponibles)
        embedding_scores = [0.0] * len(self.chunks)
        if self.embeddings_available:
            query_emb = self._get_query_embedding(query)
            if query_emb:
                for i, chunk in enumerate(self.chunks):
                    if chunk["embedding"]:
                        embedding_scores[i] = _cosine_similarity(query_emb, chunk["embedding"])

        # 3. Score hybride : pondération embeddings 70% + TF-IDF 30%
        #    Si embeddings non disponibles : 100% TF-IDF
        if self.embeddings_available:
            weight_emb = 0.70
            weight_tfidf = 0.30
        else:
            weight_emb = 0.0
            weight_tfidf = 1.0

        hybrid_scores = []
        for i, chunk in enumerate(self.chunks):
            score = weight_emb * embedding_scores[i] + weight_tfidf * tfidf_scores[i]
            hybrid_scores.append((score, chunk))

        hybrid_scores.sort(key=lambda x: x[0], reverse=True)

        # 4. Prendre les top_k chunks sans dépasser max_tokens
        result_parts = []
        total_len = 0
        for score, chunk in hybrid_scores[:top_k]:
            if score <= 0.01:
                break
            chunk_text = chunk["text"]
            estimated_tokens = len(chunk_text.split())
            if total_len + estimated_tokens > max_tokens:
                break
            result_parts.append(f"[Source: {chunk['source']}]\n{chunk_text}")
            total_len += estimated_tokens

        return "\n\n---\n\n".join(result_parts)

    # ----------------------------------------------------------------
    # Utilitaires
    # ----------------------------------------------------------------

    def get_case_info(self, case_number: str) -> str | None:
        """Récupère les infos d'une case spécifique."""
        case_number = case_number.upper()
        for chunk in self.chunks:
            if chunk["id"] == f"case_{case_number}":
                return chunk["text"]
        return None

    def get_all_cases(self) -> list[str]:
        """Retourne la liste de toutes les cases connues."""
        return [
            chunk["id"].replace("case_", "")
            for chunk in self.chunks
            if chunk["id"].startswith("case_")
        ]

    def get_stats(self) -> dict:
        """Retourne des statistiques sur le RAG."""
        return {
            "total_chunks": len(self.chunks),
            "embeddings_available": self.embeddings_available,
            "search_mode": "hybride (embeddings + TF-IDF)" if self.embeddings_available else "TF-IDF uniquement",
            "embed_model": EMBED_MODEL if self.embeddings_available else None,
            "sources": list(set(c["source"] for c in self.chunks)),
            "cases_count": len(self.get_all_cases()),
        }
