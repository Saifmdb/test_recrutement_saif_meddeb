from unittest.mock import patch

from django.core import mail
from django.test import TestCase, override_settings

from .models import Candidature, Conversation, Formation
from .services import tools
from .services.text import normalize
from .services.validators import clean_email, clean_name, normalize_phone


def make_formation(diplome, specialite, ecole, niveau="bac ou BTP dans le même secteur", nat="All", bac="All"):
    return Formation.objects.create(
        diplome=diplome, specialite=specialite, ecole=ecole, niveau_requis=niveau, nationalite_requise=nat,
        bac_requis=bac, search_text=normalize(f"{diplome} {specialite} {ecole}"),
    )


class ValidatorsTests(TestCase):
    def test_phone(self):
        self.assertEqual(normalize_phone("22 123 456"), "+21622123456")
        self.assertEqual(normalize_phone("+216 98.765.432"), "+21698765432")
        self.assertEqual(normalize_phone("0033612345678"), "+33612345678")
        self.assertIsNone(normalize_phone("12345"))
        self.assertIsNone(normalize_phone("abc"))

    def test_email_and_name(self):
        self.assertEqual(clean_email(" Fares@Gmail.com "), "fares@gmail.com")
        self.assertIsNone(clean_email("fares@"))
        self.assertEqual(clean_name("ben ali"), "Ben Ali")
        self.assertIsNone(clean_name("x1"))


class SearchTests(TestCase):
    def setUp(self):
        self.bts_sousse = make_formation("Brevet de Technicien Supérieur", "Réseaux et sécurité Informatiques", "IMSET SOUSSE")
        self.bts_tunis = make_formation("Brevet de Technicien Supérieur", "Réseaux et sécurité Informatiques", "IMSET TUNIS")
        self.compta = make_formation("Brevet de Technicien Supérieur", "Comptabilité et Finances", "IMSET SFAX")
        self.dev = make_formation("Brevet de Technicien Supérieur", "Développement sur Internet", "IMSET NABEUL")

    def test_domain_synonyms(self):
        found = tools.search_formations(specialite="informatique")
        self.assertIn(self.dev, found)  # "informatique" also covers web development
        self.assertNotIn(self.compta, found)

    def test_filters(self):
        self.assertEqual(tools.search_formations(specialite="réseaux", ecole="Sousse"), [self.bts_sousse])
        self.assertEqual(tools.search_formations(diplome="BTS", specialite="comptabilité"), [self.compta])
        self.assertEqual(tools.search_formations(diplome="Licence"), [])


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
                   ADMISSIONS_TEAM_EMAILS=["team@example.com"], SEND_PROSPECT_CONFIRMATION_EMAIL=True)
class RegistrationRulesTests(TestCase):
    def setUp(self):
        self.f = make_formation("Brevet de Technicien Supérieur", "Informatique de Gestion", "IMSET TUNIS")
        self.conv = Conversation.objects.create()
        self.ctx = {"state": {"tour": 1}, "conversation_id": str(self.conv.id), "cards": [], "recap": None,
                    "sources": [], "confirmation": None}
        self.data = dict(prenom="fares", nom="ben ali", email="fares@test.com", telephone="22123456",
                         specialite="informatique de gestion", diplome="BTS", ecole="Tunis")

    def test_invalid_data_and_unknown_formation_are_refused(self):
        res = tools.preparer_inscription(self.ctx, **{**self.data, "email": "bad", "specialite": "astronomie"})
        self.assertFalse(res["ok"])
        self.assertEqual(len(res["erreurs"]), 2)
        self.assertNotIn("inscription_en_attente", self.ctx["state"])

    def test_ambiguous_formation_asks_for_precision(self):
        make_formation("Brevet de Technicien Supérieur", "Informatique de Gestion", "IMSET SOUSSE")
        res = tools.preparer_inscription(self.ctx, **{**self.data, "ecole": ""})
        self.assertFalse(res["ok"])
        self.assertTrue(res["ambigu"])
        self.assertEqual(len(self.ctx["cards"]), 2)  # choices shown to the prospect
        self.assertNotIn("inscription_en_attente", self.ctx["state"])
        # with the school, the formation is identified unambiguously
        self.assertTrue(tools.preparer_inscription(self.ctx, **self.data)["ok"])
        self.assertEqual(self.ctx["state"]["inscription_en_attente"]["formation_id"], self.f.id)

    def test_no_save_without_recap_then_later_confirmation(self):
        # confirming without any recap
        self.assertFalse(tools.confirmer_inscription(self.ctx)["ok"])
        # recap prepared and "confirmed" in the same turn: refused (the prospect has not seen it)
        self.assertTrue(tools.preparer_inscription(self.ctx, **self.data)["ok"])
        self.assertFalse(tools.confirmer_inscription(self.ctx)["ok"])
        self.assertEqual(Candidature.objects.count(), 0)
        # next turn: the prospect asks for a change -> the model calling the tool anyway is refused
        self.ctx["state"]["tour"] = 2
        for answer in ("Attendez, mon numéro est faux", "Oui mais je veux changer d'école", "Merci"):
            self.ctx["user_text"] = answer
            self.assertFalse(tools.confirmer_inscription(self.ctx)["ok"], answer)
        self.assertEqual(Candidature.objects.count(), 0)
        # the prospect confirmed explicitly
        self.ctx["user_text"] = "Oui, je confirme"
        res = tools.confirmer_inscription(self.ctx)
        self.assertTrue(res["ok"])
        c = Candidature.objects.get()
        self.assertEqual(c.statut, "Nouvelle")
        self.assertEqual(c.telephone, "+21622123456")
        self.assertTrue(c.notification_envoyee)
        self.assertEqual([m.to for m in mail.outbox], [["team@example.com"], ["fares@test.com"]])

    def test_duplicates_on_email_or_phone(self):
        Candidature.objects.create(prenom="A", nom="B", email="other@test.com", telephone="+21622123456", formation=self.f)
        res = tools.preparer_inscription(self.ctx, **self.data)  # same phone, other e-mail
        self.assertFalse(res["ok"])
        self.assertTrue(res["doublon"])
        self.assertEqual(Candidature.objects.count(), 1)


class EligibilityTests(TestCase):
    """Eligibility is computed by the code; missing information is asked, never assumed."""

    def setUp(self):
        self.licence = make_formation("Diplome de LICENCE", "Licence informatique générale", "IMSET GABES",
                                      niveau="Bac+2 / BTS")
        self.bts = make_formation("Brevet de Technicien Supérieur", "Réseaux et sécurité Informatiques", "IMSET GABES")
        self.bachelor = make_formation("Bachelor", "Ingénierie", "IMSET TUNIS", niveau="Bac+2 / BTS", nat="Tunisienne")
        self.pharma = make_formation("Brevet de Technicien Professionnel", "Préparateur en Pharmacie", "IMSET TUNIS",
                                     niveau="4ème année secondaire", bac=" Sciences expérimentales ou Mathèmatique")
        self.conv = Conversation.objects.create()

    def ctx(self):
        return {"state": {"tour": 1}, "conversation_id": str(self.conv.id), "cards": [], "recap": None,
                "sources": [], "confirmation": None}

    def test_missing_level_is_asked_not_assumed(self):
        res = tools.verifier_eligibilite(self.ctx(), specialite="informatique générale", diplome="Licence")
        self.assertEqual(res["eligibilite"][0]["statut"], "informations_manquantes")
        self.assertIn("NE CONCLUS PAS", res["consigne"])

    def test_bac_is_not_enough_for_a_licence(self):
        res = tools.verifier_eligibilite(self.ctx(), specialite="informatique générale", diplome="Licence", niveau="bac")
        self.assertEqual(res["eligibilite"][0]["statut"], "criteres_non_remplis")
        res = tools.verifier_eligibilite(self.ctx(), specialite="informatique générale", diplome="Licence", niveau="BTS")
        self.assertEqual(res["eligibilite"][0]["statut"], "criteres_remplis")

    def test_nationality_and_bac_type_when_restricted(self):
        ctx = self.ctx()
        res = tools.verifier_eligibilite(ctx, specialite="Ingénierie", diplome="Bachelor", niveau="bac+2")
        self.assertEqual(res["eligibilite"][0]["informations_manquantes"], ["nationalité"])
        # the profile is remembered: only the nationality is given now
        res = tools.verifier_eligibilite(ctx, specialite="Ingénierie", diplome="Bachelor", nationalite="tunisienne")
        self.assertEqual(res["eligibilite"][0]["statut"], "criteres_remplis")
        # level already too low: say so instead of asking for the nationality
        res = tools.verifier_eligibilite(self.ctx(), specialite="Ingénierie", diplome="Bachelor", niveau="bac")
        self.assertEqual(res["eligibilite"][0]["statut"], "criteres_non_remplis")
        self.assertNotIn("NE CONCLUS PAS", res["consigne"])
        ctx = self.ctx()
        res = tools.verifier_eligibilite(ctx, specialite="pharmacie", bac="lettres")
        self.assertEqual(res["eligibilite"][0]["statut"], "criteres_non_remplis")
        # the refused formation is replaced by accessible ones (bac level assumed, Licence/Bachelor need Bac+2)
        ids = [c["id"] for c in ctx["cards"]]
        self.assertEqual(ids, [self.bts.id])
        self.assertEqual(len(res["alternatives"]), 1)
        res = tools.verifier_eligibilite(self.ctx(), specialite="pharmacie", niveau="bac", bac="sciences expérimentales")
        self.assertEqual(res["eligibilite"][0]["statut"], "criteres_remplis")

    def test_bac_science_is_a_level_not_a_specialty(self):
        ctx = self.ctx()
        res = tools.rechercher_formations(ctx, specialite="science", niveau="bac")
        ids = [c["id"] for c in ctx["cards"]]
        self.assertNotIn(self.licence.id, ids)  # requires Bac+2
        self.assertIn(self.bts.id, ids)
        self.assertEqual(ctx["state"]["profil"]["bac"], "science")
        self.assertIn("écartées", res.get("note", "") + res["consigne"])

    def test_formations_for_the_prospect_bac_section_come_first(self):
        # "bac science" is vague: formations requiring a science bac come first, nothing is excluded
        ctx = self.ctx()
        tools.rechercher_formations(ctx, niveau="bac", bac="science")
        ids = [c["id"] for c in ctx["cards"]]
        self.assertEqual(ids[0], self.pharma.id)
        self.assertIn(self.bts.id, ids)
        # a known section excludes formations reserved to other sections
        ctx = self.ctx()
        tools.rechercher_formations(ctx, niveau="bac", bac="lettres")
        ids = [c["id"] for c in ctx["cards"]]
        self.assertNotIn(self.pharma.id, ids)
        self.assertIn(self.bts.id, ids)

    def test_bac_informatique_shows_it_formations_first(self):
        commerce = make_formation("Brevet de Technicien Supérieur", "Commerce international", "IMSET SFAX")
        ctx = self.ctx()
        tools.rechercher_formations(ctx, niveau="bac", bac="informatique")
        ids = [c["id"] for c in ctx["cards"]]
        self.assertEqual(ids[0], self.bts.id)  # Réseaux et sécurité informatiques
        self.assertIn(commerce.id, ids)  # ranked, not excluded


class GuaranteeGuardrailTests(TestCase):
    def test_eligibility_is_never_stated_as_a_fact(self):
        from .services.agent import _clean_text

        text = _clean_text("Avec votre bac, vous êtes éligible aux formations informatiques.")
        self.assertNotIn("vous êtes éligible", text)
        self.assertIn("vous semblez remplir les critères", text)
        self.assertIn("équipe admissions", text)
        self.assertEqual(_clean_text("Voici 3 formations."), "Voici 3 formations.")


class AgentLoopTests(TestCase):
    """The agent loop executes the tool calls requested by the model and returns the cards."""

    def test_tool_call_then_answer(self):
        make_formation("Brevet de Technicien Supérieur", "Développement sur Internet", "IMSET NABEUL")
        replies = iter([
            {"role": "assistant", "content": "",
             "tool_calls": [{"function": {"name": "rechercher_formations", "arguments": {"specialite": "informatique"}}}]},
            {"role": "assistant", "content": "Voici une formation en informatique."},
        ])
        from .services import agent

        conv = Conversation.objects.create()
        with patch.object(agent.llm, "chat", side_effect=lambda *a, **k: next(replies)):
            result = agent.run(conv, "Quelles formations en informatique ?")
        self.assertEqual(result["text"], "Voici une formation en informatique.")
        self.assertEqual(result["cards"][0]["specialite"], "Développement sur Internet")
        self.assertEqual([m["role"] for m in conv.state["historique"]], ["user", "assistant", "tool", "assistant"])
