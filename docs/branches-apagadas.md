# Branches apagadas em 21/11/2026

Todas já estavam contidas na `main` (nenhum commit perdido). Para recuperar uma:

```
git push origin <hash>:refs/heads/<nome>
```

| Branch | Último commit |
|---|---|
| `chore/testes-cadastro-portateis` | `6490e21c3ee455a8f5c0b4c1e3d2744aec0e6d76` |
| `claude/blissful-brown-nq8qug` | `01ab944b3da0e9ff1fa436d972d0157bf94b8dad` |
| `codex/fix-convite-interrompido-54457` | `68ea62d8eebe585b2709c7d7f7c32501cad9fd5b` |
| `codex/journey-recovery-50` | `dd947e18e49ba3a9282dbbe07ffdcb63279ef000` |
| `feat/cadastro-conferencia-agenciamento` | `d946942b41a4fec0776d0bb69861501b020a6e40` |
| `feat/cadastro-email-confirmacao` | `af789e6c3b0e831bfbc25573e43da9e5f7c6ef50` |
| `feat/cadastro-visual-v2` | `b23e9c0a3e0b4613b2f40377169956660a6bed47` |
| `fix/bia-51-followup` | `b01dd6bbb99910a4a7bad54a802e56e1aca875ab` |
| `fix/bia-alertas-visual-20261117` | `0cf38304d8c198de0ad8a68c5e7d7df0841f62fe` |
| `fix/bia-context-ack-20261116` | `57573e7eaba65bedcd5d993cd6f89a242e9c6aa7` |
| `fix/bia-post-invite-next-step-20261114` | `d3e14eb96f5f28006f02526c632b73c121b1840f` |
| `fix/cadastro-etiqueta-acesso-chatwoot` | `329e83d7e1e5242dac0f62596ea87be7198c30a1` |
| `fix/cadastro-retomada-anexos-20261117` | `07e921b5641cab47fd40803bca9901468bba808e` |
| `fix/cadastro-timeout-agenciamento-20261117` | `ebafda0f778e75c525d0340a70f773a81eb015f5` |
| `release/bia-40` | `235ec7370ae88d9ae99f38d0ce0e09fc25e1d067` |
| `release/bia-40-1` | `54400f87b4088c0e0b04e2477ba6e04e1f27434f` |
| `release/bia-40-2` | `2e1768ce8f11613839229809774d6d8bbb15d4a5` |
| `release/bia-41` | `6b51195947a2fd5f65dd6fac695c48d121f05737` |
| `release/bia-42` | `af8e34ba0721ac323bbeea36b19634560e6997f0` |
| `release/bia-43` | `e74ba6d352af8d8bdbe4e7218056ff1a05b3eeb7` |
| `release/bia-44` | `59164aca5471cc86ad152f8187d3dda4438f212f` |
| `release/bia-45` | `0b8e320ddd3068a718b69e341b788ab3e63bd848` |
| `release/bia-46` | `2bc1ceddf20b218b79d640b540d11abf365b745c` |
| `release/bia-47` | `628062bcb90cec12ed9e54e0b67c44e7d9edf285` |
| `release/bia-48` | `47bfc12a548b73761fc3c12f8296feb82e45f618` |
| `release/cadastro-base` | `769257f8f8a823a3c7eaa8b6a20041200d9a44b3` |
| `review/bia-approved-reference-20261105` | `c64734558043a7b34846eeeeb228c065aa9a231c` |
| `review/bia-isolated-test-router-20261104` | `ccaabb44947a6c66632a36eba82d2e9039f05ee2` |

Ficaram (têm trabalho que não está na `main`): `claude/relaxed-einstein-h7mkax` (plugin do Railway), `docs/governanca-times-onboarding-20261106`, `fix/bia-identificacao-20261117`, `review/bia-isolated-knowledge-20261106`, `review/isolated-bridges-20261104`. As tags `bia-rNN` continuam.

## 22/11/2026 — as 5 branches com trabalho próprio

| Branch | Último commit | Destino |
|---|---|---|
| `claude/relaxed-einstein-h7mkax` | `a635befa79b87fb4c3f25d28247aa7ff1078c6e3` | Juntada na `main` (plugin do Railway) |
| `docs/governanca-times-onboarding-20261106` | `17a6ed8bc96b0bb696b93e8df4e199416bb3e5f9` | Juntada na `main` (doc de governança) |
| `review/bia-isolated-knowledge-20261106` | `edeb82add7f02aa1d6efc700cd23a10f00e67fc0` | Juntada na `main` (Bia interpreta respostas na etapa ativa; **ainda não publicada**) |
| `fix/bia-identificacao-20261117` | `9c891e2afad1eab6daab63a0d56233a65ffb89b3` | **Apagada sem juntar**: mudava a linha do atendimento |
| `review/isolated-bridges-20261104` | `8cb784c1a9c79b28c9da4ac153173aa26f1d22d3` | **Apagada sem juntar**: ensaio de 04/11, superado |
