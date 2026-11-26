// Respostas aos botões do alerta de renovação (26/11/2026). Funções puras + o tratamento de uma mensagem.
// Botões do template renovacao_contrato: "Quero renovar" · "Não quero renovar" · "Tenho dúvidas".
import { ETIQUETA } from './envio.mjs';

export const MOTIVOS = [
  'Parei de vender',
  'Resultados abaixo',
  'Outra agência',
  'Seguir sem agência',
  'Outro motivo',
];
export const ETIQUETA_PEDIDO = 'renovacao-enviar-pedido';
export const ETIQUETA_NAO_QUER = 'renovacao-nao-quer';
export const ETIQUETA_ATENCAO = 'renovacao-atencao';

const normalizar = (t) => String(t || '').normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase().replace(/\s+/g, ' ').trim();

// O que a pessoa respondeu. "ultima" é a resposta anterior nesta conversa (para saber se estamos esperando o motivo).
export function classificar(texto, ultima = null) {
  const t = normalizar(texto);
  if (!t) return { resposta: 'outro' };
  if (/^nao quero( renovar)?$/.test(t) || t.startsWith('nao quero renovar')) return { resposta: 'nao_quero' };
  if (/^(quero renovar|quero sim|sim,? quero|renovar)\b/.test(t)) return { resposta: 'quero' };
  if (/^tenho duvidas?\b/.test(t)) return { resposta: 'duvida' };
  if (ultima === 'nao_quero') {
    const motivo = MOTIVOS.find((m) => normalizar(m) === t) || String(texto).trim().slice(0, 200);
    return { resposta: 'motivo', motivo };
  }
  return { resposta: 'outro' };
}

// O que fazer para cada resposta. "envio" vem do banco (contrato_fim dd/mm e a situação do pedido no TikTok).
export function planejar(resposta, envio = null, motivo = null) {
  const fim = envio?.contrato_fim ? `*${envio.contrato_fim}*` : 'a data do seu contrato';
  if (resposta === 'quero') {
    const pedidoAberto = envio?.renovacao === 'Aguardando aceite';
    return {
      mensagens: [pedidoAberto
        ? '*Perfeito, falta só um toque!* 🙌\n\n📲 O pedido de renovação já está no seu TikTok.\n\n👉 Abra *TikTok › Notificações* e toque em *Aceitar*.\n\nAssim que você aceitar, eu te aviso por aqui que está tudo certo. 💙'
        : '*Perfeito, já está a caminho!* 🙌\n\n📲 Vamos enviar o pedido de renovação para o seu TikTok ainda hoje.\n\n👉 Quando ele chegar, abra *TikTok › Notificações* e toque em *Aceitar*.\n\nAssim que você aceitar, eu te aviso por aqui que está tudo certo. 💙'],
      nota: pedidoAberto ? null : '🔁 Quer renovar e ainda não tem pedido no TikTok: enviar o pedido de renovação no Partner Center.',
      etiquetas: pedidoAberto ? [] : [ETIQUETA_PEDIDO],
      tirarRenovacao: false,
    };
  }
  if (resposta === 'nao_quero') {
    return {
      lista: { texto: '*Poxa, vamos sentir sua falta!* 💙\n\nAntes de você ir, pode contar pra gente o que pesou na decisão? Leva só 1 toque e nos ajuda muito a melhorar. 👇', opcoes: MOTIVOS },
      etiquetas: [ETIQUETA_NAO_QUER], tirarRenovacao: false,
    };
  }
  if (resposta === 'motivo') {
    return {
      mensagens: [`*Obrigado por compartilhar!* 🙏\n\nSua resposta já chegou para o nosso time.\n\n📅 Seu contrato segue ativo até ${fim}.\n\nSe mudar de ideia, é só responder *RENOVAR* aqui que a gente resolve na hora. 😉`],
      nota: `⚠️ Retenção: não quer renovar. Motivo: ${motivo || '—'}. Contrato até ${envio?.contrato_fim || '—'}.`,
      // A etiqueta de renovação fica até o contrato acabar: se a pessoa responder "RENOVAR", cai aqui de novo.
      etiquetas: [], tirarRenovacao: false,
    };
  }
  if (resposta === 'duvida') {
    // A Bia assume: tira a etiqueta de renovação (a Bia ignora conversas com ela) e convida a pessoa a perguntar.
    return {
      mensagens: ['*Claro, estamos aqui pra te ajudar!* 💬\n\nPode mandar sua dúvida sobre a renovação que eu te respondo. 💙'],
      nota: '💬 Agenciado com dúvida sobre renovação: a Bia assumiu a conversa.',
      etiquetas: [], tirarRenovacao: true,
    };
  }
  return { nota: '👀 Resposta fora dos botões na conversa de renovação: conferir.', etiquetas: [ETIQUETA_ATENCAO], tirarRenovacao: false };
}

// Mensagem recebida do Chatwoot (evento message_created). Devolve null quando não é nossa.
export function lerEvento(evento, caixa) {
  if (!evento || evento.event !== 'message_created' || evento.message_type !== 'incoming' || evento.private) return null;
  const conversa = evento.conversation || {};
  const inbox = conversa.inbox_id ?? evento.inbox?.id;
  if (Number(inbox) !== Number(caixa)) return null;
  if (!(conversa.labels || []).includes(ETIQUETA)) return null;
  const id = String(evento.id || ''), conversaId = String(conversa.id || '');
  if (!/^\d{1,18}$/.test(id) || !/^\d{1,18}$/.test(conversaId)) return null;
  return { mensagem: id, conversa: conversaId, texto: String(evento.content || '').slice(0, 500),
    telefone: evento.sender?.phone_number || conversa.meta?.sender?.phone_number || null };
}

// Trata uma mensagem: registra no banco e responde. Devolve o que foi feito (para o log).
export async function tratar(msg, { db, cw }) {
  const anteriores = await db.ultimaResposta(msg.conversa);
  const { resposta, motivo } = classificar(msg.texto, anteriores);
  const reg = await db.rpc('registrar_resposta_renovacao_v5', {
    mensagem: msg.mensagem, conversa: msg.conversa, telefone: msg.telefone, resposta, motivo, texto: msg.texto });
  if (reg.status === 'repetida') return { resposta, status: 'repetida' };
  const plano = planejar(resposta, reg.envio, motivo);
  for (const texto of plano.mensagens || []) await cw.mensagem(msg.conversa, texto);
  if (plano.lista) await cw.lista(msg.conversa, plano.lista.texto, plano.lista.opcoes);
  for (const e of plano.etiquetas || []) await cw.etiqueta(msg.conversa, e);
  if (plano.nota) await cw.nota(msg.conversa, plano.nota);
  if (plano.tirarRenovacao) await cw.tirarEtiqueta(msg.conversa, ETIQUETA);
  return { resposta, status: 'tratada' };
}
