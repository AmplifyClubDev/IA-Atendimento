# Bia: release 40.2, a pós-pausa lê todas as páginas (02/11/2026)

A 40.2 é a 40.1 que está no ar (deploy `86a3c144`, zip sha `e786d1ae…`) com uma única mudança no código, em `src/retomada.py`: a pós-pausa passa a ler as conversas abertas da caixa página a página.

**Nada foi publicado.** Nenhuma variável e nenhuma conversa foram tocadas.

## O erro
Em 02/11 a pós-pausa respondeu 6 de 8 leads e pulou:
- **56866:** o lead escreveu em 01/11 às 16:12;
- **56865:** o lead escreveu em 01/11 às 13:09.

Por que os dois ficaram de fora:
- O Chatwoot entrega a lista de conversas abertas em páginas de 25, da atividade mais recente para a mais antiga.
- A pós-pausa lia só a primeira página.
- Os leads fora da lista também recebem o aviso de manutenção e as conversas deles continuam abertas. Por isso havia mais de 25 conversas mais novas na frente das duas.

**Correção:**
- A pós-pausa lê até 20 páginas (500 conversas).
- Ela para numa página vazia, numa página que só repete conversas já lidas ou numa página toda mais antiga que 23 h.
- Continua respondendo um lead por varredura, uma vez por minuto.

**Teste:** `tests/test_release40_2.py` (`PosPausaPagesTests`) usa os dois casos com os horários reais e 30 conversas mais novas na frente.
- No código da 40.1, nenhum dos dois é respondido.
- No código da 40.2, os dois são respondidos uma vez cada, e a varredura seguinte fica parada.

| | |
|---|---|
| Pacote | `atendimento-v5-release-20261102-40-2` |
| zip sha256 | `9f9cf714d080e647f9d864e9c9208c77502cb95a7811d2b74a5f8c451d0538d5` |
| Carregador | sha256 `676a1e00dc4a4ec575fe9dd9ebe91aaccf4a11fafbf4775d9f764c4f6488f341` |
| Partes | **11** (a 40.1 tem 10) |
| Variáveis | `sealed40-2/variaveis/` |
| Volta | `sealed40-2/volta40-1/`, idêntica a `sealed40-1/variaveis/` |
| Diferença da 40.1 | `release40-2.diff`: só `retomada.py` e o teste novo |
| Testes | 663 passam, 9 ficam fora de uso e continuam as mesmas 2 falhas antigas |

O pacote foi selado com o Python do sistema (3.14). Selado duas vezes, deu o mesmo sha.

## Publicação (só com autorização do usuário)
1. Trocar `V5_RELEASE_LAUNCHER_B64` e `V5_RELEASE_ARCHIVE_PART_1..10` pelos arquivos de `sealed40-2/variaveis/`.
2. **Criar** `V5_RELEASE_ARCHIVE_PART_11`. A 40.2 não sobe sem essa parte.
3. O `/ready` deve mostrar `atendimento-v5-release-20261102-40-2`. Em até alguns minutos, a pós-pausa responde 56866 e 56865, um por minuto, com o pedido de desculpas e a resposta ao que cada lead escreveu.

**Prazos:** a pós-pausa só pega mensagens de até 23 h.

| Conversa | Pós-pausa até (Brasília) | Janela do WhatsApp fecha |
|---|---|---|
| 56865 | 02/11, cerca de 12:09 | 13:09 |
| 56866 | 02/11, cerca de 15:12 | 16:12 |

**Volta:** restaurar `sealed40-2/volta40-1/` e **apagar** `V5_RELEASE_ARCHIVE_PART_11`, ou deixá-la vazia. O carregador da 40.1 recusa uma parte a mais que tenha valor.
