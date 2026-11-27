-- Testa agenciado_atendimento.sql numa subtransação desfeita no fim (usa um agenciado real com CPF, só leitura dele).
DO $test$
DECLARE r jsonb; arr text; fim4 text; errado text; cpf_todo text; nasc date; tel text;
BEGIN
 BEGIN
  SELECT a.arroba, right(regexp_replace(c.cpf, '\D', '', 'g'), 4), regexp_replace(c.cpf, '\D', '', 'g'), c.data_nascimento,
         coalesce(nullif(btrim(c.whatsapp), ''), c.telefone)
    INTO arr, fim4, cpf_todo, nasc, tel
  FROM interno.agenciados_tiktok a JOIN interno.creators c ON lower(btrim(ltrim(c.tiktok, '@'))) = a.arroba
  WHERE a.ativo AND nullif(btrim(c.cpf), '') IS NOT NULL AND c.data_nascimento IS NOT NULL
    AND interno.tel_chave(coalesce(nullif(btrim(c.whatsapp), ''), c.telefone)) IS NOT NULL LIMIT 1;
  errado := lpad(((fim4::int + 1) % 10000)::text, 4, '0');

  -- Chave do telefone: com/sem 55, com/sem o 9.
  IF interno.tel_chave('+55 (47) 99115-4859') <> interno.tel_chave('4791154859') THEN RAISE EXCEPTION 'tel_chave_9'; END IF;
  IF interno.tel_chave('5547991154859') <> '4791154859' OR interno.tel_chave('12345') IS NOT NULL THEN RAISE EXCEPTION 'tel_chave'; END IF;

  SET LOCAL ROLE service_role;
  -- Caminho 1: outro número → CPF + nascimento.
  r := public.atendimento_agenciado_v5('{"conversa": "990000001", "acao": "iniciar"}');
  IF r ->> 'etapa' <> 'pedir_arroba' THEN RAISE EXCEPTION 'iniciar %', r; END IF;
  r := public.atendimento_agenciado_v5('{"conversa": "990000001", "acao": "arroba", "arroba": "@zz_nao_existe_123"}');
  IF r ->> 'status' <> 'nao_encontrado' THEN RAISE EXCEPTION 'nao_encontrado %', r; END IF;
  r := public.atendimento_agenciado_v5(jsonb_build_object('conversa', '990000001', 'acao', 'arroba',
         'arroba', 'https://www.tiktok.com/@' || arr || '?lang=pt', 'telefone', '+5511900000000'));
  IF r ->> 'status' <> 'encontrado' OR (r ->> 'precisa_nascimento')::boolean IS NOT TRUE THEN RAISE EXCEPTION 'encontrado %', r; END IF;
  r := public.atendimento_agenciado_v5('{"conversa": "990000001", "acao": "cpf", "digitos": "12"}');
  IF r ->> 'status' <> 'formato' THEN RAISE EXCEPTION 'formato %', r; END IF;
  -- CPF errado: ainda não diz nada, pede a data; depois "não confere" sem dizer qual errou, e recomeça pelo CPF.
  r := public.atendimento_agenciado_v5(jsonb_build_object('conversa', '990000001', 'acao', 'cpf', 'digitos', errado));
  IF r ->> 'status' <> 'pedir_nascimento' THEN RAISE EXCEPTION 'cpf_errado_pede_data %', r; END IF;
  r := public.atendimento_agenciado_v5(jsonb_build_object('conversa', '990000001', 'acao', 'nascimento', 'nascimento', nasc::text));
  IF r ->> 'status' <> 'nao_confere' OR r ->> 'etapa' <> 'pedir_cpf' OR r ? 'perfil' THEN RAISE EXCEPTION 'cpf_errado %', r; END IF;
  -- CPF certo, data errada / inválida.
  r := public.atendimento_agenciado_v5(jsonb_build_object('conversa', '990000001', 'acao', 'cpf', 'digitos', fim4));
  r := public.atendimento_agenciado_v5('{"conversa": "990000001", "acao": "nascimento", "nascimento": "2001-02-30"}');
  IF r ->> 'status' <> 'formato_data' THEN RAISE EXCEPTION 'formato_data %', r; END IF;
  r := public.atendimento_agenciado_v5(jsonb_build_object('conversa', '990000001', 'acao', 'nascimento', 'nascimento', (nasc + 1)::text));
  IF r ->> 'status' <> 'nao_confere' THEN RAISE EXCEPTION 'data_errada %', r; END IF;
  IF (SELECT cpf_digitos FROM interno.agenciado_atendimentos WHERE conversa = '990000001') IS NOT NULL THEN RAISE EXCEPTION 'digitos_ficaram'; END IF;
  -- Os dois certos.
  r := public.atendimento_agenciado_v5(jsonb_build_object('conversa', '990000001', 'acao', 'cpf', 'digitos', fim4));
  r := public.atendimento_agenciado_v5(jsonb_build_object('conversa', '990000001', 'acao', 'nascimento', 'nascimento', nasc::text));
  IF r ->> 'status' <> 'ok' OR r -> 'perfil' ->> 'tiktok' IS NULL OR strpos(r::text, cpf_todo) > 0 OR r -> 'perfil' ? 'cpf'
     OR strpos(r::text, nasc::text) > 0 THEN RAISE EXCEPTION 'ok %', r; END IF;
  IF (SELECT cpf_digitos FROM interno.agenciado_atendimentos WHERE conversa = '990000001') IS NOT NULL THEN RAISE EXCEPTION 'digitos_ficaram_ok'; END IF;
  IF (public.atendimento_agenciado_v5('{"conversa": "990000001", "acao": "consultar"}')) ->> 'etapa' <> 'verificado' THEN RAISE EXCEPTION 'consultar'; END IF;
  -- Conferido: os botões de renovação passam a valer nesta conversa (sem envio registrado).
  r := public.registrar_resposta_renovacao_v5('{"mensagem": "990000101", "conversa": "990000001", "resposta": "duvida"}');
  IF r ->> 'status' <> 'registrada' OR r -> 'envio' ->> 'relation_id' IS NULL THEN RAISE EXCEPTION 'registrar_verificado %', r; END IF;

  -- Caminho 2: WhatsApp do cadastro → basta o CPF; sem limite de tentativas.
  r := public.atendimento_agenciado_v5('{"conversa": "990000002", "acao": "iniciar"}');
  r := public.atendimento_agenciado_v5(jsonb_build_object('conversa', '990000002', 'acao', 'arroba', 'arroba', arr, 'telefone', tel));
  IF (r ->> 'precisa_nascimento')::boolean IS NOT FALSE THEN RAISE EXCEPTION 'atalho_tel %', r; END IF;
  FOR i IN 1..4 LOOP
    r := public.atendimento_agenciado_v5(jsonb_build_object('conversa', '990000002', 'acao', 'cpf', 'digitos', errado));
  END LOOP;
  IF r ->> 'etapa' <> 'pedir_cpf' OR r ->> 'status' <> 'nao_confere' THEN RAISE EXCEPTION 'sem_limite %', r; END IF;
  r := public.registrar_resposta_renovacao_v5('{"mensagem": "990000102", "conversa": "990000002", "resposta": "duvida"}');
  IF r ->> 'status' <> 'fora' THEN RAISE EXCEPTION 'registrar_nao_verificado %', r; END IF;
  r := public.atendimento_agenciado_v5(jsonb_build_object('conversa', '990000002', 'acao', 'cpf', 'digitos', fim4));
  IF r ->> 'status' <> 'ok' THEN RAISE EXCEPTION 'certo_so_cpf %', r; END IF;
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
