import { test } from 'node:test';
import assert from 'node:assert/strict';
import { telefoneValido, dentroDoHorario, montarMensagem, enviarUm, principal } from './envio.mjs';

test('telefone: só celular do Brasil com DDI', () => {
  assert.equal(telefoneValido('+55 (11) 99999-8888'), '5511999998888');
  assert.equal(telefoneValido('551133334444'), '551133334444');
  assert.equal(telefoneValido('11999998888'), null);
  assert.equal(telefoneValido(null), null);
});

test('horário: só das 9h às 20h de Brasília', () => {
  assert.equal(dentroDoHorario(new Date('2026-11-25T11:59:00Z')), false); // 8h59
  assert.equal(dentroDoHorario(new Date('2026-11-25T12:00:00Z')), true);  // 9h
  assert.equal(dentroDoHorario(new Date('2026-11-25T22:59:00Z')), true);  // 19h59
  assert.equal(dentroDoHorario(new Date('2026-11-25T23:00:00Z')), false); // 20h
});

test('mensagem do template pelo tipo de contrato, com nome e data', () => {
  const m = montarMensagem({ etapa: 'convite', template: 'renovacao_primeiro_contrato', parametros: ['Ana', '02/12'] }, {});
  assert.deepEqual(m.template_params, { name: 'renovacao_primeiro_contrato', category: 'UTILITY', language: 'pt_BR',
    processed_params: { body: { 1: 'Ana', 2: '02/12' } } });
  const v = montarMensagem({ etapa: 'convite', template: 'renovacao_contrato_anual', parametros: ['Ana', '02/12'] },
    { RENOVACAO_VIDEO: 'https://v.exemplo/r.mp4' });
  assert.deepEqual(v.template_params.processed_params.header, { media_url: 'https://v.exemplo/r.mp4', media_type: 'video' });
  assert.throws(() => montarMensagem({ etapa: 'convite', template: 'renovacao_contrato_anual', parametros: ['Ana'] }, {}), /parâmetros/);
  assert.throws(() => montarMensagem({ etapa: 'semana', template: 'primeiro_contato_contrato', parametros: [] }, {}), /template inesperado/);
});

test('enviarUm: acha o contato, abre a conversa na caixa 1 e etiqueta', async () => {
  const feito = [];
  const cw = {
    async contato(tel, nome) { feito.push(['contato', tel, nome]); return { contato: { id: 9 }, sourceId: tel }; },
    async conversa(c, s, m) { feito.push(['conversa', c.id, s, m.template_params.name]); return { id: 77 }; },
    async etiqueta(id) { feito.push(['etiqueta', id]); },
  };
  const id = await enviarUm({ etapa: 'convite', template: 'renovacao_contrato_anual', parametros: ['Ana', '02/12'], nome: 'Ana' },
    '5511999998888', {}, cw);
  assert.equal(id, 77);
  assert.deepEqual(feito, [['contato', '5511999998888', 'Ana'], ['conversa', 9, '5511999998888', 'renovacao_contrato_anual'], ['etiqueta', 77]]);
});

test('enviar: desligado por padrão', async () => {
  await assert.rejects(() => principal(['enviar'], {}, () => {}), /envio desligado/);
  await assert.rejects(() => principal(['teste', '123'], {}, () => {}), /teste precisa/);
});
