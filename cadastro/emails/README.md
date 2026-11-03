# Modelos de e-mail do cadastro (padrão aprovado)

Os arquivos `.html` mostram como o e-mail chega. Os dados são de exemplo: Maria Silva, código 123456.
A fonte de verdade é o código citado em cada linha. Se mudar o texto ou o visual, altere a fonte e gere estas prévias de novo.

Remetente de todos: **Amplify — notificações**, com a conta de e-mail da Bia (`SMTP_USUARIO`).

| Arquivo | Quando sai | Assunto | Fonte |
|---|---|---|---|
| `01-codigo-confirmacao.html` / `.txt` | A pessoa pede o código no formulário | Confirme seu e-mail na Amplify 💙 | `app/emailer.py` (`send_code`), igual a `code_message` do formulário original |
| `02-boas-vindas-start.html` | Acesso ao Circle criado, categoria Start | {primeiro nome}, bem-vindo à Amplify Start! + emoji | `app/legado/cadastro_assets/welcome_templates.json` → `Start` |
| `03-boas-vindas-silver.html` | Categoria Silver | {primeiro nome}, bem-vindo à Amplify Silver! + emoji | `welcome_templates.json` → `Silver` |
| `04-boas-vindas-gold.html` | Categoria Gold | {primeiro nome}, bem-vindo à Amplify Gold! + emoji | `welcome_templates.json` → `Gold` |
| `05-boas-vindas-diamond.html` | Categoria Diamond | {primeiro nome}, bem-vindo à Amplify Diamond! + emoji | `welcome_templates.json` → `Diamond` |

- **Boas-vindas:** montado por `welcome_message` em `app/legado/cadastro_delivery.py`, copiado sem alteração do serviço "Entrega de Acessos". Ao final, acrescenta o aviso "Mensagem automática — não responda a este e-mail".
- **Original do código:** `artifacts/formulario-original-v5-20261029/deployment-source/src/cadastro_email.py`.
