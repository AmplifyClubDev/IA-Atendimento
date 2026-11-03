"""Contract tests with scripted HTTP only. No environment or network access."""
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import sys
import unittest
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from playwright_client import PlaywrightClient


SETTINGS = {
    "tiktok_precheck_url": "https://tiktok-pre-validacao-production.up.railway.app/bridge",
    "tiktok_precheck_token": "p" * 40,
    "tiktok_agency_url": "https://tiktok-agenciamento-production.up.railway.app/bridge",
    "tiktok_agency_token": "a" * 40,
    "tiktok_invites_url": "https://tiktok-partner-bridge-production.up.railway.app/bridge",
    "tiktok_invites_token": "i" * 40,
    "tiktok_lookup_url": "http://consulta-tiktok.railway.internal:3000",
    "tiktok_lookup_token": "l" * 40,
    "tiktok_gmv_url": "https://tiktok-gmv-production.up.railway.app/bridge",
    "tiktok_gmv_token": "g" * 40,
}


def ready():
    return 200, {"ok": True, "status": "ready", "contexto": {"aberto": True, "pronto": True},
                 "probe": {"status": "ok", "ageMs": 1}, "readiness": {"fresh": True},
                 "riskGuard": {"status": "clear"}}


def refreshing_ready():
    code, payload = ready()
    payload["probe"]["ageMs"] = 90000
    payload["readiness"].update(fresh=False, withinGrace=True, refreshing=True)
    return code, payload


class FakeClock:
    def __init__(self):
        self.now, self.sleeps = 0.0, []

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


def precheck(shop=1, creator="teste"):
    return 200, {"ok": True, "status": "precheck_ok", "creator": creator,
                 "precheck": {"ok": True, "data": {"code": 0, "data": {"pay_account_info": {"account_status": shop}}}}}


def relation(status, found=False, creator="teste", complete=True, cache=None):
    return 200, {"ok": True, "status": "relations_listed", "completo": complete, "cache": cache,
                 "query": {"status": str(status), "creators": [creator]},
                 "items": [{"arroba": creator, "relation_id": "100", "status": "vinculado" if status == 1 else "solicitada",
                            "tiktok_status": status, "tiktok_data_status": status,
                            "expire_time_second": "4102444800"}] if found else [],
                 "pages": [{"ok": True, "hasMore": False}], "totalNum": int(found)}


def accepted_invite(ok=True):
    return 200 if ok else 422, {"ok": ok, "creator": "teste",
                               "status": "invite_sent_and_verified" if ok else "invite_sent_unverified",
                               "create": {"ok": True}, "validation": {"ok": ok, "status": "requested"}}


class Script:
    def __init__(self, responses):
        self.responses, self.calls = list(responses), []

    def __call__(self, **call):
        self.calls.append(deepcopy(call))
        if not self.responses:
            raise AssertionError("unexpected_http_call")
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return deepcopy(response)

    def writes(self):
        return [call for call in self.calls if call["method"] == "POST" and urlsplit(call["url"]).path.endswith("/invite")]


def invitation_prefix():
    return [ready(), ready(), relation(1), relation(2), ready(), precheck(), ready()]


class ClientTests(unittest.TestCase):
    def client(self, responses, **settings):
        fake = Script(responses)
        return PlaywrightClient({**SETTINGS, **settings}, fake), fake

    def test_configuration_is_local_and_optional_roles_do_not_block_core(self):
        client, fake = self.client([], tiktok_gmv_url="", tiktok_gmv_token="", tiktok_lookup_token="")
        self.assertEqual(client.configuration(), {"configured": True, "issues": []})
        self.assertFalse(client.configuration("lookup")["configured"])
        self.assertFalse(client.configuration("gmv_report")["configured"])
        self.assertFalse(client.configuration("invalid")["configured"])
        self.assertFalse(fake.calls)

    def test_invite_configuration_requires_each_own_role(self):
        for role in ("precheck", "agency", "invites"):
            client, fake = self.client([], **{"tiktok_" + role + "_token": ""})
            result = client.configuration("invite")
            self.assertFalse(result["configured"])
            self.assertIn(role + ":connection_not_configured", result["issues"])
            self.assertFalse(fake.calls)

    def test_boolean_upstream_code_is_not_success(self):
        response = precheck()
        response[1]["precheck"]["data"]["code"] = False
        client, _ = self.client([ready(), response])
        self.assertFalse(client.execute("precheck", "teste")["confirmed"])

    def test_precheck_real_handle_and_sanitized_evidence(self):
        payload = precheck()
        payload[1]["precheck"]["data"]["data"]["private_contact"] = "never-return@example.test"
        client, fake = self.client([ready(), payload])
        result = client.execute("precheck", "@TeStE")
        self.assertEqual(result["status"], "eligible")
        self.assertTrue(result["confirmed"])
        self.assertEqual(result["creator"], "teste")
        self.assertNotIn("private_contact", repr(result))
        self.assertNotIn("never-return", repr(result))
        self.assertEqual(fake.calls[1]["json_body"], {"creator": "teste"})
        self.assertEqual(datetime.fromisoformat(result["observed_at"].replace("Z", "+00:00")).tzinfo, timezone.utc)

    def test_shop_unknown_null_bool_or_missing_never_eligible(self):
        for value in (None, True, False, "1"):
            with self.subTest(value=value):
                client, _ = self.client([ready(), precheck(value)])
                result = client.execute("precheck", "teste")
                self.assertEqual(result["status"], "verification_pending")
                self.assertFalse(result["confirmed"])

    def test_explicit_inactive_shop_is_ineligible(self):
        client, _ = self.client([ready(), precheck(0)])
        self.assertEqual(client.execute("precheck", "teste")["status"], "ineligible")

    def test_outer_false_never_promoted_by_nested_success(self):
        response = precheck()
        response[1]["ok"] = False
        response[1]["precheck"]["data"]["msg"] = "success"
        client, _ = self.client([ready(), response])
        self.assertEqual(client.execute("precheck", "teste")["status"], "verification_pending")

    def test_wrong_creator_cannot_qualify(self):
        client, _ = self.client([ready(), precheck(creator="another")])
        self.assertFalse(client.execute("precheck", "teste")["confirmed"])

    def test_redirect_and_transport_errors_fail_closed(self):
        for response in ((302, {}), TimeoutError("secret url token"), (200, []), (200, {"ok": True})):
            with self.subTest(response=type(response).__name__):
                client, fake = self.client([response])
                result = client.execute("precheck", "teste")
                self.assertFalse(result["confirmed"])
                self.assertEqual(len(fake.calls), 1)
                self.assertNotIn("secret", repr(result))

    def test_stale_readiness_even_with_ready_status_blocks(self):
        for mutate in (lambda d: d["probe"].update(ageMs=60001),
                       lambda d: d["riskGuard"].update(status="captcha_required"),
                       lambda d: d["readiness"].update(fresh=False),
                       lambda d: d["contexto"].update(pronto=False)):
            response = ready()
            mutate(response[1])
            client, fake = self.client([response])
            self.assertEqual(client.execute("precheck", "teste")["reason"], "session_not_ready")
            self.assertEqual(len(fake.calls), 1)

    def test_session_and_captcha_require_human(self):
        for status in ("human_login_required", "captcha_required", "blocked_by_risk_guard", "mfa_required"):
            client, fake = self.client([(503, {"ok": False, "status": status})])
            self.assertEqual(client.execute("precheck", "teste")["reason"], "human_verification_required")
            self.assertFalse(fake.writes())

    def test_ready_refresh_reads_again_then_requires_fresh_proof(self):
        clock, fake = FakeClock(), Script([refreshing_ready(), ready(), precheck()])
        client = PlaywrightClient(SETTINGS, fake, monotonic=clock.monotonic, sleep=clock.sleep)
        result = client.execute("precheck", "teste")
        self.assertEqual(result["status"], "eligible")
        self.assertEqual(clock.sleeps, [2])
        self.assertEqual([call["method"] for call in fake.calls], ["GET", "GET", "POST"])
        self.assertTrue(all(urlsplit(call["url"]).path == "/bridge/ready" for call in fake.calls[:2]))

    def test_ready_refreshing_flag_alone_can_request_another_read(self):
        response = refreshing_ready()
        response[1]["readiness"]["withinGrace"] = False
        clock, fake = FakeClock(), Script([response, ready()])
        client = PlaywrightClient(SETTINGS, fake, monotonic=clock.monotonic, sleep=clock.sleep)
        client._ready("agency")
        self.assertEqual(len(fake.calls), 2)
        self.assertEqual(clock.sleeps, [2])

    def test_ready_grace_persisting_fails_after_at_most_three_gets(self):
        clock, fake = FakeClock(), Script([refreshing_ready()] * 4)
        client = PlaywrightClient(SETTINGS, fake, monotonic=clock.monotonic, sleep=clock.sleep)
        result = client.execute("precheck", "teste")
        self.assertEqual(result["reason"], "session_not_ready")
        self.assertFalse(result["confirmed"])
        self.assertEqual(len(fake.calls), 3)
        self.assertEqual(clock.sleeps, [2, 2])
        self.assertTrue(all(call["method"] == "GET" for call in fake.calls))

    def test_ready_retry_timeout_is_capped_by_total_twelve_second_budget(self):
        clock, script = FakeClock(), Script([refreshing_ready(), refreshing_ready(), ready()])
        def slow_transport(**call):
            response = script(**call)
            clock.now += 5
            return response
        client = PlaywrightClient(SETTINGS, slow_transport, monotonic=clock.monotonic, sleep=clock.sleep)
        result = client.execute("precheck", "teste")
        self.assertEqual(result["reason"], "session_not_ready")
        self.assertEqual(len(script.calls), 2)
        self.assertEqual([call["timeout"] for call in script.calls], [5, 5])
        self.assertEqual(clock.now, 12)
        self.assertEqual(clock.sleeps, [2])

    def test_ready_remaining_budget_caps_configured_http_timeout(self):
        clock, script = FakeClock(), Script([refreshing_ready(), ready()])
        def slow_transport(**call):
            response = script(**call)
            clock.now += 3
            return response
        client = PlaywrightClient({**SETTINGS, "tiktok_status_timeout_seconds": 10}, slow_transport,
                                  monotonic=clock.monotonic, sleep=clock.sleep)
        client._ready("agency")
        self.assertEqual([call["timeout"] for call in script.calls], [10, 7])
        self.assertEqual(clock.now, 8)

    def test_ready_late_success_cannot_cross_deadline(self):
        clock = FakeClock()
        def late_transport(**call):
            clock.now += 13
            return ready()
        client = PlaywrightClient(SETTINGS, late_transport, monotonic=clock.monotonic, sleep=clock.sleep)
        self.assertEqual(client.execute("precheck", "teste")["reason"], "session_not_ready")
        self.assertFalse(clock.sleeps)

    def test_ready_login_risk_auth_failure_and_non_ready_503_are_never_retried(self):
        cases = [(401, {"ok": False}), (503, {"ok": False, "status": "login_required"}),
                 (503, {"ok": False, "status": "human_login_required"}),
                 (503, {"ok": False, "status": "blocked_by_risk_guard"}),
                 (503, {"ok": False, "status": "captcha_required"}),
                 (503, refreshing_ready()[1])]
        for response in cases:
            with self.subTest(http=response[0], status=response[1].get("status")):
                clock, fake = FakeClock(), Script([response, ready()])
                client = PlaywrightClient(SETTINGS, fake, monotonic=clock.monotonic, sleep=clock.sleep)
                self.assertFalse(client.execute("precheck", "teste")["confirmed"])
                self.assertEqual(len(fake.calls), 1)
                self.assertFalse(clock.sleeps)

    def test_ready_grace_requires_complete_healthy_telemetry_and_old_age(self):
        mutations = [lambda d: d.pop("contexto"), lambda d: d["contexto"].update(pronto=False),
                     lambda d: d.pop("probe"), lambda d: d["probe"].update(status="failed"),
                     lambda d: d["probe"].update(ageMs=True), lambda d: d["probe"].update(ageMs=1),
                     lambda d: d.pop("readiness"), lambda d: d["readiness"].update(withinGrace=False, refreshing=False),
                     lambda d: d["riskGuard"].update(status="blocked"), lambda d: d.update(ok=False)]
        for mutate in mutations:
            response = refreshing_ready()
            mutate(response[1])
            clock, fake = FakeClock(), Script([response, ready()])
            client = PlaywrightClient(SETTINGS, fake, monotonic=clock.monotonic, sleep=clock.sleep)
            self.assertEqual(client.execute("precheck", "teste")["reason"], "session_not_ready")
            self.assertEqual(len(fake.calls), 1)
            self.assertFalse(clock.sleeps)

    def test_refresh_before_invitation_still_sends_only_one_invite_post(self):
        responses = invitation_prefix()
        responses.insert(0, refreshing_ready())
        clock, fake = FakeClock(), Script(responses + [accepted_invite(False)])
        client = PlaywrightClient(SETTINGS, fake, monotonic=clock.monotonic, sleep=clock.sleep)
        result = client.execute("invite", "teste", confirmed=True, commission="10", before_write=lambda: True)
        self.assertEqual(result["status"], "pending_verification")
        self.assertEqual(len(fake.writes()), 1)
        self.assertEqual(clock.sleeps, [2])

    def test_exact_hosts_not_wildcard_or_other_bridge(self):
        urls = ["https://evil.up.railway.app/bridge", SETTINGS["tiktok_agency_url"],
                "https://tiktok-pre-validacao-production.up.railway.app.evil.test/bridge",
                "https://user:pass@tiktok-pre-validacao-production.up.railway.app/bridge",
                SETTINGS["tiktok_precheck_url"] + "?access=secret",
                SETTINGS["tiktok_precheck_url"] + "#access=secret",
                SETTINGS["tiktok_precheck_url"] + "/../bridge",
                "http://tiktok-pre-validacao-production.up.railway.app/bridge"]
        for url in urls:
            with self.subTest(url=url):
                client, fake = self.client([], tiktok_precheck_url=url)
                self.assertEqual(client.execute("precheck", "teste")["reason"], "connection_target_invalid")
                self.assertFalse(fake.calls)

    def test_no_credential_fallback_and_header_injection(self):
        for token in ("", "short", "x" * 40 + "\r\nX-Leak: yes"):
            client, fake = self.client([], tiktok_precheck_token=token)
            self.assertEqual(client.execute("precheck", "teste")["reason"], "connection_not_configured")
            self.assertFalse(fake.calls)

    def test_timeouts_are_bounded_and_not_boolean(self):
        for timeout in (0, 11, True, "5", float("nan")):
            client, fake = self.client([], tiktok_status_timeout_seconds=timeout)
            self.assertEqual(client.execute("precheck", "teste")["reason"], "timeout_configuration_invalid")
            self.assertFalse(fake.calls)

    def test_invalid_creator_makes_no_network(self):
        for handle in ("", "@", "https://tiktok.com/@teste", "test?x=y", "foo/bar", "@a", "x" * 25, None):
            client, fake = self.client([])
            self.assertEqual(client.execute("precheck", handle)["reason"], "invalid_creator")
            self.assertFalse(fake.calls)

    def test_linked_evidence_requires_exact_numeric_status(self):
        client, fake = self.client([ready(), relation(1, True)])
        result = client.execute("relationship", "@teste")
        self.assertEqual(result["status"], "linked")
        self.assertTrue(result["confirmed"])
        query = parse_qs(urlsplit(fake.calls[1]["url"]).query)
        self.assertEqual(query["fresh"], ["1"])
        self.assertEqual(query["priority"], ["accept"])
        self.assertEqual(query["creators"], ["teste"])
        for value in (None, True, "1", 2):
            response = relation(1, True)
            response[1]["items"][0]["tiktok_status"] = value
            client, _ = self.client([ready(), response])
            self.assertFalse(client.execute("relationship", "teste")["confirmed"])

    def test_partial_or_cached_relation_cannot_assert_absence(self):
        for response in (relation(1, complete=False), relation(1, cache={"idadeMs": 0})):
            client, fake = self.client([ready(), response])
            result = client.execute("relationship", "teste")
            self.assertEqual(result["status"], "verification_pending")
            self.assertFalse(result["confirmed"])
            self.assertEqual(len(fake.calls), 2)

    def test_inconsistent_completeness_and_unfiltered_items_are_unknown(self):
        more = relation(1)
        more[1]["pages"][0]["hasMore"] = True
        other = relation(1, True)
        other[1]["items"][0]["arroba"] = "another"
        for response in (more, other):
            client, _ = self.client([ready(), response])
            self.assertEqual(client.execute("relationship", "teste")["status"], "verification_pending")

    def test_old_invitation_expiry_does_not_expire_an_active_binding(self):
        response = relation(1, True)
        response[1]["items"][0]["expire_time_second"] = "1"
        client, _ = self.client([ready(), response])
        self.assertEqual(client.execute("relationship", "teste")["status"], "linked")

    def test_absence_requires_both_complete_lists(self):
        client, fake = self.client([ready(), relation(1), relation(2)])
        result = client.execute("relationship", "teste")
        self.assertEqual(result["status"], "not_found")
        self.assertTrue(result["confirmed"])
        self.assertEqual(len(fake.calls), 3)

    def test_pending_is_not_linked(self):
        client, _ = self.client([ready(), relation(1), relation(2, True)])
        result = client.execute("relationship", "teste")
        self.assertEqual(result["status"], "pending")
        self.assertEqual(result["evidence"]["tiktok_status"], 2)

    def test_duplicate_expired_and_wrong_target_relations_are_unknown(self):
        duplicate = relation(1, True)
        duplicate[1]["items"] *= 2
        expired = relation(1, True)
        expired[1]["items"][0]["effective_end_date_second"] = "1"
        wrong = relation(1, True, creator="other")
        for response in (duplicate, expired, wrong):
            client, _ = self.client([ready(), response])
            self.assertEqual(client.execute("relationship", "teste")["status"], "verification_pending")

    def test_invitation_needs_real_confirmation_and_explicit_commission(self):
        for kwargs in ({"confirmed": False, "commission": "10"}, {"confirmed": "true", "commission": "10"},
                       {"confirmed": True}, {"confirmed": True, "commission": "1000"},
                       {"confirmed": True, "commission": "10.01"}, {"confirmed": True, "commission": "11"},
                       {"confirmed": True, "commission": float("nan")}, {"confirmed": True, "commission": True}):
            client, fake = self.client([])
            result = client.execute("invite", "teste", **kwargs)
            self.assertEqual(result["status"], "failed")
            self.assertFalse(fake.calls)

    def test_existing_active_or_pending_does_not_send_again(self):
        for responses, expected in (([ready(), ready(), relation(1, True)], "linked"),
                                    ([ready(), ready(), relation(1), relation(2, True)], "pending")):
            client, fake = self.client(responses)
            result = client.execute("invite", "teste", confirmed=True, commission="10", before_write=lambda: True)
            self.assertEqual(result["status"], expected)
            self.assertFalse(fake.writes())

    def test_partial_pending_list_blocks_invitation(self):
        client, fake = self.client([ready(), ready(), relation(1), relation(2, complete=False)])
        self.assertEqual(client.execute("invite", "teste", confirmed=True, commission="10", before_write=lambda: True)["status"], "verification_pending")
        self.assertFalse(fake.writes())

    def test_unknown_shop_blocks_invitation(self):
        responses = invitation_prefix()
        responses[-2] = precheck(None)
        client, fake = self.client(responses)
        self.assertEqual(client.execute("invite", "teste", confirmed=True, commission="10", before_write=lambda: True)["status"], "verification_pending")
        self.assertFalse(fake.writes())

    def test_single_post_payload_no_invented_duration(self):
        client, fake = self.client(invitation_prefix() + [accepted_invite(), ready(), relation(1), relation(2, True)])
        result = client.execute("invite", "teste", confirmed=True, commission="10", before_write=lambda: True)
        self.assertEqual(result["status"], "sent")
        self.assertTrue(result["confirmed"])
        self.assertEqual(len(fake.writes()), 1)
        self.assertEqual(fake.writes()[0]["json_body"], {"creator": "teste", "confirm": True, "commission": "10",
                                                       "skip_precheck": True, "force_reinvite": False})
        self.assertEqual(fake.writes()[0]["timeout"], 135)

    def test_422_create_accepted_is_not_failure_or_linked(self):
        client, fake = self.client(invitation_prefix() + [accepted_invite(False)])
        result = client.execute("invite", "teste", confirmed=True, commission="10", before_write=lambda: True)
        self.assertEqual(result["status"], "pending_verification")
        self.assertFalse(result["confirmed"])
        self.assertTrue(result["evidence"]["create_accepted"])
        self.assertEqual(len(fake.writes()), 1)

    def test_invitation_timeout_has_no_retry_and_does_not_leak(self):
        client, fake = self.client(invitation_prefix() + [TimeoutError("secret credentials")])
        result = client.execute("invite", "teste", confirmed=True, commission="10", before_write=lambda: True)
        self.assertEqual(result["status"], "outcome_unknown")
        self.assertTrue(result["evidence"]["post_attempted"])
        self.assertEqual(len(fake.writes()), 1)
        self.assertNotIn("secret", repr(result))

    def test_authority_is_rechecked_after_scans_immediately_before_post(self):
        client, fake = self.client(invitation_prefix() + [accepted_invite(False)])
        observations = []
        def check():
            observations.append((len(fake.calls), len(fake.writes())))
            return True
        result = client.execute("invite", "teste", confirmed=True, commission="10", before_write=check)
        self.assertEqual(observations, [(7, 0)])
        self.assertEqual(result["status"], "pending_verification")
        self.assertEqual(len(fake.writes()), 1)

    def test_missing_false_or_exception_authority_never_posts(self):
        def error():
            raise RuntimeError("private_state")
        for check in (None, lambda: False, lambda: "true", error):
            client, fake = self.client(invitation_prefix())
            result = client.execute("invite", "teste", confirmed=True, commission="10", before_write=check)
            self.assertEqual(result["reason"], "write_authority_unconfirmed")
            self.assertFalse(fake.writes())
            self.assertNotIn("private_state", repr(result))

    def test_nested_success_with_outer_false_never_becomes_sent(self):
        response = accepted_invite(False)
        response[1]["status"] = "invite_failed"
        response[1]["create"]["message"] = "success"
        client, _ = self.client(invitation_prefix() + [response])
        result = client.execute("invite", "teste", confirmed=True, commission="10", before_write=lambda: True)
        self.assertEqual(result["status"], "pending_verification")
        self.assertFalse(result["confirmed"])

    def test_nested_verified_invite_still_requires_independent_relation(self):
        client, _ = self.client(invitation_prefix() + [accepted_invite(), ready(), relation(1), relation(2)])
        result = client.execute("invite", "teste", confirmed=True, commission="10", before_write=lambda: True)
        self.assertEqual(result["status"], "pending_verification")
        self.assertFalse(result["confirmed"])

    def test_wrong_invitation_handle_is_never_confirmed(self):
        response = accepted_invite()
        response[1]["creator"] = "another"
        client, _ = self.client(invitation_prefix() + [response])
        self.assertFalse(client.execute("invite", "teste", confirmed=True, commission="10", before_write=lambda: True)["confirmed"])

    def test_lookup_only_exact_private_host_and_explicit_port(self):
        for url in ("http://other.railway.internal:3000", "http://consulta-tiktok.railway.internal",
                    "http://consulta-tiktok.railway.internal.evil.test:3000", "https://other.up.railway.app"):
            client, fake = self.client([], tiktok_lookup_url=url)
            self.assertEqual(client.execute("lookup", "teste")["reason"], "connection_target_invalid")
            self.assertFalse(fake.calls)

    def test_lookup_observation_never_confirms_category_or_exact_gmv(self):
        payload = {"ok": True, "status": "creator_lookup_observed", "creator": "teste",
                   "verificationStatus": "period_and_unit_require_validation", "periodLabels": ["Last 30 days"],
                   "metrics": {"med_gmv_revenue": {"value": "100-1000", "secret": "hidden"},
                               "med_gmv_revenue_range": {"value": "100-1000"}}}
        client, fake = self.client([(200, payload)])
        result = client.execute("lookup", "teste")
        self.assertEqual(result["status"], "observed")
        self.assertFalse(result["confirmed"])
        self.assertTrue(result["evidence"]["period_and_unit_require_validation"])
        self.assertNotIn("secret", repr(result))
        self.assertEqual(fake.calls[0]["method"], "GET")

    def test_gmv_requires_explicit_valid_period_and_complete_data(self):
        for start, end in ((None, None), ("2026-10-28", "2026-10-01"), ("2025-01-01", "2026-10-01")):
            client, fake = self.client([])
            result = client.execute("gmv_report", "teste", start_date=start, end_date_exclusive=end)
            self.assertEqual(result["reason"], "explicit_gmv_period_required")
            self.assertFalse(fake.calls)
        payload = {"ok": True, "items": [], "pages": [{"ok": True}], "totalCount": 100}
        client, _ = self.client([ready(), (200, payload)])
        result = client.execute("gmv_report", "teste", start_date="2026-10-01", end_date_exclusive="2026-10-28")
        self.assertEqual(result["reason"], "gmv_report_incomplete")

    def test_gmv_observed_is_not_normalized_currency_or_category(self):
        payload = {"ok": True, "items": [{"arroba": "teste", "gmv": 1234.56, "gmv_formatted": "R$ 1.234,56", "date_range": "2026-10"}],
                   "pages": [{"ok": True}], "totalCount": 1}
        client, fake = self.client([ready(), (200, payload)])
        result = client.execute("gmv", "teste", start_date="2026-10-01", end_date_exclusive="2026-10-28")
        self.assertEqual(result["operation"], "gmv_report")
        self.assertEqual(result["status"], "observed")
        self.assertFalse(result["confirmed"])
        self.assertNotIn("currency", result["evidence"])
        self.assertEqual(parse_qs(urlsplit(fake.calls[1]["url"]).query)["end_date_exclusive"], ["2026-10-28"])

    def test_no_gmv_role_fallback(self):
        client, fake = self.client([], tiktok_gmv_url="", tiktok_gmv_token="")
        result = client.execute("gmv_report", "teste", start_date="2026-10-01", end_date_exclusive="2026-10-28")
        self.assertEqual(result["reason"], "connection_not_configured")
        self.assertFalse(fake.calls)


if __name__ == "__main__":
    unittest.main()
