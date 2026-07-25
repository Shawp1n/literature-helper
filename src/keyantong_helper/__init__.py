"""Compatibility namespace for Literature Helper 0.x users."""

from __future__ import annotations

import importlib
import sys

from literature_helper import (
    AcceptAllResult,
    AppConfig,
    Keyantong,
    LiteratureHelper,
    LiteratureMetadata,
    Task,
    TaskStatus,
    __version__,
)


__all__ = [
    "AcceptAllResult",
    "AppConfig",
    "Keyantong",
    "LiteratureHelper",
    "LiteratureMetadata",
    "Task",
    "TaskStatus",
]

for _module_name in (
    "adapter",
    "api",
    "cli",
    "config",
    "diagnostics",
    "models",
    "notifier",
    "pdfcheck",
    "storage",
    "tui",
    "workflow",
):
    _module = importlib.import_module(f"literature_helper.{_module_name}")
    sys.modules[f"{__name__}.{_module_name}"] = _module
    globals()[_module_name] = _module

del _module
del _module_name
