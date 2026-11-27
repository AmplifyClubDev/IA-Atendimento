// Testes das correções da auditoria (27/11/2026).
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { classificar, planejar, tratar, avisarFalha } from './respostas.mjs';
import { aindaVale, enviarFila } from './envio.mjs';
import { mascarar } from './ia.mjs';
import { criarIA, LIMITE_IA_DIA } from './servico.mjs';

test('classificar: só resposta exata vira decisão; o resto vai para a IA', () => {
  assert.equal(classificar('renovar como?').resposta, 'outro');
  assert.equal(classificar('quero renovar mas tenho uma dúvida').resposta, 'outro');
  assert.equal(classificar('Quero renovar!').resposta, 'quero');
  assert.equal(classificar('Não quero renovar').resposta, 'nao_quero');
  assert.deepEqual(classificar('Parei de vender'), { resposta: 'motivo', motivo: 'Parei de vender' }); // mesmo sem "ultima"
  assert.equal(classificar('posso voltar depois?', 'nao_quero').resposta, 'outro'); // pergunta vai para a IA
  assert.equal(classificar('', 'nao_quero').resposta, 'outro'); // áudio/figurinha
});

test('planejar: quem já renovou não recebe "vamos enviar o pedido"', () => {
  assert.match(planejar('quero', { renovacao: 'Aceita' }).mensagens[0], /já está confirmada/);
});

test('aindaVale: contrato vencido, longe ou renovado não sai', () => {
  const agora = new Date('2026-11-27T13:00:00Z'); // 10h em Brasília
  assert.equal(aindaVale({ contrato_fim: '2026-11-27' }, agora), 'Contrato venceu antes do envio');
  assert.equal(aindaVale({ contrato_fim: '2026-11-26' }, agora), 'Contrato venceu antes do envio');
  assert.equal(aindaVale({ contrato_fim: '2026-12-10' }, agora), 'Fora da régua (mais de 7 dias)');
  assert.equal(aindaVale({ contrato_fim: '2026-12-01', renovacao_agora: 'Aceita' }, agora), 'Renovou antes do envio');
  assert.equal(aindaVale({ contrato_fim: '2026-12-01', renovacao_agora: 'Aguardando aceite' }, agora), null);
});

function filaFalsa(linhas) {
  const marcados = [];
  return { marcados, db: { async fila() { return linhas; }, async marcar(id, s, x) { marcados.push([id, s, x?.motivo || x?.chatwoot_conversa]); } } };
}
const cwOk = { async contato(t) { return { contato: { id: 1 }, sourceId: t }; }, async conversa() { return { id: 70 }; }, async etiqueta() {} };
const DEZ_DA_MANHA = () => new Date('2026-11-27T13:00:00Z');

test('enviarFila: cancela vencido, envia o válido, para fora do horário', async () => {
  const { db, marcados } = filaFalsa([
    { id: 1, etapa: 'convite', template: 'renovacao_contrato', parametros: ['26/11'], telefone: '5547999990000', contrato_fim: '2026-11-26' },
    { id: 2, etapa: 'convite', template: 'renovacao_contrato', parametros: ['01/12'], telefone: '5547999990000', contrato_fim: '2026-12-01' },
  ]);
  const r = await enviarFila({ RENOVACAO_ENVIO_LIGADO: 'true' }, () => {}, db, cwOk, async () => {}, DEZ_DA_MANHA);
  assert.deepEqual(r, { enviados: 1, falhas: 0 });
  assert.deepEqual(marcados, [[1, 'cancelado', 'Contrato venceu antes do envio'], [2, 'enviado', '70']]);
  const noite = filaFalsa([{ id: 3, contrato_fim: '2026-12-01', telefone: '5547999990000' }]);
  const r2 = await enviarFila({ RENOVACAO_ENVIO_LIGADO: 'true' }, () => {}, noite.db, cwOk, async () => {}, () => new Date('2026-11-27T23:30:00Z'));
  assert.deepEqual(r2, { enviados: 0, falhas: 0 });
  assert.deepEqual(noite.marcados, []);
});

test('enviarFila: duas rodadas ao mesmo tempo não enviam em dobro', async () => {
  let liberar;
  const trava = new Promise((r) => { liberar = r; });
  const lenta = { async fila() { await trava; return []; }, async marcar() {} };
  const a = enviarFila({ RENOVACAO_ENVIO_LIGADO: 'true' }, () => {}, lenta, cwOk, async () => {}, DEZ_DA_MANHA);
  const msgs = [];
  const b = await enviarFila({ RENOVACAO_ENVIO_LIGADO: 'true' }, (t) => msgs.push(t), lenta, cwOk, async () => {}, DEZ_DA_MANHA);
  assert.deepEqual(b, { enviados: 0, falhas: 0 });
  assert.match(msgs[0], /em andamento/);
  liberar();
  await a;
});

test('tratar: conversa que o serviço não enviou não recebe nada', async () => {
  const feito = [];
  const db = { async ultimaResposta() { return null; }, async rpc() { return { status: 'fora', envio: null }; } };
  const cw = new Proxy({}, { get: () => async () => feito.push('chatwoot') });
  assert.deepEqual(await tratar({ mensagem: '1', conversa: '54162', texto: 'Oi! quero fazer parte' }, { db, cw }), { resposta: 'outro', status: 'fora' });
  assert.deepEqual(feito, []);
});

test('avisarFalha: etiqueta e nota para o time, sem lançar erro', async () => {
  const feito = [];
  await avisarFalha({ conversa: '9' }, { async etiqueta(c, e) { feito.push(e); }, async nota() { throw new Error('x'); } }, new Error('boom'));
  assert.deepEqual(feito, ['renovacao-atencao']);
});

test('mascarar: CPF e números longos não vão para a IA', () => {
  assert.equal(mascarar('meu cpf é 123.456.789-09'), 'meu cpf é [número oculto]');
  assert.equal(mascarar('12345678909 e 5547999990000'), '[número oculto] e [número oculto]');
  assert.equal(mascarar('vence dia 02/12'), 'vence dia 02/12');
});

test('IA: no máximo LIMITE_IA_DIA respostas por conversa por dia', async () => {
  const db = { async ler() { throw new Error('sem banco no teste'); } }, cw = { async mensagens() { return []; } };
  const ia = criarIA({ OPENAI_API_KEY: 'k' }, db, cw, () => Date.parse('2026-11-27T12:00:00Z'));
  // Passa do limite antes de chamar qualquer coisa externa: as chamadas acima do limite falham na hora.
  for (let i = 0; i < LIMITE_IA_DIA; i += 1) await ia.responder({ conversa: '9' }, null).catch(() => {});
  await assert.rejects(() => ia.responder({ conversa: '9' }, null), /limite diário/);
});

test('item 14: etiqueta conferida depois de gravar; se outra mudança apagou, grava de novo', async () => {
  const { chatwoot } = await import('./envio.mjs');
  let atuais = ['Renovacao de contrato'];
  let gravacoes = 0;
  const original = globalThis.fetch;
  globalThis.fetch = async (url, op = {}) => {
    if (op.method === 'POST') {
      gravacoes += 1;
      // Na 1ª gravação, alguém do time trocou as etiquetas ao mesmo tempo e a de renovação sumiu.
      atuais = gravacoes === 1 ? ['outra'] : JSON.parse(op.body).labels;
    }
    return { ok: true, text: async () => JSON.stringify({ payload: atuais }) };
  };
  try {
    const cw = chatwoot({ CHATWOOT_BASE_URL: 'https://cw', CHATWOOT_ACCOUNT_ID: '1', CHATWOOT_API_TOKEN: 't' });
    await cw.etiqueta('9', 'renovacao-nao-quer');
    assert.ok(atuais.includes('renovacao-nao-quer'));
    assert.equal(gravacoes, 2);
  } finally { globalThis.fetch = original; }
});

test('item 15: fim do ciclo — renovou manda confirmação (envio ligado) e tira a etiqueta; venceu só tira', async () => {
  const { liberar } = await import('./servico.mjs');
  const feito = [];
  const db = { async ler() { return [{ id: 1, chatwoot_conversa: '10', ciclo_fim: 'renovou', novo_fim: '02/12/2027' },
    { id: 2, chatwoot_conversa: '11', ciclo_fim: 'venceu', novo_fim: '01/12/2026' }]; },
  async rpc(n, p) { feito.push(['fechar', p.id, p.confirmacao]); } };
  const cw = { async template(c, m) { feito.push(['template', c, m.template_params.name, m.template_params.processed_params.body[1]]); },
    async tirarEtiqueta(c) { feito.push(['tirar', c]); } };
  const r = await liberar({ RENOVACAO_ENVIO_LIGADO: 'true' }, db, cw);
  assert.deepEqual(r, { liberadas: 2, confirmacoes: 1, falhas: 0 });
  assert.deepEqual(feito, [['template', '10', 'renovacao_confirmada', '02/12/2027'], ['tirar', '10'], ['fechar', '1', true],
    ['tirar', '11'], ['fechar', '2', false]]);
  feito.length = 0;
  await liberar({}, db, cw); // envio desligado: não manda confirmação
  assert.ok(!feito.some((f) => f[0] === 'template'));
});
