# Origin and confirmed Chatwoot labels

Prepared against the read-only definition of `public.registrar_contato_v5(jsonb)` retrieved on 2026-11-12. **Not applied remotely.** The saved `registrar_contato_v5_before.sql` is the exact baseline; compare the live function again before applying to avoid overwriting a concurrent change. Apply through the supported migration mechanism, in one transaction, before enabling Python that emits the new optional fields/RPC.

Changes:
- Adds optional `qualificacao.origem_canal_declarado`, restricted to instagram, tiktok, facebook, youtube, google, whatsapp, podcast (or null).
- Preserves old source values. Adds `ad_prefilled_message` provenance only with `value=anuncio`; it is not relabeled as an explicit personal declaration.
- Creates `interno.chatwoot_etiquetas_historico`, an append-only readback history separate from internal phase/events. No existing data is rewritten or backfilled. Foreign keys cascade only when the existing creator/attendance is deleted, so the existing 90-day closed/unconverted attendance cleanup is not blocked. This migration does not invoke cleanup or delete rows.
- `registrar_etiquetas_chatwoot_v5` is invoker/service-role-only, with identity binding to the existing attendance and stale-revision rejection. The caller sends only labels confirmed by Chatwoot GET, not desired labels before mutation.
- Replays use attendance + revision + signature; a fresh read timestamp on replay does not add history. Existing exact receipts can replay after newer revisions without changing data.
- RLS is enabled. No access or execute is granted to public, anon or authenticated. No public view is created.

RPC input keys: `instancia`, `account_id`, `contact_id`, `conversation_id`, `creator_id`, `atendimento_id`, `revision`, `labels`, `observed_at`, `signature`. Signature is SHA-256 of sorted unique labels serialized as a UTF-8 JSON array with default Python spacing, `ensure_ascii=False`. Label enum: conhecer, qualificação, validação, convite, cadastro, encerrado. Exactly one stage, optionally encerrado. Timestamps are UTC ISO8601. Receipt: status recorded/replayed, atendimento_id, revision, labels, signature.

## Querying current observed labels

Use the new relation only for actual confirmed owned labels. Other teams' labels are deliberately excluded. Absence of a row means unobserved, not an empty stage.

```sql
select distinct on (instancia, account_id, conversation_id)
 instancia, account_id, conversation_id, contact_id, creator_id,
 atendimento_id, revisao, etiquetas, observado_em, registrado_em
from interno.chatwoot_etiquetas_historico
order by instancia, account_id, conversation_id, observado_em desc, id desc;
```

For a historical reporting cutoff, filter `observado_em` AND `registrado_em` before the cutoff, then use the same ordering. Do not equate an internal phase (`form`) with a Chatwoot label or count retrospective observations as completed actions.

## Local tests

`ops/tests/test_origin_labels.mjs` compiles and runs the migration on an isolated PGlite/Postgres instance against a metadata-only schema fixture. No user records or external writes are used. The fixture deliberately contains no triggers or real production data, so it does not replace a staged integration check of production triggers.

Install the official `@electric-sql/pglite` package in a scratch directory, then set `PGLITE_MODULE=file:///path/to/node_modules/@electric-sql/pglite/dist/index.js` and run the script with Node. Verified 24 tests: write/replay/history, stale/identity/invalid label rejection, signature and Unicode sorting, time bounds, privileges/RLS, and both allowed and forbidden origin contracts. The full existing contact RPC is executed in the origin tests.

Rollback: disable Python's new optional field/RPC emission first. Restore the original contact function only after rechecking for concurrent changes. Keep the append-only table rather than dropping collected observations; no destructive rollback is included.

### Transactional baseline guard
The migration is enclosed in BEGIN/COMMIT. Before any DDL it compares
`md5(replace(pg_get_functiondef('public.registrar_contato_v5(jsonb)'::regprocedure), E'\r\n', E'\n'))`
to `87fa6a359f17bc04880cc81fe031065d`. Only CRLF is normalized; no arbitrary
whitespace is stripped. A mismatch raises `registrar_contato_v5_baseline_changed`
and aborts without changing either function or creating the history table.
The saved before-definition is unchanged. Tests first install that baseline,
simulate a concurrent function-body edit, verify rejection and no schema changes,
then restore the fixture baseline and test the successful migration.
Apply with a migration runner that stops on errors; do not remove this guard to
force an outdated patch through. This guard detects prior edits; deployment must
still be serialized with other schema migrations.
