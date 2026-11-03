"""Context-aware turns from persisted state and accepted outbox; offline only."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import conversation
import engine
import guided_ai
import real_journey as journey
from repository import Repository
from server import create_app

NOW = datetime(2026, 10, 28, 23, tzinfo=timezone.utc)


def plan(phase, reply="A parceria inclui orientação para creators.", intent="question"):
    return dict(reply=reply, intent=intent, claims=[], next_phase=phase, topic_ids=[], provider_status="completed")


def real_state(phase="origin", **facts):
    state = engine._state({})
    cycle = engine._open(state, NOW)
    cycle.update(mode="real", phase=phase)
    cycle["facts"].update(interesse_agenciamento=True, **facts)
    return state


class ContextualTurnTests(unittest.TestCase):
    def test_known_origin_recomputes_pending_handle_before_model(self):
        captured = []
        state = real_state("origin", origem_declarada="indicacao")
        result = journey.handle_real(state, "Como funciona?", lambda text, context:
            captured.append(deepcopy(context)) or plan("tiktok"), now=NOW)
        self.assertEqual(captured[0]["phase"], "tiktok")
        self.assertEqual(captured[0]["next_action"]["field"], "tiktok_declarado")
        self.assertIn("@", result["reply"])
        self.assertNotIn("Como você conheceu", result["reply"])
        self.assertEqual(result["state"]["cycle"]["facts"], state["cycle"]["facts"])

    def test_known_handle_moves_parked_shop_to_checks_and_never_duplicates_work(self):
        captured = []
        state = real_state("shop", origem_declarada="indicacao", tiktok_declarado="@contexto")
        callback = lambda text, context: captured.append(deepcopy(context)) or plan(context["phase"])
        first = journey.handle_real(state, "Não sei", callback, now=NOW)
        self.assertEqual(captured[0]["next_action"]["kind"], "wait_for_provider")
        self.assertEqual(captured[0]["phase"], "checking")
        self.assertEqual({job["operation"] for job in first["effects"]}, {"lookup", "precheck", "relationship"})
        second = journey.handle_real(first["state"], "E a comissão?", callback, now=NOW + timedelta(seconds=1))
        self.assertEqual(second["effects"], [])
        self.assertEqual(len(second["state"]["effects"]), 3)
        self.assertEqual({row["operation"] for row in captured[1]["pending_operations"]}, {"lookup", "precheck", "relationship"})
        self.assertNotIn("Shop Creator está ativo?", second["reply"])

    def test_real_clarification_is_not_erased_or_replaced_by_onboarding_question(self):
        text = "Você está falando da comissão da Amplify ou da comissão do produto?"
        result = journey.handle_real(real_state(), "Qual comissão", lambda *_: plan("origin", text, "clarify"), now=NOW)
        self.assertEqual(result["reply"], text)
        self.assertEqual(result["reply"].count("?"), 1)
        self.assertNotIn("Como você conheceu", result["reply"])

    def test_waiting_provider_answers_question_without_reasking_known_handle(self):
        state = real_state("checking", origem_declarada="indicacao", tiktok_declarado="@contexto")
        answer = "Posso explicar os benefícios da parceria. Qual é o seu @ do TikTok?"
        result = journey.handle_real(state, "Quais benefícios?", lambda *_: plan("checking", answer), now=NOW)
        self.assertIn("Posso explicar os benefícios da parceria.", result["reply"])
        self.assertIn("Estou conferindo seu perfil e o vínculo no TikTok.", result["reply"])
        self.assertNotIn("Qual é o seu @", result["reply"])
        # After work is already queued, the FAQ body survives with no new prompt.
        result = journey.handle_real(result["state"], "Quais benefícios?", lambda *_: plan("checking", answer), now=NOW)
        self.assertEqual(result["reply"], "Posso explicar os benefícios da parceria.")
        self.assertEqual(result["effects"], [])

    def test_context_operations_are_bound_to_cycle_profile_and_never_include_raw_evidence(self):
        state = real_state("checking", origem_declarada="indicacao", tiktok_declarado="@contexto")
        cycle = state["cycle"]
        record = dict(operation="precheck", status="eligible", confirmed=True, creator="@contexto",
                      cycle_id=cycle["id"], job_id="proof", observed_at=NOW.isoformat(), evidence={"secret": "NEVER_PROJECT"})
        cycle["real_operations"] = {"precheck": record, "relationship": {**record, "operation": "relationship", "status": "linked", "creator": "@other"}}
        state["effects"]["proof"] = dict(type="tiktok_operation", operation="precheck", status="done", creator="@contexto", cycle_id=cycle["id"])
        context = journey._turn_guidance(state, NOW)
        self.assertEqual(context["operations"], [dict(operation="precheck", status="eligible", proven=True, source="provider_result")])
        self.assertNotIn("NEVER_PROJECT", repr(context))

    def test_profile_change_and_consent_pending_are_explicit_context_not_model_permissions(self):
        state = real_state("consent_real", origem_declarada="indicacao", tiktok_declarado="@contexto")
        state["cycle"].update(pending_profile_changes={"tiktok_declarado": "@novo"}, invite_offer={"policy_hash": "test"})
        context = journey._turn_guidance(state, NOW)
        self.assertEqual(context["next_action"]["kind"], "confirm_profile_change")
        self.assertIsNone(context["next_action"]["field"])
        self.assertTrue(context["consent_pending"])
        self.assertEqual(context["pending_profile_changes"], {"tiktok_declarado": "@novo"})

    def test_guided_context_excludes_planned_reply_and_preserves_real_guidance(self):
        state = real_state("checking", tiktok_declarado="@contexto")
        cycle = state["cycle"]
        context = dict(real_mode=True, phase="checking", facts=cycle["facts"], cycle={"id": cycle["id"]},
            history=[dict(cycle_id=cycle["id"], direction="outbound", text="PLANNED_NOT_SENT", at=NOW.isoformat()),
                     dict(cycle_id=cycle["id"], direction="inbound", text="Não sei", at=NOW.isoformat())],
            current_question=journey.PROMPTS["checking"], next_action=dict(kind="wait_for_provider", field=None, question=""),
            allowed_actions=["question", "send_credentials"], pending_operations=[dict(operation="precheck", status="pending", token="SECRET")],
            operations=[dict(operation="lookup", status="observed", proven=False, evidence={"key": "SECRET"})],
            delivery_context=dict(source="outbox", accepted_history=[], last_accepted_reply=None, latest_attempt_status="outcome_unknown"))
        clean = guided_ai._context(context)
        self.assertNotIn("PLANNED_NOT_SENT", repr(clean))
        self.assertNotIn("SECRET", repr(clean))
        self.assertEqual(clean["last_accepted_source"], "unknown")
        self.assertEqual(clean["latest_attempt_status"], "outcome_unknown")
        self.assertEqual(clean["allowed_actions"], ["question"])
        self.assertEqual(clean["next_action"]["kind"], "wait_for_provider")
        self.assertEqual(clean["pending_operations"], [dict(operation="precheck", status="pending")])

    def test_accepted_payload_becomes_model_history_and_sensitive_links_are_redacted(self):
        context = dict(real_mode=True, phase="tiktok", facts={}, history=[],
            delivery_context=dict(source="outbox", latest_attempt_status="accepted",
                accepted_history=[dict(direction="outbound", text="Veja https://private.invalid/form segredo@example.invalid", at=NOW.isoformat())],
                last_accepted_reply=dict(text="Qual é seu @?", at=NOW.isoformat())))
        clean = guided_ai._context(context)
        self.assertEqual(clean["last_accepted_reply"], "Qual é seu @?")
        self.assertEqual(clean["last_accepted_source"], "chatwoot_accepted")
        self.assertNotIn("private.invalid", repr(clean))
        self.assertNotIn("segredo@example.invalid", repr(clean))


class DeliveryProjectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="contextual-", dir=Path(__file__).resolve().parents[1] / "data")
        self.addCleanup(self.temp.cleanup)
        self.repo = Repository(Path(self.temp.name) / "state.sqlite3")

    def save_reply(self, key, conv, text, status, at=NOW):
        with patch("repository._now", return_value=at.isoformat()):
            self.repo.reserve_event(key, conv, key)
            self.repo.prepare_reply(key, conv, {}, key + ":reply", {"text": text, "buttons": []})
            self.repo.finish_outbox(key + ":reply", status, {"status": status, "message_id": "1"})

    def test_last_accepted_is_distinct_from_later_failed_or_unknown_attempt(self):
        self.save_reply("a", "c", "Aceita pelo Chatwoot", "accepted")
        self.save_reply("b", "c", "Não confirmada", "outcome_unknown", NOW + timedelta(seconds=1))
        self.save_reply("other", "other", "Contato diferente", "accepted", NOW + timedelta(seconds=2))
        context = self.repo.conversation_delivery_context("c", (NOW - timedelta(seconds=1)).isoformat())
        self.assertEqual(context["latest_attempt_status"], "outcome_unknown")
        self.assertEqual(context["last_accepted_reply"]["text"], "Aceita pelo Chatwoot")
        self.assertEqual(len(context["accepted_history"]), 1)
        self.assertNotIn("Contato diferente", repr(context))

    def test_old_cycle_replies_are_not_projected_into_new_cycle(self):
        self.save_reply("a", "c", "Ciclo anterior", "accepted")
        context = self.repo.conversation_delivery_context("c", (NOW + timedelta(hours=1)).isoformat())
        self.assertIsNone(context["last_accepted_reply"])
        self.assertEqual(context["accepted_history"], [])

    def test_server_injects_actual_accepted_context_and_duplicate_event_never_plans_again(self):
        contexts = []
        class Client:
            def configuration(self, *args): return {"configured": True}
        class Gateway:
            def register_contact(self, entry):
                return dict(creator_id="22222222-2222-4222-8222-222222222222", atendimento_id=entry["atendimento_id"],
                            event_id=entry["event_id"], revision=entry["revision"])
        class Transport:
            def ready(self): return True
            def send_reply(self, *args): return {"status": "accepted", "message_id": "9"}
        settings = dict(gate=dict(enabled=True, provider="chatwoot", account_id="1", inbox_id="3", phone="+5547991154859"),
            webhook_token="offline-test-token-long-enough", state_dir=self.temp.name, readiness_issues=[], instance_id="test",
            conversation_enabled=True, ai_enabled=True, contact_sync_enabled=True, tiktok_mode="real", real_worker_enabled=True)
        def planner(text, context, _settings):
            contexts.append(deepcopy(context))
            return plan("intro", "A Amplify orienta creators. O que você busca na parceria?", "converse")
        app = create_app(settings, self.repo, Transport(), planner=planner, real_client=Client(), real_guard=lambda *_: {"allowed": True})
        app.extensions["v5_data_gateway"] = Gateway()
        client = app.test_client()
        def post(identifier):
            body = dict(event="message_created", id=identifier, content="oi", message_type="incoming", private=False,
                account={"id": 1}, inbox={"id": 3}, conversation={"id": 26097, "account_id": 1, "inbox_id": 3,
                    "meta": {"sender": {"id": 3, "type": "contact", "phone_number": "+5547991154859"}}},
                sender={"id": 3, "type": "contact", "phone_number": "+5547991154859"})
            return client.post("/webhook/chatwoot", json=body, headers={"X-Amplify-Webhook-Token": settings["webhook_token"]})
        self.assertEqual(post(1).get_json()["status"], "completed")
        self.assertEqual(post(2).get_json()["status"], "completed")
        self.assertIsNone(contexts[0]["delivery_context"]["last_accepted_reply"])
        self.assertIn("agente de IA", contexts[1]["delivery_context"]["last_accepted_reply"]["text"])
        self.assertTrue(post(2).get_json()["duplicate"])
        self.assertEqual(len(contexts), 2)


if __name__ == "__main__":
    unittest.main()
