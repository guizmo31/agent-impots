# Agent Impots

**Agent fiscal 100% local pour preparer sa declaration d'impots sur le revenu en France.**

> **Aucune donnee ne quitte votre ordinateur.** Le modele d'IA (Mistral-Nemo 12B) tourne localement via Ollama, vos documents restent sur votre disque, aucun appel reseau n'est effectue. Vos donnees fiscales ne transitent par aucun cloud, aucun serveur distant, aucune API externe.

---

## Avertissement

**Cet outil est un prototype experimental fourni a titre d'aide uniquement.** Il ne constitue en aucun cas un conseil fiscal, juridique ou comptable. Il ne remplace en aucun cas un conseiller fiscal professionnel, un expert-comptable ou l'administration fiscale.

- Les calculs et les numeros de cases sont des **estimations** basees sur les documents fournis et la base de connaissances fiscales integree.
- Des erreurs sont possibles, notamment sur les situations complexes (multi-societes, revenus etrangers, dispositifs speciaux).
- **Verifiez systematiquement chaque montant et chaque case** avec la legislation fiscale en vigueur avant de soumettre votre declaration officielle sur [impots.gouv.fr](https://www.impots.gouv.fr).
- En cas de doute, consultez un professionnel.
- **L'auteur decline toute responsabilite en cas d'erreur dans votre declaration.**

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

### Capacite de votre PC

Le modele par defaut (**Mistral-Nemo 12B**) necessite environ **10 Go de RAM libre**. Si votre PC n'a pas assez de memoire, l'agent sera tres lent ou ne fonctionnera pas.

**Si votre PC a moins de 12 Go de RAM**, basculez sur le modele de secours Mistral 7B (plus leger, ~5 Go de RAM) :

1. Verifiez que Mistral 7B est installe : `ollama list` (il est telecharge automatiquement par `setup.bat`)
2. Editez le fichier `backend/ollama_client.py`
3. Modifiez la liste `MODEL_PREFERENCES` en mettant `"mistral"` en premier :
   ```python
   MODEL_PREFERENCES = [
       "mistral",         # 7B, plus leger, fonctionne avec 8 Go de RAM
       "mistral-nemo",    # 12B, meilleur mais necessite plus de RAM
   ]
   ```
4. Relancez l'agent

> **Note** : Mistral 7B est moins precis que Mistral-Nemo 12B, notamment sur le francais et la generation de JSON structure. Les resultats peuvent contenir plus d'erreurs.

| Modele | RAM necessaire | Qualite | Vitesse |
|--------|---------------|---------|---------|
| **Mistral-Nemo 12B** (defaut) | ~10 Go | Bonne | ~15s par document |
| **Mistral 7B** (secours) | ~5 Go | Moyenne | ~8s par document |

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
Navigateur (http://localhost:8000)                         <- 100% local
    | WebSocket (+ messages de completion en temps reel)
    v
FastAPI (backend Python)                                   <- 100% local
    |
    |-- Etape 1 : INGESTION (0% -> 50% completion)
    |   |
    |   |-- 1a. Analyse rapide des noms de fichiers (instantane, sans LLM)
    |   |       -> Detection des types : salaires, immobilier, titres, SCPI...
    |   |       -> Generation de questions structurantes adaptees
    |   |
    |   |-- 1b. Conversion en Markdown (instantane, sans LLM)
    |   |       Chaque fichier (PDF, Excel, image, CSV, Word)
    |   |       -> Markdown structure et lisible (cache dans output/markdown/)
    |   |       -> Verifiable par l'utilisateur via la page /documents
    |   |
    |   |-- 1c. Extraction structuree par le LLM (sur le markdown, pas le fichier brut)
    |   |       1 appel LLM par document (ou batch de 3 pour les petits docs)
    |   |       -> JSON structure : type, montants, entite, confiance
    |   |       -> Sauvegarde immediate sur disque (survit a un crash)
    |   |
    |   '-- 1d. Construction du profil fiscal
    |           ExtractionStore (RAG local) -> FiscalProfile (JSON source de verite)
    |
    |   [En parallele : l'utilisateur repond aux questions structurantes]
    |
    |-- Etape 2 : VALIDATION (50% -> 75% completion)
    |   Profil analyse par le LLM -> detection des manques
    |   -> Questions ciblees (ne redemande pas ce qui est deja connu)
    |   -> Reponses structurees localement (pattern matching, LLM en fallback)
    |
    |-- Etape 3 : CALCUL (75% -> 95% completion)
    |   RAG fiscal (regles, bareme, 145 cases 2042) + profil JSON
    |   -> Le LLM recoit UNIQUEMENT le profil, jamais les documents bruts
    |   -> Cases 2042 avec montants et justifications
    |
    |-- Etape 4 : VERIFICATION (95% -> 100% completion)
    |   Cross-check automatique :
    |   - Dividendes SASU vs IS declare
    |   - Recettes meublees > 23k -> LMP pas LMNP
    |   - Revenu net <= revenu brut
    |   - Cases citees existent dans le referentiel
    |   -> Rapport HTML + PDF + page de status
    |
    v
Ollama (100% local)
    |-- Mistral-Nemo 12B (~7 Go) -- LLM principal (128K contexte, excellent en francais)
    |-- Mistral 7B (~4 Go) -- modele de secours (si RAM insuffisante)
    '-- nomic-embed-text (~270 Mo) -- embeddings pour les deux RAG locaux
```

**Trois pages web** (toutes locales) :
- **Agent** (`/`) : interface de chat avec barre de progression et pourcentage de completion
- **Documents** (`/documents`) : visualisation des markdowns generes (verification du contenu)
- **Reference fiscale** (`/reference`) : guide interactif des 145 cases 2042 avec exemples concrets

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
| Le modele est tres lent | Normal au premier lancement (chargement en RAM). Mistral-Nemo 12B necessite ~10 Go de RAM libre. Si trop lent, basculez sur Mistral 7B (voir section "Capacite de votre PC" ci-dessus) |
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

Agent : "32 documents trouves.
         Types detectes (analyse rapide) : salaires (12), immobilier (6), titres (4)...
         L'analyse approfondie demarre en arriere-plan."        <- 0%

Agent : "Question 1/5 : Quelle est votre situation familiale ?"
  Vous : Marie, 2 enfants                                       <- reponse instantanee

Agent : "Question 2/5 : Location nue ou meublee ?"
  Vous : Micro-foncier
         Analyse en arriere-plan : 18/32 documents...            <- 30%

   ... (questions et analyse en parallele)

Agent : "Analyse terminee. Profil fiscal construit."             <- 50%
Agent : "Il me manque 2 informations..."                         <- 60%
Agent : "Calcul fiscal en cours..."                              <- 85%

Agent : "Voici le resultat de votre declaration :"               <- 100%
         | Case | Libelle                   | Montant   |
         |------|---------------------------|-----------|
         | 1AJ  | Salaires declarant 1      | 48 000 EUR|
         | 4BE  | Revenus fonciers micro     | 12 000 EUR|
         | ...  | ...                       | ...       |

Agent : [Telecharger le PDF] [Voir en HTML]
```

### Memoire persistante et interruption

L'agent sauvegarde votre progression **localement** a chaque etape :

- **Bouton "Interrompre ma session"** : sauvegarde l'etat complet (documents deja analyses, profil fiscal, reponses aux questions) puis revient a l'ecran d'accueil. Vous pouvez interrompre a tout moment, y compris en plein milieu de l'analyse des documents.
- **Reprise automatique** : quand vous revenez sur votre session, l'agent detecte les documents deja analyses et reprend exactement ou vous en etiez, sans rien re-traiter.
- **Pourcentage de completion** : visible sur l'ecran d'accueil et dans le header pendant la session, il indique la progression globale de 0% a 100%.
- **Crash/fermeture du navigateur** : chaque extraction est sauvegardee sur disque immediatement. Rien n'est perdu.

### Formats de documents supportes

Chaque document est d'abord converti en **Markdown structure** (verifiable sur la page `/documents`) avant d'etre envoye au LLM.

| Format | Extension | Methode de conversion |
|--------|-----------|----------------------|
| PDF texte | `.pdf` | PyMuPDF -> Markdown avec pages, montants en gras |
| PDF scanne | `.pdf` | PyMuPDF + OCR Tesseract -> Markdown |
| Images | `.png` `.jpg` `.jpeg` `.tiff` `.bmp` | OCR Tesseract -> Markdown |
| Excel | `.xlsx` `.xls` | openpyxl -> tableaux Markdown |
| CSV | `.csv` | csv -> tableaux Markdown (detection auto separateur) |
| Word | `.docx` | python-docx -> Markdown avec headings |
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
|   |-- ollama_client.py            <- Client Ollama (detection auto du meilleur modele)
|   |-- markdown_converter.py       <- Conversion universelle -> Markdown
|   |-- extractors.py               <- Extracteur universel de donnees fiscales
|   |-- extraction_store.py         <- RAG local des extractions du contribuable
|   |-- fiscal_profile.py           <- Profil fiscal JSON (source de verite)
|   |-- rag.py                      <- RAG fiscal (regles, cases, bareme)
|   |-- sanitizer.py                <- Protection anti-prompt-injection
|   |-- document_parser.py          <- Parsing multi-format + OCR (fallback)
|   |-- fiscal_engine.py            <- Moteur de calcul fiscal (bareme IR)
|   |-- report_generator.py         <- Generation rapport HTML + PDF
|   |-- status_page.py              <- Page de status HTML temps reel
|   |-- reference_page.py           <- Page de reference des 145 cases 2042
|   '-- session_store.py            <- Memoire persistante des sessions
|-- frontend/
|   |-- index.html                  <- Interface de chat (layout 2 colonnes)
|   |-- css/style.css
|   '-- js/app.js
|-- data/
|   |-- cases_2042_2026.json        <- ~145 cases fiscales documentees
|   '-- regles_fiscales.md          <- Regles fiscales detaillees (20 sections)
|-- sessions/                       <- Donnees des sessions (local, ignore par git)
|-- documents/                      <- Vos documents (local, ignore par git)
'-- output/                         <- Rapports et markdowns generes (local, ignore par git)
```

## Mise a jour de la base fiscale

Les connaissances fiscales sont dans `data/`. Pour mettre a jour quand un nouveau bareme ou formulaire est publie :

1. Modifier `data/cases_2042_2026.json` -- cases, seuils, taux
2. Modifier `data/regles_fiscales.md` -- regles, explications
3. Ajouter des fichiers `.md` ou `.txt` dans `data/` -- indexes automatiquement par le RAG local
4. Supprimer `data/.cache/` pour forcer la regeneration des embeddings locaux

## Configuration materielle recommandee

| Composant | Minimum (Mistral 7B) | Recommande (Mistral-Nemo 12B) |
|-----------|---------------------|-------------------------------|
| RAM | 8 Go | 16 Go+ |
| Stockage | 10 Go libres | 20 Go libres |
| CPU | Tout CPU x64 recent | AMD Ryzen / Intel i5+ |
| GPU | Non requis | Accelere Ollama si compatible |

L'agent tourne integralement sur CPU. Teste sur : GEEKOM A9 Max (AMD Ryzen 9, 28 Go RAM) sous Windows 11.

---

## Vie privee et securite

- **Zero cloud** : aucune donnee n'est envoyee sur internet
- **Zero telemetrie** : aucun tracking, aucun analytics
- **Stockage local** : sessions, extractions et profils dans le dossier `sessions/` (ignore par git)
- **Documents convertis en Markdown** : verifiables par l'utilisateur sur la page `/documents`
- **Anti-prompt-injection** : sanitizer integre qui detecte et neutralise les tentatives d'injection dans les documents
- **CODEOWNERS** : toute modification des fichiers sensibles (prompts, securite, donnees fiscales) requiert une review
- **Open source** : le code est auditable

## Licence

MIT
