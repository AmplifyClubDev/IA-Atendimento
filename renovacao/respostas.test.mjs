import { test } from 'node:test';
import assert from 'node:assert/strict';
import { classificar, planejar, lerEvento, tratar, MOTIVOS, ETIQUETA_PEDIDO, ETIQUETA_NAO_QUER } from './respostas.mjs';
import { segredoConfere, criarServidor } from './servico.mjs';

test('classificar: botões, motivo depois do "não quero" e texto solto', () => {
  assert.equal(classificar('Quero renovar').resposta, 'quero');
  assert.equal(classificar('RENOVAR').resposta, 'quero');
  assert.equal(classificar('Não quero renovar').resposta, 'nao_quero');
  assert.equal(classificar('Tenho dúvidas').resposta, 'duvida');
  assert.deepEqual(classificar('Outra agência', 'nao_quero'), { resposta: 'motivo', motivo: 'Outra agência' });
  assert.deepEqual(classificar('mudei de cidade', 'nao_quero'), { resposta: 'motivo', motivo: 'mudei de cidade' });
  assert.equal(classificar('ok obrigada').resposta, 'outro');
  assert.equal(classificar('').resposta, 'outro');
});

test('planejar: quero renovar com e sem pedido aberto no TikTok', () => {
  const aberto = planejar('quero', { renovacao: 'Aguardando aceite', contrato_fim: '02/12' });
  assert.match(aberto.mensagens[0], /já está no seu TikTok/);
  assert.equal(aberto.nota, null);
  const sem = planejar('quero', { renovacao: 'Sem pedido', contrato_fim: '02/12' });
  assert.match(sem.mensagens[0], /Vamos enviar o pedido/);
  assert.deepEqual(sem.etiquetas, [ETIQUETA_PEDIDO]);
  assert.equal(sem.tirarRenovacao, false);
});

test('planejar: não quero pede o motivo; motivo agradece e avisa a retenção; dúvida passa para a Bia', () => {
  const nao = planejar('nao_quero');
  assert.deepEqual(nao.lista.opcoes, MOTIVOS);
  assert.deepEqual(nao.etiquetas, [ETIQUETA_NAO_QUER]);
  assert.ok(MOTIVOS.every((m) => m.length <= 24)); // limite do WhatsApp por opção
  const mot = planejar('motivo', { contrato_fim: '02/12' }, 'Outra agência');
  assert.match(mot.mensagens[0], /\*02\/12\*/);
  assert.match(mot.nota, /Retenção.*Outra agência/);
  assert.equal(mot.tirarRenovacao, false);
  const duv = planejar('duvida');
  assert.equal(duv.tirarRenovacao, false);
});

const evento = (extra = {}) => ({ event: 'message_created', message_type: 'incoming', id: 501, content: 'Quero renovar',
  conversation: { id: 61617, inbox_id: 3, labels: ['Renovacao de contrato'] }, sender: { phone_number: '+5547999990000' }, ...extra });

test('lerEvento: só mensagem recebida, da caixa 3, com a etiqueta de renovação', () => {
  assert.deepEqual(lerEvento(evento(), 3), { mensagem: '501', conversa: '61617', texto: 'Quero renovar', telefone: '+5547999990000', teste: false });
  assert.equal(lerEvento(evento(), 3, ['5547999990000']).teste, true);
  assert.ok(lerEvento(evento({ conversation: { id: 1, inbox_id: 3, labels: ['renovacao de contrato'] } }), 3)); // etiqueta em minúsculas
  assert.equal(lerEvento(evento({ message_type: 'outgoing' }), 3), null);
  assert.equal(lerEvento(evento({ conversation: { id: 1, inbox_id: 1, labels: ['Renovacao de contrato'] } }), 3), null);
  assert.equal(lerEvento(evento({ conversation: { id: 1, inbox_id: 3, labels: [] } }), 3), null);
  assert.equal(lerEvento({ event: 'conversation_updated' }, 3), null);
});

function falsos(ultima = null, envio = { contrato_fim: '02/12', renovacao: 'Aguardando aceite' }, status = 'registrada') {
  const feito = [];
  const db = { async ultimaResposta() { return ultima; }, async rpc(nome, p) { feito.push(['rpc', p.resposta]); return { status, envio }; } };
  const cw = {
    async mensagem(c, t) { feito.push(['mensagem', c, t.slice(0, 20)]); }, async lista(c, t, o) { feito.push(['lista', c, o.length]); },
    async etiqueta(c, e) { feito.push(['etiqueta', e]); }, async nota(c) { feito.push(['nota', c]); },
    async tirarEtiqueta(c, e) { feito.push(['tirar', e]); },
  };
  return { db, cw, feito };
}

test('tratar: "Não quero renovar" manda a lista de motivos; repetida não faz nada', async () => {
  const { db, cw, feito } = falsos();
  assert.deepEqual(await tratar({ mensagem: '1', conversa: '9', texto: 'Não quero renovar' }, { db, cw }), { resposta: 'nao_quero', status: 'tratada' });
  assert.deepEqual(feito, [['rpc', 'nao_quero'], ['lista', '9', 5], ['etiqueta', 'renovacao-nao-quer']]);
  const rep = falsos(null, null, 'repetida');
  await tratar({ mensagem: '1', conversa: '9', texto: 'Não quero renovar' }, rep);
  assert.deepEqual(rep.feito, [['rpc', 'nao_quero']]);
});

test('tratar: "Tenho dúvidas" responde e deixa nota; a etiqueta fica (a Bia de aquisição não entra)', async () => {
  const { db, cw, feito } = falsos();
  await tratar({ mensagem: '2', conversa: '9', texto: 'Tenho dúvidas' }, { db, cw });
  assert.deepEqual(feito.map((f) => f[0]), ['rpc', 'mensagem', 'nota']);
});

test('webhook: segredo errado = 404; respostas desligadas não tratam', async () => {
  assert.equal(segredoConfere('a'.repeat(32), 'a'.repeat(32)), true);
  assert.equal(segredoConfere('a'.repeat(32), 'b'.repeat(32)), false);
  assert.equal(segredoConfere('curto', 'curto'), false);
  const { db, cw, feito } = falsos();
  const s = criarServidor({ RENOVACAO_WEBHOOK_SEGREDO: 's'.repeat(40) }, db, cw).listen(0);
  const porta = s.address().port;
  const errado = await fetch(`http://127.0.0.1:${porta}/webhook/${'x'.repeat(40)}`, { method: 'POST', body: '{}' });
  assert.equal(errado.status, 404);
  const certo = await fetch(`http://127.0.0.1:${porta}/webhook/${'s'.repeat(40)}`, { method: 'POST', body: JSON.stringify(evento()) });
  assert.equal(certo.status, 200);
  await new Promise((r) => setTimeout(r, 50));
  assert.deepEqual(feito, []); // RENOVACAO_RESPOSTAS_LIGADAS não está "true"
  const saude = await fetch(`http://127.0.0.1:${porta}/health`).then((r) => r.json());
  assert.equal(saude.caixa, 3);
  s.close();
});
