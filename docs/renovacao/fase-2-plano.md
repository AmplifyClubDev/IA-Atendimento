# Renovação de contrato · Fase 2: plano do sistema novo (23/11/2026)

**Em 1 linha:** tudo nasce e fica no Supabase. A data vem do TikTok, a régua manda pela caixa 1, e o sistema sabe
quando a pessoa renovou. O n8n fica só como referência e é desligado no dia da troca.

## O maior problema hoje: telefone

| Agenciados ativos | Com telefone no nosso Supabase |
|---|---|
| 1.536 | **238** (15%) |
| Vencem em 30 dias: 223 | **6** |
| Vencem em 7 dias: 62 | **2** |

Os telefones estão em outro Supabase ("Base de dados - Amplify", tabela `criadores`) e no Notion. É isso que o
n8n usa. O token atual só enxerga o nosso projeto. **Sem trazer os telefones, a régua nova não chega em quase ninguém.**

## Como vai funcionar

```
TikTok (de hora em hora) ──► agenciados_tiktok (data de fim)
                                   │
                                   ▼
                    renovacoes (1 por contrato a vencer)
        pendente → pedido enviado → renovou ✅ / recusou / venceu
                                   │
                    régua: 7 dias · 2 dias · no dia
                                   │
                    envios (nunca manda a mesma etapa 2x)
                                   │
                                   ▼
                Chatwoot caixa 1 → WhatsApp (template)
                                   │
             botões: Já aceitei · Preciso de ajuda · Não quero renovar
```

- **Renovou?** Quando a data de fim avança na coleta seguinte, marca como renovado, para a régua e manda a confirmação.
- **Sem duplicar:** cada etapa só pode ser enviada uma vez por contrato (trava no banco).
- **Horário:** só entre 9h e 20h (Brasília).
- **Isolado da Bia:** um serviço pequeno separado, para um erro aqui nunca derrubar o atendimento da caixa 3.

## Rascunho dos textos (para revisarmos juntos)

Todos com vídeo do passo a passo, categoria UTILITY.

**1. Semana do vencimento (7 dias antes)** · `renovacao_semana`
> Oi, {{1}}! 💙
>
> Seu vínculo com a Amplify no TikTok Shop vence em *{{2}}*.
>
> Já enviamos o pedido de renovação. É só abrir o TikTok, ir em *Notificações* e tocar em *Aceitar*.
> O vídeo mostra o passo a passo.
>
> Botões: `Já aceitei` · `Preciso de ajuda` · `Não quero renovar`

**2. Lembrete (2 dias antes, só se ainda não renovou)** · `renovacao_lembrete`
> Oi, {{1}}! Seu vínculo vence em *{{2}} dias* e o pedido de renovação ainda está esperando o seu aceite.
>
> Leva menos de 1 minuto: TikTok › Notificações › *Aceitar*. 😉

**3. No dia (só se ainda não renovou)** · `renovacao_hoje`
> Oi, {{1}}! Seu vínculo com a Amplify vence *hoje*.
>
> Para não perder seus benefícios, aceite o pedido de renovação no TikTok (Notificações › *Aceitar*).

**4. Renovação confirmada** · `renovacao_confirmada`
> Renovação confirmada ✅
>
> {{1}}, seu vínculo com a Amplify segue até *{{2}}*. Que bom continuar com você! 💙

## Fases

| # | Fase | Mexe em produção? |
|---|---|---|
| A | **Telefones no Supabase:** importar do outro Supabase e do Notion, com origem e data | Banco (tabela nova) |
| B | **Banco da renovação:** `renovacoes` + `renovacao_envios` + detecção de renovação na coleta | Banco + Bia (coleta) |
| C | **Textos e templates:** fechar os textos juntos e mandar para a Meta (caixa 1) | Meta |
| D | **Régua:** serviço novo; teste só com o seu número; depois desliga o n8n e liga para todos | Railway + n8n |
| E | **Respostas na caixa 1:** botões, alerta "não quero renovar" pro time, dúvidas com IA | Chatwoot caixa 1 |
| F | **Pedido de renovação no TikTok** por Playwright, numa ponte já logada | Ponte |
| G | **Boas-vindas, acesso ao Circle e alertas** para agenciados | Caixa 1 |

Até a fase D entrar, o n8n continua como está. Ninguém fica sem mensagem.

## O que preciso de você

1. Acesso ao Supabase "Base de dados - Amplify" (só leitura), ou uma exportação de `criadores` com @ e telefone.
2. Aprovar as fases (e o que corrigir no plano).
3. Revisar os 4 textos.
