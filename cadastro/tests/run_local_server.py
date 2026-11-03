"""Sobe o formulário real (cadastro.html original) em http://127.0.0.1:8765/cadastro,
com banco PostgreSQL local, ponte TikTok simulada, e-mail e IA simulados.

@ vinculados no dublê: vinculada.ok, bia.lead, outra.pessoa, print.borrado
@ pendente: convite.pendente   |   qualquer outro @: não encontrado
O código de e-mail aparece em http://127.0.0.1:8765/__teste/codigo (só neste servidor local).
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent / "app")]

from fakes import READING_OK, FakeBridge, FakeEmail, PgGateway, openai_transport  # noqa: E402
from local_pg import ROOT, LocalPostgres  # noqa: E402

import cadastro_pilot  # noqa: E402
from agency import AgencyChecker  # noqa: E402
from cadastro_server import Deps, create_app  # noqa: E402
from gmv_print import GmvPrintReader  # noqa: E402
from store import Store  # noqa: E402
from test_cadastro_publico import RELATIONS  # noqa: E402

PORT = 8765

if __name__ == "__main__":
    pg = LocalPostgres().start(ROOT / "sql" / "001_cadastro_publico_v5.sql")
    try:
        email = FakeEmail()
        deps = Deps(secret="s" * 40, public_url=f"http://127.0.0.1:{PORT}", store=Store(pg.dir / "estado.sqlite3"),
                    v5=PgGateway(pg.dsn), agency=AgencyChecker("t" * 40, transport=FakeBridge(RELATIONS)), email=email,
                    gmv_reader=GmvPrintReader("chave-teste", "modelo-teste", transport=openai_transport(READING_OK)))
        app = cadastro_pilot.create_app(base_app_factory=lambda: create_app(deps), environ={"CADASTRO_V5_PILOT_ENABLED": "true"})
        app.add_url_rule("/__teste/codigo", "codigo", lambda: {"enviados": email.sent})
        (HERE.parent / "tests" / ".local_dsn").write_text(pg.dsn)
        print("pronto", pg.dsn, flush=True)
        app.run(host="127.0.0.1", port=PORT, threaded=True, use_reloader=False)
    finally:
        pg.stop()
