-- Testa agenciado_atendimento.sql numa subtransação desfeita no fim (usa um agenciado real com CPF, só leitura dele).
DO $test$
DECLARE r jsonb; arr text; fim4 text; errado text; cpf_todo text;
BEGIN
 BEGIN
  SELECT a.arroba, right(regexp_replace(c.cpf, '\D', '', 'g'), 4), regexp_replace(c.cpf, '\D', '', 'g') INTO arr, fim4, cpf_todo
  FROM interno.agenciados_tiktok a JOIN interno.creators c ON lower(btrim(ltrim(c.tiktok, '@'))) = a.arroba
  WHERE a.ativo AND nullif(btrim(c.cpf), '') IS NOT NULL LIMIT 1;
  errado := lpad(((fim4::int + 1) % 10000)::text, 4, '0');
  SET LOCAL ROLE service_role;
  r := public.atendimento_agenciado_v5('{"conversa": "990000001", "acao": "iniciar"}');
  IF r ->> 'etapa' <> 'pedir_arroba' THEN RAISE EXCEPTION 'iniciar %', r; END IF;
  r := public.atendimento_agenciado_v5('{"conversa": "990000001", "acao": "arroba", "arroba": "@zz_nao_existe_123"}');
  IF r ->> 'status' <> 'nao_encontrado' THEN RAISE EXCEPTION 'nao_encontrado %', r; END IF;
  r := public.atendimento_agenciado_v5(jsonb_build_object('conversa', '990000001', 'acao', 'arroba', 'arroba', 'https://www.tiktok.com/@' || arr || '?lang=pt'));
  IF r ->> 'status' <> 'encontrado' THEN RAISE EXCEPTION 'encontrado %', r; END IF;
  r := public.atendimento_agenciado_v5('{"conversa": "990000001", "acao": "cpf", "digitos": "12"}');
  IF r ->> 'status' <> 'formato' THEN RAISE EXCEPTION 'formato %', r; END IF;
  r := public.atendimento_agenciado_v5(jsonb_build_object('conversa', '990000001', 'acao', 'cpf', 'digitos', errado));
  IF r ->> 'status' <> 'nao_confere' OR r ? 'perfil' THEN RAISE EXCEPTION 'nao_confere %', r; END IF;
  r := public.atendimento_agenciado_v5(jsonb_build_object('conversa', '990000001', 'acao', 'cpf', 'digitos', fim4));
  IF r ->> 'status' <> 'ok' OR r -> 'perfil' ->> 'tiktok' IS NULL OR strpos(r::text, cpf_todo) > 0 OR r -> 'perfil' ? 'cpf' THEN RAISE EXCEPTION 'ok %', r; END IF;
  IF (public.atendimento_agenciado_v5('{"conversa": "990000001", "acao": "consultar"}')) ->> 'etapa' <> 'verificado' THEN RAISE EXCEPTION 'consultar'; END IF;
  -- Conferido: os botões de renovação passam a valer nesta conversa (sem envio registrado).
  r := public.registrar_resposta_renovacao_v5('{"mensagem": "990000101", "conversa": "990000001", "resposta": "duvida"}');
  IF r ->> 'status' <> 'registrada' OR r -> 'envio' ->> 'relation_id' IS NULL THEN RAISE EXCEPTION 'registrar_verificado %', r; END IF;
  r := public.registrar_resposta_renovacao_v5('{"mensagem": "990000102", "conversa": "990000002", "resposta": "duvida"}');
  IF r ->> 'status' <> 'fora' THEN RAISE EXCEPTION 'registrar_nao_verificado %', r; END IF;
  -- Sem limite: vários erros seguidos continuam pedindo o CPF, e o certo depois ainda confere.
  r := public.atendimento_agenciado_v5('{"conversa": "990000002", "acao": "iniciar"}');
  r := public.atendimento_agenciado_v5(jsonb_build_object('conversa', '990000002', 'acao', 'arroba', 'arroba', arr));
  r := public.atendimento_agenciado_v5(jsonb_build_object('conversa', '990000002', 'acao', 'cpf', 'digitos', errado));
  r := public.atendimento_agenciado_v5(jsonb_build_object('conversa', '990000002', 'acao', 'cpf', 'digitos', errado));
  r := public.atendimento_agenciado_v5(jsonb_build_object('conversa', '990000002', 'acao', 'cpf', 'digitos', errado));
  r := public.atendimento_agenciado_v5(jsonb_build_object('conversa', '990000002', 'acao', 'cpf', 'digitos', errado));
  IF r ->> 'etapa' <> 'pedir_cpf' OR r ->> 'status' <> 'nao_confere' THEN RAISE EXCEPTION 'sem_limite %', r; END IF;
  -- Antes do CPF certo, a conversa 990000002 não é aceita nos botões.
  r := public.registrar_resposta_renovacao_v5('{"mensagem": "990000102", "conversa": "990000002", "resposta": "duvida"}');
  IF r ->> 'status' <> 'fora' THEN RAISE EXCEPTION 'registrar_nao_verificado %', r; END IF;
  r := public.atendimento_agenciado_v5(jsonb_build_object('conversa', '990000002', 'acao', 'cpf', 'digitos', fim4));
  IF r ->> 'status' <> 'ok' THEN RAISE EXCEPTION 'certo_depois_de_erros %', r; END IF;
  RESET ROLE;
  SET LOCAL ROLE anon;
  BEGIN
    PERFORM public.atendimento_agenciado_v5('{"conversa": "1", "acao": "consultar"}');
    RAISE EXCEPTION 'anon_executou';
  EXCEPTION WHEN insufficient_privilege THEN NULL;
  END;
  RESET ROLE;
  RAISE EXCEPTION 'rollback_ok';
 EXCEPTION WHEN raise_exception THEN
  IF SQLERRM <> 'rollback_ok' THEN RAISE; END IF;
 END;
 RAISE NOTICE 'test_agenciado_atendimento: ok';
END
$test$;
