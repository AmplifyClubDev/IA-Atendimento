"""Explicit configuration for the single-contact rehearsal; no dotenv loading."""
import os
import json
import pilot_scope
import re
from datetime import datetime
from urllib.parse import urlsplit

PROJECT_REF = 'divlvdmsqbwplervsqwu'
DEMO_CONTEXT_VERSION = 'amplify_doc_20261106_v1'
DEMO_CONTEXT_VERSIONS = frozenset({DEMO_CONTEXT_VERSION, 'amplify_circle_20261106_v2', 'amplify_circle_20261106_v3', 'amplify_costs_20261110_v4'})


def demo_context_issue(settings):
    """A candidate is opt-in and can only be read by the isolated demo."""
    version = settings.get('demo_context_version', '')
    if not isinstance(version, str) or version not in ('', *DEMO_CONTEXT_VERSIONS):
        return 'demo_context_version_invalid'
    if version and settings.get('demo_enabled') is not True:
        return 'demo_context_requires_demo'
    return None


def invite_method_issue(settings):
    """The optional UI sender is scoped to the existing isolated pilot."""
    method = settings.get('tiktok_invite_method', 'api')
    if not isinstance(method, str) or method not in {'api', 'ui'}:
        return 'tiktok_invite_method_invalid'
    if method == 'ui':
        if not pilot_scope.restricted_phone(settings):
            return 'tiktok_ui_invite_scope_invalid'
        gate = settings.get('gate') or {}
        if (not isinstance(gate, dict) or gate.get('enabled') is not True
                or gate.get('provider') != 'chatwoot' or gate.get('account_id') != '1'
                or gate.get('inbox_id') != '3' or gate.get('phone') != pilot_scope.restricted_phone(settings)
                or settings.get('test_phone') != pilot_scope.restricted_phone(settings)
                or settings.get('tiktok_mode') != 'real' or settings.get('real_worker_enabled') is not True
                or settings.get('public_url') != 'https://atendimento-v5-ensaio-production.up.railway.app'):
            return 'tiktok_ui_invite_scope_invalid'
    return None


def load_settings(environ=None):
    values = os.environ if environ is None else environ
    get = lambda key, default='': str(values.get(key, default)).strip()
    phone = get('V5_TEST_PHONE')
    settings = {
        'gate': {'enabled': get('V5_ENABLED').lower() == 'true', 'provider': 'chatwoot',
                 'account_id': get('CHATWOOT_ACCOUNT_ID'), 'inbox_id': get('CHATWOOT_INBOX_ID'), 'phone': phone},
        'pilot_scope': pilot_scope.load_scope(values), 'test_phone': phone, 'state_dir': get('V5_STATE_DIR', '/data'),
        'same_engine_enabled': get('V5_SAME_ENGINE_ENABLED').lower() == 'true',
        'context_profile_id': get('V5_CONTEXT_PROFILE_ID') or 'amplify-v1',
        'approved_experience_enabled': get('V5_APPROVED_EXPERIENCE_ENABLED').lower() == 'true',
        'qualification_enabled': get('V5_QUALIFICATION_ENABLED').lower() == 'true',
        'qualification_new_cycles_only': True,
        'demo_enabled': get('V5_DEMO_ROUTER_ENABLED').lower() == 'true',
        'demo_real_enabled': get('V5_DEMO_REAL_ENABLED').lower() == 'true',
        'demo_real_test_phone': get('V5_DEMO_REAL_TEST_PHONE'),
        'slack_bot_token': get('SLACK_BOT_TOKEN'),
        'slack_gmv_channel_id': get('SLACK_GMV_CHANNEL_ID'),
        'demo_conversation_rollover_enabled': get('V5_DEMO_CONVERSATION_ROLLOVER_ENABLED').lower() == 'true',
        # Keep this exact: whitespace or an unknown version must fail closed.
        'demo_context_version': str(values.get('V5_DEMO_CONTEXT_VERSION', '')),
        'demo_smoke_check': get('V5_DEMO_SMOKE_CHECK').lower() == 'true',
        'demo_smoke_check_id': str(values.get('V5_DEMO_SMOKE_CHECK_ID', '')),
        'demo_whatsapp_live': get('V5_DEMO_WHATSAPP_LIVE').lower() == 'true',
        'demo_followup_enabled': get('V5_DEMO_FOLLOWUP_ENABLED').lower() == 'true',
        'demo_continuation_enabled': get('V5_DEMO_CONTINUATION_ENABLED').lower() == 'true',
        'demo_state_path': get('V5_DEMO_STATE_PATH'),
        'demo_scope': {'account_id': get('CHATWOOT_ACCOUNT_ID'), 'inbox_id': get('CHATWOOT_INBOX_ID'),
                       'contact_id': get('V5_PILOT_CONTACT_ID'), 'conversation_id': get('V5_PILOT_CONVERSATION_ID'),
                       'phone': phone},
        'webhook_token': get('V5_WEBHOOK_TOKEN'), 'form_secret': get('V5_FORM_SECRET'),
        'chatwoot_base_url': get('CHATWOOT_BASE_URL'), 'chatwoot_api_token': get('CHATWOOT_API_TOKEN'),
        'ai_enabled': get('V5_AI_ENABLED').lower() == 'true',
        'context_db_enabled': get('V5_CONTEXT_DB_ENABLED').lower() == 'true',
        'conversation_enabled': get('V5_CONVERSATIONAL_ENABLED').lower() == 'true',
        'contact_sync_enabled': get('V5_CONTACT_SYNC_ENABLED').lower() == 'true',
        'chatwoot_stages_enabled': get('V5_CHATWOOT_STAGES_ENABLED').lower() == 'true',
        'instance_id': get('V5_INSTANCE_ID'),
        'openai_api_key': get('OPENAI_API_KEY'), 'ai_model': get('DECISION_ENGINE_MODEL'),
        'v5_project_ref': PROJECT_REF, 'v5_url': get('V5_SUPABASE_URL'),
        'v5_service_key': get('V5_SUPABASE_SERVICE_KEY'), 'public_url': get('V5_PUBLIC_URL').rstrip('/'),
        'form_public_url': get('V5_FORM_PUBLIC_URL').rstrip('/'),
        'smtp_host': get('SMTP_HOST', 'smtp.gmail.com'), 'smtp_port': get('SMTP_PORT', '465'),
        'smtp_user': get('SMTP_USUARIO'), 'smtp_password': get('SMTP_SENHA_APP'),
        'smtp_from_name': 'Bia · Amplify',
        'tiktok_mode': get('V5_TIKTOK_MODE', 'simulated').lower(),
        'real_worker_enabled': get('V5_REAL_WORKER_ENABLED').lower() == 'true',
        'retention_enabled': get('V5_RETENTION_ENABLED').lower() == 'true',
        'followup_enabled': get('V5_FOLLOWUP_ENABLED').lower() == 'true',
        'followup_delay_seconds': get('V5_FOLLOWUP_DELAY_SECONDS', '300'),
        'followup_start_at': get('V5_FOLLOWUP_START_AT'),
        'inactivity_close_enabled': get('V5_INACTIVITY_CLOSE_ENABLED').lower() == 'true',
        # Auditoria 20/11: conversa com "encerrado" vira "resolvida" no Chatwoot (só caixa 3). Desligado por padrão.
        'resolve_on_close_enabled': get('V5_RESOLVE_ON_CLOSE_ENABLED').lower() == 'true',
        'inactivity_close_delay_seconds': get('V5_INACTIVITY_CLOSE_DELAY_SECONDS', '300'),
        'relationship_check_in_form': get('V5_RELATIONSHIP_CHECK_IN_FORM').lower() == 'true',
        # Release 39: on unless explicitly switched off; no new variable is needed to publish.
        'retomada_enabled': get('V5_RETOMADA_ENABLED', 'true').lower() != 'false',
        'pos_pausa_enabled': get('V5_POS_PAUSA_ENABLED', 'true').lower() != 'false',
        'reconferencia_enabled': get('V5_RECONFERENCIA_ENABLED', 'true').lower() != 'false',
        'tiktok_invite_method': get('V5_TIKTOK_INVITE_METHOD', 'api').lower(),
        'tiktok_invite_commission': get('V5_TIKTOK_INVITE_COMMISSION'),
        'tiktok_commission_unit': get('V5_TIKTOK_COMMISSION_UNIT'),
        'tiktok_duration_fixed_months': get('V5_TIKTOK_DURATION_FIXED_MONTHS'),
        'tiktok_duration_label': get('V5_TIKTOK_DURATION_LABEL'),
        'tiktok_policy_approved': get('V5_TIKTOK_POLICY_APPROVED').lower() == 'true',
        'tiktok_policy_version': get('V5_TIKTOK_POLICY_VERSION'),
        'whatsapp_cloud_token': get('V5_WHATSAPP_CLOUD_TOKEN'),
        'whatsapp_cloud_phone_number_id': get('V5_WHATSAPP_PHONE_NUMBER_ID'),
    }
    # Optional complete identities. An explicitly malformed list must not
    # silently fall back to the legacy contact or broaden the production gate.
    if 'V5_DEMO_SCOPES_JSON' in values:
        raw_scopes = values['V5_DEMO_SCOPES_JSON']
        if not isinstance(raw_scopes, str) or not 1 <= len(raw_scopes) <= 8192:
            raise ValueError('demo_scopes_json_invalid')
        try:
            settings['demo_scopes'] = json.loads(raw_scopes)
        except (ValueError, TypeError):
            raise ValueError('demo_scopes_json_invalid') from None
        from demo_router import configured_scopes
        configured_scopes(settings)
    if 'V5_DEMO_PENDING_SCOPE_JSON' in values:
        raw_pending = values['V5_DEMO_PENDING_SCOPE_JSON']
        if not isinstance(raw_pending, str) or not 1 <= len(raw_pending) <= 2048:
            raise ValueError('demo_pending_scope_json_invalid')
        try:
            settings['demo_pending_scope'] = json.loads(raw_pending)
        except (ValueError, TypeError):
            raise ValueError('demo_pending_scope_json_invalid') from None
        from demo_router import configured_scopes, configured_pending_scope
        configured_pending_scope(settings, configured_scopes(settings))
    for role, default_url in (
            ('precheck', 'https://tiktok-pre-validacao-production.up.railway.app/bridge'),
            ('agency', 'https://tiktok-agenciamento-production.up.railway.app/bridge'),
            ('invites', 'https://tiktok-partner-bridge-production.up.railway.app/bridge'),
            ('lookup', ''), ('gmv', '')):
        settings['tiktok_' + role + '_url'] = get('V5_TIKTOK_' + role.upper() + '_URL', default_url)
        settings['tiktok_' + role + '_token'] = get('V5_TIKTOK_' + role.upper() + '_TOKEN')
    settings['simulated_checks'] = settings['tiktok_mode'] != 'real'
    issues = []
    context_issue = demo_context_issue(settings)
    if context_issue:
        issues.append(context_issue)
    from contracts import parse_pilot_phones
    phones, phones_issue = parse_pilot_phones(get('V5_PILOT_PHONES'), phone)
    if phones_issue:
        issues.append(phones_issue)
    elif phones:
        settings['gate']['phones'] = phones
    # Release 47: V5_GATE_MODE=lista (padrão, igual à 46) ou todos (toda a caixa, com as exclusões lidas no Chatwoot).
    gate_mode = get('V5_GATE_MODE', 'lista').lower() or 'lista'
    if gate_mode not in {'lista', 'todos'}:
        issues.append('gate_mode_invalid')
    settings['gate']['mode'] = 'todos' if gate_mode == 'todos' else 'lista'
    method_issue = invite_method_issue(settings)
    if method_issue:
        issues.append(method_issue)
    if settings['relationship_check_in_form'] and (
            settings['tiktok_mode'] != 'real'
            or settings['form_public_url'] != 'https://amplify-cadastro.up.railway.app/cadastro/ensaio'
            or not pilot_scope.restricted_phone(settings) or phone != pilot_scope.restricted_phone(settings) or settings['gate']['account_id'] != '1'
            or settings['gate']['inbox_id'] != '3'):
        issues.append('form_relationship_configuration_invalid')
    if settings['inactivity_close_enabled'] and (
            not settings['followup_enabled'] or settings['inactivity_close_delay_seconds'] != '300'):
        issues.append('inactivity_close_configuration_invalid')
    if settings['followup_enabled']:
        try:
            baseline = datetime.fromisoformat(settings['followup_start_at'].replace('Z', '+00:00'))
            valid_baseline = baseline.tzinfo is not None and baseline.utcoffset().total_seconds() == 0
        except (ValueError, TypeError, AttributeError):
            valid_baseline = False
        if (settings['followup_delay_seconds'] != '300' or not valid_baseline
                or not pilot_scope.restricted_phone(settings) or phone != pilot_scope.restricted_phone(settings) or settings['gate']['account_id'] != '1'
                or settings['gate']['inbox_id'] != '3' or settings['tiktok_mode'] != 'real'):
            issues.append('followup_configuration_invalid')
    if settings['form_public_url'] and settings['form_public_url'] != 'https://amplify-cadastro.up.railway.app/cadastro/ensaio':
        issues.append('form_public_url_invalid')
    if settings['tiktok_mode'] not in {'simulated', 'real'}:
        issues.append('tiktok_mode_invalid')
    if settings['tiktok_mode'] == 'real':
        if not settings['real_worker_enabled']:
            issues.append('real_worker_disabled')
        if not settings['conversation_enabled']:
            issues.append('real_mode_requires_conversation')
        if not settings['contact_sync_enabled']:
            issues.append('real_mode_requires_data_sync')
        for role in ('precheck', 'agency', 'invites'):
            if not settings['tiktok_' + role + '_token']:
                issues.append('tiktok_' + role + '_token_missing')
        if (not re.fullmatch(r'(?:0|[1-9][0-9]{0,3})(?:\.[0-9]{1,4})?', settings['tiktok_invite_commission'])
                or not 0 <= float(settings['tiktok_invite_commission']) <= 10):
            issues.append('tiktok_commission_explicit_required')
        if (not settings['tiktok_policy_approved']
                or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,80}', settings['tiktok_policy_version'])):
            issues.append('tiktok_policy_approval_required')
        if (settings['tiktok_commission_unit'] != 'percent'
                or settings['tiktok_duration_fixed_months'] != '2'
                or settings['tiktok_duration_label'] != '2 meses'):
            issues.append('tiktok_policy_units_unconfirmed')
    for name in ('webhook_token', 'form_secret', 'chatwoot_api_token', 'v5_service_key', 'smtp_user', 'smtp_password'):
        if not settings[name]:
            issues.append(name + '_missing')
    for name in ('webhook_token', 'form_secret'):
        if settings[name] and len(settings[name]) < 32:
            issues.append(name + '_too_short')
    try:
        target = urlsplit(settings['v5_url'])
        valid_target = (target.scheme == 'https' and target.hostname == PROJECT_REF + '.supabase.co'
                        and not any((target.username, target.password, target.port, target.query, target.fragment))
                        and target.path in ('', '/'))
    except ValueError:
        valid_target = False
    if not valid_target:
        issues.append('v5_target_mismatch')
    for name in ('chatwoot_base_url', 'public_url'):
        try:
            url = urlsplit(settings[name])
            valid_url = (url.scheme == 'https' and bool(url.hostname)
                         and not any((url.username, url.password, url.query, url.fragment)))
            url.port  # Reject malformed ports while preserving the closed startup state.
        except ValueError:
            valid_url = False
        if not valid_url:
            issues.append(name + '_invalid')
    if not settings['gate']['account_id'].isdigit() or not settings['gate']['inbox_id'].isdigit():
        issues.append('chatwoot_scope_missing')
    if not (phone.startswith('+55') and len(phone) == 14 and phone[1:].isdigit()):
        issues.append('single_test_phone_missing')
    if settings['ai_enabled'] and (not settings['openai_api_key'] or not settings['ai_model']):
        issues.append('ai_configuration_missing')
    if settings['conversation_enabled'] and not settings['ai_enabled']:
        issues.append('conversation_requires_ai')
    if settings['contact_sync_enabled']:
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,79}', settings['instance_id']):
            issues.append('contact_instance_invalid')
    if settings['gate']['enabled'] and (not pilot_scope.scope_ready(settings['pilot_scope'])
            or phone != pilot_scope.restricted_phone(settings)):
        issues.append('restricted_pilot_scope_missing')
    settings['readiness_issues'] = issues
    return settings
