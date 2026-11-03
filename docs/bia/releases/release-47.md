# Bia: release 47 (03/11/2026): entrada de todos os leads

**Base:** a 46 que está no ar (deploy `ab8dd843`). A 47 contém a 46 inteira. **Nada publicado, enviado ou lido em produção.**

| | |
|---|---|
| Pacote | `atendimento-v5-release-20261103-47`, 37 arquivos |
| zip sha256 | `5f0372c05983d2d34675c91a6ce75be2d9ef7f83b772d5843ba88e45c879bf93` |
| Carregador | sha256 `994b70e7fb436f8454202a608c2aea5bb70ee02e22aabfe82d7c84c531926410` |
| Partes | 12, as mesmas variáveis da 46 |
| Variável nova | **`V5_GATE_MODE`** (`lista` ou `todos`; vazia = `lista`; outro valor fecha o `/ready` com `gate_mode_invalid`) |
| Volta | `sealed47/volta46/`, idêntica a `sealed46/variaveis/`; ou só `V5_GATE_MODE=lista` |
| Diferença | `release47.diff` (46 → 47): `config.py`, `contracts.py`, `real_operations.py`, `retomada.py`, `server.py` |
| Testes | 816 passam (827 no total, 11 novos em `src/tests/test_gate47.py`), 9 fora de uso, as mesmas 2 falhas antigas |

## Como funciona

- **`lista`** (padrão): igual à 46. A suíte inteira da 46 passa sem mudar nenhum teste.
- **`todos`:** o portão aceita qualquer telefone válido da caixa 3 (o número que o WhatsApp informou). A Bia fica em silêncio, e registra o motivo, em:

| Exclusão | Onde é lida | Motivo no diagnóstico |
|---|---|---|
| Etiqueta "Renovacao de contrato" (com ou sem acento, com `_` ou `-`) | detalhe da conversa no Chatwoot | `fora_do_gate:renovacao_de_contrato` |
| Responsável humano | `meta.assignee` | `fora_do_gate:responsavel_humano` |
| Controle humano (atributos da conversa) | `custom_attributes` | `fora_do_gate:controle_humano` |
| Grupo ou sem telefone | telefone inválido | `fora_do_gate:sem_telefone` |

- **O número de teste (final 4859) sempre entra**, mesmo com a etiqueta.
- **No webhook, só no modo `todos`:** antes de responder, a Bia lê a conversa no Chatwoot, com o mesmo controle humano das varreduras.
  - Se a pessoa estiver excluída, a Bia não responde nem registra nada no banco. O motivo vai para `GET /diagnostico/conversa/<id>`, em `decisoes.entrada`.
  - Se a leitura do Chatwoot falhar, o motivo é `erro_envio:<código>`, e a pós-pausa tenta em 2 min.
- **Pós-pausa, retomada, reconferência e varredura de sem-resposta seguem o mesmo portão,** porque todas usam o mesmo `pilot_phone` e o mesmo controle humano.
- **Carga no Chatwoot:** a pós-pausa guarda a decisão de cada conversa até ela ter atividade nova. No modo `todos` são centenas de conversas, e o histórico de cada uma não é lido de novo a cada minuto.

## Antes de ligar `todos`: quem receberia a pós-pausa

```bash
CHATWOOT_BASE_URL=https://chatwoot.t2ffoz.easypanel.host CHATWOOT_API_TOKEN=... python -I listar_entrada_todos.py
```

- **Só leitura:** faz só GET no Chatwoot e não lê o estado da Bia.
- **Mostra:**
  - quantas conversas abertas leu;
  - quem receberia (lead das últimas 23 h que só recebeu avisos automáticos), com a idade e a vez na fila de 1 por minuto;
  - quantos **sairiam da janela de 23 h antes da vez**;
  - os de fora, por motivo;
  - só os 4 últimos dígitos do telefone.

## Publicação (só com autorização do usuário)

1. **Rodar o `listar_entrada_todos.py`** e decidir sobre a fila.
   - Se for grande, quem passar de 23 h antes da vez fica sem resposta automática; o script diz quantos.
2. **Trocar as 12 partes e o carregador** pelos de `sealed47/variaveis/`, ainda com `V5_GATE_MODE=lista`. Fazer o redeploy e conferir que tudo segue igual.
3. **Regra 3 do Chatwoot: recomendo desligar.**
   - Não vale deixá-la só para "Renovacao de contrato": o aviso de "manutenção" também não serve para quem está na base, e o time responde essas conversas.
   - Se a regra continuar ligada para todos, todo lead recebe "manutenção" antes da Bia.
4. **Ligar `V5_GATE_MODE=todos`** e fazer o redeploy.
5. **Conferir:**
   - no `/ready`, as contagens `puladas_por_motivo`;
   - em `/diagnostico/conversa/<id>`, um lead novo e uma conversa de renovação.
6. **Volta:** `V5_GATE_MODE=lista` e reativar a regra 3. Se precisar voltar o código, usar `sealed47/volta46/`.
