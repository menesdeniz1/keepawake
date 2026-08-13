from datetime import datetime
from pathlib import Path

import core


def test_schedule_same_day_active():
    cfg = core.AppConfig(days=["monday"], start_time="08:30", end_time="17:30")
    assert core.is_inside_schedule(cfg, datetime(2026, 8, 10, 10, 0)) is True


def test_schedule_same_day_before_start():
    cfg = core.AppConfig(days=["monday"], start_time="08:30", end_time="17:30")
    assert core.is_inside_schedule(cfg, datetime(2026, 8, 10, 7, 0)) is False


def test_schedule_wrong_day():
    cfg = core.AppConfig(days=["monday"], start_time="08:30", end_time="17:30")
    assert core.is_inside_schedule(cfg, datetime(2026, 8, 11, 10, 0)) is False


def test_schedule_overnight_start_day():
    cfg = core.AppConfig(days=["friday"], start_time="22:00", end_time="02:00")
    assert core.is_inside_schedule(cfg, datetime(2026, 8, 14, 23, 0)) is True


def test_schedule_overnight_next_day():
    cfg = core.AppConfig(days=["friday"], start_time="22:00", end_time="02:00")
    assert core.is_inside_schedule(cfg, datetime(2026, 8, 15, 1, 0)) is True


def test_schedule_overnight_after_end():
    cfg = core.AppConfig(days=["friday"], start_time="22:00", end_time="02:00")
    assert core.is_inside_schedule(cfg, datetime(2026, 8, 15, 3, 0)) is False


def test_schedule_no_days_selected():
    cfg = core.AppConfig(days=[])
    assert core.is_inside_schedule(cfg, datetime(2026, 8, 10, 10, 0)) is False


def test_format_duration_seconds():
    assert core.format_duration(5) == "5 sn"


def test_format_duration_minutes():
    assert core.format_duration(65) == "1 dk 5 sn"


def test_format_duration_hours():
    assert core.format_duration(3665) == "1 sa 1 dk"


def test_format_duration_negative_clamped():
    assert core.format_duration(-5) == "0 sn"


def test_parse_version():
    assert core.parse_version("1.2.10") == (1, 2, 10)


def test_is_newer_true():
    assert core.is_newer("1.3.0", "1.2.0") is True


def test_is_newer_equal():
    assert core.is_newer("1.2.0", "1.2.0") is False


def test_is_newer_older():
    assert core.is_newer("1.1.9", "1.2.0") is False


def test_config_store_linux_path(monkeypatch):
    monkeypatch.delenv("APPDATA", raising=False)
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    store = core.ConfigStore()
    assert store.dir == Path.home() / ".config" / "KeepAwake"


def test_config_store_xdg_path(monkeypatch, tmp_path):
    monkeypatch.delenv("APPDATA", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    store = core.ConfigStore()
    assert store.dir == tmp_path / "KeepAwake"


def test_config_store_windows_path(monkeypatch, tmp_path):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    store = core.ConfigStore()
    assert store.dir == tmp_path / "KeepAwake"


def test_config_store_round_trip(monkeypatch, tmp_path):
    monkeypatch.delenv("APPDATA", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    store = core.ConfigStore()
    cfg = core.AppConfig(idle_minutes=7, days=["tuesday", "wednesday"])
    store.save(cfg)
    loaded = store.load()
    assert loaded.idle_minutes == 7
    assert loaded.days == ["tuesday", "wednesday"]


def test_config_store_load_missing_returns_defaults(monkeypatch, tmp_path):
    monkeypatch.delenv("APPDATA", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    store = core.ConfigStore()
    assert store.load() == core.AppConfig()


def test_config_store_load_corrupt_falls_back(monkeypatch, tmp_path):
    monkeypatch.delenv("APPDATA", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    store = core.ConfigStore()
    store.dir.mkdir(parents=True, exist_ok=True)
    store.path.write_text("{ bozuk json", encoding="utf-8")
    assert store.load() == core.AppConfig()
