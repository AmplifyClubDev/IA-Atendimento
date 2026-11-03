# AmplifyOS-v5

Reestruturação da OS desenvolvida internamente para implementação e criação de novos projetos.

## Estrutura

| Pasta | O que é | Onde roda |
| --- | --- | --- |
| `bia/` | Bia, a agente de atendimento no WhatsApp (V5) | Railway › "Atendimento V5 - Ensaio" (pacote selado nas variáveis) |
| `bia/tools/` | Scripts de empacotamento e listagem das releases | local |
| `cadastro/` | Formulário público, conferência do agenciamento e entrega do acesso ao Circle | Railway › "Cadastro" |
| `docs/` | Estado do atendimento e notas de cada release da Bia | — |

## Branches

- `main` é o que está em produção.
- `release/bia-NN`: uma branch por release da Bia, mesclada na `main` em ordem (tag `bia-rNN`).
- `feat/cadastro-*`: uma branch por mudança do Cadastro, mesclada na `main` com `--no-ff`.

Novas mudanças: criar uma branch a partir da `main`, abrir um pull request e mesclar depois de testar.

## Testes

```bash
cd cadastro && uv run --with pytest --with "psycopg[binary]" --with-requirements app/requirements.txt python -m pytest -q tests
```

Os testes sobem um PostgreSQL 17 descartável em 127.0.0.1 e aplicam o esquema de `cadastro/sql/esquema-base/` mais as migrations de `cadastro/sql/`. O Postgres é procurado em `CADASTRO_TEST_PG_BIN` (pasta `bin` com `initdb`, `pg_ctl` e `psql`) ou no `PATH`. No GitHub Actions eles rodam em todo push e pull request que mexe em `cadastro/` (`.github/workflows/cadastro-testes.yml`).
