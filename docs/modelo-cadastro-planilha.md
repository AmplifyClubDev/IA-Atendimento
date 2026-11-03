# Modelo de cadastro (planilha "Principal") × banco atual

## Migração 007 (montada em 03/11/2026, **não aplicada em produção**)

Arquivos: `sql/007_cadastro_sem_vazio_e_jornada.sql` e `sql/007_reverter_cadastro_sem_vazio_e_jornada.sql`.

| O quê | Como |
|---|---|
| `interno.jornada` | um marco por linha, só acrescenta; gravada por gatilho nas fichas e nos vínculos; histórico atual copiado das datas guardadas |
| `interno.cadastro_planilha` | as 71 colunas na ordem + Canal de entrada (real), Campanha / anúncio, Consentimento, Situação atual; só texto; a migration falha se houver célula vazia |
| `creators.observacoes` | campo do time, padrão vazio, mostrado como "Sem observações" |
| `creators_cadastro_completo` | cadastro confirmado precisa de todas as obrigatórias e das condicionais que se aplicam |

Conferências:
- ✅ **Produção, só leitura:** os 8 cadastros passam na trava, e a planilha ensaiada com os dados reais dá 75 colunas e 0 vazias.
- ✅ **Banco local descartável:** os 31 testes do formulário passam com a 007, e mais 12 conferências também (gatilhos, só acrescenta, reversão, reaplicação, aplicar duas vezes recusado).

Ainda sai como texto padrão, até mudar o código:
- **Período do GMV:** "Não informado no cadastro", até o leitor do print ler o período.
- **Campanha / anúncio:** "Não identificado", até a Bia guardar de qual anúncio a conversa veio.

Conferido em 03/11/2026 contra o Supabase (`interno.*`) e o formulário (`app/data/field-map.json`, 63 campos). Só leitura, nada alterado.

## 1. Veredito

| | Ponto | Situação |
|---|---|---|
| ✅ | 60 das 71 colunas | já existem no banco e vêm do formulário, preenchidas nos 8 cadastros |
| ❌ | 6 colunas | ficam vazias hoje (tabela 3) |
| ❌ | "Como chegou" | a planilha só tem o que a pessoa **declarou**; a origem real (anúncio, orgânico, indicação) está vazia nos 8 |
| ⚠️ | Jornada | a ideia está certa, mas hoje o banco **sobrescreve** a etapa em vez de guardar o histórico |
| ⚠️ | "Nenhum null" | 14 campos são condicionais (só aparecem se outra resposta pedir): precisam de um texto padrão, não de vazio |

## 2. Sua proposta: cadastro de entrada + jornada depois

**Está certa, com um ajuste:** são três coisas diferentes, e hoje estão misturadas na mesma tabela (`interno.creators`):

| O quê | Muda? | Onde deve ficar |
|---|---|---|
| **Pessoa / lead** (telefone, @, primeiro contato, canal real) | quase nunca | ficha da pessoa, desde a 1ª mensagem |
| **Cadastro** (as 71 colunas da planilha) | não: é a foto do dia do formulário | tabela de cadastro, **sem nenhum vazio** |
| **Jornada** (validou, convite, aceitou, agenciado, desvinculou, renovou, categoria mudou) | sempre | linha nova a cada marco, com data, **nunca sobrescrita** |

Hoje:
- 32 das 40 fichas são leads sem formulário. Se o cadastro exigir zero vazio na mesma tabela, essas fichas quebram, por isso o cadastro precisa ser separado.
- `historico_jornada` está vazio nas 40 fichas: não é usado.
- `interno.eventos` só guarda a mudança de etapa da conversa. Convite enviado, aceito e agenciado ficam em colunas que são sobrescritas, então o histórico se perde.
- `interno.agenciamentos` já está certo (um período por vínculo, com renovações). É o modelo para o resto da jornada.

## 3. Colunas que ficam vazias hoje

| Coluna da planilha | Por quê | Proposta |
|---|---|---|
| **Período do GMV** | o formulário não pergunta; `gmv.periodo_*` vazio nos 8 | ler o período do próprio print (o leitor do print já lê o valor) |
| **Data de entrada** | `primeira_mensagem_em` vazio em 4 de 8 (entraram direto pelo formulário) | 1º contato conhecido: 1ª mensagem; se não houver conversa, a data do formulário |
| **Data de agenciamento** | `agenciamentos.inicio_em` vazio nos 9 vínculos | usar a data em que a máquina comprovou o vínculo (`confirmado_em`, preenchida) e gravá-la também em `inicio_em` |
| **País** | não existe; o formulário só aceita os 27 estados | "Brasil", derivado do estado |
| **Observações** | não existe | campo do time; padrão "Sem observações" |
| **Contato** | `telefone` vazio nos 8 | usar `whatsapp` (preenchido nos 8) e remover a coluna duplicada `telefone` |

Também: `gmv_entrada_id` não liga a ficha ao GMV em nenhum dos 8 (o GMV existe, só não está ligado).

## 4. "Nenhum null": textos padrão

| Situação | Texto | Exemplos |
|---|---|---|
| Campo condicional que não se aplica | **Não se aplica** | CNPJ sem CNPJ, "Quais pets?" sem pet, Instagram sem Instagram |
| Dado da máquina ainda não aconteceu | **Pendente** | Data de agenciamento antes do aceite |
| Sim/Não | **Sim** / **Não** | nunca `true`/`false` |
| Listas | itens separados por ", " | Nichos, Plataformas, Idiomas |

Os 14 condicionais: Outro tamanho de camiseta, Outros nichos, Outra forma de conhecer, @ Instagram, Outras plataformas, Nome e experiência da agência anterior, Outra rotina, CNPJ, Restrição alimentar, Quais pets, Vídeo em outro idioma, Idiomas falados, Outros idiomas.

**Como garantir no banco:** a tabela guarda cada dado com o tipo certo (data como data, número como número), com campos obrigatórios travados. A planilha sai de uma **visão** com as 71 colunas na sua ordem, todas em texto, aplicando a tabela acima, e um teste falha se aparecer qualquer vazio.

## 5. Qualidade das respostas (não é vazio, mas suja a planilha)

- Caixa misturada: cabelo "liso" e "Ondulado", cidade "BELO HORIZONTE". Padronizar ao gravar.
- Respostas que são "nada": contexto adicional "Nenhum" e "Creio que não", produtos excluídos "nenhum". Padronizar para "Nenhum".
- @ Instagram sem @ ("Alex"). Validar o formato no formulário.

## 6. Sugestão de colunas a acrescentar

| Coluna | Por quê |
|---|---|
| **Canal de entrada (real)** | anúncio, orgânico, indicação, campanha: é o "como chegou" de verdade; o "Como conheceu" é o que a pessoa diz |
| **Campanha / anúncio** | qual anúncio trouxe |
| **Consentimento (data e versão)** | prova da LGPD; já existe no banco |
| **Situação atual** | agenciado, desvinculado, renovado: calculada pela jornada, não digitada |

## 7. Mapa completo (71 colunas)

| # | Coluna | Origem no banco | Hoje |
|---|---|---|---|
| 1 | ID | `creators.id` | ✅ |
| 2 | Nome | `nome` | ✅ |
| 3 | @ TikTok | `tiktok` (conferido na ponte) | ✅ |
| 4 | GMV | `gmv.valor` (declarado + print) | ✅ (sem ligação na ficha) |
| 5 | Período do GMV | `gmv.periodo_inicio/fim` | ❌ |
| 6 | Categoria | `circle_categoria_entrada` | ✅ |
| 7 | Contato | `whatsapp` | ✅ (`telefone` ❌) |
| 8 | E-mail | `email` | ✅ |
| 9 | Cidade | `endereco_cidade` | ✅ |
| 10 | País | não existe | ❌ → "Brasil" |
| 11 | Data de entrada | `primeira_mensagem_em` / `formulario_recebido_em` | ⚠️ 4/8 |
| 12 | Agenciado? | `agenciamentos` (vínculo aberto) | ✅ |
| 13 | Data de agenciamento | `agenciamentos.inicio_em` | ❌ |
| 14 | Observações | não existe | ❌ |
| 15 | Foto de perfil | `foto_perfil_referencia` | ✅ |
| 16 | Apresentação | `mini_bio` | ✅ |
| 17–20 | Nascimento, Gênero, Estado civil, Camiseta | colunas próprias | ✅ |
| 21 | Outro tamanho de camiseta | `camiseta_outro` | condicional |
| 22 | Nichos | `nichos` | ✅ |
| 23 | Outros nichos | `nichos_outros` | condicional |
| 24–26 | Cabelo, Calçado, Cor ou raça | colunas próprias | ✅ |
| 27 | Como conheceu | `origem_informada_formulario` | ✅ (declarado) |
| 28 | Outra forma de conhecer | `origem_outro` | condicional |
| 29–32 | Apoio esperado, Meta, Contexto, Plataformas | `expectativas`, `meta_renda_mensal`, `contexto_adicional`, `plataformas` | ✅ |
| 33–34 | @ Instagram, Outras plataformas | `instagram`, `plataformas_outros` | condicional |
| 35–36 | Live Shop, Outra agência? | `experiencia_live_shop`, `teve_agencia_anterior` | ✅ |
| 37–38 | Nome e experiência da agência | `nome_agencia_anterior`, `experiencia_agencia` | condicional |
| 39–41 | Produtos excluídos, Início informado, Rotina | colunas próprias | ✅ |
| 42 | Outra rotina | `rotina_outro` | condicional |
| 43–44 | +2.000 seguidores, Print do GMV | `declarou_mais_2000_seguidores`, `gmv.comprovante_referencia` | ✅ |
| 45–50 | Estado, Logradouro, Bairro, Número, Complemento, CEP | `endereco_*` | ✅ |
| 51–53 | CPF, PIX, Possui CNPJ | `cpf`, `pix_chave`, `possui_cnpj` | ✅ |
| 54 | CNPJ | `cnpj` | condicional |
| 55–56 | Filhos, Alimentação | colunas próprias | ✅ |
| 57 | Restrição alimentar | `restricao_alimentar` | condicional |
| 58–66 | Casa, Carro, Moto, Celular, Computador, Tripé, Microfone, Academia, Pet | colunas próprias | ✅ |
| 67 | Quais pets | `pets` | condicional |
| 68 | Outro idioma? | `outro_idioma` | ✅ |
| 69–71 | Vídeo, Idiomas, Outros idiomas | `video_idioma`, `idiomas`, `idiomas_outros` | condicional |
