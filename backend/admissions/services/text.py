"""Small text helpers shared by search, NLU and RAG (accent-insensitive French matching)."""

import re
import unicodedata

STOPWORDS = {
    "a", "au", "aux", "avec", "ce", "ces", "cette", "dans", "de", "des", "du", "en", "et", "est",
    "il", "je", "j", "l", "la", "le", "les", "leur", "lui", "ma", "mais", "me", "mes", "moi", "mon",
    "ne", "ni", "nos", "notre", "nous", "on", "ou", "par", "pas", "pour", "qu", "que", "quel",
    "quelle", "quelles", "quels", "qui", "sa", "se", "ses", "son", "sur", "ta", "te", "tes", "toi",
    "ton", "tu", "un", "une", "vos", "votre", "vous", "y", "d", "s", "n", "c", "m", "t", "ai", "as",
    "avez", "avons", "ont", "suis", "es", "sont", "etre", "avoir", "fait", "faire", "peux", "peut",
    "puis", "veux", "voudrais", "souhaite", "aimerais", "comment", "combien", "quoi", "est-ce",
    "proposez", "propose", "proposer", "offrez", "existe", "il y a", "svp", "merci", "bonjour",
    "formation", "formations", "specialite", "specialites", "filiere", "filieres", "cursus",
    "correspondent", "correspond", "correspondant", "me", "moi", "quelles", "quels", "disponibles",
    "plus", "tres", "tout", "tous", "toutes", "etudier", "etudes", "faire", "dois", "doit",
}


def strip_accents(value: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", value) if unicodedata.category(c) != "Mn")


def normalize(value: str) -> str:
    value = strip_accents(str(value or "")).lower()
    value = re.sub(r"[’'`]", " ", value)
    value = re.sub(r"[^a-z0-9+@.\- ]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def tokens(value: str, keep_stopwords: bool = False) -> list[str]:
    toks = re.findall(r"[a-z0-9+]+", normalize(value))
    if keep_stopwords:
        return toks
    return [t for t in toks if t not in STOPWORDS and len(t) > 1]


def stem(token: str) -> str:
    """Very light French stemmer: enough to match 'informatiques' with 'informatique'."""
    for suffix in ("ations", "ation", "iques", "ique", "ments", "ment", "eurs", "euse", "eur", "es", "s", "e"):
        if token.endswith(suffix) and len(token) - len(suffix) >= 4:
            return token[: -len(suffix)]
    return token
