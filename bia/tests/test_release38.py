"""Release 38: nome uma vez, textos da jornada aprovados, botão do cadastro sem repetir, convite que não aparece."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import real_journey as journey
import receipt_grounding
from test_real_journey import inbound

URL = journey.PUBLIC_FORM_URL


def cycle(**extra):
    return {"phase": "form", "facts": {}, "real_operations": {}, **extra}


class FormPromptTests(unittest.TestCase):
    def test_linked_lead_gets_name_and_link(self):
        c = cycle(facts={"nome_declarado": "Gabriela Santana"}, real_operations={"relationship": {"status": "linked"}})
        text = journey._phase_prompt(c)
        self.assertTrue(text.startswith("Tudo certo com seu agenciamento, Gabriela! 🎉"))
        self.assertIn("por aqui:\n" + URL, text)  # o transporte troca por botão
        self.assertIn("acesso à comunidade", text)

    def test_not_linked_yet_never_claims_agency(self):
        text = journey._phase_prompt(cycle(real_operations={"invite": {"status": "sent"}}))
        self.assertNotIn("Tudo certo", text)
        self.assertTrue(text.startswith("Assim que aceitar o convite"))
        self.assertIn(URL, text)

    def test_blocked_is_human_and_uses_the_name(self):
        self.assertTrue(journey._phase_prompt(cycle(phase="blocked")).startswith("Não consegui confirmar seu perfil"))
        named = journey._phase_prompt(cycle(phase="blocked", facts={"nome_declarado": "Priscila"}))
        self.assertTrue(named.startswith("Priscila, não consegui confirmar seu perfil"))
        self.assertEqual(named.count("?"), 1)


class FormLinkRepeatTests(unittest.TestCase):
    def test_link_is_not_repeated_while_it_is_in_the_last_replies(self):
        state = {"history": [{"direction": "outbound", "text": "Faça seu cadastro por aqui:\n" + URL},
                             {"direction": "inbound", "text": "Benefícios"}]}
        self.assertTrue(journey._form_link_recent(state, URL))
        state["history"] += [{"direction": "outbound", "text": "resposta %d" % i} for i in range(3)]
        self.assertFalse(journey._form_link_recent(state, URL))


class NameQuestionTests(unittest.TestCase):
    @unittest.skip('Release 40 (auditoria de conversão de 01/11): a Bia não pergunta mais a origem nem o nome; o formulário pede os dois.')
    def test_name_is_asked_once_then_used(self):
        asked = inbound("Quero me agenciar")
        self.assertTrue(asked["reply"].endswith(journey.NAME_QUESTION))
        named = inbound("me chamo vitor", asked["state"])
        self.assertTrue(named["reply"].startswith("Prazer, Vitor!"))
        self.assertEqual(named["state"]["cycle"]["facts"]["nome_declarado"].lower(), "vitor")  # guardado como digitado
        self.assertNotIn(journey.NAME_QUESTION, named["reply"])


class InviteNotFoundTests(unittest.TestCase):
    def test_after_an_invite_request_the_lead_is_told_where_to_look(self):
        state = {"cycle": {"real_operations": {"invite": {"status": "verification_pending"}}}}
        text = receipt_grounding._relationship_status(state, None)
        self.assertIn("*Parcerias* ou *Notificações*", text)
        self.assertNotIn("Ainda não tenho confirmação de envio", text)

    def test_without_any_invite_request_it_stays_neutral(self):
        text = receipt_grounding._relationship_status({"cycle": {}}, None)
        # Release 39: no "no confirmation" boilerplate; the answer gives the next step.
        self.assertNotIn("não tenho confirmação", text)
        self.assertIn("Me manda seu @", text)


if __name__ == "__main__":
    unittest.main()
