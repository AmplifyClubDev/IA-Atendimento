# Source build checks and historical release-manifest audit

Reviewed base: PR #3 commit ac7b1c2d2ead6ab35c352babc0eb3b90b203d56b.
This is a local verification report, not an image-build receipt or deployment approval.

## Docker availability and reproduced source-layout failure

Docker, Podman and Buildah are not available in this workspace. No engine or other
software was installed for this check. Gunicorn is also unavailable locally.
Therefore no image was pulled/built, no requirements installation was verified,
and no container/Gunicorn startup was executed.

The Bia Dockerfile's COPY instructions were reproduced in a temporary directory,
without the original source checkout on the child interpreter's import path.
With APP_ENV=staging, network and thread starts blocked, the prior layout failed:
`ModuleNotFoundError: No module named 'retomada'` during bootstrap.create_app().

The source also imports conversao and reconferencia. All three files exist in the
repository but were omitted by the explicit COPY inventory. The proposed fix adds
only these existing source modules to the image. A regression test recreates that
COPY layout in a temporary directory and starts the actual offline bootstrap:
healthz=200, ready=503, preflight disabled, with no network or worker threads.

The test uses locally available Python/dependencies, not the pinned image package
installation. It does not prove Docker layer behavior, reproducible dependency
resolution, OS libraries, port binding, Gunicorn behavior or production preflight.
Run an actual clean image build and container smoke test in an authorized engine
before deployment. Keep APP_ENV=staging and no real credentials for that smoke test.

## Historical manifest is not the current source contract

At the reviewed commit, bia/MANIFEST.json describes the historical sealed release
atendimento-v5-release-20261103-48, based on release47, with 36 source entries.
It is not generated for this PR. The Dockerfile neither copies nor verifies it.

All 18 PR-modified source files listed in that historical manifest mismatch its
SHA-256 and byte lengths. New bridge_config.py, offline_policy.py and
startup_preflight.py are absent from its inventory. This finding does not assert
that every unchanged manifest entry has been audited.

The existing tools/empacotar_release48.py depends on tools/src and the historical
release47 sealed launcher and its SOURCES list, then builds/verifies archive hashes
through that launcher. Those required historical inputs are not available here.
The packager was not executed. Replacing only manifest hashes would not repair the
sealed archive/launcher integrity chain and would misstate provenance.

The historical MANIFEST.json is deliberately unchanged by this patch.

## Safe path forward, still pending

1. Decide whether the release artifact will be source Docker or a separately
   versioned sealed package. Do not treat those as equivalent deployment paths.
2. For source Docker, define a separate, explicitly named snapshot manifest and
   verifier with a reviewed input inventory, exact commit/patch provenance, byte
   lengths and hashes. Include the added modules, exclude credentials, state,
   generated caches and untracked files, and verify the actual image contents.
   Do not generate it from a partial/materialized tree as if it were a sealed release.
3. For sealed deployment, obtain the authentic launcher/artifact and review its
   provenance and rollback identity. A new package needs a new release identity;
   do not overwrite historical release48 metadata with current source hashes.
4. Build and test the complete artifact with the intended pinned dependencies,
   startup command and budgets. The stage preflight's historical canary and four
   sequential 15-second requests remain separate deployment risks documented in
   startup-preflight-migration.md.

No manifest was regenerated, no secrets or production archive variables were read,
and no deploy, merge or production request was performed.
