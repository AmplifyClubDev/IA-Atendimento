-- "Já sou Amplify" (27/11/2026): atendimento de quem já é agenciado, com conferência de identidade.
-- Fluxo (serviço de renovação): pede o @ → acha o agenciado → pede os 4 últimos dígitos do CPF
-- → se o WhatsApp não for o do cadastro, pede também a data de nascimento → confere aqui no banco
-- (CPF e nascimento nunca saem do banco: as funções só respondem se confere) → mostra o perfil e a renovação.
-- Sem limite de tentativas (decisão do Vitor, 27/11). Errou → "não conferem", sem dizer qual, e recomeça pelo CPF.
-- O CPF está em interno.creators (formulário); quem não tem CPF recebe o caminho do formulário.
-- As funções são SECURITY DEFINER (leem interno.creators) e só o service_role pode executá-las.
BEGIN;
SET LOCAL lock_timeout = '5s';

CREATE TABLE IF NOT EXISTS interno.agenciado_atendimentos (
  conversa text PRIMARY KEY,                 -- id da conversa no Chatwoot
  etapa text NOT NULL CHECK (etapa IN ('pedir_arroba', 'pedir_cpf', 'pedir_nascimento', 'verificado', 'sem_cpf')),
  arroba text,
  relation_id text,
  precisa_nascimento boolean NOT NULL DEFAULT true, -- false quando o WhatsApp da conversa é o do cadastro
  cpf_digitos text,                                  -- só entre a pergunta do CPF e a do nascimento; apagado na conferência
  tentativas smallint NOT NULL DEFAULT 0,
  criado_em timestamptz NOT NULL DEFAULT now(),
  atualizado_em timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE interno.agenciado_atendimentos ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON interno.agenciado_atendimentos FROM PUBLIC, anon, authenticated;
GRANT SELECT ON interno.agenciado_atendimentos TO service_role; -- registrar_resposta (SECURITY INVOKER) lê a etapa

-- Perfil para mostrar depois de conferido (sem CPF, sem telefone).
CREATE OR REPLACE FUNCTION interno.perfil_agenciado(rel text)
RETURNS jsonb LANGUAGE sql STABLE SECURITY DEFINER SET search_path = '' AS $fn$
  SELECT jsonb_build_object('tiktok', f.tiktok, 'nome', f.nome, 'situacao', f.situacao,
    'agenciado_em', to_char(f.agenciado_em, 'DD/MM/YYYY'), 'contrato_inicio', to_char(f.contrato_inicio, 'DD/MM/YYYY'),
    'contrato_fim', to_char(f.contrato_fim, 'DD/MM/YYYY'), 'dias_para_vencer', f.dias_para_vencer,
    'categoria', f.categoria, 'gmv_nivel', f.gmv_nivel, 'renovacao', coalesce(f.renovacao, 'Sem pedido'),
    'renovacao_expira_em', to_char(f.renovacao_expira_em, 'DD/MM/YYYY'), 'renovacao_novo_fim', to_char(f.renovacao_novo_fim, 'DD/MM/YYYY'),
    'relation_id', f.relation_id)
  FROM public.agenciados_ficha f WHERE f.relation_id = rel
$fn$;
REVOKE ALL ON FUNCTION interno.perfil_agenciado(text) FROM PUBLIC, anon, authenticated;

-- Chave do telefone: DDD + 8 últimos dígitos (o WhatsApp às vezes manda sem o 9; com ou sem o 55).
CREATE OR REPLACE FUNCTION interno.tel_chave(t text)
RETURNS text LANGUAGE sql IMMUTABLE SET search_path = '' AS $fn$
  SELECT CASE WHEN length(d) BETWEEN 10 AND 11 THEN left(d, 2) || right(d, 8) END
  FROM (SELECT regexp_replace(regexp_replace(coalesce(t, ''), '\D', '', 'g'), '^55(?=[0-9]{10,11}$)', '') AS d) x
$fn$;
REVOKE ALL ON FUNCTION interno.tel_chave(text) FROM PUBLIC, anon, authenticated;

-- p = {"conversa", "acao": "iniciar"|"consultar"|"arroba"|"cpf"|"nascimento", "arroba"?, "telefone"?, "digitos"?,
--      "nascimento"? (AAAA-MM-DD)}
CREATE OR REPLACE FUNCTION public.atendimento_agenciado_v5(p jsonb)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $fn$
DECLARE conv text := p ->> 'conversa'; a record; achado record; cpf_final text; nasc_real date; nasc date; arr text;
        mesmo_tel boolean;
BEGIN
  IF conv !~ '^[0-9]{1,18}$' THEN RAISE EXCEPTION USING errcode = '23514', message = 'Conversa inválida.'; END IF;
  IF p ->> 'acao' = 'iniciar' THEN
    INSERT INTO interno.agenciado_atendimentos (conversa, etapa) VALUES (conv, 'pedir_arroba')
    ON CONFLICT (conversa) DO UPDATE SET etapa = 'pedir_arroba', tentativas = 0, precisa_nascimento = true,
         cpf_digitos = NULL, arroba = NULL, relation_id = NULL, atualizado_em = now();
  END IF;
  SELECT * INTO a FROM interno.agenciado_atendimentos WHERE conversa = conv;
  IF NOT FOUND THEN RETURN jsonb_build_object('etapa', NULL); END IF;

  IF p ->> 'acao' = 'arroba' AND a.etapa = 'pedir_arroba' THEN
    arr := lower(btrim(ltrim(regexp_replace(coalesce(p ->> 'arroba', ''), '^.*tiktok\.com/@?', ''), '@')));
    arr := split_part(split_part(arr, '?', 1), '/', 1);
    SELECT f.relation_id, f.tiktok, f.nome INTO achado FROM public.agenciados_ficha f
    WHERE lower(ltrim(f.tiktok, '@')) = arr AND f.situacao IN ('Ativo', 'Saindo')
    ORDER BY f.contrato_fim DESC NULLS LAST LIMIT 1;
    IF achado.relation_id IS NULL THEN
      UPDATE interno.agenciado_atendimentos SET tentativas = tentativas + 1, atualizado_em = now() WHERE conversa = conv;
      RETURN jsonb_build_object('etapa', 'pedir_arroba', 'status', 'nao_encontrado', 'tentativas', a.tentativas + 1);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM interno.creators c WHERE lower(btrim(ltrim(c.tiktok, '@'))) = arr AND nullif(btrim(c.cpf), '') IS NOT NULL) THEN
      UPDATE interno.agenciado_atendimentos SET etapa = 'sem_cpf', arroba = arr, relation_id = achado.relation_id, atualizado_em = now()
      WHERE conversa = conv;
      RETURN jsonb_build_object('etapa', 'sem_cpf', 'status', 'sem_cpf', 'tiktok', achado.tiktok);
    END IF;
    -- Atalho: o WhatsApp que está escrevendo é o do cadastro → basta o CPF.
    mesmo_tel := interno.tel_chave(p ->> 'telefone') IS NOT NULL AND EXISTS (
      SELECT 1 FROM interno.creators c WHERE lower(btrim(ltrim(c.tiktok, '@'))) = arr
        AND interno.tel_chave(p ->> 'telefone') IN (interno.tel_chave(c.whatsapp), interno.tel_chave(c.telefone)));
    UPDATE interno.agenciado_atendimentos SET etapa = 'pedir_cpf', arroba = arr, relation_id = achado.relation_id, tentativas = 0,
           precisa_nascimento = NOT mesmo_tel, cpf_digitos = NULL, atualizado_em = now() WHERE conversa = conv;
    RETURN jsonb_build_object('etapa', 'pedir_cpf', 'status', 'encontrado', 'tiktok', achado.tiktok, 'nome', achado.nome,
                              'precisa_nascimento', NOT mesmo_tel);
  END IF;

  IF p ->> 'acao' = 'cpf' AND a.etapa = 'pedir_cpf' THEN
    IF coalesce(p ->> 'digitos', '') !~ '^[0-9]{4}$' THEN
      RETURN jsonb_build_object('etapa', 'pedir_cpf', 'status', 'formato');
    END IF;
    IF a.precisa_nascimento THEN
      -- Ainda não confere: guarda os dígitos até a data chegar (assim o "não confere" não diz qual dos dois errou).
      UPDATE interno.agenciado_atendimentos SET etapa = 'pedir_nascimento', cpf_digitos = p ->> 'digitos', atualizado_em = now()
      WHERE conversa = conv;
      RETURN jsonb_build_object('etapa', 'pedir_nascimento', 'status', 'pedir_nascimento');
    END IF;
  END IF;

  IF p ->> 'acao' = 'nascimento' AND a.etapa = 'pedir_nascimento' THEN
    BEGIN
      nasc := CASE WHEN p ->> 'nascimento' ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$' THEN (p ->> 'nascimento')::date END;
    EXCEPTION WHEN others THEN nasc := NULL;
    END;
    IF nasc IS NULL THEN RETURN jsonb_build_object('etapa', 'pedir_nascimento', 'status', 'formato_data'); END IF;
  END IF;

  IF (p ->> 'acao' = 'cpf' AND a.etapa = 'pedir_cpf') OR (p ->> 'acao' = 'nascimento' AND a.etapa = 'pedir_nascimento') THEN
    SELECT right(regexp_replace(c.cpf, '\D', '', 'g'), 4), c.data_nascimento INTO cpf_final, nasc_real FROM interno.creators c
    WHERE lower(btrim(ltrim(c.tiktok, '@'))) = a.arroba AND nullif(btrim(c.cpf), '') IS NOT NULL
    ORDER BY c.atualizado_em DESC NULLS LAST LIMIT 1;
    IF cpf_final IS DISTINCT FROM coalesce(a.cpf_digitos, p ->> 'digitos')
       OR (a.precisa_nascimento AND (nasc_real IS NULL OR nasc_real IS DISTINCT FROM nasc)) THEN
      -- Sem limite de tentativas (decisão do Vitor, 27/11): só conta, para o time ver. Recomeça pelo CPF.
      UPDATE interno.agenciado_atendimentos SET etapa = 'pedir_cpf', cpf_digitos = NULL, tentativas = tentativas + 1,
             atualizado_em = now() WHERE conversa = conv;
      RETURN jsonb_build_object('etapa', 'pedir_cpf', 'status', 'nao_confere', 'tentativas', a.tentativas + 1);
    END IF;
    UPDATE interno.agenciado_atendimentos SET etapa = 'verificado', cpf_digitos = NULL, tentativas = 0, atualizado_em = now()
    WHERE conversa = conv;
    RETURN jsonb_build_object('etapa', 'verificado', 'status', 'ok', 'perfil', interno.perfil_agenciado(a.relation_id));
  END IF;

  RETURN jsonb_build_object('etapa', a.etapa, 'status', 'consulta',
    'perfil', CASE WHEN a.etapa = 'verificado' THEN interno.perfil_agenciado(a.relation_id) END);
END
$fn$;
REVOKE ALL ON FUNCTION public.atendimento_agenciado_v5(jsonb) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.atendimento_agenciado_v5(jsonb) TO service_role;

-- Respostas aos botões: além das conversas que o serviço enviou, aceita as de agenciado conferido ("Já sou Amplify").
CREATE OR REPLACE FUNCTION public.registrar_resposta_renovacao_v5(p jsonb)
RETURNS jsonb LANGUAGE plpgsql SECURITY INVOKER SET search_path = '' AS $fn$
DECLARE e record; n integer; rel text; v_fim timestamptz; v_renov text; v_sit text;
BEGIN
  IF current_user NOT IN ('service_role', 'postgres') THEN
    RAISE EXCEPTION USING errcode = '42501', message = 'Só o sistema registra respostas.';
  END IF;
  IF (p ->> 'mensagem') !~ '^[0-9]{1,18}$' OR (p ->> 'conversa') !~ '^[0-9]{1,18}$'
     OR (p ->> 'resposta') NOT IN ('quero', 'nao_quero', 'duvida', 'motivo', 'outro') THEN
    RAISE EXCEPTION USING errcode = '23514', message = 'Resposta inválida.';
  END IF;
  SELECT r.id, r.relation_id, r.contrato_fim, a.renovacao, a.renovacao_expira_em, a.situacao
    INTO e
  FROM interno.renovacao_envios r
  LEFT JOIN public.agenciados_ficha a ON a.relation_id = r.relation_id
  WHERE r.chatwoot_conversa = p ->> 'conversa' AND r.situacao = 'enviado'
  ORDER BY r.enviado_em DESC NULLS LAST LIMIT 1;
  IF e.id IS NULL THEN
    SELECT at.relation_id, f.contrato_fim, f.renovacao, f.situacao INTO rel, v_fim, v_renov, v_sit
    FROM interno.agenciado_atendimentos at JOIN public.agenciados_ficha f ON f.relation_id = at.relation_id
    WHERE at.conversa = p ->> 'conversa' AND at.etapa = 'verificado';
  ELSE
    rel := e.relation_id;
  END IF;
  -- Conversa que o serviço não enviou (ex.: etiqueta antiga do n8n), sem agenciado conferido e não é teste: não é nossa.
  IF rel IS NULL AND coalesce((p ->> 'teste')::boolean, false) IS NOT TRUE THEN
    RETURN jsonb_build_object('status', 'fora', 'envio', NULL);
  END IF;
  INSERT INTO interno.renovacao_respostas (chatwoot_mensagem, chatwoot_conversa, envio_id, relation_id, telefone, resposta, motivo, texto)
  VALUES (p ->> 'mensagem', p ->> 'conversa', e.id, rel, left(regexp_replace(coalesce(p ->> 'telefone', ''), '\D', '', 'g'), 20),
          p ->> 'resposta', left(nullif(p ->> 'motivo', ''), 200), left(nullif(p ->> 'texto', ''), 500))
  ON CONFLICT (chatwoot_mensagem) DO NOTHING;
  GET DIAGNOSTICS n = ROW_COUNT;
  RETURN jsonb_build_object('status', CASE WHEN n = 1 THEN 'registrada' ELSE 'repetida' END,
    'envio', CASE WHEN e.id IS NOT NULL THEN jsonb_build_object('id', e.id, 'relation_id', e.relation_id,
      'contrato_fim', to_char(e.contrato_fim, 'DD/MM'), 'renovacao', e.renovacao, 'situacao', e.situacao)
      WHEN rel IS NOT NULL THEN jsonb_build_object('id', NULL, 'relation_id', rel,
      'contrato_fim', to_char(v_fim, 'DD/MM'), 'renovacao', v_renov, 'situacao', v_sit) END);
END
$fn$;
REVOKE ALL ON FUNCTION public.registrar_resposta_renovacao_v5(jsonb) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.registrar_resposta_renovacao_v5(jsonb) TO service_role;
COMMIT;
