import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from retomada import PosPausa, Decisoes

class BoundedPosPausa(unittest.TestCase):
    def make(self, total=80, slow_pages=False):
        now=datetime(2026,11,12,18,tzinfo=timezone.utc)
        self.elapsed=0; self.requests=[]; self.sent=[]
        def http(**kw):
            self.requests.append(kw)
            page=int(kw['url'].split('page=')[-1])
            if slow_pages: self.elapsed += 10
            rows=([{'id':str(i+1),'last_activity_at':now.isoformat()} for i in range(total)] if page==1 else [])
            if slow_pages: rows=[{'id':str(page),'last_activity_at':now.isoformat()}]
            return {'data':{'payload':rows}}
        settings={'pos_pausa_enabled':True,'tiktok_mode':'real','real_worker_enabled':True,
                  'conversation_enabled':True,'gate':{'enabled':True,'account_id':'1','inbox_id':'2'}}
        worker=PosPausa(None,settings,SimpleNamespace(base_url='https://example.invalid',token='fake',http=http),
                       lambda event:{'allowed':True},lambda event,**kw:self.sent.append(event) or {'status':'completed'},now=lambda:now)
        worker.monotonic=lambda:self.elapsed
        worker.decisions=Decisoes()
        worker._candidate=lambda conv,*args:(None,'ja_respondida_no_chatwoot')
        return worker
    def test_25_conversations_each_tick_and_cooldown_only_at_end(self):
        w=self.make()
        for index in (25,50,75):
            self.assertEqual(w.tick()['status'],'scanning')
            self.assertEqual(w._progress['index'],index)
            self.assertIsNone(w.next_scan_at)
            self.assertEqual(w.counts['varreduras'],0)
        result=w.tick()
        self.assertEqual(result['status'],'idle'); self.assertEqual(result['conversas_lidas'],80)
        self.assertEqual(w.counts['varreduras'],1); self.assertIsNone(w._progress)
        self.assertEqual(w.tick()['status'],'cooldown')
        self.assertEqual(len(self.requests),2)
    def test_slow_pagination_never_runs_20_timeouts_one_tick(self):
        w=self.make(slow_pages=True)
        for page in range(1,21):
            result=w.tick()
            self.assertEqual(len(self.requests),page)
            self.assertLessEqual(self.requests[-1]['timeout'],10)
            if page<20:self.assertEqual(result['status'],'scanning')
        self.assertTrue(w._progress['listed'])
        self.assertEqual(w.tick()['status'],'idle')
        self.assertEqual(len(self.requests),20)
    def test_one_resumed_across_full_scan(self):
        w=self.make()
        def candidate(conv,*args):
            return {'provider':'chatwoot','account_id':'1','message_id':conv['id'],
                    'conversation_id':conv['id'],'_texts':['oi']},None
        w._candidate=candidate
        results=[]
        for _ in range(4): results.append(w.tick())
        self.assertEqual(len(self.sent),1)
        self.assertEqual(results[-1]['status'],'resumed')
        self.assertEqual(w.counts['respondidas'],1)
    def test_time_budget_resumes_candidate_cursor(self):
        w=self.make()
        visited=[]
        def candidate(conv,*args):
            visited.append(conv['id']);self.elapsed+=6
            return None,'ja_respondida_no_chatwoot'
        w._candidate=candidate
        self.assertEqual(w.tick()['status'],'scanning')
        self.assertEqual(visited,['1','2'])
        w.tick(); self.assertEqual(visited,['1','2','3','4'])
    def test_stable_cache_kept_between_slices(self):
        w=self.make()
        for _ in range(4):w.tick()
        self.assertEqual(len(w.seen),80)
        w.next_scan_at=None
        w._candidate=lambda *args: (_ for _ in ()).throw(AssertionError('cached candidate reread'))
        for _ in range(3):self.assertEqual(w.tick()['status'],'scanning')
        self.assertEqual(w.tick()['status'],'idle')
    def test_invalid_later_page_discards_partial_listing(self):
        w=self.make(slow_pages=True)
        self.assertEqual(w.tick()['status'],'scanning')
        w.transport.http=lambda **kw:None
        self.assertEqual(w.tick()['status'],'unavailable')
        self.assertIsNone(w._progress)
        self.assertEqual(self.sent,[])
    def test_error_discards_snapshot_without_repeating_callback(self):
        w=self.make()
        w._candidate=lambda *args: (_ for _ in ()).throw(RuntimeError('offline'))
        self.assertEqual(w.tick()['status'],'unconfirmed')
        self.assertIsNone(w._progress); self.assertEqual(w.tick()['status'],'cooldown')

if __name__=='__main__':unittest.main()
