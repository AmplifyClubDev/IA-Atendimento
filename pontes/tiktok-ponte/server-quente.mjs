#!/usr/bin/env node
/**
 * Ponte TikTok nativa do AmplifyOS com contexto Playwright persistente.
 *
 * POR QUE EXISTE
 * Criar processo e Chromium por requisicao adicionava de 15 a 27 segundos.
 * O contexto persistente elimina esse custo e mantem o processamento
 * serializado para proteger a sessao do Partner Center.
 *
 * Medido em 2026-07-29 com a ponte ociosa: 15,8s · 18,2s · 26,7s por chamada.
 * Com page_limit=1 ainda deu 18s — não é paginação, é o navegador nascendo.
 * E como a ponte atende UMA tarefa por vez, o backlog de convites a mantém
 * ocupada e o caminho quente perde a corrida: em 2026-07-30, 17 leads tinham
 * aceitado de verdade e nenhum foi promovido, porque a confirmação de 60s
 * estourava atrás de um /invite de até 150s.
 *
 * Aqui o navegador e a página do Partner Center ficam VIVOS entre requisições.
 * O custo caro acontece uma vez, no boot. Cada chamada passa a ser só a
 * requisição de verdade.
 *
 * SEGURANÇA DE OPERAÇÃO
 * - Contrato HTTP unico consumido pelo Back-End e Worker.
 * - Uma operação por vez na mesma página (fila interna), como hoje.
 * - Recicla o contexto por número de chamadas, por idade e sempre que der erro
 *   de navegador — página viva acumula memória e pode ficar num estado ruim.
 * - /health prova que o processo vive; /ready prova contexto, sessao e leitura
 *   autenticada no Partner Center sem criar convite.
 */
import crypto from 'node:crypto';
import { validRole, roleAllows, capturedRelationUrl, activateExistingSession } from './interactive-policy.mjs';
import { relationDetails } from './relation-details.mjs';
import {
  arquivoContexto, classificarPagina, lerContextoSalvo, limparTravaOrfa, paginaDeParceiroValida, proximaEspera,
  salvarContexto,
} from './auto-recuperacao.mjs';
import http from 'node:http';
import os from 'node:os';
import path from 'node:path';
import process from 'node:process';
import { chromium } from 'playwright';

import {
  computeDueDateSecond,
  createInvitation,
  defaults,
  listCreatorGmvReport,
  listRelations,
  normalizeCreator,
  normalizeRelation,
  parseCreatorList,
  precheckCreator,
  verifyCreatorRelation,
} from './invite.mjs';
import { evaluateReadiness } from './readiness-state.mjs';
import {
  deveIgnorarCacheRelacoes,
  invalidarCacheRelacoesAposConvite,
  relacoesCompletas,
} from './relations-cache-policy.mjs';

const bridgeRole = process.env.BRIDGE_ROLE;
if (!validRole(bridgeRole)) throw new Error('EXPLICIT_BRIDGE_ROLE_REQUIRED');
const interactive = process.env.TIKTOK_INTERACTIVE_SESSION === 'true';
if (!interactive) throw new Error('INTERACTIVE_SESSION_REQUIRED');
let operatorLoginMode = true;
let interactiveChanging = false;
const host = process.env.TIKTOK_INVITE_SERVER_HOST || '0.0.0.0';
// Porta unica da ponte nativa, exposta apenas pelo tunnel HTTPS.
const port = Number(process.env.TIKTOK_WARM_SERVER_PORT || 8788);
const token = process.env.TIKTOK_INVITE_SERVER_TOKEN;
const tokensAceitos = [
  token,
  process.env.TIKTOK_INVITE_SERVER_TOKEN_PREVIOUS,
].filter((valor, indice, itens) => valor && itens.indexOf(valor) === indice);

const MAX_CHAMADAS_POR_CONTEXTO = Number(process.env.TIKTOK_WARM_MAX_CALLS || 200);
const MAX_IDADE_CONTEXTO_MS = Number(process.env.TIKTOK_WARM_MAX_AGE_MS || 60 * 60 * 1000);
const TIMEOUT_OPERACAO_MS = Number(process.env.TIKTOK_WARM_OP_TIMEOUT_MS || 120_000);
const READY_PROBE_TTL_MS = inteiroEntre(process.env.TIKTOK_READY_PROBE_TTL_MS, 60_000, 5_000, 5 * 60_000);
const READY_PROBE_FAILURE_TTL_MS = inteiroEntre(
  process.env.TIKTOK_READY_PROBE_FAILURE_TTL_MS,
  15_000,
  5_000,
  60_000,
);
const READY_PROBE_GRACE_MS = inteiroEntre(
  process.env.TIKTOK_READY_PROBE_GRACE_MS,
  3 * 60_000,
  READY_PROBE_TTL_MS,
  15 * 60_000,
);
const READY_RECOVERY_COOLDOWN_MS = inteiroEntre(
  process.env.TIKTOK_READY_RECOVERY_COOLDOWN_MS,
  30_000,
  5_000,
  5 * 60_000,
);
const READY_BACKGROUND_TICK_MS = Math.max(5_000, Math.min(READY_PROBE_TTL_MS, 30_000));
const RISK_GUARD_COOLDOWN_MS = inteiroEntre(
  process.env.TIKTOK_RISK_GUARD_COOLDOWN_MS,
  15 * 60_000,
  60_000,
  2 * 60 * 60_000,
);
const RISK_GUARD_CODES = new Set([
  'captcha_required',
  'mfa_required',
  'session_or_partner_context_invalid',
  'partner_probe_rejected',
]);

if (!token) {
  console.error('Missing TIKTOK_INVITE_SERVER_TOKEN in .env');
  process.exit(1);
}

let contexto = null;
let pagina = null;
let partnerContext = null;
let contextoPronto = false;
let chamadas = 0;
let nascidoEm = 0;
let preparando = null;
let ocupadoDesde = null;
let filaTamanho = 0;
let ultimaTentativaContextoEm = 0;
let ultimoErroContexto = null;
let ultimoProbeReadiness = null;
let probeReadinessEmVoo = null;
let bloqueioRisco = null;

// Endereço da lista e página de parcerias aprendidos no último login (ficam no volume /data).
const ARQUIVO_CONTEXTO = arquivoContexto(defaults.profileDir);

function paginaInicial() {
  return lerContextoSalvo(ARQUIVO_CONTEXTO)?.pageUrl || defaults.partnerUrl;
}

async function abrirContexto() {
  if (contexto && pagina && !pagina.isClosed()) return;
  if (contexto) {
    pagina = contexto.pages().find(p => !p.isClosed()) || await contexto.newPage();
    await pagina.goto(paginaInicial(), { waitUntil: 'domcontentloaded', timeout: 60000 }).catch(() => {});
    return;
  }
  operatorLoginMode = true;
  contextoPronto = false;
  if (limparTravaOrfa(defaults.profileDir, os.hostname())) console.error('[quente] trava do Chrome de container antigo removida');
  contexto = await chromium.launchPersistentContext(defaults.profileDir, {
    headless: defaults.headless, viewport: { width: 1440, height: 1000 },
  });
  const salvo = lerContextoSalvo(ARQUIVO_CONTEXTO);
  partnerContext = { relationListUrl: salvo?.relationListUrl || null, reportDimensionListUrl: null };
  contexto.on('request', request => {
    const url = request.url();
    if (!capturedRelationUrl(url)) return;
    partnerContext.relationListUrl = url;
    let paginaAtual = null;
    try { paginaAtual = request.frame()?.url() || null; } catch { paginaAtual = null; }
    try {
      salvarContexto(ARQUIVO_CONTEXTO, {
        relationListUrl: url,
        pageUrl: paginaDeParceiroValida(paginaAtual) ? paginaAtual : salvo?.pageUrl,
      });
    } catch (erro) {
      console.error(`[quente] nao salvou contexto: ${erro.message}`);
    }
  });
  pagina = contexto.pages().find(p => !p.isClosed()) || await contexto.newPage();
  // Navigation only: no DOM is read or clicked. The saved partnerships page lets the session resume by itself.
  await pagina.goto(paginaInicial(), { waitUntil: 'domcontentloaded', timeout: 60000 }).catch(() => {});
}

// ---- volta sozinha: reativa a sessão que ainda vale; só pede humano na tela de login ----
const autoRecuperacao = { estado: 'aguardando', tentativas: 0, proximaEm: null, ultimo: null, timer: null };

function agendarAutoAtivacao(motivo, esperaMs = proximaEspera(autoRecuperacao.tentativas)) {
  if (process.env.NODE_ENV === 'test' && process.env.TIKTOK_DISABLE_WARMUP_FOR_TESTS === 'true') return;
  if (autoRecuperacao.timer) clearTimeout(autoRecuperacao.timer);
  let espera = esperaMs;
  if (bloqueioRisco) espera = Math.max(espera, bloqueioRisco.ate - Date.now() + 1000);
  autoRecuperacao.proximaEm = Date.now() + espera;
  autoRecuperacao.timer = setTimeout(() => { void autoAtivar(motivo); }, espera);
  autoRecuperacao.timer.unref?.();
}

async function autoAtivar(motivo) {
  autoRecuperacao.timer = null;
  autoRecuperacao.proximaEm = null;
  if (contextoUtilizavel() && !operatorLoginMode) {
    autoRecuperacao.estado = 'pronta';
    return;
  }
  if (bloqueioRiscoAtivo()) return agendarAutoAtivacao(motivo);
  if (interactiveChanging || ocupadoDesde || filaTamanho || preparando || probeReadinessEmVoo) {
    return agendarAutoAtivacao(motivo, 15_000);
  }
  autoRecuperacao.estado = 'tentando';
  try {
    if (!contexto || !pagina || pagina.isClosed()) await abrirContexto();
    // Dá tempo para a página de parcerias carregar e mostrar a lista (se a sessão vale).
    for (let i = 0; i < 20 && !capturedRelationUrl(partnerContext?.relationListUrl); i += 1) {
      await new Promise((r) => setTimeout(r, 1000));
    }
    if (classificarPagina(pagina?.url?.()) === 'login') {
      autoRecuperacao.estado = 'precisa_humano';
      autoRecuperacao.ultimo = { em: Date.now(), resultado: 'tela_de_login', motivo };
      console.error('[quente] TikTok pediu login: precisa de humano');
      return;
    }
    await interactiveCommand('activate');
    autoRecuperacao.estado = 'pronta';
    autoRecuperacao.tentativas = 0;
    autoRecuperacao.ultimo = { em: Date.now(), resultado: 'reativada', motivo };
    console.error(`[quente] sessao reativada sozinha (${motivo})`);
  } catch (erro) {
    autoRecuperacao.tentativas += 1;
    autoRecuperacao.estado = 'aguardando';
    autoRecuperacao.ultimo = { em: Date.now(), resultado: classificarErroReadiness(erro), motivo };
    console.error(`[quente] reativacao falhou (${autoRecuperacao.tentativas}): ${classificarErroReadiness(erro)}`);
    agendarAutoAtivacao(motivo);
  }
}

async function interactiveCommand(command) {
  if (interactiveChanging || ocupadoDesde || filaTamanho || preparando || probeReadinessEmVoo)
    throw new Error('interactive_session_busy');
  interactiveChanging = true;
  try {
    if (command === 'login') {
      operatorLoginMode = true;
      contextoPronto = false;
      ultimoProbeReadiness = null;
      cacheRelacoes.clear();
      if (!contexto || !pagina || pagina.isClosed()) await abrirContexto();
      return { ok: true, status: 'login' };
    }
    if (command !== 'activate') throw new Error('interactive_command_rejected');
    return await activateExistingSession({
      busy: () => Boolean(ocupadoDesde || filaTamanho || preparando || probeReadinessEmVoo),
      hasContext: () => Boolean(contexto && pagina && !pagina.isClosed() && capturedRelationUrl(partnerContext?.relationListUrl)),
      readProof: () => listRelations(pagina, partnerContext, { status: '1', pageSize: 1, pageLimit: 1 }),
      commit: () => {
        contextoPronto = true;
        operatorLoginMode = false;
        nascidoEm = Date.now();
        chamadas = 0;
        ultimoErroContexto = null;
        bloqueioRisco = null;
        ultimoProbeReadiness = { ok: true, status: 'ok', em: Date.now(), duracaoMs: null };
      },
    });
  } finally { interactiveChanging = false; }
}

process.on('message', async message => {
  if (!message || typeof message !== 'object' || Array.isArray(message)
      || Object.keys(message).sort().join(',') !== 'command,id'
      || !/^[a-f0-9]{32}$/.test(message.id) || !['login', 'activate'].includes(message.command)) return;
  try {
    const result = await interactiveCommand(message.command);
    process.send?.({ id: message.id, ...result });
  } catch {
    process.send?.({ id: message.id, ok: false, status: 'interactive_activation_rejected' });
  }
});

async function fecharContexto(motivo) {
  operatorLoginMode = true;
  console.error('[quente] context closed; human activation required');
  const anterior = contexto;
  contexto = null;
  pagina = null;
  partnerContext = null;
  contextoPronto = false;
  nascidoEm = 0;
  ultimoProbeReadiness = null;
  cacheRelacoes.clear();
  try {
    await anterior?.close();
  } catch (erro) {
    console.error(`[quente] falha ao fechar contexto: ${erro.message}`);
  }
}

function precisaReciclar() {
  if (!contexto || !pagina || pagina.isClosed()) return 'contexto ausente';
  if (!contextoPronto) return 'contexto ainda nao esta pronto';
  if (chamadas >= MAX_CHAMADAS_POR_CONTEXTO) return `${chamadas} chamadas`;
  if (nascidoEm > 0 && Date.now() - nascidoEm >= MAX_IDADE_CONTEXTO_MS) return 'idade máxima';
  return null;
}

async function garantirContexto() {
  verificarBloqueioRisco();
  if (operatorLoginMode || interactiveChanging || !contextoUtilizavel())
    throw new Error('interactive_login_required');
  // Keep the authenticated browser alive. Lost sessions require human activation;
  // no navigation, screenshots, DOM lookup or automated login takes place here.
}

// Fila serial: a mesma página não pode atender duas operações ao mesmo tempo.
let corrente = Promise.resolve();

function naFila(rotulo, operacao) {
  if (operatorLoginMode || interactiveChanging) return Promise.reject(new Error('interactive_login_required'));
  if (filaTamanho >= 4) return Promise.reject(new Error('bridge_queue_full'));
  filaTamanho += 1;
  const resultado = corrente.then(async () => {
    filaTamanho -= 1;
    ocupadoDesde = Date.now();
    try {
      verificarBloqueioRisco();
      await garantirContexto();
      const comPrazo = new Promise((_, rejeitar) => {
        setTimeout(() => rejeitar(new Error(`operação ${rotulo} passou de ${TIMEOUT_OPERACAO_MS}ms`)), TIMEOUT_OPERACAO_MS).unref();
      });
      return await Promise.race([operacao(pagina, partnerContext), comPrazo]);
    } catch (erro) {
      // Contexto que nunca foi aprendido (ex.: tela de relatório nunca aberta) não é sessão ruim:
      // a página está boa, então não fecha o navegador nem liga a pausa de segurança.
      if (/^Could not capture TikTok /.test(String(erro?.message || ''))) throw erro;
      // Erro de navegador deixa a página em estado duvidoso: recicla.
      registrarErroContexto(erro);
      registrarBloqueioRiscoSeNecessario(erro, rotulo);
      await fecharContexto(`erro em ${rotulo}: ${erro.message}`);
      autoRecuperacao.tentativas = 0;
      agendarAutoAtivacao(`erro em ${rotulo}`);
      throw erro;
    } finally {
      chamadas += 1;
      ocupadoDesde = null;
    }
  });
  corrente = resultado.then(() => undefined, () => undefined);
  return resultado;
}

// ---- cache curto da lista de relacoes ----
// A lista inteira custa ~25s (23 paginas) e nao da pra pedir so um creator:
// o filtro da API e ignorado. Sem cache, cada lead que declara aceite paga a
// agencia inteira. Requisicoes simultaneas compartilham a mesma varredura.
const CACHE_RELACOES_MS = Number(process.env.TIKTOK_RELATIONS_CACHE_MS || 90_000);
const cacheRelacoes = new Map();

async function relacoesEmCache(status, pageSize, pageLimit) {
  const chave = `${status}|${pageSize}|${pageLimit}`;
  const guardado = cacheRelacoes.get(chave);
  if (guardado) {
    const idadeMs = Date.now() - guardado.em;
    if (guardado.emVoo) return { ...(await guardado.emVoo), doCache: true, idadeMs: 0 };
    if (idadeMs < CACHE_RELACOES_MS) return { ...guardado.valor, doCache: true, idadeMs };
  }
  const emVoo = naFila('relations', (page, ctx) => listRelations(page, ctx, { status, pageSize, pageLimit }));
  cacheRelacoes.set(chave, { em: Date.now(), valor: null, emVoo });
  try {
    const valor = await emVoo;
    // So guarda resultado bom: erro em cache repetiria a falha por 90s.
    if (valor.ok) cacheRelacoes.set(chave, { em: Date.now(), valor, emVoo: null });
    else cacheRelacoes.delete(chave);
    return { ...valor, doCache: false, idadeMs: 0 };
  } catch (erro) {
    cacheRelacoes.delete(chave);
    throw erro;
  }
}

async function executarProbeReadiness() {
  const agora = Date.now();
  if (ultimoProbeReadiness) {
    const ttl = ultimoProbeReadiness.ok ? READY_PROBE_TTL_MS : READY_PROBE_FAILURE_TTL_MS;
    if (agora - ultimoProbeReadiness.em < ttl) {
      return { ...ultimoProbeReadiness, cached: true };
    }
  }
  if (probeReadinessEmVoo) {
    return { ...(await probeReadinessEmVoo), shared: true };
  }

  probeReadinessEmVoo = (async () => {
    const inicio = Date.now();
    try {
      // Uma pagina e um item bastam para provar navegador, sessao e API
      // autenticada. Esta sonda nunca chama relation/create e nunca convida.
      const resultado = await naFila('readiness-probe', async (page, ctx) => {
        const leitura = await listRelations(page, ctx, { status: '1', pageSize: 1, pageLimit: 1 });
        if (!leitura.ok) {
          const erro = new Error('Partner rejected the read-only readiness probe');
          erro.code = 'partner_probe_rejected';
          throw erro;
        }
        return leitura;
      });
      const probe = {
        ok: true,
        status: 'ok',
        em: Date.now(),
        duracaoMs: Date.now() - inicio,
        // Nunca devolve creators ou o payload bruto do Partner na telemetria.
        totalDisponivel: resultado.totalNum !== undefined && resultado.totalNum !== null,
      };
      ultimoProbeReadiness = probe;
      return probe;
    } catch (erro) {
      const probe = {
        ok: false,
        status: 'failed',
        em: Date.now(),
        duracaoMs: Date.now() - inicio,
        errorCode: classificarErroReadiness(erro),
      };
      ultimoProbeReadiness = probe;
      return probe;
    }
  })().finally(() => {
    probeReadinessEmVoo = null;
  });

  return await probeReadinessEmVoo;
}

function contextoUtilizavel() {
  return Boolean(contextoPronto && contexto && pagina && !pagina.isClosed());
}

function avaliarReadiness(agora = Date.now()) {
  return evaluateReadiness({
    contextReady: contextoUtilizavel(),
    contextStatus: estadoContexto(),
    preparing: Boolean(preparando),
    busy: Boolean(ocupadoDesde || filaTamanho > 0),
    refreshing: Boolean(probeReadinessEmVoo),
    probe: ultimoProbeReadiness,
    now: agora,
    successTtlMs: READY_PROBE_TTL_MS,
    failureTtlMs: READY_PROBE_FAILURE_TTL_MS,
    graceMs: READY_PROBE_GRACE_MS,
  });
}

function solicitarProbeReadiness() {
  if (operatorLoginMode || interactiveChanging) return false;
  const avaliacao = avaliarReadiness();
  if (!avaliacao.shouldRefresh) return false;
  // Intencionalmente sem await: o endpoint /ready nunca espera a fila serial.
  // A sonda Playwright roda em background e a proxima consulta observa o
  // resultado; durante a renovacao, o ultimo sucesso vale ate o limite de
  // tolerancia configurado.
  void executarProbeReadiness().catch((erro) => {
    // O executor normalmente converte falhas em um probe sanitizado. Este
    // catch protege o processo contra uma rejeicao de infraestrutura fora do
    // fluxo esperado sem expor a mensagem original na resposta HTTP.
    ultimoProbeReadiness = {
      ok: false,
      status: 'failed',
      em: Date.now(),
      duracaoMs: null,
      errorCode: classificarErroReadiness(erro),
    };
  });
  return true;
}

function solicitarRecuperacaoContexto() {
  if (interactive) return;
  if (
    process.env.NODE_ENV === 'test'
    && process.env.TIKTOK_DISABLE_WARMUP_FOR_TESTS === 'true'
  ) return;
  if (bloqueioRiscoAtivo()) return;
  if (preparando || contextoUtilizavel()) return;
  if (Date.now() - ultimaTentativaContextoEm < READY_RECOVERY_COOLDOWN_MS) return;
  garantirContexto().catch((erro) => {
    console.error(`[quente] recuperacao de contexto falhou: ${erro.message}`);
  });
}

function estadoContexto() {
  if (bloqueioRiscoAtivo()) return 'blocked_by_risk_guard';
  if (contextoUtilizavel()) return 'ready';
  if (preparando) return 'preparing';
  if (ultimoErroContexto || ultimoProbeReadiness?.ok === false) return 'degraded';
  return 'cold';
}

function telemetriaSanitizada(avaliacao = avaliarReadiness()) {
  const agora = Date.now();
  const probe = ultimoProbeReadiness
    ? {
        status: ultimoProbeReadiness.status,
        checkedAt: new Date(ultimoProbeReadiness.em).toISOString(),
        ageMs: Math.max(0, agora - ultimoProbeReadiness.em),
        durationMs: ultimoProbeReadiness.duracaoMs,
        errorCode: ultimoProbeReadiness.errorCode || null,
      }
    : { status: 'never' };
  return {
    modo: 'contexto-quente',
    contexto: {
      status: estadoContexto(),
      aberto: Boolean(contexto),
      pronto: contextoUtilizavel(),
      chamadas,
      idadeMs: contextoPronto ? agora - nascidoEm : null,
    },
    queue: {
      length: filaTamanho,
      activeMs: ocupadoDesde ? agora - ocupadoDesde : null,
    },
    readiness: {
      status: avaliacao.status,
      fresh: avaliacao.fresh,
      withinGrace: avaliacao.withinGrace,
      refreshing: Boolean(probeReadinessEmVoo),
      graceMs: READY_PROBE_GRACE_MS,
    },
    probe,
    lastContextError: ultimoErroContexto
      ? {
          code: ultimoErroContexto.code,
          at: new Date(ultimoErroContexto.em).toISOString(),
      }
    : null,
    riskGuard: bloqueioRiscoAtivo()
      ? {
          status: 'blocked',
          code: bloqueioRisco.code,
          reason: bloqueioRisco.reason,
          blockedAt: new Date(bloqueioRisco.em).toISOString(),
          retryAfterMs: Math.max(0, bloqueioRisco.ate - agora),
        }
      : { status: 'clear' },
  };
}

function registrarErroContexto(erro) {
  ultimoErroContexto = {
    code: classificarErroReadiness(erro),
    em: Date.now(),
  };
}

function bloqueioRiscoAtivo(agora = Date.now()) {
  if (!bloqueioRisco) return false;
  if (agora < bloqueioRisco.ate) return true;
  console.error(`[quente] risk guard liberado apos cooldown: ${bloqueioRisco.code}`);
  bloqueioRisco = null;
  return false;
}

function verificarBloqueioRisco() {
  if (!bloqueioRiscoAtivo()) return;
  const erro = new Error(`blocked_by_risk_guard:${bloqueioRisco.code}`);
  erro.code = 'blocked_by_risk_guard';
  throw erro;
}

function registrarBloqueioRiscoSeNecessario(erro, rotulo) {
  const code = classificarErroReadiness(erro);
  if (!RISK_GUARD_CODES.has(code)) return;
  const agora = Date.now();
  bloqueioRisco = {
    code,
    reason: rotulo,
    em: agora,
    ate: agora + RISK_GUARD_COOLDOWN_MS,
  };
  console.error(`[quente] risk guard ativo por ${Math.round(RISK_GUARD_COOLDOWN_MS / 1000)}s: ${code} em ${rotulo}`);
}

function classificarErroReadiness(erro) {
  if (erro?.code === 'blocked_by_risk_guard') return 'blocked_by_risk_guard';
  if (erro?.code === 'partner_probe_rejected') return 'partner_probe_rejected';
  const mensagem = String(erro?.message || erro || '').toLowerCase();
  if (mensagem.includes("executable doesn't exist") || mensagem.includes('browser executable')) {
    return 'browser_missing';
  }
  if (mensagem.includes('captcha')) return 'captcha_required';
  if (mensagem.includes('2fa') || mensagem.includes('mfa')) return 'mfa_required';
  if (
    mensagem.includes('login')
    || mensagem.includes('sign in')
    || mensagem.includes('session')
    || mensagem.includes('relation/list')
  ) return 'session_or_partner_context_invalid';
  if (mensagem.includes('timeout') || mensagem.includes('passou de')) return 'timeout';
  if (mensagem.includes('closed') || mensagem.includes('crash')) return 'browser_unavailable';
  return 'unknown';
}

function inteiroEntre(valor, padrao, minimo, maximo) {
  const numero = Number(valor);
  if (!Number.isFinite(numero)) return padrao;
  return Math.max(minimo, Math.min(Math.trunc(numero), maximo));
}

const servidor = http.createServer(async (req, res) => {
  try {
    const url = new URL(req.url, `http://${req.headers.host || 'localhost'}`);

    if (req.method === 'GET' && url.pathname === '/health') {
      return responder(res, 200, {
        ok: true,
        liveness: 'alive',
        role: bridgeRole,
        operatorLoginMode,
        interactiveChanging,
        status: estadoContexto(),
        contextoAberto: Boolean(contexto),
        contextoPronto: contextoUtilizavel(),
        chamadasNoContexto: chamadas,
        idadeContextoMs: contextoPronto ? Date.now() - nascidoEm : null,
        queueLength: filaTamanho,
        activeMs: ocupadoDesde ? Date.now() - ocupadoDesde : null,
        autoRecuperacao: {
          estado: autoRecuperacao.estado,
          tentativas: autoRecuperacao.tentativas,
          proximaEmMs: autoRecuperacao.proximaEm ? Math.max(0, autoRecuperacao.proximaEm - Date.now()) : null,
          ultimo: autoRecuperacao.ultimo
            ? { em: new Date(autoRecuperacao.ultimo.em).toISOString(), resultado: autoRecuperacao.ultimo.resultado }
            : null,
        },
        ...telemetriaSanitizada(),
        relacoesEmCache: [...cacheRelacoes.entries()]
          .filter(([, v]) => v.valor)
          .map(([chave, v]) => ({
            chave,
            itens: v.valor.items?.length ?? 0,
            total: v.valor.totalNum ?? null,
            idadeMs: Date.now() - v.em,
          })),
      });
    }

    if (!roleAllows(bridgeRole, req.method, url.pathname)) return responder(res, 404, {ok:false,status:'role_route_denied'});
    if (operatorLoginMode || interactiveChanging) return responder(res, 503, {ok:false,status:'human_login_required'});

    if (req.method === 'GET' && url.pathname === '/ready') {
      if (!autorizado(req)) return responder(res, 401, { ok: false, status: 'unauthorized' });

      if (!contextoUtilizavel() || preparando) {
        solicitarRecuperacaoContexto();
      }

      solicitarProbeReadiness();
      const avaliacao = avaliarReadiness();
      const telemetria = telemetriaSanitizada(avaliacao);
      return responder(res, avaliacao.ready ? 200 : 503, {
        ok: avaliacao.ready,
        status: avaliacao.status,
        ...telemetria,
      });
    }

    if (!autorizado(req)) return responder(res, 401, { ok: false, status: 'unauthorized' });

    if (req.method === 'GET' && url.pathname === '/relations') {
      const status = String(url.searchParams.get('status') || '1');
      const pageSize = Number(url.searchParams.get('page_size') || url.searchParams.get('pageSize') || 100);
      const pageLimit = Number(url.searchParams.get('page_limit') || url.searchParams.get('pageLimit') || 30);
      const creators = parseCreatorList(
        url.searchParams.get('creators') || url.searchParams.get('creator') || url.searchParams.get('users'),
      );
      // O creator_name da API do TikTok nao filtra nada: ela devolve a lista
      // inteira e quem filtra somos nos. Como sao 23 paginas (~25s), consultar
      // um unico @ custava a agencia inteira. O cache resolve isso; confirmacao
      // de aceite ou de convite recem-criado precisa sempre ler o estado atual.
      const semCache = deveIgnorarCacheRelacoes({
        priority: url.searchParams.get('priority'),
        fresh: url.searchParams.get('fresh'),
      });
      const bruto = semCache
        ? await naFila('relations', (page, ctx) => listRelations(page, ctx, { status, pageSize, pageLimit }))
        : await relacoesEmCache(status, pageSize, pageLimit);

      // ?detalhes=1: junta os campos do TikTok (nível, GMV, seguidores...) para o espelho no banco.
      const comDetalhes = url.searchParams.get('detalhes') === '1';
      let items = (bruto.items || []).map((r) => (comDetalhes
        ? { ...normalizeRelation(r), detalhes: relationDetails(r) }
        : normalizeRelation(r)));
      if (creators.size) {
        items = items.filter((i) => creators.has(normalizeCreator(i.arroba).toLowerCase()));
      }
      const saida = {
        ok: bruto.ok,
        status: bruto.ok ? 'relations_listed' : 'relations_failed',
        query: { status, pageSize, pageLimit, creators: [...creators] },
        count: items.length,
        totalNum: bruto.totalNum,
        statusCount: bruto.statusCount,
        completo: relacoesCompletas(bruto),
        cache: bruto.doCache ? { idadeMs: bruto.idadeMs } : null,
        items,
        pages: bruto.pages,
        error: bruto.error,
      };
      return responder(res, saida.ok ? 200 : 422, saida);
    }

    if (req.method === 'GET' && url.pathname === '/gmv-report') {
      const saida = await naFila('gmv-report', (page, ctx) => listCreatorGmvReport(page, ctx, {
        startDate: url.searchParams.get('start_date') || url.searchParams.get('startDate') || '',
        endDateExclusive: url.searchParams.get('end_date_exclusive') || url.searchParams.get('endDateExclusive') || '',
        pageSize: Number(url.searchParams.get('page_size') || url.searchParams.get('pageSize') || 100),
        pageLimit: Number(url.searchParams.get('page_limit') || url.searchParams.get('pageLimit') || 50),
      }));
      return responder(res, saida.ok ? 200 : 422, saida);
    }

    if (req.method !== 'POST') return responder(res, 405, { ok: false, status: 'method_not_allowed' });
    if (!['/precheck', '/invite'].includes(url.pathname)) {
      return responder(res, 404, { ok: false, status: 'not_found' });
    }

    const body = await lerJson(req);
    const creator = normalizeCreator(body.creator || body.tiktok_user || body.tiktok || body['@']);
    if (!creator) return responder(res, 400, { ok: false, status: 'missing_creator' });

    if (url.pathname === '/precheck') {
      const saida = await naFila('precheck', async (page, ctx) => {
        const precheck = await precheckCreator(page, ctx, creator);
        return {
          ok: precheck.ok,
          status: precheck.ok ? 'precheck_ok' : 'precheck_failed',
          creator,
          precheck,
          result: { ok: precheck.ok, status: precheck.ok ? 'precheck_ok' : 'precheck_failed', creator, precheck },
        };
      });
      return responder(res, saida.ok ? 200 : 422, saida);
    }

    // /invite — exige confirmação explícita, igual à ponte atual.
    if (!verdadeiro(body.confirm || body.confirmar_envio || body.yes)) {
      return responder(res, 400, {
        ok: false,
        status: 'missing_confirmation',
        message: 'Set confirmar_envio/confirm/yes to SIM/true to send.',
      });
    }
    const commission = String(body.commission || body.comissao || defaults.commission);
    const forceReinvite = verdadeiro(body.force_reinvite || body.forceReinvite);
    if (forceReinvite) return responder(res, 422, {ok:false,status:'api_only_reinvite_contract_missing'});
    // O payload tem que ser EXATAMENTE o que o CLI monta — chaves da API do
    // Partner Center, em snake_case. Passar camelCase devolve
    // "Invalid parameters. Please verify your input" (pego no teste com
    // @jozilene.andrade7 antes do corte; se tivesse cortado, todo convite
    // pararia). Mesma regra do due_date: com precheck pulado, a duração é fixa
    // em 2 meses, como o commit "use fixed invite duration without precheck".
    const pularPrecheck = (() => {
      const bruto = body.skip_precheck ?? body.skipPrecheck;
      if (bruto === undefined || bruto === null || bruto === '') return true;
      return verdadeiro(bruto);
    })();
    const saida = await naFila('invite', async (page, ctx) => {
      const precheck = pularPrecheck
        ? { ok: true, status: 'skipped', reason: 'technical TikTok requirements already confirmed by acquisition funnel' }
        : await precheckCreator(page, ctx, creator);
      if (precheck.ok === false) {
        return { ok: false, status: 'precheck_failed', creator, precheck };
      }
      const dueDateSecond = String(computeDueDateSecond({
        days: Number(defaults.dueDays),
        fixedMonths: pularPrecheck ? 2 : Number(precheck.data?.data?.bind_duration_fixed_month),
      }));
      const payload = {
        creator_name: creator,
        due_date_second: dueDateSecond,
        related_biz_types: String(defaults.relatedBizTypes),
        commission_proportion: commission,
        is_attached_business_profile: true,
      };
      const create = await createInvitation(page, ctx, payload);
      if (create.ok === false) {
        return { ok: false, status: 'invite_failed', creator, precheck, create };
      }
      // Uma leitura anterior de status=2 pode ter guardado lista vazia. Depois
      // de relation/create, esse retrato deixou de ser valido imediatamente.
      invalidarCacheRelacoesAposConvite(cacheRelacoes);
      // Verificação pós-envio, igual ao CLI: o /invite responder sucesso não
      // basta; quem prova é a relação aparecendo na lista real.
      const validation = await verifyCreatorRelation(page, ctx, creator, {
        attempts: Number(process.env.TIKTOK_INVITE_VERIFY_ATTEMPTS || 3),
        delayMs: Number(process.env.TIKTOK_INVITE_VERIFY_DELAY_MS || 3000),
      });
      return {
        ok: validation.ok,
        status: validation.ok ? 'invite_sent_and_verified' : 'invite_sent_unverified',
        creator,
        precheck,
        create,
        validation,
      };
    });
    return responder(res, saida.ok ? 200 : 422, saida);
  } catch (erro) {
    const status = erro?.message === 'bridge_queue_full' ? 429
      : erro?.message === 'interactive_login_required' ? 503 : 500;
    return responder(res, status, { ok: false, status: status === 429 ? 'queue_full'
      : status === 503 ? 'human_login_required' : 'operation_uncertain_reconcile_same_target' });
  }
});

let readinessTimer = null;
servidor.listen(port, host, () => {
  const endereco = servidor.address();
  const portaReal = typeof endereco === 'object' && endereco ? endereco.port : port;
  console.error(`[quente] ponte com contexto quente ouvindo em ${host}:${portaReal}`);
  console.error(`[quente] perfil: ${defaults.profileDir} | headless: ${defaults.headless}`);
  // Aquece já no boot: quem chamar primeiro não paga a abertura.
  const pularAquecimentoNoTeste = process.env.NODE_ENV === 'test'
    && process.env.TIKTOK_DISABLE_WARMUP_FOR_TESTS === 'true';
  if (!pularAquecimentoNoTeste) {
    preparando = abrirContexto().catch(() => { ultimoErroContexto = {code:'login_context_unavailable',em:Date.now()}; })
      .finally(() => { preparando = null; });
    // Sessão do disco ainda vale? Ativa sozinha, sem esperar ninguém.
    agendarAutoAtivacao('inicio', 15_000);
  }
  readinessTimer = setInterval(() => {
    if (!operatorLoginMode && !interactiveChanging) solicitarProbeReadiness();
  }, READY_BACKGROUND_TICK_MS);
  readinessTimer.unref();
});

function autorizado(req) {
  const cab = String(req.headers.authorization || '');
  const bearer = cab.startsWith('Bearer ') ? cab.slice(7) : '';
  const alternativo = String(req.headers['x-tiktok-invite-token'] || '');
  return tokensAceitos.some((esperado) =>
    comparacaoSegura(bearer, esperado) || comparacaoSegura(alternativo, esperado));
}

function comparacaoSegura(recebido, esperado) {
  const a = Buffer.from(String(recebido || ''), 'utf8');
  const b = Buffer.from(String(esperado || ''), 'utf8');
  return a.length === b.length && a.length > 0 && crypto.timingSafeEqual(a, b);
}

function lerJson(req) {
  return new Promise((resolver, rejeitar) => {
    let bruto = '';
    req.on('data', (parte) => {
      bruto += parte;
      if (bruto.length > 32_000) {
        req.destroy();
        rejeitar(new Error('Request body too large'));
      }
    });
    req.on('end', () => {
      try {
        resolver(bruto ? JSON.parse(bruto) : {});
      } catch {
        rejeitar(new Error('Invalid JSON body'));
      }
    });
    req.on('error', rejeitar);
  });
}

function verdadeiro(valor) {
  return ['1', 'true', 'yes', 'sim', 's'].includes(String(valor || '').trim().toLowerCase());
}

function responder(res, codigo, valor) {
  res.writeHead(codigo, { 'content-type': 'application/json; charset=utf-8' });
  res.end(`${JSON.stringify(valor, null, 2)}\n`);
}

for (const sinal of ['SIGTERM', 'SIGINT']) {
  process.on(sinal, async () => {
    console.error(`[quente] ${sinal} recebido, fechando contexto`);
    if (readinessTimer) clearInterval(readinessTimer);
    await fecharContexto(sinal);
    process.exit(0);
  });
}
