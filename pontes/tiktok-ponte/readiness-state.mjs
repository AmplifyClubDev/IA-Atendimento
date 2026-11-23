export function evaluateReadiness({
  contextReady,
  contextStatus,
  preparing,
  busy,
  refreshing,
  probe,
  now = Date.now(),
  successTtlMs,
  failureTtlMs,
  graceMs,
}) {
  const checkedAt = Number(probe?.em);
  const hasProbe = Number.isFinite(checkedAt) && checkedAt > 0;
  const ageMs = hasProbe ? Math.max(0, now - checkedAt) : null;
  const probeTtlMs = probe?.ok ? successTtlMs : failureTtlMs;
  const fresh = ageMs !== null && ageMs <= probeTtlMs;
  const withinGrace = Boolean(probe?.ok && ageMs !== null && ageMs <= graceMs);
  const shouldRefresh = Boolean(
    contextReady
    && !preparing
    && !busy
    && !refreshing
    && (!hasProbe || !fresh),
  );
  const ready = Boolean(contextReady && !preparing && withinGrace);
  let status = 'degraded';
  if (ready) status = 'ready';
  else if (!contextReady) status = contextStatus || 'cold';
  else if (!hasProbe) status = 'preparing';

  return {
    ready,
    status,
    ageMs,
    fresh,
    withinGrace,
    shouldRefresh,
  };
}
