import test from 'node:test';
import assert from 'node:assert/strict';
import { FALHAS_PARA_PEDIR_LOGIN, paginaDeLogin } from './tela-login.mjs';

test('reconhece a tela de login/verificação do TikTok só pelo endereço', () => {
  assert.equal(paginaDeLogin('https://partner.tiktokshop.com/account/login?redirect=x'), true);
  assert.equal(paginaDeLogin('https://seller.tiktokglobalshop.com/passport/verify'), true);
  assert.equal(paginaDeLogin('https://www.tiktok.com/auth/start'), true);
  assert.equal(paginaDeLogin('https://partner.tiktokshop.com/affiliate-cmp/partner/creator-management'), false);
  assert.equal(paginaDeLogin('about:blank'), false);
  assert.equal(paginaDeLogin(''), false);
  assert.equal(paginaDeLogin('http://partner.tiktokshop.com/login'), false);
  assert.equal(FALHAS_PARA_PEDIR_LOGIN, 2);
});
