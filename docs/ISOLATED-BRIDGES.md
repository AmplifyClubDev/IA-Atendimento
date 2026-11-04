# Offline nonproduction preparation (draft review, not deployed)

## Current safety boundary: offline only

This revision blocks live external integrations in any explicitly nonproduction
process or supplied configuration. There is **no flag to enable them**. The bridge
URL/allowlist and activation flags described below are configuration groundwork
only; they do not override the offline policy.

Cadastro returns a disabled liveness response at /health (HTTP 200, live=true),
and HTTP 503 at other routes without constructing live dependencies or starting
workers. The separate public blueprint, pilot proxy, direct delivery/retry methods,
watchers, bridge/console clients, Supabase/storage, Circle, both email stacks
(including OAuth token refresh), Chatwoot and image-reading adapters are guarded.
Bia blocks bootstrap relinking/probes/recovery and worker entrypoints, Gateway,
SMTP, Chatwoot and direct WhatsApp, AI and bridge adapters. Production behavior and
Bia's Supabase project pin remain unchanged.

Synthetic dependencies do not authorize real traffic. Guards run before injected
transports too. Any explicit nonproduction marker in the process wins over a
production-looking supplied configuration. No live provider test was performed.

This is application-level defense, not a network sandbox or proof of complete
isolation. No live staging deployment, build validation or production change is
part of this PR. Future integration enablement needs separate target/account and
recipient policies, independent review and explicit authorization.

## Bridge target configuration groundwork

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
from the panel and watcher list. Both bridge HTTP clients reject redirects. The offline guard still blocks all traffic regardless of these settings.

## Validation

Current local Cadastro focused suite: 56 passed, including ten existing bridge tests,
28 bridge target tests and 18 offline safety cases. Bia: 13 new synthetic cases
passed, including actual Flask startup and readiness in real/simulated modes.

Broad Bia unittest discovery, with exact schema files and sockets blocked:
- Prior PR head: 842 tests, 831 passes, 1 failure, 1 error, 9 skips.
- This patch: 855 tests, 844 passes, the same 1 failure, 1 error and 9 skips.
- No new failure/error IDs. This is not an all-green suite.

Remaining baseline issues:
- test_webhook_enqueues_without_provider_then_worker_chains_real_proof_and_form:
  actual operation is cancelled instead of completed.
- test_actual_launcher_passes_only_approved_host_and_readonly_stage_arguments:
  connectionfix_launcher.py is absent from the prior commit.

The prior PR commit passed the GitHub Cadastro suite (71 tests with PostgreSQL 17).
That earlier CI result is not validation of this follow-up commit.
Cadastro retains its historical production endpoint when an optional URL variable is
empty. Nonproduction never falls back. Bia retains its existing empty-URL rejection.
An empty panel reports disabled/unconfigured (503), never healthy.

Run from the repository root with pytest/flask installed:

    python -m pytest cadastro/tests/test_operacao_pontes.py cadastro/tests/test_bridge_isolation.py cadastro/tests/test_offline_staging.py -q
    python -m pytest bia/tests/test_offline_effects.py -q

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
recipient or database guards. Verify the offline guards against the complete build before any isolated environment
starts, and provide new credentials only through
authorized secure setup. Do not clone production credentials or browser profiles.
