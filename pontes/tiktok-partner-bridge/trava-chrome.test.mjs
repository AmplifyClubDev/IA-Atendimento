import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { limparTravaOrfa } from './trava-chrome.mjs';

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
  assert.equal(limparTravaOrfa(path.join(dir, 'nao-existe'), 'host-novo'), false);
  fs.rmSync(dir, { recursive: true, force: true });
});
