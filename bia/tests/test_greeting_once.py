"""Real reply assembly: one introduction, preserved answers and unchanged gates."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import unittest

import conversao
import conversation
import real_journey


NOW = datetime(2026, 10, 29, 6, tzinfo=timezone.utc)
POLICY = {"approved": True, "commission": 10, "commission_unit": "percent",
          "duration_fixed_months": 2, "duration_label": "2 meses", "version": "test-policy"}


def planner(reply, intent="converse"):
    def answer(_text, context):
        return {"reply": reply, "intent": intent, "claims": [], "next_phase": context["phase"],
                "topic_ids": [], "provider_status": "completed"}
    return answer


def turn(text, reply, state=None, *, real=True, intent="converse"):
    return conversation.handle(state or {}, text, planner(reply, intent), now=NOW,
                               real_mode=real, operation_policy=POLICY)


class GreetingOnceTests(unittest.TestCase):
    def test_actual_start_reply_collects_only_origin_not_content_and_shop(self):
        state = turn("oi", "O que você gostaria de conhecer?")["state"]
        actual = ("Legal saber do seu interesse em ser agenciado pela Amplify! Para te orientar direitinho, "
                  "preciso entender se você já cria conteúdo no TikTok e se usa o TikTok Shop por lá.")
        result = turn("Quero me agenciar", actual, state, intent="start")
        # Release 40: depois do "quero me agenciar", só o @ (sem nome nem origem).
        self.assertEqual(result["reply"], real_journey.PROMPTS["tiktok"])
        self.assertNotIn("Shop", result["reply"])
        self.assertEqual(result["reply"].count("?"), 1)

    def test_origin_doubt_keeps_answer_but_no_declarative_multifield_request(self):
        state = turn("Quero me agenciar", "Vamos começar.", intent="start")["state"]
        reply = ("A parceria oferece orientação e comunidade. Preciso entender se você cria conteúdo e se usa o TikTok Shop. "
                 "Me envie seu nome e seu @.")
        result = turn("Quais são os benefícios?", reply, state, intent="question")
        self.assertEqual(result["reply"], "A parceria oferece orientação e comunidade.\n\n" + real_journey.PROMPTS["tiktok"])

    def test_start_with_question_preserves_answer_before_one_current_field(self):
        state = turn("oi", "O que você gostaria de conhecer?")["state"]
        answer = "A taxa é de 10% sobre as comissões recebidas pelo creator, por 2 meses."
        result = turn("Quero me agenciar, me explica a comissão", answer + " Me informe nome e @.", state, intent="question")
        self.assertIn("10%", result["reply"])
        self.assertIn("comissões", result["reply"])
        self.assertIn("2 meses", result["reply"])
        self.assertNotRegex(result["reply"], r"10% (?:do|sobre o) GMV")
        self.assertTrue(result["reply"].endswith(real_journey.PROMPTS["tiktok"]))
        self.assertEqual(result["reply"].count("?"), 1)
        self.assertEqual(result["effects"], [])
        self.assertTrue(result["state"]["cycle"]["facts"]["interesse_agenciamento"])

    def test_single_question_mark_with_multiple_fields_is_replaced_by_one_field(self):
        state = turn("Quero me agenciar", "Vamos começar.", intent="start")["state"]
        reply = "A parceria inclui orientação. Qual é seu nome, seu @ e como conheceu a Amplify?"
        result = turn("Como funciona?", reply, state, intent="question")
        self.assertEqual(result["reply"], "A parceria inclui orientação.\n\n" + real_journey.PROMPTS["tiktok"])

    def test_equivalent_pending_question_is_not_duplicated(self):
        state = turn("Quero me agenciar", "Vamos começar.", intent="start")["state"]
        result = turn("Pode explicar?", "Posso te orientar. Como você conheceu a Amplify?", state, intent="question")
        self.assertEqual(result["reply"], "Posso te orientar.\n\n" + real_journey.PROMPTS["tiktok"])
        self.assertEqual(result["reply"].count("conheceu"), 0)

    def test_thematic_clarification_occupies_one_question_without_collection(self):
        state = turn("Quero me agenciar", "Vamos começar.", intent="start")["state"]
        reply = "Você está falando da comissão da Amplify ou da comissão do produto?"
        result = turn("Não entendi essa comissão", reply, state, intent="clarify")
        self.assertEqual(result["reply"], reply)
        self.assertEqual(result["state"]["cycle"]["phase"], "tiktok")

    def test_clarification_cannot_request_multiple_onboarding_fields(self):
        state = turn("Quero me agenciar", "Vamos começar.", intent="start")["state"]
        reply = "Posso te orientar. Você pode informar seu nome e seu @?"
        result = turn("Não entendi", reply, state, intent="clarify")
        self.assertEqual(result["reply"], "Posso te orientar.\n\n" + real_journey.PROMPTS["tiktok"])

    def test_colloquial_requests_without_question_mark_do_not_add_fields(self):
        state = turn("Quero me agenciar", "Vamos começar.", intent="start")["state"]
        for request in ("Me conta seu @.", "Me diz como conheceu a Amplify e seu nome."):
            with self.subTest(request=request):
                result = turn("Como funciona?", "A parceria oferece orientação. " + request, state, intent="question")
                self.assertEqual(result["reply"], "A parceria oferece orientação.\n\n" + real_journey.PROMPTS["tiktok"])

    def test_tiktok_collection_ignores_model_shop_and_other_fields(self):
        state = turn("Quero me agenciar", "Vamos começar.", intent="start")["state"]
        state = turn("Indicação", "Obrigado.", state, intent="continue")["state"]
        result = turn("Por que precisa do perfil?", "Ele permite consultar seu perfil. Informe seu nome e confirme se o Shop está ativo.",
                      state, intent="question")
        self.assertEqual(result["reply"], "Ele permite consultar seu perfil.\n\n" + real_journey.PROMPTS["tiktok"])
        self.assertNotIn("nome", result["reply"])
        self.assertNotIn("Shop", result["reply"])

    def test_intro_benefit_answer_does_not_collect_data_without_interest(self):
        state = turn("oi", "O que você gostaria de conhecer?")["state"]
        result = turn("Quais benefícios?", "A parceria inclui orientação e comunidade. Me informe seu nome e seu @. O que você gostaria de conhecer?",
                      state, intent="question")
        self.assertEqual(result["reply"], "A parceria inclui orientação e comunidade.\n\nO que você gostaria de conhecer?")
        self.assertEqual(result["state"]["cycle"]["phase"], "intro")

    def test_collection_filter_preserves_terms_links_and_later_explanation(self):
        body = ("A taxa é de 10% sobre as comissões, por 2 meses. "
                "Me informe seu nome e seu @. "
                "As condições completas estão em https://example.invalid/condicoes. "
                "Você precisa ter acesso ao TikTok Shop para participar.")
        expected = ("A taxa é de 10% sobre as comissões, por 2 meses. "
                    "As condições completas estão em https://example.invalid/condicoes. "
                    "Você precisa ter acesso ao TikTok Shop para participar.")
        self.assertEqual(conversation._answer_without_requests(body), expected)

    def test_real_compat_shop_state_does_not_ask_shop_after_known_handle(self):
        state = turn("Quero me agenciar", "Vamos começar.", intent="start")["state"]
        state["cycle"]["phase"] = "shop"
        state["cycle"]["facts"].update(origem_declarada="indicacao", tiktok_declarado="@fixture_creator")
        result = turn("Como funciona?", "A parceria inclui orientação. Me diga se seu Shop está ativo e se tem agência.", state, intent="question")
        self.assertNotIn("Me diga", result["reply"])
        self.assertEqual(result["state"]["cycle"]["phase"], "checking")
        self.assertEqual({effect["operation"] for effect in result["effects"]}, {"lookup", "precheck", "relationship"})

    def test_real_ai_complete_introduction_is_not_prefixed_twice(self):
        reply = "Oi! Eu sou a Bia, agente de IA da Amplify. 😊\n\nPosso te apresentar a parceria. O que você gostaria de conhecer?"
        result = turn("oi", reply)
        self.assertEqual(result["reply"], reply)
        self.assertEqual(result["reply"].count("Eu sou a Bia"), 1)
        self.assertEqual(result["state"]["cycle"]["phase"], "intro")
        self.assertEqual(result["buttons"], ["Conhecer a Amplify", "Quero me agenciar"])
        self.assertEqual(result["effects"], [])

    def test_real_ai_without_introduction_receives_one_system_identification(self):
        reply = "A Amplify reúne orientação, campanhas e comunidade. O que você gostaria de conhecer?"
        result = turn("oi", reply)
        self.assertEqual(result["reply"], "Oi! Eu sou a Bia, agente de IA da Amplify. 👋\n\n" + reply)
        self.assertEqual(result["reply"].count("Bia"), 1)
        self.assertNotIn("interesse_agenciamento", result["state"]["cycle"]["facts"])

    def test_name_only_introduction_keeps_answer_and_adds_only_ai_disclosure(self):
        reply = "Olá! Eu sou a Bia.\n\nPosso explicar a parceria. O que você gostaria de conhecer?"
        expected = "Olá! Eu sou a Bia.\nSou uma agente de IA da Amplify.\n\nPosso explicar a parceria. O que você gostaria de conhecer?"
        self.assertEqual(turn("oi", reply)["reply"], expected)
        self.assertEqual(expected.count("Bia"), 1)

    def test_natural_greeting_in_later_question_answer_is_preserved(self):
        state = turn("oi", "Posso te apresentar a Amplify. O que você gostaria de conhecer?")["state"]
        reply = "Oi! A parceria reúne orientação, campanhas e comunidade, conforme seu perfil. O que você busca desenvolver como creator?"
        result = turn("Como funciona a parceria?", reply, state, intent="question")
        self.assertEqual(result["reply"], reply)
        self.assertNotIn("Eu sou a Bia", result["reply"])
        self.assertEqual(result["effects"], [])
        self.assertEqual(result["buttons"], [])

    def test_later_mention_of_ai_is_not_mistaken_for_opening_identification(self):
        reply = "Posso te apresentar a Amplify.\n\nA IA pode esclarecer suas dúvidas. O que você gostaria de conhecer?"
        result = turn("oi", reply)
        self.assertTrue(result["reply"].startswith("Oi! Eu sou a Bia, agente de IA da Amplify."))
        self.assertTrue(result["reply"].endswith(reply))

    def test_word_ai_in_question_does_not_replace_identity_disclosure(self):
        reply = "Você já conversou com uma IA?"
        result = turn("oi", reply)
        self.assertEqual(result["reply"], "Oi! Eu sou a Bia, agente de IA da Amplify. 👋\n\n" + reply)

    def test_complete_introduction_with_artificial_intelligence_variant_preserves_all(self):
        reply = "Olá! Sou a Bia, agente de inteligência artificial da Amplify.\n\nO que você gostaria de conhecer?"
        self.assertEqual(turn("oi", reply)["reply"], reply)

    def test_helper_never_removes_terms_links_or_long_content(self):
        reply = ("Oi! Eu sou a Bia, agente de IA da Amplify. 😊\n\n"
                 "A taxa é de 10% sobre as comissões, com prazo de 2 meses.\n\n"
                 "Confira https://example.invalid/cadastro#s=opaque e os detalhes antes de autorizar. "
                 + "Condição importante. " * 25 + "Você autoriza?")
        self.assertEqual(conversation._opening_text(reply), reply)

    def test_opening_helper_is_idempotent(self):
        for text in ("O que você gostaria de conhecer?", "Oi! Eu sou a Bia.\n\nVamos conversar?",
                     "Sou a Bia, agente de IA da Amplify.\n\nO que você gostaria de conhecer?"):
            with self.subTest(text=text):
                assembled = conversation._opening_text(text)
                self.assertEqual(conversation._opening_text(assembled), assembled)

    def test_simulated_and_real_openings_use_same_identification_owner(self):
        reply = "Oi! Eu sou a Bia, agente de IA da Amplify. 😊\n\nO que você gostaria de conhecer?"
        self.assertEqual(turn("oi", reply, real=False)["reply"], reply)
        self.assertEqual(turn("oi", reply, real=True)["reply"], reply)

    def test_know_button_still_answers_without_collecting_or_confirming_interest(self):
        state = turn("oi", "O que você gostaria de conhecer?")["state"]
        reply = "A Amplify é uma agência para creators do TikTok Shop. O que você busca desenvolver como creator?"
        result = turn("Conhecer a Amplify", reply, state)
        self.assertEqual(result["reply"], reply)
        self.assertEqual(result["state"]["cycle"]["phase"], "intro")
        self.assertNotIn("interesse_agenciamento", result["state"]["cycle"]["facts"])
        self.assertEqual(result["effects"], [])
        self.assertEqual(result["buttons"], ["Como funciona", "Benefícios", "Comissão"])

    def test_commission_question_in_intro_has_free_reply_without_repeated_menu(self):
        state = turn("oi", "O que você gostaria de conhecer?")["state"]
        reply = "A taxa de agenciamento é de 10% sobre as comissões que você recebe como creator. O que você gostaria de entender sobre essa condição?"
        result = turn("Como funciona a comissão?", reply, state, intent="question")
        self.assertIn("10%", result["reply"])
        self.assertIn("comissões", result["reply"])
        self.assertIn("2 meses", result["reply"])
        self.assertNotRegex(result["reply"], r"10% (?:do|sobre o) GMV")
        self.assertLessEqual(result["reply"].count("?"), 1)
        self.assertEqual(result["buttons"], conversao.FIRST_BUTTONS)
        self.assertEqual(result["state"]["cycle"]["phase"], "intro")
        self.assertEqual(result["effects"], [])

    def test_explicit_menu_restores_two_objective_actions(self):
        state = turn("oi", "O que você gostaria de conhecer?")["state"]
        result = turn("menu", "Esta resposta não deve ser necessária.", state)
        self.assertEqual(result["buttons"], ["Conhecer a Amplify", "Quero me agenciar"])
        self.assertEqual(result["state"]["cycle"]["phase"], "intro")
        self.assertEqual(result["effects"], [])

    def test_lack_of_interest_does_not_keep_pressuring_with_start_button(self):
        state = turn("oi", "O que você gostaria de conhecer?")["state"]
        reply = "Tudo bem, podemos conversar sobre a proposta no seu ritmo. O que você gostaria de conhecer?"
        result = turn("Ainda não quero me agenciar; só queria entender a proposta.", reply, state)
        self.assertEqual(result["reply"], reply)
        self.assertEqual(result["buttons"], [])
        self.assertNotIn("interesse_agenciamento", result["state"]["cycle"]["facts"])
        self.assertEqual(result["effects"], [])

    def test_profile_change_keeps_objective_confirmation_buttons(self):
        state = turn("oi", "O que você gostaria de conhecer?")["state"]
        state["cycle"]["phase"] = "tiktok"
        state["cycle"]["facts"].update(interesse_agenciamento=True,origem_declarada="indicacao",tiktok_declarado="@perfil_antigo")
        result = turn("Meu perfil é @perfil_novo", "Vou conferir o que você informou.", state, intent="continue")
        self.assertEqual(result["buttons"], ["Confirmo", "Não confirmo"])
        self.assertEqual(result["state"]["cycle"]["facts"]["tiktok_declarado"], "@perfil_antigo")
        self.assertEqual(result["state"]["cycle"]["pending_profile_changes"], {"tiktok_declarado":"@perfil_novo"})
        self.assertEqual(result["effects"], [])

    def test_real_consent_and_waiting_paths_are_not_shortened_or_represented(self):
        state = turn("oi", "O que você gostaria de conhecer?")["state"]
        cycle = state["cycle"]
        cycle["phase"] = "consent_real"
        cycle["facts"]["tiktok_declarado"] = "@fixture_creator"
        body = real_journey._consent_prompt(cycle, POLICY)
        original = deepcopy(state)
        result = real_journey._finish(state, NOW, reply=body)
        self.assertEqual(result["reply"], body)
        self.assertEqual(result["state"]["cycle"]["invite_offer"], original["cycle"]["invite_offer"])
        self.assertIn("10%", result["reply"])
        self.assertIn("2 meses", result["reply"])
        self.assertIn("Posso te mandar o convite no TikTok", result["reply"])
        self.assertEqual(result["buttons"], conversao.CONSENT_BUTTONS)


if __name__ == "__main__":
    unittest.main()
