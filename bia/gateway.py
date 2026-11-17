"""One transactional form call to the exact V5 project; no automatic retries."""
import json
import re
from datetime import datetime, timedelta, timezone
from uuid import UUID
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlencode
from urllib.request import Request, HTTPRedirectHandler, build_opener

from config import PROJECT_REF


class SubmissionUnknown(Exception):
    pass


class SubmissionRejected(Exception):
    pass


def tiktok_projection(state):
    """Fixed, bounded latest receipts for the same real cycle and exact profile.

    No transcripts, raw provider payloads, cookies, tokens or numeric GMV claims.
    The SQL RPC independently checks this contract before recording a linkage.
    """
    cycle = state.get('cycle') or {}
    if cycle.get('mode') != 'real':
        return {}
    receipts = cycle.get('real_operations') or {}
    if not isinstance(receipts, dict):
        raise SubmissionRejected('tiktok_receipts_invalid')
    allowed = {'precheck', 'relationship', 'invite', 'lookup', 'gmv_report'}
    statuses = {'eligible', 'ineligible', 'verification_pending', 'linked', 'pending',
                'not_found', 'sent', 'pending_verification', 'outcome_unknown', 'failed', 'observed'}
    evidence_keys = {'source', 'relation_id', 'status', 'tiktok_status', 'fresh', 'complete',
                     'shop_account_status', 'shop_status', 'post_attempted', 'http_status',
                     'create_accepted', 'period_and_unit_require_validation', 'metrics',
                     'period_labels', 'start_date', 'end_date_exclusive', 'gmv_observed',
                     'gmv_formatted', 'date_range'}
    result = {}
    declared = (cycle.get('facts') or {}).get('tiktok_declarado')
    declared = declared.lower() if isinstance(declared, str) else None
    for operation, receipt in receipts.items():
        if operation not in allowed:
            raise SubmissionRejected('tiktok_operation_invalid')
        if not isinstance(receipt, dict) or receipt.get('operation') != operation:
            raise SubmissionRejected('tiktok_receipt_invalid')
        creator = receipt.get('creator')
        if (not isinstance(creator, str) or not re.fullmatch(r'@[a-z0-9_][a-z0-9_.]{1,23}', creator)
                or receipt.get('creator') != declared
                or receipt.get('cycle_id') != cycle.get('id') or receipt.get('status') not in statuses
                or type(receipt.get('confirmed')) is not bool):
            raise SubmissionRejected('tiktok_receipt_invalid')
        job_id = receipt.get('job_id')
        observed = receipt.get('observed_at')
        if not isinstance(job_id, str) or not re.fullmatch(r'[A-Za-z0-9@_.:-]{1,240}', job_id):
            raise SubmissionRejected('tiktok_job_invalid')
        try:
            at = datetime.fromisoformat(observed.replace('Z', '+00:00'))
            if at.tzinfo is None or at.utcoffset().total_seconds() != 0:
                raise ValueError()
        except (AttributeError, TypeError, ValueError):
            raise SubmissionRejected('tiktok_clock_invalid') from None
        evidence = receipt.get('evidence')
        if not isinstance(evidence, dict):
            raise SubmissionRejected('tiktok_evidence_invalid')
        # The client already strips the remote envelope. Retain only its fixed
        # operational evidence; SQL validates the linkage-specific attributes.
        clean = {k: v for k, v in evidence.items() if k in evidence_keys}
        try:
            raw = json.dumps(clean, ensure_ascii=False, allow_nan=False)
        except (TypeError, ValueError, OverflowError):
            raise SubmissionRejected('tiktok_evidence_invalid') from None
        if len(raw.encode()) > 4096:
            raise SubmissionRejected('tiktok_evidence_too_large')
        result[operation] = {'operation': operation, 'creator': creator, 'observed_at': observed,
                             'status': receipt['status'], 'confirmed': receipt['confirmed'],
                             'job_id': job_id, 'cycle_id': cycle['id'], 'evidence': clean}
    return result


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class Gateway:
    def __init__(self, settings, transport=None):
        self.settings = settings
        self.transport = transport

    def registration_status(self, phone, handle):
        """Consulta restrita: conclusão exige WhatsApp compatível E o mesmo perfil."""
        phone = re.sub(r'\D', '', str(phone or ''))
        handle = str(handle or '').lower().lstrip('@')
        if not re.fullmatch(r'55\d{10,11}', phone) or not re.fullmatch(r'[a-z0-9_][a-z0-9_.]{1,23}', handle):
            raise SubmissionRejected('registration_identity_missing')
        variants = {phone}
        if len(phone) == 13 and phone[4] == '9':
            variants.add(phone[:4] + phone[5:])
        elif len(phone) == 12:
            variants.add(phone[:4] + '9' + phone[4:])
        base = self.settings.get('v5_url', '').rstrip('/')
        if base != 'https://' + PROJECT_REF + '.supabase.co':
            raise SubmissionRejected('v5_target_mismatch')
        key = self.settings.get('v5_service_key', '')
        if not key:
            raise SubmissionRejected('v5_server_key_missing')
        headers = {'Accept': 'application/json', 'apikey': key, 'Cache-Control': 'no-cache'}
        if key.startswith('eyJ'):
            headers['Authorization'] = 'Bearer ' + key
        query = urlencode({'select': 'id,whatsapp,tiktok,cadastro', 'limit': '10',
                           'or': '(whatsapp.in.(' + ','.join(sorted(variants)) + '),tiktok.eq.' + handle + ')'})
        url = base + '/rest/v1/creators?' + query
        try:
            if self.transport:
                rows = self.transport(method='GET', url=url, headers=headers, timeout=10)
            else:
                with build_opener(NoRedirect).open(Request(url, headers=headers), timeout=10) as response:
                    raw = response.read(65537)
                    if len(raw) > 65536:
                        raise ValueError()
                    rows = json.loads(raw)
            if not isinstance(rows, list) or len(rows) >= 10:
                raise ValueError()
            matched = []
            for row in rows:
                if not isinstance(row, dict) or set(row) != {'id', 'whatsapp', 'tiktok', 'cadastro'}:
                    raise ValueError()
                str(UUID(row['id']))
                other_phone = re.sub(r'\D', '', str(row['whatsapp'] or ''))
                other_handle = str(row['tiktok'] or '').lower().lstrip('@')
                if other_handle == handle and other_phone not in variants:
                    return 'conferencia'
                if other_phone in variants and other_handle and other_handle != handle:
                    return 'conferencia'
                if other_phone in variants and other_handle == handle and row['cadastro'] == 'Confirmado':
                    matched.append(row['id'])
            return 'confirmado' if len(set(matched)) == 1 else 'conferencia' if matched else 'pendente'
        except (HTTPError, URLError, TimeoutError, OSError, ValueError, TypeError, KeyError):
            raise SubmissionUnknown('registration_read_unconfirmed') from None

    def _rpc(self, name, body):
        base = self.settings.get('v5_url', '').rstrip('/')
        try:
            parsed = urlsplit(base)
            valid_target = (parsed.scheme == 'https' and parsed.hostname == PROJECT_REF + '.supabase.co'
                            and not any((parsed.username, parsed.password, parsed.port, parsed.path,
                                         parsed.query, parsed.fragment)))
        except ValueError:
            valid_target = False
        if not valid_target:
            raise SubmissionRejected('v5_target_mismatch')
        key = self.settings.get('v5_service_key', '')
        if not key:
            raise SubmissionRejected('v5_server_key_missing')
        headers = {'Content-Type': 'application/json', 'Accept': 'application/json', 'apikey': key}
        if key.startswith('eyJ'):
            headers['Authorization'] = 'Bearer ' + key
        url = base + '/rest/v1/rpc/' + name
        try:
            if self.transport:
                value = self.transport(method='POST', url=url, headers=headers, json=body, timeout=20)
            else:
                request = Request(url, data=json.dumps(body, ensure_ascii=False).encode(), headers=headers, method='POST')
                with build_opener(NoRedirect).open(request, timeout=20) as response:
                    raw = response.read(1_048_577)
                    if len(raw) > 1_048_576:
                        raise SubmissionUnknown('response_too_large')
                    value = json.loads(raw)
        except HTTPError as error:
            status = error.code
            error.close()
            if status >= 500 or status in (408, 429):
                raise SubmissionUnknown('database_result_unknown') from None
            raise SubmissionRejected('database_rejected') from None
        except (URLError, TimeoutError, OSError, ValueError):
            raise SubmissionUnknown('database_result_unknown') from None
        return value

    def submit(self, plan):
        value = self._rpc('registrar_cadastro_ensaio_v5', {'p_payload': plan['payload'], 'p_context': plan['context']})
        if not isinstance(value, dict) or str(value.get('creator_id', '')) != str(plan['context']['creator_id']):
            raise SubmissionUnknown('receipt_not_confirmed')
        if plan['context'].get('execution_mode') == 'real' and (
                value.get('status') != 'cadastro_recebido_real'
                or value.get('event_id') != plan['context'].get('event_id')):
            raise SubmissionUnknown('real_registration_receipt_not_confirmed')
        return value

    def register_contact(self, entrada):
        """Exactly one server-owned contact/cycle operation; never a blind retry."""
        if not isinstance(entrada, dict):
            raise SubmissionRejected('contact_payload_invalid')
        declarations = entrada.get('declaracoes_chat')
        if declarations:
            payload = {key: item for key, item in entrada.items() if key != 'declaracoes_chat'}
            value = self._rpc('registrar_contato_declaracoes_v5',
                              {'p_entrada': payload, 'p_declaracoes': declarations})
        else:
            value = self._rpc('registrar_contato_v5', {'p_entrada': entrada})
        try:
            creator = str(UUID(value['creator_id']))
            valid = (isinstance(value, dict) and value['creator_id'] == creator
                     and creator != '00000000-0000-0000-0000-000000000000'
                     and value.get('event_id') == entrada.get('event_id')
                     and type(value.get('revision')) is int and value['revision'] == entrada.get('revision')
                     and value.get('atendimento_id') == entrada.get('atendimento_id')
                     and isinstance(value.get('cadastro_situacao'), str))
        except (ValueError, TypeError, KeyError, AttributeError):
            valid = False
        if not valid:
            raise SubmissionUnknown('contact_receipt_not_confirmed')
        preferred = entrada.get('creator_id')
        if preferred and creator != preferred:
            raise SubmissionUnknown('contact_creator_mismatch')
        return value

    def register_chatwoot_labels(self, entrada):
        """Persist one idempotent, readback-confirmed label snapshot."""
        if not isinstance(entrada, dict):
            raise SubmissionRejected('labels_payload_invalid')
        value = self._rpc('registrar_etiquetas_chatwoot_v5', {'p_entrada': entrada})
        if (not isinstance(value, dict) or value.get('status') not in {'recorded', 'replayed'}
                or any(value.get(key) != entrada.get(key)
                       for key in ('atendimento_id', 'revision', 'labels', 'signature'))):
            raise SubmissionUnknown('labels_receipt_not_confirmed')
        return value

    def cleanup_retention(self):
        """One bounded server-owned cleanup; never a browser or message path."""
        value = self._rpc('limpar_registros_v5', {'p_limite': 1000})
        keys = {'status', 'technical_deleted', 'summaries_deleted', 'total_deleted',
                'detail_cutoff', 'summary_cutoff', 'has_more'}
        counts = ('technical_deleted', 'summaries_deleted', 'total_deleted')
        valid = (isinstance(value, dict) and value.keys() == keys and value.get('status') == 'completed'
                 and type(value.get('has_more')) is bool
                 and all(type(value.get(key)) is int and 0 <= value[key] <= 1000 for key in counts)
                 and value['total_deleted'] == value['technical_deleted'] + value['summaries_deleted'])
        try:
            dates = [datetime.fromisoformat(value[key].replace('Z', '+00:00'))
                     for key in ('detail_cutoff', 'summary_cutoff')]
            valid = valid and all(stamp.tzinfo and stamp.utcoffset() == timedelta(0) for stamp in dates)
            valid = valid and dates[0] - dates[1] == timedelta(days=60)
        except (TypeError, ValueError, KeyError, AttributeError):
            valid = False
        if not valid:
            raise SubmissionUnknown('retention_receipt_unconfirmed')
        # No timestamps, source rows or provider bodies enter scheduler state/logs.
        return {**{key: value[key] for key in counts}, 'has_more': value['has_more']}
