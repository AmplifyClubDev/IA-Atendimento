-- Foto de perfil (25/11/2026): para o Amplify OS mostrar a foto que a pessoa enviou no formulário.
-- Só o ID e o caminho da foto no bucket privado "cadastro-privado". Só o sistema (service_role) lê.
-- A foto continua privada: o servidor do Amplify OS busca com a chave dele e entrega a quem está logado.
BEGIN;
SET LOCAL lock_timeout = '5s';

CREATE OR REPLACE VIEW public.creators_foto AS
SELECT c.id, c.foto_perfil_referencia AS foto_ref
FROM interno.creators c
WHERE c.foto_perfil_referencia LIKE 'publico/%';

REVOKE ALL ON public.creators_foto FROM PUBLIC, anon, authenticated;
GRANT SELECT ON public.creators_foto TO service_role;
COMMIT;
