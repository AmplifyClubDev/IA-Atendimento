CREATE OR REPLACE VIEW public.atendimentos WITH (security_invoker=true) AS
SELECT a.id,
    a.creator_id,
    c.nome,
    c.tiktok,
        CASE a.etapa
            WHEN 'entrada'::text THEN 'Entrada'::text
            WHEN 'intro'::text THEN 'Apresentação'::text
            WHEN 'menu'::text THEN 'Início'::text
            WHEN 'know'::text THEN 'Conhecer a Amplify'::text
            WHEN 'origin'::text THEN 'Origem'::text
            WHEN 'tiktok'::text THEN 'Perfil do TikTok'::text
            WHEN 'shop'::text THEN 'TikTok Shop'::text
            WHEN 'agency'::text THEN 'Agenciamento'::text
            WHEN 'await_acceptance'::text THEN 'Aceite do convite'::text
            WHEN 'form'::text THEN 'Formulário'::text
            WHEN 'cadastro_confirmado'::text THEN 'Cadastro'::text
            WHEN 'closed'::text THEN 'Encerramento'::text
            ELSE 'A confirmar'::text
        END AS etapa,
        CASE
            WHEN a.situacao = 'aberto'::text AND a.expires_at <= statement_timestamp() THEN 'Prazo encerrado'::text
            WHEN a.situacao = 'aberto'::text THEN 'Em atendimento'::text
            WHEN a.situacao = 'encerrado'::text THEN 'Encerrado'::text
            WHEN a.situacao = 'expirado'::text THEN 'Prazo encerrado'::text
            ELSE 'A confirmar'::text
        END AS situacao,
    a.primeira_mensagem_em AS inicio_em,
    a.ultima_mensagem_em,
    a.expires_at AS prazo_em,
        CASE a.motivo_encerramento
            WHEN '24h_sem_mensagem'::text THEN '24 horas sem mensagem'::text
            ELSE initcap(replace(a.motivo_encerramento, '_'::text, ' '::text))
        END AS encerramento,
        CASE COALESCE(a.origem ->> 'value'::text, a.qualificacao ->> 'origem_declarada'::text)
            WHEN 'anuncio'::text THEN 'Anúncio'::text
            WHEN 'indicacao'::text THEN 'Indicação'::text
            WHEN 'outro'::text THEN 'Outro'::text
            WHEN 'nao_informado'::text THEN 'Não informado'::text
            ELSE COALESCE(NULLIF(COALESCE(a.origem ->> 'value'::text, a.qualificacao ->> 'origem_declarada'::text), ''::text), 'Não informado'::text)
        END AS origem,
    a.atualizado_em
   FROM interno.atendimentos a
     JOIN interno.creators c ON c.id = a.creator_id;
