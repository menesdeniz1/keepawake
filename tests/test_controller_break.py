import sys
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("PySide6")
from PySide6.QtWidgets import QApplication

from core import AppConfig, BreakState, BreakTracker


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication(sys.argv)


@pytest.fixture
def controller(qapp, tmp_path, monkeypatch):
    monkeypatch.delenv("APPDATA", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setattr("app.is_startup_enabled", lambda: False)
    monkeypatch.setattr("app.set_startup_enabled", lambda val: None)
    monkeypatch.setattr("app.set_execution_state", lambda *a, **kw: True)
    monkeypatch.setattr("app.clear_execution_state", lambda: None)
    monkeypatch.setattr("app.nudge_mouse", lambda: True)
    monkeypatch.setattr("app.get_idle_seconds", lambda: 60.0)

    import app as ka

    ctrl = ka.KeepAwakeController(qapp)
    # Stop timer and auto update to keep test synchronous and hermetic
    ctrl.timer.stop()
    ctrl.cooldown_until = None
    ctrl.last_nudge_at = None
    ctrl.config.auto_check_updates = False
    ctrl.config.start_time = "00:00"
    ctrl.config.end_time = "23:59"
    ctrl.config.days = [
        "monday", "tuesday", "wednesday", "thursday",
        "friday", "saturday", "sunday",
    ]
    yield ctrl
    ctrl.tray.hide()


def test_controller_has_break_tracker(controller):
    assert hasattr(controller, "break_tracker")
    assert isinstance(controller.break_tracker, BreakTracker)


def test_controller_suppresses_nudge_during_break(controller, monkeypatch):
    controller.config.enabled = True
    controller.config.simulate_mouse_input = True
    controller.config.idle_minutes = 1
    controller.config.break_reminder_enabled = True
    controller.break_tracker.update_config(controller.config)

    # Force tracker into ON_BREAK
    start_time = datetime.now()
    controller.break_tracker.start_break_now(now=start_time)
    assert controller.break_tracker.state == BreakState.ON_BREAK
    assert controller.break_tracker.is_nudge_allowed() is False

    mock_nudge = MagicMock(return_value=True)
    monkeypatch.setattr("app.nudge_mouse", mock_nudge)
    monkeypatch.setattr("app.get_idle_seconds", lambda: 120.0)  # Over idle threshold

    controller.tick()

    mock_nudge.assert_not_called()


def test_controller_suppresses_nudge_during_break_violation(controller, monkeypatch):
    controller.config.enabled = True
    controller.config.simulate_mouse_input = True
    controller.config.idle_minutes = 1
    controller.config.break_reminder_enabled = True
    controller.break_tracker.update_config(controller.config)

    start_time = datetime.now()
    controller.break_tracker.start_break_now(now=start_time)
    # Trigger violation via movement (idle_seconds = 2.0 < threshold)
    controller.break_tracker.tick(now=start_time, idle_seconds=2.0)
    assert controller.break_tracker.state == BreakState.BREAK_VIOLATION
    assert controller.break_tracker.is_nudge_allowed() is False

    mock_nudge = MagicMock(return_value=True)
    monkeypatch.setattr("app.nudge_mouse", mock_nudge)
    monkeypatch.setattr("app.get_idle_seconds", lambda: 120.0)

    controller.tick()

    mock_nudge.assert_not_called()


def test_controller_allows_nudge_during_working(controller, monkeypatch):
    controller.config.enabled = True
    controller.config.simulate_mouse_input = True
    controller.config.idle_minutes = 1
    controller.config.break_reminder_enabled = True
    controller.cooldown_until = None
    now = datetime.now()
    controller.break_tracker.reset(now=now)
    assert controller.break_tracker.state == BreakState.WORKING
    assert controller.break_tracker.is_nudge_allowed() is True

    mock_nudge = MagicMock(return_value=True)
    monkeypatch.setattr("app.nudge_mouse", mock_nudge)
    monkeypatch.setattr("app.get_idle_seconds", lambda: 120.0)

    controller.tick()

    mock_nudge.assert_called_once()


def test_controller_break_tracker_apply_config(controller):
    assert controller.break_tracker.config.break_reminder_enabled is False

    controller.config.break_reminder_enabled = True
    controller.config.work_duration_minutes = 25
    controller.config.break_duration_minutes = 5
    controller.apply_config()

    assert controller.break_tracker.config.break_reminder_enabled is True
    assert controller.break_tracker.state == BreakState.WORKING
    assert controller.break_tracker.config.work_duration_minutes == 25


def test_controller_triggers_break_alert_on_violation(controller, monkeypatch):
    controller.config.enabled = True
    controller.config.break_reminder_enabled = True
    controller.break_tracker.update_config(controller.config)

    start_time = datetime.now()
    controller.break_tracker.start_break_now(now=start_time)

    # Idle = 2s triggers violation
    monkeypatch.setattr("app.get_idle_seconds", lambda: 2.0)
    mock_alert = MagicMock()
    monkeypatch.setattr(controller, "trigger_break_alert", mock_alert)

    # First tick -> alert should be triggered
    controller.tick()
    assert controller.break_tracker.state == BreakState.BREAK_VIOLATION
    mock_alert.assert_called_once()

    # Second tick immediately -> alert should NOT be triggered due to cooldown
    mock_alert.reset_mock()
    controller.tick()
    mock_alert.assert_not_called()


def test_controller_status_text_includes_break_info(controller, monkeypatch):
    # Disabled break reminder -> no break info in status text
    controller.config.enabled = True
    controller.config.break_reminder_enabled = False
    controller.apply_config()
    status_disabled = controller.status_text()
    assert "Odaklanma" not in status_disabled
    assert "Mola:" not in status_disabled

    # Enabled break reminder -> includes focus countdown
    controller.config.break_reminder_enabled = True
    controller.apply_config()
    status_working = controller.status_text()
    assert "Odaklanma" in status_working

    # Break active -> includes break countdown and pause note on mouse nudge
    start_time = datetime.now()
    controller.break_tracker.start_break_now(now=start_time)
    status_break = controller.status_text(now=start_time)
    assert "Mola: 10:00 kaldı (Masadan Kalk!)" in status_break
    assert "mouse nudge duraklatıldı (mola)" in status_break


def test_controller_keepawake_status_text_never_includes_break_info(controller):
    controller.config.enabled = True
    controller.config.break_reminder_enabled = True
    controller.apply_config()

    # Even when break tracker is enabled and working, keepawake_status_text excludes it
    ka_status = controller.keepawake_status_text()
    assert "Odaklanma" not in ka_status
    assert "Mola:" not in ka_status

    # Global status_text still includes it for tray tooltip
    global_status = controller.status_text()
    assert "Odaklanma" in global_status

