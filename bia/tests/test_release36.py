"""Release 36: one evidenced invite retry and stage labels for every pilot phone."""
from pathlib import Path
import sys
import unittest

CANDIDATE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CANDIDATE))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import real_journey as journey
import real_operations
from test_real_journey import NOW, POLICY, eligible_state, inbound, settle

NO_WRITE_UI = {"post_attempted": True, "http_status": 500, "source": "partner_invite",
               "receipt": {"method": "ui", "status": "outcome_unknown", "ui_submit_attempted": True,
                           "provider_request_observed": False, "provider_post_attempted": False,
                           "create_post_blocked": False}}
WROTE_UI = {**NO_WRITE_UI, "receipt": {**NO_WRITE_UI["receipt"], "provider_request_observed": True,
                                        "provider_post_attempted": True}}
SESSION_DOWN = {"post_attempted": False}


def consented():
    turn = inbound("Autorizo o convite real", eligible_state()["state"])
    invite = turn["effects"][0]
    assert invite["operation"] == "invite", invite
    return turn["state"], invite


def fail_invite(state, invite, status="outcome_unknown", evidence=NO_WRITE_UI):
    return settle(state, invite, status, updates={"confirmed": False, "evidence": evidence})


class InviteRetryTests(unittest.TestCase):
    def test_unobserved_create_schedules_one_delayed_precheck_then_retry_invite(self):
        state, invite = consented()
        turn = fail_invite(state, invite)
        self.assertNotIn("Não vou repetir", turn["reply"])
        self.assertEqual([e["operation"] for e in turn["effects"]], ["precheck"])
        self.assertGreater(turn["effects"][0]["payload"]["not_before"], NOW.isoformat())
        retry = settle(turn["state"], turn["effects"][0], "eligible")
        self.assertEqual([e["operation"] for e in retry["effects"]], ["invite"])
        self.assertEqual(retry["effects"][0]["payload"]["retry"], 1)
        self.assertEqual(retry["state"]["cycle"]["phase"], "inviting")
        self.assertEqual(retry["state"]["effects"][invite["id"]]["status"], "superseded_by_retry")

    def test_session_down_without_post_is_also_retried(self):
        state, invite = consented()
        turn = fail_invite(state, invite, "verification_pending", SESSION_DOWN)
        self.assertEqual([e["operation"] for e in turn["effects"]], ["precheck"])

    def test_observed_create_request_is_never_retried(self):
        state, invite = consented()
        turn = fail_invite(state, invite, "outcome_unknown", WROTE_UI)
        self.assertNotIn("precheck", [e["operation"] for e in turn["effects"]])
        self.assertNotIn("invite_retry", turn["state"]["cycle"])

    def test_retry_happens_at_most_once(self):
        state, invite = consented()
        turn = fail_invite(state, invite)
        retry = settle(turn["state"], turn["effects"][0], "eligible")
        second = fail_invite(retry["state"], retry["effects"][0])
        self.assertFalse([e for e in second["effects"] if e["operation"] in {"precheck", "invite"}])

    def test_retry_found_pending_does_not_post_again_and_moves_on(self):
        state, invite = consented()
        turn = fail_invite(state, invite)
        retry = settle(turn["state"], turn["effects"][0], "eligible")
        done = settle(retry["state"], retry["effects"][0], "pending")
        self.assertIn(done["state"]["cycle"]["phase"], {"await_acceptance", "form"})
        self.assertFalse([e for e in done["effects"] if e["operation"] == "invite"])

    def test_ineligible_refresh_stops_without_retry(self):
        state, invite = consented()
        turn = fail_invite(state, invite)
        stopped = settle(turn["state"], turn["effects"][0], "ineligible")
        self.assertFalse([e for e in stopped["effects"] if e.get("operation") == "invite"])

    def test_blocked_lead_writing_again_triggers_the_check_now(self):
        state, invite = consented()
        state = settle(state, invite, "outcome_unknown",
                       updates={"confirmed": False, "evidence": WROTE_UI})["state"]
        # Rewrite the stored receipt as a no-write proof, as for a lead stuck before release 36.
        state["cycle"]["real_operations"]["invite"]["evidence"] = NO_WRITE_UI
        state["cycle"]["phase"] = "blocked"
        turn = inbound("Oi, e o convite?", state)
        self.assertEqual([e["operation"] for e in turn["effects"]], ["precheck"])
        self.assertNotIn("not_before", turn["effects"][0]["payload"])

    def test_retry_invite_gets_its_own_job_row(self):
        state, invite = consented()
        turn = fail_invite(state, invite)
        retry = settle(turn["state"], turn["effects"][0], "eligible")
        event = {"provider": "chatwoot", "account_id": "1", "inbox_id": "3", "conversation_id": "26097",
                 "message_id": "9", "sender_phone": "+5547991154859", "message_type": "incoming",
                 "private": False, "text": "oi"}
        first = real_operations.build_jobs(event, state, [invite])[0]["job_key"]
        again = real_operations.build_jobs(event, retry["state"], retry["effects"])[0]["job_key"]
        self.assertNotEqual(first, again)


class StageLabelScopeTests(unittest.TestCase):
    def test_label_projection_accepts_any_listed_chat_only_with_phone_list(self):
        from transport import ChatwootProgress
        base = {"enabled": True, "provider": "chatwoot", "account_id": "1", "inbox_id": "3", "phone": "+5547991154859"}
        lead = {"provider": "chatwoot", "account_id": "1", "inbox_id": "3", "conversation_id": "46814",
                "contact_id": "11160", "message_id": "5", "sender_phone": "+5575991040908",
                "message_type": "incoming", "private": False, "text": "oi"}
        pinned = ChatwootProgress(None, {**base, "conversation_id": "26097", "contact_id": "3"})
        self.assertEqual(pinned.sync(lead, {}, {})["reason"], "outside_pilot")
        listed = ChatwootProgress(None, {**base, "phones": ("+5547991154859", "+5575991040908")})
        self.assertNotEqual(listed.sync(lead, {}, {}).get("reason"), "outside_pilot")


if __name__ == "__main__":
    unittest.main()
