"""Estado temporário das sessões do formulário (SQLite local do serviço).

Guarda só o necessário para conduzir o preenchimento: e-mail confirmado, @ conferido,
anexos enviados, leitura do print e o recibo do envio. Nada disto é dado de negócio:
o cadastro em si vai para o banco AmplifyOS-v5. O rascunho das respostas fica no
navegador da pessoa (IndexedDB do formulário original).
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path

SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS sessions (
  form_id TEXT PRIMARY KEY, created_at REAL NOT NULL, client_hash TEXT,
  agency_handle TEXT, agency_json TEXT, agency_at REAL,
  otp_email_hash TEXT, otp_code_hash TEXT, otp_expires_at REAL, otp_attempts INTEGER NOT NULL DEFAULT 0,
  otp_sent_json TEXT NOT NULL DEFAULT '[]', otp_status TEXT,
  email_hash TEXT, email_sha256 TEXT, email_verified_at TEXT,
  initial_hash TEXT, submitted_json TEXT);
CREATE TABLE IF NOT EXISTS attachments (
  form_id TEXT NOT NULL, field TEXT NOT NULL, object_key TEXT NOT NULL, created_at REAL NOT NULL,
  PRIMARY KEY (form_id, object_key));
CREATE TABLE IF NOT EXISTS gmv_reads (object_key TEXT PRIMARY KEY, result_json TEXT NOT NULL, created_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS hits (bucket TEXT NOT NULL, at REAL NOT NULL);
CREATE INDEX IF NOT EXISTS hits_bucket ON hits(bucket, at);
"""
FIELDS = {"agency_handle", "agency_json", "agency_at", "otp_email_hash", "otp_code_hash", "otp_expires_at",
          "otp_attempts", "otp_sent_json", "otp_status", "email_hash", "email_sha256", "email_verified_at",
          "initial_hash", "submitted_json"}


class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        with self.db() as db:
            db.executescript(SCHEMA)

    @contextmanager
    def db(self):
        conn = sqlite3.connect(str(self.path), timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def open_session(self, form_id, client_hash):
        with self.db() as db:
            db.execute("INSERT OR IGNORE INTO sessions(form_id,created_at,client_hash) VALUES(?,?,?)",
                       (form_id, time.time(), client_hash))

    def session(self, form_id):
        with self.db() as db:
            row = db.execute("SELECT * FROM sessions WHERE form_id=?", (form_id,)).fetchone()
        return dict(row) if row else None

    def update(self, form_id, **values):
        if not values or set(values) - FIELDS:
            raise ValueError("campo_de_sessao_invalido")
        with self.db() as db:
            db.execute("UPDATE sessions SET " + ",".join(k + "=?" for k in values) + " WHERE form_id=?",
                       (*values.values(), form_id))

    def try_otp_attempt(self, form_id, maximum):
        """Conta a tentativa de forma atômica: pedidos simultâneos não passam do limite."""
        with self._lock, self.db() as db:
            return db.execute("UPDATE sessions SET otp_attempts=otp_attempts+1 WHERE form_id=? AND otp_attempts<?",
                              (form_id, maximum)).rowcount == 1

    def claim_email_code(self, form_id, email_hash, code_hash, *, now, ttl, wait):
        """Reserva antes do SMTP, inclusive entre processos e endereços diferentes."""
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = dict(db.execute("SELECT * FROM sessions WHERE form_id=?", (form_id,)).fetchone())
            sent = [at for at in json.loads(row['otp_sent_json']) if now - at < 3600]
            if row['submitted_json']:
                return 'submitted'
            if row['email_hash'] == email_hash and row['email_verified_at']:
                return 'verified'
            if sent and now - sent[-1] < wait:
                return 'waiting'
            if row['otp_status'] == 'enviando' and (row['otp_expires_at'] or 0) > now:
                return 'waiting'
            if len(sent) >= 5:
                return 'limited'
            attempts = row['otp_attempts'] if row['otp_email_hash'] == email_hash else 0
            db.execute("""UPDATE sessions SET otp_email_hash=?,otp_code_hash=?,otp_expires_at=?,
                          otp_attempts=?,otp_sent_json=?,otp_status='enviando' WHERE form_id=?""",
                       (email_hash, code_hash, now + ttl, attempts, json.dumps(sent + [now]), form_id))
            return 'claimed'

    def finish_email_code(self, form_id, code_hash, status):
        if status not in {'enviado', 'devolvido', 'incerto'}:
            status = 'incerto'
        with self.db() as db:
            db.execute("UPDATE sessions SET otp_status=? WHERE form_id=? AND otp_code_hash=? AND otp_status='enviando'",
                       (status, form_id, code_hash))

    def confirm_email_code(self, form_id, email_hash, code_hash, email_sha256, verified_at, *, now, maximum):
        """Validação, limite e confirmação usam a mesma geração em uma transação."""
        import secrets
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row = dict(db.execute('SELECT * FROM sessions WHERE form_id=?', (form_id,)).fetchone())
            if row['email_hash'] == email_hash and row['email_verified_at']:
                return 'confirmado'
            if row['otp_email_hash'] != email_hash or (row['otp_expires_at'] or 0) <= now:
                return 'expirado'
            if row['otp_status'] not in {'enviado', 'incerto'}:
                return row['otp_status'] or 'expirado'
            if row['otp_attempts'] >= maximum:
                return 'tentativas_esgotadas'
            db.execute('UPDATE sessions SET otp_attempts=otp_attempts+1 WHERE form_id=?', (form_id,))
            if not secrets.compare_digest(row['otp_code_hash'] or '', code_hash):
                return 'codigo_incorreto'
            db.execute("""UPDATE sessions SET email_hash=?,email_sha256=?,email_verified_at=?,
                          otp_code_hash=NULL,otp_status='confirmado' WHERE form_id=?""",
                       (email_hash, email_sha256, verified_at, form_id))
            return 'confirmado'

    def add_attachment(self, form_id, field, key):
        with self.db() as db:
            count = db.execute("SELECT count(*) FROM attachments WHERE form_id=? AND field=?", (form_id, field)).fetchone()[0]
            if count >= 10:
                return False
            db.execute("INSERT OR IGNORE INTO attachments VALUES(?,?,?,?)", (form_id, field, key, time.time()))
        return True

    def has_attachment(self, form_id, field, key):
        with self.db() as db:
            return db.execute("SELECT 1 FROM attachments WHERE form_id=? AND field=? AND object_key=?",
                              (form_id, field, key)).fetchone() is not None

    def save_gmv_read(self, key, result):
        with self.db() as db:
            db.execute("INSERT OR REPLACE INTO gmv_reads VALUES(?,?,?)", (key, json.dumps(result), time.time()))

    def gmv_read(self, key):
        with self.db() as db:
            row = db.execute("SELECT result_json FROM gmv_reads WHERE object_key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def allow(self, bucket, limit, window):
        """Limite deslizante simples; devolve False quando estourou."""
        now = time.time()
        with self._lock, self.db() as db:
            db.execute("DELETE FROM hits WHERE at<?", (now - 86400,))
            used = db.execute("SELECT count(*) FROM hits WHERE bucket=? AND at>=?", (bucket, now - window)).fetchone()[0]
            if used >= limit:
                return False
            db.execute("INSERT INTO hits VALUES(?,?)", (bucket, now))
        return True
