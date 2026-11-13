"""Bounded readers and one-attempt invitation client for the private pilot.

The caller must durably reserve the business operation before ``execute``.
This client owns no retries, cookies, login, database, approval or category.
Injected transport returns ``(http_status, decoded_json_object)``.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
import json
import math
import re
import time
from uuid import UUID
from urllib.error import HTTPError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener


_BRIDGE_HOSTS = {
    "precheck": {"tiktok-pre-validacao-production.up.railway.app"},
    "agency": {"tiktok-agenciamento-production.up.railway.app"},
    "invites": {"tiktok-partner-bridge-production.up.railway.app"},
    "gmv": {"tiktok-partner-bridge-production.up.railway.app", "tiktok-gmv-production.up.railway.app"},
}
_LIMIT = 2 * 1024 * 1024
_HANDLE = re.compile(r"[a-z0-9_][a-z0-9_.]{1,23}\Z")
_BLOCKED = {"human_login_required", "blocked_by_risk_guard", "captcha_required", "mfa_required",
            "session_or_partner_context_invalid", "partner_probe_rejected", "lookup_login_required",
            "creator_lookup_session_unavailable", "creator_lookup_human_verification_required"}


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class _CallError(Exception):
    def __init__(self, reason):
        self.reason = reason


def _now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _handle(value):
    if not isinstance(value, str):
        raise ValueError("invalid_creator")
    value = value.strip().removeprefix("@").lower()
    if not _HANDLE.fullmatch(value):
        raise ValueError("invalid_creator")
    return value


def _number(value):
    return type(value) in (int, float) and math.isfinite(value)


def _integer(value):
    return type(value) is int


def _short(value, size=120):
    return value if isinstance(value, str) and 0 < len(value) <= size and not any(ord(c) < 32 for c in value) else None


def _json_object(value):
    if not isinstance(value, dict):
        raise _CallError("invalid_response")
    try:
        raw = json.dumps(value, allow_nan=False, separators=(",", ":"))
    except (ValueError, TypeError, OverflowError, RecursionError):
        raise _CallError("invalid_response") from None
    if len(raw.encode()) > _LIMIT:
        raise _CallError("response_too_large")
    return value


def _transport(*, method, url, headers, json_body=None, timeout=30):
    data = json.dumps(json_body, allow_nan=False).encode() if json_body is not None else None
    request = Request(url, data=data, headers=headers, method=method)
    try:
        response = build_opener(_NoRedirect(), ProxyHandler({})).open(request, timeout=timeout)
    except HTTPError as error:
        response = error
    with response:
        status = response.status
        raw = response.read(_LIMIT + 1)
    if len(raw) > _LIMIT:
        raise _CallError("response_too_large")
    try:
        return status, json.loads(raw)
    except (ValueError, UnicodeError):
        raise _CallError("invalid_response") from None


class PlaywrightClient:
    def __init__(self, settings, transport=None, *, monotonic=None, sleep=None):
        self.settings = dict(settings)
        self.transport = transport or _transport
        self._monotonic = monotonic or time.monotonic
        self._sleep = sleep or time.sleep

    def configuration(self, operation=None):
        """Local configuration check only; never session/readiness evidence.

        The default checks the three essential bridges. Optional lookup and GMV
        are checked explicitly by operation so their absence cannot imply zero.
        """
        roles = {None: ("precheck", "agency", "invites"), "precheck": ("precheck",),
                 "relationship": ("agency",), "invite": ("precheck", "agency", "invites"),
                 "lookup": ("lookup",), "gmv": ("gmv",), "gmv_report": ("gmv",)}
        if operation not in roles:
            return {"configured": False, "issues": ["invalid_operation"]}
        issues = []
        if operation in (None, 'invite'):
            from config import invite_method_issue
            method_issue = invite_method_issue(self.settings)
            if method_issue:
                issues.append('invites:' + method_issue)
        for role in roles[operation]:
            try:
                self._connection(role)
            except _CallError as error:
                issues.append(role + ":" + error.reason)
        for key, default, minimum, maximum in (("tiktok_timeout_seconds", 135, 5, 135),
                                               ("tiktok_status_timeout_seconds", 5, 1, 10)):
            value = self.settings.get(key, default)
            if not _number(value) or not minimum <= value <= maximum:
                issues.append(key + ":invalid")
        return {"configured": not issues, "issues": issues}

    def _result(self, operation, creator, status, reason, *, confirmed=False, evidence=None):
        return {"operation": operation, "creator": creator, "observed_at": _now(), "status": status,
                "confirmed": confirmed is True, "evidence": evidence or {}, "reason": reason}

    def _diagnostic_text(self, value, *, maximum=200):
        if not isinstance(value, str):
            return None
        text = value[:4000]
        for name, secret in self.settings.items():
            if (isinstance(name, str) and re.search(r'token|password|secret|service_key|api_key|senha', name, re.I)
                    and isinstance(secret, str) and len(secret) >= 6):
                text = text.replace(secret, '[redacted]')
        text = re.sub(r'https?://\S+', '[redacted_url]', text, flags=re.I)
        text = re.sub(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}', '[redacted_email]', text)
        text = re.sub(r'\b(?:bearer\s+)[^\s,;]+', '[redacted]', text, flags=re.I)
        text = re.sub(r'''\b(?:token|cookie|password|secret|authorization|sessionid|api_key)\s*["']?\s*[=:]\s*["']?[^"'\s,;}]+''',
                      '[redacted]', text, flags=re.I)
        text = re.sub(r'\b[A-Za-z0-9_-]{32,}\b', '[redacted]', text)
        text = re.sub(r'[\x00-\x1f\x7f-\x9f]', ' ', text)
        text = re.sub(r'\s+', ' ', text).strip()
        return text[:maximum] or None

    def _diagnostic_code(self, value):
        if isinstance(value, bool) or not isinstance(value, (str, int, float)):
            return None
        if isinstance(value, float) and not math.isfinite(value):
            return None
        value = str(value)
        if not re.fullmatch(r'[A-Za-z0-9_.:-]{1,64}', value):
            return None
        return value if self._diagnostic_text(value, maximum=64) == value else None

    def _invite_receipt(self, value):
        """Keep the fixed bridge receipt, never a raw request/response dump."""
        if not isinstance(value, dict) or type(value.get('version')) is not int or value['version'] != 1:
            return None
        if value.get('method') not in {'api', 'ui'}:
            return None
        receipt = {'version': 1, 'method': value['method']}
        if value.get('status') in {'not_attempted', 'create_rejected', 'create_accepted', 'outcome_unknown'}:
            receipt['status'] = value['status']
        if isinstance(value.get('stage'), str) and re.fullmatch(r'[a-z][a-z0-9_:-]{0,63}', value['stage']):
            receipt['stage'] = value['stage']
        for key in ('ui_submit_attempted', 'provider_request_observed', 'provider_post_attempted',
                    'create_post_blocked', 'target_verified'):
            if type(value.get(key)) is bool:
                receipt[key] = value[key]
        status = value.get('provider_http_status')
        if status is None or type(status) is int and 100 <= status <= 599:
            receipt['provider_http_status'] = status
        code, message = self._diagnostic_code(value.get('provider_code')), self._diagnostic_text(value.get('provider_message'))
        if code is not None:
            receipt['provider_code'] = code
        if message is not None:
            receipt['provider_message'] = message
        try:
            identifier = str(UUID(value.get('operation_id')))
            if identifier != '00000000-0000-0000-0000-000000000000':
                receipt['operation_id'] = identifier
        except (ValueError, TypeError, AttributeError):
            pass
        stamp = value.get('observed_at')
        try:
            if isinstance(stamp, str) and len(stamp) <= 40 and datetime.fromisoformat(stamp.replace('Z', '+00:00')).utcoffset().total_seconds() == 0:
                receipt['observed_at'] = stamp
        except (ValueError, TypeError, AttributeError, OverflowError):
            pass
        return receipt

    def _invite_diagnostics(self, data):
        evidence = {}
        receipt = self._invite_receipt(data.get('receipt'))
        if receipt:
            evidence['receipt'] = receipt
            for source, target in (('provider_code', 'upstream_code'), ('provider_message', 'upstream_message'),
                                   ('provider_http_status', 'provider_http_status')):
                if source in receipt:
                    evidence[target] = receipt[source]
        create = data.get('create')
        sources = [create] if isinstance(create, dict) else []
        if sources and isinstance(create.get('data'), dict):
            sources.append(create['data'])
        for source in sources:
            if 'upstream_code' not in evidence:
                code = self._diagnostic_code(source.get('code'))
                if code is not None:
                    evidence['upstream_code'] = code
            if 'upstream_message' not in evidence:
                message = self._diagnostic_text(source.get('message'))
                if message is not None:
                    evidence['upstream_message'] = message
        return evidence

    def _connection(self, role):
        base = self.settings.get("tiktok_" + role + "_url", "")
        token = self.settings.get("tiktok_" + role + "_token", "")
        if not isinstance(base, str) or not isinstance(token, str) or len(token) < 32 or re.search(r"[\r\n]", token):
            raise _CallError("connection_not_configured")
        try:
            parsed = urlsplit(base)
            common = (not parsed.username and not parsed.password and not parsed.query and not parsed.fragment
                      and not any(ord(c) < 33 for c in base) and not base.endswith("//"))
            if role == "lookup":
                valid = (common and parsed.scheme == "http" and parsed.hostname == "consulta-tiktok.railway.internal"
                         and parsed.port is not None and 1 <= parsed.port <= 65535 and parsed.path in ("", "/"))
            else:
                valid = (common and parsed.scheme == "https" and parsed.hostname in _BRIDGE_HOSTS[role]
                         and parsed.port in (None, 443) and parsed.path in ("/bridge", "/bridge/"))
        except (ValueError, KeyError):
            valid = False
        if not valid:
            raise _CallError("connection_target_invalid")
        return base.rstrip("/"), token

    def _call(self, role, method, path, *, body=None, params=None, status_probe=False, timeout_cap=None):
        base, token = self._connection(role)
        default = 5 if status_probe else 135
        setting = "tiktok_status_timeout_seconds" if status_probe else "tiktok_timeout_seconds"
        timeout = self.settings.get(setting, default)
        maximum = 10 if status_probe else 135
        minimum = 1 if status_probe else 5
        if not _number(timeout) or not minimum <= timeout <= maximum:
            raise _CallError("timeout_configuration_invalid")
        if timeout_cap is not None:
            timeout = min(timeout, timeout_cap)
        url = base + path + ("?" + urlencode(params) if params else "")
        try:
            result = self.transport(method=method, url=url,
                                    headers={"Authorization": "Bearer " + token, "Accept": "application/json",
                                             "Content-Type": "application/json"},
                                    json_body=body, timeout=timeout)
        except _CallError:
            raise
        except Exception:
            raise _CallError("transport_unconfirmed") from None
        if not isinstance(result, tuple) or len(result) != 2 or not _integer(result[0]):
            raise _CallError("invalid_response")
        status, payload = result[0], _json_object(result[1])
        if 300 <= status < 400:
            raise _CallError("redirect_rejected")
        if status < 100 or status > 599:
            raise _CallError("invalid_response")
        return status, payload

    def _ready(self, role):
        deadline = self._monotonic() + 12
        for attempt in range(3):
            remaining = deadline - self._monotonic()
            if remaining <= 0:
                raise _CallError("session_not_ready")
            code, data = self._call(role, "GET", "/ready", status_probe=True, timeout_cap=remaining)
            if data.get("status") in _BLOCKED:
                raise _CallError("human_verification_required")
            if self._monotonic() > deadline:
                raise _CallError("session_not_ready")
            context, probe, readiness, guard = (data.get(k) for k in ("contexto", "probe", "readiness", "riskGuard"))
            valid = (code == 200 and data.get("ok") is True and data.get("status") == "ready"
                     and isinstance(context, dict) and context.get("aberto") is True and context.get("pronto") is True
                     and isinstance(probe, dict) and probe.get("status") == "ok" and _number(probe.get("ageMs"))
                     and probe["ageMs"] >= 0 and isinstance(readiness, dict)
                     and isinstance(guard, dict) and guard.get("status") == "clear")
            if valid and probe["ageMs"] <= 60000 and readiness.get("fresh") is True:
                return
            # A healthy bridge can briefly serve its last successful proof while
            # renewing it. Only that precise state permits another GET; success
            # still requires a fresh proof, and no provider operation is retried.
            refreshing = (valid and probe["ageMs"] > 60000
                          and (readiness.get("withinGrace") is True or readiness.get("refreshing") is True))
            if not refreshing or attempt == 2 or deadline - self._monotonic() <= 2:
                raise _CallError("session_not_ready")
            self._sleep(2)

    def _relations(self, creator, status):
        code, data = self._call("agency", "GET", "/relations", params={
            "status": str(status), "creators": creator, "page_size": "100", "page_limit": "100",
            "fresh": "1", "priority": "accept" if status == 1 else "invite-confirm"})
        pages, items = data.get("pages"), data.get("items")
        if data.get("status") in _BLOCKED:
            raise _CallError("human_verification_required")
        if not (code == 200 and data.get("ok") is True and data.get("status") == "relations_listed"
                and data.get("completo") is True and isinstance(items, list) and len(items) <= 10000
                and isinstance(pages, list) and 1 <= len(pages) <= 100
                and all(isinstance(page, dict) and page.get("ok") is True for page in pages)
                and data.get("cache") is None):
            raise _CallError("relations_unconfirmed_or_incomplete")
        # Do not trust an inconsistent completeness flag. The returned items
        # have already been filtered by the bridge, so their count cannot be
        # compared with the agency-wide total.
        last = pages[-1]
        if last.get("hasMore") is not False:
            total = data.get("totalNum")
            counts = [page.get("count") for page in pages]
            if (last.get("hasMore") is True or not _integer(total) or total < 0
                    or not all(_integer(count) and count >= 0 for count in counts) or sum(counts) < total):
                raise _CallError("relations_completeness_inconsistent")
        query = data.get("query")
        if not (isinstance(query, dict) and str(query.get("status")) == str(status)
                and query.get("creators") == [creator]):
            raise _CallError("relations_target_unconfirmed")
        matches = []
        for item in items:
            if not isinstance(item, dict):
                raise _CallError("invalid_relation_item")
            try:
                exact = _handle(item.get("arroba")) == creator
            except ValueError:
                raise _CallError("invalid_relation_item") from None
            if exact:
                matches.append(item)
            else:
                raise _CallError("relations_target_unconfirmed")
        if len(matches) > 1:
            raise _CallError("relation_ambiguous")
        if not matches:
            return None
        item = matches[0]
        expected = "vinculado" if status == 1 else "solicitada"
        raw, nested = item.get("tiktok_status"), item.get("tiktok_data_status")
        if (item.get("status") != expected or not _integer(raw) or not _integer(nested)
                or raw != status or nested != status or not _short(str(item.get("relation_id", "")))):
            raise _CallError("relation_status_unconfirmed")
        # Invitation expiry is not the effective end of an accepted binding.
        expiry_fields = ("effective_end_date_second",) if status == 1 else ("expire_time_second", "effective_end_date_second")
        for field in expiry_fields:
            value = item.get(field)
            if value not in (None, "", 0, "0"):
                if not isinstance(value, (str, int)) or isinstance(value, bool) or not str(value).isdigit():
                    raise _CallError("relation_expiry_unconfirmed")
                if int(value) <= datetime.now(timezone.utc).timestamp():
                    raise _CallError("relation_expired")
        return {"relation_id": str(item["relation_id"]), "status": expected,
                "tiktok_status": status, "source": "partner_relations", "fresh": True, "complete": True}

    def _relationship(self, creator):
        self._ready("agency")
        active = self._relations(creator, 1)
        if active:
            return "linked", active
        pending = self._relations(creator, 2)
        if pending:
            return "pending", pending
        return "not_found", {"source": "partner_relations", "fresh": True, "complete": True}

    def _precheck(self, creator):
        self._ready("precheck")
        code, data = self._call("precheck", "POST", "/precheck", body={"creator": creator})
        if data.get("status") in _BLOCKED:
            raise _CallError("human_verification_required")
        precheck = data.get("precheck")
        if not (code == 200 and data.get("ok") is True and data.get("status") == "precheck_ok"
                and data.get("creator") == creator and isinstance(precheck, dict) and precheck.get("ok") is True):
            raise _CallError("precheck_unconfirmed")
        raw = precheck.get("data")
        if not isinstance(raw, dict) or ("code" in raw and not (type(raw["code"]) is int and raw["code"] == 0
                                                              or type(raw["code"]) is str and raw["code"] == "0")):
            raise _CallError("precheck_unconfirmed")
        detail = raw.get("data")
        account = detail.get("pay_account_info") if isinstance(detail, dict) else None
        status = account.get("account_status") if isinstance(account, dict) else None
        if not _integer(status):
            return "verification_pending", {"source": "partner_precheck", "shop_status": "unknown"}
        return ("eligible" if status == 1 else "ineligible"), {"source": "partner_precheck", "shop_account_status": status}

    def _invite(self, creator, confirmed, commission, before_write):
        if confirmed is not True:
            return "failed", False, {}, "explicit_confirmation_required"
        if isinstance(commission, bool) or not isinstance(commission, (str, int, float, Decimal)):
            return "failed", False, {}, "approved_commission_required"
        try:
            value = Decimal(str(commission))
            if not value.is_finite() or not Decimal("0") <= value <= Decimal("10") or value.as_tuple().exponent < -2:
                raise InvalidOperation()
        except (InvalidOperation, ValueError):
            return "failed", False, {}, "approved_commission_required"
        from config import invite_method_issue
        if invite_method_issue(self.settings):
            return 'failed', False, {'post_attempted': False}, 'invitation_method_not_authorized'
        method = self.settings.get('tiktok_invite_method', 'api')
        self._ready("invites")
        relation_status, relation = self._relationship(creator)
        if relation_status != "not_found":
            return relation_status, True, {**relation, "post_attempted": False}, "existing_relation"
        precheck_status, proof = self._precheck(creator)
        if precheck_status != "eligible":
            return precheck_status, precheck_status == "ineligible", {**proof, "post_attempted": False}, "precheck_not_eligible"
        # Revalidate the sending session immediately before the sole write attempt.
        self._ready("invites")
        body = {"creator": creator, "confirm": True, "commission": format(value, "f"),
                "skip_precheck": True, "force_reinvite": False}
        if method == 'ui':
            body['invite_method'] = 'ui'
        # Long scans may outlive the consent/cycle/window. The caller rechecks
        # durable authority immediately before the external write, not at enqueue.
        try:
            authorized_now = callable(before_write) and before_write() is True
        except Exception:
            authorized_now = False
        if not authorized_now:
            return "verification_pending", False, {"post_attempted": False}, "write_authority_unconfirmed"
        try:
            code, data = self._call("invites", "POST", "/invite", body=body)
        except _CallError as error:
            return "outcome_unknown", False, {"post_attempted": True}, error.reason
        evidence = {"post_attempted": True, "http_status": code, "source": "partner_invite"}
        evidence.update(self._invite_diagnostics(data))
        create, validation = data.get("create"), data.get("validation")
        create_accepted = isinstance(create, dict) and create.get("ok") is True
        if isinstance(create, dict) and type(create.get('ok')) is bool:
            evidence['create_accepted'] = create['ok']
        try:
            exact = _handle(data.get("creator")) == creator
        except ValueError:
            exact = False
        receipt = evidence.get('receipt') or {}
        if (method == 'ui' and exact and code == 422 and data.get('ok') is False
                and data.get('status') == 'invite_not_attempted' and not create_accepted
                and receipt.get('method') == 'ui' and receipt.get('status') == 'not_attempted'
                and receipt.get('provider_post_attempted') is False
                and (receipt.get('ui_submit_attempted') is False or receipt.get('create_post_blocked') is True)):
            evidence.update(post_attempted=False, bridge_post_attempted=True)
            return 'failed', False, evidence, 'invitation_not_attempted'
        if method == 'ui' and receipt.get('status') == 'outcome_unknown' and not create_accepted:
            return 'outcome_unknown', False, evidence, 'invitation_result_unconfirmed'
        if code == 200 and data.get("ok") is True and data.get("status") == "invite_sent_and_verified" and exact:
            if (create_accepted and isinstance(validation, dict) and validation.get("ok") is True
                    and validation.get("status") in {"requested", "linked"}):
                # Independent fresh read is the authority; nested success alone is not.
                try:
                    status, relation = self._relationship(creator)
                except _CallError:
                    return "pending_verification", False, evidence, "invitation_reconciliation_required"
                if status in {"linked", "pending"}:
                    return "linked" if status == "linked" else "sent", True, {**evidence, **relation}, "invitation_verified"
        if create_accepted or data.get("status") in {"invite_sent_unverified", "operation_uncertain_reconcile_same_target"}:
            return "pending_verification", False, evidence, "invitation_reconciliation_required"
        if code in (400, 401, 403, 404) and data.get("ok") is False:
            return "failed", False, evidence, "invitation_rejected"
        if (exact and code == 422 and data.get("ok") is False and not create_accepted
                and evidence.get("upstream_code") == "16004004"
                and ((isinstance(create, dict) and create.get("ok") is False)
                     or receipt.get("status") == "create_rejected")):
            return "failed", False, evidence, "creator_binding_not_permitted"
        if code == 422 and data.get("ok") is False and isinstance(create, dict) and create.get("ok") is False:
            return "failed", False, evidence, "invitation_rejected"
        return "outcome_unknown", False, evidence, "invitation_result_unconfirmed"

    def _lookup(self, creator):
        code, data = self._call("lookup", "GET", "/creator-lookup", params={"creator": creator})
        if data.get("status") in _BLOCKED:
            raise _CallError("human_verification_required")
        if not (code == 200 and data.get("ok") is True and data.get("status") == "creator_lookup_observed"
                and data.get("creator") == creator and data.get("verificationStatus") == "period_and_unit_require_validation"):
            raise _CallError("creator_lookup_unconfirmed")
        metrics, labels = data.get("metrics"), data.get("periodLabels")
        if not isinstance(metrics, dict) or not isinstance(labels, list) or len(labels) > 8:
            raise _CallError("creator_lookup_unconfirmed")
        safe_metrics = {}
        for key in ("med_gmv_revenue", "med_gmv_revenue_range"):
            metric = metrics.get(key)
            if not isinstance(metric, dict):
                raise _CallError("creator_lookup_unconfirmed")
            safe_metrics[key] = {name: value for name, value in metric.items()
                                 if name in {"value", "format", "currency", "currency_code", "symbol"}
                                 and (_short(value) is not None or _number(value))}
        return {"source": "creator_directory", "metrics": safe_metrics,
                "period_labels": [value for value in labels if _short(value)],
                "period_and_unit_require_validation": True}

    def _gmv_report(self, creator, start_date, end_date_exclusive):
        try:
            start, end = date.fromisoformat(start_date), date.fromisoformat(end_date_exclusive)
            if start.isoformat() != start_date or end.isoformat() != end_date_exclusive or not 0 < (end - start).days <= 366:
                raise ValueError()
        except (TypeError, ValueError):
            raise _CallError("explicit_gmv_period_required") from None
        self._ready("gmv")
        code, data = self._call("gmv", "GET", "/gmv-report", params={"start_date": start_date,
            "end_date_exclusive": end_date_exclusive, "page_size": "100", "page_limit": "200"})
        items, pages, total = data.get("items"), data.get("pages"), data.get("totalCount")
        if not (code == 200 and data.get("ok") is True and isinstance(items, list) and len(items) <= 20000
                and isinstance(pages, list) and pages and all(isinstance(p, dict) and p.get("ok") is True for p in pages)
                and _integer(total) and 0 <= total <= len(items)):
            raise _CallError("gmv_report_incomplete")
        selected = []
        for item in items:
            if not isinstance(item, dict):
                raise _CallError("gmv_report_invalid")
            try:
                match = _handle(item.get("arroba")) == creator
            except ValueError:
                raise _CallError("gmv_report_invalid") from None
            if match:
                if not _number(item.get("gmv")) or item["gmv"] < 0:
                    raise _CallError("gmv_report_invalid")
                selected.append({"gmv_observed": item["gmv"], "gmv_formatted": _short(item.get("gmv_formatted")),
                                 "date_range": _short(item.get("date_range"))})
        if len(selected) != 1:
            raise _CallError("gmv_creator_absent_or_ambiguous")
        return {"source": "partner_gmv_report", "start_date": start_date, "end_date_exclusive": end_date_exclusive,
                "complete": True, **selected[0], "period_and_unit_require_validation": True}

    def execute(self, operation, creator, *, confirmed=False, commission=None, start_date=None,
                end_date_exclusive=None, before_write=None):
        if operation == "gmv":
            operation = "gmv_report"
        try:
            creator = _handle(creator)
        except ValueError:
            return self._result(str(operation)[:30], "", "failed", "invalid_creator")
        if operation not in {"precheck", "invite", "relationship", "lookup", "gmv_report"}:
            return self._result("invalid", creator, "failed", "invalid_operation")
        try:
            if operation == "precheck":
                status, evidence = self._precheck(creator)
                return self._result(operation, creator, status, "shop_unknown" if status == "verification_pending" else "precheck_observed",
                                    confirmed=status in {"eligible", "ineligible"}, evidence=evidence)
            if operation == "relationship":
                status, evidence = self._relationship(creator)
                return self._result(operation, creator, status, "relations_observed", confirmed=True, evidence=evidence)
            if operation == "invite":
                status, proof, evidence, reason = self._invite(creator, confirmed, commission, before_write)
                return self._result(operation, creator, status, reason, confirmed=proof, evidence=evidence)
            if operation == "lookup":
                return self._result(operation, creator, "observed", "period_and_unit_require_validation", evidence=self._lookup(creator))
            return self._result(operation, creator, "observed", "period_and_unit_require_validation",
                                evidence=self._gmv_report(creator, start_date, end_date_exclusive))
        except _CallError as error:
            return self._result(operation, creator, "verification_pending", error.reason)
        except Exception:
            return self._result(operation, creator, "verification_pending", "response_unconfirmed")
