// Detalhes de uma parceria do Partner Center, só quando pedidos (?detalhes=1 em /relations).
// Achata o registro do TikTok em "chave.subchave": valor, só com valores simples (texto, número, sim/não).
// Fica de fora: imagens e links de mídia, textos longos e listas grandes. Serve para o espelho no banco
// (nível, GMV, seguidores, categorias...) sem mudar a resposta padrão da ponte.
const SKIP = /avatar|icon|cover|image|img|thumb|signature|token|cookie/i;
const MAX_KEYS = 200;
const MAX_TEXT = 300;
const MAX_DEPTH = 4;

export function relationDetails(relation) {
  const out = {};
  const walk = (value, prefix, depth) => {
    if (Object.keys(out).length >= MAX_KEYS || value === null || value === undefined) return;
    if (Array.isArray(value)) {
      const simple = value.filter((v) => ['string', 'number', 'boolean'].includes(typeof v));
      if (simple.length === value.length && simple.length <= 20) {
        out[prefix] = simple.map((v) => (typeof v === 'string' ? v.slice(0, MAX_TEXT) : v));
      } else if (depth < MAX_DEPTH) {
        value.slice(0, 10).forEach((v, i) => walk(v, `${prefix}.${i}`, depth + 1));
      }
      return;
    }
    if (typeof value === 'object') {
      if (depth >= MAX_DEPTH) return;
      for (const [k, v] of Object.entries(value)) {
        if (SKIP.test(k)) continue;
        walk(v, prefix ? `${prefix}.${k}` : k, depth + 1);
      }
      return;
    }
    if (typeof value === 'string') {
      if (value.length > MAX_TEXT || /^https?:\/\//i.test(value)) return;
      out[prefix] = value;
    } else if (typeof value === 'number' || typeof value === 'boolean') {
      out[prefix] = value;
    }
  };
  walk(relation, '', 0);
  return out;
}
