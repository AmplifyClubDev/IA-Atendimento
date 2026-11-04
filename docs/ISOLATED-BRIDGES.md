# Isolated bridge configuration (local proposal, not deployed)

Production behavior and role-specific bridge hostname allowlists remain unchanged when
both APP_ENV and RAILWAY_ENVIRONMENT_NAME are absent or `production`. Any explicit
nonproduction marker wins, including empty/unknown values; APP_ENV=production cannot
override a Railway staging environment. Contradictory markers therefore never enable
production targets. Set APP_ENV=staging explicitly on every new isolated service.

Nonproduction starts with no usable bridge endpoints. Each role needs:

- V5_TIKTOK_NONPRODUCTION_ENABLED=true (exact, lower-case value)
- V5_TIKTOK_<ROLE>_URL=https://<isolated-host>/bridge
- V5_TIKTOK_<ROLE>_ALLOWED_HOST=<same-isolated-host> (one exact hostname, no wildcard)
- A new environment-specific token, never copied from production.

Roles: AGENCY, PRECHECK, INVITES, GMV, LOOKUP. Only HTTPS, port 443/default,
and the /bridge path are accepted in nonproduction. Production bridge hosts are
rejected even if explicitly entered in the nonproduction allowlist. Production
keeps its original special internal HTTP lookup rule; nonproduction lookup must
use the HTTPS /bridge contract and may need a compatible proxy/service.

Cadastro's panel uses AGENCY, PRECHECK and INVITES URLs, stripping /bridge to
obtain the console origin. Read-token names are unchanged: V5_TIKTOK_AGENCY_TOKEN,
PONTE_PREVALIDACAO_TOKEN, PONTE_CONVITES_TOKEN. Bia uses its existing V5_TIKTOK_*_TOKEN
names. The URLs/hostnames must be configured consistently in both services.

Nonproduction Cadastro console login, redirects containing console access tokens,
and automatic activation/recovery are disabled unless a second exact flag is set:
PONTES_NONPRODUCTION_ACTIVATION_ENABLED=true. Invalid/missing endpoints are excluded
from the panel and watcher list. Both bridge HTTP clients reject redirects.

## Validation

Offline focused suite: 38 passed, including the existing ten bridge-operation tests.
Cadastro retains its historical production endpoint when an optional URL variable is
empty. Nonproduction never falls back. Bia retains its existing empty-URL rejection.
An empty panel reports disabled/unconfigured (503), never healthy.

Run from the repository root with pytest/flask installed:

    python -m pytest cadastro/tests/test_operacao_pontes.py cadastro/tests/test_bridge_isolation.py -q

All changed Python files compile. Test transports are mocked; no bridge was called.
The helpers are deliberately duplicated because Bia and Cadastro have independent
Docker contexts. A test checks they remain byte-identical.

## Limits before any deployment

This is a targeted bridge patch, not a complete staging isolation implementation.
The local workspace contains a source subset fetched from GitHub main, not a full
clone. Check the patch against the intended immutable commit before applying it.
No complete application suite, database tests, container build, or live smoke test
was run. Bia's artifact manifest may need regeneration under its normal release
process. Do not treat the patch as a deployable replacement repository.

Separately isolate Supabase project/schema allowlists, Chatwoot account/inbox,
Circle, SMTP/Gmail, public form URLs, AI services, workers and alert destinations.
Cadastro's atendimento watcher still has its production readiness URL. Existing
Bia startup restrictions intentionally remain; this patch does not relax business,
recipient or database guards. Confirm all externally effective workers are off
before an isolated environment starts, and provide new credentials only through
authorized secure setup. Do not clone production credentials or browser profiles.
