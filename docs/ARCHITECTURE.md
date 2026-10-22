# Documentation technique

## 1. Vue d'ensemble

```
┌──────────────────────┐   POST /api/chat/   ┌───────────────────────────────────────────────┐
│  Angular (front/)    │ ──────────────────► │  Django REST (backend/)                       │
│  - fil de discussion │ ◄────────────────── │                                               │
│  - cartes formations │  texte + cartes +   │  ChatView ──► agent.run()                     │
│  - récapitulatif     │  récap + sources    │                 │                             │
└──────────────────────┘                     │                 ▼                             │
                                             │  LLM Groq / Ollama (prompt système = règles)  │
                                             │                 │ appels d'outils             │
                                             │   ┌─────────────┼──────────────┬───────────┐  │
                                             │   ▼             ▼              ▼           ▼  │
                                             │ rechercher_  rechercher_  preparer_   confirmer_
                                             │ procedure    formations   inscription inscription
                                             │   │ (RAG)       │ (Excel→DB)    │           │  │
                                             │   ▼             ▼               ▼           ▼  │
                                             │ DocumentChunk Formation    état conv.  Candidature
                                             │ (embeddings)                           + e-mail │
                                             └───────────────────────────────────────────────┘
```

## 2. Choix techniques

### LLM : appel d'outils, fournisseur interchangeable
- Le comportement est décrit dans un **prompt système** (`services/agent.py`) qui reprend les règles du sujet :
  réponses fondées sur le document uniquement, ne pas confondre recherche et éligibilité, confirmation explicite,
  pas de doublon, ne jamais garantir l'admission.
- Le modèle choisit lui-même l'outil à appeler (pas de détection par mots-clés).
- `services/llm.py` parle à deux types de fournisseurs, choisis par `LLM_PROVIDER` :
  - **Groq** (ou toute API compatible OpenAI) avec `openai/gpt-oss-120b` : réponses en 2 à 5 s, appel d'outils
    fiable. Le plan gratuit limite les jetons par minute : le client attend le délai indiqué (HTTP 429) puis réessaie,
    et les résultats d'outils des tours précédents sont abrégés pour consommer moins de jetons.
  - **Ollama** en local (`qwen3:4b`, mode « réflexion » désactivé) : aucune donnée ne sort de la machine.
- **Choix mesuré pendant le développement** (GTX 1650, 4 Go de VRAM, 8 Go de RAM) :
  - `qwen2.5:3b` : rapide, mais appel d'outils peu fiable (il réutilise d'anciens résultats ou invente des formations) ;
  - `qwen2.5:7b` et `qwen3:4b` (contexte 8k) ne tiennent pas entièrement en VRAM : plus d'une minute par réponse ;
  - d'où Groq par défaut, le mode local restant disponible sur une machine mieux équipée.

### Outils exposés au modèle (`services/tools.py`)
| Outil | Rôle |
|---|---|
| `rechercher_procedure(question)` | RAG : renvoie les passages pertinents du document `Procedure_admission` (ou « aucune information ») |
| `rechercher_formations(specialite?, diplome?, ecole?, niveau?)` | Recherche dans le catalogue (avec `niveau`, seules les formations accessibles sont gardées) ; résultats affichés en cartes |
| `verifier_eligibilite(specialite, diplome?, ecole?, niveau?, nationalite?, bac?)` | Compare le profil du prospect aux critères de la formation **dans le code** : critère rempli / non rempli / information manquante à demander |
| `preparer_inscription(prenom, nom, email, telephone, specialite, diplome?, ecole?)` | Identifie la formation dans la base, valide les données, vérifie les doublons, affiche le récapitulatif |
| `confirmer_inscription()` | Enregistre la demande « Nouvelle », notifie l'équipe et le prospect |

### Garde-fous dans le code (indépendants du LLM)
Le LLM pilote le dialogue, mais les règles critiques sont vérifiées par le code, car un modèle peut se tromper :
- **Formation existante et non ambiguë** : le LLM décrit la formation avec les mots du prospect (spécialité,
  diplôme, école) et c'est le code qui la cherche en base : 0 résultat → refus ; plusieurs → cartes de choix et
  demande de précision ; 1 seul → récapitulatif. Le modèle ne peut donc pas choisir un identifiant au hasard.
- **Éligibilité calculée par le code** (`services/eligibility.py`) : niveaux ordonnés (9ème → 2ème secondaire/CAP →
  4ème → bac/BTP → Bac+2/BTS → Licence → Licence+1 → Bac+5), nationalité (« All » ou « Tunisienne »), section du
  bac (« All », « san bac » ou liste de sections). Un critère exigé mais inconnu est « manquant » : le modèle reçoit la
  consigne de poser uniquement ces questions, sans conclure. Le profil (niveau, nationalité, bac) est mémorisé pour
  toute la conversation.
- **Jamais de garantie** : toute formulation du type « vous êtes éligible / admis » est remplacée par
  « vous semblez remplir les critères » et le rappel « La décision finale appartient à l'équipe admissions » est ajouté.
- **Données valides** : e-mail (validateur Django), téléphone normalisé (8 chiffres tunisiens → `+216…`, ou international), nom/prénom.
- **Confirmation explicite** : `confirmer_inscription` n'enregistre que si un récapitulatif a été préparé lors d'un
  tour **précédent** ; le prospect a donc forcément vu le récapitulatif et répondu.
- **Doublons** : vérifiés avant le récapitulatif, au moment de l'enregistrement, et garantis par des contraintes
  `unique` en base sur l'e-mail et le téléphone normalisé.

### RAG (`services/rag.py`)
- Extraction du texte (PDF via `pypdf`, DOCX via `python-docx`, TXT/MD), découpage en passages d'environ 800 caractères
  en respectant les paragraphes.
- Embeddings `nomic-embed-text` (Ollama), stockés en base (`DocumentChunk.embedding`).
- Recherche : similarité cosinus (NumPy) + petit bonus lexical, seuil minimal (`RAG_MIN_SCORE`) : en dessous, l'outil
  renvoie « aucune information » et le modèle oriente vers le service des admissions.
- **Base vectorielle** : pour un document de quelques pages, une table + NumPy suffit (aucune dépendance, résultats
  instantanés). Pour un corpus plus important : pgvector, Chroma ou FAISS.

### Données formations
- `python manage.py import_formations` lit le fichier Excel `diplôme spécialité.xlsx` et remplit la table `Formation`
  (diplôme, spécialité, école, niveau, nationalité, nature du bac).
- La recherche est insensible aux accents et à la casse, avec quelques synonymes de domaine (ex. « informatique » couvre
  aussi réseaux, développement web, programmation...) et des alias de diplômes (BTS, BTP, CAP...).
- Les critères d'éligibilité (« All » = pas de restriction, « san bac » = bac non exigé) sont transmis au modèle,
  qui les compare au profil donné par le prospect et demande les informations manquantes.

### Notification
- E-mail texte + HTML à l'équipe métier (`ADMISSIONS_TEAM_EMAILS`) et e-mail de confirmation au prospect.
- `EMAIL_MODE=file` pour la démo (fichiers dans `backend/sent_emails/`), `smtp` en production.
- Si l'envoi échoue, la demande reste enregistrée et `notification_envoyee=False` est visible dans le back-office,
  avec une action « Renvoyer la notification ».

### Frontend
- Angular 21, composants standalone, *signals* (`input()` / `output()`), page du chat chargée en *lazy loading*.

```
src/app/
├── core/          chat.models.ts (types), chat.service.ts (appels API + état du chat)
├── shared/        format-text.pipe.ts (mini-Markdown sécurisé)
└── chat/          chat.component            page : assemble les composants
    └── components/
        ├── chat-header        titre + « Nouvelle conversation »
        ├── welcome-message    message d'accueil + suggestions
        ├── message            un message (texte + cartes + récap + sources)
        ├── formation-card     carte formation (critères, « S'inscrire », « Mon éligibilité »)
        ├── recap-card         récapitulatif d'inscription (« Je confirme » / « Modifier »)
        ├── sources-list       extraits du document utilisés par le RAG
        ├── typing-indicator   indicateur « l'assistant écrit »
        └── chat-input         zone de saisie
```
- Les composants de présentation ne connaissent pas l'API : ils reçoivent des `input()` et émettent des `output()` ;
  seul `ChatComponent` utilise `ChatService`.
- Rendu des cartes de formations, du récapitulatif (boutons « Je confirme » / « Modifier »), de la confirmation et des
  sources du RAG.
- Conversation conservée côté serveur ; l'identifiant est gardé dans `localStorage` pour restaurer le fil après un
  rechargement.
- Le texte de l'assistant est échappé avant affichage (mini-Markdown sûr : gras, listes).

## 3. Modèle de données

- `Formation` : une ligne du fichier Excel.
- `Conversation` : historique envoyé au LLM (avec les appels d'outils) + récapitulatif en attente.
- `Message` : messages affichés dans le chat (texte + cartes / récap / sources).
- `Candidature` : demande d'inscription (statut « Nouvelle » par défaut), e-mail et téléphone uniques.
- `DocumentChunk` : passages indexés du document de procédure avec leurs embeddings.

## 4. Limites

- **Dépendance au fournisseur LLM** : en mode Groq, les messages des prospects transitent par une API externe, et le
  plan gratuit limite les jetons par minute (attente de quelques secondes si plusieurs messages s'enchaînent).
- **Mode local** : un LLM de 4 à 7 milliards de paramètres demande un GPU d'au moins ~6 Go de VRAM pour répondre vite.
- **Éligibilité** : le pré-contrôle repose sur les critères du fichier Excel ; « dans le même secteur » (CAP/BTP) n'est
  pas vérifiable automatiquement. Il reste indicatif : la décision appartient à l'équipe admissions.
- Données Excel hétérogènes (ex. certains BTS d'IMSET SOUSSE avec le niveau « 2ème année » ; doublons
  « Décoration et design d'intérieur » / « BTS-Décoration... ») : affichées telles quelles.
- Pas d'authentification du prospect ; une seule demande par e-mail / téléphone.
- Réponses non diffusées en *streaming* (la réponse s'affiche en une fois).

## 5. Améliorations possibles

- Streaming des réponses (SSE) pour une meilleure réactivité.
- Évaluation automatique du chatbot (jeu de questions/réponses de référence) pour comparer les modèles.
- Base vectorielle dédiée (pgvector) + reranking pour un corpus plus large.
- File de tâches (Celery) pour les e-mails, avec relances automatiques.
- Gestion du statut des demandes par l'équipe (workflow, tableau de bord) et envoi d'un lien de suivi au prospect.
- Déploiement Docker Compose (backend, frontend, Ollama).
