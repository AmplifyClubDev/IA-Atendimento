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
