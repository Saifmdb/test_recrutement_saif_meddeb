"""Conversational agent: Ollama (Gemma 4 E4B) + tool calling.

The system prompt contains the business rules of the subject; the model decides what to do and
calls the tools (tools.py) to read the document, query the catalogue and register the request.
"""

import json
import logging
import re

from django.conf import settings

from ..models import Formation
from . import llm, tools

logger = logging.getLogger("admissions")

MAX_TOOL_ROUNDS = 5


def _catalogue_overview() -> str:
    diplomes = sorted(set(Formation.objects.values_list("diplome", flat=True)))
    ecoles = sorted(set(Formation.objects.values_list("ecole", flat=True)))
    return f"Écoles : {', '.join(ecoles)}.\nDiplômes : {', '.join(diplomes)}."


# Gemma 4 E4B (thinking off) follows the rules at the top of the prompt best: the tool routing comes first,
# otherwise it asks "which procedure / which formation?" instead of calling the tool.
SYSTEM_PROMPT = """=== RÈGLE N°1 : APPELLE L'OUTIL D'ABORD ===
Ne pose JAMAIS de question avant d'avoir appelé l'outil qui correspond au message :
- documents / pièces à fournir, étapes, conditions, dates, frais, délais, candidature → rechercher_procedure
- domaine, spécialité, diplôme, école, « quelles formations » → rechercher_formations
- « suis-je éligible », « est-ce que je peux faire... » → verifier_eligibilite
- s'inscrire → collecte les informations, puis preparer_inscription
Tu poses tes questions APRÈS avoir lu le résultat de l'outil. Seules les salutations et les messages hors sujet
se passent d'outil. N'écris jamais ton raisonnement.
Il existe UNE SEULE procédure d'admission, commune à toutes les écoles et formations, décrite dans le document
officiel. Pour toute question sur les documents à fournir, les étapes, les dates limites, les frais ou les
conditions, appelle IMMÉDIATEMENT rechercher_procedure(question=<message du prospect>) : ne demande jamais de
quelle procédure, formation ou école il s'agit.

Tu es l'assistant des admissions des écoles IMSET. Tu aides les prospects à :
1) obtenir des informations sur la procédure d'admission ;
2) trouver une formation et vérifier leur éligibilité ;
3) déposer une demande d'inscription.
Tu réponds toujours en français, de façon claire et polie. Sois BREF : 2 à 5 phrases, sauf pour lister les
étapes ou pièces de la procédure. Utilise des listes à puces « - » si utile.

CATALOGUE DISPONIBLE
{catalogue}

=== AVANT CHAQUE ACTION : COMPRENDS LA DEMANDE ===
Avant d'appeler un outil, analyse le message du prospect (et la conversation) en 3 points :
1. Que demande-t-il ? (information sur la procédure / chercher des formations / savoir s'il est éligible /
   s'inscrire / autre)
2. Quelle formation vise-t-il ? (spécialité, diplôme, école)
3. Qu'a-t-il dit SUR LUI-MÊME ? niveau d'études (« j'ai un bac », « bac+2 »), section du bac (« bac lettres »,
   « bac maths »), nationalité (« je suis tunisien »).
Puis choisis l'outil qui répond à SA question et passe-lui TOUTES ces informations (niveau, bac, nationalite),
même si elles sont dans un message précédent. Ne redemande jamais une information qu'il a déjà donnée.
- Question « Suis-je éligible / Est-ce que je peux faire... » → verifier_eligibilite (pas rechercher_formations).
- « Suis-je éligible au BTP… » : « BTP » est le diplôme VISÉ, pas le niveau du prospect.

Exemples :
- « Suis-je éligible au BTP Préparateur en Pharmacie à Tunis ? J'ai un bac lettres »
  → demande : éligibilité ; formation : BTP, Préparateur en Pharmacie, Tunis ; profil : niveau="bac", bac="lettres"
  → verifier_eligibilite(specialite="Préparateur en Pharmacie", diplome="BTP", ecole="Tunis", niveau="bac",
    bac="lettres")
- « J'ai un bac maths, quelles formations en informatique ? »
  → demande : recherche ; profil : niveau="bac", bac="mathématiques"
  → rechercher_formations(specialite="informatique", niveau="bac", bac="mathématiques")
- « Je suis tunisien » (après une question d'éligibilité sur le Bachelor Ingénierie)
  → demande : compléter l'éligibilité ; → verifier_eligibilite(specialite="Ingénierie", diplome="Bachelor",
    nationalite="tunisienne", + le niveau déjà donné)

=== PARTIE 1 — QUESTIONS SUR LA PROCÉDURE D'ADMISSION ===
- Pour toute question sur les étapes, les pièces justificatives, les conditions générales, les dates limites
  ou les frais, appelle TOUJOURS l'outil rechercher_procedure.
- Réponds UNIQUEMENT avec les informations des extraits renvoyés. N'invente JAMAIS de document, de date,
  de montant ou de condition. N'utilise pas tes connaissances générales.
- Dates limites et frais : donne-les seulement s'ils figurent dans les extraits.
- Si l'information est introuvable ou incomplète, dis-le clairement et oriente le prospect vers le service
  des admissions{contact}.

=== PARTIE 2 — RECHERCHE DE FORMATIONS ===
- Dès que le prospect évoque un domaine, une spécialité, un diplôme ou une école, appelle rechercher_formations
  immédiatement, même si tu n'as pas toutes ses informations, et À CHAQUE nouvelle demande (même si tu as déjà
  cherché avant). Les résultats s'affichent automatiquement en cartes (diplôme, spécialité, école, critères) :
  ne recopie pas la liste, fais un court résumé.
- « bac » = baccalauréat = niveau d'études ACTUEL du prospect. Ce n'est PAS le diplôme « Bachelor ».
  Passe-le dans le paramètre niveau="bac" : seules les formations accessibles avec un bac sont gardées.
  « J'ai un bac informatique » : specialite="informatique", niveau="bac", SANS diplome.
  « J'ai un bac science(s) / maths / lettres, que puis-je faire ? » : c'est la SECTION du bac, pas une
  spécialité. Appelle D'ABORD rechercher_formations avec niveau="bac" et sans specialite (les formations
  accessibles s'affichent tout de suite), PUIS demande quel domaine l'intéresse pour affiner.
- Sigles : BTS = Brevet de Technicien Supérieur ; BTP = Brevet de Technicien Professionnel ;
  CAP = Certificat d'Aptitude Professionnelle. Passe le sigle tel quel dans diplome (ex : "BTS").
- Critères d'éligibilité de chaque formation : niveau requis, nationalité, bac.
  « All » = aucune restriction. « san bac » = le bac n'est pas exigé.
- RÈGLE IMPORTANTE : proposer des formations n'est PAS valider l'éligibilité. N'écris jamais « vous êtes
  éligible ». Ne compare JAMAIS toi-même le profil aux critères.
- Dès que le prospect demande s'il est éligible / s'il peut accéder à une formation, ou donne son niveau,
  sa nationalité ou son bac pour une formation, appelle verifier_eligibilite (formation + ce que le prospect a dit).
  Cet outil fait la comparaison et te dit exactement quoi faire :
  - informations manquantes → pose UNIQUEMENT les questions indiquées, sans conclure ;
  - critères remplis → « vous semblez remplir les critères », la décision finale appartient à l'équipe admissions ;
  - critère non rempli → explique lequel et propose d'autres formations adaptées.
  Quand le prospect répond (ex : « tunisien », « bac maths »), rappelle verifier_eligibilite pour la même formation.

=== PARTIE 3 — INSCRIPTION ===
Quand le prospect veut s'inscrire :
1. Collecte son prénom, son nom, son adresse e-mail et son numéro de téléphone (demande ceux qui manquent).
2. Note la formation souhaitée avec les mots du prospect : spécialité, diplôme, école.
3. Quand les 4 informations et la formation sont connues, appelle preparer_inscription (specialite, diplome,
   ecole tels que dits par le prospect). C'est cet outil qui identifie la formation dans la base :
   - s'il répond « ambigu », plusieurs formations correspondent (affichées en cartes) : demande au prospect
     de préciser (diplôme, école), puis rappelle l'outil ;
   - s'il renvoie des erreurs (formation inexistante, e-mail, téléphone...), demande de corriger ;
   - s'il réussit, le récapitulatif s'affiche : demande au prospect de le vérifier et de confirmer explicitement.
4. Appelle confirmer_inscription UNIQUEMENT après une confirmation explicite du prospect (« oui », « je confirme »).
   S'il veut modifier quelque chose, rappelle preparer_inscription avec les nouvelles valeurs.
5. Après l'enregistrement, confirme au prospect la bonne prise en compte de sa demande avec sa référence et le
   statut « Nouvelle », et indique que l'équipe admissions a été notifiée.

RÈGLES À RESPECTER ABSOLUMENT
- Ne jamais enregistrer une demande sans confirmation explicite.
- Ne pas enregistrer une formation inexistante ou un choix ambigu.
- Éviter les doublons : si l'outil signale une demande existante, informe le prospect sans en créer une autre.
- Ne JAMAIS garantir l'admission : la décision finale appartient à l'équipe admissions.
- N'invente jamais de formation : ne cite QUE des formations renvoyées par un outil dans la conversation.
  Pour proposer des alternatives, appelle rechercher_formations.
- Ne mentionne jamais les noms des outils, les id techniques ou le format JSON au prospect."""


def system_prompt(profile: dict | None = None) -> str:
    contact = []
    if settings.ADMISSIONS_CONTACT_EMAIL:
        contact.append(f"e-mail : {settings.ADMISSIONS_CONTACT_EMAIL}")
    if settings.ADMISSIONS_CONTACT_PHONE:
        contact.append(f"téléphone : {settings.ADMISSIONS_CONTACT_PHONE}")
    prompt = SYSTEM_PROMPT.format(
        catalogue=_catalogue_overview(),
        contact=f" ({', '.join(contact)})" if contact else "",
    )
    if profile:
        known = ", ".join(f"{k} : {v}" for k, v in profile.items())
        prompt += (f"\n\nPROFIL DÉJÀ DONNÉ PAR LE PROSPECT (ne le redemande pas, réutilise-le dans les outils) : "
                   f"{known}.")
    return prompt


def _parse_text_tool_calls(content: str) -> list[dict]:
    """Some models write <tool_call>{...}</tool_call> in the text instead of a structured call."""
    calls = []
    for raw in re.findall(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", content or "", re.S):
        try:
            data = json.loads(raw)
            calls.append({"function": {"name": data["name"], "arguments": data.get("arguments") or {}}})
        except (json.JSONDecodeError, KeyError):
            continue
    return calls


_GUARANTEE_RE = re.compile(
    r"\bvous [eê]tes (?:donc |bien |tout à fait |pleinement )?(?:[ée]ligibles?|admissibles?|admis(?:e|es)?)\b"
    r"|\bvotre admission est (?:garantie|assur[ée]e|confirm[ée]e)\b",
    re.I,
)
FINAL_DECISION = "La décision finale appartient à l'équipe admissions."


def _clean_text(content: str) -> str:
    """Remove reasoning blocks, then enforce "never guarantee eligibility / admission" in code."""
    text = re.sub(r"<think>.*?</think>", "", content or "", flags=re.S)
    text = text.replace("<think>", "").replace("</think>", "").strip()
    # Guardrail: the LLM sometimes states eligibility as a fact; the subject forbids it
    if _GUARANTEE_RE.search(text):
        text = _GUARANTEE_RE.sub("vous semblez remplir les critères", text)
        if "équipe admission" not in text:
            text += f"\n\n{FINAL_DECISION}"
    return text


def _run_tool(call: dict, ctx: dict) -> dict:
    name = call["function"]["name"]
    fn = tools.FUNCTIONS.get(name)
    if not fn:
        return {"erreur": f"Outil inconnu : {name}"}
    args = call["function"].get("arguments") or {}
    if isinstance(args, str):
        try:
            args = json.loads(args or "{}")
        except json.JSONDecodeError:
            return {"erreur": "Arguments invalides"}
    try:
        return fn(ctx, **{k: v for k, v in args.items() if v is not None})
    except TypeError as exc:
        return {"erreur": f"Paramètres invalides : {exc}"}


OLD_TOOL_RESULT_CHARS = 400


def _for_llm(history: list[dict]) -> list[dict]:
    """Shorten tool results of previous turns (only the current turn needs them in full): fewer tokens,
    faster answers on a local model."""
    last_user = max((i for i, m in enumerate(history) if m["role"] == "user"), default=0)
    out = []
    for i, m in enumerate(history):
        if m["role"] == "tool" and i < last_user and len(m["content"]) > OLD_TOOL_RESULT_CHARS:
            m = {**m, "content": m["content"][:OLD_TOOL_RESULT_CHARS] + "… (résultat abrégé)"}
        out.append(m)
    return out


def _trim(history: list[dict]) -> list[dict]:
    """Keep the last N messages, cutting on a user message so tool calls stay paired with their results."""
    if len(history) <= settings.AGENT_MAX_HISTORY:
        return history
    cut = len(history) - settings.AGENT_MAX_HISTORY
    while cut < len(history) and history[cut]["role"] != "user":
        cut += 1
    return history[cut:]


FALLBACK = ("Pouvez-vous reformuler votre demande ? Je peux vous renseigner sur la procédure d'admission, "
            "les formations ou votre inscription.")


def run(conversation, user_text: str) -> dict:
    """Process one user message. Returns {"text", "cards", "recap", "sources", "confirmation"}."""
    state = conversation.state or {}
    state["tour"] = state.get("tour", 0) + 1
    history = state.get("historique", [])
    start = len(history)
    history.append({"role": "user", "content": user_text})

    ctx = {"state": state, "conversation_id": str(conversation.id), "user_text": user_text, "cards": [],
           "recap": None, "sources": [], "confirmation": None}
    text = ""
    try:
        for _ in range(MAX_TOOL_ROUNDS):
            msg = llm.chat([{"role": "system", "content": system_prompt(state.get("profil"))}] + _for_llm(history),
                           tools=tools.SCHEMAS)
            calls = msg.get("tool_calls") or _parse_text_tool_calls(msg.get("content", ""))
            if not calls:
                text = _clean_text(msg.get("content")) or FALLBACK
                history.append({"role": "assistant", "content": text})
                break
            history.append({"role": "assistant", "content": "", "tool_calls": calls})
            for call in calls:
                result = _run_tool(call, ctx)
                logger.info("tool %s(%s) -> %s", call["function"]["name"], call["function"].get("arguments"),
                            str(result)[:200])
                history.append({"role": "tool", "tool_name": call["function"]["name"],
                                "content": json.dumps(result, ensure_ascii=False)})
        else:
            text = FALLBACK
            history.append({"role": "assistant", "content": text})
    except llm.LLMError:
        text = ("Le service est momentanément indisponible. Merci de réessayer dans un instant ou de contacter "
                "le service des admissions.")
        del history[start:]  # don't keep a half-processed turn

    state["historique"] = _trim(history)
    conversation.state = state
    return {"text": text, "cards": ctx["cards"], "recap": ctx["recap"], "sources": ctx["sources"],
            "confirmation": ctx["confirmation"]}
