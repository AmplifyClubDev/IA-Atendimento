/** No sockets/browser/process environment: route runs in an injected VM. */
import assert from 'node:assert/strict';
import test from 'node:test';
import vm from 'node:vm';
import crypto from 'node:crypto';
import { readFile } from 'node:fs/promises';
import { classifyUiOutcome, invitationReceipt, safeCreate, safeDiagnostic, safeInspection } from './invite-receipt.mjs';
import * as receipts from './invite-receipt.mjs';
import { bearerAuthorized } from './console-security.mjs';

const CREATOR = 'perfil_fake';
const TOKEN = 'offline-fictional-token-ui-route-000000000000';
const OPERATION = 'b278645f-7219-4079-b39d-66cad19d020a';

test('supervisor reaches only the exact inspection path after bridge authorization and mode guard', async () => {
  const source = await readFile(new URL('./railway-supervisor.mjs', import.meta.url), 'utf8');
  const start = source.indexOf('const server=http.createServer(');
  const end = source.indexOf("server.on('upgrade'", start);
  assert.ok(start >= 0 && end > start, 'Supervisor handler source must be identifiable');
  let handler;
  const forwarded = [];
  const context = vm.createContext({ URL, mode: 'bridge', bridgeToken: TOKEN, bearerAuthorized,
    http: { createServer(callback) { handler = callback; return {}; } },
    json(res, status, body) { Object.assign(res, { status, body }); },
    proxy(req, res, port, path, bridge) { forwarded.push({ method: req.method, port, path, bridge }); res.status = 200; },
  });
  vm.runInContext(source.slice(start, end), context);
  const request = async (path, authorized = true) => {
    const res = {};
    await handler({ method: 'GET', url: path, headers: authorized ? { authorization: 'Bearer ' + TOKEN } : {} }, res);
    return res;
  };
  assert.equal((await request('/bridge/invite-ui/inspect', false)).status, 401);
  assert.equal(forwarded.length, 0);
  assert.equal((await request('/bridge/invite-ui/inspect?read=1')).status, 200);
  assert.deepEqual(forwarded, [{ method: 'GET', port: 8788, path: '/invite-ui/inspect?read=1', bridge: true }]);
  assert.equal((await request('/bridge/invite-ui/inspect/other')).status, 404);
  context.mode = 'login';
  assert.equal((await request('/bridge/invite-ui/inspect')).status, 503);
  assert.equal(forwarded.length, 1);
});

function outcome(status = 'create_accepted', extra = {}) {
  return { status, reason: 'provider_response_observed', postAttempted: true,
    create: { ok: status === 'create_accepted', httpStatus: 200, httpOk: true, data: { code: status === 'create_accepted' ? 0 : 1234, msg: 'Result observed' } },
    evidence: { ui_submit_attempted: true, provider_request_observed: true,
      provider_post_attempted: true, target_verified: true, create_post_blocked: false }, ...extra };
}

async function harness({ enabled = true, ui = outcome(), verification, inspect, throwUi = false, throwVerification = false } = {}) {
  const calls = { ui: [], api: [], resend: [], verify: [], inspect: 0, invalidate: 0, browser: 0, logs: [] };
  let handler;
  const server = { listen(_port, _host, callback) { callback(); }, address() { return { port: 8788 }; } };
  const page = { isClosed() { return false; }, on() {} };
  const browser = { pages() { return [page]; }, async newPage() { return page; }, async close() {} };
  const fakeProcess = { env: { TIKTOK_INVITE_SERVER_TOKEN: TOKEN, NODE_ENV: 'test', TIKTOK_DISABLE_WARMUP_FOR_TESTS: 'true',
    ...(enabled ? { BRIDGE_UI_INVITE_ENABLED: 'true' } : {}) }, on() {}, exit() { throw new Error('Unexpected process exit'); } };
  const context = vm.createContext({ URL, Buffer, Date, Promise, JSON, Object, Number, String, Boolean, Math, Set, Map,
    console: { error(...args) { calls.logs.push(args.join(' ')); } },
    setTimeout() { return { unref() {} }; }, clearTimeout() {},
    setInterval() { return { unref() {} }; }, clearInterval() {} });
  const apiCreate = { ok: true, httpStatus: 200, httpOk: true, data: { code: 0 } };
  const exports = {
    'node:crypto': { default: crypto }, 'node:path': { default: {} }, 'node:process': { default: fakeProcess },
    'node:http': { default: { createServer(callback) { handler = callback; return server; } } },
    'node:os': { default: { hostname() { return 'offline-host'; } } },
    './trava-chrome.mjs': { limparTravaOrfa() { return false; } },
    './tela-login.mjs': { paginaDeLogin() { return false; }, FALHAS_PARA_PEDIR_LOGIN: 2 },
    'playwright': { chromium: { async launchPersistentContext() { calls.browser++; return browser; } } },
    './invite.mjs': {
      defaults: { profileDir: '/offline-profile', headless: true, commission: '10', relatedBizTypes: '2,6', dueDays: 60 },
      computeDueDateSecond() { return 1790000000; },
      async createInvitation(_page, _ctx, payload) { calls.api.push(structuredClone(payload)); return structuredClone(apiCreate); },
      async resendExpiredInvitationViaUi(_page, payload) { calls.resend.push(structuredClone(payload)); return structuredClone(apiCreate); },
      async precheckCreator() { return { ok: true }; },
      async listRelations() { return { ok: true, items: [], pages: [] }; },
      async listCreatorGmvReport() { return { ok: true }; },
      normalizeCreator(value) { return String(value || '').replace(/^@+/, ''); },
      normalizeRelation(value) { return value; }, parseCreatorList() { return new Set(); },
      async openPartnerPageUntilReady(_page, ctx) { ctx.relationListUrl = 'https://partner.tiktokshop.com/relations'; },
      async verifyCreatorRelation(_page, _ctx, creator) {
        calls.verify.push(creator);
        if (throwVerification) throw new Error('private error token=' + TOKEN);
        return verification || { ok: true, status: 'requested', creator };
      },
    },
    './readiness-state.mjs': { evaluateReadiness() { return { ready: true, status: 'ready' }; } },
    './relations-cache-policy.mjs': { deveIgnorarCacheRelacoes() { return true; }, relacoesCompletas() { return true; },
      invalidarCacheRelacoesAposConvite() { calls.invalidate++; } },
    './invite-ui.mjs': {
      async inviteViaUi(_page, _ctx, params) { calls.ui.push(structuredClone(params)); if (throwUi) throw new Error('secret=' + TOKEN); return structuredClone(ui); },
      async inspectInviteForm() { calls.inspect++; return inspect || { ok: true, postAttempted: false, modalFound: true,
        reason: 'inspection_only_no_submit', fields: { creator: { count: 1, controls: [{ label: 'Creator username', value: CREATOR }] } },
        submit: { count: 1, visible: true, enabled: false }, evidence: { cancelled: true } }; },
    },
    './invite-receipt.mjs': receipts,
  };
  const source = await readFile(new URL('./server-quente.mjs', import.meta.url), 'utf8');
  const module = new vm.SourceTextModule(source, { context });
  await module.link(async (name) => {
    const values = exports[name]; assert.ok(values, 'Unexpected dependency: ' + name);
    return new vm.SyntheticModule(Object.keys(values), function() { for (const [key, value] of Object.entries(values)) this.setExport(key, value); }, { context });
  });
  await module.evaluate();
  return { calls, async request(method, path, body, authenticated = true) {
    let status, response; const headers = {}, listeners = {};
    const req = { method, url: path, headers: { host: 'offline.invalid', ...(authenticated ? { authorization: 'Bearer ' + TOKEN } : {}) },
      on(event, callback) { listeners[event] = callback; if (event === 'end') queueMicrotask(() => {
        if (body !== undefined) listeners.data(Buffer.from(JSON.stringify(body)));
        callback();
      }); return this; }, destroy() {} };
    const res = { writeHead(code, extra) { status = code; Object.assign(headers, extra); }, setHeader(key, value) { headers[key] = value; },
      end(raw) { response = JSON.parse(raw); } };
    await handler(req, res);
    return { status, body: response, headers };
  } };
}

const body = (extra = {}) => ({ creator: CREATOR, confirm: true, commission: '10', skip_precheck: true, force_reinvite: false, ...extra });

test('unknown UI outcome cannot fabricate a strong no-write receipt', () => {
  assert.equal(classifyUiOutcome({ status: 'not_attempted' }), 'outcome_unknown');
  assert.equal(classifyUiOutcome({ status: 'not_attempted', postAttempted: false,
    evidence: { ui_submit_attempted: true, provider_request_observed: false } }), 'outcome_unknown');
});

test('blocked create after UI click is a proved no-provider-write outcome', () => {
  const value = { status: 'not_attempted', postAttempted: false, evidence: {
    ui_submit_attempted: true, provider_request_observed: true, create_post_blocked: true } };
  assert.equal(classifyUiOutcome(value), 'not_attempted');
  const receipt = invitationReceipt(value, { operationId: OPERATION });
  assert.equal(receipt.status, 'not_attempted'); assert.equal(receipt.provider_post_attempted, false);
  assert.equal(receipt.ui_submit_attempted, true); assert.equal(receipt.create_post_blocked, true);
});

test('accepted create needs request and exact-target proof', () => {
  for (const key of ['provider_request_observed', 'target_verified']) {
    const value = outcome(); value.evidence[key] = false;
    assert.equal(classifyUiOutcome(value), 'outcome_unknown'); assert.equal(safeCreate(value), undefined);
  }
  assert.equal(classifyUiOutcome(outcome()), 'create_accepted');
});

test('diagnostics redact known secrets, target, URLs, email, phone, tokens and raw objects', () => {
  const input = TOKEN + ' creator=' + CREATOR + ' @someone https://private.invalid/?token=abc user@example.invalid +5547999999999 Bearer hidden api_key=hidden';
  const text = safeDiagnostic(input, { creator: CREATOR, secrets: [TOKEN] });
  for (const secret of [TOKEN, CREATOR, '@someone', 'https://', 'user@example.invalid', '5547999999999', 'Bearer hidden', 'api_key=hidden']) assert.ok(!text.includes(secret), secret);
  assert.ok(text.length <= 200); assert.equal(safeDiagnostic({ raw: 'not a string' }), null);
});

test('receipt is a fixed allowlist and preserves provider code without raw data', () => {
  const value = outcome('create_rejected'); value.create.data.private = TOKEN; value.private = TOKEN;
  const receipt = invitationReceipt(value, { operationId: OPERATION, creator: CREATOR, secrets: [TOKEN] });
  assert.equal(receipt.provider_code, 1234); assert.equal(receipt.provider_http_status, 200);
  assert.equal(receipt.status, 'create_rejected'); assert.ok(!JSON.stringify(receipt).includes(TOKEN));
  assert.equal(receipt.version, 1); assert.equal(receipt.operation_id, OPERATION);
});

test('inspection keeps only bounded control metadata and never creator input values', () => {
  const raw = { ok: true, postAttempted: false, modalFound: true, reason: 'inspection_only_no_submit',
    fields: { creator: { count: 1, controls: [{ label: 'Username', value: CREATOR, token: TOKEN }] },
      duration: { count: 1, text: ['2 months'], months: 2 } }, evidence: { cancelled: true }, private: TOKEN };
  const result = safeInspection(raw, { secrets: [TOKEN] });
  assert.equal(result.ok, true); assert.equal(result.fields.creator.controls[0].label, 'Username');
  assert.deepEqual(result.fields.duration.text, ['2 months']);
  assert.ok(!JSON.stringify(result).includes(TOKEN)); assert.ok(!JSON.stringify(result).includes(CREATOR));
  assert.equal(safeInspection({ ...raw, postAttempted: true }).ok, false);
  assert.equal(safeInspection({ ...raw, evidence: { cancelled: false } }).ok, false);
});

test('inspection needs authorization before feature flag or browser access', async () => {
  const app = await harness(); const result = await app.request('GET', '/invite-ui/inspect', undefined, false);
  assert.equal(result.status, 401); assert.equal(app.calls.inspect, 0); assert.equal(app.calls.browser, 0);
});

test('inspection is disabled by default and does not open the browser', async () => {
  const app = await harness({ enabled: false }); const result = await app.request('GET', '/invite-ui/inspect');
  assert.equal(result.status, 404); assert.equal(app.calls.inspect, 0); assert.equal(app.calls.browser, 0);
});

test('enabled inspection only calls inspection and returns no-store metadata', async () => {
  const app = await harness(); const result = await app.request('GET', '/invite-ui/inspect');
  assert.equal(result.status, 200); assert.equal(result.headers['cache-control'], 'no-store');
  assert.equal(result.body.postAttempted, false); assert.equal(result.body.fields.creator.controls[0].label, 'Creator username');
  assert.ok(!JSON.stringify(result.body).includes(CREATOR)); assert.equal(app.calls.inspect, 1);
  assert.equal(app.calls.ui.length + app.calls.api.length + app.calls.resend.length, 0);
});

test('legacy API default and explicit api retain the exact old payload and response', async () => {
  const app = await harness(); const first = await app.request('POST', '/invite', body());
  const second = await app.request('POST', '/invite', body({ invite_method: 'api' }));
  assert.equal(first.status, 200); assert.deepEqual(first.body, second.body);
  assert.equal('receipt' in first.body, false); assert.equal(app.calls.ui.length, 0);
  assert.deepEqual(app.calls.api[0], { creator_name: CREATOR, due_date_second: '1790000000', related_biz_types: '2,6', commission_proportion: '10', is_attached_business_profile: true });
});

test('legacy force-reinvite still uses its original adapter', async () => {
  const app = await harness(); const result = await app.request('POST', '/invite', body({ force_reinvite: true }));
  assert.equal(result.status, 200); assert.equal(app.calls.resend.length, 1); assert.equal(app.calls.ui.length, 0);
});

test('UI dispatch remains opt-in and requires explicit confirmation', async () => {
  const app = await harness(); const result = await app.request('POST', '/invite', body({ invite_method: 'ui', confirm: false }));
  assert.equal(result.status, 400); assert.equal(app.calls.ui.length, 0); assert.equal(app.calls.api.length, 0);
});

test('disabled UI returns a strong no-attempt receipt without API fallback', async () => {
  const app = await harness({ enabled: false }); const result = await app.request('POST', '/invite', body({ invite_method: 'ui' }));
  assert.equal(result.status, 422); assert.equal(result.body.status, 'invite_not_attempted');
  assert.equal(result.body.receipt.status, 'not_attempted'); assert.equal(result.body.receipt.provider_post_attempted, false);
  assert.equal(app.calls.ui.length + app.calls.api.length + app.calls.resend.length, 0);
});

test('UI fixed terms and reinvitation are checked before UI preparation', async () => {
  for (const extra of [{ commission: '9' }, { commission: 0 }, { force_reinvite: true }]) {
    const app = await harness(); const result = await app.request('POST', '/invite', body({ invite_method: 'ui', ...extra }));
    assert.equal(result.status, 422); assert.equal(result.body.status, 'invite_not_attempted'); assert.equal(app.calls.ui.length, 0);
  }
});

test('UI accepted creation is read-verified and never falls back to direct create', async () => {
  const app = await harness(); const result = await app.request('POST', '/invite', body({ invite_method: 'ui' }));
  assert.equal(result.status, 200); assert.equal(result.body.status, 'invite_sent_and_verified');
  assert.equal(result.body.create.ok, true); assert.equal(result.body.receipt.status, 'create_accepted');
  assert.equal(result.body.receipt.stage, 'verified'); assert.equal(result.body.validation.status, 'requested');
  assert.deepEqual(app.calls.ui, [{ creator: CREATOR, commission: '10', fixedMonths: 2 }]);
  assert.deepEqual(app.calls.verify, [CREATOR]); assert.equal(app.calls.invalidate, 1); assert.equal(app.calls.api.length, 0);
});

test('verification failure preserves accepted creation and returns unverified', async () => {
  for (const options of [{ throwVerification: true }, { verification: { ok: false, status: 'relation_not_found_after_invite' } },
    { verification: { ok: true, status: 'requested', creator: 'another_profile' } }]) {
    const app = await harness(options); const result = await app.request('POST', '/invite', body({ invite_method: 'ui' }));
    assert.equal(result.status, 422); assert.equal(result.body.status, 'invite_sent_unverified');
    assert.equal(result.body.create.ok, true); assert.equal(result.body.receipt.status, 'create_accepted');
    assert.equal(result.body.receipt.stage, 'pending_verification'); assert.equal(result.body.validation.ok, false);
    assert.equal(app.calls.ui.length, 1); assert.equal(app.calls.api.length, 0); assert.ok(!JSON.stringify(result.body).includes(TOKEN));
  }
});

test('observed rejection keeps sanitized provider code and does not verify or resend', async () => {
  const ui = outcome('create_rejected'); ui.create.data.msg = TOKEN + ' @' + CREATOR + ' invalid parameters';
  const app = await harness({ ui }); const result = await app.request('POST', '/invite', body({ invite_method: 'ui' }));
  assert.equal(result.status, 422); assert.equal(result.body.status, 'invite_failed'); assert.equal(result.body.create.ok, false);
  assert.equal(result.body.receipt.provider_code, 1234); assert.equal(app.calls.verify.length, 0);
  assert.equal(app.calls.ui.length, 1); assert.equal(app.calls.api.length, 0);
  assert.ok(!JSON.stringify(result.body.receipt).includes(TOKEN)); assert.ok(!JSON.stringify(result.body.receipt).includes(CREATOR));
});

test('UI throw after possible click is unknown and never a fabricated rejection', async () => {
  const app = await harness({ throwUi: true }); const result = await app.request('POST', '/invite', body({ invite_method: 'ui' }));
  assert.equal(result.status, 500); assert.equal(result.body.status, 'operation_uncertain_reconcile_same_target');
  assert.equal(result.body.receipt.status, 'outcome_unknown'); assert.equal('create' in result.body, false);
  assert.equal(app.calls.ui.length, 1); assert.equal(app.calls.api.length, 0); assert.equal(app.calls.verify.length, 0);
  assert.ok(!JSON.stringify(result.body).includes(TOKEN)); assert.ok(!app.calls.logs.join('\n').includes(TOKEN));
});

test('proved request abort after click remains not-attempted, not unknown', async () => {
  const ui = { status: 'not_attempted', reason: 'approved_payload_mismatch', postAttempted: false,
    evidence: { ui_submit_attempted: true, provider_request_observed: true, create_post_blocked: true, target_verified: false } };
  const app = await harness({ ui }); const result = await app.request('POST', '/invite', body({ invite_method: 'ui' }));
  assert.equal(result.status, 422); assert.equal(result.body.status, 'invite_not_attempted');
  assert.equal(result.body.receipt.ui_submit_attempted, true); assert.equal(result.body.receipt.provider_post_attempted, false);
  assert.equal(result.body.receipt.create_post_blocked, true); assert.equal('create' in result.body, false); assert.equal(app.calls.api.length, 0);
});

test('unproved not-attempted result after click stays unknown', async () => {
  const ui = { status: 'not_attempted', postAttempted: false,
    evidence: { ui_submit_attempted: true, provider_request_observed: false, create_post_blocked: false } };
  const app = await harness({ ui }); const result = await app.request('POST', '/invite', body({ invite_method: 'ui' }));
  assert.equal(result.status, 500); assert.equal(result.body.receipt.status, 'outcome_unknown'); assert.equal('create' in result.body, false);
});

test('API implementation block remains byte-identical to the exported baseline', async () => {
  const baseline = await readFile(new URL('../baseline/server-quente.mjs', import.meta.url), 'utf8');
  const candidate = await readFile(new URL('./server-quente.mjs', import.meta.url), 'utf8');
  const section = source => source.slice(source.indexOf('    const commission = String(body.commission || body.comissao || defaults.commission);'), source.indexOf('  } catch (erro) {', source.indexOf('    const commission = String(body.commission || body.comissao || defaults.commission);')));
  assert.equal(section(candidate), section(baseline));
});
