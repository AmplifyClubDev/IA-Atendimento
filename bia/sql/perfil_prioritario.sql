BEGIN;
-- Extend the existing contact contract, preserving its transaction, identity,
-- revision, payload-hash replay and receipt validation rules.
DO $migration$
DECLARE definition text; old_fragment text;
BEGIN
 definition := pg_get_functiondef('public.registrar_contato_v5(jsonb)'::regprocedure);
 old_fragment := E'  for k in select jsonb_object_keys(p_entrada->''qualificacao'') loop\n';
 IF position(old_fragment in definition)=0 OR position('perfil_tiktok' in definition)>0 THEN
  RAISE EXCEPTION 'unexpected_contact_function_version';
 END IF;
 definition := replace(definition, old_fragment, old_fragment || $validation$
   if k='perfil_tiktok' then
    if jsonb_typeof(p_entrada->'qualificacao'->k) is distinct from 'object'
      or not (p_entrada->'qualificacao'->k) ?& array['handle','url','origem','declarado_em','mensagem_id','verificado']
      or (select count(*) from jsonb_object_keys(p_entrada->'qualificacao'->k))<>6
      or coalesce(p_entrada->'qualificacao'->k->>'handle','') !~ '^@[a-z0-9_][a-z0-9_.]{1,23}$'
      or right(p_entrada->'qualificacao'->k->>'handle',1)='.'
      or p_entrada->'qualificacao'->k->>'handle' is distinct from p_entrada->'qualificacao'->>'tiktok_declarado'
      or p_entrada->'qualificacao'->k->>'url' is distinct from 'https://www.tiktok.com/'||(p_entrada->'qualificacao'->k->>'handle')
      or p_entrada->'qualificacao'->k->'verificado' is distinct from 'false'::jsonb
      or coalesce(p_entrada->'qualificacao'->k->>'origem','') not in ('chat_declarado','contexto_anterior') then
      raise exception 'contact_profile_invalid' using errcode='22023';
    end if;
    if p_entrada->'qualificacao'->k->>'origem'='chat_declarado' then
     if jsonb_typeof(p_entrada->'qualificacao'->k->'mensagem_id') is distinct from 'string'
       or coalesce(p_entrada->'qualificacao'->k->>'mensagem_id','') !~ '^[1-9][0-9]{0,19}$'
       or jsonb_typeof(p_entrada->'qualificacao'->k->'declarado_em') is distinct from 'string'
       or coalesce(p_entrada->'qualificacao'->k->>'declarado_em','') !~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}T.*(Z|[+]00:00)$'
       or not isfinite((p_entrada->'qualificacao'->k->>'declarado_em')::timestamptz)
       or (p_entrada->'qualificacao'->k->>'declarado_em')::timestamptz > statement_timestamp()+interval '5 minutes'
       or (p_entrada->'qualificacao'->k->>'declarado_em')::timestamptz > (p_entrada->>'observado_em')::timestamptz then
      raise exception 'contact_profile_source_invalid' using errcode='22023';
     end if;
    elsif p_entrada->'qualificacao'->k->'mensagem_id' is distinct from 'null'::jsonb
       or p_entrada->'qualificacao'->k->'declarado_em' is distinct from 'null'::jsonb then
     raise exception 'contact_profile_prior_source_invalid' using errcode='22023';
    end if;
    continue;
   end if;
$validation$);
 EXECUTE definition;
END;
$migration$;
-- Keep collected metadata on legacy callers/rollback, only for the same handle.
CREATE FUNCTION interno.preservar_perfil_tiktok_v5() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $fn$
BEGIN
 IF TG_OP='UPDATE' AND NOT NEW.qualificacao ? 'perfil_tiktok'
   AND OLD.qualificacao ? 'perfil_tiktok'
   AND NEW.qualificacao->>'tiktok_declarado' IS NOT DISTINCT FROM OLD.qualificacao->'perfil_tiktok'->>'handle' THEN
  NEW.qualificacao := NEW.qualificacao || jsonb_build_object('perfil_tiktok',OLD.qualificacao->'perfil_tiktok');
 END IF;
 RETURN NEW;
END;
$fn$;
REVOKE ALL ON FUNCTION interno.preservar_perfil_tiktok_v5() FROM PUBLIC,anon,authenticated;
CREATE TRIGGER v5_03_preservar_perfil_tiktok BEFORE UPDATE OF qualificacao ON interno.atendimentos
 FOR EACH ROW EXECUTE FUNCTION interno.preservar_perfil_tiktok_v5();
NOTIFY pgrst,'reload schema';
COMMIT;
