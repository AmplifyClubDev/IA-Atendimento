"""Offline nonproduction policy. No flag can enable live integrations here."""
import os
from collections.abc import Mapping
from bridge_config import bridge_settings, nonproduction

REASON = "nonproduction_external_effects_disabled"


class ExternalEffectsDisabled(RuntimeError):
    def __init__(self):
        super().__init__(REASON)


def effects_allowed(env=None, settings=None):
    # A supplied production configuration cannot override process-level staging.
    if nonproduction(bridge_settings(os.environ)):
        return False
    if env is not None and nonproduction(bridge_settings(env)):
        return False
    if settings is not None:
        values = settings if isinstance(settings, Mapping) else vars(settings)
        if nonproduction(values):
            return False
    return True


def require_effects(env=None, settings=None):
    if not effects_allowed(env=env, settings=settings):
        raise ExternalEffectsDisabled()
