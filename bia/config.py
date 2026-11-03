"""Explicit configuration for the single-contact rehearsal; no dotenv loading."""
import os
import re
from datetime import datetime
from urllib.parse import urlsplit

PROJECT_REF = 'divlvdmsqbwplervsqwu'


def invite_method_issue(settings):
    """The optional UI sender is scoped to the existing isolated pilot."""
    method = settings.get('tiktok_invite_method', 'api')
    if not isinstance(method, str) or method not in {'api', 'ui'}:
        return 'tiktok_invite_method_invalid'
    if method == 'ui':
        gate = settings.get('gate') or {}
        if (not isinstance(gate, dict) or gate.get('enabled') is not True
                or gate.get('provider') != 'chatwoot' or gate.get('account_id') != '1'
                or gate.get('inbox_id') != '3' or gate.get('phone') != '+5547991154859'
                or settings.get('test_phone') != '+5547991154859'
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
        'test_phone': phone, 'state_dir': get('V5_STATE_DIR', '/data'),
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
    for role, default_url in (
            ('precheck', 'https://tiktok-pre-validacao-production.up.railway.app/bridge'),
            ('agency', 'https://tiktok-agenciamento-production.up.railway.app/bridge'),
            ('invites', 'https://tiktok-partner-bridge-production.up.railway.app/bridge'),
            ('lookup', ''), ('gmv', '')):
        settings['tiktok_' + role + '_url'] = get('V5_TIKTOK_' + role.upper() + '_URL', default_url)
        settings['tiktok_' + role + '_token'] = get('V5_TIKTOK_' + role.upper() + '_TOKEN')
    settings['simulated_checks'] = settings['tiktok_mode'] != 'real'
    issues = []
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
            or phone != '+5547991154859' or settings['gate']['account_id'] != '1'
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
                or phone != '+5547991154859' or settings['gate']['account_id'] != '1'
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
    settings['readiness_issues'] = issues
    return settings
