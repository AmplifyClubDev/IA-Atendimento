# Bia: release 40.1, limite do piloto 100 (02/11/2026)

A release 40.1 é a 40 que está no ar (zip sha `1bd9a72e…`) com uma única mudança: `MAX_PILOT_PHONES = 100` (era 21) em `src/contracts.py`. O objetivo é liberar novos lotes de telefones sem precisar de outro pacote.

**Nada foi publicado.** A lista `V5_PILOT_PHONES` e a regra 3 do Chatwoot não foram tocadas.

| | |
|---|---|
| Pacote | `atendimento-v5-release-20261102-40-1` |
| zip sha256 | `e786d1aef2374d8a1bfc5ff0f4669459e1aced22d27d81e915609ef1b5864fb7` |
| Carregador | sha256 `934176267b49bfb401f676ecde3bd0da7203e8e227ac8bf590b215768aefb351` |
| Partes | 10, as mesmas variáveis da 40, sem variável nova |
| Variáveis | `sealed40-1/variaveis/` (`V5_RELEASE_LAUNCHER_B64` e `V5_RELEASE_ARCHIVE_PART_1..10`) |
| Volta | `sealed40-1/volta40/`, idêntica a `sealed40/variaveis/` |
| Diferença da 40 | `release40-1.diff`: só `contracts.py` (21 → 100) e o teste de limite |

**Testes:** 662 passam, 9 ficam fora de uso e continuam as mesmas 2 falhas antigas (`test_connection_host` e `test_real_executor` com data fixa). O teste do limite, `test_release39.PilotCapTests`, confere que 100 telefones são aceitos e 101 são recusados com `pilot_phones_invalid`.

**Selagem:** com o Python do sistema (3.14, zlib-ng), o mesmo que selou a 40. O resultado é determinístico: rodado duas vezes, deu o mesmo sha. Com o Python 3.12 da `.venv`, a compressão sai diferente e o pacote passa para 11 partes. Por isso não use a `.venv` para selar.

## Publicação (só com autorização do usuário)
1. Trocar `V5_RELEASE_LAUNCHER_B64` e `V5_RELEASE_ARCHIVE_PART_1..10` pelos arquivos de `sealed40-1/variaveis/`.
2. O `/ready` deve mostrar `atendimento-v5-release-20261102-40-1`.
3. Depois disso, a lista `V5_PILOT_PHONES` aceita até 100 telefones. Uma lista com mais de 21 telefones só pode entrar depois da 40.1 ou junto com ela: a 40 fecha a prontidão com `pilot_phones_invalid`.

**Volta:** restaurar `sealed40-1/volta40/` e, antes disso, reduzir `V5_PILOT_PHONES` para no máximo 21 telefones.
