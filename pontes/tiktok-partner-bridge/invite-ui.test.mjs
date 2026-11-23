import {test} from 'node:test';
import assert from 'node:assert/strict';
import {inviteViaUi, inspectInviteForm} from './invite-ui.mjs';
import {safeInspection} from './invite-receipt.mjs';

function deadline(months = 2) {
  const date = new Date(); const day = date.getUTCDate();
  date.setUTCDate(1); date.setUTCMonth(date.getUTCMonth() + months);
  date.setUTCDate(Math.min(day, new Date(Date.UTC(date.getUTCFullYear(), date.getUTCMonth() + 1, 0)).getUTCDate()));
  return String(Math.floor(date.getTime() / 1000));
}
class Locator {
  constructor(page, nodes) { this.page = page; this.nodes = nodes; }
  count() { return Promise.resolve(this.nodes.length); }
  nth(i) { return new Locator(this.page, [this.nodes[i]]); }
  isVisible() { return Promise.resolve(this.nodes[0]?.visible !== false); }
  getByRole(role, options = {}) {
    return new Locator(this.page, (this.nodes[0]?.children || []).filter(n => n.role === role
      && (!options.name || options.name.test(n.name))));
  }
  getByPlaceholder(value, options = {}) {
    assert.equal(options.exact, true);
    return new Locator(this.page, (this.nodes[0]?.children || []).filter(n => n.placeholder === value));
  }
  locator(selector) {
    if (selector === 'input[type="checkbox"]' && this.nodes[0]?.containsCheckbox) return new Locator(this.page, [this.nodes[0].containsCheckbox]);
    if (selector === 'input[type="checkbox"]') return new Locator(this.page, (this.nodes[0]?.children || []).filter(n => n.type === 'checkbox'));
    if (selector === 'label:has(input[type="checkbox"])') return new Locator(this.page, (this.nodes[0]?.children || []).filter(n => n.tag === 'label' && n.containsCheckbox));
    assert.equal(selector, 'input[type="checkbox"], [role="checkbox"], [class*="checkbox" i]');
    return new Locator(this.page, (this.nodes[0]?.children || []).filter(n => n.type === 'checkbox'
      || n.role === 'checkbox' || /checkbox/i.test(n.class || '')));
  }
  evaluate(callback) {
    const n = this.nodes[0];
    const wrapper = {getAttribute: () => null, textContent: n.nearbyText || n.label || ''};
    let parent = wrapper;
    for (const text of (n.ancestors || []).slice(0, 4)) {
      parent.parentElement = {getAttribute: () => null, textContent: text}; parent = parent.parentElement;
    }
    return Promise.resolve(callback({tagName: (n.tag || 'input').toUpperCase(), value: n.value, className: n.class || '',
      ...(typeof n.checked === 'boolean' ? {checked: n.checked} : {}),
      labels: n.label ? [{textContent: n.label}] : [],
      ownerDocument: {getElementById: () => null},
      querySelectorAll: selector => { assert.equal(selector, 'input[type="checkbox"]'); return n.containsCheckbox ? [n.containsCheckbox] : []; },
      closest: selector => { assert.equal(selector, 'label'); return n.wrapperLabel ? wrapper : null; },
      parentElement: wrapper, getAttribute: name => n[name] ?? null}));
  }
  inputValue() { return Promise.resolve(this.nodes[0].value); }
  getAttribute(name) { return Promise.resolve(this.nodes[0][name] || null); }
  isEnabled() { return Promise.resolve(!this.nodes[0].disabled); }
  fill(value) { this.page.order.push('fill_creator'); this.nodes[0].value = value; return Promise.resolve(); }
  press(key) {
    const n = this.nodes[0];
    if (key === 'Backspace') n.value = '';
    if (key === 'Tab' && this.page.resetOnBlur) n.value = '9';
    return Promise.resolve();
  }
  pressSequentially(value) { this.page.order.push('type_commission'); this.nodes[0].value += value; return Promise.resolve(); }
  innerText() { return Promise.resolve(this.nodes[0].text || ''); }
  async click() {
    const n = this.nodes[0];
    if (n.type === 'checkbox' && n.visible === false) throw Error('hidden input must never be clicked');
    if (n.action === 'open') { this.page.order.push('open'); this.page.dialog.visible = true; if (this.page.accidentalCreate) await this.page.fireCreate(); }
    if (n.action === 'cancel') { this.page.order.push('cancel'); this.page.dialog.visible = false; }
    if (n.role === 'checkbox') { this.page.order.push('agreement'); n.checked = true; this.page.commission.value = ''; }
    if (n.action === 'check-label') { this.page.order.push('agreement_label'); n.containsCheckbox.checked = true; this.page.commission.value = ''; }
    if (n.action === 'submit') {
      this.page.submitClicks++;
      if (this.page.clickThrows) throw Error('private provider exception must not escape');
      if (!this.page.noRequest) await this.page.fireCreate();
      if (this.page.duplicate) await this.page.fireCreate();
    }
  }
}
class Page {
  constructor(options = {}) {
    Object.assign(this, options); this.order = []; this.submitClicks = 0; this.allowed = 0; this.aborted = 0;
    this.routeHandlers = [];
    this.creator = {role: 'textbox', name: '', label: 'Nome de usuário do TikTok', placeholder: "Please enter the creator's user name", value: ''};
    this.commission = {role: 'spinbutton', name: '', label: 'Nova taxa de agenciamento', value: '', min: '0', max: '10'};
    this.terms = {role: 'checkbox', name: '', label: 'Li e concordo com os termos do acordo', checked: false};
    this.submit = {role: 'button', name: 'Adicionar', action: 'submit'};
    this.cancel = {role: 'button', name: 'Cancelar', action: 'cancel'};
    // The live form now requires an expiry day; the default fake models it already selected.
    this.expiry = {role: 'textbox', placeholder: 'Please select an expiry date', value: '2026-12-30'};
    this.dialog = {role: 'dialog', name: 'Adicionar novo criador', visible: false, text: 'Acordo de agenciamento por 2 meses.',
      children: [this.creator, this.commission, this.terms, ...(this.withExpiry === false ? [] : [this.expiry]), this.submit, this.cancel]};
    this.newCreator = {role: 'button', name: 'Adicionar novo criador', action: 'open'};
    this.body = {text: this.bodyText || 'Manage partnerships'};
    if (this.ambiguousCheckbox) this.dialog.children.push({...this.terms});
    if (this.unnamedCheckbox) this.terms.label = '';
    if (this.duplicateOpen) this.extraOpen = {...this.newCreator};
  }
  url() { return this.pageUrl || 'https://partner.tiktokshop.com/affiliate/creator/agency'; }
  getByRole(role, options = {}) {
    const nodes = [this.newCreator, this.dialog, ...(this.extraOpen ? [this.extraOpen] : [])];
    return new Locator(this, nodes.filter(n => n.role === role && (!options.name || options.name.test(n.name))));
  }
  getByLabel() { return new Locator(this, []); }
  locator() { return new Locator(this, [this.body]); }
  get routeHandler() { return this.routeHandlers.at(-1); }
  route(_glob, handler) { this.routeHandlers.push(handler); return Promise.resolve(); }
  unroute(_glob, handler) { this.routeHandlers = this.routeHandlers.filter(item => item !== handler); return Promise.resolve(); }
  on(_event, fn) { this.responseListener = fn; }
  off(_event, fn) { assert.equal(fn, this.responseListener); this.responseListener = null; }
  keyboard = {press: async key => { assert.equal(key, 'Escape'); this.dialog.visible = false; }};
  async fireCreate() {
    let payload = {creator_name: this.creator.value || 'pilot.creator', commission_proportion: this.commission.value || '10', due_date_second: deadline(), ...this.payload};
    if (this.reversePayload) payload = Object.fromEntries(Object.entries(payload).reverse());
    const request = {method: () => 'POST', url: () => this.requestUrl || 'https://api-partner-sg.tiktokshop.com/api/v1/affiliate/partner/relation/create',
      postDataJSON: () => { if (this.encodedBody) throw Error('encoded'); return payload; },
      postData: () => JSON.stringify(payload)};
    const route = {request: () => request, abort: async () => { this.aborted++; }, continue: async () => {
      this.allowed++;
      if (this.noResponse) return;
      const response = {request: () => this.wrongResponse ? {...request} : request,
        status: () => this.httpStatus || 200, ok: () => (this.httpStatus || 200) >= 200 && (this.httpStatus || 200) < 300,
        json: async () => this.responseData ?? {code: 0}};
      this.responseListener?.(response);
    }};
    await this.routeHandler(route);
  }
}
const params = {creator: 'pilot.creator', commission: '10', fixedMonths: 2, responseTimeoutMs: 50};

test('one approved UI request uses agreement before typing and captures its exact response', async () => {
  const page = new Page(); const result = await inviteViaUi(page, {}, params);
  assert.equal(result.status, 'create_accepted'); assert.equal(result.create.ok, true);
  assert.equal(page.submitClicks, 1); assert.equal(page.allowed, 1);
  assert(page.order.indexOf('agreement') < page.order.indexOf('type_commission'));
  assert.deepEqual([result.evidence.ui_submit_attempted, result.evidence.provider_request_observed,
    result.evidence.provider_post_attempted, result.evidence.payload_verified], [true, true, true, true]);
  assert.equal(result.evidence.cancelled, true); assert.equal(page.routeHandlers.length, 1);
});
test('Portuguese and English stable labels work without positional selectors', async () => {
  const page = new Page(); page.newCreator.name = 'Add new creator'; page.dialog.name = 'Add new creator';
  page.submit.name = 'Add'; page.cancel.name = 'Cancel'; page.terms.label = 'I have read and agree to the terms';
  assert.equal((await inviteViaUi(page, {}, params)).status, 'create_accepted');
});
test('wrong creator, commission, term or encoded body is aborted before provider', async () => {
  for (const options of [{payload: {creator_name: 'another.creator'}}, {payload: {commission_proportion: '11'}},
    {payload: {due_date_second: deadline(3)}}, {payload: {due_date_second: '123'}}, {encodedBody: true},
    {requestUrl: 'https://api-partner-sg.tiktokshop.com/api/v2/affiliate/partner/relation/create'}]) {
    const page = new Page(options); const result = await inviteViaUi(page, {}, params);
    assert.equal(result.status, 'not_attempted'); assert.equal(result.postAttempted, false);
    assert.equal(result.evidence.ui_submit_attempted, true); assert.equal(result.evidence.provider_request_observed, true);
    assert.equal(page.allowed, 0); assert.equal(page.aborted, 1); assert.equal(page.submitClicks, 1);
  }
});
test('frontend duplicate create is aborted and never gets a second provider allowance', async () => {
  const page = new Page({duplicate: true}); const result = await inviteViaUi(page, {}, params);
  assert.equal(result.status, 'create_accepted'); assert.equal(page.allowed, 1); assert.equal(page.aborted, 1);
  assert.equal(result.evidence.duplicate_posts_blocked, 1);
});
test('late same-creator retry is blocked, other creator stays untouched, new controlled call may proceed', async () => {
  const page = new Page(); const first = await inviteViaUi(page, {}, params);
  assert.equal(first.status, 'create_accepted'); assert.equal(first.evidence.creator_tombstone_installed, true);
  await page.fireCreate(); assert.equal(page.allowed, 1); assert.equal(page.aborted, 1);
  page.payload = {creator_name: 'another.creator'};
  await page.fireCreate(); assert.equal(page.allowed, 2); assert.equal(page.aborted, 1);
  page.payload = {};
  const second = await inviteViaUi(page, {}, params);
  assert.equal(second.status, 'create_accepted'); assert.equal(page.allowed, 3);
  await page.fireCreate(); assert.equal(page.allowed, 3); assert.equal(page.aborted, 2);
});
test('exact rejected other-creator body stays blocked after return without blocking unrelated manual requests', async () => {
  const page = new Page({payload: {creator_name: 'wrong.creator', commission_proportion: '10', due_date_second: deadline()}});
  const result = await inviteViaUi(page, {}, params);
  assert.equal(result.status, 'not_attempted'); assert.equal(page.allowed, 0); assert.equal(page.aborted, 1);
  assert.equal(result.evidence.rejected_payload_tombstone_installed, true);
  page.reversePayload = true;
  await page.fireCreate(); assert.equal(page.allowed, 0); assert.equal(page.aborted, 2);
  page.payload = {creator_name: 'unrelated.creator', commission_proportion: '10', due_date_second: deadline()};
  await page.fireCreate(); assert.equal(page.allowed, 1); assert.equal(page.aborted, 2);
});
test('known API rejection stays rejected without retry or success claim', async () => {
  const page = new Page({responseData: {code: 400, msg: 'Invalid parameters'}});
  const result = await inviteViaUi(page, {}, params);
  assert.equal(result.status, 'create_rejected'); assert.equal(result.create.ok, false);
  assert.equal(page.submitClicks, 1); assert.equal(page.allowed, 1);
});
test('missing or unrelated response after permitted POST stays outcome_unknown', async () => {
  for (const options of [{noResponse: true}, {wrongResponse: true}, {responseData: {unexpected: true}}]) {
    const page = new Page(options); const result = await inviteViaUi(page, {}, params);
    assert.equal(result.status, 'outcome_unknown'); assert.equal(result.postAttempted, true);
    assert.equal(page.allowed, 1); assert.equal(page.submitClicks, 1);
  }
});
test('click without observed request or a click exception stays uncertain without retry', async () => {
  for (const options of [{noRequest: true}, {clickThrows: true}]) {
    const page = new Page(options); const result = await inviteViaUi(page, {}, params);
    assert.equal(result.status, 'outcome_unknown'); assert.equal(result.postAttempted, false);
    assert.equal(result.evidence.ui_submit_attempted, true); assert.equal(page.submitClicks, 1);
    assert.equal(page.allowed, 0); assert(!JSON.stringify(result).includes('private provider exception'));
    assert.equal(result.evidence.creator_tombstone_installed, true);
    await page.fireCreate(); assert.equal(page.allowed, 0); assert.equal(page.aborted, 1);
  }
});
test('ambiguous opening or agreement and controlled commission reset fail before submit', async () => {
  for (const options of [{duplicateOpen: true}, {ambiguousCheckbox: true}, {unnamedCheckbox: true}, {resetOnBlur: true}]) {
    const page = new Page(options); const result = await inviteViaUi(page, {}, params);
    assert.equal(result.status, 'not_attempted'); assert.equal(page.submitClicks, 0); assert.equal(page.allowed, 0);
  }
});
test('CAPTCHA/login, wrong page and invalid approved conditions do not attempt submit', async () => {
  for (const options of [{bodyText: 'CAPTCHA required'}, {bodyText: 'Faça login'}, {pageUrl: 'https://other.example/'}]) {
    const page = new Page(options); assert.equal((await inviteViaUi(page, {}, params)).status, 'not_attempted');
    assert.equal(page.submitClicks, 0); assert.equal(page.allowed, 0);
  }
  for (const change of [{creator: '@pilot.creator'}, {commission: '9'}, {fixedMonths: 3}]) {
    const page = new Page(); assert.equal((await inviteViaUi(page, {}, {...params, ...change})).status, 'not_attempted');
    assert.equal(page.order.length, 0);
  }
});
test('prepareOnly fills and validates the form but cancels without any submit', async () => {
  const page = new Page(); const result = await inviteViaUi(page, {}, {...params, prepareOnly: true});
  assert.equal(result.status, 'not_attempted'); assert.equal(result.reason, 'prepared_only');
  assert.equal(result.evidence.form_state_verified, true); assert.equal(result.evidence.cancelled, true);
  assert.equal(page.allowed, 0); assert.equal(page.submitClicks, 0);
});
test('inspect reads bounded control metadata, blocks accidental create, and cancels', async () => {
  const page = new Page({accidentalCreate: true, withExpiry: false}); page.terms.label += ' https://example.invalid/secret @private';
  const result = await inspectInviteForm(page, {});
  assert.equal(result.ok, true); assert.equal(result.status, 'inspected'); assert.equal(result.postAttempted, false);
  assert.equal(result.fields.creator.count, 1); assert.equal(result.fields.duration.months, 2);
  assert.equal(result.evidence.create_post_blocked, true); assert.equal(result.evidence.blocked_create_count, 1);
  assert.equal(result.evidence.provider_request_observed, true);
  assert.equal(result.evidence.cancelled, true);
  assert.equal(page.allowed, 0); assert.equal(page.submitClicks, 0); assert.equal(page.creator.value, '');
  assert(!JSON.stringify(result).includes('example.invalid')); assert(!JSON.stringify(result).includes('@private'));
});
test('inspection never infers absent duration and reports failed modal cleanup', async () => {
  const page = new Page({withExpiry: false}); page.dialog.text = 'Termos disponíveis para consulta';
  page.dialog.children.push({...page.cancel});
  const result = await inspectInviteForm(page, {});
  assert.equal(result.fields.duration.months, null); assert.equal(result.ok, false);
  assert.equal(result.reason, 'modal_cleanup_required'); assert.equal(result.evidence.cancelled, false);
  assert.equal(page.allowed, 0); assert.equal(page.submitClicks, 0);
});

test('exact username placeholder excludes the observed second expiry textbox', async () => {
  const page = new Page({withExpiry: false});
  const expiry = {role: 'textbox', placeholder: 'Please select an expiry date', value: '2026-12-30'};
  page.dialog.children.push(expiry);
  const result = await inviteViaUi(page, {}, {...params, prepareOnly: true});
  assert.equal(result.reason, 'prepared_only'); assert.equal(page.creator.value, 'pilot.creator');
  assert.equal(expiry.value, '2026-12-30'); assert.equal(page.submitClicks, 0); assert.equal(page.allowed, 0);
  page.dialog.children.push({...page.creator});
  const ambiguous = await inviteViaUi(page, {}, {...params, prepareOnly: true});
  assert.equal(ambiguous.reason, 'creator_field_ambiguous'); assert.equal(page.submitClicks, 0);
});

test('inspector reports hidden native and custom checkbox metadata without selecting terms', async () => {
  const page = new Page({withExpiry: false}); page.dialog.children = page.dialog.children.filter(n => n !== page.terms);
  page.dialog.text = 'Acordo disponível para consulta';
  page.dialog.children.push({type: 'checkbox', tag: 'input', visible: false, checked: false,
    label: 'I agree with terms', nearbyText: 'Agreement @private person@example.invalid https://example.invalid/private'});
  page.dialog.children.push({tag: 'div', class: 'arco-checkbox', 'aria-checked': 'true',
    nearbyText: 'Authorization includes commissions', value: 'do-not-leak-input'});
  page.dialog.children.push({role: 'textbox', type: 'text', placeholder: 'Please select an expiry date', value: '2026-12-30'});
  const raw = await inspectInviteForm(page, {}); const result = safeInspection(raw);
  assert.equal(result.ok, true); assert.equal(result.fields.creator.count, 2);
  assert.equal(result.fields.terms.count, 0); assert.equal(result.fields.terms.domCandidates.count, 2);
  const [native, custom] = result.fields.terms.domCandidates.controls;
  assert.deepEqual([native.tag, native.type, native.visible, native.checked], ['input', 'checkbox', false, false]);
  assert.deepEqual([custom.tag, custom.checked], ['div', true]);
  assert.equal(result.fields.duration.months, null);
  assert.equal(result.fields.duration.dateControls.controls[0].value, '2026-12-30');
  assert(!JSON.stringify(result).includes('@private')); assert(!JSON.stringify(result).includes('person@'));
  assert(!JSON.stringify(result).includes('example.invalid')); assert(!JSON.stringify(result).includes('do-not-leak-input'));
  assert.equal(page.submitClicks, 0); assert.equal(page.allowed, 0); assert.equal(result.evidence.cancelled, true);
});

test('date diagnostics reject invalid dates or arbitrary values and candidate arrays stay bounded', async () => {
  for (const value of ['2026-02-30', '30/12/2026', 'private@example.invalid', '2026-12-30 token=secret']) {
    const page = new Page({withExpiry: false});
    page.dialog.children.push({role: 'textbox', placeholder: 'Please select an expiry date', value});
    for (let i = 0; i < 25; i++) page.dialog.children.push({tag: 'div', class: 'checkbox-icon', nearbyText: 'Terms'});
    const result = safeInspection(await inspectInviteForm(page, {}));
    assert.equal(result.ok, true); assert.equal(result.fields.duration.dateControls.controls[0].value, null);
    assert.equal(result.fields.terms.domCandidates.count, 26);
    assert.equal(result.fields.terms.domCandidates.truncated, true);
    assert.equal(result.fields.terms.domCandidates.controls.length, 20);
    assert.equal(page.submitClicks, 0); assert.equal(page.allowed, 0);
  }
});

test('inspection whitelist drops arbitrary metadata and revalidates date and secret fields', () => {
  const secret = 'private-key-value';
  const result = safeInspection({ok: true, postAttempted: false, evidence: {cancelled: true},
    fields: {terms: {domCandidates: {count: 1, controls: [{tag: 'div', type: 'token=secret',
      role: 'checkbox', checked: 'true', visible: true, label: secret,
      nearbyText: 'token=hidden @private https://example.invalid/private', html: '<private>', value: secret}]}},
      duration: {dateControls: {count: 2, controls: [
        {placeholder: 'Please select an expiry date', value: '2026-02-30'},
        {placeholder: 'Another input', value: '2026-12-30'}]}}}}, {secrets: [secret]});
  const control = result.fields.terms.domCandidates.controls[0];
  assert.equal(control.type, null); assert.equal(control.checked, null);
  assert(!('html' in control)); assert(!('value' in control));
  assert(result.fields.duration.dateControls.controls.every(item => item.value === null));
  assert(!JSON.stringify(result).includes(secret)); assert(!JSON.stringify(result).includes('@private'));
});

test('details diagnostic exposes only redacted modal and three bounded checkbox ancestors without submit', async () => {
  const page = new Page();
  page.dialog.text = 'Authorization to manage commissions. token=private-value @private a@example.invalid https://example.invalid/private ' + 'A'.repeat(2200);
  page.terms.nearbyText = '';
  page.terms.ancestors = ['Checkbox agreement description @private', 'Authorization details ' + 'B'.repeat(500), 'fourth ancestor must stay out'];
  const result = safeInspection(await inspectInviteForm(page, {}));
  assert.equal(result.ok, true); assert(result.formText.startsWith('Authorization to manage commissions.'));
  assert(result.formText.length <= 2000);
  const ancestors = result.fields.terms.domCandidates.controls[0].ancestorText;
  assert(ancestors.length <= 3); assert(ancestors.some(text => text.includes('Checkbox agreement description')));
  assert(ancestors.every(text => text.length <= 300));
  const json = JSON.stringify(result);
  for (const privateText of ['private-value', '@private', 'a@example.invalid', 'example.invalid', 'fourth ancestor']) assert(!json.includes(privateText));
  assert.equal(page.submitClicks, 0); assert.equal(page.allowed, 0); assert.equal(result.evidence.cancelled, true);
});

test('details diagnostic classifies expiry display format without returning non-ISO values', async () => {
  for (const [value, format] of [['Dec 30, 2026', 'month_name_date'], ['30/12/2026', 'numeric_date'], ['', 'empty'], ['private-value', 'other']]) {
    const page = new Page({withExpiry: false});
    page.dialog.children.push({role: 'textbox', type: 'text', class: 'arco-picker-input', 'data-format': 'MMM DD, YYYY',
      placeholder: 'Please select an expiry date', value});
    const result = safeInspection(await inspectInviteForm(page, {}));
    const date = result.fields.duration.dateControls.controls[0];
    assert.equal(date.value, null); assert.equal(date.formatClass, format);
    assert.equal(date.className, 'arco-picker-input'); assert.equal(date.formatHint, 'MMM DD, YYYY');
    if (value) assert(!JSON.stringify(result).includes(value));
    assert.equal(page.submitClicks, 0); assert.equal(page.allowed, 0);
  }
});

const confirmedTermsText = 'By clicking "Add", you agree to use and protect the creator\'s data according to the TikTok Shop Partner Center Terms of Service and TikTok Shop Partner Center Privacy Policy';
function hiddenCheckboxPage(text = confirmedTermsText) {
  const page = new Page(); Object.assign(page.terms, {type: 'checkbox', visible: false, label: ''});
  const label = {tag: 'label', visible: true, action: 'check-label', containsCheckbox: page.terms, nearbyText: text};
  page.dialog.children.push(label); return {page, label};
}

test('hidden terms fallback clicks only its proved visible label after username and verifies native checked', async () => {
  const {page} = hiddenCheckboxPage();
  const result = await inviteViaUi(page, {}, {...params, prepareOnly: true});
  assert.equal(result.reason, 'prepared_only'); assert.equal(result.evidence.form_state_verified, true);
  assert.equal(page.terms.checked, true); assert(page.order.indexOf('fill_creator') < page.order.indexOf('agreement_label'));
  assert(page.order.indexOf('agreement_label') < page.order.indexOf('type_commission'));
  assert(!page.order.includes('agreement')); assert.equal(page.submitClicks, 0); assert.equal(page.allowed, 0);
});

test('hidden terms fallback fails closed for absent semantics, duplicated input or duplicated containing label', async () => {
  for (const kind of ['no_semantics', 'duplicate_input', 'duplicate_label', 'hidden_label']) {
    const {page, label} = hiddenCheckboxPage(kind === 'no_semantics' ? 'I agree to marketing messages' : confirmedTermsText);
    if (kind === 'duplicate_input') page.dialog.children.push({...page.terms});
    if (kind === 'duplicate_label') page.dialog.children.push({...label});
    if (kind === 'hidden_label') label.visible = false;
    const result = await inviteViaUi(page, {}, {...params, prepareOnly: true});
    assert.equal(result.status, 'not_attempted'); assert.equal(page.terms.checked, false);
    assert(!page.order.includes('agreement_label')); assert(!page.order.includes('type_commission'));
    assert.equal(page.creator.value, 'pilot.creator'); assert.equal(page.submitClicks, 0); assert.equal(page.allowed, 0);
  }
});

test('unselected expiry day stops before the Add click', async () => {
  const page = new Page(); page.expiry.value = ''; page.expiry.readonly = 'readonly';
  const result = await inviteViaUi(page, {}, params);
  assert.equal(result.status, 'not_attempted'); assert.equal(page.submitClicks, 0); assert.equal(page.allowed, 0);
});

test('missing expiry day stops before the Add click', async () => {
  const page = new Page({withExpiry: false}); const result = await inviteViaUi(page, {}, params);
  assert.equal(result.status, 'not_attempted'); assert.equal(result.reason, 'expiry_field_ambiguous');
  assert.equal(page.submitClicks, 0); assert.equal(page.allowed, 0);
});
