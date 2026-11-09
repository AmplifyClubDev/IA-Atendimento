"""Offline selection/ingestion checks; no database or provider requests."""
import copy
import json
import unittest
from context_ia import _validated_context
from demo_knowledge import select_demo_knowledge, MAX_CONTEXT_CHARS


def card(identifier, text, title=None, kind='conhecimento'):
    return dict(id=identifier, tipo=kind, titulo=title or identifier.replace('_', ' '),
                conteudo=text, atualizado_em='2026-11-09')


def payload(extra):
    return {'version': 'contextos-ia-v1:' + 'a' * 32, 'cards': [
        card('bia', 'Tom natural, respeite as condições.', kind='personalidade'),
        card('regras', 'Nunca invente nem garanta resultados.', kind='limites'), *extra]}


def knowledge(extra):
    # Exercise actual retrieval rather than the intentionally lossless small-catalog path.
    if len(extra) <= 8:
        extra = extra + [card('archive_' + str(i), 'Unrelated archival text.', 'Archive') for i in range(9 - len(extra))]
    return _validated_context(payload(extra), demo=True)


class KnowledgeSelectionTests(unittest.TestCase):
    def test_small_catalog_is_lossless_and_metadata_optional(self):
        data = _validated_context(payload([card('lives', 'Live opcional.')]), demo=True)
        del data['topics'][0]['title']
        del data['topics'][0]['patterns']
        self.assertEqual(select_demo_knowledge(data, 'O que oferece?'), data)

    def test_demo_headroom_does_not_change_production(self):
        data = payload([card('topic_' + str(i), 'a' * 3000) for i in range(70)])
        with self.assertRaisesRegex(ValueError, 'context_shape'):
            _validated_context(data)
        self.assertEqual(_validated_context(data, demo=True)['card_count'], 72)
        data = payload([card('topic_' + str(i), 'a' * 3000) for i in range(16)])
        with self.assertRaisesRegex(ValueError, 'context_too_large'):
            _validated_context(data)
        self.assertEqual(_validated_context(data, demo=True)['card_count'], 18)

    def test_catalog_still_bounded(self):
        with self.assertRaisesRegex(ValueError, 'context_too_large'):
            knowledge([card('topic_' + str(i), 'a' * 8000) for i in range(31)])
        with self.assertRaisesRegex(ValueError, 'context_shape'):
            knowledge([card('topic_' + str(i), 'small') for i in range(255)])

    def test_large_catalog_selects_whole_cards_and_does_not_mutate(self):
        data = knowledge([card('lives', 'Não é obrigatório fazer live. Condições se aplicam.'),
                          *[card('unrelated_' + str(i), 'Arquivo histórico. ' * 200) for i in range(40)]])
        before = copy.deepcopy(data)
        selected = select_demo_knowledge(data, 'Sou obrigada a fazer live?')
        self.assertEqual([t['id'] for t in selected['topics']], ['lives'])
        self.assertEqual(selected['knowledge_version'], data['knowledge_version'])
        self.assertEqual(selected['limits'], data['limits'])
        self.assertEqual(selected['personality'], data['personality'])
        self.assertLessEqual(len(json.dumps(selected, ensure_ascii=False)), MAX_CONTEXT_CHARS)
        selected['topics'][0]['answer'] = 'mutation'
        self.assertEqual(data, before)

    def test_compound_synonyms_and_exit_conditions(self):
        data = knowledge([card('lives', 'Live opcional.'), card('funcionamento', 'Pode sair, com ressalvas.'),
                          card('custos', 'Custos dependem do convite.'),
                          card('ja_tem_agencia', 'Confira a agência atual.'),
                          card('garantias', 'Sem garantia de renda.')])
        result = select_demo_knowledge(data, 'Preciso fazer ao vivo e posso encerrar a parceria sem multa?')
        self.assertEqual({t['id'] for t in result['topics']},
                         {'lives', 'funcionamento', 'custos', 'ja_tem_agencia', 'garantias'})

    def test_category_siblings_and_explicit_link(self):
        data = knowledge([card('amplify_doc_categories', 'Silver: ver regra_extra.'),
                          card('amplify_doc_monthly_journey', 'Categoria requer registro mensal.'),
                          card('amplify_doc_programs', 'Programas exigem confirmação.'),
                          card('regra_extra', 'Não classificar automaticamente.'),
                          card('garantias', 'Sem garantia.')])
        result = select_demo_knowledge(data, 'Quais as vantagens Silver?')
        self.assertEqual(len(result['topics']), 5)

    def test_sample_siblings_never_ranked_out(self):
        data = knowledge([card('amplify_doc_sample_types', 'Amostras gratuitas ou reembolsáveis.'),
                          card('amplify_doc_sample_approval', 'A marca decide.'),
                          card('amplify_doc_sample_process', 'Prazo da campanha prevalece.')])
        self.assertEqual(len(select_demo_knowledge(data, 'Recebo brindes?')['topics']), 3)

    def test_new_qualification_and_prefix_sibling(self):
        data = knowledge([card('novidade', 'Oferta publicada.', 'Novidade'),
                          card('novidade_criterios', 'Somente com confirmação.', 'Critérios'),
                          card('excecao', 'Nunca há direito automático.', 'Exceções importantes')])
        result = select_demo_knowledge(data, 'Como funciona a novidade?')
        self.assertEqual(len(result['topics']), 3)

    def test_reverse_reference_keeps_supplemental_rule(self):
        data = knowledge([card('oferta_nova', 'Oferta descrita.', 'Promoção'),
                          card('nota_recente', 'Ver oferta_nova: não disponível para todos.', 'Atualização')])
        result = select_demo_knowledge(data, 'Qual é a promoção?')
        self.assertEqual({t['id'] for t in result['topics']}, {'oferta_nova', 'nota_recente'})

    def test_history_only_resolves_references_not_new_questions(self):
        data = knowledge([card('lives', 'Live opcional.'), card('amplify_doc_sample_types', 'Amostras.'),
                          card('amplify_doc_sample_approval', 'A marca decide.')])
        dialogue = {'last_question': 'Como recebo amostra?', 'last_answer': 'Live é obrigatória.'}
        result = select_demo_knowledge(data, 'E nesse caso?', dialogue)
        self.assertTrue(result['selection']['history_used'])
        self.assertNotIn('lives', {t['id'] for t in result['topics']})
        result = select_demo_knowledge(data, 'Live é obrigatória?', dialogue)
        self.assertFalse(result['selection']['history_used'])
        self.assertEqual([t['id'] for t in result['topics']], ['lives'])

    def test_pending_clarification_short_replies_keep_both_question_topics(self):
        data = knowledge([card('lives', 'Live opcional.'),
                          card('amplify_doc_sample_types', 'Amostras.'),
                          card('amplify_doc_sample_approval', 'A marca decide.'),
                          card('amplify_doc_account_health', 'Consulte o aviso de violação.')])
        dialogue = {'last_question': 'Como recebo amostras?',
                    'pending_clarification': 'Você quer saber se precisa fazer live?',
                    'last_answer': 'Resposta anterior não é fonte factual.'}
        self.assertGreater(len(data['topics']), 8)
        for question in ('sim', 'ok', 'entendi', 'não', 'Não!', 'SIM.'):
            with self.subTest(question=question):
                result = select_demo_knowledge(data, question, dialogue)
                self.assertTrue(result['selection']['history_used'])
                self.assertEqual({t['id'] for t in result['topics']},
                                 {'lives', 'amplify_doc_sample_types', 'amplify_doc_sample_approval'})
        result = select_demo_knowledge(data, 'Como recorrer de uma violação?', dialogue)
        self.assertFalse(result['selection']['history_used'])
        self.assertEqual({t['id'] for t in result['topics']}, {'amplify_doc_account_health'})

    def test_short_reply_needs_valid_bounded_pending_question(self):
        data = knowledge([card('lives', 'Live opcional.')])
        for pending in ('', 'Você quer saber sobre live.', 'live ' * 60 + '?', None):
            with self.subTest(pending=pending):
                result = select_demo_knowledge(data, 'sim',
                    {'last_question': 'Live é obrigatória?', 'pending_clarification': pending})
                self.assertFalse(result['selection']['history_used'])
                self.assertEqual(result['topics'], [])
        # Handles in history are removed before they can become routing matches.
        result = select_demo_knowledge(data, 'ok',
            {'last_question': '@lives', 'pending_clarification': 'Quer confirmar o @lives?'})
        self.assertTrue(result['selection']['history_used'])
        self.assertEqual(result['topics'], [])

    def test_essential_bundle_over_budget_fails_closed(self):
        data = knowledge([card('oferta', 'Oferta disponível.'),
                          *[card('oferta_' + str(i), 'Ressalva completa. ' * 400) for i in range(7)]])
        with self.assertRaisesRegex(ValueError, 'demo_selection_budget_exceeded'):
            select_demo_knowledge(data, 'Qual é a oferta?')

    def test_editorial_rules_never_trimmed_to_fit(self):
        data = knowledge([card('lives', 'Live opcional.'),
                          *[card('regra_' + str(i), 'Limites de negócio. ' * 400, kind='limites')
                            for i in range(7)]])
        with self.assertRaisesRegex(ValueError, 'demo_selection_budget_exceeded'):
            select_demo_knowledge(data, 'Preciso fazer live?')

    def test_deterministic_without_rehashing_selected_snapshot(self):
        data = knowledge([card('lives', 'Live opcional.'), card('requisitos', 'Requisitos aprovados.')])
        reversed_data = copy.deepcopy(data)
        reversed_data['topics'].reverse()
        self.assertEqual(select_demo_knowledge(data, 'Live e requisitos?'),
                         select_demo_knowledge(reversed_data, 'Live e requisitos?'))


if __name__ == '__main__':
    unittest.main()
