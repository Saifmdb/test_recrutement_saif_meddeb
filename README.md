# Assistant d'admission pour prospects

Assistant conversationnel qui permet à un prospect de :

1. poser des questions sur la **procédure d'admission** (RAG sur le document `Procedure_admission`) ;
2. **rechercher des formations** dans la base « diplôme spécialité », sous forme de cartes ;
3. **déposer une demande d'inscription** (collecte, récapitulatif, confirmation, enregistrement « Nouvelle »,
   e-mail à l'équipe métier).

| Couche | Technologie |
|---|---|
| Frontend | Angular 21 (standalone components, signals) |
| Backend | Django 5.2 + Django REST Framework, SQLite |
| LLM | **Groq — `openai/gpt-oss-120b`** (appel d'outils / *tool calling*), ou **Ollama — `qwen3:4b`** en 100 % local |
| Embeddings / base vectorielle | Ollama `nomic-embed-text`, vecteurs stockés en base + similarité cosinus (NumPy) |

La documentation technique (architecture, choix, limites) est dans [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

---

## 1. Prérequis

- Python 3.11+
- Node.js 20+ et npm
- [Ollama](https://ollama.com) installé et lancé (embeddings du RAG, et chat si mode local)
- Une clé API **Groq** gratuite : https://console.groq.com/keys (mode par défaut)

```bash
ollama pull nomic-embed-text    # toujours nécessaire (recherche dans le document)
ollama pull qwen3:4b            # uniquement pour le mode 100 % local
```

**Choix du LLM** (dans `backend/.env`) :
- **Groq (défaut)** : `LLM_PROVIDER=openai` + `LLM_API_KEY=gsk_...`. Réponses en 2 à 5 s sur n'importe quel PC.
  Le plan gratuit limite les jetons par minute : en cas de dépassement, le backend attend et réessaie automatiquement.
- **Ollama local** : `LLM_PROVIDER=ollama`, `LLM_CHAT_MODEL=qwen3:4b`, `LLM_THINK=false`. Demande un GPU
  avec au moins ~6 Go de VRAM pour des réponses rapides.

## 2. Backend (Django REST)

```bash
cd backend
python -m venv .venv
# Windows : .venv\Scripts\activate      Linux/macOS : source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env                # puis adapter si besoin (modèle, e-mails...)
python manage.py migrate
python manage.py import_formations  # importe data/documents/diplôme spécialité.xlsx
python manage.py ingest_documents   # indexe Procedure_admission (PDF/DOCX/TXT) de data/documents/
python manage.py createsuperuser    # optionnel : accès au back-office /admin
python manage.py runserver          # http://localhost:8000
```

Les documents à indexer se placent dans `backend/data/documents/` (le fichier Excel y est aussi).
Relancer `ingest_documents` après toute modification du document de procédure.

## 3. Frontend (Angular)

```bash
cd front
npm install
npm start                           # http://localhost:4200  (proxy /api -> http://localhost:8000)
```

## 4. Configuration (`backend/.env`)

| Variable | Rôle | Défaut |
|---|---|---|
| `LLM_PROVIDER` | `openai` (Groq ou toute API compatible OpenAI) ou `ollama` (local) | `ollama` |
| `LLM_API_URL` / `LLM_API_KEY` | URL et clé de l'API (mode `openai`) | Groq / — |
| `LLM_CHAT_MODEL` | Modèle du chat | `qwen3:4b` (`.env.example` : `openai/gpt-oss-120b`) |
| `LLM_REASONING_EFFORT` | Effort de raisonnement des modèles gpt-oss (`low` = plus rapide) | — |
| `LLM_THINK` | Mode « réflexion » de qwen3 sur Ollama (`false` = plus rapide) | `false` |
| `LLM_EMBED_MODEL` | Modèle d'embeddings (Ollama) | `nomic-embed-text` |
| `LLM_NUM_CTX` | Fenêtre de contexte (Ollama) | `4096` |
| `ADMISSIONS_CONTACT_EMAIL` / `_PHONE` | Contact donné quand une réponse est introuvable | — |
| `ADMISSIONS_TEAM_EMAILS` | Destinataires de la notification (séparés par des virgules) | — |
| `EMAIL_MODE` | `file` (e-mails écrits dans `backend/sent_emails/`), `console` ou `smtp` | `file` |
| `EMAIL_HOST`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD` | SMTP (ex. Gmail + mot de passe d'application) | — |

## 5. Utilisation

- Chat : http://localhost:4200
- Back-office (demandes d'inscription, formations, conversations) : http://localhost:8000/admin
- État du service : http://localhost:8000/api/health/

### API

| Méthode | URL | Description |
|---|---|---|
| `POST` | `/api/chat/` | `{conversation_id?, message}` → réponse de l'assistant (`text`, `payload.cards`, `payload.recap`, `payload.sources`, `payload.confirmation`) |
| `GET` | `/api/chat/<id>/` | Historique d'une conversation |
| `GET` | `/api/formations/` | Catalogue des formations |
| `GET` | `/api/health/` | Disponibilité du LLM, nombre de formations et de passages indexés |

## 6. Tests

```bash
cd backend && python manage.py test admissions     # règles métier (sans LLM)
cd front && npx ng test --watch=false
```

## 7. Scénario de démonstration

1. « Quels documents dois-je fournir pour déposer une candidature ? » → réponse basée sur le document + sources.
2. « Quels sont les frais de scolarité ? » → si absent du document : l'assistant le signale et oriente vers le service des admissions.
3. « Quelles spécialités proposez-vous en informatique ? » → cartes de formations.
4. « J'ai un bac informatique, quelles spécialités me correspondent ? » → cartes, puis demande des informations manquantes pour l'éligibilité.
5. Bouton **S'inscrire** sur une carte → prénom, nom, e-mail, téléphone → récapitulatif → **Je confirme**.
6. Vérifier la demande dans `/admin` (statut « Nouvelle ») et l'e-mail dans `backend/sent_emails/`.
7. Refaire une inscription avec le même e-mail → doublon détecté, aucune nouvelle demande.
