# Release 55: baseline sanitizada para revisão

Esta branch prepara o código da Bia que estava em execução no Railway para revisão no GitHub. Ela **difere do artefato original**: remove identificadores privados, exige configuração explícita do piloto e acrescenta testes sintéticos. Nenhum serviço, variável, credencial, tráfego ou branch `main` foi alterado por esta preparação.

## Proveniência e comparação

- Release observada: `atendimento-v5-release-20261103-55-roteiro-ia`.
- Deployment: `582fbd1f-239c-4772-85ba-e3eb1f9366a3`.
- SHA256 do pacote original: `4c7f27cd5f6918c7461e97ab479c98804c988d240ece71d1c24f1e656fc8c68e`.
- Referência de comparação: `fix/bia-51-followup`, commit `b01dd6bbb99910a4a7bad54a802e56e1aca875ab`.

Os 37 arquivos de fontes e contratos estáticos observados no disco associado ao processo principal coincidiam com o pacote. Antes da sanitização, 32 eram idênticos à branch 51 e cinco diferiam: `MANIFEST.json`, `conversao.py`, `real_journey.py`, `transport.py` e `ops/stage_preflight.py`. Esta observação verifica arquivos no disco, sem inspecionar o bytecode já carregado pelo processo.

As diferenças funcionais da release 55 em relação à 51 são:

- A entrada oferece escolhas definidas pelo roteiro. Um `@` literal e comandos explícitos de início seguem o fluxo sem pedir interpretação à IA.
- A qualificação pode ficar pausada enquanto a Bia responde dúvidas. A declaração de outra agência não comprova vínculo no provedor.
- Elegibilidade desconhecida é tratada como informação ausente. Ela não comprova que o TikTok Shop esteja inativo. Correções de perfil exigem confirmação e perguntas comerciais não disparam uma nova consulta por conta própria.
- O estado `verification_pending` de um convite também mantém a verificação pendente.
- O transporte de metadados e o preflight usam o hostname Chatwoot do Railway observado nessa release, enquanto a branch 51 usava o hostname antigo da VPS.
- O manifest original registra proveniência da release 54 e hashes próprios da release 55.

## Sanitização e alteração de comportamento

Os identificadores semelhantes a telefones foram substituídos **no servidor antes da transferência das fontes**. Nenhum banco, dump, cookie, perfil de navegador, sessão ou valor de ambiente foi exportado. Depois foram retiradas referências privadas a conversas, eventos históricos, perfis e incidentes em comentários/docstrings. O número de exemplo usado para testar rejeição de destinatário foi substituído por uma entrada inválida.

`pilot_scope.py` centraliza três configurações sem valores padrão:

| Variável | Uso |
| --- | --- |
| `V5_RESTRICTED_PILOT_PHONE` | Identidade explicitamente autorizada para recursos restritos do piloto. |
| `V5_PILOT_CONVERSATION_ID` | Conversa explicitamente autorizada para esses recursos. |
| `V5_PILOT_CONTACT_ID` | Contato explicitamente autorizado para esses recursos. |

O escopo de conta/caixa que já existia nessa release continua restrito à conta `1` e caixa `3` nos recursos especializados. A nova configuração é validada e não pode conter padrões, listas ou identificadores inválidos. Quando o gate está habilitado, a ausência do escopo completo ou a divergência em relação a `V5_TEST_PHONE` acrescenta `restricted_pilot_scope_missing` à prontidão. Followup, retomada restrita e formulário direto também recusam escopo ausente. Portanto, **esta cópia não deve substituir produção com a configuração atual sem uma revisão posterior**.

As listas excepcionais de eventos históricos agora ficam vazias por padrão. As opções `V5_INITIAL_RECHECK_EVENT_KEYS` e `V5_INITIAL_INVITE_RECHECK_EVENT_KEYS` aceitam somente uma lista explícita, limitada e validada. Nenhum valor operacional foi transportado para essas opções. Isso desativa as exceções históricas até uma decisão explícita de configuração.

`MANIFEST.json` foi recalculado para as fontes sanitizadas e inclui `pilot_scope.py`. `.gitattributes` preserva os bytes das fontes para que conversões de fim de linha no checkout não invalidem os hashes. O Dockerfile passa a copiar esse módulo e três módulos locais já referenciados pela aplicação, mas ausentes do COPY original: `conversao.py`, `retomada.py` e `reconferencia.py`. O build da imagem não foi executado.

## Validação offline

Execute a partir da raiz do repositório, com Python 3.12:

```sh
python -I -B bia/review_tests/run_offline.py
```

A suíte usa somente a biblioteca padrão. O runner remove variáveis de ambiente que possam conter credenciais antes de importar a aplicação e bloqueia criação de sockets, resolução DNS e execução de subprocessos. Os dados de teste são sintéticos e nenhuma base ou mensagem real é usada. Ele descobre somente `review_tests`, sem executar as fixtures legadas de `bia/tests`.

Foram verificados os cenários de configuração explícita/ausente/inválida, mismatch de telefone, followup desabilitado sem leitura de repositório/provedor, identidade do formulário direto, rejeição de contato/conversa divergentes, controle de transporte, fechamento do preflight antes do cliente HTTP, fluxo inicial, recusa, pausa, troca de perfil, elegibilidade desconhecida e convite pendente. A compilação das fontes, a integridade do manifest e os módulos copiados pelo Dockerfile também são verificados.

Não foram testados o bootstrap Flask completo, o build Docker, o armazenamento persistente, a autenticação de clientes ou chamadas reais a Chatwoot, TikTok, Supabase, IA e SMTP. A suíte valida a cópia sanitizada; não substitui homologação de integrações.

## Escopo da branch e próximo passo

O commit se baseia na branch 51 e atualiza somente as fontes sanitizadas da Bia, acrescentando este documento e a suíte sintética. Outros componentes, testes e histórico já existentes no repositório não fazem parte do pacote de fontes exportado nem foram reescritos por esta preparação. Os artefatos locais de auditoria e os hashes pseudônimos dos telefones não são incluídos no commit.

O próximo passo é revisar esse delta, validar o bootstrap/build em ambiente isolado e preparar a configuração privada necessária, antes de decidir sobre integração à `main` e conexão da fonte GitHub ao Railway. Esta preparação não faz essa conexão nem autoriza deploy.
