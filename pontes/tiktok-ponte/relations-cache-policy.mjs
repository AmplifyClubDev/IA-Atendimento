export function deveIgnorarCacheRelacoes({ priority, fresh } = {}) {
  const prioridade = String(priority || '').trim().toLowerCase();
  return String(fresh || '') === '1'
    || prioridade === 'accept'
    || prioridade.startsWith('invite-confirm');
}

export function invalidarCacheRelacoesAposConvite(cache) {
  cache.clear();
}

export function relacoesCompletas(result) {
  if (result?.ok !== true || !Array.isArray(result.items)
      || !Array.isArray(result.pages) || result.pages.length === 0
      || result.pages.some((page) => page?.ok !== true)) return false;
  const last = result.pages.at(-1);
  // Partner totals can drift while pages are read. Its explicit pagination
  // boundary takes precedence over that aggregate, in either direction.
  if (typeof last.hasMore === 'boolean') return last.hasMore === false;
  const total = result.totalNum;
  return Number.isInteger(total) && total >= 0 && result.items.length >= total;
}
