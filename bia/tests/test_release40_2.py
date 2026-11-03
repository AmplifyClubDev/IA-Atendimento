"""Release 40.2: a 40.1 com a pós-pausa lendo todas as páginas de conversas abertas do Chatwoot (02/11)."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
import re
import tempfile
import unittest

import contracts
import retomada
from repository import Repository

AD = 'Oi, quero saber mais sobre agenciamento de creators'
class PosPausaPagesTests(unittest.TestCase):
    """02/11, 40.1 no ar: a pós-pausa respondeu 6 de 8 leads e pulou 56866 e 56865.

    O lead de 56866 escreveu em 01/11 às 16:12 e o de 56865 às 13:09 (Brasília). Nos dois casos a última
    mensagem era o aviso de manutenção. As duas conversas estavam abertas, sem etiqueta e sem responsável.
    Elas estavam além das 25 conversas da primeira página do Chatwoot, a única que a 40 lia.
    """
    NOW = datetime(2026, 11, 2, 8, 30, tzinfo=timezone.utc)          # 05:30 de Brasília
    REAL = {56866: datetime(2026, 11, 1, 19, 12, tzinfo=timezone.utc),  # 16:12 de Brasília
            56865: datetime(2026, 11, 1, 16, 9, tzinfo=timezone.utc)}   # 13:09 de Brasília

    def setUp(self):
        from test_release39 import FakeChatwoot, GATE, PHONE
        tmp = tempfile.TemporaryDirectory(dir=Path.cwd(), prefix='regressao41-')
        self.addCleanup(tmp.cleanup)
        self.repo = Repository(Path(tmp.name) / 'state.sqlite3')
        conversations, self.history, phones = [], {}, []
        # 30 conversas abertas mais recentes, de leads fora da lista (receberam só a manutenção).
        for index in range(30):
            conversations.append(self.conversation(57000 + index, '+551190000' + format(index, '04d'),
                                                   self.NOW - timedelta(minutes=10 + 20 * index)))
        for conv, arrived in self.REAL.items():
            phone = '+5511988' + str(conv)[1:] + '0'
            phones.append(phone)
            conversations.append(self.conversation(conv, phone, arrived))
        conversations.sort(key=lambda item: -item['last_activity_at'])
        parsed, issue = contracts.parse_pilot_phones(','.join([PHONE] + phones), PHONE)
        self.assertIsNone(issue)
        self.chatwoot, self.pages = FakeChatwoot(), []
        self.chatwoot.http = lambda **request: self.http(conversations, **request)
        self.calls = []
        self.subject = retomada.PosPausa(self.repo, {'pos_pausa_enabled': True, 'tiktok_mode': 'real',
                                         'real_worker_enabled': True, 'conversation_enabled': True,
                                         'gate': {**GATE, 'phones': parsed}},
                                         self.chatwoot, lambda _: {'allowed': True}, self.process, now=lambda: self.NOW)

    def conversation(self, conv, phone, arrived):
        notice = {'id': conv * 10 + 1, 'message_type': 1, 'private': False, 'content': 'Estamos em manutenção',
                  'content_attributes': {'automation_rule_id': 3}, 'created_at': arrived.timestamp() + 2}
        self.history[conv] = [{'id': conv * 10, 'message_type': 0, 'private': False, 'content': AD,
                               'created_at': arrived.timestamp()}, notice]
        return {'id': conv, 'inbox_id': 3, 'meta': {'sender': {'id': conv, 'phone_number': phone}},
                'last_activity_at': int(arrived.timestamp()) + 2, 'last_non_activity_message': deepcopy(notice)}

    def http(self, conversations, *, method, url, headers, timeout, json_body=None):
        if '/conversations?' in url:
            page = int(re.search(r'[?&]page=(\d+)', url).group(1)) if 'page=' in url else 1
            self.pages.append(page)
            return {'data': {'payload': deepcopy(conversations[25 * (page - 1):25 * page])}}
        return {'payload': deepcopy(self.history[int(url.rsplit('/', 2)[-2])])}

    def process(self, event, resumed):
        self.assertTrue(self.repo.reserve_event(event['source_ref'], 'chatwoot:1:' + str(event['conversation_id']), 'webhook'))
        self.calls.append((event['conversation_id'], resumed['texts']))
        return {'status': 'completed'}

    def scan(self):
        self.subject.next_scan_at = None
        return self.subject.tick()

    def test_both_leads_beyond_the_first_page_are_answered_once(self):
        for _ in range(4):
            self.scan()
        self.assertEqual(sorted(conv for conv, _ in self.calls), [56865, 56866])
        for _, texts in self.calls:
            self.assertEqual(texts, [AD])
        self.pages.clear()
        self.assertEqual(self.scan()['status'], 'idle')
        self.assertEqual(self.pages, [1, 2, 3])  # 32 conversas: a página 3 vem vazia e a leitura para
