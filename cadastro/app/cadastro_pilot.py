"""Opt-in V5 pilot wrapper for the existing Cadastro Flask application.

The original factory, views, questions and non-pilot routes remain unchanged.
Only this wrapper's page adapts the reviewed HTML's API namespace and signed
resume token. Server-to-server calls use a fixed HTTPS target, not user URLs.
No Supabase credential, session cookie, redirect or POST retry is used here.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import ssl
from dataclasses import dataclass
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, HTTPSHandler, ProxyHandler, Request, build_opener
from uuid import UUID

from flask import Response, request


PUBLIC_ORIGIN = 'https://amplify-cadastro.up.railway.app'
UPSTREAM = 'https://atendimento-v5-ensaio-production.up.railway.app/cadastro/compat/'
PREFIX = '/onboarding/api/v2/ensaio/'
FORM_VERSION = 'amplify-cadastro-v2'
CONTRACT_SHA256 = '86218313e269183a9b190d0e11090f1b274792c491bd772b794e9b9cfe389fcf'
ORIGINAL_CSP = ("default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
                "img-src data: blob:; connect-src 'self'; base-uri 'none'; "
                "form-action 'none'; frame-ancestors 'none'")
TOKEN = re.compile(r'[A-Za-z0-9_-]{43}\Z')
MAX_JSON = 65_536
MAX_IMAGE = 5 * 1024 * 1024
ROUTES = {
    'contexto': frozenset({'GET'}),
    'respostas': frozenset({'PUT', 'POST'}),
    'agenciamento': frozenset({'POST', 'GET'}),
    'validacao-inicial': frozenset({'POST'}),
    'email/estado': frozenset({'POST'}),
    'email/solicitar': frozenset({'POST'}),
    'email/confirmar': frozenset({'POST'}),
    'anexos': frozenset({'POST'}),
    'imagem': frozenset({'POST'}),
}


@dataclass(frozen=True)
class UpstreamResponse:
    status: int
    body: bytes
    content_type: str = 'application/json'


class PilotError(Exception):
    def __init__(self, code, status=502):
        self.code, self.status = code, status


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _http(*, method, url, headers, body, timeout):
    """One bounded call. Never follow redirects or environment proxy settings."""
    if not url.startswith(UPSTREAM):
        raise PilotError('pilot_target_invalid')
    opener = build_opener(ProxyHandler({}), HTTPSHandler(context=ssl.create_default_context()), NoRedirect())
    req = Request(url, method=method, headers=headers, data=body)
    try:
        response = opener.open(req, timeout=timeout)
    except HTTPError as error:
        response = error
    except Exception:
        raise PilotError('pilot_upstream_unavailable') from None
    try:
        raw = response.read(MAX_IMAGE + 1)
        if len(raw) > MAX_IMAGE:
            raise PilotError('pilot_upstream_too_large')
        return UpstreamResponse(response.code, raw, response.headers.get('Content-Type', ''))
    finally:
        response.close()


def _json(raw):
    try:
        value = json.loads(raw, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
        if not isinstance(value, dict):
            raise ValueError()
        return value
    except (ValueError, TypeError, UnicodeError):
        raise PilotError('pilot_upstream_invalid') from None


def _call(transport, path, method, token, *, body=None, content_type='application/json', query=''):
    headers = {'Authorization': 'Bearer ' + token, 'Accept': 'application/json'}
    if body is not None:
        headers['Content-Type'] = content_type
    try:
        result = transport(method=method, url=UPSTREAM + path + query, headers=headers,
                           body=body, timeout=20 if path == 'agenciamento' else 5 if method == 'GET' else 20)
    except PilotError:
        raise
    except Exception:
        raise PilotError('pilot_upstream_unavailable') from None
    if (not isinstance(result, UpstreamResponse) or type(result.status) is not int
            or not 100 <= result.status <= 599 or not isinstance(result.body, bytes)
            or len(result.body) > MAX_IMAGE):
        raise PilotError('pilot_upstream_invalid')
    if 300 <= result.status < 400:
        raise PilotError('pilot_redirect_rejected')
    return result


def _proof(result, token):
    """The V5 context authenticates the original server-owned pilot instance."""
    data = _json(result.body)
    if result.status != 200:
        raise PilotError('pilot_context_unavailable', result.status if result.status in {401, 403, 404, 409, 410, 429} else 503)
    try:
        resume = data.get('resume_key')
        valid_resume = isinstance(resume, str) and str(UUID(resume)) == resume and bool(UUID(resume).int)
    except (ValueError, TypeError, AttributeError):
        valid_resume = False
    candidate = data.get('token')
    if (not isinstance(candidate, str) or not TOKEN.fullmatch(candidate)
            or not hmac.compare_digest(candidate, token) or data.get('version') != FORM_VERSION
            or data.get('cycle_bound') is not True or not valid_resume
            or type(data.get('revision')) is not int or data['revision'] < 0
            or type(data.get('step')) is not int or not 0 <= data['step'] < 6
            or type(data.get('submitted')) is not bool
            or not isinstance(data.get('answers'), dict) or not isinstance(data.get('prefill'), dict)):
        raise PilotError('pilot_context_unverified', 403)
    return data


def adapt_html(html):
    """Change only reviewed connection/resume anchors in this pilot response."""
    match = re.search(r'const\s*\{sections,fields,revision,consent\}\s*=\s*', html)
    try:
        contract, _ = json.JSONDecoder().raw_decode(html[match.end():]) if match else (None, 0)
        canonical = json.dumps(contract, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()
        if hashlib.sha256(canonical).hexdigest() != CONTRACT_SHA256:
            raise ValueError()
    except (ValueError, TypeError):
        raise PilotError('pilot_original_contract_changed', 503) from None
    replacements = (
        ("const publicMode=location.pathname.replace(/\\/$/,'')==='/cadastro';", 'const publicMode=true;'),
        ("const signedResumeProvided=publicMode&&entryParams.has('s');", 'const signedResumeProvided=true;'),
        ("const apiPrefix=publicMode?'publico/':inviteCode?'convite/':'';", "const apiPrefix='ensaio/';"),
        ("const publicStorageKey='amplify-cadastro-session';", "const publicStorageKey='amplify-v5-pilot-session';"),
        ("const validSessionToken=value=>typeof value==='string'&&value.length>0&&value.length<=4096&&/^[A-Za-z0-9_-]+=*$/.test(value);",
         "const validSessionToken=value=>typeof value==='string'&&/^[A-Za-z0-9_-]{43}$/.test(value);"),
        ("indexedDB.open('amplify-cadastro-drafts',1)", "indexedDB.open('amplify-v5-pilot-drafts',1)"),
        ('Não encontramos esse @ com agenciamento ativo na Amplify. Confira se digitou o perfil correto ou retome o atendimento para validar o vínculo.',
         'Ainda não confirmamos o vínculo desse @ com a Amplify. Confira o perfil. Se recebeu o convite, aceite-o no TikTok e toque em Verificar novamente.'),
        ('Encontramos esse @ na base, mas o vínculo com a Amplify ainda não está ativo. Retome o atendimento para confirmar o agenciamento.',
         'O vínculo com a Amplify ainda está pendente. Se recebeu o convite, aceite-o no TikTok e toque em Verificar novamente.'),
        ('Não conseguimos confirmar um agenciamento ativo e sem conflito para esse @. Confira o perfil informado ou fale com o atendimento.',
         'Não foi possível concluir a consulta agora. Aguarde um pouco e toque em Verificar novamente.'),
    )
    for before, after in replacements:
        if html.count(before) != 1:
            raise PilotError('pilot_original_html_changed', 503)
        html = html.replace(before, after, 1)
    # A consulta do ensaio pode responder "em andamento": o painel fica em "Validando" e consulta de novo.
    before = """ try{result=await request;}catch(error){agencyStage('validate','fail','Não foi possível concluir a conferência');throw error;}"""
    after = """ try{
  result=await request;
  const deadline=Date.now()+60000;
  while(result.status==='conferencia'&&result.reason==='verificacao_em_andamento'){
   if(Date.now()>=deadline)throw Error('A consulta ainda está em andamento. Aguarde um pouco e toque em Verificar para conferir novamente.');
   agencyStage('validate','active','Conferindo seu vínculo com a Amplify. Aguarde nesta tela…');
   await pause(3000);
   if(normalizeHandle(answers.tiktok)!==handle)throw Error('O perfil mudou. Confira o @ antes de verificar novamente.');
   result=await apiRequest('agenciamento');
  }
  if(result.status==='aprovada'&&normalizeHandle(answers.tiktok)!==handle)throw Error('O perfil mudou. Confira o @ antes de continuar.');
 }catch(error){agencyStage('validate','fail','Não foi possível concluir a conferência');throw error;}"""
    newline = '\r\n' if html.count(before.replace('\n', '\r\n')) == 1 else '\n'
    before, after = before.replace('\n', newline), after.replace('\n', newline)
    if html.count(before) != 1:
        raise PilotError('pilot_original_html_changed', 503)
    html = html.replace(before, after, 1)
    return '<!-- amplify-v5-pilot; original form contract preserved -->\n' + html


def _error(code, status):
    messages = {
        'pilot_disabled': 'Este cadastro de teste não está disponível.',
        'pilot_unauthorized': 'Abra o link individual recebido no atendimento.',
        'pilot_context_unavailable': 'Não foi possível validar este atendimento. Confira seu link ou volte ao WhatsApp.',
        'pilot_context_unverified': 'Não foi possível confirmar este cadastro de teste.',
        'pilot_completed': 'Este cadastro já foi enviado. Reabra seu link para conferir o resultado.',
    }
    return _response(json.dumps({'erro': messages.get(code, 'Não foi possível concluir esta solicitação agora.'),
                                 'code': code}, ensure_ascii=False).encode(), status, 'application/json')


def _response(body, status, content_type):
    response = Response(body, status=status, content_type=content_type)
    response.headers.update({'Cache-Control': 'no-store', 'Referrer-Policy': 'no-referrer',
                             'X-Content-Type-Options': 'nosniff', 'X-Frame-Options': 'DENY',
                             'Content-Security-Policy': ORIGINAL_CSP})
    return response


def _request_body(limit):
    """Bound only this request, without Flask-version-dependent setters.

    The original app's global JSON-size limit stays unchanged. Reading its
    request.stream would apply that limit to pilot image uploads as well.
    Unknown-length input is accepted only when the WSGI server marks its end.
    """
    declared = request.environ.get('CONTENT_LENGTH')
    if declared in (None, ''):
        length = None
    elif isinstance(declared, str) and re.fullmatch(r'[0-9]{1,20}', declared):
        length = int(declared)
    else:
        raise PilotError('pilot_body_invalid', 400)
    if length is not None:
        if type(length) is not int or length < 0:
            raise PilotError('pilot_body_invalid', 400)
        if length > limit:
            raise PilotError('pilot_body_invalid', 413)
        maximum = length
    else:
        if request.environ.get('wsgi.input_terminated') is not True:
            raise PilotError('pilot_content_length_required', 411)
        maximum = limit + 1
    stream = request.environ.get('wsgi.input')
    if not callable(getattr(stream, 'read', None)):
        raise PilotError('pilot_body_invalid', 400)
    try:
        raw = stream.read(maximum)
    except Exception:
        raise PilotError('pilot_body_invalid', 400) from None
    if not isinstance(raw, bytes) or not raw or (length is not None and len(raw) != length):
        raise PilotError('pilot_body_invalid', 400)
    if len(raw) > limit:
        raise PilotError('pilot_body_invalid', 413)
    return raw


def create_app(*, base_app_factory=None, transport=None, environ=None):
    """Production entrypoint: cadastro_pilot:create_app(); one explicit flag."""
    if base_app_factory is None:
        from cadastro_server import create_app as base_app_factory
    app = base_app_factory()
    adapter = app.url_map.bind('')
    original_endpoint, original_values = adapter.match('/cadastro', method='GET')
    original_view = app.view_functions[original_endpoint]
    transport = _http if transport is None else transport
    values = os.environ if environ is None else environ
    enabled = str(values.get('CADASTRO_V5_PILOT_ENABLED', '')).strip().lower() == 'true'

    def page():
        if not enabled:
            return _error('pilot_disabled', 404)
        if request.args:
            return _error('pilot_unauthorized', 400)
        try:
            response = app.make_response(original_view(**original_values))
            response.direct_passthrough = False
            if response.status_code != 200 or response.mimetype != 'text/html':
                raise PilotError('pilot_original_html_unavailable', 503)
            html = adapt_html(response.get_data(as_text=True))
            return _response(html.encode(), 200, 'text/html; charset=utf-8')
        except PilotError as error:
            return _error(error.code, error.status)
        except Exception:
            return _error('pilot_original_html_unavailable', 503)

    def proxy(path):
        if not enabled:
            return _error('pilot_disabled', 404)
        if path not in ROUTES:
            return _error('pilot_route_unavailable', 404)
        if request.method not in ROUTES[path]:
            return _error('pilot_method_unavailable', 405)
        header = request.headers.get('Authorization', '')
        match = re.fullmatch(r'(?i:Bearer) ([A-Za-z0-9_-]{43})', header)
        if not match:
            return _error('pilot_unauthorized', 401)
        if request.headers.get('Origin') not in {None, PUBLIC_ORIGIN}:
            return _error('pilot_origin_invalid', 403)
        if request.headers.get('Range'):
            return _error('pilot_range_unsupported', 400)
        token, query = match.group(1), ''
        if path == 'anexos':
            if set(request.args) != {'campo'} or len(request.args.getlist('campo')) != 1 or request.args['campo'] not in {'foto_perfil', 'print_gmv'}:
                return _error('pilot_attachment_invalid', 400)
            query = '?' + urlencode({'campo': request.args['campo']})
        elif request.args:
            return _error('pilot_query_invalid', 400)
        try:
            body = None
            content_type = 'application/json'
            if request.method != 'GET':
                limit = MAX_IMAGE if path == 'anexos' else MAX_JSON
                body = _request_body(limit)
                if path == 'anexos':
                    content_type = request.mimetype or 'application/octet-stream'
                    if content_type not in {'image/jpeg', 'image/png', 'image/webp', 'application/octet-stream'}:
                        return _error('pilot_attachment_invalid', 415)
                elif not request.is_json:
                    return _error('pilot_json_required', 415)
                else:
                    _json(body)
            # Every state-changing request is authenticated against V5 first;
            # the V5 helper independently revalidates identity and final effects.
            if request.method == 'GET' and path == 'agenciamento':
                # The status endpoint authenticates the same token itself and
                # is strictly read-only. Do not create/update a draft here.
                result = _call(transport, path, 'GET', token)
            else:
                context_result = _call(transport, 'contexto', 'GET', token)
                context = _proof(context_result, token)
                if request.method == 'GET':
                    result = context_result
                else:
                    if context['submitted'] and (request.method, path) not in {
                            ('POST', 'respostas'), ('POST', 'imagem'), ('POST', 'email/estado')}:
                        return _error('pilot_completed', 409)
                    result = _call(transport, path, request.method, token, body=body,
                                   content_type=content_type, query=query)
            mime = result.content_type.split(';', 1)[0].strip().lower()
            if path == 'imagem' and result.status == 200:
                if mime != 'image/jpeg' or not result.body.startswith(b'\xff\xd8\xff'):
                    raise PilotError('pilot_upstream_invalid')
                return _response(result.body, 200, 'image/jpeg')
            if mime != 'application/json':
                raise PilotError('pilot_upstream_invalid')
            _json(result.body)
            return _response(result.body, result.status, 'application/json')
        except PilotError as error:
            return _error(error.code, error.status)

    app.add_url_rule('/cadastro/ensaio', endpoint='cadastro_v5_pilot_page', view_func=page,
                     methods=['GET'], provide_automatic_options=False)
    app.add_url_rule(PREFIX + '<path:path>', endpoint='cadastro_v5_pilot_proxy', view_func=proxy,
                     methods=['GET', 'PUT', 'POST'], provide_automatic_options=False)
    return app
