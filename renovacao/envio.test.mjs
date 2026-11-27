import { test } from 'node:test';
import assert from 'node:assert/strict';
import { telefoneValido, dentroDoHorario, montarMensagem, enviarUm, principal } from './envio.mjs';

test('telefone: só celular do Brasil com DDI', () => {
  assert.equal(telefoneValido('+55 (11) 99999-8888'), '5511999998888');
  assert.equal(telefoneValido('551133334444'), '551133334444');
  assert.equal(telefoneValido('11999998888'), null);
  assert.equal(telefoneValido(null), null);
});

test('horário: só das 12h às 14h de Brasília (envio ao meio-dia)', () => {
  assert.equal(dentroDoHorario(new Date('2026-11-25T14:59:00Z')), false); // 11h59
  assert.equal(dentroDoHorario(new Date('2026-11-25T15:00:00Z')), true);  // 12h
  assert.equal(dentroDoHorario(new Date('2026-11-25T16:59:00Z')), true);  // 13h59
  assert.equal(dentroDoHorario(new Date('2026-11-25T17:00:00Z')), false); // 14h
  assert.equal(dentroDoHorario(new Date('2026-11-25T03:00:00Z')), false); // meia-noite
});

test('mensagem do template único com a data', () => {
  const m = montarMensagem({ etapa: 'convite', template: 'renovacao_contrato', parametros: ['02/12'] }, {});
  assert.deepEqual(m.template_params, { name: 'renovacao_contrato', category: 'MARKETING', language: 'pt_BR',
    processed_params: { body: { 1: '02/12' } } });
  assert.throws(() => montarMensagem({ etapa: 'convite', template: 'renovacao_contrato', parametros: [] }, {}), /parâmetros/);
  assert.throws(() => montarMensagem({ etapa: 'convite', template: 'renovacao_contrato_anual', parametros: ['02/12'] }, {}), /template inesperado/);
});

test('enviarUm: acha o contato, abre a conversa na caixa 1 e etiqueta', async () => {
  const feito = [];
  const cw = {
    async contato(tel, nome) { feito.push(['contato', tel, nome]); return { contato: { id: 9 }, sourceId: tel }; },
    async conversa(c, s, m) { feito.push(['conversa', c.id, s, m.template_params.name]); return { id: 77 }; },
    async etiqueta(id) { feito.push(['etiqueta', id]); },
  };
  const id = await enviarUm({ etapa: 'convite', template: 'renovacao_contrato', parametros: ['02/12'], nome: 'Ana' },
    '5511999998888', {}, cw);
  assert.equal(id, 77);
  assert.deepEqual(feito, [['contato', '5511999998888', 'Ana'], ['conversa', 9, '5511999998888', 'renovacao_contrato'], ['etiqueta', 77]]);
});

test('sem a etiqueta o envio falha (a Bia responderia)', async () => {
  const cw = { async contato() { return { contato: { id: 1 }, sourceId: 'x' }; }, async conversa() { return { id: 5 }; },
    async etiqueta() { throw new Error('422'); } };
  await assert.rejects(() => enviarUm({ etapa: 'convite', template: 'renovacao_contrato', parametros: ['02/12'] }, '5511999998888', {}, cw), /etiqueta não aplicada/);
});

test('enviar: desligado por padrão', async () => {
  await assert.rejects(() => principal(['enviar'], {}, () => {}), /envio desligado/);
  await assert.rejects(() => principal(['teste', '123'], {}, () => {}), /teste precisa/);
});
