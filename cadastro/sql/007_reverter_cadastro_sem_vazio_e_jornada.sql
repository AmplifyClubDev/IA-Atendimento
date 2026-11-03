-- Reverte a 007. Os marcos gravados depois dela em interno.jornada se perdem (os anteriores
-- vêm das datas da ficha e voltam se a 007 for reaplicada). Recusa se o time já escreveu observações.
BEGIN;
SET LOCAL lock_timeout='5s';
SET LOCAL statement_timeout='60s';
DO $guard$
BEGIN
 IF to_regclass('interno.jornada') IS NULL OR to_regclass('interno.cadastro_planilha') IS NULL
   THEN RAISE EXCEPTION 'cadastro_publico_007_nao_aplicada'; END IF;
 IF EXISTS(SELECT 1 FROM interno.creators WHERE observacoes<>'')
   THEN RAISE EXCEPTION 'cadastro_publico_007_observacoes_preenchidas'; END IF;
END;
$guard$;

DROP VIEW interno.cadastro_planilha;
DROP FUNCTION interno.planilha_sim_nao(boolean), interno.planilha_data(timestamptz), interno.planilha_data(date),
 interno.planilha_numero(numeric), interno.planilha_lista(text[]), interno.planilha_rotulo(text),
 interno.planilha_nome_proprio(text), interno.planilha_nenhum(text), interno.planilha_condicional(text,boolean);
DROP TRIGGER v5_80_jornada ON interno.creators;
DROP TRIGGER v5_80_jornada ON interno.agenciamentos;
DROP FUNCTION interno.jornada_da_ficha(), interno.jornada_do_vinculo();
DROP TRIGGER v5_10_so_acrescenta ON interno.jornada;
DROP TABLE interno.jornada;
DROP FUNCTION interno.jornada_proteger(), interno.jornada_marcar(uuid,text,timestamptz,text,text,text);
ALTER TABLE interno.creators DROP CONSTRAINT creators_cadastro_completo;
ALTER TABLE interno.creators DROP COLUMN observacoes;
COMMIT;
