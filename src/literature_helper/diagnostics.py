from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from .config import AppConfig, default_home


def collect_diagnostics(
    config: AppConfig,
    *,
    config_path: Path | None = None,
) -> dict[str, Any]:
    checks: dict[str, Any] = {
        "python": sys.version.split()[0],
        "config": str(config_path or (default_home() / "config.json")),
        "data_dir": str(config.data_dir),
        "profile_dir": str(config.profile_dir),
        "browser_session": "saved" if config.profile_dir.exists() else "not_created",
        "download_dir": str(config.download_dir),
        "browser_channel": config.browser_channel,
        "poll_interval_seconds": config.poll_interval_seconds,
        "download_timeout_seconds": config.download_timeout_seconds,
        "prefer_high_speed_download": config.prefer_high_speed_download,
        "headless": config.headless,
    }
    try:
        import playwright  # noqa: F401

        checks["playwright"] = "ok"
    except ImportError:
        checks["playwright"] = "missing"
    try:
        import pypdf

        checks["pypdf"] = pypdf.__version__
    except ImportError:
        checks["pypdf"] = "missing"
    try:
        import questionary

        checks["questionary"] = getattr(questionary, "__version__", "ok")
    except ImportError:
        checks["questionary"] = "missing"
    return checks


def diagnostics_ok(checks: dict[str, Any]) -> bool:
    return (
        checks.get("playwright") == "ok"
        and checks.get("pypdf") != "missing"
        and checks.get("questionary") != "missing"
    )
