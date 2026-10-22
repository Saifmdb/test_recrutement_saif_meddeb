from pathlib import Path
import os

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def env(name, default=None):
    return os.environ.get(name, default)


def env_bool(name, default=False):
    return str(env(name, str(default))).strip().lower() in {"1", "true", "yes", "on"}


def env_list(name, default=""):
    return [v.strip() for v in str(env(name, default)).split(",") if v.strip()]


SECRET_KEY = env("DJANGO_SECRET_KEY", "dev-insecure-secret-key-change-me")
DEBUG = env_bool("DJANGO_DEBUG", True)
ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "corsheaders",
    "admissions",
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "fr-fr"
TIME_ZONE = "Africa/Tunis"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- REST / CORS -------------------------------------------------------------
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.AllowAny"],
    "DEFAULT_THROTTLE_CLASSES": ["rest_framework.throttling.AnonRateThrottle"],
    "DEFAULT_THROTTLE_RATES": {"anon": "120/min"},
    "UNAUTHENTICATED_USER": None,
}
CORS_ALLOWED_ORIGINS = env_list("CORS_ALLOWED_ORIGINS", "http://localhost:4200")

# --- LLM ---------------------------------------------------------------------
# "ollama" (local) or "openai" (any OpenAI-compatible API: Groq, OpenAI, Mistral...)
LLM_PROVIDER = env("LLM_PROVIDER", "ollama").strip().lower()
LLM_API_URL = env("LLM_API_URL", "https://api.groq.com/openai/v1").rstrip("/")
LLM_API_KEY = env("LLM_API_KEY", "")
# Reasoning models via API (e.g. gpt-oss on Groq): "low" = faster, shorter answers. Empty = not sent.
LLM_REASONING_EFFORT = env("LLM_REASONING_EFFORT", "").strip()
OLLAMA_URL = env("OLLAMA_URL", "http://localhost:11434").rstrip("/")
LLM_CHAT_MODEL = env("LLM_CHAT_MODEL", "qwen3:4b")
# Reasoning mode of "thinking" models (qwen3): False = faster answers. Empty = not sent (models without it).
LLM_THINK = {"true": True, "false": False}.get(env("LLM_THINK", "false").strip().lower())
LLM_EMBED_MODEL = env("LLM_EMBED_MODEL", "nomic-embed-text")
LLM_NUM_CTX = int(env("LLM_NUM_CTX", "4096"))  # 4096 keeps qwen3:4b entirely in 4 GB of VRAM
LLM_TIMEOUT = float(env("LLM_TIMEOUT", "300"))

# --- RAG ---------------------------------------------------------------------
DOCUMENTS_DIR = BASE_DIR / "data" / "documents"
FORMATIONS_FILE = BASE_DIR / "data" / "documents" / "diplôme spécialité.xlsx"
AGENT_MAX_HISTORY = int(env("AGENT_MAX_HISTORY", "30"))
RAG_TOP_K = int(env("RAG_TOP_K", "4"))
RAG_MIN_SCORE = float(env("RAG_MIN_SCORE", "0.35"))

# --- Admissions --------------------------------------------------------------
ADMISSIONS_CONTACT_EMAIL = env("ADMISSIONS_CONTACT_EMAIL", "")
ADMISSIONS_CONTACT_PHONE = env("ADMISSIONS_CONTACT_PHONE", "")
ADMISSIONS_TEAM_EMAILS = env_list("ADMISSIONS_TEAM_EMAILS", "equipe.admissions@example.com")
SEND_PROSPECT_CONFIRMATION_EMAIL = env_bool("SEND_PROSPECT_CONFIRMATION_EMAIL", True)

# --- E-mail ------------------------------------------------------------------
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", "Assistant Admissions <no-reply@example.com>")
EMAIL_MODE = env("EMAIL_MODE", "file").lower()
if EMAIL_MODE == "smtp":
    EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
    EMAIL_HOST = env("EMAIL_HOST", "smtp.gmail.com")
    EMAIL_PORT = int(env("EMAIL_PORT", "587"))
    EMAIL_USE_TLS = env_bool("EMAIL_USE_TLS", True)
    EMAIL_HOST_USER = env("EMAIL_HOST_USER", "")
    EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD", "")
elif EMAIL_MODE == "console":
    EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
else:
    EMAIL_BACKEND = "django.core.mail.backends.filebased.EmailBackend"
    EMAIL_FILE_PATH = BASE_DIR / "sent_emails"

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "loggers": {"admissions": {"handlers": ["console"], "level": "INFO"}},
}
