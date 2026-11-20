"""Auditoria 20/11/2026: "código incorreto" quando o primeiro e-mail chega depois do reenvio."""
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

from store import Store  # noqa: E402

EMAIL = "e" * 64
TTL, WAIT, MAX = 600, 60, 10


def _store(tmp_path):
    store = Store(tmp_path / "estado.sqlite3")
    store.open_session("f1", "cliente")
    return store


def _pedir(store, code, now):
    assert store.claim_email_code("f1", EMAIL, code, now=now, ttl=TTL, wait=WAIT) == "claimed"
    store.finish_email_code("f1", code, "enviado")


def _conferir(store, code, now, email=EMAIL):
    return store.confirm_email_code("f1", email, code, "sha", "2026-11-20T10:00:00Z", now=now, maximum=MAX)


def test_codigo_anterior_ainda_vale_depois_do_reenvio(tmp_path):
    store = _store(tmp_path)
    _pedir(store, "codigo-1", 1000)
    _pedir(store, "codigo-2", 1070)
    assert _conferir(store, "codigo-1", 1100) == "confirmado"


def test_vale_o_atual_e_os_dois_anteriores_mas_nao_o_quarto(tmp_path):
    store = _store(tmp_path)
    for index, at in enumerate((1000, 1070, 1140, 1210), start=1):
        _pedir(store, f"codigo-{index}", at)
    assert _conferir(store, "codigo-1", 1250) == "codigo_incorreto"
    assert _conferir(store, "codigo-2", 1250) == "confirmado"


def test_codigo_vencido_ou_de_outro_email_nao_vale(tmp_path):
    store = _store(tmp_path)
    _pedir(store, "codigo-1", 1000)
    _pedir(store, "codigo-2", 1070)
    assert _conferir(store, "codigo-1", 1000 + TTL + 1) == "codigo_incorreto"
    assert _conferir(store, "codigo-2", 1100, email="x" * 64) == "expirado"


def test_codigo_anterior_vale_enquanto_o_novo_ainda_esta_sendo_enviado(tmp_path):
    store = _store(tmp_path)
    _pedir(store, "codigo-1", 1000)
    assert store.claim_email_code("f1", EMAIL, "codigo-2", now=1070, ttl=TTL, wait=WAIT) == "claimed"
    assert _conferir(store, "codigo-1", 1080) == "confirmado"


def test_limite_de_tentativas_continua_valendo(tmp_path):
    store = _store(tmp_path)
    _pedir(store, "codigo-1", 1000)
    for _ in range(MAX):
        assert _conferir(store, "errado", 1010) == "codigo_incorreto"
    assert _conferir(store, "codigo-1", 1010) == "tentativas_esgotadas"


def test_banco_antigo_ganha_a_coluna_nova(tmp_path):
    path = tmp_path / "antigo.sqlite3"
    with sqlite3.connect(path) as db:
        db.execute("""CREATE TABLE sessions (form_id TEXT PRIMARY KEY, created_at REAL NOT NULL, client_hash TEXT,
            agency_handle TEXT, agency_json TEXT, agency_at REAL, otp_email_hash TEXT, otp_code_hash TEXT,
            otp_expires_at REAL, otp_attempts INTEGER NOT NULL DEFAULT 0, otp_sent_json TEXT NOT NULL DEFAULT '[]',
            otp_status TEXT, email_hash TEXT, email_sha256 TEXT, email_verified_at TEXT, initial_hash TEXT,
            submitted_json TEXT)""")
        db.execute("INSERT INTO sessions(form_id, created_at) VALUES('f1', 1)")
    store = Store(path)
    _pedir(store, "codigo-1", 1000)
    _pedir(store, "codigo-2", 1070)
    assert _conferir(store, "codigo-1", 1100) == "confirmado"
