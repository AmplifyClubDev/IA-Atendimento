/** Bounded diagnostics; no environment, browser, file, network or log access. */
const STAGES = new Set(['not_attempted', 'create_rejected', 'create_accepted', 'outcome_unknown', 'verified', 'pending_verification']);

function literal(value) {
  return String(value).replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

export function safeDiagnostic(value, { creator = '', secrets = [] } = {}, limit = 200) {
  if (typeof value !== 'string') return null;
  let text = value.slice(0, 2000).replace(/[\x00-\x1f\x7f]/g, ' ');
  for (const secret of secrets.filter((item) => typeof item === 'string' && item.length > 0)) {
    text = text.replace(new RegExp(literal(secret), 'g'), '[redacted]');
  }
  if (typeof creator === 'string' && creator.length > 0) {
    text = text.replace(new RegExp(`@?${literal(creator.replace(/^@+/, ''))}`, 'gi'), '[redacted]');
  }
  text = text.replace(/https?:\/\/\S+/gi, '[url]')
    .replace(/\bBearer\s+\S+/gi, 'Bearer [redacted]')
    .replace(/\b(?:api[_-]?key|token|cookie|authorization|password|msToken|X-Bogus|_signature)\s*[:=]\s*[^\s,;]+/gi, '[secret]')
    .replace(/[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}/gi, '[email]')
    .replace(/@[a-z0-9_.]+/gi, '[handle]')
    .replace(/\+?\d[\d ().-]{8,}\d/g, '[number]')
    .replace(/[a-z0-9_+\/-]{32,}={0,2}/gi, '[opaque]')
    .replace(/\s+/g, ' ').trim();
  return text ? text.slice(0, limit) : null;
}

function code(value, meta) {
  if (typeof value === 'number') return Number.isSafeInteger(value) ? value : null;
  if (typeof value !== 'string' || !/^(?:-?\d{1,20}|[A-Z][A-Z0-9_]{0,63})$/.test(value)) return null;
  return safeDiagnostic(value, meta, 64) === value ? value : null;
}

function reason(value) {
  return typeof value === 'string' && /^[a-z][a-z0-9_]{0,79}$/.test(value) ? value : 'ui_result_unconfirmed';
}

function providerStatus(value) {
  return Number.isInteger(value) && value >= 100 && value <= 599 ? value : null;
}

export function classifyUiOutcome(value) {
  const outcome = value && typeof value === 'object' ? value : {};
  const evidence = outcome.evidence && typeof outcome.evidence === 'object' ? outcome.evidence : {};
  const observed = evidence.provider_request_observed === true;
  const attempted = outcome.postAttempted === true;
  const target = evidence.target_verified === true;
  if (attempted && observed && target && outcome.create?.ok === true) return 'create_accepted';
  if (outcome.status === 'create_rejected' && attempted && observed && target && outcome.create?.ok === false) return 'create_rejected';
  if (outcome.status === 'not_attempted' && outcome.postAttempted === false
      && typeof evidence.ui_submit_attempted === 'boolean'
      && typeof evidence.provider_request_observed === 'boolean'
      && (evidence.ui_submit_attempted === false || evidence.create_post_blocked === true)) return 'not_attempted';
  return 'outcome_unknown';
}

export function invitationReceipt(value, meta = {}, stage = classifyUiOutcome(value)) {
  const outcome = value && typeof value === 'object' ? value : {};
  const evidence = outcome.evidence && typeof outcome.evidence === 'object' ? outcome.evidence : {};
  const create = outcome.create && typeof outcome.create === 'object' ? outcome.create : {};
  const data = create.data && typeof create.data === 'object' ? create.data : {};
  return {
    version: 1,
    method: 'ui',
    operation_id: typeof meta.operationId === 'string' && /^[a-f0-9-]{36}$/.test(meta.operationId) ? meta.operationId : null,
    observed_at: new Date().toISOString(),
    status: classifyUiOutcome(value),
    stage: STAGES.has(stage) ? stage : 'outcome_unknown',
    reason: reason(outcome.reason),
    ui_submit_attempted: evidence.ui_submit_attempted === true,
    provider_request_observed: evidence.provider_request_observed === true,
    provider_post_attempted: outcome.postAttempted === true,
    create_post_blocked: evidence.create_post_blocked === true,
    target_verified: evidence.target_verified === true,
    provider_http_status: providerStatus(create.httpStatus),
    provider_code: code(data.code, meta),
    provider_message: safeDiagnostic(data.msg ?? data.message, meta),
  };
}

export function safeCreate(value, meta = {}) {
  const stage = classifyUiOutcome(value);
  if (!['create_accepted', 'create_rejected'].includes(stage)) return undefined;
  const receipt = invitationReceipt(value, meta, stage);
  return { ok: stage === 'create_accepted', httpStatus: receipt.provider_http_status,
    httpOk: value.create?.httpOk === true,
    data: { code: receipt.provider_code, msg: receipt.provider_message } };
}

function count(value) {
  return Number.isInteger(value) && value >= 0 && value <= 100 ? value : null;
}
function strictDate(value) {
  if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return null;
  const date = new Date(value + 'T00:00:00.000Z');
  return Number.isFinite(date.getTime()) && date.toISOString().slice(0, 10) === value ? value : null;
}
function diagnosticControls(value, meta, date = false) {
  const field = value && typeof value === 'object' ? value : {};
  const identifier = value => typeof value === 'string' && /^[a-z][a-z0-9-]{0,23}$/.test(value) ? value : null;
  return {count: count(field.count), truncated: field.truncated === true,
    controls: (Array.isArray(field.controls) ? field.controls : []).slice(0, 20).map(control => ({
      tag: identifier(control?.tag), type: identifier(control?.type), role: identifier(control?.role),
      visible: control?.visible === true, checked: typeof control?.checked === 'boolean' ? control.checked : null,
      label: safeDiagnostic(control?.label, meta, 160), nearbyText: safeDiagnostic(control?.nearbyText, meta, 160),
      ancestorText: (Array.isArray(control?.ancestorText) ? control.ancestorText : []).slice(0, 3)
        .map(text => safeDiagnostic(text, meta, 300)).filter(Boolean),
      ...(date ? {placeholder: control?.placeholder === 'Please select an expiry date' ? control.placeholder : null,
        value: control?.placeholder === 'Please select an expiry date' ? strictDate(control?.value) : null,
        className: safeDiagnostic(control?.className, meta, 120), formatHint: safeDiagnostic(control?.formatHint, meta, 64),
        formatClass: ['empty', 'iso_date', 'numeric_date', 'month_name_date', 'other'].includes(control?.formatClass) ? control.formatClass : null} : {})
    }))};
}

export function safeInspection(value, meta = {}) {
  const inspected = value && typeof value === 'object' ? value : {};
  const fields = inspected.fields && typeof inspected.fields === 'object' ? inspected.fields : {};
  const evidence = inspected.evidence && typeof inspected.evidence === 'object' ? inspected.evidence : {};
  const noPost = inspected.postAttempted === false;
  const valid = inspected.ok === true && noPost && evidence.cancelled === true;
  const result = { ok: valid, status: valid ? 'inspected' : 'inspection_unconfirmed',
    postAttempted: inspected.postAttempted === true ? true : noPost ? false : null,
    reason: reason(inspected.reason), modalFound: inspected.modalFound === true, fields: {},
    formText: safeDiagnostic(inspected.formText, meta, 2000),
    submit: { count: count(inspected.submit?.count), visible: inspected.submit?.visible === true, enabled: inspected.submit?.enabled === true },
    evidence: { cancelled: evidence.cancelled === true, create_post_blocked: evidence.create_post_blocked === true,
      provider_request_observed: evidence.provider_request_observed === true,
      provider_post_attempted: inspected.postAttempted === true ? true : noPost ? false : null } };
  for (const name of ['creator', 'commission', 'terms', 'duration']) {
    const field = fields[name] && typeof fields[name] === 'object' ? fields[name] : {};
    result.fields[name] = { count: count(field.count), label: safeDiagnostic(field.label, meta, 160),
      placeholder: safeDiagnostic(field.placeholder, meta, 120) };
    result.fields[name].controls = (Array.isArray(field.controls) ? field.controls : []).slice(0, 20)
      .map((control) => ({label: safeDiagnostic(control?.label, meta, 160),
        placeholder: safeDiagnostic(control?.placeholder, meta, 120),
        min: safeDiagnostic(String(control?.min ?? ''), meta, 24),
        max: safeDiagnostic(String(control?.max ?? ''), meta, 24), checked: control?.checked === true}));
    if (name === 'commission') {
      for (const key of ['min', 'max']) result.fields[name][key] = safeDiagnostic(String(field[key] ?? ''), meta, 24);
    }
    if (name === 'terms') {
      result.fields[name].checked = field.checked === true;
      result.fields[name].semantic = safeDiagnostic(field.semantic, meta, 80);
      result.fields[name].domCandidates = diagnosticControls(field.domCandidates, meta);
    }
    if (name === 'duration') {
      result.fields[name].text = Array.isArray(field.text)
        ? field.text.slice(0, 5).map((text) => safeDiagnostic(text, meta, 160)).filter(Boolean)
        : safeDiagnostic(field.text, meta, 160);
      result.fields[name].value = safeDiagnostic(typeof field.value === 'string' ? field.value : '', meta, 40);
      result.fields[name].months = Number.isInteger(field.months) && field.months > 0 && field.months <= 24 ? field.months : null;
      result.fields[name].dateControls = diagnosticControls(field.dateControls, meta, true);
    }
  }
  const clean = (value, depth = 0) => depth > 4 ? null : typeof value === 'string' ? safeDiagnostic(value, meta, 200)
    : typeof value === 'number' || typeof value === 'boolean' || value === null ? value
    : Array.isArray(value) ? value.slice(0, 15).map(item => clean(item, depth + 1))
    : typeof value === 'object' ? Object.fromEntries(Object.entries(value).slice(0, 20).map(([k, v]) => [String(k).slice(0, 40), clean(v, depth + 1)])) : null;
  if (inspected.datePicker) result.datePicker = clean(inspected.datePicker);
  if (inspected.dryRun) result.dryRun = clean(inspected.dryRun);
  return result;
}
