"""Release 40: reconferir sozinha quem parou na conferência do perfil com a ponte fora.

Casos reais de 31/10 (ponte de pré-validação em human_login_required de 04:22 a 16:59):
- conversa 56747 (Emy, @emytododiademaria): "A consulta precisa de uma verificação de segurança…";
- conversa 56752 (Thaina, @thaina_teodoroo_): "Não consegui confirmar seu perfil… Vou pedir para o time".
"""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest

import contracts
import real_journey as journey
import reconferencia
from config import load_settings
from real_operations import build_jobs
from repository import Repository
from test_release39 import FakeChatwoot, GATE, PHONE
from test_relationship_form_chat30 import POLICY, qualified, settle

EMY = {'conversation': '56747', 'contact': '8801', 'phone': '+5511987654301', 'handle': '@emytododiademaria'}
THAINA = {'conversation': '56752', 'contact': '8802', 'phone': '+5511987654302', 'handle': '@thaina_teodoroo_'}
DOWN = 'human_verification_required'


def bridge_down(state, effect, reason=DOWN):
    return settle(state, effect, 'verification_pending', confirmed=False, evidence={}, reason=reason)


class JourneyTests(unittest.TestCase):
    """A falha da ponte marca o atendimento; o resultado da reconferência segue a conversa."""

    def stuck(self, reason=DOWN):
        result = qualified()
        effect = next(item for item in result['effects'] if item['operation'] == 'precheck')
        return bridge_down(result['state'], effect, reason)

    def test_bridge_down_marks_the_wait_with_an_honest_short_message(self):
        result = self.stuck()
        cycle = result['state']['cycle']
        self.assertEqual(cycle['phase'], 'blocked')
        self.assertEqual(cycle['bridge_wait']['reason'], DOWN)
        self.assertEqual(result['reply'], journey._BRIDGE_WAIT)
        self.assertNotIn('time', result['reply'])
        self.assertEqual(journey._phase_prompt(cycle), journey._BRIDGE_STILL)

    def test_profile_conditions_are_never_retried(self):
        self.assertNotIn('bridge_wait', self.stuck('shop_unknown')['state']['cycle'])
        result = qualified()
        effect = next(item for item in result['effects'] if item['operation'] == 'precheck')
        ineligible = settle(result['state'], effect, 'ineligible')
        for state, reason in ((self.stuck('shop_unknown')['state'], 'shop_unknown'), (ineligible['state'], None)):
            with self.subTest(reason=reason):
                self.assertFalse(journey.bridge_retry_due(state, datetime.now(timezone.utc), reason=reason))

    def test_retry_is_silent_and_eligible_continues_to_the_invite_conditions(self):
        state = self.stuck()['state']
        now = datetime.now(timezone.utc)
        self.assertTrue(journey.bridge_retry_due(state, now))
        effect = journey.bridge_retry_effect(state, now)
        self.assertEqual(effect['payload']['source'], 'bridge_retry')
        self.assertEqual(state['cycle']['bridge_wait']['retries'], 1)
        self.assertFalse(journey.bridge_retry_due(state, now))  # a consulta já está na fila
        event = {'account_id': '1', 'conversation_id': '56747', 'message_id': '10', 'provider': 'chatwoot'}
        self.assertIn('precheck-bridge:', build_jobs(event, state, [effect])[0]['job_key'] + 'precheck-bridge:')
        done = settle(state, effect, 'eligible')
        self.assertEqual(done['state']['cycle']['phase'], 'consent_real')
        self.assertTrue(done['reply'].startswith(journey._BRIDGE_BACK))
        self.assertNotIn('bridge_wait', done['state']['cycle'])
        self.assertNotIn('Qual é o seu @', done['reply'])

    def test_bridge_down_again_during_the_retry_says_nothing(self):
        state = self.stuck()['state']
        now = datetime.now(timezone.utc)
        effect = journey.bridge_retry_effect(state, now)
        again = bridge_down(state, effect)
        self.assertEqual(again.get('reply', ''), '')
        self.assertEqual(again['state']['cycle']['phase'], 'blocked')
        self.assertFalse(journey.bridge_retry_due(again['state'], now + timedelta(minutes=5)))
        self.assertTrue(journey.bridge_retry_due(again['state'], now + timedelta(minutes=11)))

    def test_retries_stop_after_the_limit(self):
        state = self.stuck()['state']
        now = datetime.now(timezone.utc)
        for attempt in range(journey.BRIDGE_RETRY_LIMIT):
            effect = journey.bridge_retry_effect(state, now + timedelta(minutes=11 * attempt))
            state = bridge_down(state, effect)['state']
        self.assertIsNone(journey.bridge_retry_effect(state, now + timedelta(hours=2)))

    def test_model_reply_promising_the_team_is_replaced(self):
        # Thaina às 16:10: "assim que o time conferir… te aviso". Ninguém confere à mão.
        state = self.stuck()['state']
        plan = {'provider_status': 'completed', 'intent': 'question',
                'reply': 'Assim que o time conferir seu perfil, te aviso por aqui.'}
        reply = journey._question_reply('E aí?', plan, state['cycle'], POLICY, state=state,
                                        now=datetime.now(timezone.utc))
        reply = reply[0] if isinstance(reply, tuple) else reply
        self.assertNotIn('time', reply)


class FakeBridgeClient:
    """Ponte de pré-validação: fora até ``self.up`` virar True."""

    def __init__(self):
        self.up, self.calls = False, []

    def configuration(self, operation=None):
        return {'configured': True, 'issues': []}

    def _ready(self, role):
        if not self.up:
            raise RuntimeError('human_verification_required')

    def execute(self, operation, creator, **kwargs):
        self.calls.append((operation, creator))
        observed = datetime.now(timezone.utc).isoformat()
        if operation == 'precheck' and not self.up:
            return {'operation': operation, 'creator': creator, 'status': 'verification_pending', 'confirmed': False,
                    'observed_at': observed, 'evidence': {}, 'reason': DOWN}
        status = 'eligible' if operation == 'precheck' else 'not_found'
        return {'operation': operation, 'creator': creator, 'status': status, 'confirmed': True,
                'observed_at': observed, 'evidence': {'source': 'offline', 'complete': True}, 'reason': 'precheck_observed'}


class RealCasesTests(unittest.TestCase):
    """Emy e Thaina pelo caminho inteiro: webhook → ponte fora → ponte volta → varredura → convite."""

    def setUp(self):
        from server import create_app
        from test_real_executor import FakeGateway
        tmp = tempfile.TemporaryDirectory(dir=Path.cwd(), prefix='release40-')
        self.addCleanup(tmp.cleanup)
        self.repo = Repository(Path(tmp.name) / 'state.sqlite3')
        phones, issue = contracts.parse_pilot_phones(','.join([PHONE, EMY['phone'], THAINA['phone']]), PHONE)
        self.assertIsNone(issue)
        self.chatwoot = FakeChatwoot()
        self.chatwoot.ready = lambda: True
        self.sent = []
        self.chatwoot.send_reply = lambda event, text, buttons, key, **_: (
            self.sent.append((str(event['conversation_id']), text)) or {'status': 'accepted', 'message_id': str(9000 + len(self.sent))})
        self.client = FakeBridgeClient()
        settings = {'tiktok_mode': 'real', 'real_worker_enabled': True, 'gate': {**GATE, 'phones': phones},
                    'state_dir': tmp.name, 'webhook_token': 'w' * 40, 'conversation_enabled': True, 'ai_enabled': True,
                    'contact_sync_enabled': True, 'instance_id': 'offline-test', 'readiness_issues': [],
                    'relationship_check_in_form': True, 'retomada_enabled': True, 'pos_pausa_enabled': True,
                    'reconferencia_enabled': True, 'tiktok_policy_approved': True, 'tiktok_invite_commission': '10',
                    'tiktok_policy_version': 'test-approved-v1', 'tiktok_commission_unit': 'percent',
                    'tiktok_duration_fixed_months': '2', 'tiktok_duration_label': '2 meses'}
        unknown = {'provider_status': 'unknown', 'claims': [], 'reply': '', 'intent': 'clarify'}
        self.app = create_app(settings, self.repo, self.chatwoot, planner=lambda *_: dict(unknown),
                              real_client=self.client, real_guard=lambda _: {'allowed': True})
        self.app.extensions['v5_data_gateway'] = FakeGateway()
        self.executor = self.app.extensions['v5_real_executor']
        self.offset = timedelta(0)
        self.executor.clock = lambda: datetime.now(timezone.utc) + self.offset
        self.scan = self.app.extensions['v5_reconferencia']
        self.message_id = 70000

    def say(self, lead, text):
        self.message_id += 1
        event = {'provider': 'chatwoot', 'event': 'message_created', 'account_id': '1', 'inbox_id': '3',
                 'conversation_id': lead['conversation'], 'contact_id': lead['contact'], 'message_id': str(self.message_id),
                 'sender_phone': lead['phone'], 'sender_type': 'contact', 'message_type': 'incoming', 'private': False,
                 'text': text, 'created_at': datetime.now(timezone.utc).isoformat(),
                 'source_ref': 'chatwoot:1:' + str(self.message_id)}
        with self.app.app_context():
            body, code = self.app.extensions['v5_process_inbound'](event)
        self.assertEqual(code, 200, body)

    def reach_precheck(self, lead):
        for text in ('oi', 'Quero me agenciar', 'Indicação', lead['handle']):
            self.say(lead, text)
        self.drain()
        return self.repo.load_session('chatwoot:1:' + lead['conversation'])

    def drain(self):
        # O @ enfileira a consulta do perfil e a leitura de dados públicos (lookup).
        for _ in range(5):
            if self.executor.tick()['status'] == 'idle':
                return
        self.fail('fila não esvaziou')

    def probe(self):
        self.executor.probe_sessions()

    def texts(self, lead):
        return [text for conv, text in self.sent if conv == lead['conversation']]

    def run_scan(self):
        self.scan.next_scan_at = None
        return self.scan.tick()

    def test_emy_and_thaina_are_rechecked_once_each_when_the_bridge_returns(self):
        emy = self.reach_precheck(EMY)
        self.assertEqual(emy['cycle']['phase'], 'blocked')
        self.assertEqual(self.texts(EMY)[-1], journey._BRIDGE_WAIT)
        thaina = self.reach_precheck(THAINA)
        # Thaina parou na 39: sem a marca, com a resposta antiga "vou pedir para o time".
        thaina['cycle'].pop('bridge_wait')
        self.repo.save_session('chatwoot:1:' + THAINA['conversation'], thaina)
        self.assertEqual([row['conversation'] for row in reconferencia.candidates(self.repo, self.executor.clock())],
                         ['chatwoot:1:56747', 'chatwoot:1:56752'])

        self.say(EMY, 'E aí, conseguiu?')
        self.assertEqual(self.texts(EMY)[-1], journey._BRIDGE_STILL)

        self.probe()
        self.assertEqual(self.run_scan()['status'], 'bridge_not_ready')
        self.client.up = True
        self.probe()
        before = len(self.sent)
        self.assertEqual(self.run_scan()['status'], 'queued')  # um lead por varredura
        self.assertEqual(len(self.sent), before)                 # a fila não manda mensagem
        self.assertEqual(self.executor.tick()['status'], 'completed')
        self.assertEqual(self.run_scan()['status'], 'queued')
        self.assertEqual(self.executor.tick()['status'], 'completed')
        self.assertEqual(self.run_scan()['status'], 'idle')

        for lead in (EMY, THAINA):
            with self.subTest(lead=lead['handle']):
                state = self.repo.load_session('chatwoot:1:' + lead['conversation'])
                self.assertEqual(state['cycle']['phase'], 'consent_real')
                last = self.texts(lead)[-1]
                self.assertTrue(last.startswith(journey._BRIDGE_BACK))
                self.assertNotIn('Qual é o seu @', last)
                self.assertEqual(sum(text == journey._BRIDGE_WAIT for text in self.texts(lead)), 1)
        self.assertEqual([call for call in self.client.calls if call[0] == 'precheck'],
                         [('precheck', 'emytododiademaria'), ('precheck', 'thaina_teodoroo_'),
                          ('precheck', 'emytododiademaria'), ('precheck', 'thaina_teodoroo_')])

    def test_bridge_flapping_during_the_retry_stays_silent_and_waits_ten_minutes(self):
        self.reach_precheck(EMY)
        self.client.up = True
        self.probe()
        self.assertEqual(self.run_scan()['status'], 'queued')
        self.client.up = False                       # caiu de novo antes da consulta
        count = len(self.sent)
        self.assertEqual(self.executor.tick()['status'], 'completed')
        self.assertEqual(len(self.sent), count)      # nada repetido ao lead
        self.client.up = True
        self.probe()
        self.assertEqual(self.run_scan()['status'], 'idle')
        self.offset += timedelta(minutes=11)
        self.probe()
        self.assertEqual(self.run_scan()['status'], 'queued')
        self.assertEqual(self.executor.tick()['status'], 'completed')
        self.assertTrue(self.texts(EMY)[-1].startswith(journey._BRIDGE_BACK))

    def test_switch_and_status(self):
        self.assertTrue(load_settings({})['reconferencia_enabled'])
        self.assertFalse(load_settings({'V5_RECONFERENCIA_ENABLED': 'false'})['reconferencia_enabled'])
        self.assertIn('reconferencia', self.executor.followup_status())


if __name__ == '__main__':
    unittest.main()
