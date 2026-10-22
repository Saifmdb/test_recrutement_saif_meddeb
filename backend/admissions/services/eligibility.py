"""Deterministic eligibility check (the LLM never decides eligibility on its own).

Each formation of the Excel file has 3 criteria: required level, nationality, type of bac.
The prospect's answers are compared to them in code; a criterion that is required but unknown is
reported as "manquant" (to ask), never as satisfied.
"""

import re

from .text import normalize

# Education levels, from lowest to highest
LEVELS = {
    0: "inférieur à la 9ème année",
    1: "9ème année de base",
    2: "2ème année secondaire réussie (ou CAP)",
    3: "3ème année secondaire",
    4: "4ème année secondaire (sans bac)",
    5: "Baccalauréat (ou BTP)",
    6: "Bac+2 / BTS",
    7: "Licence (Bac+3)",
    8: "Licence + 1 an (Bac+4)",
    9: "Bac+5 (Master / Ingénieur)",
}

BAC_SECTIONS = {
    "mathematiques": r"\bmath",
    "sciences_experimentales": r"exp[ée]rimental|sciences? exp|\bsc\.? exp",
    "sciences_techniques": r"technique|sciences? tech",
    "informatique": r"\binfo",
    "economie_gestion": r"[ée]co|gestion",
    "lettres": r"lettre",
    "sport": r"sport",
}


def required_level(raw: str) -> int:
    """'bac ou BTP dans le même secteur' -> 5 ; 'All' -> 0 (no requirement)."""
    t = normalize(raw)
    if not t or t == "all":
        return 0
    if "approfondissement" in t or re.search(r"licence\s*\+\s*1", t):
        return 8
    if "licence" in t:
        return 7
    if re.search(r"bac\s*\+\s*2|\bbts\b", t):
        return 6
    if re.search(r"\bbac\b", t):
        return 5
    if re.search(r"\b4\s*(eme|e)\b", t):
        return 4
    if re.search(r"\b2\s*(eme|e)\b", t):
        return 2
    if re.search(r"\b9\s*(eme|e)\b", t):
        return 1
    return 0


def prospect_level(raw: str) -> int | None:
    """Free text ('bac', 'bac+2', 'BTS', 'licence', '4ème année'...) -> level rank, or None."""
    t = normalize(raw)
    if not t:
        return None
    patterns = [
        (9, r"bac\s*\+\s*5|\bmaster\b(?!\s*1)|\bm2\b|ingenieur|doctorat"),
        (8, r"bac\s*\+\s*4|master\s*1|\bm1\b|maitrise|licence\s*\+\s*1"),
        (7, r"bac\s*\+\s*3|licence|\bl3\b|bachelor"),
        (6, r"bac\s*\+\s*2|\bbts\b|\bdut\b|\bl2\b"),
        (5, r"bac\s*\+\s*1|\bl1\b|\bbtp\b"),
        (4, r"4\s*(eme|e)|terminale|sans (le )?bac|pas (le |de )?bac|niveau bac"),
        (5, r"\bbac\b|baccalaureat|bachelier"),
        (3, r"3\s*(eme|e)"),
        (2, r"2\s*(eme|e)|\bcap\b"),
        (1, r"1\s*(ere|er)\s*(annee)?\s*secondaire|9\s*(eme|e)"),
    ]
    for rank, pattern in patterns:
        if re.search(pattern, t):
            return rank
    return None


def bac_sections(raw: str) -> list[str]:
    t = normalize(raw)
    return [key for key, pattern in BAC_SECTIONS.items() if re.search(pattern, t)]


def is_tunisian(raw: str) -> bool | None:
    t = normalize(raw)
    if not t:
        return None
    if re.search(r"\bnon\b|\bpas\b|autre|etranger", t):
        return False
    return "tunisi" in t


def evaluate(formation, profile: dict) -> dict:
    """Compare the profile {niveau, nationalite, bac} with the formation's criteria."""
    details, missing = [], []

    # 1. Level
    req = required_level(formation.niveau_requis)
    if req == 0:
        details.append({"critere": "niveau", "requis": "aucun", "statut": "ok"})
    elif not profile.get("niveau"):
        details.append({"critere": "niveau", "requis": formation.niveau_requis, "statut": "manquant"})
        missing.append("niveau d'études actuel")
    else:
        rank = prospect_level(profile["niveau"])
        if rank is None:
            details.append({"critere": "niveau", "requis": formation.niveau_requis, "statut": "manquant"})
            missing.append("niveau d'études actuel (précisez : bac, bac+2, licence...)")
        else:
            details.append({"critere": "niveau", "requis": formation.niveau_requis, "prospect": LEVELS[rank],
                            "statut": "ok" if rank >= req else "non_rempli"})

    # 2. Nationality
    if normalize(formation.nationalite_requise) in ("", "all"):
        details.append({"critere": "nationalité", "requis": "toutes", "statut": "ok"})
    elif not profile.get("nationalite"):
        details.append({"critere": "nationalité", "requis": formation.nationalite_requise, "statut": "manquant"})
        missing.append("nationalité")
    else:
        ok = is_tunisian(profile["nationalite"])
        details.append({"critere": "nationalité", "requis": formation.nationalite_requise,
                        "prospect": profile["nationalite"], "statut": "ok" if ok else "non_rempli"})

    # 3. Type of bac
    bac_req = normalize(formation.bac_requis)
    if bac_req in ("", "all") or "san" in bac_req:
        details.append({"critere": "bac", "requis": "toutes sections / bac non exigé", "statut": "ok"})
    elif not profile.get("bac"):
        details.append({"critere": "bac", "requis": formation.bac_requis.strip(), "statut": "manquant"})
        missing.append("section du baccalauréat")
    elif not bac_sections(profile["bac"]):
        # e.g. "bac science": could be sciences expérimentales or sciences techniques -> ask, don't guess
        details.append({"critere": "bac", "requis": formation.bac_requis.strip(), "prospect": profile["bac"],
                        "statut": "manquant"})
        missing.append("section du baccalauréat")
    else:
        ok = bool(set(bac_sections(profile["bac"])) & set(bac_sections(formation.bac_requis)))
        details.append({"critere": "bac", "requis": formation.bac_requis.strip(), "prospect": profile["bac"],
                        "statut": "ok" if ok else "non_rempli"})

    statuses = {d["statut"] for d in details}
    if "non_rempli" in statuses:
        statut = "criteres_non_remplis"
    elif "manquant" in statuses:
        statut = "informations_manquantes"
    else:
        statut = "criteres_remplis"
    return {"statut": statut, "details": details, "informations_manquantes": missing}
