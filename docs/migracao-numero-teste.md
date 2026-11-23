# Migração: número de teste (contato 3) vira lead real — plano testado (22/11/2026)

**Em 1 linha:** apagar os 9 vínculos do contato 3 no banco da demo (com backup), trocar 7 variáveis e reiniciar a Bia.
Testado numa simulação completa com cópias do `/data` de produção: a Bia sobe e a conversa 59081 fica liberada.

## Por que a tentativa de 22/11 07:57 derrubou a Bia

O modo demonstração guarda em `/data/bia-demo-test.sqlite3`, tabela `demo_conversation_bindings`, as conversas que
cada demonstração "segura" fora do atendimento real. Se a configuração tira uma demonstração que ainda tem vínculos,
a Bia **não sobe** (`demo_conversation_binding_owner_changed`), para nunca liberar conversa de teste por engano.
O contato 3 tem 9 vínculos (58151, 58387, 58416, 58558, 58580, 58753, 58759, 58993, 59081).

## Simulação (cópias de produção, sem rede)

| Cenário | Sobe? | Teste real | 59081 |
|---|---|---|---|
| Hoje | ✅ | ativo | presa na demo |
| Só variáveis novas | ❌ `demo_conversation_binding_owner_changed` | — | — |
| **Migração** (apaga 9 vínculos + variáveis) | ✅ | ativo | **liberada** |

`/data/demo-real-test/handoffs.sqlite3` está vazio (não trava). As outras demonstrações (18186, 3285, 13381) não mudam;
os 4 vínculos do contato 3285 ficam.

## Passo a passo (produção)

1. **Backup** no próprio volume: `/data/bia-demo-test.sqlite3` → `/data/bia-demo-test.sqlite3.bak-20261122` (API de backup do SQLite).
2. **Apagar** só os vínculos do contato 3: `DELETE FROM demo_conversation_bindings WHERE owner_slot='8bbb064d9c77…'` (9 linhas).
3. **Variáveis** (sem reiniciar): `V5_TEST_PHONE`, `V5_PILOT_CONTACT_ID` (18186), `V5_PILOT_CONVERSATION_ID` (57704),
   `V5_DEMO_SCOPES_JSON` (sem o contato 3), `V5_RESTRICTED_PILOT_PHONE`, `V5_DEMO_REAL_TEST_PHONE` (telefone do 18186),
   `V5_PILOT_PHONES` (+ telefone do 18186). Conferir que gravaram iguais à simulação.
4. **Conferir** de novo que o contato 3 tem 0 vínculos (se o número de teste escrever antes do reinício, a demo pode
   criar um vínculo novo; nesse caso, repetir o passo 2).
5. **Reiniciar** com as configurações atuais do serviço (`serviceInstanceRedeploy`) e acompanhar `/healthz`.
6. **Testar:** mandar "Oi" do número de teste → a Bia responde como lead real.

**Durante a janela (≈2 min): não mandar mensagem pelo número de teste.**

## Rollback (se a Bia não subir)

1. Restaurar `/data/bia-demo-test.sqlite3` a partir do `.bak-20261122`.
2. Voltar as 7 variáveis aos valores anteriores.
3. Redeploy do último deploy bom. Tempo fora estimado: 3 a 4 minutos.

## O que muda para o seu número

Passa a seguir a linha real: ficha no banco, consulta do perfil no TikTok, convite (se autorizar) e alertas de GMV.
O histórico de demonstração dele fica guardado no banco da demo, sem uso.

## Executado em 23/11/2026 (11:10–11:12 UTC) ✅

| Passo | Resultado |
|---|---|
| Conferência antes | Deploy bom `69a6c339`, 7 variáveis originais, pré-deploy novo (31231 caracteres) |
| Backup | `/data/bia-demo-test.sqlite3.bak-20261123` (íntegro, 9 vínculos do contato 3) |
| Variáveis | 7 trocadas e conferidas (validadas antes com o código de produção) |
| Vínculos | 9 apagados; ficaram só os 4 do contato 3285 |
| Reinício | Deploy `622332de` SUCCESS, `/healthz` 200 o tempo todo (sem queda) |
| Conferência depois | Demonstrações: 18186, 3285, 13381. Conversa 59081 **não** é mais segurada pela demo |

Rollback continua possível com o `.bak-20261123` + as variáveis anteriores (guardadas fora do repositório).
