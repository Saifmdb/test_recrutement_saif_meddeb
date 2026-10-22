# Documentation technique

## 1. Vue d'ensemble

```
┌──────────────────────┐   POST /api/chat/   ┌───────────────────────────────────────────────┐
│  Angular (front/)    │ ──────────────────► │  Django REST (backend/)                       │
│  - fil de discussion │ ◄────────────────── │                                               │
│  - cartes formations │  texte + cartes +   │  ChatView ──► agent.run()                     │
│  - récapitulatif     │  récap + sources    │                 │                             │
└──────────────────────┘                     │                 ▼                             │
                                             │  LLM Ollama gemma4:e4b (prompt = règles)      │
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

### LLM : Gemma 4 E4B en local (Ollama), appel d'outils
- Le comportement est décrit dans un **prompt système** (`services/agent.py`) qui reprend les règles du sujet :
  réponses fondées sur le document uniquement, ne pas confondre recherche et éligibilité, confirmation explicite,
  pas de doublon, ne jamais garantir l'admission.
- Le modèle choisit lui-même l'outil à appeler (pas de détection par mots-clés).
- `services/llm.py` appelle **Ollama** en local avec **Gemma 4 E4B** (`gemma4:e4b`, mode « réflexion » désactivé) :
  appel d'outils natif, bon français, et aucune donnée ne sort de la machine. Les embeddings du RAG utilisent
  `nomic-embed-text`, aussi via Ollama.
- Les résultats d'outils des tours précédents sont abrégés dans l'historique envoyé au modèle : moins de jetons,
  réponses plus rapides.

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
  tour **précédent** ; le prospect a donc forcément vu le récapitulatif et répondu. Son message doit en plus être
  une confirmation explicite (« oui », « je confirme »…) sans demande de modification (« non », « faux »,
  « changer »…) : vérifié par le code, même si le modèle appelle l'outil à tort.
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

- **Matériel** : Gemma 4 E4B tourne en local ; avec moins de ~8 Go de VRAM, une partie du modèle passe sur le CPU
  et les réponses sont nettement plus lentes. Un petit modèle peut aussi se tromper d'outil : les règles critiques
  restent vérifiées par le code (voir garde-fous).
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
