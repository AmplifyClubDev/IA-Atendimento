# Pontes do TikTok (Playwright, Chrome logado no Partner Center)

Copiado dos containers do Railway em 23/11/2026, sem mudanças (antes só existia dentro das imagens).
A sessão logada fica no volume `/data` de cada serviço e **não** está aqui.

| Pasta | Serviço no Railway | Faz |
|---|---|---|
| `tiktok-ponte/` | **TikTok Agenciamento** e **TikTok Pre-validacao** (mesmo código) | Lista parcerias (`GET /relations`), confere perfil e Shop |
| `tiktok-partner-bridge/` | **TikTok Partner Bridge** | Envia o convite (`invite-ui.mjs`) |

Entrada: `railway-supervisor.mjs` (sobe o Chrome e o `server-quente.mjs`). Publicar: ver `docs/railway.md`.
