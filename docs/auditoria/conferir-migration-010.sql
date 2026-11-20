-- Conferência da migration cadastro/sql/010_destino_etiqueta_acesso_circle.sql
-- SÓ LEITURA. Rodar no SQL Editor do Supabase (projeto divlvdmsqbwplervsqwu).
-- Resultado esperado se JÁ foi aplicada: 1 linha, com pode_executar_service_role = true
-- e pode_executar_anon = false. Se voltar 0 linhas: NÃO foi aplicada.
SELECT p.oid::regprocedure                                   AS funcao,
       p.prosecdef                                           AS security_definer, -- esperado: false
       p.proconfig                                           AS config,           -- esperado: {search_path=""}
       has_function_privilege('service_role', p.oid, 'EXECUTE')  AS pode_executar_service_role,
       has_function_privilege('anon', p.oid, 'EXECUTE')          AS pode_executar_anon,
       has_function_privilege('authenticated', p.oid, 'EXECUTE') AS pode_executar_authenticated,
       md5(pg_get_functiondef(p.oid))                        AS md5_definicao
FROM pg_proc p
JOIN pg_namespace n ON n.oid = p.pronamespace
WHERE n.nspname = 'public'
  AND p.proname = 'destino_etiqueta_acesso_circle_v5';
