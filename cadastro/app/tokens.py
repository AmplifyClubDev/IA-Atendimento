"""Tokens assinados (HMAC-SHA256), sem estado no servidor.

Formato: base64url(json || assinatura de 32 bytes), sem ponto nem padding, para
caber na regra do navegador (`^[A-Za-z0-9_-]+=*$`, até 4096 caracteres).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time


class TokenInvalido(ValueError):
    pass


def _key(secret: str, kind: str) -> bytes:
    return hmac.new(secret.encode(), b"amplify-cadastro-publico-v5:" + kind.encode(), hashlib.sha256).digest()


def sign(secret: str, kind: str, claims: dict, *, now: float | None = None) -> str:
    body = json.dumps({**claims, "k": kind, "iat": int(now if now is not None else time.time())},
                      separators=(",", ":"), sort_keys=True).encode()
    mac = hmac.new(_key(secret, kind), body, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(body + mac).decode().rstrip("=")


def verify(secret: str, kind: str, token: object, *, ttl: int, now: float | None = None) -> dict:
    try:
        if not isinstance(token, str) or not 40 < len(token) <= 2048:
            raise ValueError()
        raw = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4))
        body, mac = raw[:-32], raw[-32:]
        if not hmac.compare_digest(mac, hmac.new(_key(secret, kind), body, hashlib.sha256).digest()):
            raise ValueError()
        claims = json.loads(body)
        age = (now if now is not None else time.time()) - claims["iat"]
        if claims.get("k") != kind or not -60 <= age <= ttl:
            raise ValueError()
        return claims
    except (ValueError, TypeError, KeyError, UnicodeError):
        raise TokenInvalido() from None


def digest(secret: str, purpose: str, value: str) -> str:
    """HMAC para guardar IP/código/e-mail sem o valor em texto."""
    return hmac.new(secret.encode(), (purpose + ":" + value).encode(), hashlib.sha256).hexdigest()
