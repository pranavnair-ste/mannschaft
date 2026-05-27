"""Auto-discovery registry for lint rules.

Each rule module under this package must expose:
  - ``RULE_NAME: str``     # stable identifier, also the module file stem
  - ``check(spec) -> list[LintViolation]``

The registry imports every non-underscore module on first access.
"""
from __future__ import annotations

import importlib
import pkgutil
from types import ModuleType

_CACHED: dict[str, ModuleType] | None = None


def _discover() -> dict[str, ModuleType]:
    global _CACHED
    if _CACHED is not None:
        return _CACHED
    out: dict[str, ModuleType] = {}
    package = importlib.import_module(__name__)
    for info in pkgutil.iter_modules(package.__path__):
        if info.name.startswith("_"):
            continue
        mod = importlib.import_module(f"{__name__}.{info.name}")
        rule_name = getattr(mod, "RULE_NAME", info.name)
        if not callable(getattr(mod, "check", None)):
            raise RuntimeError(
                f"Lint rule {info.name!r} missing required `check(spec)` function"
            )
        out[rule_name] = mod
    _CACHED = out
    return out


def all_rules() -> dict[str, ModuleType]:
    return dict(_discover())


def reset_cache_for_testing() -> None:
    global _CACHED
    _CACHED = None
