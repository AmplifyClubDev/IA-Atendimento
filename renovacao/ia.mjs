// "Bia dos agenciados" (26/11/2026): responde dúvidas na conversa de renovação, com a mesma personalidade,
// conhecimento e limites da Bia (cartões de public.bia_contextos_ativos) e os dados do contrato da pessoa.
// A Bia de aquisição não entra (a conversa mantém a etiqueta de renovação). Sem certeza → passa para o time.
// Variáveis: OPENAI_API_KEY, RENOVACAO_MODELO (padrão gpt-4.1),
//            RENOVACAO_TESTE_TELEFONE + RENOVACAO_TESTE_RELATION (só teste: usa o contrato de um agenciado real).

const CACHE_MS = 600000;
let cache = { em: 0, cartoes: [] };

const CONHECIMENTO_RENOVACAO = `Renovação de contrato (regras confirmadas):
- Todo agenciado começa com um contrato de 2 meses. A renovação estende o contrato por mais 1 ano.
- A renovação é feita pelo TikTok: a Amplify envia um pedido de renovação e a pessoa aceita em TikTok › Notificações › Aceitar.
- O pedido de renovação vale por alguns dias; se expirar, a Amplify pode enviar de novo (há um limite de pedidos por contrato).
- Se a pessoa não renovar, o vínculo com a Amplify termina na data de fim do contrato.
- Renovar mantém a parceria ativa com a Amplify. Se a pessoa perguntar de mudança de condições, comissão nova ou benefícios
  específicos depois da renovação, isso não está confirmado aqui: passe para o time.
- Para renovar por aqui, a pessoa pode responder "RENOVAR".
- Não renovar NÃO tem cobrança nem multa: a parceria só termina na data de fim do contrato (confirmado pela Amplify em 26/11).
  Diga isso de forma direta ("não há cobrança nenhuma"), sem "confirmada" e sem oferecer conferir com o time.
- Só use fatos desta lista, dos dados da pessoa e do conhecimento da Amplify.`;

export async function carregarCartoes(db, agora = Date.now()) {
  if (agora - cache.em < CACHE_MS && cache.cartoes.length) return cache.cartoes;
  const cartoes = await db.ler('bia_contextos_ativos', 'select=tipo,titulo,conteudo');
  cache = { em: agora, cartoes };
  return cartoes;
}

export async function dadosDoAgenciado(db, { relationId, telefone }, env = process.env) {
  const tel = String(telefone || '').replace(/\D/g, '');
  let rel = relationId;
  // Números de teste (um ou mais, separados por vírgula) usam o contrato de RENOVACAO_TESTE_RELATION.
  const testes = String(env.RENOVACAO_TESTE_TELEFONE || '').split(',').map((t) => t.replace(/\D/g, '')).filter(Boolean);
  if (!rel && tel && testes.includes(tel)) rel = env.RENOVACAO_TESTE_RELATION;
  const campos = 'select=tiktok,nome,situacao,agenciado_em,contrato_inicio,contrato_fim,dias_para_vencer,categoria,gmv_nivel,comissao_pct,renovacao,renovacao_expira_em,renovacao_novo_fim';
  if (rel && /^[0-9A-Za-z_-]{1,64}$/.test(rel)) {
    const r = await db.ler('agenciados_ficha', `${campos}&relation_id=eq.${rel}&limit=1`);
    if (r[0]) return r[0];
  }
  if (/^\d{10,15}$/.test(tel)) {
    const r = await db.ler('agenciados_ficha', `${campos}&telefone=eq.${tel}&situacao=neq.Saiu&order=contrato_fim.desc.nullslast&limit=1`);
    if (r[0]) return r[0];
  }
  return null;
}

const dataBR = (v) => (v ? String(v).slice(0, 10).split('-').reverse().join('/') : '—');

export function montarInstrucoes(cartoes, ag) {
  const por = (tipo) => cartoes.filter((c) => c.tipo === tipo).map((c) => `### ${c.titulo}\n${c.conteudo}`).join('\n\n');
  const ficha = ag ? `Dados desta pessoa (do Partner Center, atualizados de hora em hora):
- TikTok: ${ag.tiktok} · nome: ${ag.nome || '—'} · situação: ${ag.situacao}
- Agenciada desde: ${dataBR(ag.agenciado_em)} · contrato atual: ${dataBR(ag.contrato_inicio)} até ${dataBR(ag.contrato_fim)} (faltam ${ag.dias_para_vencer ?? '—'} dias)
- Categoria Amplify: ${ag.categoria || '—'} · GMV: R$ ${ag.gmv_nivel ?? '—'} · comissão da agência: ${ag.comissao_pct ?? '—'}%
- Pedido de renovação no TikTok: ${ag.renovacao || 'Sem pedido'}${ag.renovacao_expira_em ? ` (expira ${dataBR(ag.renovacao_expira_em)})` : ''}${ag.renovacao_novo_fim ? ` · novo fim se aceitar: ${dataBR(ag.renovacao_novo_fim)}` : ''}`
    : 'Não encontramos o contrato desta pessoa pelo número. Não invente datas: diga que vai confirmar com o time (passar_para_time = true) se ela perguntar do prazo.';
  return `${por('personalidade')}

## SITUAÇÃO DESTA CONVERSA (mais importante que qualquer roteiro de aquisição)
Esta pessoa JÁ É AGENCIADA da Amplify. Ela recebeu o aviso de renovação de contrato e tem uma dúvida.
- Nunca trate como lead novo: não ofereça agenciamento, não peça @ para conferir perfil, não fale de convite de entrada, formulário ou cadastro.
- Responda só sobre o contrato, a renovação e a parceria.

## FORMATO DA RESPOSTA (WhatsApp, obrigatório)
- 1ª linha: a resposta direta em *negrito* (com *asteriscos*), curta, com 1 emoji no fim.
- Depois uma linha em branco e 1 a 3 linhas curtas de explicação. Se houver itens ou passos, use "• " ou 1️⃣ 2️⃣ 3️⃣, um por linha.
- Datas e valores importantes em *negrito*. No máximo 2 emojis na mensagem toda. Sem parágrafos longos.
- Se fizer sentido, termine com uma linha curta de próximo passo (ex.: como renovar) ou "Posso te ajudar em mais alguma coisa? 💙".
- Nunca termine oferecendo "pedir pro time conferir" quando você já respondeu. Responda com segurança o que está aqui.
Exemplo de formato:
*Não precisa pagar nada pra renovar!* 💙

• Sem mensalidade e sem taxa fixa
• A Amplify fica com *10%* das comissões, como já é hoje

Quer renovar? É só abrir *TikTok › Notificações* e tocar em *Aceitar*.
- Se a pessoa disser que quer renovar, intencao = "quero_renovar". Se disser que não quer, intencao = "nao_quero".
- Só passe para o time (passar_para_time = true, dizendo que alguém do time vai responder) quando a pergunta for de outro assunto
  que não está aqui (saque, problema na conta, campanha específica) ou quando a pessoa pedir para falar com alguém.
  Dúvidas sobre o contrato e a renovação você responde sozinha.

${ficha}

## RENOVAÇÃO
${CONHECIMENTO_RENOVACAO}

## CONHECIMENTO DA AMPLIFY
${por('conhecimento')}

## LIMITES
${por('limites')}

Responda em JSON: {"resposta": texto para a pessoa, "intencao": "quero_renovar" | "nao_quero" | "duvida" | "outro", "passar_para_time": true/false}.`;
}

const ESQUEMA = {
  type: 'json_schema',
  json_schema: { name: 'resposta_bia', strict: true, schema: { type: 'object', additionalProperties: false,
    required: ['resposta', 'intencao', 'passar_para_time'],
    properties: { resposta: { type: 'string' }, intencao: { type: 'string', enum: ['quero_renovar', 'nao_quero', 'duvida', 'outro'] },
      passar_para_time: { type: 'boolean' } } } },
};

export async function perguntarIA({ instrucoes, historico, env = process.env, chamar = fetch }) {
  const r = await chamar('https://api.openai.com/v1/chat/completions', {
    method: 'POST', signal: AbortSignal.timeout(30000),
    headers: { Authorization: `Bearer ${env.OPENAI_API_KEY}`, 'Content-Type': 'application/json' },
    body: JSON.stringify({ model: env.RENOVACAO_MODELO || 'gpt-4.1', temperature: 0.3, response_format: ESQUEMA,
      messages: [{ role: 'system', content: instrucoes }, ...historico] }),
  });
  if (!r.ok) throw new Error(`openai ${r.status}`);
  const j = await r.json();
  const saida = JSON.parse(j.choices?.[0]?.message?.content || '{}');
  if (typeof saida.resposta !== 'string' || !saida.resposta.trim()) throw new Error('resposta vazia');
  return { resposta: saida.resposta.trim().slice(0, 1200), intencao: saida.intencao, passarParaTime: saida.passar_para_time === true };
}

// CPF e números longos que a pessoa digitar não vão para a IA.
// Uma mensagem que é só um número curto (ex.: os 4 últimos dígitos do CPF no "Já sou Amplify") também fica oculta.
const soNumeroCurto = (t) => /^[\s\d.\-]+$/.test(t) && /^\d{3,6}$/.test(t.replace(/\D/g, ''));
export const mascarar = (t) => (soNumeroCurto(String(t)) ? '[número oculto]'
  : String(t).replace(/\d{9,}/g, '[número oculto]').replace(/\d{3}\.\d{3}\.\d{3}-?\d{2}/g, '[número oculto]'));

// Últimas mensagens da conversa (sem notas internas), no formato da IA.
export function historicoDe(mensagens, limite = 12) {
  return mensagens.filter((m) => !m.private && (m.message_type === 0 || m.message_type === 1) && (m.content || '').trim())
    .sort((a, b) => a.created_at - b.created_at).slice(-limite)
    .map((m) => ({ role: m.message_type === 0 ? 'user' : 'assistant', content: mascarar(String(m.content).slice(0, 800)) }));
}
