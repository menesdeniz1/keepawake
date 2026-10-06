import sys
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("PySide6")
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from core import APP_NAME, AppConfig, BreakState


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

    import app as ka

    ctrl = ka.KeepAwakeController(qapp)
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
    if hasattr(ctrl, "nag_dialog") and ctrl.nag_dialog is not None:
        ctrl.nag_dialog.hide()


def test_break_nag_dialog_properties(controller):
    import app as ka

    assert hasattr(ka, "BreakNagDialog"), "BreakNagDialog should be defined in app.py"
    dialog = ka.BreakNagDialog(controller)
    try:
        assert isinstance(dialog, QDialog)
        flags = dialog.windowFlags()
        assert bool(flags & Qt.WindowType.WindowStaysOnTopHint)
        assert f"{APP_NAME} - Mola Zamanı" in dialog.windowTitle()
        assert "Lütfen Masadan Uzaklaşın!" in dialog.headline_label.text()
        assert hasattr(dialog, "countdown_label")

        dialog.update_status("07:42")
        assert "07:42" in dialog.countdown_label.text()
    finally:
        dialog.hide()


def test_break_nag_dialog_buttons(controller, monkeypatch):
    import app as ka

    dialog = ka.BreakNagDialog(controller)
    dialog.show()
    assert dialog.isVisible()

    snooze_spy = MagicMock()
    monkeypatch.setattr(controller, "snooze_break", snooze_spy)

    dialog.snooze_btn.click()
    snooze_spy.assert_called_once_with(5)
    assert not dialog.isVisible()

    dialog.show()
    assert dialog.isVisible()

    finish_spy = MagicMock()
    monkeypatch.setattr(controller, "start_work_now", finish_spy)

    dialog.finish_btn.click()
    finish_spy.assert_called_once()
    assert not dialog.isVisible()


def test_settings_window_upnow_fields(controller):
    win = controller.window

    assert hasattr(win, "break_enabled_check")
    assert hasattr(win, "work_duration_spin")
    assert hasattr(win, "break_duration_spin")
    assert hasattr(win, "break_alert_combo")

    assert win.work_duration_spin.minimum() == 1
    assert win.work_duration_spin.maximum() == 180
    assert "dk" in win.work_duration_spin.suffix()

    assert win.break_duration_spin.minimum() == 1
    assert win.break_duration_spin.maximum() == 60
    assert "dk" in win.break_duration_spin.suffix()

    combo_items = [
        win.break_alert_combo.itemText(i)
        for i in range(win.break_alert_combo.count())
    ]
    assert "Nazik Bildirim (Sistem)" in combo_items
    assert "Zorlayıcı Mod (Uyarı Penceresi)" in combo_items


def test_settings_window_load_and_save(controller, monkeypatch):
    win = controller.window

    # Test load_from_config
    controller.config.break_reminder_enabled = True
    controller.config.work_duration_minutes = 45
    controller.config.break_duration_minutes = 15
    controller.config.break_alert_mode = "nagging"

    win.load_from_config()

    assert win.break_enabled_check.isChecked() is True
    assert win.work_duration_spin.value() == 45
    assert win.break_duration_spin.value() == 15
    assert win.break_alert_combo.currentIndex() == 1

    # Test save_from_window
    win.break_enabled_check.setChecked(False)
    win.work_duration_spin.setValue(25)
    win.break_duration_spin.setValue(5)
    win.break_alert_combo.setCurrentIndex(0)

    assert hasattr(win, "save_from_window"), "SettingsWindow should implement save_from_window"
    win.save_from_window()

    assert controller.config.break_reminder_enabled is False
    assert controller.config.work_duration_minutes == 25
    assert controller.config.break_duration_minutes == 5
    assert controller.config.break_alert_mode == "notification"

    # Test saving via full save() method
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **kw: QMessageBox.StandardButton.Ok)
    save_store_spy = MagicMock()
    monkeypatch.setattr(controller.store, "save", save_store_spy)

    win.break_enabled_check.setChecked(True)
    win.work_duration_spin.setValue(50)
    win.save()

    assert controller.config.break_reminder_enabled is True
    assert controller.config.work_duration_minutes == 50
    save_store_spy.assert_called_once()


def test_tray_menu_actions(controller):
    actions = {action.text(): action for action in controller.menu.actions()}

    assert "Mola Takipçisi (UpNow)" in actions
    upnow_action = actions["Mola Takipçisi (UpNow)"]
    assert upnow_action.isCheckable()

    assert "Molayı Şimdi Başlat" in actions
    assert "5 Dakika Ertele" in actions
    assert "Mola Takibini Duraklat / Devam Ettir" in actions


def test_controller_break_action_triggers(controller, monkeypatch):
    controller.config.break_reminder_enabled = True
    controller.break_tracker.update_config(controller.config)

    # 1. Start break now
    controller.start_break_now()
    assert controller.break_tracker.state == BreakState.ON_BREAK

    # 2. Snooze break
    controller.snooze_break(5)
    assert controller.break_tracker.state == BreakState.WORKING

    # 3. Toggle break pause
    controller.toggle_break_pause()
    assert controller.break_tracker.state == BreakState.PAUSED
    controller.toggle_break_pause()
    assert controller.break_tracker.state == BreakState.WORKING

    # 4. Start work now
    controller.start_break_now()
    assert controller.break_tracker.state == BreakState.ON_BREAK
    controller.start_work_now()
    assert controller.break_tracker.state == BreakState.WORKING

    # 5. Toggle break reminder from tray
    controller.set_break_reminder_enabled_from_tray(False)
    assert controller.config.break_reminder_enabled is False
    assert controller.break_tracker.state == BreakState.DISABLED
    controller.set_break_reminder_enabled_from_tray(True)
    assert controller.config.break_reminder_enabled is True


def test_trigger_break_alert_modes(controller, monkeypatch):
    # Mode: nagging -> shows nag_dialog
    controller.config.break_alert_mode = "nagging"
    controller.nag_dialog.hide()
    assert not controller.nag_dialog.isVisible()

    controller.trigger_break_alert()
    assert controller.nag_dialog.isVisible()
    controller.nag_dialog.hide()

    # Mode: notification -> calls tray.showMessage
    controller.config.break_alert_mode = "notification"
    show_message_spy = MagicMock()
    monkeypatch.setattr(controller.tray, "showMessage", show_message_spy)

    controller.trigger_break_alert()
    assert not controller.nag_dialog.isVisible()
    show_message_spy.assert_called_once()


def test_tick_updates_nag_dialog(controller):
    controller.config.break_reminder_enabled = True
    controller.config.break_alert_mode = "nagging"
    controller.apply_config()

    controller.start_break_now()
    controller.trigger_break_alert()
    assert controller.nag_dialog.isVisible()

    controller.tick()
    assert controller.nag_dialog.isVisible()
    assert ":" in controller.nag_dialog.countdown_label.text()

    # When transitioning to working, tick hides the dialog
    controller.start_work_now()
    assert not controller.nag_dialog.isVisible()

