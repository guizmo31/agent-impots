# Agent Impots

**Agent fiscal 100% local pour preparer sa declaration d'impots sur le revenu en France.**

> **Aucune donnee ne quitte votre ordinateur.** Le modele d'IA (Mistral-Nemo 12B) tourne localement via Ollama, vos documents restent sur votre disque, aucun appel reseau n'est effectue. Vos donnees fiscales ne transitent par aucun cloud, aucun serveur distant, aucune API externe.

---

## Avertissement

**Cet outil est une aide a la preparation de la declaration d'impots.** Il ne remplace en aucun cas un conseiller fiscal professionnel, un expert-comptable ou l'administration fiscale.

- Les calculs et les numeros de cases sont des **estimations** basees sur les documents fournis et la base de connaissances fiscales integree.
- Des erreurs sont possibles, notamment sur les situations complexes (multi-societes, revenus etrangers, dispositifs speciaux).
- **Verifiez systematiquement chaque montant et chaque case** avant de soumettre votre declaration officielle sur [impots.gouv.fr](https://www.impots.gouv.fr).
- En cas de doute, consultez un professionnel.

---

## Objectif

Remplir sa declaration d'impots est complexe : entre les numeros de cases (1AJ, 4BA, 7DB...), les regimes fiscaux (micro-foncier, LMNP, PFU...) et les multiples formulaires (2042, 2044, 2042-C...), il est facile de se tromper ou d'oublier une deduction.

**Agent Impots** est un assistant **100% local** qui vous guide pas a pas :

1. Vous lui indiquez un dossier contenant vos documents fiscaux (bulletins de paie, releves, factures, avis...)
2. Il analyse chaque document **localement** et construit un profil fiscal structure
3. Il vous pose des questions ciblees pour completer les informations manquantes
4. Il calcule votre impot et produit un **rapport detaille** avec pour chaque montant :
   - Le **numero de la case** exacte a remplir
   - Le **montant** calcule
   - La **justification** complete (source documentaire, regle fiscale, article du CGI)

**Tout reste sur votre machine** -- aucune donnee n'est envoyee sur internet.

## Pourquoi 100% local ?

- Vos documents fiscaux contiennent des informations extremement sensibles (revenus, patrimoine, situation familiale)
- Un agent cloud enverrait ces donnees sur des serveurs tiers
- Ici, le modele d'IA tourne **sur votre PC** via Ollama -- zero fuite de donnees
- Meme la recherche semantique (RAG) utilise des embeddings generes **localement**
- Vous pouvez couper internet et l'agent fonctionne quand meme

## Domaines couverts

| Domaine | Details |
|---------|---------|
| **Salaires** | Cases 1AJ/1BJ, abattement 10%, frais reels, heures sup exonerees |
| **Societes** | SA, SAS, SARL (gerant majoritaire art. 62), SCI (IR/IS), SCPI, EURL, SNC |
| **Actions & titres** | Plus-values (3VG), RSU/AGA (1TZ), stock-options (1TT), BSPCE, PEA, crypto (3VT) |
| **Immobilier locatif** | Location nue (bail 3 ans, micro-foncier 4BE, reel 4BA), LMNP (5ND), LMP, meuble saisonnier/Airbnb, Pinel, deficit foncier |
| **Famille** | Parts fiscales, enfants mineurs/majeurs rattaches, residence alternee, parent isole (case T), handicap (CMI) |
| **Aidants** | EHPAD (7CD), accueil ascendant, emploi a domicile (7DB), pensions alimentaires (6GI/6GU), APA |
| **Autres** | PER (6NS), dons (7UF), garde d'enfants (7GA), IFI, revenus etrangers, prelevements sociaux |

## Architecture technique

L'agent fonctionne **integralement en local** selon ce pipeline :

```
Navigateur (http://localhost:8000)           <- 100% local
    | WebSocket
    v
FastAPI (backend Python)                     <- 100% local
    |
    |-- Etape 1 : INGESTION
    |   Chaque document -> extraction structuree universelle (1 appel LLM par doc)
    |   -> ExtractionStore (RAG local des donnees du contribuable)
    |   -> FiscalProfile (profil JSON = source de verite unique)
    |
    |-- Etape 2 : VALIDATION
    |   Profil analyse -> detection des manques -> questions ciblees
    |
    |-- Etape 3 : CALCUL
    |   RAG fiscal (regles, bareme, cases) + profil JSON -> cases 2042
    |
    |-- Etape 4 : VERIFICATION
    |   Cross-check coherence (SASU/IS, LMNP/LMP, ...) -> rapport HTML
    |
    v
Ollama (100% local)
    |-- Mistral-Nemo 12B (~7 Go) -- LLM principal (128K contexte, excellent en francais)
    |-- Mistral 7B (~4 Go) -- modele de secours
    '-- nomic-embed-text (~270 Mo) -- embeddings pour les deux RAG locaux
```

**Deux RAG locaux** (aucun cloud) :
- **RAG fiscal** : regles fiscales, ~145 cases 2042, bareme IR, articles CGI
- **RAG extractions** : donnees structurees extraites de VOS documents

---

## Installation sur Windows

### Prerequis

| Logiciel | Telechargement | Pourquoi |
|----------|---------------|----------|
| **Python 3.10+** | [python.org/downloads](https://www.python.org/downloads/) | Backend du serveur (100% local) |
| **Ollama** | [ollama.com/download/windows](https://ollama.com/download/windows) | Fait tourner le LLM localement sur votre PC |
| **Git** *(optionnel)* | [git-scm.com](https://git-scm.com/download/win) | Pour cloner le repo |

> **Note** : lors de l'installation de Python, cochez **"Add Python to PATH"**.

### Etape 1 -- Cloner le projet

```cmd
git clone https://github.com/guizmo31/agent-impots.git
cd agent-impots
```

Ou telechargez le ZIP depuis GitHub et decompressez-le.

### Etape 2 -- Installer Ollama

1. Telechargez l'installeur depuis [ollama.com/download/windows](https://ollama.com/download/windows)
2. Lancez l'installeur et suivez les instructions
3. Ollama demarre automatiquement en tache de fond (icone dans la barre de notification)
4. Verification dans un terminal :
   ```cmd
   ollama --version
   ```

### Etape 3 -- Lancer l'installation

Double-cliquez sur **`setup.bat`** ou dans un terminal :
```cmd
setup.bat
```

Ce script va automatiquement :
1. Installer les dependances Python (FastAPI, uvicorn, PyMuPDF, websockets...)
2. Detecter Ollama (cherche dans le PATH et les emplacements classiques)
3. Telecharger **Mistral-Nemo 12B** (~7 Go) -- le LLM principal, excellent en francais et en JSON
4. Telecharger **Mistral 7B** (~4 Go) -- modele de secours
5. Telecharger **nomic-embed-text** (~270 Mo) -- pour les embeddings des RAG locaux

> Le telechargement des modeles peut prendre 10-20 minutes selon votre connexion. C'est la seule fois ou une connexion internet est necessaire -- ensuite tout fonctionne hors ligne.

### Etape 4 -- Lancer l'agent local

Double-cliquez sur **`lancer.bat`** ou :
```cmd
lancer.bat
```

Puis ouvrez **http://localhost:8000** dans votre navigateur. L'agent tourne localement sur votre machine.

### Depannage Windows

| Probleme | Solution |
|----------|----------|
| `ollama` n'est pas reconnu | Fermez et rouvrez le terminal apres l'installation d'Ollama. Le script cherche aussi dans `%LOCALAPPDATA%\Programs\Ollama\` |
| Erreur WebSocket / 404 sur `/ws/` | Lancez `pip install "uvicorn[standard]"` |
| Le modele est tres lent | Normal au premier lancement (chargement en RAM). Mistral-Nemo 12B necessite ~10 Go de RAM libre |
| OCR ne fonctionne pas sur les images | Installez [Tesseract OCR](https://github.com/UB-Mannheim/tesseract/wiki) pour Windows. Les PDF textuels fonctionnent sans Tesseract |

---

## Installation sur macOS

### Prerequis

```bash
# Python (si pas deja installe)
brew install python3

# Ollama (LLM 100% local)
brew install ollama
```

Ou telechargez Ollama depuis [ollama.com/download/mac](https://ollama.com/download/mac).

### Installation et lancement

```bash
git clone https://github.com/guizmo31/agent-impots.git
cd agent-impots
chmod +x setup.sh lancer.sh

# Installation (dependances + modeles locaux)
./setup.sh

# Lancement de l'agent local
./lancer.sh
```

Puis ouvrez **http://localhost:8000**. Tout tourne sur votre Mac, rien n'est envoye en ligne.

### Depannage macOS

| Probleme | Solution |
|----------|----------|
| `pip3: command not found` | `brew install python3` ou `python3 -m ensurepip` |
| `ollama: command not found` | `brew install ollama` ou telechargez l'app depuis ollama.com |
| Erreur de permission sur les scripts | `chmod +x setup.sh lancer.sh` |
| OCR sur les images | `brew install tesseract` puis `brew install tesseract-lang` pour le francais |

---

## Installation sur Linux

### Prerequis

```bash
# Ubuntu / Debian
sudo apt update
sudo apt install python3 python3-pip python3-venv

# Ollama (LLM 100% local, une seule commande)
curl -fsSL https://ollama.com/install.sh | sh
```

### Installation et lancement

```bash
git clone https://github.com/guizmo31/agent-impots.git
cd agent-impots
chmod +x setup.sh lancer.sh
./setup.sh
./lancer.sh
```

Puis ouvrez **http://localhost:8000**. 100% local, zero cloud.

---

## Utilisation

### Flux de dialogue

```
Agent : "Bonjour ! Indiquez le chemin du dossier contenant vos documents fiscaux."
  Vous : C:\Users\MonNom\Documents\Impots2025

Agent : "32 documents trouves. Ingestion en cours..."
         [Chaque document est analyse localement un par un]

Agent : "Ingestion terminee. 28 extraits, 4 non exploitables.
         Types detectes : fiche_de_paie (12), taxe_fonciere (3), pret_immobilier (2)...
         Montants cles : net_imposable: 48 000EUR, taxe_fonciere: 1 200EUR..."

Agent : "Il me manque 5 informations pour calculer votre impot."
Agent : "Question 1/5 : Quelle est votre situation familiale ?"
  Vous : Marie, 2 enfants

Agent : "Question 2/5 : Pour vos revenus fonciers, etes-vous au micro-foncier ou au reel ?"
  Vous : Micro-foncier

   ... (questions adaptees a VOTRE profil)

Agent : "Voici le resultat de votre declaration :"
         | Case | Libelle                   | Montant   |
         |------|---------------------------|-----------|
         | 1AJ  | Salaires declarant 1      | 48 000 EUR|
         | 4BE  | Revenus fonciers micro     | 12 000 EUR|
         | 7UF  | Dons associations          |    500 EUR|
         | ...  | ...                       | ...       |

Agent : [Lien vers le rapport HTML detaille]
```

### Memoire persistante

L'agent sauvegarde votre progression **localement** :
- Fermez le navigateur en plein milieu -> rouvrez -> l'agent reprend ou vous en etiez
- Les documents deja analyses ne sont pas re-traites
- Le profil fiscal se construit au fil des sessions

### Formats de documents supportes

| Format | Extension | Methode d'extraction |
|--------|-----------|---------------------|
| PDF texte | `.pdf` | PyMuPDF (extraction directe, 100% local) |
| PDF scanne | `.pdf` | PyMuPDF + OCR Tesseract (100% local) |
| Images | `.png` `.jpg` `.jpeg` `.tiff` `.bmp` | OCR Tesseract (100% local) |
| Excel | `.xlsx` `.xls` | openpyxl |
| CSV | `.csv` | csv (detection auto du separateur) |
| Word | `.docx` | python-docx |
| Texte | `.txt` | Lecture directe |

---

## Structure du projet

```
agent-impots/
|-- setup.bat / setup.sh            <- Scripts d'installation
|-- lancer.bat / lancer.sh          <- Scripts de demarrage
|-- requirements.txt
|-- backend/
|   |-- app.py                      <- Serveur FastAPI + WebSocket
|   |-- agent.py                    <- Orchestration multi-etapes
|   |-- ollama_client.py            <- Client Ollama (Mistral-Nemo 12B, 100% local)
|   |-- extractors.py               <- Extracteur universel de donnees fiscales
|   |-- extraction_store.py         <- RAG local des extractions du contribuable
|   |-- fiscal_profile.py           <- Profil fiscal JSON (source de verite)
|   |-- rag.py                      <- RAG fiscal (regles, cases, bareme)
|   |-- document_parser.py          <- Parsing multi-format + OCR
|   |-- fiscal_engine.py            <- Moteur de calcul fiscal (bareme IR)
|   |-- report_generator.py         <- Generation rapport HTML
|   '-- session_store.py            <- Memoire persistante des sessions
|-- frontend/
|   |-- index.html                  <- Interface de chat
|   |-- css/style.css
|   '-- js/app.js
|-- data/
|   |-- cases_2042_2026.json        <- ~145 cases fiscales documentees
|   '-- regles_fiscales.md          <- Regles fiscales detaillees (20 sections)
|-- sessions/                       <- Donnees des sessions (local, ignore par git)
|-- documents/                      <- Vos documents (local, ignore par git)
'-- output/                         <- Rapports generes (local, ignore par git)
```

## Mise a jour de la base fiscale

Les connaissances fiscales sont dans `data/`. Pour mettre a jour quand un nouveau bareme ou formulaire est publie :

1. Modifier `data/cases_2042_2026.json` -- cases, seuils, taux
2. Modifier `data/regles_fiscales.md` -- regles, explications
3. Ajouter des fichiers `.md` ou `.txt` dans `data/` -- indexes automatiquement par le RAG local
4. Supprimer `data/.cache/` pour forcer la regeneration des embeddings locaux

## Configuration materielle recommandee

| Composant | Minimum | Recommande |
|-----------|---------|------------|
| RAM | 12 Go | 16 Go+ |
| Stockage | 15 Go libres | 20 Go libres |
| CPU | Tout CPU x64 recent | AMD Ryzen / Intel i5+ |
| GPU | Non requis | Accelere Ollama si compatible |

L'agent tourne integralement sur CPU. Teste sur : GEEKOM A9 Max (AMD Ryzen 9, 28 Go RAM) sous Windows 11.

---

## Vie privee et securite

- **Zero cloud** : aucune donnee n'est envoyee sur internet
- **Zero telemetrie** : aucun tracking, aucun analytics
- **Stockage local** : sessions, extractions et profils dans le dossier `sessions/` (ignore par git)
- **Documents jamais copies** : les fichiers originaux ne sont pas dupliques, seules les extractions structurees sont conservees
- **Open source** : le code est auditable

## Licence

MIT
