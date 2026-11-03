"""Read-only startup proof of the active V5 context; never calls the AI."""
from __future__ import annotations

import json
from pathlib import Path
import sys


def main(environ=None):
    runtime = str(Path(__file__).resolve().parents[1])
    if runtime not in sys.path:
        sys.path.insert(0, runtime)
    try:
        from config import load_settings
        settings = load_settings(environ)
        if settings.get("context_db_enabled") is not True:
            result = {"passed": True, "source": "disabled", "version": None,
                      "active_cards": 0, "skipped": True}
        else:
            from context_ia import load_context
            context = load_context(settings)
            result = {"passed": True, "source": context["source"],
                      "version": context["knowledge_version"],
                      "active_cards": context["card_count"]}
    except Exception:
        result = {"passed": False, "source": "database", "version": None,
                  "active_cards": 0, "reason": "context_ia_unavailable"}
    print(json.dumps(result, ensure_ascii=True, sort_keys=True))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
