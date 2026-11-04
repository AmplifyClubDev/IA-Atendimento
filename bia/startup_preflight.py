"""Explicit, read-only stage gate for the source-based Docker startup.

This is not a reconstruction of the historical sealed release launcher.
No provider is imported or constructed in nonproduction or with stages off.
"""
from offline_policy import effects_allowed


class StartupPreflightFailed(RuntimeError):
    """Fixed diagnostic only: provider responses and credentials stay private."""


def verify_stage_readiness(settings):
    if not effects_allowed(settings=settings):
        return {'status': 'disabled', 'reason': 'nonproduction_external_effects_disabled'}
    if settings.get('chatwoot_stages_enabled') is not True:
        return {'status': 'disabled', 'reason': 'stages_disabled'}
    try:
        from ops.stage_preflight import run_preflight
        gate = settings.get('gate') or {}
        # Derive the check from the exact settings that bootstrap will use.
        # Never validate process env A and start an app with supplied settings B.
        environ = {
            'V5_ENABLED': 'true' if gate.get('enabled') is True else 'false',
            'CHATWOOT_BASE_URL': settings.get('chatwoot_base_url', ''),
            'CHATWOOT_API_TOKEN': settings.get('chatwoot_api_token', ''),
            'CHATWOOT_ACCOUNT_ID': gate.get('account_id', ''),
            'CHATWOOT_INBOX_ID': gate.get('inbox_id', ''),
            'V5_TEST_PHONE': settings.get('test_phone', ''),
            'V5_CHATWOOT_STAGES_ENABLED': 'true',
            'V5_INACTIVITY_CLOSE_ENABLED': (
                'true' if settings.get('inactivity_close_enabled') is True else 'false'),
        }
        result = run_preflight(
            environ,
            expected_host='chatwoot.t2ffoz.easypanel.host',
            expected_account_id='1', expected_inbox_id='3',
            expected_conversation_id='26097', expected_contact_id='3',
            require_labels=True, setup=False,
        )
        if (not isinstance(result, dict) or result.get('passed') is not True
                or result.get('mode') != 'readonly'
                or type(result.get('post_attempts')) is not int
                or result['post_attempts'] != 0):
            raise StartupPreflightFailed('stage_preflight_failed')
    except Exception:
        raise StartupPreflightFailed('stage_preflight_failed') from None
    return {'status': 'passed', 'mode': 'readonly'}
