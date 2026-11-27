// "Já sou Amplify" (27/11/2026): quem toca esse botão no menu da Bia (caixa 3) é atendido aqui, pela Bia dos agenciados.
// Pede o @ → acha o agenciado → pede os 4 últimos dígitos do CPF → se o WhatsApp não é o do cadastro, pede também
// a data de nascimento → o banco confere (CPF e nascimento nunca saem do banco; sem limite de tentativas)
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
  // Não diz qual dado errou (CPF ou nascimento): recomeça pelo CPF.
  naoConfere: '*Os dados não conferem* 😕\n\nVamos de novo: me manda os *4 últimos dígitos do seu CPF*.',
  pedirNascimento: '*Só mais uma confirmação* 🔒\n\nComo este número é diferente do seu cadastro, me manda também a sua *data de nascimento*.\n\nExemplo: *15/03/1998*',
  formatoData: '*Não entendi a data* 📅\n\nManda assim: *dia/mês/ano*. Exemplo: *15/03/1998*',
  pedirCpf: (nome) => `*Achei você${nome ? `, ${nome}` : ''}!* 🙌\n\nPra sua segurança, me manda os *4 últimos dígitos do seu CPF*.\n\n🔒 Eu só confiro; o número não fica salvo na conversa.`,
  formato: '*Preciso só dos 4 últimos dígitos do CPF* 🔢\n\nExemplo: se o CPF termina em 12-34, mande *1234*.',
  semCpf: `*Achei você, mas falta atualizar seu cadastro* 📝\n\nPra eu mostrar seu perfil com segurança, preciso que você preencha o formulário:\n${FORMULARIO}\n\n• Informe o seu @ do TikTok.\n• Ele confere seu agenciamento antes de liberar o cadastro.\n\nDepois é só tocar em *Já sou Amplify* de novo. 😉`,
};

// "15/03/1998", "15-03-98", "15.3.1998", "15031998" → "1998-03-15". Data impossível → null (o banco pede de novo).
export function lerData(texto) {
  const t = String(texto || '').trim();
  let m = t.match(/^(\d{1,2})\s*[/.\-\s]\s*(\d{1,2})\s*[/.\-\s]\s*(\d{2}|\d{4})$/);
  if (!m) m = t.match(/^(\d{2})(\d{2})(\d{4})$/);
  if (!m) return null;
  const dia = Number(m[1]), mes = Number(m[2]);
  let ano = Number(m[3]);
  if (m[3].length === 2) ano += ano > (new Date().getFullYear() % 100) ? 1900 : 2000;
  const d = new Date(Date.UTC(ano, mes - 1, dia));
  if (d.getUTCFullYear() !== ano || d.getUTCMonth() !== mes - 1 || d.getUTCDate() !== dia) return null;
  return d.toISOString().slice(0, 10);
}

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

// Botões de renovação só quando faz sentido: pedido aberto no TikTok ou até 30 dias do fim (nunca para quem já renovou ou está saindo).
export const horaDeRenovar = (p) => p.situacao !== 'Saindo' && p.renovacao !== 'Aceita'
  && (p.renovacao === 'Aguardando aceite' || (p.dias_para_vencer != null && p.dias_para_vencer <= 30));

// Perfil conferido, sem CPF nem telefone.
export function textoPerfil(p) {
  const dias = p.dias_para_vencer != null && p.dias_para_vencer >= 0 ? ` (faltam *${p.dias_para_vencer} dias*)` : '';
  return [
    '*Pronto, conferi! Este é o seu perfil na Amplify* 💙',
    '',
    `👤 *${p.tiktok}*${p.nome ? ` · ${p.nome}` : ''}`,
    `• Situação: *${p.situacao}*`,
    `• Categoria: *${p.categoria || 'Start'}*`,
    `• GMV (nível TikTok): *${real(p.gmv_nivel)}*`,
    p.agenciado_em ? `• Na Amplify desde: ${p.agenciado_em}` : null,
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
  if (horaDeRenovar(perfil)) {
    await cw.lista(msg.conversa, `${texto}\n\nQuer renovar seu contrato? Se tiver dúvida, é só mandar por aqui. 😉`.slice(0, 1000), BOTOES_DECISAO);
  } else if (perfil.renovacao === 'Aceita' || perfil.situacao === 'Saindo') {
    await cw.mensagem(msg.conversa, `${texto}\n\nSe tiver alguma dúvida, é só mandar por aqui. 😉`);
  } else {
    await cw.mensagem(msg.conversa, `${texto}\n\nQuando estiver perto do fim, eu te aviso por aqui. Se tiver alguma dúvida, é só mandar. 😉`);
  }
  await cw.nota(msg.conversa, `✅ Já sou Amplify: identidade conferida (${perfil.tiktok}).`);
}

// Devolve null quando a conversa não está na conferência (segue para o fluxo de renovação).
export async function atenderAgenciado(msg, { db, cw }) {
  const rpc = (acao, extra = {}) => db.rpc('atendimento_agenciado_v5', { conversa: msg.conversa, acao, ...extra });
  if (msg.jaSou) {
    // Etiqueta primeiro: com ela, a Bia de aquisição não responde mais nesta conversa.
    await cw.etiqueta(msg.conversa, ETIQUETA);
    await rpc('iniciar');
    await cw.mensagem(msg.conversa, MSG.pedirArroba);
    return { status: 'agenciado', etapa: 'pedir_arroba' };
  }
  const atual = await rpc('consultar');
  if (!atual.etapa || atual.etapa === 'verificado') return null;
  if (atual.etapa === 'sem_cpf') return { status: 'agenciado', etapa: atual.etapa, silencio: true };

  if (atual.etapa === 'pedir_arroba') {
    // O telefone da conversa: se for o do cadastro, o banco dispensa a data de nascimento.
    const r = await rpc('arroba', { arroba: msg.texto.trim().slice(0, 120), telefone: msg.telefone || null });
    if (r.status === 'nao_encontrado') {
      await cw.mensagem(msg.conversa, MSG.naoAchei); // sem limite de tentativas
    } else if (r.status === 'sem_cpf') {
      await cw.mensagem(msg.conversa, MSG.semCpf);
      await cw.nota(msg.conversa, `📝 Já sou Amplify: ${r.tiktok} é agenciado, mas não tem CPF no cadastro. Link do formulário enviado.`);
    } else {
      await cw.mensagem(msg.conversa, MSG.pedirCpf(String(r.nome || '').split(' ')[0]));
    }
    return { status: 'agenciado', etapa: r.etapa };
  }

  // pedir_cpf / pedir_nascimento: só os dados vão para o banco; a resposta nunca traz CPF nem data.
  const r = atual.etapa === 'pedir_nascimento'
    ? await rpc('nascimento', { nascimento: lerData(msg.texto) })
    : await rpc('cpf', { digitos: msg.texto.replace(/\D/g, '') });
  if (r.status === 'formato') await cw.mensagem(msg.conversa, MSG.formato);
  else if (r.status === 'formato_data') await cw.mensagem(msg.conversa, MSG.formatoData);
  else if (r.status === 'pedir_nascimento') await cw.mensagem(msg.conversa, MSG.pedirNascimento);
  else if (r.status === 'nao_confere') await cw.mensagem(msg.conversa, MSG.naoConfere); // sem limite de tentativas
  else if (r.status === 'ok') await mostrarPerfil(msg, cw, r.perfil);
  return { status: 'agenciado', etapa: r.etapa };
}
