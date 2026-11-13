# Shared Bia engine release candidate

Baseline: `d9f9d3196671fbdee8bc80348fdf3020354c52a0` on `review/bia-isolated-knowledge-20261106`.

The previous release had promoted opening/menu/qualification, not the tested answer engine. This candidate uses the same answer pipeline for demonstration and real turns, with an explicit Amplify profile. Operational actions remain under backend consent, receipts, idempotency, eligibility, and human-pause controls.

## Verification

- 798 offline tests passed locally (independent timeout-budget re-review pending) after additional adversarial review identified and corrected clarification consumption, generic FAQ/status confusion, unproved specialist transfers, and commercial policy/context mismatch.
- Source manifest: 52 entries, checked against file contents.
- Approved commercial snapshot is pinned by factual digest, knowledge version, profile version, and operational policy fingerprint. Altered content retaining a version string fails closed.
- No live-model smoke result is claimed. No synthetic messages were sent to leads as part of this release QA.

## Release gates

1. Complete final independent review.
2. Recheck branch HEAD. Publish with expected-SHA lease, never force over concurrent changes.
3. Stage source for Bia service only, preserving unrelated staged changes by stopping if any exist.
4. Deploy with new flag disabled. Verify build, health, dependencies, source revision.
5. Enable `V5_SAME_ENGINE_ENABLED=true` only after those gates. Profile remains `amplify-v1`.
6. Verify readiness and natural incoming turns read-only. Do not reset cycles or replay messages.

Rollback: set the new flag false; existing state, receipts, deduplication, forms, bridges, and history must remain. Prior source SHA is recorded above. Do not delete backend integration modules or data to remove the old answer route.

This document records the candidate and procedure, not a claim that deployment has completed.

Authorized real-provider smoke: benefits and costs were accepted by the shared pipeline; live requirement question failed closed on provider timeout. Remaining questions were not completed due to an execution approval-review interruption. This is partial evidence, not a full smoke pass. No lead data or messaging endpoints were used.

Timeout-budget adjustment: generation capped at min(18 seconds, remaining turn time minus 6 seconds reserved for verification); total turn deadline remains 28 seconds. A post-adjustment real-provider smoke was blocked by access review before a response; it is not validated.
