import re

from django.core.exceptions import ValidationError
from django.core.validators import validate_email as dj_validate_email

NAME_RE = re.compile(r"^[A-Za-zÀ-ÖØ-öø-ÿ]+(?:[ '\-][A-Za-zÀ-ÖØ-öø-ÿ]+)*$")


def clean_name(value: str) -> str | None:
    value = re.sub(r"\s+", " ", str(value or "")).strip(" .,;")
    if not (2 <= len(value) <= 60) or not NAME_RE.match(value):
        return None
    return " ".join(w[:1].upper() + w[1:].lower() if w.islower() or w.isupper() else w for w in value.split(" "))


def clean_email(value: str) -> str | None:
    value = str(value or "").strip().strip(".").lower()
    try:
        dj_validate_email(value)
    except ValidationError:
        return None
    return value


def normalize_phone(value: str) -> str | None:
    """Return an E.164-like number (+21612345678) or None. 8 digits alone = Tunisian number."""
    raw = re.sub(r"[\s.\-()/]", "", str(value or ""))
    if raw.startswith("00"):
        raw = "+" + raw[2:]
    if not re.fullmatch(r"\+?\d+", raw):
        return None
    digits = raw.lstrip("+")
    if not raw.startswith("+"):
        if len(digits) == 8 and digits[0] in "2345679":
            return "+216" + digits
        if len(digits) == 11 and digits.startswith("216"):
            raw = "+" + digits
        else:
            return None
    digits = raw[1:]
    if digits.startswith("216"):
        return raw if len(digits) == 11 and digits[3] in "2345679" else None
    return raw if 8 <= len(digits) <= 15 else None
