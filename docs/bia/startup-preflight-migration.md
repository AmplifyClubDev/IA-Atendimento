# Source-based stage startup gate (local review candidate)

Baseline: AmplifyClubDev/AmplifyOS-v5 PR #3, head b505e42. This patch has not
been published or deployed and does not read production services or secrets.

## Evidence and scope

- `bia/tests/test_connection_host.py` referenced absent
  `ops/connectionfix_launcher.py`; no replacement launcher exists in the tree.
- `docs/bia/releases/release-40.md` records the missing-file failure as existing
  since release 35. It describes production as a sealed launcher and zip delivered
  through `V5_RELEASE_LAUNCHER_B64` and release-part variables.
- `bia/Dockerfile` instead invokes `bootstrap:create_app()` directly. The checked-in
  bootstrap did not invoke the stage preflight, and Docker did not copy it.
- The historical sealed launcher was not available for source comparison. This
  patch does not reconstruct it, decode production secrets, or assert equivalence.

## Explicit new contract

`bootstrap.create_app()` calls `startup_preflight.verify_stage_readiness(settings)`
before constructing the server, SQLite repository, relinking forms or starting
workers. The check uses the same supplied settings that the application will use.

- Any nonproduction marker wins, following the existing offline policy. No
  preflight provider import, client construction or external request occurs.
- With stage labels disabled, no stage check occurs and normal bootstrap proceeds.
- With stage labels enabled in production, reuse `ops.stage_preflight.run_preflight`
  with fixed approved host/account/inbox/conversation/contact, `require_labels=True`
  and `setup=False`. The existing preflight validates configuration before HTTP,
  rejects redirects, disables proxies and uses bounded HTTPS responses.
- The successful path performs four GETs: inbox, canary conversation, label
  definitions and automation rules. Startup never creates labels and never accepts
  a rules override. Inactivity-close labels remain required when enabled.
- Only literal boolean success, read-only mode and integer zero POST attempts
  permit startup. An invalid result or exception aborts startup with a fixed
  diagnostic, without exposing credentials, provider data or exception chains.
- The runtime extension records only passed/disabled and fixed reason codes.
  This is a startup check, not continuing validation or a replacement for each
  request's runtime recipient and offline fences.

The old missing-file test is replaced with tests of this actual startup contract,
including exact scope, failure ordering, normal startup after success, offline
no-provider behavior, packaging and a four-GET fake-client fixture.

## Production migration risks and prerequisites

This is a deliberate fail-closed startup change, not proof of unchanged production
behavior. Do not deploy solely because these local tests pass.

1. Verify the actual running launcher, release identity, source hashes, start
   command and rollback artifact through an authorized process. Source Docker and
   sealed-launcher deployments are distinct paths. A deployment still using the
   sealed launcher will not necessarily execute this gate or include its modules.
2. Review all historical launcher responsibilities (integrity verification,
   extraction, configuration, other readiness checks). This patch implements only
   the stage check that the stale test specifies. It does not replace context
   preflight or any unknown historical launcher responsibilities.
3. Verify the historical canary conversation 26097/contact 3 still exists in
   account 1/inbox 3 and matches V5_TEST_PHONE. Current runtime supports multiple
   pilot phones; the inherited preflight remains pinned to this one canary. If it
   no longer applies, define and approve a replacement contract rather than
   removing fences or auto-discovering an arbitrary contact.
4. Read and review the current label and automation-rule inventory. Missing exact
   titles or risky active automation rules block startup. This patch deliberately
   has no automatic setup or new rules-approval configuration. Preflight's existing
   read-only label semantics are preserved; it does not newly demand matching
   colors/descriptions for already exact title names.
5. Review startup timing: four sequential requests have 15-second timeouts each.
   An unavailable Chatwoot service can prevent worker boot/restart; tune deployment
   health/startup budgets through the normal approved rollout, not by failing open.
6. Build the complete image and run a no-network staging smoke test. Docker build
   and live production readiness were not run here. Nonproduction readiness remains
   intentionally disabled under the existing offline policy, not production proof.
7. Publish/deploy only with authorization and a preserved rollback. No production
   variables, credentials, messaging flows, database schema or pilot list were
   changed by this local candidate.

Direct `server.create_app()` consumers bypass bootstrap by design and are not
covered by this startup gate. The Docker entrypoint continues using bootstrap.
