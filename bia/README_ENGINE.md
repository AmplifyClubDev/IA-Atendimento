# Motor comum da Bia

## Separação de responsabilidades

- `answer_engine.py`: pipeline único de resposta usado pelos testes e pelo atendimento real. Seleciona o contexto, exige referências válidas, verifica suporte semântico, permite uma reformulação completa e preserva a formatação aprovada. Não chama TikTok, Chatwoot, cadastro ou Slack.
- `demo_answers.py`: entrada compatível dos testes, apontando para o mesmo módulo `answer_engine`. Não existe uma cópia divergente do gerador.
- `amplify_answer_profile.py`: perfil explícito `amplify-v1`. Contém contexto, instruções da Amplify, seleção de fontes e fábrica do verificador. A troca de modo altera somente o envelope operacional, não o estilo aprovado.
- `real_answer_adapter.py`: adapta histórico sanitizado e interpretações da produção para o motor comum. Remove a resposta e o FAQ alternativo do classificador antigo antes de produzir a resposta final. Falhas não retornam texto antigo.
- `real_journey.py`, `lead_validation.py`, `real_operations.py`: continuam responsáveis por etapas, consentimento, pontes, convites, vínculo e formulário. O gerador não pode autorizar uma ação.

Perguntas livres durante a qualificação chegam ao mesmo motor sem consumir uma resposta de agência, Shop, GMV ou consentimento. Uma resposta curta a um esclarecimento do motor não autoriza a pergunta operacional anterior. Ciclos e históricos não são reiniciados para trocar o motor.

## Configuração e rollback

`V5_SAME_ENGINE_ENABLED=true` seleciona o motor comum em todos os novos turnos admitidos da produção, inclusive ciclos em andamento. `V5_CONTEXT_PROFILE_ID=amplify-v1` seleciona o perfil conhecido. O padrão da nova flag é desligado; ligar exige QA e observação do rollout. O `/ready` informa versão, perfil e disponibilidade; a ausência de gerador impede prontidão.

Desligar a flag reverte a apresentação dos próximos turnos sem apagar fases, fatos, recibos, deduplicação, pausas, formulários ou handoffs existentes. Não apagar os serviços de cadastro/acesso, pontes TikTok, Chatwoot, volumes ou bancos. Não remover o isolamento dos testes.

## Outro contexto

Adicione um `AnswerProfile` com identificador, namespace e versão próprios, loader isolado, instruções, seletor e fábrica de verificação. Registre-o explicitamente no resolvedor e teste antes de habilitar. O loader deve retornar o mesmo `profile_id` e `context_namespace`; divergências falham antes da geração. Referências de evidência incluem namespace. Nunca reutilize o loader/cache global `context_ia` da Amplify para outro cliente. Não há cadastro público de tenants nem roteamento multiempresa automático nesta versão.

Um perfil alternativo pode usar o mesmo pipeline sem editar `answer_engine.py`. Sua verificação semântica deve validar o snapshot completo e negar fatos operacionais não confirmados. Não habilite `allow_unscoped_test_loader` fora de fixtures de compatibilidade. Não armazene credenciais, telefones ou IDs de contato no perfil.

## QA

Instale `requirements.txt` em ambiente isolado. Execute `unittest` em `review_tests` com a criação de sockets bloqueada depois da descoberta dos módulos (a suíte verifica esse bloqueio). A suíte adicional `test_shared_answer_engine.py` cobre identidade do motor demo/real, namespace/evidências, falhas sem fallback antigo, privacidade do contexto, dúvidas em todas as etapas e esclarecimento sem consentimento. `test_audit_natural_guidance.py` cobre os casos reais de linguagem identificados na auditoria.

Não disparar mensagens de teste para leads. Após deploy com a flag desligada, verificar saúde, versão e regressão; só depois habilitar e observar conversas autorizadas já chegando, sem reiniciar atendimentos nem reenviar convites.

### Vinculação de condições comerciais
O perfil Amplify mantém `APPROVED_COMMERCIAL_BINDINGS`: versão do perfil,
versão do contexto, fingerprint da política operacional e SHA-256 dos campos
factuais (`knowledge_version`, `personality`, `limits`, `topics`, JSON canônico).
Esse registro exige revisão humana/técnica explícita da compatibilidade; nunca
é atualizado automaticamente a partir do contexto vivo. Política incompatível
impede a construção do motor real e deixa `/ready` indisponível. Conteúdo alterado
mantendo a mesma versão falha fechado antes de chamar o modelo. A seleção pode
reduzir cartões inteiros, mas não alterar suas fontes, condições ou limites.
Um novo contexto/política exige revisão, novo par aprovado e regressão antes de
liberação. O registro não substitui consentimento ou recibo operacional.
