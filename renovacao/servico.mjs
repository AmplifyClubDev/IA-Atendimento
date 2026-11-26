// Serviço "Renovação de contrato" (26/11/2026). Node 22, sem dependências. Roda no Railway, separado da Bia.
//  - De hora em hora: prepara a fila no banco e, se o envio estiver ligado, envia (só das 9h às 20h).
//  - Webhook do Chatwoot: responde aos botões nas conversas da caixa 3 com a etiqueta "Renovacao de contrato".
// Variáveis: SUPABASE_URL, SUPABASE_SERVICE_KEY, CHATWOOT_BASE_URL, CHATWOOT_ACCOUNT_ID, CHATWOOT_API_TOKEN,
//            RENOVACAO_WEBHOOK_SEGREDO (32+ caracteres, vai no caminho do webhook),
//            RENOVACAO_ENVIO_LIGADO=true para enviar a fila, RENOVACAO_RESPOSTAS_LIGADAS=true para responder aos botões.
import http from 'node:http';
import crypto from 'node:crypto';
import { CAIXA, banco, chatwoot, enviarFila } from './envio.mjs';
import { lerEvento, tratar } from './respostas.mjs';
import { carregarCartoes, dadosDoAgenciado, historicoDe, montarInstrucoes, perguntarIA } from './ia.mjs';

const HORA_MS = 3600000;
const PRIMEIRA_RODADA_MS = 60000;
const estado = { iniciado: new Date().toISOString(), rodadas: 0, ultimaRodada: null, respostas: 0, ultimaResposta: null, erros: 0 };

export function segredoConfere(recebido, esperado) {
  const a = Buffer.from(String(recebido || '')), b = Buffer.from(String(esperado || ''));
  return b.length >= 32 && a.length === b.length && crypto.timingSafeEqual(a, b);
}

function log(tipo, dados) {
  console.log(`[renovacao] ${tipo} ${JSON.stringify(dados)}`);
}

export function criarBanco(env) {
  const db = banco(env);
  const base = String(env.SUPABASE_URL || '').replace(/\/$/, '');
  const h = { apikey: env.SUPABASE_SERVICE_KEY, Authorization: `Bearer ${env.SUPABASE_SERVICE_KEY}` };
  db.ultimaResposta = async (conversa) => {
    const r = await fetch(`${base}/rest/v1/renovacao_respostas?chatwoot_conversa=eq.${conversa}&select=resposta&order=recebido_em.desc&limit=1`, { headers: h });
    if (!r.ok) throw new Error(`ultima resposta: ${r.status}`);
    return (await r.json())[0]?.resposta || null;
  };
  db.ler = async (tela, consulta) => {
    const r = await fetch(`${base}/rest/v1/${tela}?${consulta}`, { headers: h });
    if (!r.ok) throw new Error(`${tela}: ${r.status}`);
    return r.json();
  };
  return db;
}

export async function rodada(env, db, cw) {
  const resumo = { em: new Date().toISOString() };
  try {
    resumo.fila = await db.rpc('preparar_fila_renovacao_v5');
    resumo.envio = env.RENOVACAO_ENVIO_LIGADO === 'true' ? await enviarFila(env, (t) => log('envio', t), db, cw) : 'desligado';
  } catch (erro) {
    resumo.erro = String(erro.message).slice(0, 200);
    estado.erros += 1;
  }
  estado.rodadas += 1;
  estado.ultimaRodada = resumo;
  log('rodada', resumo);
  return resumo;
}

// A Bia dos agenciados: só existe com OPENAI_API_KEY (sem ela, texto livre vira nota para o time).
export function criarIA(env, db, cw) {
  if (!env.OPENAI_API_KEY) return null;
  return {
    async responder(msg, envio) {
      const [cartoes, ag, mensagens] = await Promise.all([
        carregarCartoes(db), dadosDoAgenciado(db, { relationId: envio?.relation_id, telefone: msg.telefone }, env), cw.mensagens(msg.conversa)]);
      return perguntarIA({ instrucoes: montarInstrucoes(cartoes, ag), historico: historicoDe(mensagens), env });
    },
  };
}

export function criarServidor(env, db = criarBanco(env), cw = chatwoot(env), ia = criarIA(env, db, cw)) {
  const fila = [];
  let ocupado = false;
  // Uma mensagem por vez, na ordem em que chegaram (a mesma pessoa pode tocar 2 botões em seguida).
  const processar = async () => {
    if (ocupado) return;
    ocupado = true;
    while (fila.length) {
      const msg = fila.shift();
      try {
        const r = await tratar(msg, { db, cw, ia });
        estado.respostas += 1;
        estado.ultimaResposta = { em: new Date().toISOString(), ...r };
        log('resposta', { conversa: msg.conversa, ...r });
      } catch (erro) {
        estado.erros += 1;
        log('erro_resposta', { conversa: msg.conversa, erro: String(erro.message).slice(0, 200) });
      }
    }
    ocupado = false;
  };
  return http.createServer((req, res) => {
    const url = new URL(req.url, 'http://localhost');
    const responder = (codigo, corpo) => { res.writeHead(codigo, { 'Content-Type': 'application/json' }); res.end(JSON.stringify(corpo)); };
    if (req.method === 'GET' && url.pathname === '/health') {
      return responder(200, { ok: true, caixa: CAIXA, envio_ligado: env.RENOVACAO_ENVIO_LIGADO === 'true',
        respostas_ligadas: env.RENOVACAO_RESPOSTAS_LIGADAS === 'true', bia_agenciados: Boolean(ia), ...estado });
    }
    const m = url.pathname.match(/^\/webhook\/([A-Za-z0-9_-]{32,128})$/);
    if (req.method === 'POST' && m) {
      if (!segredoConfere(m[1], env.RENOVACAO_WEBHOOK_SEGREDO)) return responder(404, { ok: false });
      let corpo = '';
      req.on('data', (p) => { corpo += p; if (corpo.length > 256000) req.destroy(); });
      req.on('end', () => {
        responder(200, { ok: true });
        if (env.RENOVACAO_RESPOSTAS_LIGADAS !== 'true') return;
        let evento;
        try { evento = JSON.parse(corpo); } catch { return; }
        const msg = lerEvento(evento, CAIXA);
        if (msg) { fila.push(msg); processar(); }
      });
      return undefined;
    }
    return responder(404, { ok: false });
  });
}

if (process.argv[1]?.endsWith('servico.mjs')) {
  const env = process.env;
  for (const k of ['SUPABASE_URL', 'SUPABASE_SERVICE_KEY', 'CHATWOOT_BASE_URL', 'CHATWOOT_ACCOUNT_ID', 'CHATWOOT_API_TOKEN']) {
    if (!env[k]) throw new Error(`falta ${k}`);
  }
  const db = criarBanco(env), cw = chatwoot(env);
  criarServidor(env, db, cw).listen(Number(env.PORT || 8080), '::', () => log('no_ar', { porta: env.PORT || 8080, caixa: CAIXA }));
  setTimeout(() => { rodada(env, db, cw); setInterval(() => rodada(env, db, cw), HORA_MS); }, PRIMEIRA_RODADA_MS);
}
