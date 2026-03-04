# tools/toolset_health_tool.py
#
# Safe Toolset Availability Checker
# ----------------------------------
# Safely runs toolset check_fn's in hermes-agent.
# Hermes implementation of the pattern introduced in the original diff:
#
#   Before:  return check() if check else True      → exception = crash
#   After:   try/except + logger.debug(...)         → exception = False + log
#
# Usage:
#   toolset_health_check(toolsets="web,terminal,vision")
#   toolset_health_check(toolsets="all")

import json
import logging
import os
from tools.registry import registry

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helper: safely run a single check_fn
# ---------------------------------------------------------------------------

def _safe_check(toolset_name: str, check_fn) -> tuple[bool, str | None]:
    """
    check_fn'i çalıştırır; exception fırlatırsa (ağ, config, import hatası)
    uygulamayı çökertmek yerine False + hata mesajı döner.

    Returns:
        (available: bool, error_msg: str | None)
    """
    if check_fn is None:
        return True, None          # no check means available by default

    try:
        result = check_fn()
        return bool(result), None
    except Exception as e:
        logger.debug(
            "Toolset '%s' check raised; treating as unavailable: %s",
            toolset_name, e
        )
        return False, str(e)


# ---------------------------------------------------------------------------
# Helper: find the check_fn for a given toolset
# ---------------------------------------------------------------------------

def _get_check_fn(toolset_name: str):
    """
    Registry'deki tool'ların check_fn'ini inceler.
    İlk başarısız check_fn'i döner; hepsi geçerliyse None döner.
    """
    # registry._tools: {tool_name: ToolEntry}
    tools_in_set = [
        entry for name, entry in registry._tools.items()
        if getattr(entry, "toolset", None) == toolset_name
    ]

    for entry in tools_in_set:
        fn = getattr(entry, "check_fn", None)
        if fn is not None:
            return fn

    return None


# ---------------------------------------------------------------------------
# Main tool handler
# ---------------------------------------------------------------------------

def toolset_health_check(toolsets: str = "all", task_id: str = None) -> str:
    """
    Belirtilen toolset'lerin check_fn'lerini güvenli biçimde çalıştırır
    ve her birinin durumunu raporlar.

    Args:
        toolsets: Virgülle ayrılmış toolset isimleri, ya da "all"
        task_id:  Hermes session izolasyonu için (kullanılmıyor ama API gereği)

    Returns:
        JSON string — toolset durumları + özet
    """
    # Hangi toolset'leri kontrol edeceğiz?
    if toolsets.strip().lower() == "all":
        known = sorted({
            getattr(e, "toolset", None)
            for e in registry._tools.values()
            if getattr(e, "toolset", None)
        })
    else:
        known = [t.strip() for t in toolsets.split(",") if t.strip()]

    results = {}
    errors  = {}

    for ts in known:
        check_fn = _get_check_fn(ts)
        available, err = _safe_check(ts, check_fn)
        results[ts] = available
        if err:
            errors[ts] = err

    available_list   = [ts for ts, ok in results.items() if ok]
    unavailable_list = [ts for ts, ok in results.items() if not ok]

    return json.dumps(
        {
            "summary": {
                "total":       len(results),
                "available":   len(available_list),
                "unavailable": len(unavailable_list),
            },
            "toolsets":    results,          # {name: bool}
            "errors":      errors,           # {name: hata mesajı}  — sadece başarısızlar
            "available":   available_list,
            "unavailable": unavailable_list,
        },
        ensure_ascii=False,
        indent=2,
    )


# ---------------------------------------------------------------------------
# Registry registration
# ---------------------------------------------------------------------------

TOOLSET_HEALTH_SCHEMA = {
    "name": "toolset_health_check",
    "description": (
        "Safely checks whether the specified toolsets meet their requirements "
        "(API key, dependencies, network). If a check raises an exception, "
        "the app does not crash — the toolset is marked as unavailable and "
        "the error is logged at DEBUG level. "
        "CLI, banner, and doctor commands always remain stable."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "toolsets": {
                "type": "string",
                "description": (
                    "Comma-separated toolset names to check. "
                    "Example: 'web,terminal,vision' — or 'all' for everything."
                ),
                "default": "all",
            }
        },
        "required": [],
    },
}

# Hermes registry'ye kayıt — check_fn yok çünkü bu tool her zaman çalışmalı
# Register into Hermes — check_fn=None because this tool must always be available,
# even when every other toolset is broken.
registry.register(
    name="toolset_health_check",
    handler=toolset_health_check,
    schema=TOOLSET_HEALTH_SCHEMA,
    toolset="health",      # /toolsets çıktısında "health" grubu altında görünür
    check_fn=None,         # Her zaman mevcut — check_fn'i olmayan güvenli tool
)
