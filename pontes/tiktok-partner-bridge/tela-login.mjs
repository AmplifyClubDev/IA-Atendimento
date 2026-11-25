// 25/11/2026: reconhece a tela de login/verificação do TikTok pelo endereço (só lê a URL; nada é clicado).
// Mesma regra da ponte de Agenciamento/Pré-validação (auto-recuperacao.mjs, classificarPagina).
export function paginaDeLogin(value) {
  let u;
  try { u = new URL(String(value || '')); } catch { return false; }
  if (u.protocol !== 'https:') return false;
  const caminho = `${u.pathname}${u.search}`.toLowerCase();
  if (/(^|[/?&=._-])(login|signin|sign-in|sign_in|passport|register|signup|verify|verification|captcha|2fa|mfa)([/?&=._-]|$)/.test(caminho)) {
    return true;
  }
  return /(^|\.)(tiktok|tiktokshop|tiktokglobalshop)\.com$/.test(u.hostname) && /account|auth|oauth/.test(caminho);
}

// Precisa de humano depois de 2 aberturas seguidas que terminaram na tela de login.
export const FALHAS_PARA_PEDIR_LOGIN = 2;
