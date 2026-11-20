"""Auditoria 20/11/2026: a conferência do @ não devolve resultado velho (consulta que passou da espera)."""
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

from agency import AgencyChecker  # noqa: E402


def _checker(results, fresh_seconds):
    checker = AgencyChecker("x" * 40, wait_seconds=0.05, fresh_seconds=fresh_seconds)
    calls, release = [], threading.Event()

    def run(handle):
        calls.append(handle)
        release.wait(2)
        return dict(results[min(len(calls), len(results)) - 1])

    checker._run = run
    return checker, calls, release


def _esperar_terminar(checker, handle):
    future = checker._inflight[handle]
    future.result(timeout=2)
    deadline = time.monotonic() + 2
    while future not in checker._finished and time.monotonic() < deadline:
        time.sleep(0.01)


def test_resultado_recente_e_reaproveitado():
    checker, calls, release = _checker([{"status": "pending"}], fresh_seconds=60)
    try:
        assert checker.check("ana") is None  # passou da espera
        release.set(); _esperar_terminar(checker, "ana")
        assert checker.check("ana") == {"status": "pending"}
        assert len(calls) == 1
    finally:
        release.set(); checker.pool.shutdown()


def test_resultado_velho_gera_nova_consulta():
    checker, calls, release = _checker([{"status": "pending"}, {"status": "not_found"}], fresh_seconds=0)
    try:
        assert checker.check("ana") is None
        release.set(); _esperar_terminar(checker, "ana")
        time.sleep(0.02)
        assert checker.check("ana") == {"status": "not_found"}
        assert len(calls) == 2
    finally:
        release.set(); checker.pool.shutdown()
