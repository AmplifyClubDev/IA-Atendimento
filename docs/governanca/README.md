# Governança Amplify: operação gratuita, times e publicação

**Status: processo gratuito documentado; implantação e validações pendentes.** Este documento não ativa proteções, não concede acesso, não altera workflows ou deploys. O PR deve permanecer em rascunho até revisão dos responsáveis.

## 1. Estado observado em 6 de novembro de 2026

- Organização AmplifyClubDev no GitHub Free; AmplifyOS-v5 privado e `main` sem proteção.
- A interface avisa que rulesets para este repositório não serão aplicados sem GitHub Team. Criar uma regra não equivale a ativar sua aplicação.
- Times `amplify-os`, `ferramentas` e `rh` criados. Os times antigos Back-End e Front-End foram removidos após confirmação.
- Permissão-base de repositórios: **No permission**. Permissão-base de Projects: **No access**, com efeito indicado para novos projetos. A lista de Projects exibiu a opção de criar o primeiro projeto.
- Owners da organização: `Vuheff` e `andrei1104`; ambos possuem autoridade administrativa global. O time Amplify OS contém esses responsáveis.
- Ferramentas tem convite pendente para `ferramentasamplify` e nenhum repositório associado.
- RH ainda não está isolado: `Vuheff` permanece membro e owners têm acesso administrativo global. Não anunciar segregação validada.
- Esta revisão documental não associa times a repositórios e não altera acessos.

**Limite central:** neste estado, PR, aprovação e checks são convenções operacionais para quem pode integrar. Não são exigências técnicas impostas à `main` pelo plano atual. Owners e pessoas com escrita podem contornar o processo.

## 2. Modelo gratuito proposto

Colaboradores comuns recebem **Read** apenas nos repositórios aprovados para seu projeto. Trabalham em fork privado autorizado e abrem PR para o repositório de origem. Um responsável com escrita revisa os testes e a mudança e faz a integração.

```text
Read no repositório autorizado
    → fork privado permitido e validado
    → branch de trabalho no fork
    → pull request para o repositório de origem
    → revisão humana + evidência dos testes
    → integração pelo responsável
    → publicação pelo caminho Railway validado separadamente
```

**Bloqueio verificado:** a opção da organização `Allow forking of private repositories` está desativada e `Allow forking` do V5 aparece desabilitado. A habilitação ainda exige aprovação explícita; nenhuma alteração foi aplicada. Portanto, o fluxo Read + fork + PR ainda não está operacional.

O fluxo de fork depende das políticas da organização, da configuração do repositório e das permissões efetivas. **Não conceder Write ao colaborador como solução automática se o fork falhar.** Pausar o onboarding e decidir com o responsável uma alternativa autorizada.

Read impede push direto do colaborador no repositório de origem, mas não impede leitura/cópia de código. Não oferece barreira equivalente para owners ou integradores com escrita. Não tornar código público nem contratar plano pago sem aprovação.

## 3. Matriz mínima de acesso

| Grupo | Permissão proposta | Escopo e limite |
| --- | --- | --- |
| Owners atuais | Owner | Administração global; manter contas individuais e atuação excepcional |
| Colaboradores amplify-os | Read | Somente repositórios OS explicitamente aprovados |
| Colaboradores ferramentas | Read | Somente ferramentas/LPs explicitamente aprovados |
| Colaboradores rh | Read | Somente repositórios RH explicitamente aprovados |
| Integrador designado | Write, quando necessário | Somente o projeto designado; não implica acesso à produção |
| Integração de IA/CI | Mínimo necessário | Repositórios e ações aprovados; sem compartilhar login humano |

A matriz é o modelo de futuras concessões, não uma descrição de acessos já aplicados. Identificar pessoas, repositórios, permissões efetivas e aprovadores antes de qualquer alteração. Evitar times aninhados quando causarem herança indesejada.

Branches e environments não isolam código entre equipes. Para separar RH e OS, usar repositórios privados distintos, concessões explícitas e testes de ausência de acesso. Owners da organização continuam sendo exceção administrativa; remover uma pessoa de um time não elimina acesso herdado de Owner.

## 4. Inventário ainda necessário

| Repositório/projeto | Estado conhecido | Próxima confirmação |
| --- | --- | --- |
| AmplifyClubDev/Amplify-OS | Privado; main; não arquivado no inventário inicial | Serviços ativos, responsável e eventual legado |
| AmplifyClubDev/amplifyos-V2 | Privado; main; não arquivado no inventário inicial | Dependências antes de qualquer arquivamento |
| AmplifyClubDev/AmplifyOS-v5 | Privado; main sem proteção | Componentes, integradores e serviços por ambiente |
| Retenção da Camila, LPs, Dash Sniper e RH | Localização não confirmada | URLs, responsáveis e hospedagem |

Não migrar, renomear ou arquivar por aparência de legado. Antes disso, inventariar serviços dependentes, workflows, integrações e webhooks, sem copiar segredos.

## 5. Auditoria do CI existente no V5

Fonte: [cadastro-testes.yml](../../.github/workflows/cadastro-testes.yml), lido via GitHub em 6 de novembro de 2026.

- Workflow: `Testes do Cadastro`; identificador do job: `testes`.
- Eventos: `push` e `pull_request`, ambos filtrados para `cadastro/**` ou `.github/workflows/cadastro-testes.yml`.
- Runner `ubuntu-24.04`, limite de 20 minutos, comandos executados em `cadastro`.
- Checkout com `actions/checkout@v4`; instalação do PostgreSQL 17 pelo repositório oficial e configuração de `CADASTRO_TEST_PG_BIN`.
- Setup com `astral-sh/setup-uv@v5`; execução:
  `uv run --python 3.12 --with pytest --with "psycopg[binary]" --with-requirements app/requirements.txt python -m pytest -q tests`.
- O YAML não referencia segredos de produção nem define etapa de deploy. Não declara `permissions` explicitamente; permissões efetivas do token dependem da configuração do GitHub.
- Não define lint, análise de tipos, build dos demais componentes ou gate de produção. Um resultado verde desse job não demonstra cobertura de todo o V5/Bia.
- PRs apenas de documentação fora desses caminhos não acionam esse workflow. Ausência de execução não é aprovação dos testes.
- Em forks privados, confirmar a política de Actions e eventuais aprovações exigidas antes de prometer execução automática. Não habilitar envio de secrets ou tokens de escrita a código não confiável.

**Propostas para uma futura alteração, não implementadas neste PR:** declarar permissões mínimas do token, avaliar fixação de actions por SHA e dependências reprodutíveis, mapear testes/build/lint por componente e um check agregador sempre executado que distinga testes aprovados, falhas e componentes não afetados. Confirmar os nomes reais dos checks em uma execução antes de referenciá-los em regras.

Não marcar como obrigatório global um check filtrado que pode não executar. No plano atual, mesmo checks existentes não tornam a revisão obrigatória na main privada.

## 6. Checklist de integração manual

O integrador registra no PR:

- [ ] Objetivo, componentes alterados e responsável pela revisão identificados.
- [ ] Diff revisado; nenhum segredo, dado pessoal real ou mudança de acesso não autorizada.
- [ ] Revisão por outra pessoa sempre que possível; se não houver, exceção e motivo registrados, sem fingir revisão independente.
- [ ] Para Cadastro, resultado do job `testes` ou evidência reproduzível da execução local, vinculada ao SHA revisado.
- [ ] Para outros componentes, comandos e resultados pertinentes registrados; lacunas de cobertura explícitas.
- [ ] Para documentação, links e consistência conferidos; marcar testes de runtime como não aplicáveis, não como aprovados.
- [ ] Após mudanças no PR, revisar o novo SHA e repetir os testes afetados.
- [ ] Falhas, conversas abertas e limitações resolvidas ou aceitas explicitamente pelo responsável.
- [ ] Efeito do merge sobre Railway conhecido antes de integrar; não presumir que merge e deploy são separados.
- [ ] Commit a integrar e caminho de rollback identificados quando houver efeito em produção.

Não fazer push direto, force push ou exclusão da main no processo normal. Esta é uma regra de trabalho, não bloqueio técnico. Em emergência, registrar autor, motivo, SHA, validação e rollback. Um PR rascunho ou atualização documental não autoriza merge ou deploy.

## 7. Separação teste e produção

1. Inventariar cada serviço Railway: projeto, ambiente, serviço, repositório, branch, diretório raiz, versão e responsável.
2. Preservar a configuração atual até validar o mapeamento, especialmente o Atendimento V5 - Ensaio.
3. Separar dados e credenciais de teste e produção; o nome do ambiente não é prova dessa separação.
4. Identificar quem administra Railway e pode publicar.
5. Verificar se push/merge dispara deploy automaticamente. Não afirmar que há aprovação de produção enquanto isso não for testado no caminho real.
6. GitHub Environments só controla jobs que o utilizam e recursos disponíveis no plano. Não bloqueia sozinho deploy independente no Railway.
7. Registrar commit/image imutável, health check e rollback para a versão anterior.
8. Não alterar serviços, credenciais, integrações ou produção como parte desta documentação.

### Estado Railway observado em 6 de novembro de 2026

Consultas de serviços e configuração, sem alterar Railway:

| Serviço no projeto AmplifyOS | Configuração observada | Limites da evidência |
| --- | --- | --- |
| Atendimento V5 - Ensaio | Único ambiente listado: `production`; repositório AmplifyClubDev/AmplifyOS-v5; branch `review/bia-isolated-knowledge-20261106`; SHA configurado `2d0f121572096554023e37c7364d9cc5f9e10171`; raiz `/bia`; volume `/data`; health check `/healthz` | Configuração live, sem staged; último deploy reportado SUCCESS em 2026-11-06 17:09:56 UTC. O nome Ensaio não comprova isolamento nem o gatilho de deploy |
| Cadastro | Ambiente `production`; volume `/data`; health check `/health` | Configuração live, sem staged; último deploy reportado SUCCESS em 2026-11-04 14:16:16 UTC; a consulta não retornou source, então repositório, branch e gatilho permanecem sem confirmação |

Não presumir que qualquer serviço acompanha `main` ou usa autodeploy. SUCCESS é o status reportado do deploy, não uma validação funcional independente nem prova de aprovação obrigatória. O próximo passo é confirmar gatilhos, acesso de publicação e separação real de dados/credenciais, sem expor seus valores.

## 8. Segredos e automações

- Guardar valores no provedor apropriado, separados por ambiente; no Git, apenas nomes e exemplos sem credenciais.
- Não copiar tokens, senhas ou dados reais de creators para documentação, issues, logs ou PR.
- Não conceder a ferramentas de IA acesso à organização inteira por padrão.
- Criação de credenciais e expansão de acesso persistente exigem aprovação específica.
- Inventariar credenciais por responsável e finalidade, sem revelar valores.
- Coordenar qualquer rotação com os serviços consumidores para evitar interrupção.

## 9. Entrada e saída de pessoas

**Informações necessárias:** username GitHub, projeto/repositório, função, aprovador, necessidade de ambiente de teste e data de revisão/término.

- [ ] Confirmar username e conta individual.
- [ ] Confirmar autorização para os repositórios exatos.
- [ ] Aplicar Read no escopo aprovado, sem Write por padrão.
- [ ] Conferir permissões efetivas, inclusive acessos diretos, times aninhados e Owner.
- [ ] Validar que lê apenas repositórios autorizados, usando conta comum, não conta Owner.
- [ ] Validar fork privado e abertura de PR sem push no repositório de origem.
- [ ] Preparar ambiente sem segredos ou dados de produção.
- [ ] Abrir PR pequeno; registrar testes e revisão; integração pelo responsável.
- [ ] Verificar que não ganhou acesso indevido à publicação.
- [ ] Registrar quem concedeu acesso e quando será revisto.

Na saída: revisar membresia, acessos diretos, forks, Railway e demais provedores. Não presumir que remover acesso apaga cópias locais. Revogar apenas o escopo autorizado e verificar dependências de automações antes.

## 10. Critério de pronto do processo gratuito

- [ ] Todos os projetos e serviços têm responsável e repositório.
- [ ] Integradores definidos e permissões efetivas inventariadas.
- [ ] Acessos Read e ausência de acesso cruzado testados com conta comum.
- [ ] Fork privado, PR e execução de testes validados de ponta a ponta.
- [ ] Checklist manual usado e evidências registradas no SHA integrado.
- [ ] Lacunas de CI por componente explícitas e plano de correção aprovado.
- [ ] Caminho real de deploy, autoridade de publicação e rollback validados.
- [ ] Primeiro colaborador trabalha sem credenciais de produção.

**Pronto não significa main protegida.** O processo gratuito reduz quem pode escrever e concentra integração nos responsáveis; não impede que esses responsáveis/owners contornem PR, revisão ou testes. Proteção técnica futura deve ser tratada como iniciativa separada, com plano/recursos autorizados e teste de bloqueio real.
