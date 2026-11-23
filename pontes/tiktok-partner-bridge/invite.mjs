#!/usr/bin/env node
import { chromium } from 'playwright';
import fs from 'node:fs';
import path from 'node:path';
import process from 'node:process';

const here = path.dirname(new URL(import.meta.url).pathname);
loadDotEnv(path.join(here, '.env'));

export const defaults = {
  partnerUrl: process.env.TIKTOK_PARTNER_URL || 'https://partner.tiktokshop.com/',
  apiBase: stripTrailingSlash(process.env.TIKTOK_PARTNER_API_BASE || 'https://api-partner-sg.tiktokshop.com'),
  profileDir: resolveFromHere(process.env.TIKTOK_PLAYWRIGHT_PROFILE_DIR || '../../.playwright/tiktok-partner-profile'),
  headless: parseBool(process.env.TIKTOK_HEADLESS, false),
  commission: process.env.TIKTOK_DEFAULT_COMMISSION || '10',
  relatedBizTypes: process.env.TIKTOK_DEFAULT_RELATED_BIZ_TYPES || '2,6',
  dueDays: Number(process.env.TIKTOK_DEFAULT_DUE_DAYS || 60),
  customReportUrl: process.env.TIKTOK_CUSTOM_REPORT_URL || 'https://partner.tiktokshop.com/compass/custom-report',
};

const args = parseArgs(process.argv.slice(2));
const command = args._[0] || 'help';

// Só executa o CLI quando este arquivo é o ponto de entrada. Importado como
// módulo (pelo server de contexto quente), nada dispara — a lógica do Partner
// Center passa a ser reaproveitada em vez de duplicada, que é o único jeito
// seguro: ela é a parte mais crítica e menos testada do sistema.
const executadoDireto = (() => {
  try {
    const entrada = process.argv[1] ? new URL(`file://${process.argv[1]}`).pathname : '';
    return here === path.dirname(entrada) && path.basename(entrada) === 'invite.mjs';
  } catch {
    return false;
  }
})();

if (executadoDireto) {
  main().catch((error) => {
    emit({
      ok: false,
      status: 'fatal_error',
      error: serializeError(error),
    });
    process.exitCode = 1;
  });
}

async function main() {
  if (command === 'help' || args.help) {
    printHelp();
    return;
  }

  if (command === 'login') {
    await login();
    return;
  }

  if (command === 'precheck') {
    const creator = normalizeCreator(requiredArg(args.creator, 'creator'));
    const result = await withPartnerPage(async (page, partnerContext) => {
      const precheck = await precheckCreator(page, partnerContext, creator);
      return { ok: precheck.ok, status: precheck.ok ? 'precheck_ok' : 'precheck_failed', creator, precheck };
    });
    emit(result);
    if (!result.ok) process.exitCode = 2;
    return;
  }

  if (command === 'relations') {
    const status = String(args.status || '1');
    const pageSize = Number(args.pageSize || 100);
    const pageLimit = Number(args.pageLimit || 5);
    const creators = parseCreatorList(args.creator || args.creators || args.users);
    const result = await withPartnerPage(async (page, partnerContext) => {
      const relations = await listRelations(page, partnerContext, {
        status,
        pageSize,
        pageLimit,
        creator: creators.size === 1 ? [...creators][0] : '',
      });
      let items = relations.items.map((relation) => normalizeRelation(relation));
      if (creators.size) {
        items = items.filter((item) => creators.has(normalizeCreator(item.arroba).toLowerCase()));
      }
      return {
        ok: relations.ok,
        status: relations.ok ? 'relations_listed' : 'relations_failed',
        query: { status, pageSize, pageLimit, creators: [...creators] },
        count: items.length,
        totalNum: relations.totalNum,
        statusCount: relations.statusCount,
        completo: relations.totalNum == null || relations.items.length >= relations.totalNum,
        items,
        pages: relations.pages,
        error: relations.error,
      };
    });
    emit(result);
    if (!result.ok) process.exitCode = 2;
    return;
  }

  if (command === 'gmv-report') {
    const period = getReportPeriod({
      startDate: args.startDate || args.start,
      endDateExclusive: args.endDateExclusive || args.endExclusive,
    });
    const pageSize = Number(args.pageSize || 100);
    const pageLimit = Number(args.pageLimit || 50);
    const result = await withPartnerPage(async (page, partnerContext) => {
      const report = await listCreatorGmvReport(page, partnerContext, { ...period, pageSize, pageLimit });
      return {
        ok: report.ok,
        status: report.ok ? 'gmv_report_listed' : 'gmv_report_failed',
        query: { ...period, pageSize, pageLimit },
        ...report,
      };
    }, { url: defaults.customReportUrl, waitForReportContext: true });
    emit(result);
    if (!result.ok) process.exitCode = 2;
    return;
  }

  if (command === 'invite') {
    const creator = normalizeCreator(requiredArg(args.creator, 'creator'));
    const commission = String(args.commission || defaults.commission);
    const relatedBizTypes = String(args.relatedBizTypes || defaults.relatedBizTypes);
    const requestedDueDateSecond = args.dueDateSecond;
    const yes = Boolean(args.yes);
    const skipPrecheck = parseBool(args.skipPrecheck, parseBool(process.env.TIKTOK_INVITE_SKIP_PRECHECK, true));
    const verifyAttempts = Number(args.verifyAttempts || process.env.TIKTOK_INVITE_VERIFY_ATTEMPTS || 3);
    const verifyDelayMs = Number(args.verifyDelayMs || process.env.TIKTOK_INVITE_VERIFY_DELAY_MS || 3000);
    const forceReinvite = parseBool(args.forceReinvite, false);

    const result = await withPartnerPage(async (page, partnerContext) => {
      const precheck = skipPrecheck
        ? { ok: true, status: 'skipped', reason: 'technical TikTok requirements already confirmed by acquisition funnel' }
        : await precheckCreator(page, partnerContext, creator);
      if (precheck.ok === false) {
        return { ok: false, status: 'precheck_failed', creator, precheck };
      }

      const dueDateSecond = String(requestedDueDateSecond || computeDueDateSecond({
        days: Number(args.dueDays || defaults.dueDays),
        fixedMonths: skipPrecheck ? Number(args.fixedMonths || 2) : Number(precheck.data?.data?.bind_duration_fixed_month),
      }));

      const payload = {
        creator_name: creator,
        due_date_second: dueDateSecond,
        related_biz_types: relatedBizTypes,
        commission_proportion: commission,
        is_attached_business_profile: parseBool(args.attachedBusinessProfile, true),
      };

      if (!yes) {
        return {
          ok: true,
          status: 'dry_run',
          creator,
          precheck,
          payload,
          validation: {
            status: 'not_run',
            reason: 'Dry run does not send the invitation.',
          },
          message: 'Dry run only. Add --yes to send the invitation.',
        };
      }

      const create = forceReinvite
        ? await resendExpiredInvitationViaUi(page, payload)
        : await createInvitation(page, partnerContext, payload);
      if (!create.ok) {
        return {
          ok: false,
          status: 'invite_failed',
          creator,
          precheck,
          create,
        };
      }

      const validation = await verifyCreatorRelation(page, partnerContext, creator, {
        attempts: verifyAttempts,
        delayMs: verifyDelayMs,
      });
      return {
        ok: validation.ok,
        status: validation.ok ? 'invite_sent_and_verified' : 'invite_sent_unverified',
        creator,
        precheck,
        create,
        validation,
      };
    });

    emit(result);
    if (!result.ok) process.exitCode = 2;
    return;
  }

  throw new Error(`Unknown command: ${command}`);
}

async function login() {
  fs.mkdirSync(defaults.profileDir, { recursive: true });
  const context = await chromium.launchPersistentContext(defaults.profileDir, {
    headless: false,
    viewport: { width: 1440, height: 1000 },
  });
  const page = context.pages()[0] || await context.newPage();
  await page.goto(defaults.partnerUrl, { waitUntil: 'domcontentloaded', timeout: 60000 });

  console.error('Login window opened.');
  if (args.hold) {
    console.error('Hold mode enabled. Log in through noVNC, then tell the agent to stop the login browser.');
    await new Promise(() => {});
  } else {
    console.error('After logging into TikTok Partner Center, return here and press Enter.');
    await waitForEnter();
  }
  await context.close();
  emit({ ok: true, status: 'login_saved', profileDir: defaults.profileDir });
}

async function withPartnerPage(fn, options = {}) {
  fs.mkdirSync(defaults.profileDir, { recursive: true });
  const context = await chromium.launchPersistentContext(defaults.profileDir, {
    headless: args.headless === undefined ? defaults.headless : parseBool(args.headless, defaults.headless),
    viewport: { width: 1440, height: 1000 },
  });

  // Reuse the persistent Partner tab when available. TikTok's logged-in shell
  // can load empty in a brand-new tab, while the saved tab keeps the session
  // bootstrapped enough to trigger relation/list.
  const page = context.pages().find((candidate) => !candidate.isClosed()) || await context.newPage();
  const partnerContext = { relationListUrl: null, reportDimensionListUrl: null };
  const capturePartnerContext = (requestOrResponse) => {
    const url = requestOrResponse.url();
    if (url.includes('/api/v1/affiliate/partner/relation/list')) {
      partnerContext.relationListUrl ||= url;
    }
    if (url.includes('/api/v1/insights/partner/report/valid/dimension/list')) {
      partnerContext.reportDimensionListUrl ||= url;
    }
  };
  page.on('request', capturePartnerContext);
  page.on('response', capturePartnerContext);

  try {
    await openPartnerPageUntilReady(page, partnerContext, options);
    return await fn(page, partnerContext);
  } catch (error) {
    const screenshot = await saveFailureScreenshot(page).catch(() => null);
    return {
      ok: false,
      status: 'browser_error',
      error: serializeError(error),
      screenshot,
    };
  } finally {
    await context.close();
  }
}

export async function openPartnerPageUntilReady(page, partnerContext, options = {}) {
  const url = options.url || defaults.partnerUrl;
  const maxAttempts = Number(options.loadAttempts || 3);
  const waitsForReport = Boolean(options.waitForReportContext);
  let lastBodyText = '';

  for (let attempt = 1; attempt <= maxAttempts; attempt += 1) {
    const contextReady = waitForPartnerContext(page, partnerContext, waitsForReport);
    await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 60000 });
    await page.waitForLoadState('networkidle', { timeout: 20000 }).catch(() => {});
    await contextReady;

    lastBodyText = await page.locator('body').innerText({ timeout: 5000 }).catch(() => '');
    const hasEnglishInviteButton = await page.getByRole('button', { name: /Add New Creator/i })
      .count()
      .then((count) => count > 0)
      .catch(() => false);
    const hasPortugueseInviteButton = await page.getByRole('button', { name: /Adicionar novo criador/i })
      .count()
      .then((count) => count > 0)
      .catch(() => false);

    if (waitsForReport && partnerContext.reportDimensionListUrl) return;
    if (!waitsForReport && partnerContext.relationListUrl) return;
    if (!waitsForReport && (hasEnglishInviteButton || hasPortugueseInviteButton)) {
      await waitForPartnerContext(page, partnerContext, false);
      if (partnerContext.relationListUrl) return;
    }

    if (attempt < maxAttempts) {
      await page.waitForTimeout(1500 * attempt);
    }
  }

  const contextName = waitsForReport ? 'custom report' : 'relation/list';
  const bodyHint = lastBodyText.trim().slice(0, 120) || 'empty page body';
  throw new Error(`Could not capture TikTok ${contextName} context after ${maxAttempts} attempts (${bodyHint}). Open the Partner Center page first or refresh login.`);
}

async function waitForPartnerContext(page, partnerContext, waitsForReport) {
  const expectedPath = waitsForReport
    ? '/api/v1/insights/partner/report/valid/dimension/list'
    : '/api/v1/affiliate/partner/relation/list';
  await page.waitForRequest((request) => request.url().includes(expectedPath), { timeout: 45000 })
    .then((request) => {
      const url = request.url();
      if (waitsForReport) partnerContext.reportDimensionListUrl ||= url;
      else partnerContext.relationListUrl ||= url;
    })
    .catch(() => {});
}

export async function precheckCreator(page, partnerContext, creator) {
  const url = buildPartnerApiUrl(partnerContext, '/api/v1/affiliate/partner/relation/precheck', {
    creator_name: creator,
  });
  return await browserFetchJson(page, url, { method: 'GET' });
}

export async function createInvitation(page, partnerContext, payload) {
  const url = buildPartnerApiUrl(partnerContext, '/api/v1/affiliate/partner/relation/create');
  return await browserFetchJson(page, url, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(payload),
  });
}

export async function resendExpiredInvitationViaUi(page, payload) {
  const creator = normalizeCreator(payload.creator_name);
  const commission = String(payload.commission_proportion || defaults.commission);
  const resendName = /Solicitar novamente|Request again|Resend request/i;

  let row = page.locator('tr, [role="row"]').filter({ hasText: creator }).first();
  if (await row.count().catch(() => 0) === 0) {
    const search = page.getByPlaceholder(/Search creators by username|Buscar criadores por nome de usuário/i);
    if (await search.count().catch(() => 0) !== 1) {
      throw new Error(`Could not identify the creator search field for @${creator}`);
    }
    const listResponse = page.waitForResponse(
      (response) => response.url().includes('/api/v1/affiliate/partner/relation/list'),
      { timeout: 15000 },
    ).catch(() => null);
    await search.fill(creator);
    await search.press('Enter').catch(() => {});
    await listResponse;
    await page.waitForTimeout(1200);
    row = page.locator('tr, [role="row"]').filter({ hasText: creator }).first();
  }
  let resendButton = row.getByRole('button', { name: resendName });
  if (await resendButton.count().catch(() => 0) === 0) {
    const globalResend = page.getByRole('button', { name: resendName });
    if (await globalResend.count().catch(() => 0) === 1) resendButton = globalResend;
  }
  if (await resendButton.count().catch(() => 0) !== 1) {
    const url = page.url();
    const buttons = await page.getByRole('button').allTextContents().catch(() => []);
    const inputs = await page.locator('input').evaluateAll((nodes) => nodes.slice(0, 20).map((node) => ({
      type: node.getAttribute('type'),
      placeholder: node.getAttribute('placeholder'),
      ariaLabel: node.getAttribute('aria-label'),
    }))).catch(() => []);
    const body = await page.locator('body').innerText().catch(() => '');
    throw new Error(
      `Could not identify exactly one resend button for @${creator}; `
      + `url=${url}; buttons=${JSON.stringify(buttons.slice(0, 30))}; `
      + `inputs=${JSON.stringify(inputs)}; `
      + `body=${body.replace(/\s+/g, ' ').slice(0, 700)}`,
    );
  }
  await resendButton.click();

  const labelledForm = page.getByLabel(/Adicionar novo criador|Add new creator/i).last();
  const dialog = page.getByRole('dialog').last();
  const scope = await labelledForm.count().catch(() => 0) ? labelledForm : dialog;
  const creatorInput = scope.getByRole('textbox').first();
  if (await creatorInput.count().catch(() => 0) !== 1) {
    throw new Error(`Could not identify the creator field in the resend form for @${creator}`);
  }
  const creatorJaPreenchido = await creatorInput.inputValue().catch(() => '');
  if (normalizeCreator(creatorJaPreenchido).toLowerCase() !== creator.toLowerCase()) {
    await creatorInput.fill(creator);
  }

  let commissionInput = scope.getByPlaceholder(
    /Please set a percentage from 0 to 100|Defina uma porcentagem de 0 a 100/i,
  );
  if (await commissionInput.count().catch(() => 0) !== 1) {
    commissionInput = scope.getByRole('spinbutton').first();
  }
  if (await commissionInput.count().catch(() => 0) !== 1) {
    throw new Error(`Could not identify the commission field in the resend form for @${creator}`);
  }
  const checkboxes = scope.getByRole('checkbox');
  if (await checkboxes.count().catch(() => 0) < 1) {
    throw new Error(`Could not identify the agreement checkbox for @${creator}`);
  }
  const agreement = checkboxes.last();
  if (!await agreement.isChecked()) {
    await agreement.evaluate((element) => element.click());
  }
  if (!await agreement.isChecked()) {
    throw new Error(`Agreement was not committed in the resend form for @${creator}`);
  }
  // O InputNumber do Arco recria o estado ao marcar o acordo. Digitar como
  // usuário, depois dessa recriação, é o único caminho que atualiza o valor
  // controlado usado pela validação do Submit.
  await commissionInput.click();
  await commissionInput.press(process.platform === 'darwin' ? 'Meta+A' : 'Control+A');
  await commissionInput.press('Backspace');
  await commissionInput.pressSequentially(commission, { delay: 180 });
  const commissionStateAfterInput = await commissionInput.evaluate((element) => {
    const propsKey = Object.keys(element).find((key) => key.startsWith('__reactProps'));
    const props = propsKey ? element[propsKey] : null;
    return {
      domValue: element.value,
      propValue: props?.value,
      propDefaultValue: props?.defaultValue,
      hasOnChange: typeof props?.onChange === 'function',
      hasOnInput: typeof props?.onInput === 'function',
      propKeys: props ? Object.keys(props) : [],
    };
  }).catch(() => null);
  await page.waitForTimeout(800);
  if (String(await commissionInput.inputValue()).trim() !== commission) {
    throw new Error(
      `Commission was reset before submit for @${creator}; `
      + `state_after_input=${JSON.stringify(commissionStateAfterInput)}`,
    );
  }
  const formContainer = scope.locator('div').filter({
    hasText: /The request expires after 7 days|A solicitação expira após 7 dias/i,
  }).first();
  if (await formContainer.count().catch(() => 0) === 1) {
    await formContainer.click();
    await page.waitForTimeout(800);
  }
  if (String(await commissionInput.inputValue()).trim() !== commission) {
    throw new Error(`Commission was reset by the form-container click for @${creator}`);
  }
  const commissionStateBeforeSubmit = await commissionInput.evaluate((element) => {
    const propsKey = Object.keys(element).find((key) => key.startsWith('__reactProps'));
    const fiberKey = Object.keys(element).find((key) => key.startsWith('__reactFiber'));
    const props = propsKey ? element[propsKey] : null;
    const chain = [];
    let fiber = fiberKey ? element[fiberKey] : null;
    for (let depth = 0; fiber && depth < 25; depth += 1, fiber = fiber.return) {
      const memo = fiber.memoizedProps;
      const type = fiber.type;
      chain.push({
        depth,
        type: typeof type === 'string' ? type : (type?.displayName || type?.name || typeof type),
        hasOnChange: typeof memo?.onChange === 'function',
        hasValue: Boolean(memo && Object.prototype.hasOwnProperty.call(memo, 'value')),
        value: ['string', 'number', 'boolean'].includes(typeof memo?.value) ? memo.value : null,
        name: typeof memo?.name === 'string' ? memo.name : null,
        field: typeof memo?.field === 'string' ? memo.field : null,
        required: typeof memo?.required === 'boolean' ? memo.required : null,
      });
    }
    return {
      domValue: element.value,
      ariaInvalid: element.getAttribute('aria-invalid'),
      propValue: props?.value,
      propDefaultValue: props?.defaultValue,
      hasOnChange: typeof props?.onChange === 'function',
      hasOnInput: typeof props?.onInput === 'function',
      reactKey: propsKey || null,
      chain,
    };
  }).catch(() => null);

  let submit = scope.getByRole('button', { name: /^(Enviar|Send|Submit)$/i });
  if (await submit.count().catch(() => 0) !== 1) {
    submit = scope.locator('div').filter({ hasText: /^(Enviar|Send|Submit)$/i }).first();
  }
  if (await submit.count().catch(() => 0) !== 1) {
    // O Partner renderiza a ação fora da árvore rotulada do formulário em
    // algumas versões. Este é o mesmo alvo estável gerado pelo Playwright
    // recorder; o modal já está aberto e os campos acima foram validados.
    submit = page.locator('div').filter({ hasText: /^(Enviar|Send|Submit)$/i }).first();
  }
  if (await submit.count().catch(() => 0) !== 1) {
    const buttons = await page.getByRole('button').allTextContents().catch(() => []);
    const body = await page.locator('body').innerText().catch(() => '');
    throw new Error(
      `Could not identify the send action in the resend form for @${creator}; `
      + `buttons=${JSON.stringify(buttons.slice(-20))}; `
      + `body_tail=${body.replace(/\s+/g, ' ').slice(-1000)}`,
    );
  }
  const responsePromise = page.waitForResponse(
    (response) => response.url().includes('/api/v1/affiliate/partner/relation/create'),
    { timeout: 30000 },
  ).catch(() => null);
  await submit.click();
  const response = await Promise.race([
    responsePromise,
    page.waitForTimeout(4000).then(() => null),
  ]);
  if (!response) {
    const inputs = await scope.locator('input').evaluateAll((nodes) => nodes.map((node) => ({
      type: node.getAttribute('type'),
      placeholder: node.getAttribute('placeholder'),
      value: node.value,
    }))).catch(() => []);
    const commissionMarkup = await commissionInput.evaluate(
      (node) => node.parentElement?.parentElement?.outerHTML?.slice(0, 3000) || node.outerHTML,
    ).catch(() => '');
    const body = await scope.innerText().catch(() => '');
    const screenshot = await saveFailureScreenshot(page).catch(() => null);
    throw new Error(
      `Resend form did not call relation/create for @${creator}; `
      + `inputs=${JSON.stringify(inputs)}; commission=${commissionMarkup.replace(/\s+/g, ' ')}; `
      + `commission_before=${JSON.stringify(commissionStateBeforeSubmit)}; `
      + `screenshot=${screenshot}; body=${body.replace(/\s+/g, ' ').slice(-1200)}`,
    );
  }
  const data = response ? await response.json().catch(() => null) : null;
  const apiAccepted = data?.code === 0 || data?.success === true;
  const accepted = !response || (response.ok() && apiAccepted);
  return {
    ok: accepted,
    status: accepted ? 'reinvite_ui_submitted' : 'reinvite_ui_failed',
    creator,
    commission,
    http_status: response?.status() || null,
    data,
  };
}

export async function listRelations(page, partnerContext, { status = '1', pageSize = 100, pageLimit = 5, creator = '' } = {}) {
  const safePageSize = Math.max(1, Math.min(Number(pageSize) || 100, 100));
  const safePageLimit = Math.max(1, Math.min(Number(pageLimit) || 5, 100));
  const items = [];
  const pages = [];
  let totalNum = null;
  let statusCount = null;
  const normalizedCreator = normalizeCreator(creator);

  for (let pageNumber = 1; pageNumber <= safePageLimit; pageNumber += 1) {
    const url = buildPartnerApiUrl(partnerContext, '/api/v1/affiliate/partner/relation/list', {
      status,
      page_size: safePageSize,
      cur_page: pageNumber,
      creator_name: normalizedCreator,
    });
    const response = await browserFetchJson(page, url, { method: 'GET' });
    const relations = response.data?.data?.relations || [];
    const hasMore = response.data?.data?.has_more;
    totalNum = response.data?.data?.total_num ?? totalNum;
    statusCount = response.data?.data?.status_count ?? statusCount;
    pages.push({
      page: pageNumber,
      ok: response.ok,
      count: relations.length,
      code: response.data?.code,
      msg: response.data?.msg,
      hasMore: hasMore ?? null,
    });

    if (!response.ok) {
      return {
        ok: false,
        items,
        pages,
        totalNum,
        statusCount,
        error: response.data?.msg || `Failed to list relations on page ${pageNumber}`,
      };
    }

    items.push(...relations);
    // A API devolve paginas curtas no meio da lista (ex.: 99 de 100 na pagina 19
    // de 23), entao parar por pagina incompleta subcontava. has_more e o unico
    // sinal de fim confiavel; o tamanho da pagina so vale como plano B.
    if (hasMore === false) break;
    if (hasMore === undefined && relations.length < safePageSize) break;
    if (relations.length === 0) break;
  }

  return { ok: true, items, pages, totalNum, statusCount };
}

export async function verifyCreatorRelation(page, partnerContext, creator, { attempts = 3, delayMs = 3000 } = {}) {
  const normalizedCreator = normalizeCreator(creator).toLowerCase();
  const safeAttempts = Math.max(1, Math.min(Number(attempts) || 3, 6));
  const safeDelayMs = Math.max(0, Math.min(Number(delayMs) || 3000, 15000));
  // Convite recém-criado aparece primeiro em "Link requested" (status 2).
  // Consultar os 1.800+ vinculados antes disso consumia todo o timeout quente.
  const checkedStatuses = ['2', '1', '3', '4'];
  const checks = [];

  for (let attempt = 1; attempt <= safeAttempts; attempt += 1) {
    for (const status of checkedStatuses) {
      const relations = await listRelations(page, partnerContext, {
        status,
        pageSize: 100,
        pageLimit: 12,
        creator: normalizedCreator,
      });
      checks.push({
        attempt,
        status,
        ok: relations.ok,
        pages: relations.pages,
        count: relations.items.length,
        error: relations.error,
      });

      if (!relations.ok) {
        return {
          ok: false,
          status: 'relation_check_failed',
          creator,
          checkedStatuses,
          checks,
          error: relations.error,
        };
      }

      const match = relations.items
        .map((relation) => normalizeRelation(relation))
        .find((item) =>
          normalizeCreator(item.arroba).toLowerCase() === normalizedCreator
          && ['solicitada', 'vinculado'].includes(item.status)
        );
      if (match && ['solicitada', 'vinculado'].includes(match.status)) {
        return {
          ok: true,
          status: match.status === 'vinculado' ? 'linked' : 'requested',
          creator,
          relation: match,
          checkedStatuses,
          attempts: attempt,
          checks,
        };
      }
    }

    if (attempt < safeAttempts) {
      await page.waitForTimeout(safeDelayMs);
    }
  }

  return {
    ok: false,
    status: 'relation_not_found_after_invite',
    creator,
    checkedStatuses,
    attempts: safeAttempts,
    checks,
  };
}

export async function listCreatorGmvReport(page, partnerContext, {
  startDate,
  endDateExclusive,
  pageSize = 100,
  pageLimit = 50,
} = {}) {
  const safePageSize = Math.max(1, Math.min(Number(pageSize) || 100, 100));
  const safePageLimit = Math.max(1, Math.min(Number(pageLimit) || 50, 200));
  const items = [];
  const pages = [];
  let columns = [];
  let totalCount = null;

  for (let currentPage = 0; currentPage < safePageLimit; currentPage += 1) {
    const url = buildPartnerReportApiUrl(partnerContext, '/api/v1/insights/partner/report/data/list');
    const response = await browserFetchJson(page, url, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        request: buildCreatorGmvReportRequest({ startDate, endDateExclusive, currentPage, pageSize: safePageSize }),
      }),
    });

    const rows = response.data?.data?.data?.rows || [];
    const pagination = response.data?.data?.pagination || {};
    if (!columns.length) columns = response.data?.data?.data?.columns || [];
    if (totalCount === null && pagination.total_count !== undefined) totalCount = Number(pagination.total_count);

    pages.push({
      page: currentPage,
      ok: response.ok,
      count: rows.length,
      total_count: pagination.total_count,
      total_pages: pagination.total_pages,
      code: response.data?.code,
      message: response.data?.message,
    });

    if (!response.ok) {
      return {
        ok: false,
        items,
        pages,
        columns,
        totalCount,
        error: response.data?.message || `Failed to list GMV report page ${currentPage}`,
      };
    }

    for (const row of rows) {
      const data = row.data || {};
      if (String(data.date_range || '').toLowerCase() === 'summary') continue;
      items.push(normalizeCreatorGmvRow(data));
    }

    if (rows.length < safePageSize) break;
    if (pagination.total_pages !== undefined && currentPage + 1 >= Number(pagination.total_pages)) break;
  }

  return {
    ok: true,
    items,
    pages,
    columns,
    totalCount,
  };
}

function buildCreatorGmvReportRequest({ startDate, endDateExclusive, currentPage, pageSize }) {
  const emptyFilter = { include_ids: [], exclude_ids: [] };
  return {
    time_interval: {
      start: startDate,
      end: endDateExclusive,
      granularity: 'all',
    },
    dimensions: [4],
    pagination: {
      current_page: currentPage,
      page_size: pageSize,
    },
    sort_rules: [
      { field: 'sum_cl_pay_amt', direction: 2 },
    ],
    filter: {
      require_summation: true,
      product: emptyFilter,
      campaign: emptyFilter,
      shop: emptyFilter,
      live: emptyFilter,
      video: emptyFilter,
      first_product_category: emptyFilter,
      second_product_category: emptyFilter,
      first_product_category_name: emptyFilter,
      second_product_category_name: emptyFilter,
      creator_id: emptyFilter,
      creator: emptyFilter,
    },
  };
}

function normalizeCreatorGmvRow(data) {
  return {
    arroba: normalizeCreator(data.author_alias || ''),
    author_id: data.author_id || '',
    date_range: data.date_range || '',
    gmv: parseCurrencyNumber(data.sum_cl_pay_amt),
    gmv_formatted: data.sum_cl_pay_amt || '',
    orders: parseInteger(data.cl_pay_sku_order_cnt),
    live_gmv: parseCurrencyNumber(data.cl_live_pay_amt),
    video_gmv: parseCurrencyNumber(data.cl_video_pay_amt),
    direct_gmv: parseCurrencyNumber(data.cl_flow_con_pay_amt),
    estimated_commission: parseCurrencyNumber(data.pre_estimated_commission),
    raw: data,
  };
}

export function normalizeRelation(relation) {
  const creator = relation.creator_info || relation.data_relation?.creator_info || {};
  const rawStatus = Number(relation.status ?? relation.data_relation?.status);
  const dataStatus = Number(relation.data_relation?.status ?? relation.status);
  const expireTimeSecond = relation.expire_time_second || relation.data_relation?.expire_time_second || '';
  const effectiveEndDateSecond = relation.effective_end_date_second || relation.data_relation?.effective_end_date_second || '';
  const expired = isExpiredSecond(expireTimeSecond) || isExpiredSecond(effectiveEndDateSecond);
  return {
    arroba: normalizeCreator(creator.user_name || ''),
    creator_name: creator.nick_name || '',
    status: rawStatus === 1 || dataStatus === 1 ? 'vinculado' : (expired ? 'expirada' : 'solicitada'),
    tiktok_status: rawStatus,
    tiktok_data_status: dataStatus,
    relation_id: relation.id || relation.data_relation?.id || '',
    create_time_second: relation.create_time_second || '',
    expire_time_second: expireTimeSecond,
    effective_end_date_second: effectiveEndDateSecond,
  };
}

function isExpiredSecond(value) {
  const second = Number(value || 0);
  return Number.isFinite(second) && second > 0 && second <= Math.floor(Date.now() / 1000);
}

function buildPartnerApiUrl(partnerContext, pathname, params = {}) {
  if (!partnerContext?.relationListUrl) {
    throw new Error('Could not capture TikTok partner context from relation/list. Open the Partner Center page first or refresh login.');
  }

  const url = new URL(partnerContext.relationListUrl);
  url.pathname = pathname;

  const remove = [
    'status',
    'page_size',
    'cur_page',
    'relation_tag',
    'effective_end_dates',
    'msToken',
    'X-Bogus',
    '_signature',
    'X-Tts-Oec-Bsid',
  ];

  for (const key of remove) url.searchParams.delete(key);
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== '') {
      url.searchParams.set(key, String(value));
    }
  }

  return url.toString();
}

function buildPartnerReportApiUrl(partnerContext, pathname, params = {}) {
  if (!partnerContext?.reportDimensionListUrl) {
    throw new Error('Could not capture TikTok custom report context. Open the Custom report page first or refresh login.');
  }

  const url = new URL(partnerContext.reportDimensionListUrl);
  url.pathname = pathname;

  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== '') {
      url.searchParams.set(key, String(value));
    }
  }

  return url.toString();
}

function getReportPeriod({ startDate, endDateExclusive } = {}) {
  if (startDate && endDateExclusive) {
    return { startDate: String(startDate), endDateExclusive: String(endDateExclusive) };
  }

  const now = new Date();
  const saoPauloNow = new Date(now.toLocaleString('en-US', { timeZone: 'America/Sao_Paulo' }));
  const year = saoPauloNow.getFullYear();
  const month = saoPauloNow.getMonth();
  const start = new Date(year, month - 1, 1);
  const endExclusive = new Date(year, month, 1);
  return {
    startDate: formatDate(start),
    endDateExclusive: formatDate(endExclusive),
  };
}

function formatDate(date) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

function parseCurrencyNumber(value) {
  const text = String(value || '').trim();
  if (!text || text === '-') return 0;
  const normalized = text
    .replace(/R\$|BRL|\s/g, '')
    .replace(/\./g, '')
    .replace(',', '.')
    .replace(/[^0-9.-]/g, '');
  const number = Number(normalized);
  return Number.isFinite(number) ? number : 0;
}

function parseInteger(value) {
  const number = Number(String(value || '').replace(/[^0-9-]/g, ''));
  return Number.isFinite(number) ? number : 0;
}

async function browserFetchJson(page, url, init) {
  const headers = {
    accept: 'application/json, text/plain, */*',
    ...(init.headers || {}),
  };
  const res = await page.context().request.fetch(url, {
    method: init.method || 'GET',
    headers,
    data: init.body,
    timeout: init.timeout || 60000,
    failOnStatusCode: false,
  });
  const text = await res.text();
  let data;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = { raw: text.slice(0, 1000) };
  }

  const apiOk = data?.code === 0 || data?.success === true;
  return {
    ok: res.ok() && apiOk,
    httpStatus: res.status(),
    httpOk: res.ok(),
    data,
  };
}

async function saveFailureScreenshot(page) {
  const dir = path.join(here, 'artifacts');
  fs.mkdirSync(dir, { recursive: true });
  const file = path.join(dir, `tiktok-error-${Date.now()}.png`);
  await page.screenshot({ path: file, fullPage: true });
  return file;
}

export function computeDueDateSecond({ days, fixedMonths } = {}) {
  if (Number.isFinite(fixedMonths) && fixedMonths > 0) {
    const date = new Date();
    date.setUTCMonth(date.getUTCMonth() + fixedMonths);
    return Math.floor(date.getTime() / 1000);
  }

  const safeDays = Number.isFinite(days) && days > 0 ? days : defaults.dueDays;
  return Math.floor(Date.now() / 1000 + safeDays * 24 * 60 * 60);
}

export function normalizeCreator(value) {
  return String(value || '').trim().replace(/^@+/, '');
}

export function parseCreatorList(value) {
  return new Set(String(value || '')
    .split(',')
    .map((item) => normalizeCreator(item).toLowerCase())
    .filter(Boolean));
}

function parseArgs(argv) {
  const out = { _: [] };
  for (let i = 0; i < argv.length; i += 1) {
    const token = argv[i];
    if (!token.startsWith('--')) {
      out._.push(token);
      continue;
    }
    const keyValue = token.slice(2);
    const eq = keyValue.indexOf('=');
    if (eq !== -1) {
      out[toCamel(keyValue.slice(0, eq))] = keyValue.slice(eq + 1);
      continue;
    }
    const key = toCamel(keyValue);
    const next = argv[i + 1];
    if (next && !next.startsWith('--')) {
      out[key] = next;
      i += 1;
    } else {
      out[key] = true;
    }
  }
  return out;
}

function toCamel(value) {
  return value.replace(/-([a-z])/g, (_, char) => char.toUpperCase());
}

function requiredArg(value, name) {
  if (value === undefined || value === null || String(value).trim() === '') {
    throw new Error(`Missing required --${name}`);
  }
  return value;
}

function parseBool(value, fallback) {
  if (value === undefined || value === null || value === '') return fallback;
  if (typeof value === 'boolean') return value;
  return ['1', 'true', 'yes', 'on'].includes(String(value).toLowerCase());
}

function stripTrailingSlash(value) {
  return String(value).replace(/\/+$/, '');
}

function resolveFromHere(value) {
  if (path.isAbsolute(value)) return value;
  return path.resolve(here, value);
}

function loadDotEnv(file) {
  if (!fs.existsSync(file)) return;
  const content = fs.readFileSync(file, 'utf8');
  for (const line of content.split(/\r?\n/)) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith('#')) continue;
    const eq = trimmed.indexOf('=');
    if (eq === -1) continue;
    const key = trimmed.slice(0, eq).trim();
    const value = trimmed.slice(eq + 1).trim().replace(/^['"]|['"]$/g, '');
    if (!process.env[key]) process.env[key] = value;
  }
}

function waitForEnter() {
  return new Promise((resolve) => {
    process.stdin.resume();
    process.stdin.once('data', () => resolve());
  });
}

function serializeError(error) {
  return {
    name: error?.name || 'Error',
    message: error?.message || String(error),
  };
}

function emit(value) {
  process.stdout.write(`${JSON.stringify(value, null, 2)}\n`);
}

function printHelp() {
  process.stdout.write(`Usage:
  node invite.mjs login
  node invite.mjs login --hold
  node invite.mjs precheck --creator <tiktok_user>
  node invite.mjs invite --creator <tiktok_user> [--commission 10] [--due-days 60] [--yes]

Options:
  --creator                    TikTok handle, with or without @
  --commission                 Commission percent. Default: ${defaults.commission}
  --due-days                   Days from now. Default: ${defaults.dueDays}
  --due-date-second            Explicit Unix timestamp in seconds
  --related-biz-types          Default: ${defaults.relatedBizTypes}
  --attached-business-profile  true/false. Default: true
  --skip-precheck              true/false. Default: true (funnel already validated profile)
  --verify-attempts            Post-send Partner checks. Default: 3
  --verify-delay-ms            Delay between post-send checks. Default: 3000
  --headless                   true/false
  --hold                       Keep login browser open for remote/noVNC login
  --yes                        Required to send invitation
`);
}
