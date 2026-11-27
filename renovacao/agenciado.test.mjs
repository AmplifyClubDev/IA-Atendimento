import { test } from 'node:test';
import assert from 'node:assert/strict';
import { atenderAgenciado, ehJaSouAmplify, textoPerfil, textoRenovacao } from './agenciado.mjs';

const PERFIL = { tiktok: '@ana', nome: 'Ana Souza', situacao: 'Ativo', categoria: 'Silver', gmv_nivel: 7250.4,
  agenciado_em: '01/10/2026', contrato_inicio: '01/10/2026', contrato_fim: '01/12/2026', dias_para_vencer: 4,
  renovacao: 'Sem pedido', relation_id: '1' };

function falso(respostas) {
  const feito = [], pedidos = [];
  const db = { async rpc(nome, p) { pedidos.push(p); return respostas.shift(); } };
  const cw = {
    async mensagem(c, t) { feito.push(['mensagem', t]); },
    async lista(c, t, o) { feito.push(['lista', t, o]); },
    async etiqueta(c, e) { feito.push(['etiqueta', e]); },
    async nota(c, t) { feito.push(['nota', t]); },
  };
  return { db, cw, feito, pedidos };
}
const msg = (texto, extra = {}) => ({ mensagem: '1', conversa: '50', texto, ...extra });

test('reconhece o botão "Já sou Amplify"', () => {
  assert.equal(ehJaSouAmplify('Já sou Amplify'), true);
  assert.equal(ehJaSouAmplify('já sou amplify!'), true);
  assert.equal(ehJaSouAmplify('já sou amplify e quero renovar'), false);
});

test('Já sou Amplify: etiqueta primeiro (a Bia sai) e pede o @', async () => {
  const f = falso([{ etapa: 'pedir_arroba' }]);
  const r = await atenderAgenciado(msg('Já sou Amplify', { jaSou: true }), f);
  assert.equal(r.etapa, 'pedir_arroba');
  assert.equal(f.feito[0][1], 'Renovacao de contrato');
  assert.match(f.feito[1][1], /@ do TikTok/);
  assert.equal(f.pedidos[0].acao, 'iniciar');
});

test('@ encontrado → pede os 4 dígitos; não encontrado → pede de novo, sem limite', async () => {
  let f = falso([{ etapa: 'pedir_arroba' }, { etapa: 'pedir_cpf', status: 'encontrado', tiktok: '@ana', nome: 'Ana Souza' }]);
  await atenderAgenciado(msg('@ana'), f);
  assert.equal(f.pedidos[1].arroba, '@ana');
  assert.match(f.feito[0][1], /Achei você, Ana!/);
  assert.match(f.feito[0][1], /4 últimos dígitos/);
  f = falso([{ etapa: 'pedir_arroba' }, { etapa: 'pedir_arroba', status: 'nao_encontrado', tentativas: 1 }]);
  await atenderAgenciado(msg('@zz'), f);
  assert.match(f.feito[0][1], /Não achei esse @/);
  f = falso([{ etapa: 'pedir_arroba' }, { etapa: 'pedir_arroba', status: 'nao_encontrado', tentativas: 7 }]);
  await atenderAgenciado(msg('@zz'), f);
  assert.deepEqual(f.feito.map((x) => x[0]), ['mensagem']);
  assert.match(f.feito[0][1], /Não achei esse @/);
});

test('sem CPF no banco → link do formulário', async () => {
  const f = falso([{ etapa: 'pedir_arroba' }, { etapa: 'sem_cpf', status: 'sem_cpf', tiktok: '@ana' }]);
  await atenderAgenciado(msg('ana'), f);
  assert.match(f.feito[0][1], /amplify-cadastro\.up\.railway\.app\/cadastro/);
});

test('CPF: só os dígitos vão ao banco; confere → perfil com botões de renovação', async () => {
  const f = falso([{ etapa: 'pedir_cpf' }, { etapa: 'verificado', status: 'ok', perfil: PERFIL }]);
  const r = await atenderAgenciado(msg('final 12-34'), f);
  assert.equal(r.etapa, 'verificado');
  assert.equal(f.pedidos[1].digitos, '1234');
  assert.equal(f.feito[0][0], 'lista');
  assert.deepEqual(f.feito[0][2], ['Quero renovar', 'Não quero renovar']);
  assert.match(f.feito[0][1], /\*@ana\* · Ana Souza/);
  assert.match(f.feito[0][1], /faltam \*4 dias\*/);
  assert.doesNotMatch(JSON.stringify(f.feito), /1234/); // os dígitos não voltam para a conversa
});

test('CPF errado → pede de novo, sem limite e sem chamar o time', async () => {
  const f = falso([{ etapa: 'pedir_cpf' }, { etapa: 'pedir_cpf', status: 'nao_confere', tentativas: 5 }]);
  await atenderAgenciado(msg('9999'), f);
  assert.deepEqual(f.feito.map((x) => x[0]), ['mensagem']);
  assert.match(f.feito[0][1], /não conferem/);
  assert.doesNotMatch(f.feito[0][1], /tentativa/);
});

test('o telefone da conversa vai junto com o @ (atalho do WhatsApp do cadastro)', async () => {
  const f = falso([{ etapa: 'pedir_arroba' }, { etapa: 'pedir_cpf', status: 'encontrado', tiktok: '@ana', nome: 'Ana' }]);
  await atenderAgenciado(msg('@ana', { telefone: '+5547999990000' }), f);
  assert.equal(f.pedidos[1].telefone, '+5547999990000');
});

test('outro número: depois do CPF pede a data; data vai ao banco em AAAA-MM-DD; errado não diz qual', async () => {
  let f = falso([{ etapa: 'pedir_cpf' }, { etapa: 'pedir_nascimento', status: 'pedir_nascimento' }]);
  await atenderAgenciado(msg('1234'), f);
  assert.match(f.feito[0][1], /data de nascimento/);
  f = falso([{ etapa: 'pedir_nascimento' }, { etapa: 'verificado', status: 'ok', perfil: PERFIL }]);
  await atenderAgenciado(msg('15/03/1998'), f);
  assert.deepEqual(f.pedidos[1], { conversa: '50', acao: 'nascimento', nascimento: '1998-03-15' });
  assert.equal(f.feito[0][0], 'lista');
  f = falso([{ etapa: 'pedir_nascimento' }, { etapa: 'pedir_cpf', status: 'nao_confere', tentativas: 1 }]);
  await atenderAgenciado(msg('15/03/1998'), f);
  assert.match(f.feito[0][1], /Os dados não conferem/);
  assert.match(f.feito[0][1], /CPF/);
  f = falso([{ etapa: 'pedir_nascimento' }, { etapa: 'pedir_nascimento', status: 'formato_data' }]);
  await atenderAgenciado(msg('ontem'), f);
  assert.equal(f.pedidos[1].nascimento, null);
  assert.match(f.feito[0][1], /dia\/mês\/ano/);
});

test('lerData: formatos comuns e datas impossíveis', async () => {
  const { lerData } = await import('./agenciado.mjs');
  assert.equal(lerData('15/03/1998'), '1998-03-15');
  assert.equal(lerData('5-3-98'), '1998-03-05');
  assert.equal(lerData('15.03.2001'), '2001-03-15');
  assert.equal(lerData('15031998'), '1998-03-15');
  assert.equal(lerData('15 03 1998'), '1998-03-15');
  assert.equal(lerData('30/02/2000'), null);
  assert.equal(lerData('1998'), null);
});

test('conferido ou fora da conferência → segue para o fluxo de renovação', async () => {
  assert.equal(await atenderAgenciado(msg('Quero renovar'), falso([{ etapa: 'verificado' }])), null);
  assert.equal(await atenderAgenciado(msg('Quero renovar'), falso([{ etapa: null }])), null);
});

test('os dígitos do CPF não vão para a IA', async () => {
  const { mascarar } = await import('./ia.mjs');
  assert.equal(mascarar('1234'), '[número oculto]');
  assert.equal(mascarar('12-34'), '[número oculto]');
  assert.equal(mascarar('15/03/1998'), '[número oculto]');
  assert.equal(mascarar('15031998'), '[número oculto]');
  assert.equal(mascarar('faltam 4 dias'), 'faltam 4 dias');
  assert.equal(mascarar('01/12'), '01/12');
});

test('perfil: renovação confirmada e pedido aberto', () => {
  assert.match(textoRenovacao({ ...PERFIL, renovacao: 'Aceita', renovacao_novo_fim: '01/12/2027' }), /confirmada.*01\/12\/2027/);
  assert.match(textoRenovacao({ ...PERFIL, renovacao: 'Aguardando aceite', renovacao_expira_em: '05/12/2026' }), /Aceitar/);
  assert.match(textoRenovacao({ ...PERFIL, dias_para_vencer: 200 }), /em dia/);
  assert.match(textoPerfil(PERFIL), /GMV \(nível TikTok\): \*R\$\s?7\.250\*/);
  assert.match(textoPerfil(PERFIL), /Na Amplify desde: 01\/10\/2026/);
});

test('longe do fim (mais de 30 dias, sem pedido): perfil sem botões de renovação', async () => {
  const f = falso([{ etapa: 'pedir_cpf' }, { etapa: 'verificado', status: 'ok', perfil: { ...PERFIL, dias_para_vencer: 51 } }]);
  await atenderAgenciado(msg('1234'), f);
  assert.equal(f.feito[0][0], 'mensagem');
  assert.match(f.feito[0][1], /em dia/);
  assert.match(f.feito[0][1], /eu te aviso por aqui/);
  assert.doesNotMatch(f.feito[0][1], /Quer renovar/);
  const g = falso([{ etapa: 'pedir_cpf' }, { etapa: 'verificado', status: 'ok',
    perfil: { ...PERFIL, dias_para_vencer: 51, renovacao: 'Aguardando aceite' } }]);
  await atenderAgenciado(msg('1234'), g);
  assert.equal(g.feito[0][0], 'lista'); // pedido aberto no TikTok: botões mesmo longe do fim
});
