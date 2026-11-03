"""Offline contract checks for real journey -> projection -> form mapper."""
from copy import deepcopy
import hashlib
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock

CANDIDATE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CANDIDATE))
from data import mapper
from gateway import SubmissionRejected, tiktok_projection

CYCLE = "8f438537-57aa-430e-bbfe-e8e3c1bd692e"
CREATOR = "01999999-aaaa-4bbb-8ccc-111111111111"
FORM = "01999999-aaaa-4bbb-8ccc-222222222222"


def state_fixture():
    return {"cycle": {"mode": "real", "id": CYCLE, "facts": {"tiktok_declarado": "@teste"},
            "real_operations": {"relationship": {
                "operation": "relationship", "creator": "@teste", "status": "linked", "confirmed": True,
                "cycle_id": CYCLE, "observed_at": "2026-10-28T15:00:00+00:00",
                "job_id": "tiktok:" + "a" * 64,
                "evidence": {"source": "partner_relations", "relation_id": "12345", "status": "vinculado",
                             "tiktok_status": 1, "fresh": True, "complete": True}}}}}


def form_fixture():
    answers = {}
    for field in mapper.load_mapping()["fields"]:
        key, kind = field["id"], field["type"]
        if kind == "select":
            answers[key] = "Sim" if "Sim" in field["options"] else field["options"][0]
        elif kind == "multi_select":
            answers[key] = ["Outros"]
        elif kind == "date":
            answers[key] = "2000-01-01"
        elif kind == "number":
            answers[key] = "38.5" if key == "calcado" else "0.00"
        elif kind == "file":
            answers[key] = {"receipt": "recibo_ficticio_" + key}
        elif kind == "url":
            answers[key] = "https://example.invalid/video"
        else:
            answers[key] = "Exemplo fictício"
    cpf = "123456789"
    for length in (9, 10):
        total = sum(int(cpf[index]) * (length + 1 - index) for index in range(length))
        cpf += str(total * 10 % 11 % 10)
    answers.update(nome="Pessoa fictícia", email="PESSOA@EXAMPLE.INVALID", whatsapp="+55 (11) 99999-9999",
                   tiktok="@TeSte", cpf=cpf, cep="00000-000", cnpj="ABCDEFGHIJKL12", canal_origem="Outro jeito",
                   camiseta="Outro", plataformas=["Instagram", "Outros"], rotina="Outro",
                   alimentacao="Tenho restrições alimentares (especificar)")
    context = {"creator_id": CREATOR, "form_instance_id": FORM, "event_id": mapper.submission_id(CREATOR, FORM),
               "received_at": "2026-10-28T15:01:00Z", "source": {"kind": "formulario_whatsapp", "reference": "formulario:" + FORM},
               "execution_mode": "real", "atendimento_id": CYCLE, "attachments": {}}
    for key in ("foto_perfil", "print_gmv"):
        context["attachments"][key] = {"reference": "storage:ensaio/" + FORM + "/" + key + ".jpg",
                "receipt_sha256": hashlib.sha256(answers[key]["receipt"].encode()).hexdigest(), "source": "upload_validado"}
    payload = {"version": "amplify-cadastro-v2", "revision": 0, "step": 5, "answers": answers,
               "consent": {"accepted": True, "version": "2026-09-09-v1"}}
    return payload, context


class ProjectionTests(unittest.TestCase):
    def test_actual_real_job_identifier_and_canonical_tiktok_are_preserved(self):
        projection = tiktok_projection(state_fixture())
        receipt = projection["relationship"]
        self.assertEqual(set(receipt), {"operation", "creator", "observed_at", "status", "confirmed", "job_id", "cycle_id", "evidence"})
        self.assertEqual(receipt["job_id"], "tiktok:" + "a" * 64)
        self.assertEqual(receipt["creator"], "@teste")
        self.assertEqual(receipt["evidence"]["status"], "vinculado")

    def test_only_cycle_mode_establishes_real_projection(self):
        state = state_fixture()
        state["real_mode"] = True
        state["cycle"]["mode"] = "simulated"
        self.assertEqual(tiktok_projection(state), {})

    def test_receipt_for_another_cycle_is_rejected(self):
        state = state_fixture()
        state["cycle"]["real_operations"]["relationship"]["cycle_id"] = "other"
        with self.assertRaises(SubmissionRejected):
            tiktok_projection(state)

    def test_receipt_for_another_handle_is_rejected_before_sql(self):
        state = state_fixture()
        state["cycle"]["real_operations"]["relationship"]["creator"] = "@somebody_else"
        with self.assertRaises(SubmissionRejected):
            tiktok_projection(state)

    def test_raw_envelope_and_secrets_are_not_projected(self):
        state = state_fixture()
        receipt = state["cycle"]["real_operations"]["relationship"]
        receipt.update(raw_body={"secret": "fictional"}, bearer="fictional")
        receipt["evidence"].update(cookie="fictional", authorization="fictional")
        projected = tiktok_projection(state)["relationship"]
        self.assertNotIn("raw_body", projected)
        self.assertNotIn("bearer", projected)
        self.assertNotIn("cookie", projected["evidence"])
        self.assertNotIn("authorization", projected["evidence"])

    def test_nonfinite_and_oversized_evidence_rejected(self):
        for metrics in ({"x": float("nan")}, {"x": "a" * 4200}):
            state = state_fixture()
            state["cycle"]["real_operations"]["relationship"]["evidence"]["metrics"] = metrics
            with self.assertRaises(SubmissionRejected):
                tiktok_projection(state)

    def test_unknown_operation_or_non_utc_time_rejected(self):
        state = state_fixture()
        state["cycle"]["real_operations"]["relationship"]["observed_at"] = "2026-10-28T12:00:00-03:00"
        with self.assertRaises(SubmissionRejected):
            tiktok_projection(state)
        state = state_fixture()
        state["cycle"]["real_operations"]["delete_profile"] = {}
        with self.assertRaises(SubmissionRejected):
            tiktok_projection(state)


class MapperRealModeTests(unittest.TestCase):
    def test_real_source_mode_cycle_and_tiktok_case_are_normalized(self):
        payload, context = form_fixture()
        plan = mapper.map_submission(payload, context)
        self.assertEqual(plan["context"]["execution_mode"], "real")
        self.assertEqual(plan["context"]["source"]["kind"], "formulario_whatsapp")
        self.assertEqual(plan["context"]["atendimento_id"], CYCLE)
        self.assertEqual(plan["payload"]["identity"]["tiktok"], "teste")
        self.assertEqual(plan["coverage"]["mapped"], 63)

    def test_real_mode_requires_attendance_before_sql(self):
        payload, context = form_fixture()
        context.pop("atendimento_id")
        with self.assertRaises(mapper.MappingError):
            mapper.map_submission(payload, context)

    def test_simulated_source_cannot_be_paired_with_real_mode(self):
        payload, context = form_fixture()
        context["source"]["kind"] = "formulario_ensaio"
        with self.assertRaises(mapper.MappingError):
            mapper.map_submission(payload, context)

    def test_real_source_cannot_implicitly_enable_real_mode(self):
        payload, context = form_fixture()
        context.pop("execution_mode")
        with self.assertRaises(mapper.MappingError):
            mapper.map_submission(payload, context)

    def test_legacy_mode_is_preserved_without_promoting_it(self):
        payload, context = form_fixture()
        context.pop("execution_mode")
        context["source"]["kind"] = "formulario_ensaio"
        plan = mapper.map_submission(payload, context)
        self.assertNotIn("execution_mode", plan["context"])
        self.assertEqual(plan["context"]["source"]["kind"], "formulario_ensaio")


class FakeSmtp:
    def __init__(self):
        self.messages = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def login(self, username, password):
        return None

    def send_message(self, message):
        self.messages.append(message)
        return {}


class SmtpRealModeTests(unittest.TestCase):
    def sender(self):
        from smtp import SmtpSender
        fake = FakeSmtp()
        factory = Mock(return_value=fake)
        sender = SmtpSender({"tiktok_mode": "real", "smtp_user": "bia@example.invalid",
                             "smtp_password": "fictional-only", "smtp_from_name": "Bia · Amplify"}, factory=factory)
        return sender, fake, factory

    def test_real_otp_contains_no_simulation_text(self):
        sender, smtp, factory = self.sender()
        result = sender.send_otp("person@example.invalid", "123456", "fictional-otp-operation")
        self.assertEqual(result["status"], "accepted")
        factory.assert_called_once()
        message = smtp.messages[0]
        self.assertIn("123456", message.get_content())
        self.assertIn("agente de IA", message.get_content())
        for word in ("ensaio", "simulad"):
            self.assertNotIn(word, str(message["Subject"]).lower() + message.get_content().lower())

    def test_real_receipt_contains_registration_and_separate_access_status(self):
        sender, smtp, factory = self.sender()
        result = sender.send_receipt("person@example.invalid", {"status": "cadastro_recebido_real",
                                    "creator_id": CREATOR, "event_id": mapper.submission_id(CREATOR, FORM)}, "fictional-receipt")
        self.assertEqual(result["status"], "accepted")
        factory.assert_called_once()
        text = smtp.messages[0].get_content().lower()
        self.assertIn("registrado na base da amplify", text)
        self.assertIn("acessos terá sua própria confirmação", text)
        self.assertNotIn("simulad", text)
        self.assertNotIn("ensaio", text)
        self.assertFalse(result["inbox_delivery_confirmed"])

    def test_missing_simulated_or_incomplete_receipt_never_sends_real_confirmation(self):
        for receipt in (None, {}, {"status": "cadastro_recebido_ensaio"}, {"status": "cadastro_recebido_real"},
                        {"status": "cadastro_recebido_real", "creator_id": "invalid", "event_id": "invalid"}):
            with self.subTest(receipt=receipt):
                sender, smtp, factory = self.sender()
                result = sender.send_receipt("person@example.invalid", receipt, "fictional-receipt")
                self.assertEqual(result["status"], "failed")
                self.assertEqual(smtp.messages, [])
                factory.assert_not_called()


class ServerRealDataBoundaryTests(unittest.TestCase):
    def test_real_config_requires_data_sync_even_with_other_incomplete_fields(self):
        from config import load_settings
        settings = load_settings({"V5_TIKTOK_MODE": "real", "V5_CONTACT_SYNC_ENABLED": "false"})
        self.assertIn("real_mode_requires_data_sync", settings["readiness_issues"])

    def test_injected_real_server_settings_cannot_skip_data_sync(self):
        from server import create_app
        settings = {"tiktok_mode": "real", "real_worker_enabled": True, "contact_sync_enabled": False,
                    "conversation_enabled": True, "ai_enabled": True,
                    "webhook_token": "fictional-webhook-secret" * 2,
                    "gate": {"enabled": True, "provider": "chatwoot", "account_id": "1", "inbox_id": "3",
                             "phone": "+5547991154859"}}
        repository = type("LocalRepository", (), {"ready": lambda self: True})()
        transport = type("LocalTransport", (), {"ready": lambda self: True})()
        real_client = type("LocalClient", (), {"configuration": lambda self, operation=None: {"configured": True}})()
        app = create_app(settings=settings, repository=repository, transport=transport, real_client=real_client)
        response = app.test_client().get("/ready")
        self.assertEqual(response.status_code, 503)
        self.assertIn("real_mode_requires_data_sync", response.get_json()["issues"])


if __name__ == "__main__":
    unittest.main()
