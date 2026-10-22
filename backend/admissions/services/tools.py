"""Tools the LLM can call. Each returns a JSON-serialisable dict.

The LLM drives the conversation; these functions only access data and enforce the hard rules
that must never depend on the model: existing formation, valid contact details, no duplicates,
and no registration without a recap shown first and confirmed in a later message.
"""

import re

from django.db import IntegrityError, transaction
from django.db.models import Q

from ..models import Candidature, Formation
from . import eligibility, llm, notifications, rag
from .text import normalize, stem, tokens
from .validators import clean_email, clean_name, normalize_phone

MAX_RESULTS = 8
FINAL_DECISION = "La décision finale appartient à l'équipe admissions."

DIPLOMA_ALIASES = {
    "bts": "technicien superieur",
    "btp": "technicien professionnel",
    "cap": "aptitude professionnelle",
    "ingenieur": "ingenieur",
    "licence": "licence",
    "bachelor": "bachelor",
    "rncp": "concepteur",
}
# A domain word also matches the specialties that belong to it
SYNONYMS = {
    "informatique": ["informati", "reseau", "developpement", "programmeur", "internet", "web", "logiciel", "infographie"],
    "gestion": ["gestion", "comptab", "financ"],
    "comptabilite": ["comptab", "financ"],
    "commerce": ["commerc", "distribution", "vente", "vendeur"],
    "sante": ["bio", "pharmac", "laboratoire", "prothese", "dentaire"],
    "design": ["decoration", "design", "infographie", "video"],
    "industrie": ["maintenance", "climatisation", "froid", "electroni", "industri", "qualite"],
}


# ---------------------------------------------------------------------------
# Schemas given to the LLM
# ---------------------------------------------------------------------------
SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "rechercher_procedure",
            "description": "Cherche dans le document officiel « Procedure_admission » (étapes, pièces justificatives, "
                           "conditions générales, dates limites, frais). À utiliser pour TOUTE question sur la procédure.",
            "parameters": {
                "type": "object",
                "properties": {"question": {"type": "string", "description": "La question du prospect, reformulée"}},
                "required": ["question"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "rechercher_formations",
            "description": "Cherche des formations dans la base « diplôme spécialité ». Tous les paramètres sont "
                           "optionnels ; renseigne seulement ceux que le prospect a indiqués.",
            "parameters": {
                "type": "object",
                "properties": {
                    "specialite": {"type": "string", "description": "Domaine ou spécialité, ex : informatique, comptabilité, réseaux"},
                    "diplome": {"type": "string", "description": "Uniquement si le prospect nomme le diplôme qu'il VEUT préparer : "
                                "BTS, BTP, CAP, Licence, Ingénieur, Bachelor. Laisser vide sinon. "
                                "« bac » n'est PAS « Bachelor »."},
                    "ecole": {"type": "string", "description": "Ville de l'école : Tunis, Sousse, Sfax, Nabeul, Gabès"},
                    "niveau": {"type": "string", "description": "Niveau d'études ACTUEL du prospect s'il l'a donné "
                               "(ex : bac, bac+2, 4ème année) : seules les formations accessibles à ce niveau sont gardées"},
                    "nationalite": {"type": "string", "description": "Nationalité du prospect s'il l'a donnée"},
                    "bac": {"type": "string", "description": "Section du bac du prospect s'il l'a donnée (ex : lettres, mathématiques)"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "verifier_eligibilite",
            "description": "Vérifie l'éligibilité du prospect à une formation en comparant son profil aux critères de "
                           "la base (niveau, nationalité, bac). À appeler dès que le prospect demande s'il est "
                           "éligible / s'il peut accéder à une formation, ou donne son niveau, sa nationalité ou son "
                           "bac pour une formation donnée. Ne renseigne que les informations données par le prospect.",
            "parameters": {
                "type": "object",
                "properties": {
                    "specialite": {"type": "string", "description": "Spécialité de la formation visée"},
                    "diplome": {"type": "string", "description": "Diplôme de la formation visée, ex : BTS, Licence"},
                    "ecole": {"type": "string", "description": "Ville de l'école si connue"},
                    "niveau": {"type": "string", "description": "Niveau d'études actuel du prospect (ex : bac, bac+2)"},
                    "nationalite": {"type": "string", "description": "Nationalité du prospect"},
                    "bac": {"type": "string", "description": "Section du bac du prospect (ex : sciences expérimentales, mathématiques)"},
                },
                "required": ["specialite"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "preparer_inscription",
            "description": "Identifie la formation dans la base, valide les informations et affiche le récapitulatif. "
                           "À appeler quand prénom, nom, e-mail, téléphone et la formation souhaitée sont connus. "
                           "Décris la formation avec les mots du prospect (diplôme, spécialité, école).",
            "parameters": {
                "type": "object",
                "properties": {
                    "prenom": {"type": "string"},
                    "nom": {"type": "string"},
                    "email": {"type": "string"},
                    "telephone": {"type": "string"},
                    "specialite": {"type": "string", "description": "Spécialité souhaitée, ex : Réseaux et sécurité informatiques"},
                    "diplome": {"type": "string", "description": "Diplôme souhaité si connu, ex : BTS"},
                    "ecole": {"type": "string", "description": "Ville de l'école si connue, ex : Sousse"},
                },
                "required": ["prenom", "nom", "email", "telephone", "specialite"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "confirmer_inscription",
            "description": "Enregistre la demande préparée. À appeler UNIQUEMENT si le prospect vient de confirmer "
                           "explicitement le récapitulatif (ex : « oui, je confirme »).",
            "parameters": {"type": "object", "properties": {}},
        },
    },
]


# ---------------------------------------------------------------------------
# Implementations
# ---------------------------------------------------------------------------
def rechercher_procedure(ctx, question: str = "") -> dict:
    try:
        hits = rag.retrieve(question)
    except llm.LLMError:
        return {"erreur": "Recherche documentaire indisponible. Oriente le prospect vers le service des admissions."}
    if not hits:
        return {"resultat": "AUCUNE information trouvée dans le document Procedure_admission pour cette question."}
    ctx["sources"] = [{"ref": i + 1, "document": h["chunk"].source, "extrait": h["chunk"].text[:400]}
                      for i, h in enumerate(hits)]
    return {"extraits": [{"ref": i + 1, "texte": h["chunk"].text} for i, h in enumerate(hits)]}


def _formation_dict(f: Formation) -> dict:
    return {
        "id": f.id,
        "diplome": f.diplome,
        "specialite": f.specialite,
        "ecole": f.ecole,
        "niveau_requis": f.niveau_requis,
        "nationalite_requise": f.nationalite_requise,
        "bac_requis": f.bac_requis,
    }


def _keywords(specialite: str) -> list[list[str]]:
    """One group of alternatives per word: "informatiques" -> ["informati", "reseau", ...]."""
    groups = []
    for t in tokens(specialite):
        s = stem(t)
        groups.append(next((v for k, v in SYNONYMS.items() if s == stem(k)), [s]))
    return groups


def search_formations(specialite: str = "", diplome: str = "", ecole: str = "") -> list[Formation]:
    qs = Formation.objects.all()
    if ecole:
        qs = qs.filter(search_text__contains=normalize(ecole).replace("imset", "").strip())
    d = normalize(diplome)
    d = DIPLOMA_ALIASES.get(d, d)
    groups = _keywords(specialite)
    results = []
    for f in qs:
        if d and d not in normalize(f.diplome):
            continue
        spec = normalize(f.specialite)
        score = sum(1 for g in groups if any(k in spec for k in g))
        if groups and score == 0:
            continue
        results.append((score, f))
    if not results:
        return []
    # Keep only the best matches: "réseaux et sécurité informatiques" must not return every IT formation
    best = max(score for score, _ in results)
    return _interleave_schools([f for score, f in results if score == best])


def _interleave_schools(formations: list[Formation]) -> list[Formation]:
    """Round-robin over schools so the first cards are not all from the same school."""
    by_school: dict[str, list[Formation]] = {}
    for f in formations:
        by_school.setdefault(f.ecole, []).append(f)
    queues = list(by_school.values())
    out = []
    while any(queues):
        for q in queues:
            if q:
                out.append(q.pop(0))
    return out


def _formation_line(f: Formation) -> str:
    """Compact text sent to the LLM (fewer tokens than JSON = faster answers)."""
    return (f"id={f.id} | {f.diplome} | {f.specialite} | {f.ecole} | niveau: {f.niveau_requis} | "
            f"nationalité: {f.nationalite_requise} | bac: {f.bac_requis}")


# Words that describe the prospect's bac section, not a specialty ("j'ai un bac science")
BAC_DOMAINS = {"informatique": "informatique", "economie_gestion": "gestion"}
BAC_SECTION_WORDS = {"science", "sciences", "scientifique", "math", "maths", "mathematique", "mathematiques",
                     "experimentale", "experimentales", "lettre", "lettres", "technique", "techniques", "sport"}


def _prospect_bac_sections(bac: str) -> tuple[set[str], bool]:
    """Bac sections of the prospect, and whether they are certain. A vague "bac science" may be
    sciences expérimentales or techniques: good enough to rank, not to exclude."""
    sections = set(eligibility.bac_sections(bac))
    if sections:
        return sections, True
    if "scien" in normalize(bac):
        return {"sciences_experimentales", "sciences_techniques"}, False
    return set(), False


def _bac_match(formation, sections: set[str]) -> int:
    """0 = requires the prospect's bac section (most relevant), 1 = open to all sections, 2 = other section."""
    req = normalize(formation.bac_requis)
    if req in ("", "all") or "san" in req:
        return 1
    return 0 if sections & set(eligibility.bac_sections(formation.bac_requis)) else 2


def _remember_profile(ctx, **values) -> dict:
    """The profile given by the prospect (level, nationality, bac), as understood and passed by the LLM,
    is kept for the whole conversation."""
    profile = ctx["state"].setdefault("profil", {})
    for key, value in values.items():
        if value and str(value).strip():
            profile[key] = str(value).strip()
    return profile


def _evaluation(candidates: list[Formation], profile: dict) -> dict:
    """Eligibility of each candidate formation + the exact instruction for the LLM."""
    results, missing = [], []
    for f in candidates:
        ev = eligibility.evaluate(f, profile)
        results.append({"formation": _formation_line(f), **ev})
        for m in ev["informations_manquantes"]:
            if m not in missing:
                missing.append(m)
    statuses = {r["statut"] for r in results}
    if statuses == {"criteres_non_remplis"}:
        # A known criterion already fails for every candidate: asking for more information is pointless
        missing = []
    if missing:
        consigne = ("NE CONCLUS PAS sur l'éligibilité : il manque des informations. Pose au prospect les questions "
                    "suivantes : " + " ; ".join(QUESTION_FOR.get(m, m) for m in missing) + ".")
    elif statuses == {"criteres_remplis"}:
        consigne = ("Tous les critères connus sont remplis : dis « vous semblez remplir les critères » (jamais "
                    "« vous êtes éligible ») et précise que la décision finale appartient à l'équipe admissions. "
                    "Propose l'inscription.")
    else:
        consigne = ("Explique quel critère ne semble pas rempli (niveau, nationalité ou bac) en citant ce qui est "
                    "exigé et ce que le prospect a indiqué, sans juger. Ne cite AUCUNE autre formation de mémoire "
                    "(tu inventerais) : propose plutôt de chercher des formations adaptées à son profil "
                    "(rechercher_formations avec son niveau et son bac) ou de contacter le service des admissions.")
    return {"profil_prospect": profile, "eligibilite": results, "consigne": consigne}


def rechercher_formations(ctx, specialite: str = "", diplome: str = "", ecole: str = "", niveau: str = "",
                          nationalite: str = "", bac: str = "") -> dict:
    specialite, diplome, ecole = specialite or "", diplome or "", ecole or ""
    note = ""
    if specialite and set(tokens(specialite)) <= BAC_SECTION_WORDS:
        # "bac science" is the prospect's bac section, not a specialty to search for
        _remember_profile(ctx, bac=specialite)
        note = f"« {specialite} » est la section du bac du prospect, pas une spécialité. "
        specialite = ""
    profile = _remember_profile(ctx, niveau=niveau, nationalite=nationalite, bac=bac)
    found = search_formations(specialite, diplome, ecole)
    # Small models sometimes add a filter the prospect never asked for: relax it rather than answer "nothing"
    if not found and diplome:
        found = search_formations(specialite, "", ecole)
        note += f"Aucune formation de type « {diplome} » ; résultats sans filtre de diplôme. "
    if not found and ecole:
        found = search_formations(specialite, diplome, "")
        note += f"Aucune formation à « {ecole} » ; résultats dans toutes les écoles. "
    # Refine with the prospect's level: only formations accessible at that level, closest level first
    rank = eligibility.prospect_level(profile.get("niveau", ""))
    if rank is not None and found:
        accessible = [f for f in found if eligibility.required_level(f.niveau_requis) <= rank]
        excluded = len(found) - len(accessible)
        found = sorted(accessible, key=lambda f: -eligibility.required_level(f.niveau_requis))
        if excluded:
            note += (f"{excluded} formation(s) exigeant un niveau supérieur à « {profile['niveau']} » ont été "
                     "écartées. ")
    # Refine with the prospect's bac: formations made for their section first, then those open to all
    sections, certain = _prospect_bac_sections(profile.get("bac", ""))
    if sections and found:
        if certain:
            kept = [f for f in found if _bac_match(f, sections) < 2]
            if len(kept) < len(found):
                note += (f"{len(found) - len(kept)} formation(s) réservée(s) à une autre section du bac ont été "
                         "écartées. ")
            found = kept
        found = sorted(found, key=lambda f: _bac_match(f, sections))  # stable: keeps the level order
        specific = sum(1 for f in found if _bac_match(f, sections) == 0)
        if specific:
            note += (f"Les {specific} premières formations exigent spécifiquement la section du bac du prospect : "
                     "cite leurs domaines en priorité. ")
        # "J'ai un bac informatique, quelles spécialités me correspondent ?": no domain asked, the bac section
        # gives one -> formations of that domain first (nothing excluded)
        domain = next((BAC_DOMAINS[s] for s in sections if s in BAC_DOMAINS), "") if not specialite else ""
        if domain:
            groups = _keywords(domain)
            in_domain = [any(k in normalize(f.specialite) for g in groups for k in g) for f in found]
            if any(in_domain):
                found = [f for f, ok in zip(found, in_domain) if ok] + [f for f, ok in zip(found, in_domain) if not ok]
                note += (f"Les {sum(in_domain)} premières formations relèvent du domaine du bac du prospect "
                         f"({domain}) : présente-les en priorité. ")
    shown = found[:MAX_RESULTS]
    ctx["cards"] = [_formation_dict(f) for f in shown]
    if not found:
        return {"total": 0, "resultat": "Aucune formation trouvée avec ces critères."}
    if len(found) <= 3 and any(profile.get(k) for k in ("niveau", "nationalite", "bac")):
        # Precise search + known profile: give the eligibility pre-check right away
        return {"total": len(found), "formations": [_formation_line(f) for f in shown],
                "note": note + "Les formations sont affichées en cartes : ne recopie pas la liste.",
                **_evaluation(found, profile)}
    return {
        "total": len(found),
        "formations": [_formation_line(f) for f in shown],
        "consigne": note + f"{len(found)} résultat(s) ; {len(shown)} sont DÉJÀ affichés au prospect sous forme de "
                           "cartes. NE RECOPIE PAS la liste : réponds en 2 ou 3 phrases (nombre de résultats, "
                           "écoles concernées) puis pose UNE question utile (école, niveau d'études, nationalité ou bac). "
                           "Ces résultats NE VALIDENT PAS l'éligibilité : ne dis jamais « vous êtes éligible ».",
    }


QUESTION_FOR = {
    "niveau d'études actuel": "son niveau d'études actuel (ex : bac, bac+2, 4ème année secondaire)",
    "nationalité": "sa nationalité",
    "section du baccalauréat": "la section de son baccalauréat (ex : mathématiques, sciences expérimentales)",
}


def verifier_eligibilite(ctx, specialite: str = "", diplome: str = "", ecole: str = "",
                         niveau: str = "", nationalite: str = "", bac: str = "") -> dict:
    """Code-side eligibility check: the LLM only phrases the result."""
    profile = _remember_profile(ctx, niveau=niveau, nationalite=nationalite, bac=bac)
    candidates = search_formations(specialite or "", diplome or "", ecole or "")
    if not candidates:
        return {"resultat": f"Formation introuvable dans la base : « {diplome} {specialite} {ecole} ».",
                "consigne": "Demande au prospect de préciser la formation (spécialité, diplôme, école)."}
    if len(candidates) > 3:
        ctx["cards"] = [_formation_dict(f) for f in candidates[:MAX_RESULTS]]
        return {"ambigu": True, "nombre": len(candidates),
                "consigne": "Plusieurs formations correspondent (affichées en cartes) : demande au prospect "
                            "laquelle l'intéresse (diplôme, école) avant de vérifier l'éligibilité."}

    result = _evaluation(candidates, profile)
    if {r["statut"] for r in result["eligibilite"]} != {"criteres_non_remplis"}:
        ctx["cards"] = [_formation_dict(f) for f in candidates]
        return result

    # Not accessible: show formations the prospect can aim for instead of the refused one
    alternatives = _alternatives(candidates, profile)
    ctx["cards"] = [_formation_dict(f) for f in alternatives]
    if alternatives:
        result["alternatives"] = [_formation_line(f) for f in alternatives]
        result["consigne"] = (
            "Explique en une phrase quel critère n'est pas rempli (exigé / indiqué par le prospect), sans juger. "
            f"Les {len(alternatives)} formations de la liste « alternatives » sont DÉJÀ affichées en cartes à la place "
            "de la formation demandée : cite 2 ou 3 de leurs spécialités comme pistes (sans recopier la liste), "
            "propose de vérifier son éligibilité à l'une d'elles, et termine par cette phrase exacte : "
            f"« {FINAL_DECISION} »"
        )
    return result


def _domain_keywords(formations: list[Formation]) -> list[str]:
    """Keywords of the domains the formations belong to ("Préparateur en Pharmacie" -> santé)."""
    specs = [normalize(f.specialite) for f in formations]
    return [k for words in SYNONYMS.values() if any(w in s for w in words for s in specs) for k in words]


def _alternatives(refused: list[Formation], profile: dict) -> list[Formation]:
    """Formations whose known criteria do not exclude the prospect: same domain first, criteria met first,
    one card per specialty."""
    domain = _domain_keywords(refused)
    if profile.get("bac") and not profile.get("niveau"):
        # "je suis bac lettres": a bac section means the prospect holds the bac -> suggest what a bac gives access to
        profile = {**profile, "niveau": "bac"}
    scored = []
    for f in Formation.objects.exclude(id__in=[f.id for f in refused]):
        statut = eligibility.evaluate(f, profile)["statut"]
        if statut == "criteres_non_remplis":
            continue
        in_domain = any(k in normalize(f.specialite) for k in domain)
        scored.append(((not in_domain, statut != "criteres_remplis", -eligibility.required_level(f.niveau_requis)), f))
    scored.sort(key=lambda s: s[0])
    out, seen = [], set()
    for _, f in scored:
        key = normalize(f.specialite)
        if key not in seen:
            seen.add(key)
            out.append(f)
    return out[:MAX_RESULTS]


def _duplicate(email: str, phone: str) -> Candidature | None:
    return Candidature.objects.filter(Q(email=email) | Q(telephone=phone)).first()


def preparer_inscription(ctx, prenom="", nom="", email="", telephone="", specialite="", diplome="", ecole="") -> dict:
    errors = []
    data = {"prenom": clean_name(prenom), "nom": clean_name(nom), "email": clean_email(email),
            "telephone": normalize_phone(telephone)}
    if not data["prenom"]:
        errors.append(f"Prénom invalide : « {prenom} »")
    if not data["nom"]:
        errors.append(f"Nom invalide : « {nom} »")
    if not data["email"]:
        errors.append(f"E-mail invalide : « {email} »")
    if not data["telephone"]:
        errors.append(f"Téléphone invalide : « {telephone} » (8 chiffres pour la Tunisie ou format international +XXX)")

    # The formation is identified by the code from the database, never chosen by the model
    candidates = search_formations(specialite or "", diplome or "", ecole or "") if specialite else []
    if not candidates:
        errors.append(f"Formation inexistante dans la base : « {diplome} {specialite} {ecole} ». "
                      "Demande au prospect de préciser une formation existante.")
    elif len(candidates) > 1:
        ctx["cards"] = [_formation_dict(f) for f in candidates[:MAX_RESULTS]]
        return {"ok": False, "ambigu": True, "nombre": len(candidates),
                "formations_possibles": [_formation_line(f) for f in candidates[:MAX_RESULTS]],
                "consigne": "Plusieurs formations correspondent (affichées en cartes). N'enregistre rien : demande au "
                            "prospect de préciser le diplôme et/ou l'école, puis rappelle preparer_inscription."}
    if errors:
        return {"ok": False, "erreurs": errors, "consigne": "Demande au prospect de corriger ces informations."}
    formation = candidates[0]

    existing = _duplicate(data["email"], data["telephone"])
    if existing:
        return {"ok": False, "doublon": True,
                "erreurs": [f"Une demande existe déjà avec cet e-mail ou ce téléphone (référence {existing.reference}, "
                            f"statut « {existing.statut} »). Aucune nouvelle demande ne peut être créée."]}

    data["formation_id"] = formation.id
    ctx["state"]["inscription_en_attente"] = {**data, "tour": ctx["state"]["tour"]}
    recap = {**data, "formation": _formation_dict(formation)}
    ctx["recap"] = recap
    return {"ok": True, "recapitulatif": recap,
            "consigne": "Le récapitulatif est affiché. Demande au prospect de confirmer explicitement. N'enregistre rien avant."}


_CONFIRM_RE = re.compile(r"\b(oui|ok|okay|d accord|je confirme|confirme|confirmer|valide|valider|parfait|c est bon|"
                         r"tout est (bon|correct)|exact|correct|yes)\b")
_REFUSE_RE = re.compile(r"\b(non|pas|attend|attendez|modifier|modifie|changer|change|corriger|faux|fausse|erreur|"
                        r"annule|annuler)\b")


def is_explicit_confirmation(text: str) -> bool:
    """The prospect's own message must confirm, without asking for a change ("oui mais l'e-mail est faux")."""
    t = normalize(text)
    return bool(_CONFIRM_RE.search(t)) and not _REFUSE_RE.search(t)


def confirmer_inscription(ctx) -> dict:
    state = ctx["state"]
    pending = state.get("inscription_en_attente")
    if not pending:
        return {"ok": False, "erreur": "Aucun récapitulatif en attente : appelle d'abord preparer_inscription."}
    if pending["tour"] >= state["tour"]:
        # The recap must have been shown to the prospect and confirmed in a LATER message
        return {"ok": False, "erreur": "Le prospect n'a pas encore vu le récapitulatif : attends sa confirmation explicite."}
    if not is_explicit_confirmation(ctx.get("user_text", "")):
        # Checked in code: the model must not register on an ambiguous answer or a correction request
        return {"ok": False, "erreur": "Le dernier message du prospect n'est pas une confirmation explicite. N'enregistre "
                                       "rien : demande-lui de confirmer le récapitulatif ou de préciser la modification."}
    try:
        with transaction.atomic():
            if _duplicate(pending["email"], pending["telephone"]):
                state.pop("inscription_en_attente", None)
                return {"ok": False, "doublon": True, "erreur": "Une demande existe déjà avec cet e-mail ou ce téléphone."}
            c = Candidature.objects.create(
                prenom=pending["prenom"], nom=pending["nom"], email=pending["email"], telephone=pending["telephone"],
                formation_id=pending["formation_id"], statut=Candidature.STATUT_NOUVELLE,
                conversation_id=ctx["conversation_id"],
            )
    except IntegrityError:
        state.pop("inscription_en_attente", None)
        return {"ok": False, "doublon": True, "erreur": "Une demande existe déjà avec cet e-mail ou ce téléphone."}

    state.pop("inscription_en_attente", None)
    sent = notifications.notify_team(c)
    notifications.confirm_prospect(c)
    ctx["confirmation"] = {"reference": c.reference, "statut": c.statut}
    return {"ok": True, "reference": c.reference, "statut": c.statut, "equipe_notifiee": sent,
            "consigne": "Confirme l'enregistrement au prospect avec la référence, et rappelle que l'admission "
                        "n'est pas garantie : la décision appartient à l'équipe admissions."}


FUNCTIONS = {
    "rechercher_procedure": rechercher_procedure,
    "rechercher_formations": rechercher_formations,
    "verifier_eligibilite": verifier_eligibilite,
    "preparer_inscription": preparer_inscription,
    "confirmer_inscription": confirmer_inscription,
}
