import json

import pytest

from literature_helper.config import AppConfig, default_home


def test_config_roundtrip(tmp_path):
    config = AppConfig.defaults(tmp_path / "app")
    path = config.write()
    loaded = AppConfig.load(path)
    assert loaded.data_dir == config.data_dir
    assert loaded.headless is True
    assert loaded.poll_interval_seconds == 3.0
    assert loaded.download_dir == config.download_dir
    assert loaded.prefer_high_speed_download is True
    assert loaded.download_timeout_seconds == 180.0
    assert loaded.auto_accept_after_validation is False
    assert loaded.auto_accept_historical_pending is True


def test_poll_rate_limit(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(
        json.dumps({"poll_interval_seconds": 1}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="不能小于 3 秒"):
        AppConfig.load(path)


def test_rejects_non_ablesci_assist_url(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(
        json.dumps({"assist_url": "https://example.com/assist"}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="ablesci"):
        AppConfig.load(path)


def test_home_environment_variable_sets_data_directory(tmp_path, monkeypatch):
    monkeypatch.setenv("LITHELPER_HOME", str(tmp_path / "literature"))

    assert default_home() == (tmp_path / "literature").resolve()
