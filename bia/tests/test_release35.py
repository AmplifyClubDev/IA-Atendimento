"""Release 35: a closed list of pilot phones and the @ typed without "@"."""
from datetime import datetime, timezone
from pathlib import Path
import sys
import unittest

CANDIDATE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CANDIDATE))
import config
import contracts
import conversation

NOW = datetime(2026, 10, 28, 15, 0, tzinfo=timezone.utc)
POLICY = {"approved": True, "commission": 10, "commission_unit": "percent",
          "duration_fixed_months": 2, "duration_label": "2 meses", "version": "approved-test-policy"}
PRIMARY = "+5547991154859"
LEAD = "+5511987654321"
OTHER = "+5521912345678"
GATE = {"enabled": True, "provider": "chatwoot", "account_id": "1", "inbox_id": "3", "phone": PRIMARY}
# The live model text that produced the 30/10 10:55 contradiction.
RECEIVED = lambda text, context: {
    "reply": "Recebi seu @, obrigada! Vou consultar o perfil para verificar o próximo passo do agenciamento.",
    "intent": "continue", "claims": [], "next_phase": "tiktok", "topic_ids": [], "provider_status": "completed"}


def inbound(text, state=None, callback=None):
    return conversation.handle(state or {}, text, callback, now=NOW, real_mode=True, operation_policy=POLICY)


def at_handle_question():
    state = inbound("oi")["state"]
    state = inbound("Quero me agenciar", state)["state"]
    turn = inbound("Anúncio", state)
    assert turn["state"]["cycle"]["phase"] == "tiktok", turn["state"]["cycle"]["phase"]
    return turn["state"]


def event(phone, conversation_id="55719", message_id="900"):
    return {"provider": "chatwoot", "account_id": "1", "inbox_id": "3", "conversation_id": conversation_id,
            "message_id": message_id, "sender_phone": phone, "message_type": "incoming",
            "private": False, "text": "oi"}


class HandleWithoutAtTests(unittest.TestCase):
    def assert_accepted(self, typed, expected):
        turn = inbound(typed, at_handle_question(), RECEIVED)
        self.assertEqual(turn["state"]["cycle"]["facts"].get("tiktok_declarado"), expected)
        self.assertEqual(turn["state"]["cycle"]["phase"], "checking")
        self.assertIn("precheck", {job["operation"] for job in turn["effects"]})
        self.assertNotIn("Qual é o seu @", turn["reply"])

    def test_live_case_underscores_without_at_is_accepted_and_checked(self):
        self.assert_accepted("_mariiacunha_", "@_mariiacunha_")

    def test_same_handle_with_at_still_works(self):
        self.assert_accepted("@_mariiacunha_", "@_mariiacunha_")

    def test_plain_and_mixed_case_handles_are_normalized(self):
        self.assert_accepted("mariiacunha", "@mariiacunha")
        self.assert_accepted(" Mariia.Cunha ", "@mariia.cunha")

    def assert_rejected_honestly(self, typed):
        turn = inbound(typed, at_handle_question(), RECEIVED)
        self.assertNotIn("tiktok_declarado", turn["state"]["cycle"]["facts"])
        self.assertEqual(turn["state"]["cycle"]["phase"], "tiktok")
        self.assertFalse(turn["effects"])
        self.assertNotIn("Recebi", turn["reply"])
        self.assertNotIn("consultar", turn["reply"])
        self.assertEqual(turn["reply"].count("@seuperfil"), 1)

    def test_two_words_and_answer_words_are_not_handles(self):
        for typed in ("maria cunha", "não sei", "sim", "ok", "1234"):
            with self.subTest(typed=typed):
                self.assert_rejected_honestly(typed)
        # "menu" is a command with its own reply; it is still never a profile.
        turn = inbound("menu", at_handle_question(), RECEIVED)
        self.assertNotIn("tiktok_declarado", turn["state"]["cycle"]["facts"])
        self.assertFalse(turn["effects"])

    def test_question_is_not_taken_as_handle(self):
        turn = inbound("qual o meu @?", at_handle_question())
        self.assertNotIn("tiktok_declarado", turn["state"]["cycle"]["facts"])
        self.assertFalse(turn["effects"])

    @unittest.skip('Release 40 (auditoria de conversão de 01/11): a Bia não pergunta mais a origem nem o nome; o formulário pede os dois.')
    def test_bare_word_at_origin_question_stays_origin(self):
        state = inbound("Quero me agenciar", inbound("oi")["state"])["state"]
        turn = inbound("anuncio", state)
        self.assertNotIn("tiktok_declarado", turn["state"]["cycle"]["facts"])
        self.assertEqual(turn["state"]["cycle"]["facts"].get("origem_declarada"), "anuncio")


class PilotPhonesTests(unittest.TestCase):
    def test_empty_list_keeps_single_contact_pilot(self):
        self.assertEqual(contracts.parse_pilot_phones("", PRIMARY), (None, None))
        self.assertTrue(contracts.allow_inbound(GATE, event(PRIMARY, "26097")))
        self.assertFalse(contracts.allow_inbound(GATE, event(LEAD)))

    def test_listed_phones_are_allowed_and_others_ignored(self):
        phones, issue = contracts.parse_pilot_phones(f"{PRIMARY},{LEAD}", PRIMARY)
        self.assertIsNone(issue)
        gate = {**GATE, "phones": phones}
        self.assertTrue(contracts.allow_inbound(gate, event(PRIMARY, "26097")))
        self.assertTrue(contracts.allow_inbound(gate, event(LEAD)))
        self.assertTrue(contracts.allow_inbound(gate, event("+55 11 8765-4321")))  # mobile alias, same person
        self.assertFalse(contracts.allow_inbound(gate, event(OTHER)))
        self.assertEqual(contracts.pilot_phone(gate, "5511987654321"), LEAD)
        self.assertIsNone(contracts.pilot_phone(gate, OTHER))

    def test_invalid_lists_close_readiness(self):
        over_cap = ",".join([PRIMARY] + [f"+55119876543{i:02d}" for i in range(contracts.MAX_PILOT_PHONES)])
        for raw in (f"{LEAD}", f"{PRIMARY},{PRIMARY}", f"{PRIMARY},abc", f"{PRIMARY},+14155550100", over_cap,
                    f"{PRIMARY},+5547 99115-4859"):
            with self.subTest(raw=raw):
                phones, issue = contracts.parse_pilot_phones(raw, PRIMARY)
                self.assertIsNone(phones)
                self.assertIn(issue, {"pilot_phones_invalid", "pilot_phones_primary_missing"})

    def test_cap_is_accepted(self):
        at_cap = ",".join([PRIMARY] + [f"+55119876543{i:02d}" for i in range(contracts.MAX_PILOT_PHONES - 1)])
        phones, issue = contracts.parse_pilot_phones(at_cap, PRIMARY)
        self.assertIsNone(issue)
        self.assertEqual(len(phones), contracts.MAX_PILOT_PHONES)

    def test_config_exposes_list_or_reports_issue(self):
        base = {"V5_TEST_PHONE": PRIMARY, "V5_ENABLED": "true", "CHATWOOT_ACCOUNT_ID": "1", "CHATWOOT_INBOX_ID": "3"}
        ok = config.load_settings({**base, "V5_PILOT_PHONES": f"{PRIMARY},{LEAD}"})
        self.assertEqual(ok["gate"]["phones"], (PRIMARY, LEAD))
        self.assertEqual(ok["gate"]["phone"], PRIMARY)
        self.assertFalse([i for i in ok["readiness_issues"] if i.startswith("pilot_phones")])
        bad = config.load_settings({**base, "V5_PILOT_PHONES": LEAD})
        self.assertIn("pilot_phones_primary_missing", bad["readiness_issues"])
        self.assertNotIn("phones", bad["gate"])
        single = config.load_settings(base)
        self.assertNotIn("phones", single["gate"])


if __name__ == "__main__":
    unittest.main()


class LeadWebhookTests(unittest.TestCase):
    """A listed lead is answered in its own chat and recorded with its own phone."""

    def test_listed_lead_gets_reply_and_own_whatsapp_in_contact_sync(self):
        import tempfile
        from unittest.mock import patch
        from repository import Repository
        from server import create_app
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        repo = Repository(Path(tmp.name) / "t.sqlite3")
        sent, entries = [], []
        class Transport:
            def ready(self): return True
            def send_reply(self, event, text, buttons, key, **_):
                sent.append((event["conversation_id"], text)); return {"status": "accepted", "message_id": "901"}
        class Gateway:
            def register_contact(self, entry):
                entries.append(dict(entry))
                return {"creator_id": "22222222-2222-4222-8222-222222222222", "atendimento_id": entry["atendimento_id"],
                        "event_id": entry["event_id"], "revision": entry["revision"]}
        gate = {**GATE, "phones": (PRIMARY, LEAD)}
        settings = {"gate": gate, "webhook_token": "w" * 40, "conversation_enabled": True, "ai_enabled": True,
                    "contact_sync_enabled": True, "instance_id": "offline-test", "readiness_issues": [],
                    "state_dir": tmp.name}
        app = create_app(settings, repo, Transport(), planner=lambda *a, **k: None)
        app.extensions["v5_data_gateway"] = Gateway()
        payload = {"event": "message_created", "id": 5001, "account": {"id": 1}, "inbox": {"id": 3},
                   "conversation": {"id": 46814, "account_id": 1, "inbox_id": 3},
                   "sender": {"id": 77, "type": "contact", "phone_number": LEAD},
                   "message_type": "incoming", "private": False, "content": "Quero me agenciar"}
        response = app.test_client().post("/webhook/chatwoot", json=payload, headers={"X-Amplify-Webhook-Token": "w" * 40})
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertTrue(sent and sent[0][0] == 46814, sent)
        self.assertTrue(entries)
        self.assertTrue(all(e["whatsapp"] == LEAD.lstrip("+") for e in entries), [e["whatsapp"] for e in entries])
        outsider = {**payload, "id": 5002, "sender": {"id": 78, "type": "contact", "phone_number": OTHER},
                    "conversation": {"id": 46815, "account_id": 1, "inbox_id": 3}}
        response = app.test_client().post("/webhook/chatwoot", json=outsider, headers={"X-Amplify-Webhook-Token": "w" * 40})
        self.assertEqual(response.status_code, 202)
        self.assertEqual(len([s for s in sent if s[0] == 46815]), 0)


class FormUrlButtonTests(unittest.TestCase):
    """Release 37: the public form link goes as a WhatsApp URL button, mirrored privately."""

    def transport(self, cloud_answer):
        from transport import ChatwootTransport
        calls = []
        def http(*, method, url, headers=None, json_body=None, timeout=None):
            calls.append((method, url, json_body))
            if url.startswith("https://graph.facebook.com/"):
                if isinstance(cloud_answer, Exception):
                    raise cloud_answer
                return cloud_answer
            if method == "GET":
                return {"id": 46814, "account_id": 1, "inbox_id": 3, "can_reply": True,
                        "meta": {"sender": {"id": 77, "phone_number": LEAD}}}
            return {"id": 999}
        gate = {**GATE, "phones": (PRIMARY, LEAD)}
        t = ChatwootTransport("https://chatwoot.t2ffoz.easypanel.host", "tok", gate, http=http,
                              cloud={"token": "cloud-token", "phone_number_id": "123456789012"})
        return t, calls

    def lead_event(self):
        return {"provider": "chatwoot", "account_id": "1", "inbox_id": "3", "conversation_id": "46814",
                "contact_id": "77", "message_id": "5", "sender_phone": LEAD, "message_type": "incoming",
                "private": False, "text": "aceitei"}

    def test_form_link_is_sent_as_button_and_mirrored_as_private_note(self):
        import real_journey
        t, calls = self.transport({"messages": [{"id": "wamid.X"}]})
        text = "Seu convite foi enviado! 🎉\n\nFaça seu cadastro por aqui:\n" + real_journey.PUBLIC_FORM_URL
        receipt = t.send_reply(self.lead_event(), text, [], "k:1")
        self.assertEqual(receipt["status"], "accepted")
        cloud = [c for c in calls if c[1].startswith("https://graph.facebook.com/")]
        self.assertEqual(len(cloud), 1)
        self.assertEqual(cloud[0][2]["interactive"]["type"], "cta_url")
        self.assertEqual(cloud[0][2]["interactive"]["action"]["parameters"]["url"], real_journey.PUBLIC_FORM_URL)
        self.assertEqual(cloud[0][2]["to"], LEAD.lstrip("+"))
        self.assertNotIn(real_journey.PUBLIC_FORM_URL, cloud[0][2]["interactive"]["body"]["text"])
        note = [c for c in calls if c[0] == "POST" and "chatwoot" in c[1]][-1][2]
        self.assertTrue(note["private"])

    def test_cloud_failure_falls_back_to_public_text_with_link(self):
        import real_journey
        t, calls = self.transport(RuntimeError("cloud down"))
        text = "Faça seu cadastro por aqui:\n" + real_journey.PUBLIC_FORM_URL
        self.assertEqual(t.send_reply(self.lead_event(), text, [], "k:2")["status"], "accepted")
        message = [c for c in calls if c[0] == "POST" and "chatwoot" in c[1]][-1][2]
        self.assertFalse(message["private"])
        self.assertIn(real_journey.PUBLIC_FORM_URL, message["content"])

    def test_messages_without_form_link_never_touch_cloud(self):
        t, calls = self.transport({"messages": [{"id": "wamid.X"}]})
        t.send_reply(self.lead_event(), "Oi! Como posso ajudar?", [], "k:3")
        self.assertFalse([c for c in calls if c[1].startswith("https://graph.facebook.com/")])
