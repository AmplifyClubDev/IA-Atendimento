// Sessão automática da ponte (23/11/2026): volta sozinha quando a sessão do TikTok ainda vale.
// - Guarda no disco o endereço da lista de parcerias e a página onde ele apareceu (aprendidos no último login).
// - Reconhece a tela de login/verificação do TikTok: só nesse caso pede um humano.
// - Agenda novas tentativas com espera crescente. Nada aqui clica, digita ou lê a página: só endereços.
import fs from 'node:fs';
import path from 'node:path';
import { capturedRelationUrl } from './interactive-policy.mjs';

export const ESPERAS_MS = Object.freeze([30_000, 2 * 60_000, 10 * 60_000]);
export const ESPERA_LENTA_MS = 30 * 60_000;

function urlSegura(value) {
  try {
    const u = new URL(value);
    if (u.protocol !== 'https:' || u.username || u.password) return null;
    return u;
  } catch {
    return null;
  }
}

// 'login': o TikTok está pedindo entrar ou verificar (precisa de humano).
// 'parceiro': uma página do Partner Center. 'desconhecida': qualquer outra coisa.
export function classificarPagina(value) {
  const u = urlSegura(value);
  if (!u) return 'desconhecida';
  const caminho = `${u.pathname}${u.search}`.toLowerCase();
  if (/(^|[/?&=._-])(login|signin|sign-in|sign_in|passport|register|signup|verify|verification|captcha|2fa|mfa)([/?&=._-]|$)/.test(caminho)) {
    return 'login';
  }
  if (u.hostname === 'partner.tiktokshop.com' || u.hostname.endsWith('.partner.tiktokshop.com')) return 'parceiro';
  if (/(^|\.)(tiktok|tiktokshop|tiktokglobalshop)\.com$/.test(u.hostname) && /account|auth|oauth/.test(caminho)) {
    return 'login';
  }
  return 'desconhecida';
}

export function paginaDeParceiroValida(value) {
  return classificarPagina(value) === 'parceiro';
}

export function proximaEspera(tentativasFalhas) {
  const n = Math.max(0, Math.trunc(Number(tentativasFalhas) || 0));
  return n < ESPERAS_MS.length ? ESPERAS_MS[n] : ESPERA_LENTA_MS;
}

// 25/11/2026: precisa de humano só quando a leitura de prova falhou numa tela de login/verificação do TikTok,
// ou quando o próprio erro pede verificação (captcha, código). Ponte ocupada nunca conta.
export function precisaLoginDeVerdade(telaDeLogin, erro) {
  const mensagem = String(erro?.message || erro || '').toLowerCase();
  if (mensagem.includes('interactive_session_busy')) return false;
  if (telaDeLogin === true) return true;
  return /captcha|2fa|mfa|verification|verify/.test(mensagem);
}

export function arquivoContexto(profileDir, env = process.env) {
  return env.TIKTOK_PARTNER_CONTEXT_FILE || path.join(path.dirname(profileDir), 'partner-context.json');
}

export function lerContextoSalvo(arquivo) {
  try {
    const dados = JSON.parse(fs.readFileSync(arquivo, 'utf8'));
    const relationListUrl = capturedRelationUrl(dados?.relationListUrl) ? dados.relationListUrl : null;
    const pageUrl = paginaDeParceiroValida(dados?.pageUrl) ? dados.pageUrl : null;
    return relationListUrl ? { relationListUrl, pageUrl } : null;
  } catch {
    return null;
  }
}

// Trava do Chrome deixada por um container antigo (SingletonLock -> "<host>-<pid>"). Num container novo,
// o volume /data só está aqui, então trava de outro host é órfã: o Chrome se recusa a abrir até ela sair.
// Só remove os 3 arquivos Singleton*; o perfil (cookies, login) não é tocado.
export function limparTravaOrfa(profileDir, hostAtual) {
  const trava = path.join(profileDir, 'SingletonLock');
  let alvo;
  try { alvo = fs.readlinkSync(trava); } catch { return false; }
  const host = String(alvo).replace(/-\d+$/, '');
  if (!host || host === hostAtual) return false;
  for (const nome of ['SingletonLock', 'SingletonCookie', 'SingletonSocket']) {
    try { fs.unlinkSync(path.join(profileDir, nome)); } catch { /* já não existe */ }
  }
  return true;
}

export function salvarContexto(arquivo, { relationListUrl, pageUrl }) {
  if (!capturedRelationUrl(relationListUrl)) return false;
  const dados = { relationListUrl, pageUrl: paginaDeParceiroValida(pageUrl) ? pageUrl : null, salvoEm: new Date().toISOString() };
  const temporario = `${arquivo}.tmp`;
  fs.writeFileSync(temporario, JSON.stringify(dados), { mode: 0o600 });
  fs.renameSync(temporario, arquivo);
  return true;
}
