// Envio da régua de renovação pela caixa 1 do Chatwoot (25/11/2026). Node 22, sem dependências.
// Modos (nunca envia sem pedir):
//   node envio.mjs seco                     -> mostra o que sairia da fila, não envia nada
//   node envio.mjs teste <telefone>         -> manda 1 mensagem de cada etapa SÓ para esse número (não mexe na fila)
//   node envio.mjs enviar                   -> manda a fila "previsto" (só com RENOVACAO_ENVIO_LIGADO=true)
// Variáveis: SUPABASE_URL, SUPABASE_SERVICE_KEY, CHATWOOT_BASE_URL, CHATWOOT_ACCOUNT_ID, CHATWOOT_API_TOKEN,
//            RENOVACAO_VIDEO (opcional: link fixo do vídeo, se o template tiver vídeo no cabeçalho).
// Régua nova (25/11): 1 mensagem entre 7 e 1 dias; template pelo tipo de contrato; {{1}} nome, {{2}} data do fim.

export const CAIXA = 1;
export const ETIQUETA = 'Renovacao de contrato';
export const TEMPLATES = {
  renovacao_primeiro_contrato: { category: 'UTILITY', parametros: 2 },
  renovacao_contrato_anual: { category: 'UTILITY', parametros: 2 },
};
export const HORARIO = { inicio: 9, fim: 20 }; // Brasília
export const ESPERA_ENTRE_ENVIOS_MS = 8000;

// Telefone do Brasil com DDI, só números (5511999998888). Devolve null se não parecer celular válido.
export function telefoneValido(valor) {
  const n = String(valor || '').replace(/\D/g, '');
  return /^55\d{10,11}$/.test(n) ? n : null;
}

export function dentroDoHorario(agora = new Date()) {
  const hora = Number(agora.toLocaleString('en-US', { timeZone: 'America/Sao_Paulo', hour: '2-digit', hour12: false })) % 24;
  return hora >= HORARIO.inicio && hora < HORARIO.fim;
}

// Mensagem no formato do Chatwoot 4.x (template do WhatsApp com vídeo no cabeçalho).
export function montarMensagem(envio, env = process.env) {
  const t = TEMPLATES[envio.template];
  if (!t || envio.etapa !== 'convite') throw new Error(`template inesperado: ${envio.etapa}/${envio.template}`);
  const valores = Array.isArray(envio.parametros) ? envio.parametros.map((v) => String(v ?? '').trim()) : [];
  if (valores.length !== t.parametros || valores.some((v) => !v)) throw new Error('parâmetros incompletos');
  const corpo = Object.fromEntries(valores.map((v, i) => [String(i + 1), v]));
  const video = env.RENOVACAO_VIDEO;
  if (video && !/^https:\/\/\S+$/.test(video)) throw new Error('RENOVACAO_VIDEO inválido');
  return {
    content: 'renovação de contrato',
    template_params: {
      name: envio.template, category: t.category, language: 'pt_BR',
      processed_params: { body: corpo, ...(video ? { header: { media_url: video, media_type: 'video' } } : {}) },
    },
  };
}

function chatwoot(env) {
  const base = String(env.CHATWOOT_BASE_URL || '').replace(/\/$/, '');
  const conta = env.CHATWOOT_ACCOUNT_ID;
  const chamar = async (metodo, caminho, corpo) => {
    const r = await fetch(`${base}/api/v1/accounts/${conta}${caminho}`, {
      method: metodo, headers: { api_access_token: env.CHATWOOT_API_TOKEN, 'Content-Type': 'application/json' },
      body: corpo ? JSON.stringify(corpo) : undefined, signal: AbortSignal.timeout(30000),
    });
    const texto = await r.text();
    if (!r.ok) throw new Error(`chatwoot ${metodo} ${caminho.split('?')[0]}: ${r.status} ${texto.slice(0, 200)}`);
    return texto ? JSON.parse(texto) : {};
  };
  return {
    // Acha o contato pelo telefone ou cria na caixa 1. Devolve { contato, sourceId }.
    async contato(telefone, nome) {
      const busca = await chamar('GET', `/contacts/search?q=%2B${telefone}&include_contact_inboxes=true`);
      let c = (busca.payload || []).find((x) => String(x.phone_number || '').replace(/\D/g, '') === telefone);
      if (!c) {
        const novo = await chamar('POST', '/contacts', { inbox_id: CAIXA, name: nome || `+${telefone}`, phone_number: `+${telefone}` });
        c = novo.payload?.contact || novo.payload || novo;
      }
      let ci = (c.contact_inboxes || []).find((x) => x.inbox?.id === CAIXA);
      if (!ci) ci = await chamar('POST', `/contacts/${c.id}/contact_inboxes`, { inbox_id: CAIXA, source_id: telefone });
      return { contato: c, sourceId: ci.source_id || telefone };
    },
    async conversa(contato, sourceId, mensagem) {
      return chamar('POST', '/conversations', { inbox_id: CAIXA, contact_id: contato.id, source_id: sourceId, message: mensagem });
    },
    async etiqueta(conversaId) {
      return chamar('POST', `/conversations/${conversaId}/labels`, { labels: [ETIQUETA] });
    },
  };
}

function banco(env) {
  const base = String(env.SUPABASE_URL || '').replace(/\/$/, '');
  const h = { apikey: env.SUPABASE_SERVICE_KEY, Authorization: `Bearer ${env.SUPABASE_SERVICE_KEY}`, 'Content-Type': 'application/json' };
  return {
    async fila() {
      const r = await fetch(`${base}/rest/v1/renovacao_fila?situacao=eq.previsto&order=previsto_em.asc&limit=200`, { headers: h });
      if (!r.ok) throw new Error(`fila: ${r.status}`);
      return r.json();
    },
    async marcar(id, situacao, extra = {}) {
      const r = await fetch(`${base}/rest/v1/rpc/marcar_envio_renovacao_v5`, {
        method: 'POST', headers: h, body: JSON.stringify({ p: { id, situacao, ...extra } }) });
      if (!r.ok) throw new Error(`marcar ${id}: ${r.status}`);
      return r.json();
    },
  };
}

export async function enviarUm(envio, telefone, env, cw = chatwoot(env)) {
  const mensagem = montarMensagem(envio, env);
  const { contato, sourceId } = await cw.contato(telefone, envio.nome);
  const conversa = await cw.conversa(contato, sourceId, mensagem);
  await cw.etiqueta(conversa.id).catch(() => {});
  return conversa.id;
}

const espera = (ms) => new Promise((r) => setTimeout(r, ms));

export async function principal(argv = process.argv.slice(2), env = process.env, saida = console.log) {
  const [modo, alvo] = argv;
  const db = banco(env);
  if (modo === 'seco') {
    const fila = await db.fila();
    for (const e of fila) {
      let resumo;
      try { resumo = JSON.stringify(montarMensagem(e, env).template_params); } catch (erro) { resumo = 'NÃO SAI: ' + erro.message; }
      saida(`${e.etapa}\t${e.tiktok}\t${telefoneValido(e.telefone) ? 'tel ok' : 'tel inválido'}\t${resumo}`);
    }
    saida(`seco: ${fila.length} na fila, nada enviado`);
    return;
  }
  if (modo === 'teste') {
    const telefone = telefoneValido(alvo);
    if (!telefone) throw new Error('teste precisa de um telefone 55DDDNUMERO');
    const exemplos = [
      { etapa: 'convite', template: 'renovacao_primeiro_contrato', parametros: ['Teste', '02/12'], nome: 'Teste renovação' },
      { etapa: 'convite', template: 'renovacao_contrato_anual', parametros: ['Teste', '02/12'], nome: 'Teste renovação' },
    ].filter((e) => !argv[2] || e.template === argv[2]);
    for (const e of exemplos) {
      const id = await enviarUm(e, telefone, env);
      saida(`teste ${e.template}: enviado para ${telefone.slice(0, 4)}…${telefone.slice(-4)} (conversa ${id})`);
      await espera(ESPERA_ENTRE_ENVIOS_MS);
    }
    return;
  }
  if (modo === 'enviar') {
    if (env.RENOVACAO_ENVIO_LIGADO !== 'true') throw new Error('envio desligado (RENOVACAO_ENVIO_LIGADO)');
    if (!dentroDoHorario()) { saida('fora do horário (9h às 20h): nada enviado'); return; }
    for (const e of await db.fila()) {
      const telefone = telefoneValido(e.telefone);
      if (!telefone) { await db.marcar(e.id, 'cancelado', { motivo: 'Telefone inválido' }); continue; }
      try {
        const conversa = await enviarUm(e, telefone, env);
        await db.marcar(e.id, 'enviado', { chatwoot_conversa: String(conversa) });
        saida(`enviado ${e.etapa} ${e.tiktok}`);
      } catch (erro) {
        await db.marcar(e.id, 'falhou', { motivo: String(erro.message).slice(0, 200) });
        saida(`falhou ${e.etapa} ${e.tiktok}: ${erro.message}`);
      }
      await espera(ESPERA_ENTRE_ENVIOS_MS);
    }
    return;
  }
  throw new Error('modo: seco | teste <telefone> [etapa] | enviar');
}

if (process.argv[1]?.endsWith('envio.mjs')) {
  principal().catch((erro) => { console.error('[renovacao]', erro.message); process.exit(1); });
}
