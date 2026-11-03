"""Read-only checks inside the private deployment; never calls a provider."""
import hashlib
import json
import os
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from config import load_settings
from contracts import allow_inbound


def local_request(path, payload=None):
    request = Request('http://127.0.0.1:' + os.environ.get('PORT', '8000') + path,
                      data=payload, method='POST' if payload is not None else 'GET',
                      headers={'Content-Type': 'application/json'})
    try:
        with urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read(16_384))
    except HTTPError as error:
        status, raw = error.code, error.read(16_384)
        error.close()
        try:
            value = json.loads(raw)
        except ValueError:
            value = {}
        return status, value


def verify():
    settings = load_settings()
    health, _ = local_request('/healthz')
    ready, details = local_request('/ready')
    webhook, _ = local_request('/webhook/chatwoot', b'{}')
    form, _ = local_request('/cadastro/' + 'x' * 43)
    gate = {**settings['gate'], 'enabled': True}
    sample = {'provider': 'chatwoot', 'account_id': gate['account_id'],
              'inbox_id': gate['inbox_id'], 'conversation_id': '1', 'message_id': '1',
              'sender_phone': gate['phone'], 'message_type': 'incoming',
              'private': False, 'text': 'private verification'}
    scope = {
        'configured_contact_matches_gate': allow_inbound(gate, sample),
        'different_contact_rejected': not allow_inbound(gate, {**sample, 'sender_phone': '+5511999999999'}),
        'different_inbox_rejected': not allow_inbound(gate, {**sample, 'inbox_id': '999999'}),
        'outgoing_rejected': not allow_inbound(gate, {**sample, 'message_type': 'outgoing'}),
        'private_message_rejected': not allow_inbound(gate, {**sample, 'private': True}),
    }
    result = {
        'health_http': health, 'ready_http': ready,
        'unauthenticated_webhook_http': webhook, 'invalid_form_http': form,
        'pilot_disabled': settings['gate']['enabled'] is False,
        'ai_disabled': settings['ai_enabled'] is False,
        'provider_credentials_absent': not any(settings[key] for key in (
            'chatwoot_api_token', 'smtp_password', 'openai_api_key')),
        'readiness_issues': details.get('issues', []),
        'data_directory_exists': Path(settings['state_dir']).is_dir(),
        'data_directory_is_mount': os.path.ismount(settings['state_dir']),
        'scope': scope,
        'source_sha256': {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                          for p in sorted(Path('/app').glob('*.py'))},
        'external_provider_calls': 0,
    }
    result['passed'] = (health == 200 and ready == 503 and webhook == 401
                        and form in (404, 503) and result['pilot_disabled']
                        and result['ai_disabled'] and result['provider_credentials_absent']
                        and result['data_directory_is_mount'] and all(scope.values()))
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return result['passed']


if __name__ == '__main__':
    raise SystemExit(0 if verify() else 1)
