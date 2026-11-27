// Evidência local, sem URLs, cookies, mensagens livres ou payloads do TikTok.
import fs from 'node:fs';
import path from 'node:path';

const code = value => typeof value === 'string' && /^[a-zA-Z][a-zA-Z0-9_.:-]{0,95}$/.test(value) ? value : null;
const number = value => Number.isFinite(value) && value >= 0 ? value : null;
export function pageClass(value) {
  try {
    const u = new URL(value);
    if (u.protocol !== 'https:' || !/(^|\.)(tiktok|tiktokshop|tiktokglobalshop)\.com$/.test(u.hostname)) return 'unknown';
    const p = u.pathname.toLowerCase();
    if (/captcha/.test(p)) return 'captcha';
    if (/mfa|2fa/.test(p)) return 'mfa';
    if (/verify|verification/.test(p)) return 'verification';
    if (/login|signin|passport/.test(p)) return 'login';
    return u.hostname.endsWith('partner.tiktokshop.com') ? 'partner' : 'other_tiktok';
  } catch { return 'unknown'; }
}

export function errorClass(error) {
  const text = String(error?.message || '').toLowerCase(); // Só classifica; nunca publica a mensagem.
  if (/captcha/.test(text)) return 'captcha_required';
  if (/\bmfa\b|2fa/.test(text)) return 'mfa_required';
  if (/verification|verify/.test(text)) return 'human_verification_required';
  if (/out of memory|oom/.test(text)) return 'memory_error_unconfirmed';
  if (/crash/.test(text)) return 'browser_crashed';
  if (/closed|disconnected/.test(text)) return 'browser_disconnected';
  if (/timeout|timed out/.test(text)) return 'timeout';
  if (/net::|econn|enotfound|network/.test(text)) return 'network_error';
  return code(error?.code) || code(error?.name) || 'unknown';
}

export function resourceSnapshot(read = file => fs.readFileSync(file, 'utf8')) {
  const numeric = file => { try { const s = read(file).trim(); return /^\d+$/.test(s) ? Number(s) : null; } catch { return null; } };
  let events = {};
  try { events = Object.fromEntries(read('/sys/fs/cgroup/memory.events').trim().split('\n').map(line => line.trim().split(/\s+/))); } catch {}
  return {
    memoryBytes: numeric('/sys/fs/cgroup/memory.current') ?? numeric('/sys/fs/cgroup/memory/memory.usage_in_bytes'),
    memoryLimitBytes: numeric('/sys/fs/cgroup/memory.max') ?? numeric('/sys/fs/cgroup/memory/memory.limit_in_bytes'),
    memoryPeakBytes: numeric('/sys/fs/cgroup/memory.peak'),
    oomKillCount: /^\d+$/.test(events.oom_kill || '') ? Number(events.oom_kill) : null,
    processRssBytes: process.memoryUsage().rss,
  };
}

export function createDiagnostics({dir = '/data', prefix = 'bridge', readResources = resourceSnapshot,
                                   now = Date.now, log = record => console.error(JSON.stringify(record))} = {}) {
  const file = path.join(dir, `${prefix}-diagnostics.jsonl`);
  const stateFile = path.join(dir, `${prefix}-diagnostics-state.json`);
  let previous = readResources(), lastFailure = null, lastRecovery = null;
  // O baseline de memória não é restaurado: o cgroup pode ter sido recriado.
  try { const s = JSON.parse(fs.readFileSync(stateFile, 'utf8')); lastFailure = safe(s.lastFailure); lastRecovery = safe(s.lastRecovery); } catch {}
  function safe(input) {
    if (!input || typeof input !== 'object') return null;
    const result = {};
    for (const k of ['event', 'code', 'sourceCode', 'errorType', 'pageClass', 'reason', 'result', 'signal', 'child']) {
      if (code(input[k])) result[k] = input[k];
    }
    for (const k of ['at', 'attempt', 'httpStatus', 'apiCode', 'exitCode', 'memoryBytes', 'memoryLimitBytes',
                     'memoryPeakBytes', 'oomKillCount', 'oomKillDelta', 'processRssBytes']) {
      if (number(input[k]) !== null) result[k] = input[k];
    }
    if (input.expected === true || input.expected === false) result.expected = input.expected;
    return result;
  }
  function record(event, detail = {}) {
    const resources = readResources();
    const delta = Number.isInteger(resources.oomKillCount) && Number.isInteger(previous.oomKillCount)
      ? Math.max(0, resources.oomKillCount - previous.oomKillCount) : null;
    previous = resources;
    const evidence = safe({...detail, ...resources, event, at: now(), oomKillDelta: delta});
    if (delta > 0) {
      evidence.sourceCode = evidence.code || 'unknown';
      evidence.code = 'oom_killed'; // OOM ocorreu no cgroup, não necessariamente no Chrome.
    }
    if ((event === 'failure' && detail.expected !== true) || (event === 'browser_closed' && detail.expected !== true) || delta > 0) lastFailure = evidence;
    if (event === 'recovery') lastRecovery = evidence;
    log({event: 'bridge_diagnostic', level: event === 'failure' || delta > 0 ? 'error' : 'info',
      message: code(event) || 'diagnostic_event', diagnostic: evidence});
    try {
      if (fs.existsSync(file) && fs.statSync(file).size >= 512 * 1024) fs.renameSync(file, file + '.1');
      fs.appendFileSync(file, JSON.stringify(evidence) + '\n', {mode: 0o600});
      fs.writeFileSync(stateFile + '.tmp', JSON.stringify({lastFailure, lastRecovery}), {mode: 0o600});
      fs.renameSync(stateFile + '.tmp', stateFile);
    } catch { log({event: 'bridge_diagnostic_storage_error', code: 'storage_unavailable'}); }
    return evidence;
  }
  return {record, sample: () => record('resource_sample'),
    snapshot: () => ({resources: safe(readResources()), lastFailure, lastRecovery})};
}
