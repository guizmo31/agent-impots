# Agent Impots

**Assistant fiscal intelligent, 100% local et privé, pour préparer sa déclaration d'impôts sur le revenu en France.**

Aucune donnée ne quitte votre ordinateur : le modèle d'IA (Mistral 7B) tourne localement via Ollama, vos documents restent sur votre disque, et aucun appel réseau n'est effectué.

---

## Objectif

Remplir sa déclaration d'impôts est complexe : entre les numéros de cases (1AJ, 4BA, 7DB...), les régimes fiscaux (micro-foncier, LMNP, PFU...) et les multiples formulaires (2042, 2044, 2042-C...), il est facile de se tromper ou d'oublier une déduction.

**Agent Impots** vous guide pas à pas :

1. Vous lui indiquez un dossier contenant vos documents fiscaux (bulletins de paie, relevés, factures, avis...)
2. Il analyse et extrait automatiquement les informations (PDF, images avec OCR, Excel, CSV, Word)
3. Il vous pose des questions ciblées pour compléter votre profil (situation familiale, enfants, revenus complémentaires, charges...)
4. Il calcule votre impôt et produit un **rapport détaillé** avec pour chaque montant :
   - Le **numéro de la case** exacte à remplir
   - Le **montant** calculé
   - La **justification** complète (source documentaire, règle fiscale, article du CGI)

## Domaines couverts

| Domaine | Détails |
|---------|---------|
| **Salaires** | Cases 1AJ/1BJ, abattement 10%, frais réels, heures sup exonérées |
| **Sociétés** | SA, SAS, SARL (gérant majoritaire art. 62), SCI (IR/IS), SCPI, EURL, SNC |
| **Actions & titres** | Plus-values (3VG), RSU/AGA (1TZ), stock-options (1TT), BSPCE, PEA, crypto (3VT) |
| **Immobilier locatif** | Location nue (bail 3 ans, micro-foncier 4BE, réel 4BA), LMNP (5ND), LMP, meublé saisonnier/Airbnb, Pinel, déficit foncier |
| **Famille** | Parts fiscales, enfants mineurs/majeurs rattachés, résidence alternée, parent isolé (case T), handicap (CMI) |
| **Aidants** | EHPAD (7CD), accueil ascendant, emploi à domicile (7DB), pensions alimentaires (6GI/6GU), APA |
| **Autres** | PER (6NS), dons (7UF), garde d'enfants (7GA), IFI, revenus étrangers, prélèvements sociaux |

## Architecture technique

```
Navigateur (http://localhost:8000)
    │ WebSocket
    ▼
FastAPI (backend Python)
    │
    ├── Agent conversationnel (flux étape par étape)
    ├── Parser de documents (PDF/OCR/Excel/CSV/Word)
    ├── RAG hybride ──► Embeddings (nomic-embed-text via Ollama)
    │                └► TF-IDF (fallback sans GPU)
    ├── Moteur de calcul fiscal (barème IR, quotient familial, décote)
    └── Générateur de rapport HTML
    │
    ▼
Ollama (local)
    ├── Mistral 7B (~4 Go) — LLM principal
    └── nomic-embed-text (~270 Mo) — embeddings pour le RAG
```

---

## Installation sur Windows

### Prérequis

| Logiciel | Téléchargement | Pourquoi |
|----------|---------------|----------|
| **Python 3.10+** | [python.org/downloads](https://www.python.org/downloads/) | Backend du serveur |
| **Ollama** | [ollama.com/download/windows](https://ollama.com/download/windows) | Fait tourner le LLM en local |
| **Git** *(optionnel)* | [git-scm.com](https://git-scm.com/download/win) | Pour cloner le repo |

> **Note** : lors de l'installation de Python, cochez **"Add Python to PATH"**.

### Etape 1 — Cloner le projet

```cmd
git clone https://github.com/votre-user/AGENT-IMPOTS.git
cd AGENT-IMPOTS
```

Ou téléchargez le ZIP depuis GitHub et décompressez-le.

### Etape 2 — Installer Ollama

1. Téléchargez l'installeur depuis [ollama.com/download/windows](https://ollama.com/download/windows)
2. Lancez l'installeur et suivez les instructions
3. Ollama démarre automatiquement en tâche de fond (icône dans la barre de notification)
4. Vérification dans un terminal :
   ```cmd
   ollama --version
   ```

### Etape 3 — Lancer l'installation

Double-cliquez sur **`setup.bat`** ou dans un terminal :
```cmd
setup.bat
```

Ce script va automatiquement :
1. Installer les dépendances Python (FastAPI, uvicorn, PyMuPDF, websockets...)
2. Détecter Ollama (cherche dans le PATH et les emplacements classiques)
3. Télécharger **Mistral 7B** (~4 Go — première fois uniquement)
4. Télécharger **nomic-embed-text** (~270 Mo — pour les embeddings du RAG)

> Le téléchargement des modèles peut prendre 10-20 minutes selon votre connexion.

### Etape 4 — Lancer l'agent

Double-cliquez sur **`lancer.bat`** ou :
```cmd
lancer.bat
```

Puis ouvrez **http://localhost:8000** dans votre navigateur.

### Dépannage Windows

| Problème | Solution |
|----------|----------|
| `ollama` n'est pas reconnu | Fermez et rouvrez le terminal après l'installation d'Ollama. Le script cherche aussi dans `%LOCALAPPDATA%\Programs\Ollama\` |
| Erreur WebSocket / 404 sur `/ws/` | Lancez `pip install "uvicorn[standard]"` |
| Le modèle est très lent | Normal au premier lancement (chargement en RAM). Mistral 7B nécessite ~6 Go de RAM libre |
| OCR ne fonctionne pas sur les images | Installez [Tesseract OCR](https://github.com/UB-Mannheim/tesseract/wiki) pour Windows. Les PDF textuels fonctionnent sans Tesseract |

---

## Installation sur macOS

### Prérequis

```bash
# Python (si pas déjà installé)
brew install python3

# Ollama
brew install ollama
```

Ou téléchargez Ollama depuis [ollama.com/download/mac](https://ollama.com/download/mac).

### Installation et lancement

```bash
git clone https://github.com/votre-user/AGENT-IMPOTS.git
cd AGENT-IMPOTS
chmod +x setup.sh lancer.sh

# Installation (dépendances + modèles)
./setup.sh

# Lancement
./lancer.sh
```

Puis ouvrez **http://localhost:8000**.

### Dépannage macOS

| Problème | Solution |
|----------|----------|
| `pip3: command not found` | `brew install python3` ou `python3 -m ensurepip` |
| `ollama: command not found` | `brew install ollama` ou téléchargez l'app depuis ollama.com |
| Erreur de permission sur les scripts | `chmod +x setup.sh lancer.sh` |
| OCR sur les images | `brew install tesseract` puis `brew install tesseract-lang` pour le français |

---

## Installation sur Linux

### Prérequis

```bash
# Ubuntu / Debian
sudo apt update
sudo apt install python3 python3-pip python3-venv

# Ollama (une seule commande)
curl -fsSL https://ollama.com/install.sh | sh
```

### Installation et lancement

```bash
git clone https://github.com/votre-user/AGENT-IMPOTS.git
cd AGENT-IMPOTS
chmod +x setup.sh lancer.sh
./setup.sh
./lancer.sh
```

Puis ouvrez **http://localhost:8000**.

---

## Utilisation

### Flux de dialogue

```
Agent : "Bonjour ! Indiquez le chemin du dossier contenant vos documents fiscaux."
  Vous : C:\Users\MonNom\Documents\Impots2025

Agent : "J'ai trouvé 6 documents. Analyse en cours..."
Agent : "Documents identifiés :
         - bulletin_dec.pdf : Bulletin de paie — Net imposable : 32 450€
         - releve_bourso.pdf : Relevé de compte-titres
         ..."

Agent : "Question 1/7 : Quelle est votre situation familiale ?"
  Vous : Marié, 2 enfants

Agent : "Question 2/7 : Avez-vous des revenus fonciers ?"
  Vous : Oui, un appartement en location meublée Airbnb, 8000€ de recettes

   ... (questions adaptées aux documents détectés)

Agent : "Voici le résultat de votre déclaration :"
         ┌──────┬───────────────────────────┬───────────┐
         │ Case │ Libellé                   │ Montant   │
         ├──────┼───────────────────────────┼───────────┤
         │ 1AJ  │ Salaires déclarant 1      │ 32 450 €  │
         │ 1BJ  │ Salaires déclarant 2      │ 28 100 €  │
         │ 5NJ  │ Location meublée Airbnb   │  8 000 €  │
         │ ...  │ ...                       │ ...       │
         └──────┴───────────────────────────┴───────────┘

Agent : [Lien vers le rapport HTML détaillé]
```

### Formats de documents supportés

| Format | Extension | Méthode d'extraction |
|--------|-----------|---------------------|
| PDF texte | `.pdf` | PyMuPDF (extraction directe) |
| PDF scanné | `.pdf` | PyMuPDF + OCR Tesseract |
| Images | `.png` `.jpg` `.jpeg` `.tiff` `.bmp` | OCR Tesseract |
| Excel | `.xlsx` `.xls` | openpyxl |
| CSV | `.csv` | csv (détection auto du séparateur) |
| Word | `.docx` | python-docx |
| Texte | `.txt` | Lecture directe |

---

## Structure du projet

```
AGENT-IMPOTS/
├── setup.bat / setup.sh          ← Scripts d'installation
├── lancer.bat / lancer.sh        ← Scripts de démarrage
├── requirements.txt              ← Dépendances Python
├── backend/
│   ├── app.py                    ← Serveur FastAPI + WebSocket
│   ├── agent.py                  ← Logique conversationnelle
│   ├── ollama_client.py          ← Client Ollama (Mistral 7B)
│   ├── rag.py                    ← RAG hybride (embeddings + TF-IDF)
│   ├── document_parser.py        ← Parsing multi-format + OCR
│   ├── fiscal_engine.py          ← Moteur de calcul fiscal (barème IR)
│   └── report_generator.py       ← Génération rapport HTML
├── frontend/
│   ├── index.html                ← Interface de chat
│   ├── css/style.css
│   └── js/app.js
├── data/
│   ├── cases_2042_2026.json      ← ~100 cases fiscales documentées
│   └── regles_fiscales.md        ← Règles fiscales détaillées (20 sections)
├── documents/                    ← Vos documents (ignoré par git)
└── output/                       ← Rapports générés (ignoré par git)
```

## Mise à jour de la base fiscale

Les connaissances fiscales sont dans `data/`. Pour mettre à jour quand un nouveau barème ou formulaire est publié :

1. Modifier `data/cases_2042_2026.json` — cases, seuils, taux
2. Modifier `data/regles_fiscales.md` — règles, explications
3. Ajouter des fichiers `.md` ou `.txt` dans `data/` — indexés automatiquement
4. Supprimer `data/.cache/` pour forcer la régénération des embeddings

## Configuration matérielle recommandée

| Composant | Minimum | Recommandé |
|-----------|---------|------------|
| RAM | 8 Go | 16 Go+ |
| Stockage | 10 Go libres | 15 Go libres |
| CPU | Tout CPU x64 récent | AMD Ryzen / Intel i5+ |
| GPU | Non requis | Accélère Ollama si compatible |

Testé sur : GEEKOM A9 Max (AMD Ryzen 9, 28 Go RAM) sous Windows 11.

---

## Avertissement

Cet outil est une **aide à la préparation de la déclaration d'impôts**. Il ne remplace pas un conseiller fiscal professionnel. Vérifiez systématiquement chaque montant et chaque case avant de soumettre votre déclaration officielle sur [impots.gouv.fr](https://www.impots.gouv.fr).

## Licence

MIT
