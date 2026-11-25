# Diagnóstico das quedas — alteração preparada em 25/11/2026

Status: código local; nenhuma publicação, reinicialização ou mensagem de teste real.
Base: origin/main 0375c5c. Escopo de ativação proposto: Pré-validação e o monitor
do Cadastro. O código tiktok-ponte é compartilhado com Agenciamento, mas isso não
autoriza publicar nesse segundo serviço. Convites não foi alterada.

## Evidência adicionada

- RAM atual, limite, pico e contador oom_kill do cgroup, incluindo subprocessos
  Chrome. RSS do Node fica separado. Amostra a cada 60 segundos e nos eventos.
- OOM confirmado apenas por incremento do contador no cgroup ou código explícito.
  RAM alta, texto “out of memory” e SIGKILL isolado não provam que o Chrome morreu
  por memória. Se o contêiner inteiro morrer, dados não gravados podem se perder;
  o diagnóstico deve então ser cruzado com eventos/métricas do Railway.
- Crash/fechamento de página/contexto; fechamento controlado identificado como
  esperado; saída de processo com código/sinal e nome do subprocesso.
- HTTP e código numérico da API na rejeição da consulta autenticada de readiness.
  Categoria da página (login, CAPTCHA, MFA, verificação ou parceiro), sem URL.
- Tentativas de recuperação e resultado; HTTP aceito não comprova sessão pronta.
- auto_reconcile bem-sucedido deixa de ser emitido como erro sem mensagem.

As novas observações não fazem login, convite ou consulta adicional ao TikTok.
Reutilizam eventos do Playwright, leitura da sonda existente e arquivos do cgroup.
Nenhum HTML, screenshot, mensagem livre, creator, cookie ou token é persistido.

## Persistência e consumo

- Ponte: /data/bridge-diagnostics.jsonl e rotação .1; até cerca de 1 MB, mais estado
  atômico em bridge-diagnostics-state.json. Supervisor usa prefixo supervisor.
- Cadastro: pontes-diagnostico.sqlite3 junto de CADASTRO_STATE_PATH; retenção de
  até 2.000 eventos ou 14 dias. Falha no armazenamento é registrada sem parar
  monitoramento/recuperação.
- Readiness autenticado preserva os campos diagnostics, inclusive em HTTP 503 e
  modo login. Console/status autenticado também os expõe. Health público não muda.
- Histórico sobrevivente não é prova de causa do incidente atual: classificador
  só usa causa técnica com timestamp recente; contadores cumulativos de OOM
  não são interpretados como um novo evento.

## Compatibilidade

Preserva autenticação, bloqueio de redirecionamentos, espera de rate limit,
sessão compartilhada do painel, prova de leitura autenticada e políticas de
reconexão da versão atual. O alerta mantém confirmações e espera já existentes,
mas elimina afirmações não comprovadas de logout, nova autenticação ou tentativa
de recuperação. Falhas sustentadas de infraestrutura passam a ser observadas.

Os patches do Cadastro já publicados via bootstrap devem ser preservados.
Não publicar o checkout antigo inteiro nem substituir variáveis secretas.
O diretório novo está isolado em branch fix/diagnostico-ponte-20261125.

Não recupera retroativamente a causa das quedas passadas: a coleta só começará
após o deploy autorizado. Não aumenta memória nem modifica campanhas/contratos.

Validação local: 37 testes Python (diagnóstico, vigia, operação e Telegram) e
27 testes Node (diagnóstico, segurança, política interativa, handoff, detalhes
e recuperação automática), todos aprovados. Verificações sintáticas do servidor
e supervisor e git diff --check aprovadas. Cenários sintéticos, sem derrubar a
ponte, sem consultar creators reais e sem enviar alertas reais.
