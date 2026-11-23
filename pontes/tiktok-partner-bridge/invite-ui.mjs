/** One scoped UI submission; no direct create API, retries or login changes. */
import {createHash} from 'node:crypto';
const NEW_CREATOR = /^(Adicionar novo criador|Add new creator)$/i;
const SUBMIT = /^(Adicionar|Add)$/i;
const CANCEL = /^(Cancelar|Cancel|Fechar|Close)$/i;
const CREATE_PATH = '/api/v1/affiliate/partner/relation/create';
const CREATE_ROUTE = '**/affiliate/partner/relation/create*';
const TERMS = /concord|aceit|li e|read|agree|agreement|termos|terms/i;
const CREATOR_PLACEHOLDER = "Please enter the creator's user name";
const EXPIRY_PLACEHOLDER = 'Please select an expiry date';
const pageGuards = new WeakMap();

class UiError extends Error { constructor(code) { super(code); this.code = code; } }
const safe = (value, limit = 180) => String(value ?? '').replace(/https?:\/\/\S+/gi, '[link]')
  .replace(/[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}/g, '[email]')
  .replace(/@[A-Za-z0-9_.-]+/g, '[perfil]').replace(/\b\d{8,}\b/g, '[numero]')
  .replace(/\b(?:eyJ|sk-)[A-Za-z0-9_.-]+/g, '[redigido]')
  .replace(/\b(?:token|cookie|authorization|password|secret)\s*[:=]\s*[^\s,;]+/gi, '[redigido]')
  .replace(/\s+/g, ' ').trim().slice(0, limit);

async function visible(locator) {
  const count = await locator.count();
  if (count > 20) throw new UiError('ambiguous_controls');
  const result = [];
  for (let i = 0; i < count; i++) if (await locator.nth(i).isVisible()) result.push(locator.nth(i));
  return result;
}
async function only(locator, code) {
  const items = await visible(locator);
  if (items.length !== 1) throw new UiError(code);
  return items[0];
}
async function meta(locator) {
  const value = await locator.evaluate(el => ({
    label: el.getAttribute('aria-label') || [...(el.labels || [])].map(n => n.textContent).join(' ')
      || (el.getAttribute('aria-labelledby') || '').split(/\s+/).map(id => el.ownerDocument.getElementById(id)?.textContent || '').join(' '),
    placeholder: el.getAttribute('placeholder'), min: el.getAttribute('min'), max: el.getAttribute('max'),
    checked: typeof el.checked === 'boolean' ? el.checked : el.getAttribute('aria-checked') === 'true',
  }));
  return {label: safe(value.label), placeholder: safe(value.placeholder), min: safe(value.min),
    max: safe(value.max), checked: value.checked === true};
}
function strictDate(value) {
  if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return null;
  const date = new Date(value + 'T00:00:00.000Z');
  return Number.isFinite(date.getTime()) && date.toISOString().slice(0, 10) === value ? value : null;
}
async function diagnosticControls(locator, {date = false} = {}) {
  const count = await locator.count();
  const controls = [];
  for (let i = 0; i < Math.min(count, 20); i++) {
    const item = locator.nth(i);
    const value = await item.evaluate(el => {
      const label = el.getAttribute('aria-label') || [...(el.labels || [])].map(n => n.textContent).join(' ')
        || (el.getAttribute('aria-labelledby') || '').split(/\s+/).map(id => el.ownerDocument.getElementById(id)?.textContent || '').join(' ');
      const wrapper = el.closest('label') || el.parentElement;
      const nearby = wrapper && wrapper.getAttribute('role') !== 'dialog' ? String(wrapper.textContent || '') : '';
      const ancestorText = [];
      for (let parent = el.parentElement, depth = 0; parent && depth < 3; parent = parent.parentElement, depth++) {
        if (parent.getAttribute('role') === 'dialog') break;
        ancestorText.push(String(parent.textContent || '').slice(0, 600));
      }
      return {tag: el.tagName.toLowerCase(), type: el.getAttribute('type'), role: el.getAttribute('role'),
        label: String(label).slice(0, 500), placeholder: el.getAttribute('placeholder'),
        checked: typeof el.checked === 'boolean' ? el.checked
          : ['true', 'false'].includes(el.getAttribute('aria-checked')) ? el.getAttribute('aria-checked') === 'true' : null,
        nearbyText: nearby.length <= 500 ? nearby : '', ancestorText,
        className: typeof el.className === 'string' ? el.className.slice(0, 240) : '',
        formatHint: el.getAttribute('data-format') || el.getAttribute('format') || '',
        value: el.getAttribute('placeholder') === 'Please select an expiry date' && typeof el.value === 'string' ? el.value.slice(0, 40) : null};
    });
    controls.push({tag: safe(value.tag).slice(0, 24), type: safe(value.type).slice(0, 24),
      role: safe(value.role).slice(0, 24), visible: await item.isVisible(),
      checked: typeof value.checked === 'boolean' ? value.checked : null,
      label: safe(value.label), nearbyText: safe(value.nearbyText),
      ancestorText: value.ancestorText.slice(0, 3).map(text => safe(text, 300)),
      ...(date ? {placeholder: safe(value.placeholder), value: strictDate(value.value),
        className: safe(value.className, 120), formatHint: safe(value.formatHint, 64),
        formatClass: !value.value ? 'empty' : strictDate(value.value) ? 'iso_date'
          : /^\d{1,2}[/-]\d{1,2}[/-]\d{4}$/.test(value.value) ? 'numeric_date'
          : /^(?:[A-Za-z]{3,9} \d{1,2},? \d{4}|\d{1,2} [A-Za-z]{3,9} \d{4})$/.test(value.value) ? 'month_name_date' : 'other'} : {})});
  }
  return {count, truncated: count > 20, controls};
}
async function blocked(page) {
  const url = new URL(page.url());
  if (url.protocol !== 'https:' || url.hostname !== 'partner.tiktokshop.com') throw new UiError('unexpected_partner_page');
  const body = await page.locator('body').innerText({timeout: 3000});
  if (/captcha|verify (?:that )?you are human|verifique que voc[eê] [eé] humano|security verification|verifica[çc][aã]o de seguran[çc]a|two.step verification|c[oó]digo de verifica[çc][aã]o|sign in to|fa[çc]a login/i.test(body))
    throw new UiError('human_verification_required');
}
async function open(page, proof) {
  await blocked(page);
  if ((await visible(page.getByRole('dialog'))).length) throw new UiError('existing_modal_requires_operator');
  const button = await only(page.getByRole('button', {name: NEW_CREATOR}), 'new_creator_button_ambiguous');
  proof.modal_open_attempted = true;
  await button.click();
  const dialogs = await visible(page.getByRole('dialog'));
  if (dialogs.length > 1) throw new UiError('new_creator_modal_ambiguous');
  return dialogs[0] || await only(page.getByLabel(NEW_CREATOR), 'new_creator_modal_ambiguous');
}
async function close(page, scope, proof) {
  if (!scope) return !proof.modal_open_attempted;
  if (!await scope.isVisible().catch(() => false)) return true;
  const buttons = await visible(scope.getByRole('button', {name: CANCEL}));
  if (buttons.length === 1) await buttons[0].click();
  else if (buttons.length === 0) await page.keyboard.press('Escape');
  else return false;
  return !await scope.isVisible().catch(() => false);
}
async function fields(scope, creator) {
  const commission = await only(scope.getByRole('spinbutton'), 'commission_field_ambiguous');
  const candidates = await visible(scope.getByRole('checkbox'));
  const terms = [];
  for (const item of candidates) if (TERMS.test((await meta(item)).label)) terms.push(item);
  let termsInput;
  if (terms.length === 0) {
    const labels = await visible(scope.locator('label:has(input[type="checkbox"])'));
    // Every checkbox must sit in its own label (live form: attach-profile + terms); a loose input stays ambiguous.
    if (await scope.locator('input[type="checkbox"]').count() !== labels.length) throw new UiError('agreement_field_ambiguous');
    const provenLabels = [];
    for (const candidate of labels) if (await termsLabel(candidate)) provenLabels.push(candidate);
    if (provenLabels.length !== 1) throw new UiError(labels.length ? 'agreement_semantics_unconfirmed' : 'agreement_field_ambiguous');
    const label = provenLabels[0];
    const proven = await label.evaluate(el => {
      if (el.querySelectorAll('input[type="checkbox"]').length !== 1) return false;
      for (let parent = el.parentElement, depth = 0; parent && depth < 2; parent = parent.parentElement, depth++) {
        if (parent.getAttribute('role') === 'dialog') break;
        const text = String(parent.textContent || '').replace(/\s+/g, ' ').trim();
        if (text.length <= 1500 && /\byou agree to use and protect the creator['’]s data according to the TikTok Shop Partner Center Terms of Service\b/i.test(text)) return true;
      }
      return false;
    });
    if (!proven) throw new UiError('agreement_semantics_unconfirmed');
    termsInput = label.locator('input[type="checkbox"]'); terms.push(label);
  }
  if (terms.length !== 1) throw new UiError('agreement_field_ambiguous');
  const submit = await only(scope.getByRole('button', {name: SUBMIT}), 'submit_button_ambiguous');
  return {creator, commission, terms: terms[0], termsInput, submit};
}
async function termsLabel(label) {
  return label.evaluate(el => {
    if (el.querySelectorAll('input[type="checkbox"]').length !== 1) return false;
    for (let parent = el.parentElement, depth = 0; parent && depth < 2; parent = parent.parentElement, depth++) {
      if (parent.getAttribute('role') === 'dialog') break;
      const text = String(parent.textContent || '').replace(/\s+/g, ' ').trim();
      if (text.length <= 1500 && /\byou agree to use and protect the creator['’]s data according to the TikTok Shop Partner Center Terms of Service\b/i.test(text)) return true;
    }
    return false;
  }).catch(() => false);
}
const MONTH_NAMES = ['jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec'];
const PICKER_ROOT = `(() => { const roots = [...document.querySelectorAll('[class*="picker"]')].filter(el => el.offsetParent !== null
  && /dropdown|popup|panel|container/i.test(String(el.className)) && el.querySelector('[class*="cell"]'));
  return roots[roots.length - 1] || null; })()`;
// Select the expiry day 2 calendar months ahead; the create guard still checks the payload.
async function setExpiry(page, scope, nowMs) {
  const target = new Date(calendarDeadline(nowMs) * 1000);
  const y = target.getUTCFullYear(), m = target.getUTCMonth() + 1, d = target.getUTCDate();
  const pad = n => String(n).padStart(2, '0');
  const input = await only(scope.getByPlaceholder(EXPIRY_PLACEHOLDER, {exact: true}), 'expiry_field_ambiguous');
  const done = async () => {
    const value = await input.inputValue().catch(() => '');
    const text = await scope.innerText().catch(() => '');
    return value && !/until\s*--/i.test(text) ? value : null;
  };
  let value = await done();
  if (value) return {set: true, value: safe(value, 40), method: 'preset'};
  if (await input.getAttribute('readonly') === null) {
    for (const typed of [`${y}-${pad(m)}-${pad(d)}`, `${y}/${pad(m)}/${pad(d)}`, `${pad(m)}/${pad(d)}/${y}`, `${pad(d)}/${pad(m)}/${y}`]) {
      await input.click(); await input.fill(typed); await input.press('Enter'); await page.waitForTimeout(500);
      value = await done();
      if (value) return {set: true, value: safe(value, 40), method: 'typed'};
      await input.fill('').catch(() => {});
    }
  }
  await input.click(); await page.waitForTimeout(700);
  const titled = page.locator(`[title="${y}-${pad(m)}-${pad(d)}"]`);
  if (await titled.count() === 1 && await titled.first().isVisible()) {
    await titled.first().click(); await page.waitForTimeout(500);
    value = await done();
    if (value) return {set: true, value: safe(value, 40), method: 'title_cell'};
  }
  const steps = [];
  for (let i = 0; i < 4; i++) {
    const header = await page.evaluate(`(() => { const root = ${PICKER_ROOT}; if (!root) return null;
      const head = root.querySelector('[class*="header"]');
      return String(head?.innerText || '').replace(/\\s+/g, ' ').trim().slice(0, 60); })()`);
    steps.push(safe(header ?? '', 60));
    if (!header) break;
    const lower = header.toLowerCase();
    const numeric = lower.replace(String(y), ' ');
    const monthHit = lower.includes(MONTH_NAMES[m - 1]) || new RegExp('(^|\\D)0?' + m + '(\\D|$)').test(numeric);
    if (lower.includes(String(y)) && monthHit) {
      const clicked = await page.evaluate(`(() => { const root = ${PICKER_ROOT};
        const cells = [...root.querySelectorAll('[class*="cell"]')].filter(el => el.offsetParent !== null
          && !/disabled|prev|next|last-month|outside|not-in-view/i.test(String(el.className))
          && String(el.innerText || '').trim() === '${d}' && !el.querySelector('[class*="cell"]'));
        if (cells.length !== 1) return cells.length;
        cells[0].click(); return 1; })()`);
      await page.waitForTimeout(500);
      value = await done();
      if (value) return {set: true, value: safe(value, 40), method: 'calendar', steps};
      return {set: false, method: 'calendar_cell_' + clicked, steps};
    }
    const moved = await page.evaluate(`(() => { const root = ${PICKER_ROOT};
      const names = el => String(el.className?.baseVal ?? el.className) + ' ' + (el.getAttribute('aria-label') || '');
      const buttons = [...root.querySelectorAll('[class*="header"] *')].filter(el => el.offsetParent !== null
        && /next|right/i.test(names(el)) && !/super|double|year/i.test(names(el)));
      const target = buttons.find(el => el.tagName === 'BUTTON' || el.getAttribute('role') === 'button') || buttons[0];
      if (!target) return false;
      target.click(); return true; })()`);
    if (!moved) break;
    await page.waitForTimeout(400);
  }
  await page.keyboard.press('Escape').catch(() => {});
  return {set: false, method: 'not_selected', steps};
}
async function termsChecked(controls) {
  return controls.termsInput ? await controls.termsInput.evaluate(el => el.checked === true)
    : (await meta(controls.terms)).checked;
}
function createRequest(request) {
  try { return request.method() === 'POST' && new URL(request.url()).pathname.includes('/affiliate/partner/relation/create'); }
  catch { return false; }
}
function payloadFingerprint(request) {
  const canonical = (value, depth = 0) => {
    if (depth > 12) throw new Error('shape');
    if (Array.isArray(value)) return value.map(item => canonical(item, depth + 1));
    if (value && typeof value === 'object') return Object.fromEntries(Object.keys(value).sort()
      .map(key => [key, canonical(value[key], depth + 1)]));
    return value;
  };
  try {
    const raw = JSON.stringify(canonical(request.postDataJSON()));
    if (typeof raw === 'string') return createHash('sha256').update('json\0' + raw).digest('hex');
  } catch {}
  try {
    const raw = request.postData();
    if (typeof raw === 'string') return createHash('sha256').update('raw\0' + raw).digest('hex');
  } catch {}
  return null;
}
async function reservePage(page) {
  let state = pageGuards.get(page);
  if (!state) {
    state = {active: false, creators: new Set(), rejectedPayloads: new Set(), installed: false};
    state.guard = async route => {
      let creator;
      try { creator = route.request().postDataJSON()?.creator_name; } catch {}
      const key = typeof creator === 'string' ? creator.trim().replace(/^@+/, '').toLowerCase() : null;
      if (createRequest(route.request()) && ((key && state.creators.has(key))
          || state.rejectedPayloads.has(payloadFingerprint(route.request())))) return route.abort();
      return route.continue();
    };
    pageGuards.set(page, state);
  }
  if (state.active) throw new UiError('ui_operation_already_active');
  state.active = true;
  try {
    if (!state.installed) { await page.route(CREATE_ROUTE, state.guard); state.installed = true; }
    return state;
  } catch (error) { state.active = false; throw error; }
}
function calendarDeadline(now) {
  const date = new Date(now);
  const day = date.getUTCDate();
  date.setUTCDate(1); date.setUTCMonth(date.getUTCMonth() + 2);
  const last = new Date(Date.UTC(date.getUTCFullYear(), date.getUTCMonth() + 1, 0)).getUTCDate();
  date.setUTCDate(Math.min(day, last));
  return Math.floor(date.getTime() / 1000);
}
function validPayload(request, creator, commission, now) {
  try {
    const url = new URL(request.url());
    if (url.protocol !== 'https:' || url.pathname !== CREATE_PATH
        || !/^api-partner-(?:sg|us)\.tiktokshop\.com$/.test(url.hostname)) return false;
    const payload = request.postDataJSON();
    if (!payload || Array.isArray(payload) || payload.creator_name !== creator) return false;
    if (!['string', 'number'].includes(typeof payload.commission_proportion)
        || String(payload.commission_proportion).trim() === '' || Number(payload.commission_proportion) !== commission) return false;
    if (!['string', 'number'].includes(typeof payload.due_date_second)
        || !/^\d{10}$/.test(String(payload.due_date_second))) return false;
    // The picker selects a calendar day, not a second: accept that same deadline day.
    return Math.abs(Number(payload.due_date_second) - calendarDeadline(now)) <= 36 * 3600;
  } catch { return false; }
}
function responseData(value) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return {};
  const result = {};
  if (typeof value.code === 'number' || (typeof value.code === 'string' && /^[A-Za-z0-9_-]{1,32}$/.test(value.code))) result.code = value.code;
  if (typeof value.success === 'boolean') result.success = value.success;
  const message = value.msg ?? value.message;
  if (typeof message === 'string') result.msg = /token|cookie|secret|authorization|signature|csrf|bearer/i.test(message)
    ? '[mensagem de autenticação redigida]' : safe(message);
  return result;
}
function evidence() {
  return {ui_submit_attempted: false, submit_clicked: false, provider_request_observed: false,
    provider_post_attempted: false, target_verified: false, payload_verified: false,
    create_post_blocked: false, blocked_create_count: 0, duplicate_posts_blocked: 0, cancelled: false};
}


// Read-only shape of the expiry date picker: opens it, records structure, closes it.
async function probeDatePicker(page, scope) {
  const out = {opened: false, panels: []};
  try {
    const input = await only(scope.getByPlaceholder(EXPIRY_PLACEHOLDER, {exact: true}), 'expiry_field_ambiguous');
    out.readonly = await input.getAttribute('readonly');
    await input.click(); await page.waitForTimeout(800); out.opened = true;
    out.panels = await page.evaluate(() => {
      const pick = el => ({tag: el.tagName.toLowerCase(), cls: String(el.className?.baseVal ?? el.className ?? '').slice(0, 120),
        title: el.getAttribute('title'), aria: el.getAttribute('aria-label'), text: (el.innerText || '').replace(/\s+/g, ' ').trim().slice(0, 40)});
      const roots = [...document.querySelectorAll('[class*="picker"]')].filter(el => /dropdown|panel|popup|container/i.test(String(el.className)) && el.offsetParent !== null);
      return roots.slice(0, 3).map(root => ({root: pick(root),
        header: [...root.querySelectorAll('[class*="header"] *')].slice(0, 12).map(pick),
        cells: [...root.querySelectorAll('[class*="cell"]')].slice(0, 10).map(pick),
        inputs: [...root.querySelectorAll('input')].slice(0, 3).map(pick)}));
    });
    out.inputValue = await input.inputValue().catch(() => null);
    await page.keyboard.press('Escape');
  } catch (error) { out.error = error instanceof UiError ? error.code : String(error?.message || error).slice(0, 120); }
  return out;
}
export async function inspectInviteForm(page, _ctx, {creator = null, fill = false} = {}) {
  const proof = evidence(); let scope, routed = false, lease;
  const result = {ok: false, status: 'not_attempted', postAttempted: false, reason: 'inspection_unavailable',
    modalFound: false, fields: {}, submit: {count: 0, visible: false, enabled: false}, evidence: proof};
  const guard = async route => {
    if (createRequest(route.request())) {
      proof.provider_request_observed = true; proof.create_post_blocked = true;
      proof.blocked_create_count++; await route.abort();
    }
    else await route.continue();
  };
  try {
    lease = await reservePage(page);
    await page.route(CREATE_ROUTE, guard); routed = true;
    scope = await open(page, proof); result.modalFound = true;
    for (const [name, role] of [['creator', 'textbox'], ['commission', 'spinbutton'], ['terms', 'checkbox']]) {
      const items = await visible(scope.getByRole(role));
      result.fields[name] = {count: items.length, controls: await Promise.all(items.map(meta))};
    }
    const text = await scope.innerText();
    result.formText = safe(text, 2000);
    const durations = [...text.matchAll(/.{0,35}\b\d{1,2}\s*(?:meses?|months?)\b.{0,35}/gi)].map(m => safe(m[0])).slice(0, 5);
    result.fields.duration = {count: durations.length, text: durations, months: durations.length === 1 && /\b2\s*(?:meses?|months?)\b/i.test(durations[0]) ? 2 : null};
    result.fields.terms.domCandidates = await diagnosticControls(scope.locator('input[type="checkbox"], [role="checkbox"], [class*="checkbox" i]'));
    result.fields.duration.dateControls = await diagnosticControls(scope.getByPlaceholder(EXPIRY_PLACEHOLDER, {exact: true}), {date: true});
    const submits = await visible(scope.getByRole('button', {name: SUBMIT}));
    result.submit = {count: submits.length, visible: submits.length === 1, enabled: submits.length === 1 && await submits[0].isEnabled()};
    if (fill && typeof creator === 'string' && /^[A-Za-z0-9_.]{2,64}$/.test(creator)) {
      // Dry run: fill every field the real flow fills, never click "Add"; the route guard aborts any create.
      const run = {};
      const creatorControl = await only(scope.getByPlaceholder(CREATOR_PLACEHOLDER, {exact: true}), 'creator_field_ambiguous');
      await creatorControl.fill(creator); await page.waitForTimeout(1500);
      const controls = await fields(scope, creatorControl);
      if (!await termsChecked(controls)) await controls.terms.click();
      run.termsChecked = await termsChecked(controls);
      await controls.commission.click();
      await controls.commission.press(process.platform === 'darwin' ? 'Meta+A' : 'Control+A');
      await controls.commission.press('Backspace');
      await controls.commission.pressSequentially('10', {delay: 100});
      await controls.commission.press('Tab');
      run.commission = await controls.commission.inputValue();
      run.expiry = await setExpiry(page, scope, Date.now());
      run.until = safe((String(await scope.innerText()).match(/until[^.]{0,40}/i) || [''])[0], 80);
      run.submitEnabled = await controls.submit.isEnabled();
      result.dryRun = run;
    } else {
      result.datePicker = await probeDatePicker(page, scope);
    }
    result.ok = true; result.status = 'inspected'; result.reason = 'inspection_only_no_submit';
  } catch (error) { result.reason = error instanceof UiError ? error.code : 'inspection_unavailable'; }
  finally {
    proof.cancelled = await close(page, scope, proof).catch(() => false);
    if (routed) await page.unroute(CREATE_ROUTE, guard);
    if (lease) lease.active = false;
  }
  if (!proof.cancelled) { result.ok = false; result.reason = 'modal_cleanup_required'; }
  return result;
}

export async function inviteViaUi(page, _ctx, {creator, commission, fixedMonths, prepareOnly = false, responseTimeoutMs = 30000} = {}) {
  const proof = evidence(); let scope, allowedRequest, response, timer, listener, routed = false, lease;
  let blockedReason, matchedResponse;
  const result = (status, reason, create) => ({status, reason, postAttempted: proof.provider_post_attempted,
    ...(create ? {create} : {}), evidence: proof});
  if (typeof creator !== 'string' || !/^[A-Za-z0-9_.]{2,64}$/.test(creator) || creator.startsWith('@')
      || !['string', 'number'].includes(typeof commission) || String(commission).trim() === ''
      || Number(commission) !== 10 || fixedMonths !== 2 || typeof prepareOnly !== 'boolean')
    return result('not_attempted', 'approved_target_and_conditions_required');
  const guard = async route => {
    const request = route.request();
    if (!createRequest(request)) return route.continue();
    proof.provider_request_observed = true;
    if (prepareOnly || allowedRequest || proof.provider_post_attempted || blockedReason) {
      proof.duplicate_posts_blocked++; blockedReason ||= prepareOnly ? 'prepared_only' : 'duplicate_create_blocked';
      proof.create_post_blocked = true; proof.blocked_create_count++;
      const fingerprint = payloadFingerprint(request);
      if (fingerprint) lease.rejectedPayloads.add(fingerprint);
      return route.abort();
    }
    if (!proof.ui_submit_attempted || !validPayload(request, creator, 10, Date.now())) {
      blockedReason = 'ui_payload_mismatch'; proof.create_post_blocked = true; proof.blocked_create_count++;
      const fingerprint = payloadFingerprint(request);
      if (fingerprint) { lease.rejectedPayloads.add(fingerprint); proof.rejected_payload_tombstone_installed = true; }
      return route.abort();
    }
    allowedRequest = request; proof.target_verified = true; proof.payload_verified = true;
    proof.provider_post_attempted = true;
    await route.continue();
  };
  try {
    // Only a new controlled call may supersede this page's previous creator fence.
    // The server/client must revalidate consent and current relations first.
    lease = await reservePage(page);
    if (lease.creators.size >= 256 && !lease.creators.has(creator.toLowerCase()))
      throw new UiError('ui_page_guard_capacity');
    await page.route(CREATE_ROUTE, guard); routed = true;
    scope = await open(page, proof);
    const creatorControl = await only(scope.getByPlaceholder(CREATOR_PLACEHOLDER, {exact: true}), 'creator_field_ambiguous');
    await creatorControl.fill(creator);
    // Same settle time as the verified dry run: the profile card and expiry day load after the username.
    if (typeof page.waitForTimeout === 'function') await page.waitForTimeout(1500);
    const controls = await fields(scope, creatorControl);
    if (!await termsChecked(controls)) await controls.terms.click();
    if (!await termsChecked(controls)) throw new UiError('agreement_not_checked');
    await controls.commission.click();
    await controls.commission.press(process.platform === 'darwin' ? 'Meta+A' : 'Control+A');
    await controls.commission.press('Backspace');
    await controls.commission.pressSequentially('10', {delay: 100});
    await controls.commission.press('Tab');
    const expiry = await setExpiry(page, scope, Date.now()); proof.expiry_method = expiry.method;
    if (!expiry.set) throw new UiError('expiry_date_not_set');
    proof.expiry_set = true;
    await blocked(page);
    if (await controls.creator.inputValue() !== creator || Number(await controls.commission.inputValue()) !== 10
        || !await termsChecked(controls) || await controls.commission.getAttribute('aria-invalid') === 'true'
        || !await controls.submit.isEnabled()) throw new UiError('form_state_not_confirmed');
    proof.form_state_verified = true;
    if (prepareOnly) return result('not_attempted', 'prepared_only');
    const responsePromise = new Promise(resolve => { matchedResponse = resolve; });
    listener = value => { if (allowedRequest && value.request() === allowedRequest) matchedResponse(value); };
    page.on('response', listener);
    proof.ui_submit_attempted = true;
    await controls.submit.click(); proof.submit_clicked = true;
    if (blockedReason && !proof.provider_post_attempted) return result('not_attempted', blockedReason);
    response = await Promise.race([responsePromise, new Promise(resolve => { timer = setTimeout(() => resolve(null), Math.max(50, Math.min(Number(responseTimeoutMs) || 30000, 30000))); })]);
    if (!response) return result('outcome_unknown', 'create_response_unconfirmed');
    const httpStatus = response.status();
    const data = responseData(await response.json().catch(() => null));
    const accepted = response.ok() && (data.code === 0 || data.success === true);
    if (accepted) return result('create_accepted', 'ui_create_accepted', {ok: true, httpStatus, data});
    if (typeof data.code !== 'undefined' || data.success === false)
      return result('create_rejected', 'ui_create_rejected', {ok: false, httpStatus, data});
    return result('outcome_unknown', 'create_response_unconfirmed', {ok: null, httpStatus, data});
  } catch (error) {
    return result(proof.ui_submit_attempted ? 'outcome_unknown' : 'not_attempted',
      error instanceof UiError ? error.code : 'ui_operation_unconfirmed');
  } finally {
    clearTimeout(timer); if (listener) page.off('response', listener);
    proof.cancelled = await close(page, scope, proof).catch(() => false);
    if (lease && proof.ui_submit_attempted) {
      lease.creators.add(creator.toLowerCase()); proof.creator_tombstone_installed = true;
    }
    if (routed) await page.unroute(CREATE_ROUTE, guard);
    if (lease) lease.active = false;
  }
}
