"""Single automation process: Chatwoot, form, data, email. No dashboard."""
from config import load_settings
from gateway import Gateway
from smtp import SmtpSender
from server import create_app as create_server
from forms import register_forms


def create_app(settings=None):
    settings = load_settings() if settings is None else settings
    app = create_server(settings=settings)
    settings = app.extensions['v5_settings']
    app.extensions['v5_data_gateway'] = Gateway(settings)
    app.extensions['v5_real_executor'].retention_cleanup = app.extensions['v5_data_gateway'].cleanup_retention
    app.extensions['v5_email_sender'] = SmtpSender(settings)
    register_forms(app, settings, app.extensions['v5_repository'])
    if settings.get('form_public_url'):
        import json
        with app.app_context():
            relinked = app.extensions['v5_form_relink_existing']()
        print(json.dumps({'original_form_handoff': relinked}, sort_keys=True))
    # No thread exists in simulated mode or without the explicit opt-in flag.
    if settings.get('tiktok_mode') == 'real' and settings.get('real_worker_enabled') is True:
        import json
        executor = app.extensions['v5_real_executor']
        print(json.dumps({'real_tiktok_preflight': executor.probe_sessions()}, sort_keys=True))
        if executor.start():
            from recovery import recover_stalled
            try:
                recovery = recover_stalled(app)
            except Exception:
                recovery = {'status': 'unconfirmed'}
            print(json.dumps({'real_qualification_recovery': recovery}, sort_keys=True))
    return app
