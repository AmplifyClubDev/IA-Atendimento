import { test } from 'node:test';
import assert from 'node:assert/strict';
import { montarInstrucoes, historicoDe, perguntarIA, dadosDoAgenciado } from './ia.mjs';
import { responderComIA } from './respostas.mjs';

const CARTOES = [{ tipo: 'personalidade', titulo: 'Personalidade da Bia', conteudo: 'Você é Bia.' },
  { tipo: 'conhecimento', titulo: 'Comissão e custos', conteudo: 'Taxa de 10%.' }, { tipo: 'limites', titulo: 'Limites', conteudo: 'Não invente.' }];
const AG = { tiktok: '@ana', nome: 'Ana', situacao: 'Ativo', agenciado_em: '2026-10-01T10:00:00', contrato_inicio: '2026-10-01',
  contrato_fim: '2026-12-01', dias_para_vencer: 5, categoria: 'Silver', gmv_nivel: 6000, comissao_pct: 10, renovacao: 'Aguardando aceite',
  renovacao_expira_em: '2026-11-28T10:00:00', renovacao_novo_fim: '2027-12-01' };

test('instruções: agenciada (nunca lead), dados do contrato, cartões da Bia', () => {
  const i = montarInstrucoes(CARTOES, AG);
  assert.match(i, /Você é Bia\./);
  assert.match(i, /JÁ É AGENCIADA/);
  assert.match(i, /não ofereça agenciamento/);
  assert.match(i, /01\/10\/2026 até 01\/12\/2026 \(faltam 5 dias\)/);
  assert.match(i, /Aguardando aceite \(expira 28\/11\/2026\)/);
  assert.match(i, /Taxa de 10%/);
  assert.match(montarInstrucoes(CARTOES, null), /Não invente datas/);
});

test('histórico: só mensagens da conversa, sem notas internas, em ordem', () => {
  const h = historicoDe([{ message_type: 1, content: 'renovação de contrato', created_at: 1 }, { message_type: 2, content: 'x', created_at: 2 },
    { message_type: 1, content: 'nota', private: true, created_at: 3 }, { message_type: 0, content: 'Preciso pagar?', created_at: 4 }]);
  assert.deepEqual(h, [{ role: 'assistant', content: 'renovação de contrato' }, { role: 'user', content: 'Preciso pagar?' }]);
});

test('perguntarIA: lê o JSON da resposta e usa o modelo configurado', async () => {
  let corpo;
  const chamar = async (url, op) => { corpo = JSON.parse(op.body); return { ok: true, json: async () => ({ choices: [{ message: {
    content: JSON.stringify({ resposta: 'Não precisa pagar nada! 💙', intencao: 'duvida', passar_para_time: false }) } }] }) }; };
  const r = await perguntarIA({ instrucoes: 'x', historico: [], env: { OPENAI_API_KEY: 'k', RENOVACAO_MODELO: 'gpt-4.1' }, chamar });
  assert.deepEqual(r, { resposta: 'Não precisa pagar nada! 💙', intencao: 'duvida', passarParaTime: false });
  assert.equal(corpo.model, 'gpt-4.1');
  await assert.rejects(() => perguntarIA({ instrucoes: 'x', historico: [], env: {}, chamar: async () => ({ ok: false, status: 500 }) }), /openai 500/);
});

test('dados do agenciado: pelo contrato, pelo telefone e o número de teste', async () => {
  const consultas = [];
  const db = { async ler(tela, q) { consultas.push(q); return q.includes('relation_id=eq.R1') || q.includes('telefone=eq.5547') ? [AG] : []; } };
  assert.equal((await dadosDoAgenciado(db, { relationId: 'R1' }, {})).tiktok, '@ana');
  assert.equal(await dadosDoAgenciado(db, { telefone: '+55 11 99999-0000' }, {}), null);
  assert.equal((await dadosDoAgenciado(db, { telefone: '+55 47 99115-4859' }, {})).tiktok, '@ana');
  assert.equal((await dadosDoAgenciado(db, { telefone: '5511988887777' }, { RENOVACAO_TESTE_TELEFONE: '5511988887777', RENOVACAO_TESTE_RELATION: 'R1' })).tiktok, '@ana');
});

function cwFalso() {
  const feito = [];
  return { feito, async mensagem(c, t) { feito.push(['mensagem', t]); }, async lista() { feito.push(['lista']); },
    async etiqueta(c, e) { feito.push(['etiqueta', e]); }, async nota() { feito.push(['nota']); }, async tirarEtiqueta() { feito.push(['tirar']); } };
}

test('responderComIA: responde; passa para o time; falha vira time; "quero renovar" segue o fluxo do botão', async () => {
  const msg = { conversa: '9', texto: 'Preciso pagar?' };
  let cw = cwFalso();
  assert.equal((await responderComIA(msg, null, { cw, ia: { responder: async () => ({ resposta: 'Oi!', intencao: 'duvida', passarParaTime: false }) } })).status, 'ia');
  assert.deepEqual(cw.feito, [['mensagem', 'Oi!']]);
  cw = cwFalso();
  assert.equal((await responderComIA(msg, null, { cw, ia: { responder: async () => ({ resposta: 'Vou chamar o time', intencao: 'outro', passarParaTime: true }) } })).status, 'time');
  assert.deepEqual(cw.feito.map((f) => f[0]), ['mensagem', 'etiqueta', 'nota']);
  cw = cwFalso();
  assert.equal((await responderComIA(msg, null, { cw, ia: { responder: async () => { throw new Error('openai 500'); } } })).status, 'time');
  assert.equal(cw.feito[1][1], 'renovacao-atencao');
  cw = cwFalso();
  await responderComIA(msg, { renovacao: 'Aguardando aceite' }, { cw, ia: { responder: async () => ({ resposta: 'x', intencao: 'quero_renovar', passarParaTime: false }) } });
  assert.match(cw.feito[0][1], /falta só um toque/);
});
