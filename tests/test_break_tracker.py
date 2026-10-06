from datetime import datetime, timedelta
import json
import pytest

from core import AppConfig, BreakState, BreakTracker, ConfigStore


def test_app_config_break_defaults():
    config = AppConfig()
    assert config.break_reminder_enabled is False
    assert config.work_duration_minutes == 50
    assert config.break_duration_minutes == 10
    assert config.break_snooze_minutes == 5
    assert config.break_alert_mode == "notification"
    assert config.break_violation_threshold_seconds == 15
    assert config.break_alert_cooldown_seconds == 60


def test_break_tracker_transitions():
    config = AppConfig(break_reminder_enabled=True, work_duration_minutes=50, break_duration_minutes=10)
    start_time = datetime(2026, 10, 6, 10, 0, 0)
    tracker = BreakTracker(config, now=start_time)

    assert tracker.state == BreakState.WORKING
    assert tracker.remaining_seconds(start_time) == 50 * 60

    # 50 dakika sonra mola başlamalı
    break_time = start_time + timedelta(minutes=50, seconds=1)
    tracker.tick(now=break_time, idle_seconds=30.0)
    assert tracker.state == BreakState.ON_BREAK
    assert tracker.is_nudge_allowed() is False

    # Mola sırasında hareket olursa (idle < 15 sn) VIOLATION olmalı
    tracker.tick(now=break_time + timedelta(seconds=10), idle_seconds=2.0)
    assert tracker.state == BreakState.BREAK_VIOLATION


def test_break_tracker_disabled_by_default():
    config = AppConfig()
    start_time = datetime(2026, 10, 6, 10, 0, 0)
    tracker = BreakTracker(config, now=start_time)

    assert tracker.state == BreakState.DISABLED
    assert tracker.is_nudge_allowed() is True
    assert tracker.remaining_seconds(start_time) == 0

    # Tick should not change disabled state
    tracker.tick(now=start_time + timedelta(minutes=60), idle_seconds=0.0)
    assert tracker.state == BreakState.DISABLED


def test_break_tracker_violation_recovery():
    config = AppConfig(break_reminder_enabled=True, work_duration_minutes=50, break_duration_minutes=10)
    start_time = datetime(2026, 10, 6, 10, 0, 0)
    tracker = BreakTracker(config, now=start_time)

    # Enter break
    break_time = start_time + timedelta(minutes=50, seconds=1)
    tracker.tick(now=break_time, idle_seconds=20.0)
    assert tracker.state == BreakState.ON_BREAK

    # Move mouse -> violation
    tracker.tick(now=break_time + timedelta(seconds=5), idle_seconds=1.0)
    assert tracker.state == BreakState.BREAK_VIOLATION
    assert tracker.is_nudge_allowed() is False

    # Step away from computer -> user is idle >= 15s again
    tracker.tick(now=break_time + timedelta(seconds=20), idle_seconds=20.0)
    assert tracker.state == BreakState.ON_BREAK
    assert tracker.is_nudge_allowed() is False


def test_break_tracker_break_completion():
    config = AppConfig(break_reminder_enabled=True, work_duration_minutes=50, break_duration_minutes=10)
    start_time = datetime(2026, 10, 6, 10, 0, 0)
    tracker = BreakTracker(config, now=start_time)

    break_time = start_time + timedelta(minutes=50, seconds=1)
    tracker.tick(now=break_time, idle_seconds=30.0)
    assert tracker.state == BreakState.ON_BREAK

    # Break finishes after 10 minutes
    work_resume_time = break_time + timedelta(minutes=10, seconds=1)
    tracker.tick(now=work_resume_time, idle_seconds=30.0)
    assert tracker.state == BreakState.WORKING
    assert tracker.is_nudge_allowed() is True


def test_break_tracker_start_break_now():
    config = AppConfig(break_reminder_enabled=True, work_duration_minutes=50, break_duration_minutes=10)
    start_time = datetime(2026, 10, 6, 10, 0, 0)
    tracker = BreakTracker(config, now=start_time)

    assert tracker.state == BreakState.WORKING
    now_5m = start_time + timedelta(minutes=5)
    tracker.start_break_now(now=now_5m)

    assert tracker.state == BreakState.ON_BREAK
    assert tracker.is_nudge_allowed() is False
    assert tracker.remaining_seconds(now_5m) == 10 * 60


def test_break_tracker_snooze():
    config = AppConfig(break_reminder_enabled=True, work_duration_minutes=50, break_duration_minutes=10, break_snooze_minutes=12)
    start_time = datetime(2026, 10, 6, 10, 0, 0)
    tracker = BreakTracker(config, now=start_time)

    # Snooze without explicit minutes uses config.break_snooze_minutes (12m)
    tracker.snooze(now=start_time)
    assert tracker.remaining_seconds(start_time) == 62 * 60

    # Snooze during working extends target time by specified minutes
    tracker.snooze(minutes=5, now=start_time)
    assert tracker.remaining_seconds(start_time) == 67 * 60

    # Start break then snooze -> transitions to working for break_snooze_minutes (12m)
    break_time = start_time + timedelta(minutes=67, seconds=1)
    tracker.tick(now=break_time, idle_seconds=30.0)
    assert tracker.state == BreakState.ON_BREAK

    tracker.snooze(now=break_time)
    assert tracker.state == BreakState.WORKING
    assert tracker.is_nudge_allowed() is True
    assert tracker.remaining_seconds(break_time) == 12 * 60


def test_break_tracker_toggle_pause():
    config = AppConfig(break_reminder_enabled=True, work_duration_minutes=50, break_duration_minutes=10)
    start_time = datetime(2026, 10, 6, 10, 0, 0)
    tracker = BreakTracker(config, now=start_time)

    now_10m = start_time + timedelta(minutes=10)
    # Remaining was 40m
    assert tracker.remaining_seconds(now_10m) == 40 * 60

    # Pause
    was_paused = tracker.toggle_pause(now=now_10m)
    assert was_paused is True
    assert tracker.state == BreakState.PAUSED
    assert tracker.is_nudge_allowed() is True
    assert tracker.remaining_seconds(now_10m) == 40 * 60

    # Time passes while paused (30 minutes in real life)
    now_40m = now_10m + timedelta(minutes=30)
    tracker.tick(now=now_40m, idle_seconds=0.0)
    assert tracker.state == BreakState.PAUSED
    assert tracker.remaining_seconds(now_40m) == 40 * 60

    # Unpause
    was_paused = tracker.toggle_pause(now=now_40m)
    assert was_paused is False
    assert tracker.state == BreakState.WORKING
    assert tracker.remaining_seconds(now_40m) == 40 * 60


def test_break_tracker_status_text():
    config = AppConfig(break_reminder_enabled=True, work_duration_minutes=50, break_duration_minutes=10)
    start_time = datetime(2026, 10, 6, 10, 0, 0)
    tracker = BreakTracker(config, now=start_time)

    assert "Odaklanma: 50:00 kaldı" in tracker.status_text(now=start_time)

    # In break
    break_time = start_time + timedelta(minutes=50, seconds=1)
    tracker.tick(now=break_time, idle_seconds=30.0)
    assert "Mola Vakti: 10:00 kaldı (Masadan Kalk!)" in tracker.status_text(now=break_time)

    # Violation
    tracker.tick(now=break_time + timedelta(seconds=10), idle_seconds=2.0)
    assert "Masadan Kalk!" in tracker.status_text(now=break_time + timedelta(seconds=10))

    # Paused
    tracker.toggle_pause(now=break_time + timedelta(seconds=10))
    assert "Duraklatıldı" in tracker.status_text()

    # Disabled
    disabled_tracker = BreakTracker(AppConfig(break_reminder_enabled=False))
    assert "Devre Dışı" in disabled_tracker.status_text()


def test_break_tracker_alert_cooldown():
    config = AppConfig(
        break_reminder_enabled=True,
        work_duration_minutes=50,
        break_duration_minutes=10,
        break_alert_cooldown_seconds=60,
    )
    start_time = datetime(2026, 10, 6, 10, 0, 0)
    tracker = BreakTracker(config, now=start_time)

    # Before break, should_alert is False
    assert tracker.should_alert(start_time) is False

    # Enter break & violate
    break_time = start_time + timedelta(minutes=50, seconds=1)
    tracker.tick(now=break_time, idle_seconds=1.0)
    assert tracker.state == BreakState.BREAK_VIOLATION
    assert tracker.should_alert(break_time) is True

    # Record alert
    tracker.record_alert(break_time)
    # Next check 30s later (within cooldown) -> False
    assert tracker.should_alert(break_time + timedelta(seconds=30)) is False
    # Next check 61s later (cooldown passed) -> True
    assert tracker.should_alert(break_time + timedelta(seconds=61)) is True


def test_config_store_legacy_compatibility(tmp_path, monkeypatch):
    monkeypatch.delenv("APPDATA", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    store = ConfigStore()
    store.dir.mkdir(parents=True, exist_ok=True)
    # Write legacy json without any UpNow fields
    legacy_json = {
        "enabled": True,
        "idle_minutes": 4,
        "start_time": "08:30",
        "end_time": "17:30",
    }
    store.path.write_text(json.dumps(legacy_json), encoding="utf-8")

    loaded = store.load()
    assert loaded.break_reminder_enabled is False
    assert loaded.work_duration_minutes == 50
    assert loaded.break_duration_minutes == 10
    assert loaded.break_alert_mode == "notification"
    assert loaded.break_violation_threshold_seconds == 15
    assert loaded.break_alert_cooldown_seconds == 60
