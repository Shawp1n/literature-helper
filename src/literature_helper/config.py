from __future__ import annotations

import json
import os
import platform
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any


class ConfigError(ValueError):
    """Configuration content is invalid or cannot be interpreted safely."""


def default_home() -> Path:
    """Return the per-user data directory without creating it."""
    override = os.environ.get("LITHELPER_HOME")
    if override:
        return Path(override).expanduser().resolve()

    system = platform.system()
    if system == "Darwin":
        return Path.home() / "Library" / "Application Support" / "literature-helper"
    if system == "Windows":
        root = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        return root / "literature-helper"
    root = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return root / "literature-helper"


@dataclass(slots=True)
class AppConfig:
    data_dir: Path
    profile_dir: Path
    download_dir: Path
    database_path: Path
    debug_dir: Path
    selectors_path: Path | None = None

    assist_url: str = "https://www.ablesci.com/assist/create"
    my_assists_url: str = "https://www.ablesci.com/my/assist-my"
    points_url: str = "https://www.ablesci.com/my/point"
    login_url: str = "https://www.ablesci.com/site/login"
    browser_channel: str | None = "chrome"
    headless: bool = True
    slow_mo_ms: int = 0

    initial_poll_delay_seconds: float = 8.0
    poll_interval_seconds: float = 3.0
    poll_timeout_seconds: float = 180.0
    download_timeout_seconds: float = 180.0
    minimum_pdf_bytes: int = 8_000
    save_debug_artifacts: bool = True
    auto_publish: bool = True
    prefer_high_speed_download: bool = True
    auto_accept_after_validation: bool = False
    auto_accept_historical_pending: bool = True

    @classmethod
    def defaults(cls, home: Path | None = None) -> "AppConfig":
        data_dir = (home or default_home()).expanduser().resolve()
        return cls(
            data_dir=data_dir,
            profile_dir=data_dir / "browser-profile",
            download_dir=Path.home() / "Downloads" / "科研通",
            database_path=data_dir / "tasks.sqlite3",
            debug_dir=data_dir / "debug",
        )

    @classmethod
    def load(cls, path: Path | None = None) -> "AppConfig":
        default = cls.defaults(path.parent if path else None)
        config_path = path or (default.data_dir / "config.json")
        if not config_path.exists():
            return default

        raw = json.loads(config_path.read_text(encoding="utf-8"))
        allowed = {item.name for item in fields(cls)}
        unknown = sorted(set(raw) - allowed)
        if unknown:
            raise ConfigError(f"配置文件包含未知字段: {', '.join(unknown)}")

        merged: dict[str, Any] = asdict(default)
        merged.update(raw)
        for name in (
            "data_dir",
            "profile_dir",
            "download_dir",
            "database_path",
            "debug_dir",
            "selectors_path",
        ):
            value = merged.get(name)
            if value is not None:
                merged[name] = Path(value).expanduser().resolve()

        config = cls(**merged)
        config.validate()
        return config

    def validate(self) -> None:
        if self.poll_interval_seconds < 3:
            raise ConfigError("poll_interval_seconds 不能小于 3 秒，以避免高频刷新站点")
        if self.initial_poll_delay_seconds < 0:
            raise ConfigError("initial_poll_delay_seconds 不能为负数")
        if self.poll_timeout_seconds <= 0:
            raise ConfigError("poll_timeout_seconds 必须大于 0")
        if self.download_timeout_seconds <= 0:
            raise ConfigError("download_timeout_seconds 必须大于 0")
        if self.minimum_pdf_bytes < 1_024:
            raise ConfigError("minimum_pdf_bytes 不能小于 1024")
        if not self.assist_url.startswith("https://www.ablesci.com/"):
            raise ConfigError("assist_url 必须是 https://www.ablesci.com/ 下的地址")
        if not self.my_assists_url.startswith("https://www.ablesci.com/"):
            raise ConfigError("my_assists_url 必须是 https://www.ablesci.com/ 下的地址")
        if not self.points_url.startswith("https://www.ablesci.com/"):
            raise ConfigError("points_url 必须是 https://www.ablesci.com/ 下的地址")
        if not self.login_url.startswith("https://www.ablesci.com/"):
            raise ConfigError("login_url 必须是 https://www.ablesci.com/ 下的地址")

    def ensure_directories(self) -> None:
        for path in (
            self.data_dir,
            self.profile_dir,
            self.download_dir,
            self.database_path.parent,
            self.debug_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)

    def write(self, path: Path | None = None, *, overwrite: bool = False) -> Path:
        config_path = path or (self.data_dir / "config.json")
        if config_path.exists() and not overwrite:
            raise FileExistsError(f"配置已存在: {config_path}")
        config_path.parent.mkdir(parents=True, exist_ok=True)
        payload = asdict(self)
        for key, value in payload.items():
            if isinstance(value, Path):
                payload[key] = str(value)
        config_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return config_path
