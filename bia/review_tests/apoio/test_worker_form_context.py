"""Actual form factory from a real worker tick, without request/app context."""
from datetime import datetime, timedelta, timezone
from copy import deepcopy
import inspect
import unittest
from unittest.mock import patch

from flask import Flask, current_app, has_app_context
from forms import register_forms
from real_operations import build_jobs
from server import create_app
import test_real_executor as fixture


class Transport:
    def __init__(self):
        self.calls = []
    def ready(self):
        return True
    def send_reply(self, *args):
        self.calls.append(args)
        return {"status": "accepted", "message_id": "999"}


class WorkerFormContextTests(unittest.TestCase):
    def setUp(self):
        self.case = fixture.ExecutorTests()
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        state, effect = self.case.state("relationship")
        now = datetime.now(timezone.utc)
        state["cycle"].update(opened_at=now.isoformat(), last_inbound_at=now.isoformat(),
            expires_at=(now + timedelta(hours=24)).isoformat())
        state["cycle"]["facts"].update(interesse_agenciamento=True, origem_declarada="indicacao")
        self.deadline = state["cycle"]["expires_at"]
        self.case.repository.reserve_event("chatwoot:1:777", fixture.CONV, "fixture")
        self.case.certify_projection(state)
        self.jobs = build_jobs(fixture.EVENT, state, [effect])
        self.case.repository.prepare_reply("chatwoot:1:777", fixture.CONV, state, "fixture", None, real_jobs=self.jobs)
        settings = {**self.case.settings, "webhook_token": "w" * 40, "form_secret": "s" * 40,
            "public_url": "https://form.invalid", "conversation_enabled": True,
            "ai_enabled": True, "instance_id": "offline-test", "readiness_issues": []}
        self.client = fixture.FakeClient({"operation": "relationship", "creator": "alice", "status": "linked",
            "confirmed": True, "observed_at": now.isoformat(),
            "evidence": {"source": "partner_relations", "relation_id": "123", "status": "vinculado",
                "tiktok_status": 1, "fresh": True, "complete": True}})
        self.transport = Transport()
        self.contexts = []
        def planner(text, context, _settings):
            self.contexts.append(deepcopy(context))
            return {"reply": "Vou confirmar o resultado dessa consulta.", "intent": "question", "claims": [],
                "next_phase": context["phase"], "topic_ids": [], "provider_status": "completed"}
        self.app = create_app(settings, self.case.repository, self.transport,
            real_client=self.client, real_guard=self.case.guard, planner=planner)
        self.app.extensions["v5_data_gateway"] = fixture.FakeGateway()
        register_forms(self.app, settings, self.case.repository)
        self.executor = self.app.extensions["v5_real_executor"]
        self.token = settings["webhook_token"]

    def assert_settled_once(self):
        state = self.case.repository.load_session(fixture.CONV)
        self.assertEqual(state["cycle"]["phase"], "form")
        self.assertEqual(state["cycle"]["expires_at"], self.deadline)
        self.assertEqual(state["creator_id"], fixture.CREATOR_ID)
        self.assertEqual(self.case.repository.real_job(self.jobs[0]["job_key"])["status"], "completed")
        with self.app.extensions["v5_forms_store"].db() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM v5_forms").fetchone()[0], 1)
        self.assertEqual(len(self.client.calls), 1)
        self.assertEqual(self.client.calls[0][0], "relationship")
        self.assertEqual(len(self.transport.calls), 1)
        self.assertIn("https://form.invalid/", self.transport.calls[0][1])

    def test_linked_worker_outside_app_context_completes_with_one_real_form(self):
        self.assertFalse(has_app_context())
        self.assertEqual(self.executor.tick()["status"], "completed")
        self.assertFalse(has_app_context())
        self.assert_settled_once()
        # Another tick cannot duplicate the form, provider call or reply.
        self.assertEqual(self.executor.tick()["status"], "idle")
        self.assert_settled_once()

    def test_worker_uses_owning_app_and_restores_an_existing_other_context(self):
        other = Flask("unrelated-test-app")
        with other.app_context():
            self.assertIs(current_app._get_current_object(), other)
            self.assertEqual(self.executor.tick()["status"], "completed")
            self.assertIs(current_app._get_current_object(), other)
        self.assertFalse(has_app_context())
        self.assert_settled_once()

    def post_question(self, identifier):
        body = {"event": "message_created", "id": identifier, "content": "E agora?",
            "message_type": "incoming", "private": False, "account": {"id": 1}, "inbox": {"id": 3},
            "conversation": {"id": 26097, "account_id": 1, "inbox_id": 3,
                "meta": {"sender": {"id": 3, "type": "contact", "phone_number": "+5547991154859"}}},
            "sender": {"id": 3, "type": "contact", "phone_number": "+5547991154859"}}
        return self.app.test_client().post("/webhook/chatwoot", json=body,
            headers={"X-Amplify-Webhook-Token": self.token})

    def test_terminal_jobs_with_stale_pending_effect_are_uncertain_in_ai_context(self):
        for index, status in enumerate(("outcome_unknown", "cancelled", "completed"), 778):
            with self.subTest(status=status):
                self.case.repository.finish_real_job(self.jobs[0]["job_key"], status, datetime.now(timezone.utc).isoformat())
                self.assertEqual(self.post_question(index).get_json()["status"], "completed")
                context = self.contexts[-1]
                row = next(row for row in context["pending_operations"] if row["operation"] == "relationship")
                self.assertEqual(row["status"], "outcome_unknown")
                self.assertIn("não há confirmação de consulta em andamento", context["current_question"])
        self.assertEqual(self.client.calls, [])

    def test_only_exactly_bound_live_job_is_projected_as_pending(self):
        original = self.case.repository.real_job(self.jobs[0]["job_key"])
        self.assertEqual(self.post_question(778).get_json()["status"], "completed")
        row = next(row for row in self.contexts[-1]["pending_operations"] if row["operation"] == "relationship")
        self.assertEqual(row["status"], "pending")
        # A row for a different conversation/cycle/profile/effect never makes
        # this contact's stale effect look like a running provider operation.
        for index, changes in enumerate(({"conversation_key": "other"}, {"cycle_id": "other"},
                                        {"creator": "other"}, {"effect_id": "other"}), 779):
            foreign = {**original, **changes, "status": "running"}
            with patch.object(self.case.repository, "real_job", return_value=foreign):
                self.assertEqual(self.post_question(index).get_json()["status"], "completed")
            row = next(row for row in self.contexts[-1]["pending_operations"] if row["operation"] == "relationship")
            self.assertEqual(row["status"], "outcome_unknown")

    def fail_original_application(self):
        before = self.case.repository.load_session(fixture.CONV)
        scoped = self.executor.apply_result
        # Exercise the original missing-app-context failure in the actual local
        # form factory, with the deterministic form operation already reserved.
        self.executor.apply_result = inspect.getclosurevars(scoped).nonlocals["apply_real"]
        self.assertEqual(self.executor.tick()["status"], "application_outcome_unknown")
        self.executor.apply_result = scoped
        self.assertEqual(self.case.repository.load_session(fixture.CONV), before)
        with self.case.repository._connection() as db:
            row = db.execute("SELECT operation_key,event_key FROM operations WHERE kind='generate_form_link'").fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(self.case.repository.get_operation(row["operation_key"])["status"], "outcome_unknown")
        self.assertEqual(self.case.repository.event(row["event_key"])["status"], "outcome_unknown")
        self.assertEqual(self.case.repository.outbox(row["event_key"]), [])
        # Release 43: the lead hears one honest notice instead of silence; the result itself is never replayed.
        import conversao
        self.assertEqual([call[1] for call in self.transport.calls], [conversao.OPERATION_FALLBACK])
        self.transport.calls.clear()
        return dict(row), before

    def test_original_failure_same_revision_reconciles_local_form_after_fresh_read_once(self):
        old, before = self.fail_original_application()
        recovery = self.case.repository.recover_real_jobs(datetime.now(timezone.utc).isoformat())
        self.assertEqual(recovery["requeued_reads"], 1)
        self.assertEqual(self.case.repository.load_session(fixture.CONV)["revision"], before["revision"])
        self.client.result["observed_at"] = datetime.now(timezone.utc).isoformat()
        self.assertEqual(self.executor.tick()["status"], "completed")
        state = self.case.repository.load_session(fixture.CONV)
        self.assertEqual(state["cycle"]["phase"], "form")
        self.assertEqual(state["cycle"]["expires_at"], self.deadline)
        self.assertEqual(self.case.repository.real_job(self.jobs[0]["job_key"])["attempts"], 2)
        operation = self.case.repository.get_operation(old["operation_key"])
        self.assertEqual(operation["status"], "completed")
        self.assertEqual(operation["result"]["reconciled_from"], old["event_key"])
        # The old uncertain application remains an audit fact; no old outbox is
        # created or replayed. The new read/application owns the one new reply.
        self.assertEqual(self.case.repository.event(old["event_key"])["status"], "outcome_unknown")
        self.assertEqual(self.case.repository.outbox(old["event_key"]), [])
        with self.app.extensions["v5_forms_store"].db() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM v5_forms").fetchone()[0], 1)
        self.assertEqual([call[0] for call in self.client.calls], ["relationship", "relationship"])
        self.assertEqual(len(self.transport.calls), 1)
        self.assertEqual(self.executor.tick()["status"], "idle")

    def test_previous_application_with_any_outbox_cannot_resume_local_form(self):
        old, before = self.fail_original_application()
        self.case.repository.prepare_reply(old["event_key"], fixture.CONV, before, "uncertain-old-reply", {"text": "unknown", "buttons": []})
        self.assertEqual(self.case.repository.recover_real_jobs(datetime.now(timezone.utc).isoformat())["requeued_reads"], 0)
        # Even if a caller wrongly queues the read, the independent form guard
        # still refuses to reuse the previous operation with an uncertain send.
        with self.case.repository._connection() as db:
            db.execute("UPDATE real_jobs SET status='queued',next_run_at=? WHERE job_key=?",
                (datetime.now(timezone.utc).isoformat(), self.jobs[0]["job_key"]))
        self.client.result["observed_at"] = datetime.now(timezone.utc).isoformat()
        self.assertEqual(self.executor.tick()["status"], "application_outcome_unknown")
        self.assertEqual(self.transport.calls, [])
        with self.app.extensions["v5_forms_store"].db() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM v5_forms").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
