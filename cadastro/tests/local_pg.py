"""PostgreSQL 17 descartável, só em 127.0.0.1, com o esquema do AmplifyOS-v5.

Reaplica a mesma sequência de arquivos usada nos testes anteriores do V5
(baseline -> consultas -> contato/cadastro reais -> retenção) e depois a
migration nova. Nenhum DSN remoto ou credencial de produção é usado.
"""
from __future__ import annotations

import os
import re
import shutil
import socket
import subprocess
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
ARTIFACTS = ROOT.parent
REPO = ARTIFACTS.parent
PACKAGE = REPO / ".maestri" / "roles" / "3370b0e3-edaa-481b-b0db-9de40491a858" / "central-inteligencia-20261020" / "pg" / "pgsql"
# initdb não aceita o caminho com acentos ("Área de Trabalho"): usa uma cópia em pasta ASCII.
ASCII_PACKAGE = Path(tempfile.gettempdir()) / "cadastro-v5-pgsql"
if not (ASCII_PACKAGE / "bin" / "initdb.exe").exists():
    shutil.copytree(PACKAGE, ASCII_PACKAGE, dirs_exist_ok=True)
BIN = ASCII_PACKAGE / "bin"
PUBLIC = ARTIFACTS / "v5-public-20261028"
SUMMARY = ARTIFACTS / "v5-banco-resumo-20261028"
REAL = ARTIFACTS / "v5-integracao-real-20261028" / "sql"
RETENTION = ARTIFACTS / "v5-retencao-20261029" / "sql"
CHAIN = [
    PUBLIC / "baseline-empty-schema.sql", PUBLIC / "consolidar-public.sql",
    PUBLIC / "simplificar-todas-consultas.sql", PUBLIC / "ativar-reset-chat.sql",
    SUMMARY / "registrar-contato-live.sql", SUMMARY / "atendimentos-view-before.sql",
    SUMMARY / "aplicar-resumo-atendimentos.sql", REAL / "public-registrar_cadastro_ensaio_v5-before.sql",
    REAL / "aplicar-integracao-real-v2.sql", RETENTION / "aplicar-retencao.sql",
]
FLAGS = getattr(subprocess, "CREATE_NO_WINDOW", 0)
GUARD = re.compile(r"DO \$guard\$.*?\$guard\$;", re.S)


class LocalPostgres:
    def __init__(self):
        self.dir = Path(tempfile.mkdtemp(prefix="cadastro-v5-pg-"))
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            self.port = str(sock.getsockname()[1])
        self.dsn = f"postgresql://postgres@127.0.0.1:{self.port}/v5"
        self.started = False

    def run(self, exe, *args, text=None):
        result = subprocess.run([str(BIN / exe), *map(str, args)], input=text, capture_output=True, text=True,
                                encoding="utf-8", errors="replace", timeout=180, creationflags=FLAGS,
                                env={**os.environ, "PGCLIENTENCODING": "UTF8"})
        if result.returncode:
            raise RuntimeError(f"{exe}: {result.stderr[-3000:]}{result.stdout[-1500:]}")
        return result.stdout

    def sql(self, text):
        return self.run("psql.exe", "-X", "-q", "-A", "-t", "-v", "ON_ERROR_STOP=1", "-h", "127.0.0.1", "-p",
                        self.port, "-U", "postgres", "-d", "v5", text=text)

    def runfile(self, path, *, strip_guard=False):
        text = path.read_text(encoding="utf-8-sig")
        if strip_guard:
            # Os guards de produção conferem hashes do banco real; no banco descartável
            # eles são removidos (como nos testes anteriores do V5).
            text = GUARD.sub("-- guard de producao omitido no banco local", text)
        has_tx = re.match(r"\s*(--[^\n]*\n\s*)*BEGIN;", text, re.I) is not None
        try:
            return self.sql(text if has_tx else "BEGIN;\n" + text + "\n;\nCOMMIT;")
        except RuntimeError as error:
            raise RuntimeError(path.name + ": " + str(error)) from None

    def start(self, migration=None):
        self.run("initdb.exe", "-L", BIN.parent / "share", "-D", self.dir / "data", "-U", "postgres",
                 "--locale=C", "--encoding=UTF8", "--auth=trust")
        # Saída em arquivo: o servidor herda os descritores e um pipe nunca fecharia.
        with open(self.dir / "pg_ctl.out", "wb") as out:
            subprocess.run([str(BIN / "pg_ctl.exe"), "-D", str(self.dir / "data"), "-l", str(self.dir / "pg.log"), "-o",
                            f"-h 127.0.0.1 -p {self.port} -c shared_buffers=16MB -c max_connections=20", "-w", "start"],
                           check=True, stdout=out, stderr=out, timeout=120, creationflags=FLAGS,
                           stdin=subprocess.DEVNULL)
        self.started = True
        self.run("createdb.exe", "-h", "127.0.0.1", "-p", self.port, "-U", "postgres", "v5")
        # Papéis e extensões que o Supabase já fornece; storage.* mínimo para o bucket.
        self.sql("CREATE ROLE anon NOLOGIN; CREATE ROLE authenticated NOLOGIN; CREATE ROLE service_role NOLOGIN BYPASSRLS;"
                 "CREATE SCHEMA extensions; CREATE EXTENSION btree_gist WITH SCHEMA extensions;"
                 "CREATE EXTENSION pgcrypto WITH SCHEMA extensions; CREATE EXTENSION \"uuid-ossp\" WITH SCHEMA extensions;"
                 "GRANT USAGE ON SCHEMA public,extensions TO service_role;"
                 "CREATE SCHEMA storage; CREATE TABLE storage.buckets(id text PRIMARY KEY,name text NOT NULL,public boolean,"
                 "file_size_limit bigint,allowed_mime_types text[]);"
                 "CREATE TABLE storage.objects(id uuid PRIMARY KEY DEFAULT gen_random_uuid(),bucket_id text,name text);")
        for path in CHAIN:
            self.runfile(path, strip_guard=True)
        if migration:
            self.runfile(migration)
            # Migrations seguintes (002_, 003_...), na ordem, como foram aplicadas em produção.
            for later in sorted(Path(migration).parent.glob("00[2-9]_*.sql")):
                if "reverter" not in later.name:
                    self.runfile(later)
        return self

    def stop(self):
        if self.started:
            subprocess.run([str(BIN / "pg_ctl.exe"), "-D", str(self.dir / "data"), "-w", "stop", "-m", "fast"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=120, creationflags=FLAGS,
                           stdin=subprocess.DEVNULL)
            self.started = False
        shutil.rmtree(self.dir, ignore_errors=True)


if __name__ == "__main__":
    pg = LocalPostgres()
    try:
        pg.start(ROOT / "sql" / "001_cadastro_publico_v5.sql")
        print(pg.sql("select count(*) from information_schema.columns where table_schema='interno' and table_name='creators';"
                     "select proname from pg_proc where proname like '%cadastro_publico%' order by 1;"))
    finally:
        pg.stop()
