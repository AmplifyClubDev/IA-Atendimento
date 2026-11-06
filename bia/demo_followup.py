"""One durable, test-only reminder per accepted turn; never restart a flow."""
import json
from datetime import timedelta

WAITING = frozenset({'opening', 'about', 'profile', 'member', 'conditions', 'invite',
                     'faq', 'faq_context', 'faq_agency', 'faq_benefits', 'faq_terms',
                     'faq_invite', 'faq_partnership', 'faq_more', 'faq_unknown'})
PAYLOAD = {'content': 'Ainda estou por aqui 😊 Quer continuar de onde paramos? '
           'Responda à última pergunta ou use as opções da mensagem anterior.',
           'message_type': 'outgoing', 'private': False, 'content_type': 'text'}


def arm(router, source_key):
    from demo_router import clock, digest
    with router.store.lock:
        state = router.store.current(router.scope.slot)
        if not state or state['outbox_key'] != source_key or state['step'] not in WAITING:
            return
        router.store.db.execute('INSERT OR IGNORE INTO demo_followups VALUES(?,?,?,?,?,?)',
            ('bia-demo-followup:' + digest([router.scope.slot, source_key]), router.scope.slot,
             source_key, (clock(router.now()) + timedelta(seconds=300)).isoformat(),
             'pending', json.dumps(PAYLOAD)))


def cancel_for_inbound(router, event):
    from demo_router import clock
    with router.store.lock:
        state = router.store.current(router.scope.slot)
        if not state:
            return
        try:
            fresh = (int(event['message_id']) > int(state['watermark'])
                     and clock(state['started']) <= clock(event['created_at'])
                     and -30 <= (clock(router.now())-clock(event['created_at'])).total_seconds() <= 300)
        except (ValueError, TypeError, KeyError):
            fresh = False
        if fresh:
            router.store.db.execute("UPDATE demo_followups SET status='cancelled' WHERE slot=? AND status='pending'",
                                    (router.scope.slot,))


def tick(router):
    from demo_router import clock, DemoScope, DemoWhatsAppGateway
    if not router.followup_enabled or not router.continuation_enabled or not isinstance(router.scope, DemoScope):
        return {'status': 'disabled'}
    with router.store.lock:
        state = router.store.current(router.scope.slot)
        if not state or state['step'] not in WAITING:
            return {'status': 'idle'}
        row = router.store.db.execute('SELECT * FROM demo_followups WHERE slot=? AND source_key=? AND status=?',
                (router.scope.slot, state['outbox_key'], 'pending')).fetchone()
        if not row or clock(router.now()) < clock(row['due']):
            return {'status': 'idle'}
        if clock(router.now()) - clock(row['due']) >= timedelta(minutes=55):
            router.store.db.execute("UPDATE demo_followups SET status='expired' WHERE key=?", (row['key'],))
            return {'status': 'expired'}
        source = router.store.db.execute('SELECT status FROM demo_outbox WHERE key=? AND slot=?',
                                        (state['outbox_key'], router.scope.slot)).fetchone()
        if not source or source['status'] != 'accepted' or not state['parent_id']:
            return {'status': 'blocked'}
        try:
            # Provider read catches replies/human messages not processed by the webhook.
            current = router.gateway.preflight(router.scope)
            expected = str(max(int(state['watermark']), int(state['parent_id'])))
            if current.get('after_message_id') != expected:
                router.store.db.execute("UPDATE demo_followups SET status='cancelled' WHERE key=?", (row['key'],))
                return {'status': 'source_changed'}
            if isinstance(router.gateway, DemoWhatsAppGateway):
                detail = router.gateway._api(router.scope, 'GET')
                if (detail.get('status') != 'open' or (detail.get('meta') or {}).get('assignee')
                        or (detail.get('custom_attributes') or {}).get('human_control')):
                    router.store.db.execute("UPDATE demo_followups SET status='cancelled' WHERE key=?", (row['key'],))
                    return {'status': 'human_or_closed'}
            # Claim durably before network IO. A lost response is never retried.
            cursor = router.store.db.execute("UPDATE demo_followups SET status='outcome_unknown' WHERE key=? AND status='pending'",
                                             (row['key'],))
            if cursor.rowcount != 1:
                return {'status': 'already_reserved'}
            receipt = router.gateway.send(router.scope, json.loads(row['payload']), row['key'])
            status = 'accepted' if isinstance(receipt, dict) and receipt.get('status') == 'accepted' else 'outcome_unknown'
            router.store.db.execute('UPDATE demo_followups SET status=? WHERE key=?', (status, row['key']))
            return {'status': status}
        except Exception:
            return {'status': 'unconfirmed'}


def tick_all(router):
    from demo_router import DemoMultiplexer, DemoPendingRouter
    results = []
    for item in router.routers if isinstance(router, DemoMultiplexer) else (router,):
        if isinstance(item, DemoPendingRouter):
            item = item.router if not item.binding_failed else None
        if item is not None:
            results.append(tick(item))
    return results
