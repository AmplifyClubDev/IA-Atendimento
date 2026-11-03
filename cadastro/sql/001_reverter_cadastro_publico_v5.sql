-- Volta para trás da 001_cadastro_publico_v5.sql.
-- Remove só as 5 funções novas e o bucket (se estiver vazio).
-- NÃO apaga cadastros já recebidos: eles ficam nas tabelas de sempre e são
-- identificáveis por interno.eventos.instancia='formulario_publico' e
-- interno.creators.formulario_submissao_referencia LIKE 'cadastro-publico-v5:%'.
BEGIN;
SET LOCAL lock_timeout='5s';
DROP FUNCTION IF EXISTS public.registrar_cadastro_publico_v5(jsonb,jsonb);
DROP FUNCTION IF EXISTS public.preparar_entrega_circle_v5(uuid);
DROP FUNCTION IF EXISTS public.confirmar_entrega_circle_v5(uuid,text,text,bigint,text,text);
DROP FUNCTION IF EXISTS public.consultar_cadastro_publico_v5(text,text,text);
DROP FUNCTION IF EXISTS interno.cadastro_publico_resolver(text,text,text);
DO $bucket$
BEGIN
 -- Imagens enviadas precisam ser movidas/apagadas pela API de Storage antes;
 -- com objetos dentro, o bucket é mantido e o aviso abaixo aparece.
 IF EXISTS(SELECT 1 FROM storage.objects WHERE bucket_id='cadastro-privado') THEN
  RAISE NOTICE 'bucket cadastro-privado mantido: contem imagens de cadastros recebidos';
 ELSE
  DELETE FROM storage.buckets WHERE id='cadastro-privado';
 END IF;
END;
$bucket$;
COMMIT;
