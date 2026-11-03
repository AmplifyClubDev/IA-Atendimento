"""Original browser protocol, private local fixtures and injected mail/SQL doubles."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import io
import json
from pathlib import Path
import shutil
import struct
import tempfile
import unittest
from urllib.parse import urlsplit
from uuid import UUID, uuid4
import zlib

from flask import Flask
from forms import register_forms
from repository import Repository
from data.mapper import load_mapping


NOW = datetime(2026, 10, 29, 3, tzinfo=timezone.utc)
PHONE = "+5511999999999"
ORIGINAL = "https://amplify-cadastro.up.railway.app/cadastro/ensaio"
ROOT = Path(__file__).resolve().parents[1]


def png():
    def chunk(name, data):
        return struct.pack("!I", len(data)) + name + data + struct.pack("!I", zlib.crc32(name + data) & 0xffffffff)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack("!2I5B", 1, 1, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(b"\x00\x00\x00\x00")) + chunk(b"IEND", b""))


def complete_answers():
    result = {}
    for field in load_mapping()["fields"]:
        key, kind = field["id"], field["type"]
        if kind == "select":
            result[key] = "Sim" if "Sim" in field["options"] else field["options"][0]
        elif kind == "multi_select":
            result[key] = ["Outros"]
        elif kind == "date":
            result[key] = "2000-01-01"
        elif kind == "number":
            result[key] = "38.5" if key == "calcado" else "0.00"
        elif kind == "url":
            result[key] = "https://example.invalid/video"
        else:
            result[key] = "Exemplo fictício"
    digits = "123456789"
    for length in (9, 10):
        digits += str(sum(int(digits[i]) * (length + 1 - i) for i in range(length)) * 10 % 11 % 10)
    result.update(nome="Pessoa fictícia", email="pessoa@example.invalid", whatsapp=PHONE,
                  tiktok="@contato_exemplo_v5", cpf=digits, cep="00000-000", cnpj="ABCDEFGHIJKL12",
                  canal_origem="Outro jeito", camiseta="Outro", plataformas=["Instagram", "Outros"],
                  rotina="Outro", alimentacao="Tenho restrições alimentares (especificar)")
    return result


class Mail:
    def __init__(self):
        self.otp, self.receipts, self.status = [], [], "accepted"
    def send_otp(self, email, code, operation):
        self.otp.append((email, code, operation))
        return {"status": self.status}
    def send_receipt(self, email, receipt, operation):
        self.receipts.append((email, receipt, operation))
        return {"status": "accepted"}


class Gateway:
    def __init__(self):
        self.calls, self.unknown = [], False
    def submit(self, plan):
        self.calls.append(deepcopy(plan))
        if self.unknown:
            raise TimeoutError("fictional uncertain commit")
        return {"status": "cadastro_recebido_real", "creator_id": plan["context"]["creator_id"],
                "event_id": plan["context"]["event_id"]}


class OriginalFormCompatTests(unittest.TestCase):
    def setUp(self):
        self.parent = (ROOT / "tests" / "runtime").resolve()
        self.parent.mkdir(parents=True, exist_ok=True)
        self.folder = Path(tempfile.mkdtemp(prefix="original-form-", dir=self.parent)).resolve()
        self.addCleanup(self.cleanup)
        self.repo = Repository(self.folder / "state.sqlite3")
        self.settings = {"state_dir": str(self.folder), "form_secret": "s" * 40,
            "public_url": "https://forms.example.invalid", "form_public_url": ORIGINAL,
            "tiktok_mode": "real", "contact_sync_enabled": True,
            "gate": {"enabled": True, "provider": "chatwoot", "account_id": "1", "inbox_id": "3", "phone": PHONE}}
        self.now = NOW
        self.app = Flask("original-form-compat-tests")
        self.app.config.update(TESTING=True, MAX_CONTENT_LENGTH=128_000)
        self.mail, self.gateway = Mail(), Gateway()
        self.app.extensions.update(v5_form_clock=lambda: self.now, v5_email_sender=self.mail, v5_data_gateway=self.gateway)
        register_forms(self.app, self.settings, self.repo)
        self.client = self.app.test_client()
        self.conv = "chatwoot:1:201"
        creator, cycle, job = str(uuid4()), str(uuid4()), "relationship-effect"
        self.state = {"creator_id": creator, "session_id": str(uuid4()), "effects": {job: {
            "id": job, "type": "tiktok_operation", "operation": "relationship", "status": "done",
            "cycle_id": cycle, "creator": "@contato_exemplo_v5"}}, "history": [], "cycle": {
            "id": cycle, "mode": "real", "number": 1, "status": "open", "phase": "form",
            "opened_at": NOW.isoformat(), "last_inbound_at": NOW.isoformat(),
            "expires_at": (NOW + timedelta(hours=24)).isoformat(), "facts": {
                "tiktok_declarado": "@contato_exemplo_v5", "nome_declarado": "Pessoa fictícia", "origem_declarada": "indicacao"},
            "real_operations": {"relationship": {"job_id": job, "creator": "@contato_exemplo_v5", "cycle_id": cycle,
                "status": "linked", "confirmed": True, "observed_at": NOW.isoformat(), "evidence": {"source": "partner_relations"}}}}}
        self.repo.save_session(self.conv, self.state)
        self.effect = {"id": "form-effect", "type": "generate_form_link", "cycle_id": cycle,
                       "payload": {"verification_mode": "real", "relationship_job_id": job}}
        self.event = {"provider": "chatwoot", "event": "message_created", "account_id": 1, "inbox_id": 3,
            "message_id": 101, "conversation_id": 201, "sender_phone": PHONE,
            "sender_type": "contact", "message_type": "incoming", "private": False, "text": "já aceitei"}
        with self.app.app_context():
            self.url = self.app.extensions["v5_form_link_factory"](self.state, self.effect, self.event)
        self.token = urlsplit(self.url).fragment.removeprefix("s=")
        self.headers = {"Authorization": "Bearer " + self.token, "Origin": "https://amplify-cadastro.up.railway.app"}
        self.answers, self.revision = complete_answers(), 0

    def cleanup(self):
        target = self.folder.resolve()
        if not target.is_relative_to(self.parent) or not target.name.startswith("original-form-"):
            raise AssertionError("cleanup outside owned fixture")
        shutil.rmtree(target)

    def post(self, path, value):
        return self.client.post("/cadastro/compat/" + path, json=value, headers=self.headers)

    def context(self):
        return self.client.get("/cadastro/compat/contexto", headers=self.headers)

    def payload(self, step=0, final=False):
        value = {"version": "amplify-cadastro-v2", "revision": self.revision, "step": step, "answers": deepcopy(self.answers)}
        if final:
            value["consent"] = {"accepted": True, "version": "2026-09-09-v1"}
        return value

    def gate(self):
        response = self.post("agenciamento", {"tiktok": "contato_exemplo_v5"})
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(response.get_json()["status"], "aprovada")

    def verify(self):
        email = self.answers["email"]
        sent = self.post("email/solicitar", {"email": email})
        self.assertEqual(sent.status_code, 200, sent.get_json())
        confirmed = self.post("email/confirmar", {"email": email, "code": self.mail.otp[-1][1]})
        self.assertTrue(confirmed.get_json()["verified"], confirmed.get_json())

    def upload(self, field):
        result = self.client.post("/cadastro/compat/anexos?campo=" + field, data=png(),
            headers={**self.headers, "Content-Type": "image/png"})
        self.assertEqual(result.status_code, 201, result.get_json())
        self.assertEqual(set(result.get_json()), {"receipt"})
        self.answers[field] = result.get_json()
        return result.get_json()

    def initial(self):
        self.gate()
        self.verify()
        response = self.post("validacao-inicial", {key: self.answers[key] for key in ("nome", "email", "whatsapp", "tiktok")})
        self.assertEqual(response.status_code, 200, response.get_json())

    def ready(self):
        self.initial()
        self.upload("foto_perfil")
        self.upload("print_gmv")

    def test_private_link_context_has_exact_original_protocol_and_stable_bound_identity(self):
        self.assertTrue(self.url.startswith(ORIGINAL + "#s="))
        self.assertEqual(len(self.token), 43)
        value = self.context().get_json()
        self.assertEqual(value["token"], self.token)
        self.assertTrue(value["cycle_bound"])
        self.assertNotEqual(UUID(value["resume_key"]).int, 0)
        self.assertEqual((value["revision"], value["step"], value["submitted"]), (0, 0, False))
        self.assertEqual(value["answers"], {})
        self.assertEqual(value["prefill"]["whatsapp"], PHONE)
        self.assertEqual(self.context().get_json()["resume_key"], value["resume_key"])
        self.assertEqual(self.gateway.calls, [])
        self.assertEqual(self.mail.otp, [])
        self.assertEqual(self.client.get("/cadastro/" + self.token).status_code, 303)
        self.assertEqual(self.client.get("/cadastro/" + self.token).headers["Location"], self.url)

    def test_missing_token_wrong_origin_wrong_phone_and_wrong_profile_do_not_select_other_person(self):
        self.assertEqual(self.client.get("/cadastro/compat/contexto").status_code, 401)
        response = self.client.get("/cadastro/compat/contexto", headers={**self.headers, "Origin": "https://foreign.invalid"})
        self.assertEqual(response.status_code, 403)
        self.assertIn("erro", response.get_json())
        self.assertEqual(self.post("agenciamento", {"tiktok": "other_creator"}).status_code, 409)
        self.initial()
        value = {key: self.answers[key] for key in ("nome", "email", "whatsapp", "tiktok")}
        value["whatsapp"] = "+5511888888888"
        self.assertEqual(self.post("validacao-inicial", value).status_code, 403)
        self.assertEqual(self.gateway.calls, [])

    def test_declared_acceptance_without_current_matching_relationship_cannot_open_gate(self):
        self.state["cycle"]["real_operations"]["relationship"]["confirmed"] = False
        self.state["cycle"]["facts"]["vinculo_confirmado"] = True
        self.repo.save_session(self.conv, self.state)
        response = self.post("agenciamento", {"tiktok": "contato_exemplo_v5"})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.get_json()["code"], "real_relationship_not_proven")

    def test_scope_cycle_and_profile_changes_invalidate_existing_form(self):
        self.state["cycle"]["id"] = str(uuid4())
        self.repo.save_session(self.conv, self.state)
        self.assertEqual(self.context().status_code, 410)

    def test_otp_status_is_read_only_wrong_code_persists_attempt_and_unknown_send_never_retries(self):
        email = self.answers["email"]
        self.assertEqual(self.post("email/estado", {"email": email}).get_json()["status"], "nao_solicitado")
        self.assertEqual(self.mail.otp, [])
        self.mail.status = "outcome_unknown"
        self.assertEqual(self.post("email/solicitar", {"email": email}).get_json()["status"], "incerto")
        self.post("email/solicitar", {"email": email})
        self.assertEqual(len(self.mail.otp), 1)
        code = self.mail.otp[-1][1]
        wrong = "000000" if code != "000000" else "111111"
        self.assertEqual(self.post("email/confirmar", {"email": email, "code": wrong}).get_json()["status"], "codigo_incorreto")
        self.assertEqual(self.app.extensions["v5_forms_store"].row(self.token)["otp_tries"], 1)
        self.assertTrue(self.post("email/confirmar", {"email": email, "code": code}).get_json()["verified"])

    def test_changed_email_requires_new_otp_and_invalidates_initial_validation(self):
        self.initial()
        self.answers["email"] = "other@example.invalid"
        self.assertFalse(self.post("email/estado", {"email": self.answers["email"]}).get_json()["verified"])
        self.verify()
        row = self.app.extensions["v5_forms_store"].row(self.token)
        self.assertTrue(row["verified_at"])
        self.assertEqual(len(self.mail.otp), 2)
        # The initial step had confirmed the former email; it must run again.
        self.upload("foto_perfil")
        self.upload("print_gmv")
        response = self.client.put("/cadastro/compat/respostas", json=self.payload(step=1), headers=self.headers)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.get_json()["code"], "initial_validation_required")

    def test_draft_cas_is_one_row_and_replays_exact_save_without_rpc_or_email(self):
        self.gate()
        self.answers = {key: self.answers[key] for key in ("nome", "email", "whatsapp", "tiktok")}
        value = self.payload()
        for _ in range(2):
            response = self.client.put("/cadastro/compat/respostas", json=value, headers=self.headers)
            self.assertEqual(response.status_code, 200, response.get_json())
            self.assertEqual(response.get_json()["revision"], 1)
        value["answers"]["nome"] = "Outra grafia"
        self.assertEqual(self.client.put("/cadastro/compat/respostas", json=value, headers=self.headers).status_code, 409)
        with self.app.extensions["v5_forms_store"].db() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM v5_form_drafts").fetchone()[0], 1)
        self.assertEqual(self.context().get_json()["answers"]["nome"], "Pessoa fictícia")
        self.assertEqual(self.gateway.calls, [])
        self.assertEqual(self.mail.otp, [])

    def test_step_advance_requires_gate_initial_identity_and_verified_email(self):
        self.answers = {key: self.answers[key] for key in ("nome", "email", "whatsapp", "tiktok")}
        self.assertEqual(self.client.put("/cadastro/compat/respostas", json=self.payload(), headers=self.headers).status_code, 409)
        self.gate()
        response = self.client.put("/cadastro/compat/respostas", json=self.payload(step=1), headers=self.headers)
        self.assertEqual(response.status_code, 403)
        self.verify()
        response = self.client.put("/cadastro/compat/respostas", json=self.payload(step=1), headers=self.headers)
        self.assertEqual(response.status_code, 409)

    def test_raw_upload_private_restore_and_receipt_scope(self):
        receipt = self.upload("foto_perfil")
        value = {**receipt, "field": "foto_perfil"}
        response = self.post("imagem", value)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "image/jpeg")
        self.assertTrue(response.data.startswith(b"\xff\xd8"))
        response.close()
        self.assertEqual(self.post("imagem", {**receipt, "field": "print_gmv"}).status_code, 404)
        self.assertNotIn("path", json.dumps(receipt))

    def test_original_six_step_journey_and_final_63_field_single_commit_have_honest_outcome(self):
        self.ready()
        for step in range(6):
            response = self.client.put("/cadastro/compat/respostas", json=self.payload(step), headers=self.headers)
            self.assertEqual(response.status_code, 200, response.get_json())
            self.revision = response.get_json()["revision"]
            self.assertEqual(self.context().get_json()["step"], step)
        final = self.payload(5, final=True)
        for _ in range(2):
            response = self.post("respostas", final)
            self.assertEqual(response.status_code, 200, response.get_json())
            value = response.get_json()
            self.assertTrue(value["submitted"])
            self.assertEqual(value["outcome"], {"status": "cadastro_recebido"})
        self.assertEqual(len(self.gateway.calls), 1)
        self.assertEqual(self.gateway.calls[0]["coverage"]["mapped"], 63)
        self.assertEqual(self.gateway.calls[0]["context"]["creator_id"], self.state["creator_id"])
        self.assertEqual(self.gateway.calls[0]["context"]["atendimento_id"], self.state["cycle"]["id"])
        self.assertEqual(len(self.mail.receipts), 1)
        self.assertTrue(self.context().get_json()["submitted"])
        restored = self.post("imagem", {**self.answers["foto_perfil"], "field": "foto_perfil"})
        self.assertEqual(restored.status_code, 200)
        restored.close()
        self.assertEqual(self.post("email/estado", {"email": self.answers["email"]}).status_code, 200)
        self.assertGreaterEqual(self.post("email/solicitar", {"email": self.answers["email"]}).status_code, 400)
        self.assertEqual(self.repo.load_session(self.conv)["cycle"]["reason"], "validated_form")

    def test_final_consent_and_all_fields_remain_required(self):
        self.ready()
        value = self.payload(5, final=True)
        value["consent"]["accepted"] = False
        self.assertEqual(self.post("respostas", value).status_code, 400)
        value["consent"]["accepted"] = True
        del value["answers"]["cpf"]
        self.assertEqual(self.post("respostas", value).status_code, 400)
        self.assertEqual(self.gateway.calls, [])

    def test_uncertain_commit_is_not_success_and_never_repeats_external_post(self):
        self.ready()
        self.gateway.unknown = True
        value = self.payload(5, final=True)
        for _ in range(2):
            result = self.post("respostas", value)
            self.assertEqual(result.status_code, 409, result.get_json())
            self.assertNotIn("submitted", result.get_json())
            self.assertIn("erro", result.get_json())
        self.assertEqual(len(self.gateway.calls), 1)
        self.assertEqual(self.context().status_code, 409)
        self.assertEqual(self.mail.receipts, [])

    def test_original_step_zero_sequence_saves_access_before_email_then_advances_same_form(self):
        self.gate()
        self.answers = {key: self.answers[key] for key in ("nome", "email", "whatsapp", "tiktok")}
        first = self.client.put("/cadastro/compat/respostas", json=self.payload(0), headers=self.headers)
        self.assertEqual(first.status_code, 200, first.get_json())
        self.revision = first.get_json()["revision"]
        self.assertFalse(self.post("email/estado", {"email": self.answers["email"]}).get_json()["verified"])
        self.verify()
        initial = {key: self.answers[key] for key in ("nome", "email", "whatsapp", "tiktok")}
        self.assertEqual(self.post("validacao-inicial", initial).get_json()["status"], "aprovada")
        second = self.client.put("/cadastro/compat/respostas", json=self.payload(1), headers=self.headers)
        self.assertEqual(second.status_code, 200, second.get_json())
        self.assertEqual(second.get_json()["revision"], 2)
        self.assertEqual(self.context().get_json()["step"], 1)
        self.assertEqual(self.gateway.calls, [])

    def test_relink_existing_changes_only_exact_current_pilot_url_and_is_idempotent(self):
        self.state["revision"] = 33
        self.state["cycle"]["form_url"] = "https://forms.example.invalid/cadastro/" + self.token
        self.repo.save_session(self.conv, self.state)
        expected = deepcopy(self.state)
        expected["cycle"]["form_url"] = self.url
        with self.app.app_context():
            first = self.app.extensions["v5_form_relink_existing"]()
            second = self.app.extensions["v5_form_relink_existing"]()
        self.assertEqual(first, {"updated": 1, "skipped": 0})
        self.assertEqual(second, {"updated": 0, "skipped": 1})
        self.assertEqual(self.repo.load_session(self.conv), expected)
        self.assertEqual(self.gateway.calls, [])
        self.assertEqual(self.mail.otp, [])

    def test_expired_link_and_malformed_or_operational_draft_fields_cannot_write(self):
        self.gate()
        self.answers = {"creator_id": str(uuid4())}
        self.assertEqual(self.client.put("/cadastro/compat/respostas", json=self.payload(), headers=self.headers).status_code, 400)
        self.now = NOW + timedelta(hours=24)
        self.assertEqual(self.context().status_code, 410)


if __name__ == "__main__":
    unittest.main()
