# Governança Amplify: times, repositórios e publicação

**Status: proposta operacional em revisão.** Este documento não ativa proteções, não concede acesso, não altera deploys e não substitui a configuração administrativa do GitHub/Railway.

## Resultado esperado

Cada pessoa acessa somente seus projetos. Toda mudança chega à `main` por pull request, revisão e testes. Produção é publicada somente pelo processo autorizado, com versão e rollback identificados.

## 1. Estrutura proposta

```text
AmplifyClubDev
├── Owners da organização (poucas pessoas, contas individuais)
├── Time amplify-os → repositórios OS aprovados
├── Time ferramentas → repositórios de ferramentas e landing pages aprovados
└── Time rh → somente repositórios RH aprovados

Branch de trabalho → Pull request → Testes + revisão → main
                                                        ↓
                                          Aprovação de produção
                                                        ↓
                                               Deploy Railway
```

Times são propostos, não criados. Acesso a um repositório permite ler suas branches; **branches e environments não isolam código entre equipes**. Para impedir que RH veja OS, use repositórios privados distintos e concessões explícitas por time.

## 2. Matriz mínima de acesso

| Grupo | Permissão proposta | Escopo | Observação |
| --- | --- | --- | --- |
| Owners | Owner | Organização | Identidades nominais a confirmar; não usar no trabalho diário |
| amplify-os | Write | Repositórios OS selecionados | Pode desenvolver e abrir PR; não implica administrar produção |
| ferramentas | Write | Ferramentas/LPs selecionadas | Não herda acesso a RH/OS |
| rh | Write | RH selecionado | Não herda acesso a outros projetos |
| Responsável técnico de cada projeto | Maintain, se necessário | Apenas o projeto designado | Não dar Admin por padrão |
| Integração de IA/CI | Mínimo necessário | Repositórios e ações aprovados | Preferir integração própria; não compartilhar login humano |

**Não aplicar concessões ou remoções sem identificar pessoas, repositórios e permissões.** Evitar times aninhados quando isso causar herança indesejada. Definir acesso-base da organização como nenhum somente depois de inventariar acessos existentes e aprovar o impacto.

## 3. Inventário inicial

| Repositório | Estado observado | Decisão pendente |
| --- | --- | --- |
| AmplifyClubDev/Amplify-OS | Privado; main; não arquivado | Responsável, serviços ativos e possível legado |
| AmplifyClubDev/amplifyos-V2 | Privado; main; não arquivado | Responsável e dependências antes de arquivar |
| AmplifyClubDev/AmplifyOS-v5 | Privado; main; não arquivado | Mapeamento por componente/ambiente |
| Retenção da Camila, LPs, Dash Sniper e RH | Localização ainda não confirmada | Identificar URLs, owners e hospedagem |

Não migrar, renomear ou arquivar por aparência de legado. Antes disso, listar serviços que dependem do repositório, workflows, integrações, webhooks e owners.

## 4. Proteção da main: configuração a aplicar após validação

- Exigir pull request.
- Exigir ao menos uma aprovação de pessoa diferente do autor.
- Exigir resolução de conversas e invalidar aprovações após mudanças relevantes.
- Exigir checks reais, existentes e adequados ao componente alterado.
- Bloquear force push e exclusão da branch.
- Restringir bypass a responsáveis definidos; registrar uso emergencial.
- Ativar revisão por CODEOWNERS apenas depois de confirmar usuários/times válidos com acesso adequado.
- Testar com conta de desenvolvedor que um push direto é recusado e um PR sem testes/revisão não pode ser mesclado.

**Limite verificado:** a auditoria retornou main sem proteção no resumo das três branches. A consulta detalhada de proteção recebeu 403 da integração; rulesets recebeu 403 com indicação de plano/visibilidade. O plano atual e a disponibilidade efetiva devem ser confirmados por administrador. Não tornar repositórios públicos para obter proteção e não contratar upgrade sem aprovação.

O workflow `production-gate.yml` no Amplify-OS não garante bloqueio sozinho. O workflow de testes de Cadastro no V5 cobre caminhos específicos, não toda a Bia. Não configurar um check obrigatório que nunca roda para certos PRs: isso pode impedir merges legítimos.

## 5. Separação teste e produção

1. Inventariar cada serviço Railway: projeto, ambiente, serviço, repositório, branch, diretório raiz, versão e responsável.
2. Manter a configuração atual até validar o mapeamento, especialmente o Atendimento V5 - Ensaio.
3. Teste e produção devem usar credenciais e dados separados. Não depender apenas do nome do serviço/ambiente.
4. Controlar quem administra os projetos Railway e quem pode disparar/publicar produção.
5. Escolher um único caminho de deploy. Se o Railway publicar automaticamente antes do gate, corrigir essa integração antes de declarar produção protegida.
6. GitHub Environments só protege jobs que usam esse environment; não bloqueia, por si só, deploy independente iniciado diretamente no Railway.
7. Registrar commit/image imutável, health check e rollback para a versão anterior.
8. Verificar os recursos disponíveis no plano GitHub e no Railway antes de escolher o mecanismo de aprovação.

## 6. Segredos e automações

- Valores ficam no provedor apropriado, separados por ambiente; no Git, apenas nomes/explicações em `.env.example`.
- Não copiar tokens, senhas ou dados reais de creators para documentação, issues, logs ou PR.
- Não conceder a ferramentas de IA acesso a toda a organização por padrão.
- Criação de credenciais e expansão de acesso persistente exigem aprovação específica.
- Inventariar credenciais existentes por responsável e finalidade, sem expor os valores.
- Rotação deve ser coordenada com os serviços consumidores para evitar interrupção.

## 7. Entrada de uma nova pessoa

**Informações necessárias:** username GitHub; projeto(s); função/permissão; necessidade de teste/produção; aprovador; data de revisão ou término.

Checklist:
- [ ] Confirmar username e conta individual.
- [ ] Confirmar associação ao projeto e autorização do responsável.
- [ ] Adicionar ao time específico, com a menor permissão necessária.
- [ ] Validar que consegue clonar apenas repositórios autorizados.
- [ ] Preparar ambiente de desenvolvimento sem segredos de produção.
- [ ] Ler README, documentação de arquitetura, testes e regras de PR.
- [ ] Abrir um PR pequeno, executar testes e receber revisão.
- [ ] Validar que não publica produção sem o controle previsto.
- [ ] Registrar acesso concedido e responsável pela revisão.

Na saída: revisar membresia de times, acessos diretos, Railway e demais provedores. Revogar somente o escopo aprovado; verificar antes se a conta sustenta alguma automação.

## 8. Ordem de implantação

1. **Inventário:** confirmar repositórios, serviços, plano e administradores.
2. **Times:** confirmar nomes e integrantes; criar sem concessões amplas.
3. **Acessos:** aplicar matriz autorizada e testar isolamento.
4. **Main e CI:** ativar regras suportadas, checks por componente e revisão.
5. **Deploy:** aplicar/testar controles no caminho real até Railway.
6. **Onboarding:** executar o checklist com a primeira pessoa.

## 9. Critério de pronto

- [ ] Todos os projetos e serviços têm owner e repositório.
- [ ] Acesso entre equipes foi validado, inclusive ausência de acesso.
- [ ] Main recusa mudanças sem processo.
- [ ] CI cobre componentes implantados.
- [ ] Deploy não contorna aprovação/checks.
- [ ] Rollback foi documentado e validado em teste.
- [ ] A primeira pessoa consegue trabalhar sem credenciais de produção.

Até concluir esses testes, o status correto é **governança preparada, configuração pendente**, não “organização protegida”.
