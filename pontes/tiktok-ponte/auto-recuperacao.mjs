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

export function salvarContexto(arquivo, { relationListUrl, pageUrl }) {
  if (!capturedRelationUrl(relationListUrl)) return false;
  const dados = { relationListUrl, pageUrl: paginaDeParceiroValida(pageUrl) ? pageUrl : null, salvoEm: new Date().toISOString() };
  const temporario = `${arquivo}.tmp`;
  fs.writeFileSync(temporario, JSON.stringify(dados), { mode: 0o600 });
  fs.renameSync(temporario, arquivo);
  return true;
}
