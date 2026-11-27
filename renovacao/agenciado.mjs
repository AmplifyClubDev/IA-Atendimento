// "Já sou Amplify" (27/11/2026): quem toca esse botão no menu da Bia (caixa 3) é atendido aqui, pela Bia dos agenciados.
// Pede o @ → acha o agenciado → pede os 4 últimos dígitos do CPF → o banco confere (o CPF nunca sai do banco)
// → mostra o perfil (contrato, categoria, GMV, renovação) com os botões de renovação. Depois disso, a conversa
// segue no fluxo de renovação (respostas.mjs), que passa a aceitar esta conversa porque o agenciado foi conferido.
import { ETIQUETA } from './envio.mjs';
import { BOTOES_DECISAO, ETIQUETA_ATENCAO, normalizar } from './respostas.mjs';

export const FORMULARIO = 'https://amplify-cadastro.up.railway.app/cadastro';
export const ehJaSouAmplify = (texto) => normalizar(texto) === 'ja sou amplify';

const MSG = {
  pedirArroba: '*Que bom te ver por aqui!* 💙\n\nPra eu abrir o seu perfil, me manda o seu *@ do TikTok*.',
  naoAchei: '*Não achei esse @ entre os agenciados* 🤔\n\n• Confere se está escrito igual ao TikTok.\n• Pode mandar só o @ (ex.: @seuperfil).',
  naoAcheiTime: '*Não consegui achar o seu perfil* 🤔\n\nVou chamar alguém do nosso time pra te ajudar. 💙',
  pedirCpf: (nome) => `*Achei você${nome ? `, ${nome}` : ''}!* 🙌\n\nPra sua segurança, me manda os *4 últimos dígitos do seu CPF*.\n\n🔒 Eu só confiro; o número não fica salvo na conversa.`,
  formato: '*Preciso só dos 4 últimos dígitos do CPF* 🔢\n\nExemplo: se o CPF termina em 12-34, mande *1234*.',
  naoConfere: (resta) => `*Esses dígitos não conferem* 😕\n\nConfere e manda de novo. ${resta === 1 ? 'Você tem mais *1 tentativa*.' : `Você tem mais *${resta} tentativas*.`}`,
  bloqueado: '*Não consegui confirmar seus dados* 🔒\n\nPra sua segurança, vou passar pro nosso time te atender. 💙',
  semCpf: `*Achei você, mas falta atualizar seu cadastro* 📝\n\nPra eu mostrar seu perfil com segurança, preciso que você preencha o formulário:\n${FORMULARIO}\n\n• Informe o seu @ do TikTok.\n• Ele confere seu agenciamento antes de liberar o cadastro.\n\nDepois é só tocar em *Já sou Amplify* de novo. 😉`,
};

const real = (v) => Number(v || 0).toLocaleString('pt-BR', { style: 'currency', currency: 'BRL', maximumFractionDigits: 0 });

export function textoRenovacao(p) {
  if (p.situacao === 'Saindo') return 'desvinculação em andamento.';
  if (p.renovacao === 'Aceita') return `*confirmada* ✅${p.renovacao_novo_fim ? ` (contrato vai até ${p.renovacao_novo_fim})` : ''}.`;
  if (p.renovacao === 'Aguardando aceite') {
    return `*pedido no seu TikTok* 📲${p.renovacao_expira_em ? ` (aceite até ${p.renovacao_expira_em})` : ''}.\n   👉 Abra *TikTok › Notificações* e toque em *Aceitar*.`;
  }
  if (p.dias_para_vencer != null && p.dias_para_vencer <= 30) return '*ainda não renovado*.';
  return 'ainda não é hora: seu contrato está em dia. 👍';
}

// Perfil conferido, sem CPF nem telefone.
export function textoPerfil(p) {
  const dias = p.dias_para_vencer != null && p.dias_para_vencer >= 0 ? ` (faltam *${p.dias_para_vencer} dias*)` : '';
  return [
    '*Pronto, conferi! Este é o seu perfil na Amplify* 💙',
    '',
    `👤 *${p.tiktok}*${p.nome ? ` · ${p.nome}` : ''}`,
    `• Situação: *${p.situacao}*`,
    `• Categoria: *${p.categoria || 'Start'}*`,
    `• GMV: *${real(p.gmv_nivel)}*`,
    p.agenciado_em ? `• Agenciado desde: ${p.agenciado_em}` : null,
    `• Contrato: ${p.contrato_inicio || '—'} até *${p.contrato_fim || '—'}*${dias}`,
    `• Renovação: ${textoRenovacao(p)}`,
  ].filter((l) => l !== null).join('\n');
}

async function passarParaTime(msg, cw, texto, nota) {
  await cw.mensagem(msg.conversa, texto);
  await cw.etiqueta(msg.conversa, ETIQUETA_ATENCAO);
  await cw.nota(msg.conversa, nota);
}

async function mostrarPerfil(msg, cw, perfil) {
  if (!perfil) {
    await passarParaTime(msg, cw, MSG.naoAcheiTime, '👀 Já sou Amplify: conferido, mas o perfil não foi encontrado. Atender manualmente.');
    return;
  }
  const texto = textoPerfil(perfil);
  if (perfil.renovacao === 'Aceita' || perfil.situacao === 'Saindo') {
    await cw.mensagem(msg.conversa, `${texto}\n\nSe tiver alguma dúvida, é só mandar por aqui. 😉`);
  } else {
    await cw.lista(msg.conversa, `${texto}\n\nQuer renovar seu contrato? Se tiver dúvida, é só mandar por aqui. 😉`.slice(0, 1000), BOTOES_DECISAO);
  }
  await cw.nota(msg.conversa, `✅ Já sou Amplify: identidade conferida (${perfil.tiktok}).`);
}

// Devolve null quando a conversa não está na conferência (segue para o fluxo de renovação).
export async function atenderAgenciado(msg, { db, cw }) {
  const rpc = (acao, extra = {}) => db.rpc('atendimento_agenciado_v5', { conversa: msg.conversa, acao, ...extra });
  if (msg.jaSou) {
    // Etiqueta primeiro: com ela, a Bia de aquisição não responde mais nesta conversa.
    await cw.etiqueta(msg.conversa, ETIQUETA);
    const r = await rpc('iniciar');
    if (r.etapa === 'bloqueado') {
      await passarParaTime(msg, cw, MSG.bloqueado, '🔒 Já sou Amplify: conferência bloqueada (3 erros nas últimas 24h). Atender manualmente.');
      return { status: 'agenciado', etapa: 'bloqueado' };
    }
    await cw.mensagem(msg.conversa, MSG.pedirArroba);
    return { status: 'agenciado', etapa: 'pedir_arroba' };
  }
  const atual = await rpc('consultar');
  if (!atual.etapa || atual.etapa === 'verificado') return null;
  if (atual.etapa === 'bloqueado' || atual.etapa === 'sem_cpf') return { status: 'agenciado', etapa: atual.etapa, silencio: true };

  if (atual.etapa === 'pedir_arroba') {
    const r = await rpc('arroba', { arroba: msg.texto.trim().slice(0, 120) });
    if (r.status === 'nao_encontrado') {
      if (r.tentativas >= 3) await passarParaTime(msg, cw, MSG.naoAcheiTime, '👀 Já sou Amplify: @ não encontrado 3 vezes. Atender manualmente.');
      else await cw.mensagem(msg.conversa, MSG.naoAchei);
    } else if (r.status === 'sem_cpf') {
      await cw.mensagem(msg.conversa, MSG.semCpf);
      await cw.nota(msg.conversa, `📝 Já sou Amplify: ${r.tiktok} é agenciado, mas não tem CPF no cadastro. Link do formulário enviado.`);
    } else {
      await cw.mensagem(msg.conversa, MSG.pedirCpf(String(r.nome || '').split(' ')[0]));
    }
    return { status: 'agenciado', etapa: r.etapa };
  }

  // pedir_cpf: só os dígitos vão para o banco; a resposta nunca traz o CPF.
  const r = await rpc('cpf', { digitos: msg.texto.replace(/\D/g, '') });
  if (r.status === 'formato') await cw.mensagem(msg.conversa, MSG.formato);
  else if (r.status === 'nao_confere' && r.etapa === 'bloqueado') {
    await passarParaTime(msg, cw, MSG.bloqueado, '🔒 Já sou Amplify: CPF não conferiu 3 vezes. Atender manualmente.');
  } else if (r.status === 'nao_confere') await cw.mensagem(msg.conversa, MSG.naoConfere(3 - r.tentativas));
  else if (r.status === 'ok') await mostrarPerfil(msg, cw, r.perfil);
  return { status: 'agenciado', etapa: r.etapa };
}
