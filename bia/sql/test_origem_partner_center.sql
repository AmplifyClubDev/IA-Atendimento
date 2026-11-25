-- Testa origem_partner_center.sql (só leitura).
DO $test$
BEGIN
  IF EXISTS (SELECT 1 FROM public.agenciados_ficha WHERE passou_pela_bia = 'Não' AND origem IS DISTINCT FROM 'Partner Center') THEN
    RAISE EXCEPTION 'ficha_sem_origem'; END IF;
  IF EXISTS (SELECT 1 FROM public.partner_center WHERE origem_lead IS NULL) THEN RAISE EXCEPTION 'pc_sem_origem'; END IF;
  IF (SELECT count(*) FROM public.partner_center) <> (SELECT count(DISTINCT id_parceria) FROM public.partner_center) THEN
    RAISE EXCEPTION 'id_repetido'; END IF;
  RAISE NOTICE 'test_origem_partner_center: ok';
END
$test$;
