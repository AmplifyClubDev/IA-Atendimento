"""Synthetic qualification -> declaration -> atomic gateway contract."""
import unittest
from copy import deepcopy
from chat_declarations import collect
from gateway import Gateway
from lead_validation import advance
import engine

AT = '2026-11-17T20:00:00Z'


class Declarations(unittest.TestCase):
    def event(self, text):
        return {'provider': 'chatwoot', 'account_id': '1', 'inbox_id': '3',
                'message_id': '123', 'text': text, 'created_at': AT, 'private': False}

    def cycle(self, stage='gmv'):
        return {'id': '11111111-1111-4111-8111-111111111111', 'facts': {},
                'bia_validation': {'stage': stage}}

    def qualified(self, text, stage='gmv'):
        cycle = self.cycle(stage); before = deepcopy(cycle)
        advance(cycle, text, engine._clock(AT))
        return collect(self.event(text), before, cycle)

    def test_actual_gmv_transition_preserves_units_and_source(self):
        row, = self.qualified('90 mil')
        self.assertEqual((row['valor'], row['periodo_dias'], row['moeda']), (9000000, 30, 'BRL'))
        self.assertEqual(row['mensagem_id'], '123')
        self.assertEqual(row['evidencia'], '90 mil')

    def test_zero_and_unknown_follow_approved_storage_policy(self):
        self.assertEqual(self.qualified('Sim, nenhuma venda', 'gmv_zero_confirmation')[0]['valor'], 0)
        self.assertEqual(self.qualified('Não sei')[0]['valor'], 0)
        self.assertEqual(self.qualified('Não sei')[0]['criterio_normalizacao'], 'nao_sabe')
        self.assertEqual(self.qualified('50-60k')[0]['valor'], 5000000)
        for text in ['mais de 50k', '50000 USD', '50k?']:
            with self.subTest(text=text): self.assertEqual(self.qualified(text), [])

    def test_old_gmv_not_attributed_to_new_message_or_reset(self):
        cycle = self.cycle('complete')
        cycle['facts']['gmv_30d_declarado_centavos'] = 9000000
        cycle['bia_validation']['gmv_at'] = AT
        self.assertEqual(collect(self.event('sim'), deepcopy(cycle), cycle), [])
        before = self.cycle(); before['id'] = 'different'
        self.assertEqual(collect(self.event('90 mil'), before, cycle), [])

    def test_followers_are_explicit_integer_counts_only(self):
        for text, amount in [('Tenho 5 mil seguidores', 5000), ('2.500 seguidores', 2500),
                             ('Estou com 5,5k seguidores', 5500)]:
            row, = collect(self.event(text), {}, self.cycle())
            self.assertEqual((row['campo'], row['valor'], row['moeda']), ('seguidores', amount, None))
        for text in ['Tenho mais de 5 mil seguidores', 'Tenho 5-6 mil seguidores',
                     'Tenho 5 mil seguidores?', 'Meu amigo tem 5000 seguidores', '5000']:
            self.assertEqual(collect(self.event(text), {}, self.cycle()), [])

    def test_private_and_other_inbox_do_not_collect(self):
        for key, value in [('private', True), ('inbox_id', '4'), ('account_id', '2')]:
            event = self.event('Tenho 5000 seguidores'); event[key] = value
            self.assertEqual(collect(event, {}, self.cycle()), [])

    def test_gateway_uses_atomic_rpc_only_for_declarations(self):
        calls = []
        creator = '22222222-2222-4222-8222-222222222222'
        def transport(**request):
            calls.append(request)
            return {'creator_id': creator, 'atendimento_id': None, 'event_id': 'chatwoot:1:123',
                    'revision': 1, 'cadastro_situacao': 'pendente'}
        gateway = Gateway({'v5_url': 'https://divlvdmsqbwplervsqwu.supabase.co',
                           'v5_service_key': 'synthetic'}, transport=transport)
        payload = {'event_id': 'chatwoot:1:123', 'revision': 1, 'atendimento_id': None}
        gateway.register_contact(payload)
        self.assertTrue(calls[-1]['url'].endswith('/registrar_contato_v5'))
        payload['declaracoes_chat'] = self.qualified('90 mil')
        gateway.register_contact(payload)
        self.assertTrue(calls[-1]['url'].endswith('/registrar_contato_declaracoes_v5'))
        self.assertNotIn('declaracoes_chat', calls[-1]['json']['p_entrada'])
        self.assertEqual(calls[-1]['json']['p_declaracoes'][0]['valor'], 9000000)

    def test_real_inbound_reaches_contact_payload_before_reply(self):
        import tempfile
        from datetime import datetime, timezone
        from pathlib import Path
        from server import create_app
        from repository import Repository
        from test_worker_form_context import Transport
        from test_real_executor import FakeClient, FakeGateway, GATE, EVENT
        with tempfile.TemporaryDirectory() as folder:
            entries = []
            class Recorder(FakeGateway):
                def register_contact(self, entry):
                    entries.append(deepcopy(entry))
                    return {**super().register_contact(entry), 'cadastro_situacao': 'pendente'}
            settings = {'tiktok_mode': 'real', 'real_worker_enabled': True, 'gate': dict(GATE),
                'state_dir': folder, 'webhook_token': 'w'*40, 'conversation_enabled': True,
                'ai_enabled': True, 'contact_sync_enabled': True, 'instance_id': 'offline-test',
                'readiness_issues': [], 'qualification_enabled': True,
                'tiktok_policy_approved': True, 'tiktok_invite_commission': '10',
                'tiktok_policy_version': 'offline', 'tiktok_commission_unit': 'percent',
                'tiktok_duration_fixed_months': '2', 'tiktok_duration_label': '2 meses'}
            repo = Repository(Path(folder)/'state.sqlite')
            app = create_app(settings, repo, Transport(),
                planner=lambda *_: {'provider_status': 'unknown', 'claims': []},
                real_client=FakeClient(), real_guard=lambda e: {'allowed': True})
            app.extensions['v5_data_gateway'] = Recorder()
            def send(number, text):
                event = {**EVENT, 'message_id': str(number), 'text': text,
                    'created_at': datetime.now(timezone.utc).isoformat(), 'source_ref': f'chatwoot:1:{number}'}
                with app.app_context(): result, code = app.extensions['v5_process_inbound'](event)
                self.assertEqual(code, 200, result)
            for number, text in enumerate(['Quero me agenciar', 'Não', 'Sim', '90 mil'], 800):
                send(number, text)
            self.assertEqual(entries[-1]['declaracoes_chat'][0]['valor'], 9000000)
            self.assertEqual(entries[-1]['declaracoes_chat'][0]['mensagem_id'], '803')
            send(804, 'Tenho 5 mil seguidores')
            self.assertEqual(entries[-1]['declaracoes_chat'][0]['campo'], 'seguidores')
            send(805, 'Oi')
            self.assertNotIn('declaracoes_chat', entries[-1])


if __name__ == '__main__':
    unittest.main()
