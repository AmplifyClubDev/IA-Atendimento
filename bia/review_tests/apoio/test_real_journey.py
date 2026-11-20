"""Offline authoritative-state cases; no API or database is contacted."""
import copy
from datetime import datetime, timedelta, timezone
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from urllib.parse import urlsplit

CANDIDATE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(CANDIDATE))
import conversation
import engine
import guided_ai
import real_journey as journey

NOW = datetime(2026, 10, 28, 15, 0, tzinfo=timezone.utc)
POLICY = {"approved": True, "commission": 10, "commission_unit": "percent",
          "duration_fixed_months": 2, "duration_label": "2 meses", "version": "approved-test-policy"}
GATE = {"enabled": True, "provider": "chatwoot", "account_id": "1", "inbox_id": "3", "phone": "+5547991154859"}


def inbound(text, state=None, callback=None, **kwargs):
    return conversation.handle(state or {}, text, callback, now=kwargs.pop("now", NOW),
                               real_mode=True, operation_policy=kwargs.pop("policy", POLICY), **kwargs)


def qualified(creator="@teste"):
    state = inbound("oi")["state"]
    for text in ("Quero me agenciar", "Indicação", creator):
        turn = inbound(text, state)
        state = turn["state"]
    return turn


def pending_job(state, operation):
    return next(job for job in state["effects"].values()
                if job.get("operation") == operation and job["status"] == "pending")


def api_result(job, status, **updates):
    return {"operation": job["operation"], "creator": job["creator"].lstrip("@"), "status": status,
            "observed_at": NOW.isoformat(), "confirmed": True,
            "evidence": {"source": "partner_bridge", "complete": True}, **updates}


def settle(state, job, status, **kwargs):
    result = api_result(job, status, **kwargs.pop("updates", {}))
    return conversation.resolve_tiktok_result(state, job["id"], result,
                                              now=kwargs.pop("now", NOW), operation_policy=kwargs.pop("policy", POLICY))


def eligible_state():
    turn = qualified()
    job = next(job for job in turn["effects"] if job["operation"] == "precheck")
    turn = settle(turn["state"], job, "eligible")
    relation = pending_job(turn["state"], "relationship")
    turn = settle(turn["state"], relation, "not_found")
    return turn


class RealJourneyTests(unittest.TestCase):
    def legacy_shop_cycle(self):
        turn = qualified()
        state = turn["state"]
        state["effects"] = {}
        state["cycle"]["phase"] = "shop"
        state["cycle"].pop("real_operations", None)
        return state

    def test_handle_starts_real_checks_without_manual_shop_or_agency_answers(self):
        state = inbound("oi")["state"]
        state = inbound("Quero me agenciar", state)["state"]
        origin = inbound("Vi um anúncio", state, callback=lambda text, context: {
            "reply": "Seu TikTok Shop está ativo e qual é seu @?", "intent": "continue", "claims": [],
            "next_phase": "shop", "topic_ids": [], "provider_status": "completed"})
        self.assertEqual(origin["state"]["cycle"]["phase"], "tiktok")
        self.assertIn("Qual é o seu @", origin["reply"])
        self.assertNotIn("Creator está ativo", origin["reply"])
        turn = inbound("@perfil_ficticio", origin["state"])
        self.assertEqual(turn["state"]["cycle"]["phase"], "checking")
        self.assertEqual({job["operation"] for job in turn["effects"]}, {"precheck", "relationship", "lookup"})
        self.assertNotIn("shop_ativo_declarado", turn["state"]["cycle"]["facts"])
        self.assertNotIn("possui_agencia_declarada", turn["state"]["cycle"]["facts"])
        self.assertNotIn("está ativo?", turn["reply"])
        self.assertNotIn("invite", {job["operation"] for job in turn["effects"]})

    def test_legacy_shop_uncertainty_recovers_same_cycle_and_saved_handle(self):
        for text in ("Não sei se está", "não sabia se estava ativa"):
            with self.subTest(text=text):
                state = self.legacy_shop_cycle()
                cycle_id, creator = state["cycle"]["id"], state["cycle"]["facts"]["tiktok_declarado"]
                turn = inbound(text, state)
                self.assertEqual(turn["state"]["cycle"]["id"], cycle_id)
                self.assertEqual(turn["state"]["cycle"]["facts"]["tiktok_declarado"], creator)
                self.assertIsNone(turn["state"]["cycle"]["facts"]["shop_ativo_declarado"])
                self.assertEqual(turn["state"]["cycle"]["phase"], "checking")
                self.assertEqual({job["operation"] for job in turn["effects"]}, {"precheck", "relationship", "lookup"})
                self.assertIn("você não precisa saber", turn["reply"])
                self.assertNotIn("está ativo?", turn["reply"])
                self.assertNotIn("Qual é o seu @", turn["reply"])

    def test_natural_continue_starts_legacy_checks_once_without_new_claims(self):
        turn = inbound("Pode verificar", self.legacy_shop_cycle())
        self.assertEqual(turn["state"]["cycle"]["phase"], "checking")
        self.assertEqual({job["operation"] for job in turn["effects"]}, {"precheck", "relationship", "lookup"})
        self.assertEqual(turn["applied_claims"], [])
        again = inbound("Pode verificar", turn["state"])
        self.assertFalse(again["effects"])
        self.assertEqual(len(again["state"]["effects"]), 3)

    def test_uncertainty_about_accepting_is_not_shop_status_or_invite_permission(self):
        turn = inbound("Não sei se aceito", self.legacy_shop_cycle())
        self.assertNotIn("shop_ativo_declarado", turn["state"]["cycle"]["facts"])
        self.assertNotIn("consentimento_convite", turn["state"]["cycle"]["facts"])
        self.assertFalse(any(job.get("operation") == "invite" for job in turn["effects"]))
        self.assertFalse(journey._shop_unknown("Meu Shop não está ativo", contextual=True))

    def test_unconfirmed_checks_never_enable_invite_or_form(self):
        turn = qualified()
        precheck = pending_job(turn["state"], "precheck")
        result = settle(turn["state"], precheck, "eligible", updates={"confirmed": False})
        self.assertTrue(result["ignored"])
        self.assertEqual(result["state"]["cycle"]["phase"], "checking")
        self.assertFalse(result["effects"])

    def test_parallel_read_order_not_found_then_eligible_reuses_both_proofs(self):
        turn = qualified()
        relationship = pending_job(turn["state"], "relationship")
        result = settle(turn["state"], relationship, "not_found")
        self.assertEqual(result["state"]["cycle"]["phase"], "checking")
        self.assertFalse(result["effects"])
        result = settle(result["state"], pending_job(result["state"], "precheck"), "eligible")
        self.assertEqual(result["state"]["cycle"]["phase"], "consent_real")
        self.assertFalse(result["effects"])
        self.assertEqual(len(result["state"]["effects"]), 3)

    def test_late_precheck_never_regresses_real_linked_form(self):
        for status in ("eligible", "ineligible", "failed"):
            with self.subTest(status=status):
                turn = qualified()
                precheck = pending_job(turn["state"], "precheck")
                linked = settle(turn["state"], pending_job(turn["state"], "relationship"), "linked")
                result = settle(linked["state"], precheck, status)
                self.assertEqual(result["state"]["cycle"]["phase"], "form")
                self.assertEqual(result["state"]["cycle"]["form_effect_id"], linked["state"]["cycle"]["form_effect_id"])
                self.assertFalse(result["effects"])

    def test_late_eligible_precheck_keeps_pending_acceptance_without_duplicate_query(self):
        turn = qualified()
        precheck = pending_job(turn["state"], "precheck")
        waiting = settle(turn["state"], pending_job(turn["state"], "relationship"), "pending")
        result = settle(waiting["state"], precheck, "eligible")
        self.assertEqual(result["state"]["cycle"]["phase"], "await_acceptance")
        self.assertFalse(result["effects"])

    def test_failed_precheck_followed_by_no_relationship_stays_blocked_without_retry(self):
        turn = qualified()
        relation = pending_job(turn["state"], "relationship")
        failed = settle(turn["state"], pending_job(turn["state"], "precheck"), "failed")
        result = settle(failed["state"], relation, "not_found")
        self.assertEqual(result["state"]["cycle"]["phase"], "blocked")
        self.assertFalse(result["effects"])

    def test_opening_keeps_knowing_amplify_and_ai_identity(self):
        turn = inbound("oi")
        self.assertEqual(turn["state"]["cycle"]["phase"], "intro")
        self.assertIn("Mandar meu @", turn["buttons"])  # release 40: o próximo passo é o @
        self.assertIn("agente de IA", turn["reply"])
        self.assertFalse(turn["effects"])

    def test_legacy_simulated_consent_and_form_are_never_promoted(self):
        old = engine._state({})
        cycle = engine._open(old, NOW)
        cycle.update(phase="form", form_url="https://old.invalid/form")
        cycle["facts"].update(consentimento_ensaio=True, aceite_no_ensaio=True)
        turn = inbound("já aceitei", old)
        self.assertNotEqual(turn["state"]["cycle"]["id"], cycle["id"])
        self.assertEqual(turn["state"]["closed_cycles"][0]["reason"], "real_mode_started")
        self.assertFalse(turn["state"]["cycle"]["facts"])
        self.assertFalse(turn["effects"])

    def test_teste_handle_is_sent_to_real_consultations(self):
        turn = qualified()
        self.assertEqual({job["operation"] for job in turn["effects"]}, {"lookup", "precheck", "relationship"})
        self.assertTrue(all(job["creator"] == "@teste" for job in turn["effects"]))
        self.assertEqual(turn["state"]["cycle"]["simulations"], [])
        self.assertNotIn("simulad", turn["reply"].lower())

    def test_eligible_requires_relationship_before_offer(self):
        turn = qualified()
        precheck = next(job for job in turn["effects"] if job["operation"] == "precheck")
        turn = settle(turn["state"], precheck, "eligible")
        self.assertEqual(turn["state"]["cycle"]["phase"], "checking")
        self.assertTrue(any(effect.get("operation") == "relationship" for effect in turn["state"]["effects"].values()))
        self.assertNotIn("invite_offer", turn["state"]["cycle"])

    def test_unknown_or_unapproved_policy_never_produces_invite(self):
        turn = eligible_state()
        for policy in (None, {}, {**POLICY, "approved": False}, {**POLICY, "commission_unit": "unknown"},
                       {**POLICY, "duration_fixed_months": 3}, {**POLICY, "commission": 11}):
            state = copy.deepcopy(turn["state"])
            state["cycle"].pop("invite_offer", None)
            result = inbound("Autorizo o convite real", state, policy=policy)
            self.assertFalse(result["effects"])
            self.assertNotIn("invite_consent", result["state"]["cycle"])

    def test_real_invite_is_explicit_and_policy_bound(self):
        turn = eligible_state()
        self.assertIn("10%", turn["reply"])
        self.assertIn("2 meses", turn["reply"])
        turn = inbound("Autorizo o convite real", turn["state"])
        self.assertEqual(turn["effects"][0]["operation"], "invite")
        self.assertTrue(turn["effects"][0]["confirmed"])
        self.assertEqual(turn["effects"][0]["commission"], 10)
        self.assertEqual(turn["effects"][0]["consent"]["creator"], "@teste")

    def test_question_or_simulated_authorization_is_not_real_consent(self):
        state = eligible_state()["state"]
        for text in ("Autorizo o convite real?", "Autorizo simulações", "Aceitei no ensaio"):
            turn = inbound(text, state)
            self.assertFalse(turn["effects"])
            self.assertNotIn("invite_consent", turn["state"]["cycle"])

    def test_changed_terms_must_be_presented_then_reconfirmed(self):
        state = eligible_state()["state"]
        policy = {**POLICY, "commission": 8, "version": "changed"}
        turn = inbound("sim", state, policy=policy)
        self.assertFalse(turn["effects"])
        self.assertIn("8%", turn["reply"])
        self.assertEqual(inbound("sim", turn["state"], policy=policy)["effects"][0]["commission"], 8)

    def test_lead_acceptance_only_queues_lookup_not_form(self):
        turn = inbound("Autorizo o convite real", eligible_state()["state"])
        turn = settle(turn["state"], turn["effects"][0], "sent")
        turn = inbound("Já aceitei", turn["state"])
        self.assertEqual(turn["state"]["cycle"]["phase"], "checking_acceptance")
        self.assertTrue(any(job.get("operation") == "relationship" and job["status"] == "pending"
                            for job in turn["state"]["effects"].values()))
        self.assertFalse(any(effect["type"] == "generate_form_link" for effect in turn["effects"]))

    def test_linked_evidence_releases_real_form(self):
        turn = qualified()
        precheck = next(job for job in turn["effects"] if job["operation"] == "precheck")
        turn = settle(turn["state"], precheck, "eligible")
        turn = settle(turn["state"], pending_job(turn["state"], "relationship"), "linked")
        self.assertEqual(turn["state"]["cycle"]["phase"], "form")
        self.assertTrue(journey.relationship_proven(turn["state"], now=NOW))
        form = turn["effects"][0]
        self.assertEqual(form["payload"]["verification_mode"], "real")
        resolved = conversation.resolve_effect(turn["state"], form["id"], form_url="https://example.com/cadastro/private", now=NOW)
        self.assertNotIn("simulad", resolved["reply"].lower())

    def test_bare_boolean_relationship_does_not_prove_form(self):
        state = qualified()["state"]
        state["cycle"]["facts"]["vinculo_confirmado"] = True
        state["cycle"]["facts"]["aceite_declarado"] = True
        self.assertFalse(journey.relationship_proven(state, now=NOW))

    def test_existing_confirmed_registration_does_not_receive_new_form(self):
        turn = qualified()
        turn["state"]["cadastro_situacao"] = "confirmado"
        precheck = next(job for job in turn["effects"] if job["operation"] == "precheck")
        turn = settle(turn["state"], precheck, "eligible")
        result = settle(turn["state"], pending_job(turn["state"], "relationship"), "linked")
        self.assertEqual(result["state"]["cycle"]["phase"], "blocked")
        self.assertEqual(result["state"]["cycle"]["block_reason"], "existing_registration_requires_confirmation")
        self.assertIn("cadastro já consta concluído", result["reply"])
        self.assertFalse(result["effects"])

    def test_missing_stale_future_or_empty_evidence_does_not_advance(self):
        turn = qualified()
        job = next(job for job in turn["effects"] if job["operation"] == "precheck")
        for updates in ({"evidence": {}}, {"observed_at": None},
                        {"observed_at": (NOW - timedelta(hours=1)).isoformat()},
                        {"observed_at": (NOW + timedelta(seconds=1)).isoformat()}):
            resolved = settle(turn["state"], job, "eligible", updates=updates)
            self.assertTrue(resolved["ignored"])
            self.assertEqual(resolved["state"]["cycle"]["phase"], "checking")

    def test_wrong_operation_or_creator_is_ignored(self):
        turn = qualified()
        job = next(job for job in turn["effects"] if job["operation"] == "precheck")
        for updates in ({"creator": "somebody_else"}, {"operation": "invite"}):
            self.assertTrue(settle(turn["state"], job, "eligible", updates=updates)["ignored"])

    def test_real_sent_requires_provider_confirmation(self):
        turn = inbound("Autorizo o convite real", eligible_state()["state"])
        resolved = settle(turn["state"], turn["effects"][0], "sent", updates={"confirmed": False})
        self.assertTrue(resolved["ignored"])

    def test_real_sent_guides_creator_to_official_invitation_navigation(self):
        turn = inbound("Autorizo o convite real", eligible_state()["state"])
        result = settle(turn["state"], turn["effects"][0], "sent")
        text = result["reply"]
        for fragment in ("TikTok Shop Creator", "*Parcerias*", "*Notificações*", "*Amplify*",
                         "percentual", "prazo", "autorizações", "somente se estiver de acordo", "consultar o TikTok"):
            self.assertIn(fragment, text)
        self.assertNotIn("7 dias", text)
        self.assertEqual(result["state"]["cycle"]["phase"], "await_acceptance")
        self.assertTrue(all(job["type"] != "generate_form_link" for job in result["effects"]))

    def test_pending_relationship_explains_navigation_without_claiming_acceptance(self):
        turn = qualified()
        precheck = next(job for job in turn["effects"] if job["operation"] == "precheck")
        turn = settle(turn["state"], precheck, "eligible")
        result = settle(turn["state"], pending_job(turn["state"], "relationship"), "pending")
        self.assertIn("ainda aparece pendente", result["reply"])
        self.assertNotIn("não substitui", result["reply"])
        self.assertIn("te aviso aqui", result["reply"])
        self.assertIn("*Parcerias*", result["reply"])
        self.assertIn("*Notificações*", result["reply"])
        self.assertFalse(result["effects"])
        self.assertEqual(result["state"]["cycle"]["phase"], "await_acceptance")

    def test_fresh_invite_precheck_can_block_without_ignoring_or_retrying(self):
        turn = inbound("Autorizo o convite real", eligible_state()["state"])
        invite = turn["effects"][0]
        result = settle(turn["state"], invite, "ineligible", updates={
            "evidence": {"source": "partner_precheck", "shop_account_status": 2, "post_attempted": False}})
        self.assertFalse(result.get("ignored", False))
        self.assertEqual(result["state"]["cycle"]["phase"], "blocked")
        self.assertEqual(result["state"]["effects"][invite["id"]]["status"], "done")
        self.assertIn("Nenhum convite foi enviado", result["reply"])
        self.assertFalse(result["effects"])

    def test_stale_eligibility_is_rechecked_before_sending_invite(self):
        state = eligible_state()["state"]
        turn = inbound("Autorizo o convite real", state, now=NOW + timedelta(minutes=16))
        self.assertEqual(turn["state"]["cycle"]["phase"], "checking")
        self.assertEqual({job["operation"] for job in turn["effects"]}, {"precheck"})
        self.assertFalse(any(job.get("operation") == "invite" for job in turn["state"]["effects"].values()))

    def test_positive_eligibility_requires_confirmed_result(self):
        turn = qualified()
        job = next(job for job in turn["effects"] if job["operation"] == "precheck")
        resolved = settle(turn["state"], job, "eligible", updates={"confirmed": False})
        self.assertTrue(resolved["ignored"])

    def test_pending_poll_same_job_can_become_linked_without_new_row(self):
        turn = qualified()
        precheck = next(job for job in turn["effects"] if job["operation"] == "precheck")
        turn = settle(turn["state"], precheck, "eligible")
        job = pending_job(turn["state"], "relationship")
        pending = settle(turn["state"], job, "pending")
        self.assertEqual(pending["state"]["effects"][job["id"]]["status"], "pending")
        linked = settle(pending["state"], job, "linked")
        self.assertEqual(linked["state"]["cycle"]["phase"], "form")
        self.assertEqual(linked["state"]["effects"][job["id"]]["status"], "done")
        self.assertTrue(settle(linked["state"], job, "linked")["ignored"])

    def test_uncertain_invite_is_never_repeated(self):
        turn = inbound("Autorizo o convite real", eligible_state()["state"])
        job = turn["effects"][0]
        turn = settle(turn["state"], job, "outcome_unknown", updates={"evidence": {}})
        self.assertEqual(turn["state"]["cycle"]["phase"], "blocked")
        self.assertIsNone(journey._effect(turn["state"], "invite", NOW, policy=POLICY))
        followup = inbound("Verificar aceite", turn["state"])
        self.assertTrue(any(effect.get("operation") == "relationship" and effect["status"] == "pending"
                            for effect in followup["state"]["effects"].values()))

    def test_profile_change_requires_confirmation_and_fences_late_callback(self):
        turn = qualified()
        precheck = next(job for job in turn["effects"] if job["operation"] == "precheck")
        proposal = inbound("@new_profile", turn["state"])
        self.assertEqual(proposal["state"]["cycle"]["facts"]["tiktok_declarado"], "@teste")
        self.assertEqual(proposal["state"]["cycle"]["pending_profile_changes"]["tiktok_declarado"], "@new_profile")
        confirmed = inbound("Confirmo", proposal["state"])
        self.assertEqual(confirmed["state"]["cycle"]["facts"]["tiktok_declarado"], "@new_profile")
        self.assertTrue(settle(confirmed["state"], precheck, "eligible")["ignored"])

    def test_reset_keeps_history_but_rejects_old_job(self):
        turn = qualified()
        job = turn["effects"][0]
        reset = inbound("resetar", turn["state"])
        self.assertEqual(len(reset["state"]["closed_cycles"]), 1)
        self.assertTrue(settle(reset["state"], job, "observed")["ignored"])
        self.assertTrue(reset["state"]["history"])

    def test_worker_result_does_not_renew_24h_lead_window(self):
        turn = qualified()
        job = next(job for job in turn["effects"] if job["operation"] == "precheck")
        deadline = turn["state"]["cycle"]["expires_at"]
        result = settle(turn["state"], job, "eligible", now=NOW + timedelta(minutes=1))
        self.assertEqual(result["state"]["cycle"]["expires_at"], deadline)
        self.assertTrue(settle(turn["state"], job, "eligible", now=NOW + timedelta(hours=24))["ignored"])

    def test_return_after_24h_is_new_cycle_and_preserves_closed_history(self):
        turn = qualified()
        result = inbound("oi", turn["state"], now=NOW + timedelta(hours=24))
        self.assertNotEqual(result["state"]["cycle"]["id"], turn["state"]["cycle"]["id"])
        self.assertEqual(result["state"]["closed_cycles"][0]["reason"], "24h_since_last_inbound")

    def test_lookup_never_fabricates_eligibility_or_gmv(self):
        turn = qualified()
        job = next(job for job in turn["effects"] if job["operation"] == "lookup")
        result = settle(turn["state"], job, "observed", updates={"confirmed": False,
            "evidence": {"source": "creator_directory", "period_and_unit_require_validation": True}})
        self.assertEqual(result["state"]["cycle"]["phase"], "checking")
        self.assertFalse(result["effects"])
        self.assertNotIn("gmv", result["state"]["cycle"]["facts"])

    def test_other_contact_rejected_before_real_dispatch(self):
        event = {"provider": "chatwoot", "account_id": "1", "inbox_id": "3", "phone": "+5547000000000",
                 "text": "oi", "message_id": "123", "conversation_id": "99"}
        result = conversation.handle_event({}, event, GATE, real_mode=True, now=NOW)
        self.assertFalse(result["accepted"])
        self.assertFalse(result["effects"])

    def test_ai_context_uses_real_mode_and_retains_personality_data_boundary(self):
        contexts = []
        inbound("Como funciona?", callback=lambda text, ctx: contexts.append(ctx))
        self.assertTrue(contexts[0]["real_mode"])
        self.assertFalse(contexts[0]["simulation_only"])
        self.assertFalse(contexts[0]["can_confirm_external_events"])
        real = guided_ai._context(contexts[0])
        self.assertFalse(real["simulated_checks"])
        self.assertTrue(real["real_mode"])

    def test_schema_and_parser_separate_real_fields_and_simulation(self):
        schema = guided_ai._schema(["approved"], real_mode=True)
        fields = schema["properties"]["claims"]["items"]["properties"]["field"]["enum"]
        self.assertIn("consentimento_convite", fields)
        self.assertNotIn("consentimento_ensaio", fields)
        value = {"reply": "Vou verificar seu aceite.", "intent": "check_acceptance", "claims": [],
                 "next_phase": "checking_acceptance", "topic_ids": []}
        response = {"output": [{"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": json.dumps(value)}]}]}
        self.assertEqual(guided_ai._parse(response, [], real_mode=True)["intent"], "check_acceptance")
        with self.assertRaises(ValueError):
            guided_ai._parse(response, [])

    def test_ai_cannot_confirm_business_success_or_simulated_permission(self):
        def malicious(text, context):
            return {"reply": "Convite enviado, vínculo confirmado.", "intent": "consent_real",
                    "claims": [{"field": "consentimento_convite", "value": "true", "quote": text}],
                    "provider_status": "completed", "next_phase": "form", "topic_ids": []}
        state = eligible_state()["state"]
        turn = inbound("Olá", state, malicious)
        self.assertFalse(turn["effects"])
        self.assertNotIn("invite_consent", turn["state"]["cycle"])
        self.assertNotIn("Convite enviado", turn["reply"])

    def test_organic_discovery_is_not_silently_recorded_as_an_ad(self):
        state = inbound("Quero me agenciar", inbound("oi")["state"])["state"]
        organic = inbound("Conheci vocês no Instagram", state)
        self.assertEqual(organic["state"]["cycle"]["facts"]["origem_declarada"], "outro")
        self.assertEqual(organic["state"]["cycle"]["facts"]["origem_canal_declarado"], "instagram")
        advert = inbound("Vi um anúncio no Instagram", state)
        self.assertEqual(advert["state"]["cycle"]["facts"]["origem_declarada"], "anuncio")

    def test_name_change_confirmation_does_not_requery_tiktok(self):
        state = eligible_state()["state"]
        state["cycle"]["facts"]["nome_declarado"] = "Nome Anterior"
        proposal = inbound("Me chamo Nome Novo", state)
        self.assertEqual(proposal["state"]["cycle"]["facts"]["nome_declarado"], "Nome Anterior")
        result = inbound("Confirmo", proposal["state"])
        self.assertEqual(result["state"]["cycle"]["facts"]["nome_declarado"], "Nome Novo")
        self.assertEqual(result["state"]["cycle"]["phase"], "consent_real")
        self.assertFalse(result["effects"])

    def test_pause_prevents_queued_operations_from_resolving(self):
        turn = qualified()
        job = turn["effects"][0]
        paused = inbound("Quero parar", turn["state"])
        self.assertEqual(paused["state"]["cycle"]["status"], "closed")
        self.assertTrue(settle(paused["state"], job, "observed")["ignored"])

    def test_not_found_after_invite_is_polled_without_resending_it(self):
        turn = inbound("Autorizo o convite real", eligible_state()["state"])
        invite = turn["effects"][0]
        turn = settle(turn["state"], invite, "sent")
        relationship = turn["effects"][0]
        turn = settle(turn["state"], relationship, "not_found")
        self.assertEqual(turn["state"]["effects"][relationship["id"]]["status"], "pending")
        self.assertEqual(turn["state"]["cycle"]["phase"], "await_acceptance")
        self.assertFalse(turn["effects"])
        self.assertEqual(sum(job.get("operation") == "invite" for job in turn["state"]["effects"].values()), 1)


class RealFormBoundaryTests(unittest.TestCase):
    def setUp(self):
        from flask import Flask
        from forms import register_forms
        from repository import Repository
        parent = Path(__file__).resolve().parent / "runtime"
        parent.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix="real-form-", dir=parent)
        self.addCleanup(self.temp.cleanup)
        self.repo = Repository(Path(self.temp.name) / "state.sqlite3")
        self.settings = {"real_mode": True, "state_dir": self.temp.name,
                         "form_secret": "fictional-form-secret-" * 3,
                         "public_url": "https://forms.example.invalid", "gate": GATE}
        self.app = Flask("real-form-boundary")
        self.app.config["TESTING"] = True
        self.app.extensions["v5_form_clock"] = lambda: NOW
        register_forms(self.app, self.settings, self.repo)
        self.client = self.app.test_client()
        turn = qualified()
        precheck = next(job for job in turn["effects"] if job["operation"] == "precheck")
        turn = settle(turn["state"], precheck, "eligible")
        turn = settle(turn["state"], pending_job(turn["state"], "relationship"), "linked")
        self.state, self.effect = turn["state"], turn["effects"][0]
        self.state["cycle"]["facts"]["nome_declarado"] = "Pessoa de Exemplo"
        self.conv = "chatwoot:1:201"
        self.event = {"provider": "chatwoot", "event": "message_created", "account_id": 1, "inbox_id": 3,
                      "message_id": 101, "conversation_id": 201, "sender_phone": GATE["phone"],
                      "sender_type": "contact", "message_type": "incoming", "private": False, "text": "já aceitei"}
        self.repo.save_session(self.conv, self.state)

    def link(self, state=None, effect=None):
        with self.app.app_context():
            return self.app.extensions["v5_form_link_factory"](state or self.state, effect or self.effect, self.event)

    def test_link_requires_worker_proof_and_correct_verification_mode(self):
        from forms import FormError
        state = copy.deepcopy(self.state)
        state["cycle"]["real_operations"] = {}
        state["cycle"]["facts"]["aceite_declarado"] = True
        with self.assertRaises(FormError) as caught:
            self.link(state)
        self.assertEqual(caught.exception.code, "real_relationship_not_proven")
        effect = copy.deepcopy(self.effect)
        effect["payload"]["verification_mode"] = "simulated"
        with self.assertRaises(FormError):
            self.link(effect=effect)

    def test_context_prefills_confirmed_name_handle_origin(self):
        url = self.link()
        token = url.rsplit("/", 1)[1]
        response = self.client.get("/cadastro/api/contexto", headers={"Authorization": "Bearer " + token})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["prefill"]["nome"], "Pessoa de Exemplo")
        self.assertEqual(response.get_json()["prefill"]["tiktok"], "@teste")
        # Release 40: a origem não é mais perguntada no chat; o formulário pergunta.
        self.assertEqual(response.get_json()["prefill"]["canal_origem"], "")

    def test_existing_form_rejects_lost_relationship_evidence(self):
        token = self.link().rsplit("/", 1)[1]
        self.state["cycle"]["real_operations"]["relationship"]["evidence"] = {}
        self.repo.save_session(self.conv, self.state)
        response = self.client.get("/cadastro/api/contexto", headers={"Authorization": "Bearer " + token})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.get_json()["code"], "real_relationship_not_proven")

    def test_form_cannot_register_a_different_tiktok_from_proven_handle(self):
        url = self.link()
        token = url.rsplit("/", 1)[1]
        self.app.extensions["v5_data_gateway"] = type("Gateway", (), {"submit": lambda self, plan: None})()
        response = self.client.post(urlsplit(url).path, json={"answers": {"tiktok": "@different"}},
                                    headers={"Authorization": "Bearer " + token})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.get_json()["code"], "tiktok_profile_changed")

    def test_proof_of_another_cycle_cannot_authorize_form(self):
        from forms import FormError
        self.state["cycle"]["real_operations"]["relationship"]["cycle_id"] = "different-cycle"
        with self.assertRaises(FormError):
            self.link()


if __name__ == "__main__":
    unittest.main()
