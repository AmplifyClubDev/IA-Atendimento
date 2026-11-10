"""Synthetic Ensaio fee/copy regression. No live model, DB or WhatsApp calls."""
from copy import deepcopy
from pathlib import Path
import io
import json
import unittest
from unittest.mock import Mock, patch

import config
from context_ia import _validated_context, load_context, load_demo_context
from demo_answers import build_answerer, _evidence_catalog, _answer_copy_issue
from demo_knowledge import select_demo_knowledge
from demo_support import build_semantic_verifier
from demo_flow import format_answer

VERSION = 'amplify_costs_20261110_v4'
SETTINGS = {'ai_enabled': True, 'openai_api_key': 'synthetic', 'ai_model': 'test',
            'demo_enabled': True, 'demo_context_version': VERSION,
            'v5_url': 'https://' + config.PROJECT_REF + '.supabase.co', 'v5_service_key': 'synthetic'}
ROWS = json.loads((Path(__file__).parent / 'fixtures' / 'costs-v4.json').read_text())
PAYLOAD = {'version': 'contextos-ia-v1:' + '1' * 32,
           'cards': [{k: v for k, v in row.items() if k != 'versao'} for row in ROWS]}
KNOWLEDGE = _validated_context(PAYLOAD, demo=True)
COST = ('Antes de ser agenciada, *você não paga nenhuma taxa*. 😊\n\n'
        'Depois, a taxa de gerenciamento é de *10% das suas comissões* no TikTok Shop, '
        'somente sobre vendas feitas após o início do agenciamento. As vendas anteriores ficam de fora.')
COMBINED = ('*Live não é obrigatória.* Você também pode trabalhar com vídeos. 🎥\n\n'
            'Antes de ser agenciada, você não paga taxa. Depois, a taxa de gerenciamento é de '
            '*10% das suas comissões* no TikTok Shop, só sobre vendas feitas após o início do '
            'agenciamento. Vendas anteriores ficam de fora.')


def envelope(value):
    return io.BytesIO(json.dumps({'status': 'completed', 'output': [{'type': 'message',
        'role': 'assistant', 'content': [{'type': 'output_text', 'text': json.dumps(value)}]}]}).encode())


def pipeline(question, texts, *, sources=('custos',), verdict='supported', dialogue=None):
    selected = select_demo_knowledge(KNOWLEDGE, question, dialogue)
    catalog = _evidence_catalog(selected)
    refs = [next(ref for ref, item in catalog.items() if item['id'] == source) for source in sources]
    opener = Mock()
    opener.open.side_effect = [envelope({'answer': text, 'evidence': refs}) for text in texts]
    support = Mock(return_value=verdict)
    loader = Mock(return_value=deepcopy(KNOWLEDGE))
    answer = build_answerer(SETTINGS, opener=opener, context_loader=loader, semantic_verifier=support)
    return answer, opener, loader, support


class KnowledgeCosts(unittest.TestCase):
    def test_candidate_is_exactly_opt_in_and_demo_only(self):
        self.assertIsNone(config.demo_context_issue(SETTINGS))
        self.assertEqual(config.demo_context_issue({**SETTINGS, 'demo_enabled': False}), 'demo_context_requires_demo')
        for version in (VERSION + ' ', VERSION.upper(), 'amplify_costs_20261110_v5'):
            self.assertEqual(config.demo_context_issue({**SETTINGS, 'demo_context_version': version}), 'demo_context_version_invalid')
        self.assertEqual(config.load_settings({})['demo_context_version'], '')

    def test_candidate_reader_and_production_reader_remain_separate(self):
        demo = Mock(return_value=PAYLOAD)
        active_payload = deepcopy(PAYLOAD)
        active_payload['cards'] = [row for row in active_payload['cards'] if row['id'] in ('bia', 'custos', 'promessas')]
        active = Mock(return_value=active_payload)
        self.assertEqual(load_demo_context(SETTINGS, transport=demo)['card_count'], 29)
        load_context(SETTINGS, transport=active)
        self.assertTrue(demo.call_args.kwargs['url'].endswith('/rpc/ler_contexto_ia_ensaio_v5'))
        self.assertEqual(demo.call_args.kwargs['json'], {'p_version': VERSION})
        self.assertTrue(active.call_args.kwargs['url'].endswith('/rpc/ler_contexto_ia_v5'))
        self.assertEqual(active.call_args.kwargs['json'], {})

    def test_cost_source_has_rate_denominator_cutoff_and_no_retroactivity(self):
        text = next(row['conteudo'] for row in ROWS if row['id'] == 'custos')
        for phrase in ('10%', 'sobre as comissões', 'vendas feitas depois do início do agenciamento',
                       'não cobra nenhuma taxa', 'Não há cobrança retroativa', 'mesmo que sejam recebidas depois',
                       'não o valor total das vendas', 'Não inventar outras cobranças',
                       'não confirma que a pessoa já é agenciada'):
            self.assertIn(phrase, text)
        for stale in ('registro histórico', 'referência histórica', 'oferta vigente de cada convite'):
            self.assertNotIn(stale, text)

    def test_global_limits_do_not_contradict_current_fee(self):
        for row in ROWS:
            self.assertNotIn('registro histórico de 10%', row['conteudo'])
            self.assertNotIn('taxa de agenciamento de 10%, sem mensalidade', row['conteudo'])
        for key in ('promessas', 'amplify_doc_claim_limits'):
            text = next(row['conteudo'] for row in ROWS if row['id'] == key)
            self.assertIn('custos', text)
            self.assertIn('10%', text)
            self.assertIn('nenhuma taxa antes', text)

    def test_live_source_remains_exactly_unchanged(self):
        self.assertEqual(next(row['conteudo'] for row in ROWS if row['id'] == 'lives'),
            'Fazer live não é obrigatório para participar da parceria. O creator também pode trabalhar com '
            'vídeos, conteúdo, divulgação de produtos e campanhas. Live é uma estratégia adicional. '
            'Se a pessoa quiser explorar esse formato, a orientação disponível depende das condições da parceria.')

    def test_question_variants_retrieve_current_full_fee_and_limits(self):
        for question in ('É obrigado fazer live e pagar?', 'Quanto custa entrar?', 'Vocês cobram 10%?',
                         'Pago antes de ser agenciada?', 'E as minhas vendas anteriores?',
                         'A taxa cai em cima das vendas ou da comissão?', 'Quando começa a cobrança?',
                         'A comissão de uma venda antiga chegou agora, vocês cobram?', 'Tem mensalidade?',
                         'Se eu não vender nada, quanto vou pagar?', 'É tudo gratuito para sempre?'):
            with self.subTest(question=question):
                selected = select_demo_knowledge(KNOWLEDGE, question)
                custos = next(t for t in selected['topics'] if t['id'] == 'custos')
                self.assertIn('mesmo que sejam recebidas depois', custos['answer'])
                self.assertIn('10%', selected['limits'])
                self.assertLessEqual(len(json.dumps(selected, ensure_ascii=False)), 48000)
                _evidence_catalog(selected)


class CopySafety(unittest.TestCase):
    def test_history_and_internal_attribution_are_detected(self):
        for text in ('No nosso histórico diz que são 10%.', 'A referência histórica é de 10%.',
                     'Historicamente eram 10%.', 'Segundo nossos registros, a live é opcional.',
                     'De acordo com nossos dados, não é obrigatório.', 'Na nossa base de conhecimento está assim.',
                     'Conforme as fontes, há uma taxa.', 'O material confirma a taxa.'):
            with self.subTest(text=text):
                self.assertIsNotNone(_answer_copy_issue(text))

    def test_commercial_base_of_calculation_is_not_internal_attribution(self):
        for text in ('A base de cálculo é sua comissão, não o valor total das vendas.',
                     'A taxa incide na base de cálculo das comissões.',
                     'Confira nos dados do seu perfil se está na conta correta.',
                     'As vendas anteriores ficam de fora.', 'Live não é obrigatória. 🎥', COST, COMBINED):
            self.assertIsNone(_answer_copy_issue(text))

    def test_first_bad_copy_is_rewritten_once_using_identical_source_snapshot(self):
        question = 'É obrigado fazer live e pagar?'
        answer, opener, loader, support = pipeline(question, ['No nosso histórico, são 10%.', COMBINED],
                                                   sources=('custos', 'lives'))
        result = answer(question)
        self.assertEqual(result['answer'], format_answer(COMBINED))
        self.assertEqual(opener.open.call_count, 2)
        loader.assert_called_once()
        support.assert_called_once()
        bodies = [json.loads(call.args[0].data) for call in opener.open.call_args_list]
        self.assertEqual(bodies[0]['input'], bodies[1]['input'])
        self.assertEqual(bodies[0]['text'], bodies[1]['text'])
        self.assertNotIn('Ao explicar taxas históricas', bodies[0]['instructions'])
        self.assertIn('Não mencione histórico', bodies[0]['instructions'])

    def test_repeated_copy_failure_blocks_delivery_without_third_attempt(self):
        answer, opener, _, support = pipeline('Quanto custa?', ['No histórico são 10%.'] * 3)
        with patch('builtins.print') as log:
            self.assertEqual(answer('Quanto custa?'), 'faq_unavailable')
        self.assertEqual(opener.open.call_count, 2)
        support.assert_not_called()
        self.assertEqual(json.loads(log.call_args.args[0])['category'], 'answer_copy')
        self.assertNotIn('No histórico', str(log.call_args_list))

    def test_copy_and_integrity_share_one_rewrite_budget(self):
        for texts in (['No histórico são 10%.', 'A taxa é de'], ['A taxa é de', 'No histórico são 10%.']):
            answer, opener, _, support = pipeline('Quanto custa?', texts + [COST])
            self.assertEqual(answer('Quanto custa?'), 'faq_unavailable')
            self.assertEqual(opener.open.call_count, 2)
            support.assert_not_called()

    def test_rewritten_text_still_requires_semantic_approval(self):
        answer, opener, _, support = pipeline('Quanto custa?', ['No histórico são 10%.', 'Tudo é gratuito.'],
                                               verdict='unsupported')
        self.assertEqual(answer('Quanto custa?'), 'faq_unavailable')
        self.assertEqual(opener.open.call_count, 2)
        support.assert_called_once()

    def test_copy_rule_is_global_and_preserves_live_only_answer(self):
        text = '*Live não é obrigatória.* Você também pode trabalhar com vídeos. 🎥'
        answer, opener, _, _ = pipeline('Preciso fazer live?', ['Segundo nossos registros, live não é obrigatória.', text],
                                         sources=('lives',))
        self.assertEqual(answer('Preciso fazer live?')['answer'], format_answer(text))
        self.assertEqual(opener.open.call_count, 2)
        self.assertNotIn('10%', format_answer(text))

    def test_invalid_citation_is_never_fixed_by_copy_rewrite(self):
        answer, opener, _, support = pipeline('Quanto custa?', [COST])
        opener.open.side_effect = [envelope({'answer': 'No histórico são 10%.', 'evidence': ['invented']})]
        self.assertEqual(answer('Quanto custa?'), 'faq_unavailable')
        opener.open.assert_called_once()
        support.assert_not_called()


class FeePipeline(unittest.TestCase):
    def test_short_grounded_answers_for_variants_keep_all_material_conditions(self):
        for question in ('Quanto custa?', 'Pago antes de ser agenciada?', 'Cobra do que vendi antes?',
                         'É 10% do GMV ou da comissão?', 'Tenho que fazer live e pagar?'):
            text = COMBINED if 'live' in question else COST
            sources = ('custos', 'lives') if 'live' in question else ('custos',)
            answer, opener, _, support = pipeline(question, [text], sources=sources)
            result = answer(question)
            self.assertEqual(result['answer'], format_answer(text))
            self.assertLess(len(text), 350)
            self.assertLessEqual(max(map(len, text.split('\n\n'))), 260)
            self.assertIn('10%', result['answer'])
            self.assertIn('comissões', result['answer'])
            support.assert_called_once()
            opener.open.assert_called_once()

    def test_claimed_acceptance_and_previous_bad_answer_do_not_confirm_membership(self):
        question = 'Aceitei o convite; os 10% cobram das vendas anteriores?'
        dialogue = {'return_step': 'invite', 'last_answer': 'Já está agenciada e paga 20% retroativos.',
                    'invitation_accepted': True, 'operational_context': {'real_membership_status': 'confirmed'}}
        answer, opener, _, support = pipeline(question, [COST])
        result = answer(question, conversation=dialogue)
        request = json.loads(json.loads(opener.open.call_args.args[0].data)['input'])
        self.assertEqual(request['operational_context']['real_membership_status'], 'unverified')
        self.assertEqual(request['operational_context']['confirmed_real_actions'], [])
        self.assertNotIn('invitation_accepted', request['conversation'])
        self.assertNotIn('20%', result['answer'])
        self.assertNotIn('já está agenciada', result['answer'])

    def test_false_fees_retroactivity_and_partial_answer_remain_blocked_by_verifier(self):
        # The mocked verdict tests runtime enforcement, not real-model judgement.
        for text in ('A taxa é 20%.', 'A taxa é 10% do valor total das vendas.',
                     'Você paga 10% antes de ser agenciada.', 'Cobramos também sobre vendas anteriores.',
                     'Você paga R$ 50 para entrar e R$ 30 mensais.', 'Tudo é gratuito para sempre.',
                     'Você já é agenciada.', 'Live não é obrigatória.'):
            answer, _, _, support = pipeline('Preciso fazer live e pagar?', [text],
                                              sources=('custos', 'lives'), verdict='unsupported')
            self.assertEqual(answer('Preciso fazer live e pagar?'), 'faq_unavailable')
            support.assert_called_once()

    def test_real_verifier_receives_current_rule_and_explicit_timing_checks(self):
        question = 'E as vendas anteriores?'
        selected = select_demo_knowledge(KNOWLEDGE, question)
        source = next(t for t in selected['topics'] if t['id'] == 'custos')
        candidate = {'answer': COST, 'knowledge_version': selected['knowledge_version'],
                     'evidence': [{'id': 'custos', 'quote': source['answer']}]}
        opener = Mock()
        opener.open.return_value = envelope({'verdict': 'supported'})
        self.assertEqual(build_semantic_verifier(SETTINGS, opener=opener)(question, candidate, selected, {}), 'supported')
        request = json.loads(opener.open.call_args.args[0].data)
        data = json.loads(request['input'])
        self.assertIn('mesmo que sejam recebidas depois', data['sources']['custos'])
        for requirement in ('base de cálculo', 'momento de início', 'retroativa', 'cobranças adicionais inventadas',
                            'gratuidade geral', 'Não aprove referência a histórico'):
            self.assertIn(requirement, request['instructions'])
        self.assertFalse(request['store'])
        self.assertNotIn('tools', request)
