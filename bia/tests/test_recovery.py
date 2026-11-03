"""One-conversation source recovery with fake HTTP only; no provider effects."""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import recovery

NOW = datetime(2026, 10, 28, 23, 0, tzinfo=timezone.utc)
SOURCE = "chatwoot:1:312830"
CREATOR = "b3e0fa4b-6d0d-48ed-b011-05f465aaff00"
CYCLE = "86b23000-0000-4000-8000-000000000001"
PHONE = "+5547991154859"
TEXT = "Não sei se a conta está ativa."


class Repository:
    def __init__(self, state, source, receipt):
        self.state, self.source, self.receipt = deepcopy(state), deepcopy(source), deepcopy(receipt)
        self.reserved = None

    def load_session(self, key):
        assert key == recovery.CONVERSATION
        return deepcopy(self.state)

    def event(self, key):
        if key == SOURCE:
            return deepcopy(self.source)
        return deepcopy(self.reserved)

    def get_operation(self, key):
        return deepcopy(self.receipt) if key == SOURCE + ":contact:28" else None


class Transport:
    token = "fixture-token-not-a-credential"
    def __init__(self, detail, messages):
        self.detail, self.pages, self.calls = detail, [messages], []

    def ready(self): return True

    def _conversation_url(self, event):
        assert event == {"account_id": "1", "conversation_id": "26097"}
        return "https://chatwoot.example.test/api/v1/accounts/1/conversations/26097"

    def http(self, **request):
        self.calls.append(deepcopy(request))
        assert request["method"] == "GET"
        assert "/accounts/1/conversations/26097" in request["url"]
        if "/messages" in request["url"]:
            return {"payload": deepcopy(self.pages.pop(0))}
        return deepcopy(self.detail)


def fixture():
    gate = {"enabled": True, "provider": "chatwoot", "account_id": "1", "inbox_id": "3", "phone": PHONE}
    detail = {"id": 26097, "account_id": 1, "inbox_id": 3,
              "meta": {"sender": {"id": 3, "type": "contact", "phone_number": PHONE}}}
    timestamp = int(datetime(2026, 10, 28, 22, 53, 53, tzinfo=timezone.utc).timestamp())
    message = {"id": 312830, "conversation_id": 26097, "inbox_id": 3, "message_type": 0,
               "private": False, "content": TEXT, "created_at": timestamp,
               "sender": {"id": 3, "type": "contact", "phone_number": PHONE}}
    state = {"revision": 28, "creator_id": CREATOR, "processed_inbound": [SOURCE], "effects": {},
             "history": [{"direction": "inbound", "text": TEXT, "at": "2026-10-28T22:53:54Z", "cycle_id": CYCLE}],
             "cycle": {"id": CYCLE, "mode": "real", "status": "open", "phase": "shop",
                       "last_inbound_at": "2026-10-28T22:53:54Z", "expires_at": "2026-10-29T22:53:54Z",
                       "facts": {"interesse_agenciamento": True, "origem_declarada": "indicacao",
                                 "tiktok_declarado": "@mary_oficiall83"}},
             "contact_sync_proof": {"creator_id": CREATOR, "atendimento_id": CYCLE, "event_id": SOURCE, "revision": 28}}
    event = recovery._source_event(message, detail, gate)
    digest = hashlib.sha256(json.dumps(event, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    source = {"conversation_key": recovery.CONVERSATION, "status": "completed", "digest": digest,
              "created_at": "2026-10-28T22:53:53.500000+00:00"}
    receipt = {"status": "completed", "result": deepcopy(state["contact_sync_proof"])}
    repository, transport = Repository(state, source, receipt), Transport(detail, [message])
    callbacks, controls = [], []
    def callback(**kwargs):
        callbacks.append(deepcopy(kwargs))
        return {"status": "scheduled", "operations": ["lookup", "precheck", "relationship"]}
    def guard(event):
        controls.append(deepcopy(event))
        return {"allowed": True}
    lock = threading.RLock()
    app = SimpleNamespace(extensions={
        "v5_settings": {"tiktok_mode": "real", "contact_sync_enabled": True, "real_worker_enabled": True, "gate": gate},
        "v5_repository": repository, "v5_transport": transport, "v5_real_executor": SimpleNamespace(guard=guard),
        "v5_conversation_lock_for": lambda key: lock, "v5_reconcile_initial": callback})
    return app, repository, transport, callbacks, controls


class RecoveryTests(unittest.TestCase):
    def run_helper(self, app):
        with patch.object(recovery, "_utc_now", return_value=NOW):
            return recovery.recover_stalled(app)

    def test_exact_real_source_calls_only_reads_callback_without_mutating_state(self):
        app, repository, transport, calls, guards = fixture()
        before = deepcopy(repository.state)
        result = self.run_helper(app)
        self.assertEqual(result["status"], "scheduled")
        self.assertEqual(calls[0]["provenance"], "webhook_digest_confirmed")
        self.assertEqual(calls[0]["event"]["source_ref"], SOURCE)
        self.assertEqual(calls[0]["state"], before)
        self.assertRegex(calls[0]["recovery_key"], r"^[a-f0-9]{64}$")
        self.assertEqual(repository.state, before)
        self.assertEqual(len(guards), 1)
        self.assertEqual(len(transport.calls), 2)
        self.assertTrue(all(call["method"] == "GET" for call in transport.calls))

    def test_api_seconds_vs_webhook_microseconds_revalidates_without_altering_digest(self):
        app, repository, transport, calls, _ = fixture()
        original = recovery._source_event(transport.pages[0][0], transport.detail, app.extensions["v5_settings"]["gate"])
        original["created_at"] = "2026-10-28T22:53:53.123456Z"
        repository.source["digest"] = hashlib.sha256(json.dumps(original, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        original_digest = repository.source["digest"]
        self.assertEqual(self.run_helper(app)["status"], "scheduled")
        self.assertEqual(calls[0]["provenance"], "revalidated_chatwoot_source")
        self.assertEqual(calls[0]["event"]["created_at"], "2026-10-28T22:53:53Z")
        self.assertEqual(repository.source["digest"], original_digest)

    def test_different_source_text_cannot_use_history_as_a_substitute(self):
        app, _, transport, calls, _ = fixture()
        transport.pages[0][0]["content"] = "other real source text"
        self.assertEqual(self.run_helper(app)["reason"], "source_content_unconfirmed")
        self.assertFalse(calls)

    def test_newer_real_inbound_defers_without_replaying_previous_message(self):
        app, _, transport, calls, _ = fixture()
        newer = deepcopy(transport.pages[0][0]); newer["id"] += 1
        transport.pages[0].append(newer)
        self.assertEqual(self.run_helper(app)["reason"], "new_inbound_pending")
        self.assertFalse(calls)

    def test_wrong_contact_private_outgoing_and_wrong_conversation_fail_closed(self):
        for field, value in (("private", True), ("message_type", 1), ("conversation_id", 99), ("inbox_id", 9)):
            app, _, transport, calls, _ = fixture()
            transport.pages[0][0][field] = value
            self.assertEqual(self.run_helper(app)["status"], "blocked")
            self.assertFalse(calls)
        app, _, transport, calls, _ = fixture()
        transport.pages[0][0]["sender"]["id"] = 4
        self.assertEqual(self.run_helper(app)["status"], "blocked")
        self.assertFalse(calls)

    def test_stale_closed_paused_incomplete_or_confirmed_journey_makes_no_http_request(self):
        for field, value in (("phase", "form"), ("status", "closed"), ("mode", "simulated"),
                             ("expires_at", "2026-10-28T22:00:00Z"), ("qualification_paused", True),
                             ("pending_profile_changes", {"tiktok_declarado": "@other"})):
            app, repository, transport, calls, _ = fixture()
            repository.state["cycle"][field] = value
            self.assertEqual(self.run_helper(app)["status"], "noop")
            self.assertFalse(transport.calls)
            self.assertFalse(calls)

    def test_wrong_scope_no_callback_or_bad_contact_receipt_blocks_before_http(self):
        app, _, transport, calls, _ = fixture()
        app.extensions["v5_settings"]["gate"]["inbox_id"] = "4"
        self.assertEqual(self.run_helper(app)["reason"], "recovery_scope_invalid")
        self.assertFalse(transport.calls)
        app, repository, transport, calls, _ = fixture()
        repository.receipt["result"]["revision"] = 27
        self.assertEqual(self.run_helper(app)["reason"], "contact_projection_unconfirmed")
        self.assertFalse(transport.calls)
        app.extensions.pop("v5_reconcile_initial")
        self.assertEqual(self.run_helper(app)["status"], "noop")

    def test_unique_source_and_original_reference_required(self):
        app, _, transport, calls, _ = fixture()
        transport.pages[0] *= 2
        self.assertEqual(self.run_helper(app)["reason"], "source_message_not_unique")
        self.assertFalse(calls)

    def test_future_source_time_and_changed_history_for_precision_fallback_are_blocked(self):
        app, _, transport, calls, _ = fixture()
        transport.pages[0][0]["created_at"] = NOW.timestamp() + 10
        self.assertEqual(self.run_helper(app)["reason"], "source_time_invalid")
        self.assertFalse(calls)
        app, repository, _, calls, _ = fixture()
        repository.source["digest"] = "a" * 64
        repository.state["history"][-1]["cycle_id"] = "another-cycle"
        self.assertEqual(self.run_helper(app)["reason"], "source_content_unconfirmed")
        self.assertFalse(calls)

    def test_human_guard_or_state_change_cannot_schedule(self):
        app, _, _, calls, _ = fixture()
        app.extensions["v5_real_executor"].guard = lambda event: {"allowed": False}
        self.assertEqual(self.run_helper(app)["reason"], "human_control_unconfirmed")
        self.assertFalse(calls)
        app, repository, _, calls, _ = fixture()
        def changed_guard(event):
            repository.state["revision"] += 1
            return {"allowed": True}
        app.extensions["v5_real_executor"].guard = changed_guard
        self.assertEqual(self.run_helper(app)["reason"], "state_changed")
        self.assertFalse(calls)

    def test_already_reserved_recovery_does_not_repeat_callback(self):
        app, repository, _, calls, guards = fixture()
        repository.reserved = {"status": "completed"}
        self.assertEqual(self.run_helper(app)["reason"], "recovery_already_reserved")
        self.assertFalse(calls)
        self.assertFalse(guards)

    def test_callback_cannot_report_invitation_and_failures_do_not_leak(self):
        app, _, _, _, _ = fixture()
        app.extensions["v5_reconcile_initial"] = lambda **kwargs: {"status": "scheduled", "operations": ["invite"]}
        self.assertEqual(self.run_helper(app)["status"], "outcome_unknown")
        app, _, _, _, _ = fixture()
        def failing_callback(**kwargs): raise RuntimeError("private contents and credential")
        app.extensions["v5_reconcile_initial"] = failing_callback
        result = self.run_helper(app)
        self.assertEqual(result["status"], "outcome_unknown")
        self.assertNotIn("credential", repr(result))

    def test_second_page_is_bounded_and_remains_on_same_conversation(self):
        app, _, transport, calls, _ = fixture()
        actual = transport.pages[0][0]
        # Twenty later outgoing messages may hide the last real inbound.
        first = [{"id": 312831 + index, "message_type": 1, "private": False} for index in range(20)]
        transport.pages = [first, [actual]]
        self.assertEqual(self.run_helper(app)["status"], "scheduled")
        self.assertEqual(len(transport.calls), 3)
        self.assertIn("before=312831", transport.calls[-1]["url"])
        self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()
