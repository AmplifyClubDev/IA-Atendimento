"""One durable, test-only reminder per accepted turn; never restart a flow."""
import json
import logging
from datetime import timedelta

WAITING = frozenset({'opening', 'about', 'profile', 'member', 'conditions', 'invite',
                     'faq', 'faq_context', 'faq_agency', 'faq_benefits', 'faq_terms',
                     'faq_invite', 'faq_partnership', 'faq_more', 'faq_unknown'})
PAYLOAD = {'content': 'Ainda estou por aqui 😊\n\n'
           'Quer continuar de onde paramos?\n\n'
           'Se não houver resposta em mais 10 minutos, encerro este atendimento por agora.',
           'message_type': 'outgoing', 'private': False, 'content_type': 'text'}


def effective_due(row):
    """Legacy persisted +5 minute deadline becomes +10 without new keys/replays."""
    from demo_router import clock
    return clock(row['due']) + timedelta(seconds=300)


def arm(router, source_key):
    from demo_router import clock, digest
    with router.store.lock:
        state = router.store.current(router.scope.slot)
        if not state or state['outbox_key'] != source_key or state['step'] not in WAITING:
            return
        router.store.db.execute('INSERT OR IGNORE INTO demo_followups VALUES(?,?,?,?,?,?)',
            ('bia-demo-followup:v2:' + digest([router.scope.slot, source_key]), router.scope.slot,
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
            router.store.db.execute("UPDATE demo_closures SET status='cancelled' WHERE slot=? AND status='pending'",
                                    (router.scope.slot,))
            router.store.db.execute("UPDATE demo_followups SET status='cancelled' WHERE slot=? AND status='pending'",
                                    (router.scope.slot,))


def tick(router):
    bridge = getattr(router.store, 'real_bridge', None)
    if bridge is not None and bridge.enrolled(router.scope):
        return {'status': 'real_handoff_active'}
    from demo_router import clock, DemoScope, DemoWhatsAppGateway
    if not router.followup_enabled or not router.continuation_enabled or not isinstance(router.scope, DemoScope):
        return {'status': 'disabled'}
    with router.store.lock:
        closure = tick_closure(router)
        if closure is not None:
            return closure
        state = router.store.current(router.scope.slot)
        if not state or state['step'] not in WAITING:
            return {'status': 'idle'}
        row = router.store.db.execute('SELECT * FROM demo_followups WHERE slot=? AND source_key=? AND status=?',
                (router.scope.slot, state['outbox_key'], 'pending')).fetchone()
        if not row or clock(router.now()) < effective_due(row):
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
            cursor = router.store.db.execute("UPDATE demo_followups SET status='outcome_unknown',payload=? WHERE key=? AND status='pending'",
                                             (json.dumps(PAYLOAD), row['key']))
            if cursor.rowcount != 1:
                return {'status': 'already_reserved'}
            receipt = router.gateway.send(router.scope, dict(PAYLOAD), row['key'])
            status = 'accepted' if isinstance(receipt, dict) and receipt.get('status') == 'accepted' else 'outcome_unknown'
            with router.store.transaction():
                router.store.db.execute('UPDATE demo_followups SET status=? WHERE key=?', (status, row['key']))
                if status == 'accepted' and row['key'].startswith('bia-demo-followup:v2:'):
                    arm_closure(router, row, receipt)
            audit(router, 'warning', status)
            return {'status': status}
        except Exception:
            return {'status': 'unconfirmed'}


def tick_all(router):
    from demo_router import DemoMultiplexer, DemoPendingRouter, DemoConversationRouter
    results = []
    for item in router.routers if isinstance(router, DemoMultiplexer) else (router,):
        if isinstance(item, DemoPendingRouter):
            item = item.router if not item.binding_failed else None
        if isinstance(item, DemoConversationRouter):
            if not item.binding_failed:
                with item.guard():
                    results.extend({'status': 'blocked'} if item.effects_blocked(child.scope) else tick(child)
                                   for child in tuple(item.routers.values()))
            continue
        if item is not None:
            results.append(tick(item))
    return results

CLOSE_PAYLOAD = {'content': 'Como não tivemos resposta, encerrei este atendimento por agora.\n\n'
                 'Obrigada pela conversa! 💙',
                 'message_type': 'outgoing', 'private': False, 'content_type': 'text'}

# Receipt-only allowlist, never used to send new messages. This exact copy was
# deployed through e3ed98104e83ed40b149806ec7eb09476ae01b82, before paragraph formatting.
PRE_FORMAT_CLOSE_PAYLOAD = {'content': 'Como não tivemos resposta, encerrei este atendimento por agora. '
                            'Obrigada pela conversa! 💙',
                            'message_type': 'outgoing', 'private': False, 'content_type': 'text'}

# Receipt-only allowlist, never used to send new messages. This exact copy was
# deployed before 3bd9f6dfaee71f8e07022347e24f9fbe922cb431 (2026-11-07).
LEGACY_CLOSE_PAYLOAD = {'content': 'Como não tivemos resposta, encerrei este atendimento por agora. '
                        'Seu histórico foi preservado. Para iniciar um novo teste, escreva Resetar. 💙',
                        'message_type': 'outgoing', 'private': False, 'content_type': 'text'}


def approved_closure_receipt(payload):
    return (isinstance(payload, dict) and payload.get('private') is False
            and payload in (CLOSE_PAYLOAD, PRE_FORMAT_CLOSE_PAYLOAD, LEGACY_CLOSE_PAYLOAD))


def audit(router, stage, status):
    # Operational receipt only: never message text, phone, token or profile.
    logging.getLogger(__name__).warning('demo_inactivity %s', json.dumps({
        'scope_digest': router.scope.slot, 'stage': stage, 'status': status}, sort_keys=True))


def arm_closure(router, warning, receipt):
    from demo_router import clock, identifier
    message_id = identifier(receipt.get('message_id'))
    if not message_id:
        return
    router.store.db.execute('INSERT OR IGNORE INTO demo_closures VALUES(?,?,?,?,?,?,?,NULL)',
        ('bia-demo-close:' + warning['key'].split(':')[-1], router.scope.slot, warning['source_key'],
         (clock(router.now()) + timedelta(seconds=300)).isoformat(), 'pending',
         json.dumps(CLOSE_PAYLOAD), message_id))


def persisted_payload(store, scope, key):
    table = 'demo_closures' if key.startswith('bia-demo-close:') else 'demo_followups'
    status = 'notice_unknown' if table == 'demo_closures' else 'outcome_unknown'
    with store.lock:
        row = store.db.execute('SELECT payload FROM ' + table + ' WHERE key=? AND slot=? AND status=?',
                               (key, scope.slot, status)).fetchone()
    if row is None:
        raise ValueError('demo_followup_not_reserved')
    return json.loads(row['payload'])


def source_current(store, scope, key, preflight):
    with store.lock:
        state = store.current(scope.slot)
        if not state:
            return False
        if key.startswith('bia-demo-close:'):
            row = store.db.execute('SELECT * FROM demo_closures WHERE key=? AND slot=?', (key, scope.slot)).fetchone()
            if not row or row['source_key'] != state['outbox_key']:
                return False
            if row['status'] == 'notice_unknown' and state['step'] in WAITING:
                expected = row['warning_message_id']
            elif (row['status'] == 'resolve_unknown' and state['step'] == 'closed'
                  and state['choice'] == 'inactivity_timeout'):
                expected = row['closure_message_id']
            else:
                return False
            return bool(expected and preflight.get('after_message_id') == expected)
        row = store.db.execute('SELECT source_key FROM demo_followups WHERE key=? AND slot=? AND status=?',
                               (key, scope.slot, 'outcome_unknown')).fetchone()
        return bool(row and row['source_key'] == state['outbox_key'] and state['step'] in WAITING
                    and preflight.get('after_message_id') == str(max(int(state['watermark']), int(state['parent_id']))))


def reconcile_resolutions(router):
    """Confirm historical closes by GET only, preserving all send uncertainties."""
    from demo_router import identifier, DemoWhatsAppGateway
    if not isinstance(router.gateway, DemoWhatsAppGateway):
        return 0  # Offline adapters cannot establish provider truth.
    confirmed = 0
    with router.store.lock:
        # Bound provider work per inbound. Malformed or older receipts stay held.
        rows = router.store.db.execute(
            "SELECT * FROM demo_closures WHERE slot=? AND status='resolve_unknown' ORDER BY rowid DESC LIMIT 1",
            (router.scope.slot,)).fetchall()
        for row in rows:
            try:
                if (not row['key'].startswith('bia-demo-close:')
                        or not identifier(row['closure_message_id']) or not identifier(row['warning_message_id'])
                        or not approved_closure_receipt(json.loads(row['payload']))):
                    continue
                source = router.store.db.execute(
                    "SELECT 1 FROM demo_outbox WHERE key=? AND slot=? AND status='accepted'",
                    (row['source_key'], router.scope.slot)).fetchone()
                if not source or router.gateway.verify_resolution(
                        router.scope, row['closure_message_id'], json.loads(row['payload'])) is not True:
                    continue
                updated = router.store.db.execute(
                    "UPDATE demo_closures SET status='resolved' WHERE key=? AND slot=? AND status='resolve_unknown' "
                    'AND source_key=? AND closure_message_id=?',
                    (row['key'], router.scope.slot, row['source_key'], row['closure_message_id'])).rowcount
                if updated == 1:
                    confirmed += 1
                    audit(router, 'resolution_readback', 'resolved')
            except Exception:
                # No provider writes, retries, state deletion or blanket clearing.
                # Keep the original uncertainty if any proof or persistence fails.
                audit(router, 'resolution_readback', 'unconfirmed')
    return confirmed


def tick_closure(router):
    """Only new v2 warnings create this queue. No backfill or unknown-send retry."""
    from demo_router import clock, identifier, DemoWhatsAppGateway
    state = router.store.current(router.scope.slot)
    if not state or state['step'] not in WAITING:
        return None
    row = router.store.db.execute('SELECT * FROM demo_closures WHERE slot=? AND source_key=? AND status=?',
                                  (router.scope.slot, state['outbox_key'], 'pending')).fetchone()
    if not row or clock(router.now()) < effective_due(row):
        return None
    if clock(router.now()) - clock(row['due']) >= timedelta(minutes=55):
        router.store.db.execute("UPDATE demo_closures SET status='expired' WHERE key=?", (row['key'],))
        audit(router, 'closure', 'expired')
        return {'status': 'expired', 'stage': 'closure'}
    try:
        current = router.gateway.preflight(router.scope)
        if current.get('after_message_id') != row['warning_message_id']:
            router.store.db.execute("UPDATE demo_closures SET status='cancelled' WHERE key=?", (row['key'],))
            audit(router, 'closure', 'source_changed')
            return {'status': 'source_changed', 'stage': 'closure'}
        if isinstance(router.gateway, DemoWhatsAppGateway):
            try:
                router.gateway.inactivity_human_guard(router.scope)
            except ValueError:
                router.store.db.execute("UPDATE demo_closures SET status='cancelled' WHERE key=?", (row['key'],))
                audit(router, 'closure', 'human_or_closed')
                return {'status': 'human_or_closed', 'stage': 'closure'}
        # The claim and notice receipt are separate durable boundaries. Never
        # repeat a possibly delivered notice or resolve a changed conversation.
        reserved = router.store.db.execute("UPDATE demo_closures SET status='notice_unknown',payload=? WHERE key=? AND status='pending'",
                                            (json.dumps(CLOSE_PAYLOAD), row['key'])).rowcount
        if reserved != 1:
            return {'status': 'already_reserved', 'stage': 'closure'}
        receipt = router.gateway.send(router.scope, dict(CLOSE_PAYLOAD), row['key'])
        message_id = identifier(receipt.get('message_id')) if isinstance(receipt, dict) else None
        if not message_id or receipt.get('status') != 'accepted':
            audit(router, 'closure', 'notice_unknown')
            return {'status': 'outcome_unknown', 'stage': 'closure'}
        with router.store.transaction():
            router.store.db.execute("UPDATE demo_closures SET status='resolve_unknown',closure_message_id=? WHERE key=?",
                                    (message_id, row['key']))
            router.store.db.execute("UPDATE demo_runs SET step='closed',choice='inactivity_timeout' WHERE slot=? AND outbox_key=?",
                                    (router.scope.slot, row['source_key']))
        audit(router, 'closure_notice', 'accepted')
        # Explicit resolved status, not a toggle. The gateway rechecks recipient,
        # latest message, human ownership and our durable claim before the POST.
        result = router.gateway.resolve_inactivity(router.scope, row['key'])
        if not isinstance(result, dict) or result.get('status') != 'resolved':
            audit(router, 'chatwoot_resolution', 'outcome_unknown')
            return {'status': 'resolution_unconfirmed', 'stage': 'closure'}
        router.store.db.execute("UPDATE demo_closures SET status='resolved' WHERE key=?", (row['key'],))
        audit(router, 'chatwoot_resolution', 'resolved')
        return {'status': 'closed', 'stage': 'closure'}
    except Exception:
        audit(router, 'closure', 'unconfirmed')
        return {'status': 'unconfirmed', 'stage': 'closure'}
