import {test} from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import vm from 'node:vm';
import {EventEmitter} from 'node:events';
import {createDiagnostics, resourceSnapshot, pageClass, errorClass} from './diagnostico.mjs';

test('OOM requires a cgroup counter increase, not high memory or SIGKILL alone', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'bridge-diag-'));
  try {
    let oom = 3;
    const d = createDiagnostics({dir, log: () => {}, readResources: () => ({memoryBytes: 3999, memoryLimitBytes: 4000, oomKillCount: oom})});
    d.record('failure', {code: 'child_exited', signal: 'SIGKILL'});
    assert.equal(d.snapshot().lastFailure.code, 'child_exited');
    oom++;
    d.sample();
    assert.equal(d.snapshot().lastFailure.code, 'oom_killed');
    assert.equal(d.snapshot().lastFailure.oomKillDelta, 1);
    const restarted = createDiagnostics({dir, log: () => {}, readResources: () => ({oomKillCount: 0})});
    assert.equal(restarted.snapshot().lastFailure.code, 'oom_killed');
    restarted.record('failure', {code: 'timeout'});
    assert.equal(restarted.snapshot().lastFailure.code, 'timeout');
  } finally { fs.rmSync(dir, {recursive: true, force: true}); }
});

test('evidence excludes cookies, URLs and raw errors; rotation is bounded', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'bridge-diag-'));
  const logs = [];
  try {
    const d = createDiagnostics({dir, log: x => logs.push(x), readResources: () => ({})});
    const secret = 'https://partner.tiktokshop.com/login?token=secret';
    d.record('failure', {code: secret, message: secret, cookie: secret, pageClass: pageClass(secret)});
    d.record('recovery', {result: 'failed', code: 'captcha_required'});
    assert.equal(logs[0].level, 'error');
    assert.equal(logs[1].level, 'info');
    assert.equal(d.snapshot().lastRecovery.code, 'captcha_required');
    assert(!JSON.stringify(logs).includes('token='));
    assert(!fs.readFileSync(path.join(dir, 'bridge-diagnostics.jsonl'), 'utf8').includes('token='));
    fs.writeFileSync(path.join(dir, 'bridge-diagnostics.jsonl'), 'x'.repeat(512 * 1024));
    d.sample();
    assert(fs.existsSync(path.join(dir, 'bridge-diagnostics.jsonl.1')));
  } finally { fs.rmSync(dir, {recursive: true, force: true}); }
});

test('cgroup metrics cover Chrome descendants and tolerate unavailable files', () => {
  const files = {'/sys/fs/cgroup/memory.current': '200', '/sys/fs/cgroup/memory.max': '400',
    '/sys/fs/cgroup/memory.events': 'oom 2\noom_kill 1\n'};
  const snapshot = resourceSnapshot(file => {if (!(file in files)) throw new Error('missing'); return files[file];});
  assert.equal(snapshot.memoryBytes, 200);
  assert.equal(snapshot.memoryLimitBytes, 400);
  assert.equal(snapshot.oomKillCount, 1);
  assert.equal(resourceSnapshot(() => {throw new Error('missing');}).memoryBytes, null);
});

test('classifies errors without publishing raw data; memory text is not OOM proof', () => {
  assert.equal(pageClass('https://partner.tiktokshop.com/captcha?token=secret'), 'captcha');
  assert.equal(pageClass('https://partner.tiktokshop.com/mfa'), 'mfa');
  assert.equal(pageClass('https://evil.example/login'), 'unknown');
  assert.equal(errorClass(new Error('browser closed secret')), 'browser_disconnected');
  assert.equal(errorClass(new Error('net::ERR_CONNECTION_RESET secret')), 'network_error');
  assert.equal(errorClass(new Error('out of memory')), 'memory_error_unconfirmed');
});

test('actual page hooks distinguish crash from expected closure without navigating', () => {
  const source = fs.readFileSync(new URL('./server-quente.mjs', import.meta.url), 'utf8');
  const hooks = source.slice(source.indexOf('const expectedClosures'), source.indexOf("diagnostics.record('startup')"));
  const events = [];
  const sandbox = {diagnostics: {record: (event, detail) => events.push({event, ...detail})}, pageClass};
  vm.createContext(sandbox);
  vm.runInContext(hooks, sandbox);
  const context = {};
  const page = new EventEmitter();
  page.url = () => 'https://partner.tiktokshop.com/login?token=secret';
  page.context = () => context;
  sandbox.page = page;
  vm.runInContext('observePage(page); observePage(page)', sandbox);
  page.emit('crash');
  assert.equal(events.length, 1);
  assert.equal(events[0].code, 'browser_crashed');
  assert.equal(events[0].pageClass, 'login');
  sandbox.context = context;
  vm.runInContext('expectedClosures.add(context)', sandbox);
  page.emit('close');
  assert.equal(events[1].expected, true);
  assert(!JSON.stringify(events).includes('token='));
});
