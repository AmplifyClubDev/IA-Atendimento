# Bia: release 48 (03/11/2026): etiquetas etapa + encerrado

No ar desde 03/11 05:19 (deploy `d0d71fe6`). Base: a 47.

## O que muda

| Antes (47) | Depois |
|---|---|
| Lead parado continua só com a etapa ("validação") e não dá para saber que parou | Passou 24 h sem responder → **etapa + encerrado** (ex.: `validação` + `encerrado`) |
| "encerrado" substituía a etapa (só na conversa de teste 26097) | "encerrado" vem **sempre junto** da etapa |
| Convite enviado e ainda não aceito aparecia como `cadastro` | Fica `convite` até o vínculo ser comprovado (lista de vínculos, aviso do vínculo, ficha ou acesso) |
| "Conferindo aceite" aparecia como `validação` | `convite` |
| Depois do acesso liberado, a etiqueta parava de atualizar | `cadastro` |

Quando o lead volta a escrever, o "encerrado" sai sozinho e fica só a etapa nova. Etiquetas de outras equipes (ex.: "Renovacao de contrato") nunca são tocadas. Conversa com atendente humano não ganha "encerrado".

## Onde

- `src/transport.py`: `_stage_label` (etapa real), `_window_closed`, prova `parado`, e o Chatwoot aceita "etapa + encerrado" num pedido só.
- `src/retomada.py` + `src/server.py`: a varredura de 1 minuto marca quem passou da janela de 24 h.
- `src/tests/test_etiquetas48.py`: 15 testes novos.

## Testes

842 testes, 831 passam, 9 fora de uso, **as mesmas 2 falhas antigas da 47** (`suite48.log`). Diff: `etiquetas48.diff`.

## Para publicar

Publicado com `tools/empacotar_release48.py`. A renovação (pasta `claude-bia-renovacao-20261103`) também se chama 48: quem publicar primeiro fica com o número, e a outra precisa ser refeita em cima.

## Conhecimento (cards) revisado no mesmo dia

Gravado em `interno.contextos_ia` (vale sem deploy). Cópia em `bia/contexto-ia/cards.json`; o estado anterior em `cards-antes-20261103.json` e a volta em `volta-20261103.sql`.

- Corrigidos: `funcionamento`, `convite_tiktok`, `cadastro_acessos`, `ensaio`, `perfil_tiktok`, `ja_tem_agencia`, `bia`, `promessas` (link do cadastro só depois do vínculo; sem pedir origem nem nome; sem prometer prazo; não pedir o @ de novo; link do perfil vale como @).
- Novos: `categorias` (Start até R$ 4.999, Silver ≥ R$ 5 mil, Gold ≥ R$ 30 mil, Diamond ≥ R$ 100 mil de GMV), `amostras_campanhas`, `sem_confirmacao`.
- Regra: nada sobre atendimento humano nos cards.
