import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {
  arquivoContexto, classificarPagina, lerContextoSalvo, limparTravaOrfa, proximaEspera, salvarContexto, ESPERA_LENTA_MS,
} from './auto-recuperacao.mjs';

test('trava de outro container sai; trava deste fica; perfil intacto', { skip: process.platform === 'win32' }, () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'perfil-'));
  fs.writeFileSync(path.join(dir, 'Cookies'), 'x');
  fs.symlinkSync('host-antigo-8795', path.join(dir, 'SingletonLock'));
  fs.symlinkSync('123', path.join(dir, 'SingletonCookie'));
  assert.equal(limparTravaOrfa(dir, 'host-novo'), true);
  assert.ok(!fs.readdirSync(dir).some((n) => n.startsWith('Singleton')));
  assert.ok(fs.existsSync(path.join(dir, 'Cookies')));
  fs.symlinkSync('host-novo-10', path.join(dir, 'SingletonLock'));
  assert.equal(limparTravaOrfa(dir, 'host-novo'), false);
  assert.ok(fs.readdirSync(dir).includes('SingletonLock'));
  assert.equal(limparTravaOrfa(path.join(dir, 'nao-existe'), 'host-novo'), false);
  fs.rmSync(dir, { recursive: true, force: true });
});

const LISTA = 'https://api-partner-sg.tiktokshop.com/api/v1/affiliate/partner/relation/list?partner_id=sintetico';

test('reconhece tela de login e verificação', () => {
  for (const u of [
    'https://partner.tiktokshop.com/account/login?redirect=x',
    'https://partner.tiktokshop.com/passport/web/login',
    'https://partner.tiktokshop.com/verify?type=email',
    'https://seller.tiktokshop.com/account/register',
    'https://www.tiktok.com/login/phone-or-email',
    'https://partner.tiktokshop.com/x?captcha=1',
  ]) assert.equal(classificarPagina(u), 'login', u);
});

test('página do Partner Center não é login', () => {
  assert.equal(classificarPagina('https://partner.tiktokshop.com/affiliate-cmp/creator?market=BR'), 'parceiro');
  assert.equal(classificarPagina('https://partner.tiktokshop.com/'), 'parceiro');
});

test('endereços estranhos não viram página de parceiro', () => {
  for (const u of ['http://partner.tiktokshop.com/', 'https://partner.tiktokshop.com.evil/', 'https://u:p@partner.tiktokshop.com/',
    'about:blank', '', undefined]) assert.equal(classificarPagina(u), 'desconhecida', String(u));
});

test('espera cresce e depois fica lenta', () => {
  assert.equal(proximaEspera(0), 30_000);
  assert.equal(proximaEspera(1), 120_000);
  assert.equal(proximaEspera(2), 600_000);
  assert.equal(proximaEspera(3), ESPERA_LENTA_MS);
  assert.equal(proximaEspera(-5), 30_000);
});

test('salva e lê o contexto; rejeita lixo', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'ponte-'));
  const arq = arquivoContexto(path.join(dir, 'partner-profile'), {});
  assert.equal(arq, path.join(dir, 'partner-context.json'));
  assert.equal(lerContextoSalvo(arq), null);
  assert.equal(salvarContexto(arq, { relationListUrl: 'https://evil.com/api/v1/affiliate/partner/relation/list' }), false);
  assert.equal(salvarContexto(arq, { relationListUrl: LISTA, pageUrl: 'https://partner.tiktokshop.com/affiliate-cmp/creator' }), true);
  assert.deepEqual(lerContextoSalvo(arq), { relationListUrl: LISTA, pageUrl: 'https://partner.tiktokshop.com/affiliate-cmp/creator' });
  salvarContexto(arq, { relationListUrl: LISTA, pageUrl: 'https://partner.tiktokshop.com/account/login' });
  assert.deepEqual(lerContextoSalvo(arq), { relationListUrl: LISTA, pageUrl: null });
  fs.writeFileSync(arq, '{quebrado');
  assert.equal(lerContextoSalvo(arq), null);
  fs.rmSync(dir, { recursive: true, force: true });
});
