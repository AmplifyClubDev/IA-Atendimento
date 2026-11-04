"""Explicit bridge isolation. No network, dotenv loading, or secret logging."""
import re
from urllib.parse import urlsplit

PRODUCTION_HOSTS = frozenset({
    "tiktok-agenciamento-production.up.railway.app",
    "tiktok-pre-validacao-production.up.railway.app",
    "tiktok-partner-bridge-production.up.railway.app",
    "tiktok-gmv-production.up.railway.app",
})


def bridge_settings(env):
    # Missing markers preserve production. Any explicit nonproduction marker wins,
    # including empty/unknown values: APP_ENV cannot override Railway staging.
    markers = [str(env[key]).strip().lower() for key in ("APP_ENV", "RAILWAY_ENVIRONMENT_NAME") if key in env]
    environment = "production" if all(value == "production" for value in markers) else "nonproduction"
    return {
        "bridge_environment": environment,
        "bridge_nonproduction_enabled": env.get("V5_TIKTOK_NONPRODUCTION_ENABLED") == "true",
        "bridge_allowed_hosts": {
            role: str(env.get("V5_TIKTOK_" + role.upper() + "_ALLOWED_HOST", "")).strip().lower()
            for role in ("agency", "precheck", "invites", "gmv", "lookup")
        },
    }


def nonproduction(settings):
    return settings.get("bridge_environment", "production") != "production"


def allowed_host(settings, role, hostname):
    if not nonproduction(settings):
        return False  # Production continues to use the original role-specific allowlists.
    hosts = settings.get("bridge_allowed_hosts")
    host = hosts.get(role, "") if isinstance(hosts, dict) else ""
    return (settings.get("bridge_nonproduction_enabled") is True
            and isinstance(host, str) and re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?", host) is not None
            and "." in host and host not in PRODUCTION_HOSTS and hostname == host)


def bridge_origin(env, role, production_origin):
    settings = bridge_settings(env)
    default = "" if nonproduction(settings) else production_origin + "/bridge"
    value = str(env.get("V5_TIKTOK_" + role.upper() + "_URL", default))
    # Cadastro historically ignored these optional URL variables. Preserve its
    # production default for empty values; never fall back in nonproduction.
    if not nonproduction(settings) and not value.strip():
        value = default
    try:
        parsed = urlsplit(value)
        production_host = urlsplit(production_origin).hostname
        host_ok = (allowed_host(settings, role, parsed.hostname) if nonproduction(settings)
                   else parsed.hostname == production_host)
        valid = (host_ok and parsed.scheme == "https" and parsed.port in (None, 443)
                 and not parsed.username and not parsed.password and not parsed.query and not parsed.fragment
                 and parsed.path in ("/bridge", "/bridge/") and not any(ord(c) < 33 for c in value))
    except ValueError:
        valid = False
    if not valid:
        return ""
    return "https://" + parsed.netloc


def activation_allowed(env):
    settings = bridge_settings(env)
    return (not nonproduction(settings) or
            (settings["bridge_nonproduction_enabled"] and env.get("PONTES_NONPRODUCTION_ACTIVATION_ENABLED") == "true"))
