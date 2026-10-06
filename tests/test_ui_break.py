import sys
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("PySide6")
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox, QPushButton

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
    monkeypatch.setattr("app.get_idle_seconds", lambda: 60.0)

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
        assert "UpNow - Mola Vakti" in dialog.windowTitle()
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
    assert hasattr(win, "break_snooze_spin")
    assert hasattr(win, "break_alert_combo")

    assert hasattr(win, "tabs")
    assert win.tabs.count() == 3
    assert "Genel Bakış" in win.tabs.tabText(0)
    assert "KeepAwake" in win.tabs.tabText(1)
    assert "UpNow" in win.tabs.tabText(2)
    assert hasattr(win, "status_label")
    assert hasattr(win, "upnow_status_label")
    assert hasattr(win, "dash_ka_status")
    assert hasattr(win, "dash_upnow_status")
    assert hasattr(win, "dash_start_break_btn")
    assert hasattr(win, "dash_snooze_btn")
    assert hasattr(win, "dash_ka_toggle_btn")
    assert hasattr(win, "dash_upnow_toggle_btn")
    assert win.dash_upnow_box.title() == "UpNow - Mola Takipçisi"
    assert not hasattr(win, "dash_to_ka_btn")
    assert not hasattr(win, "dash_to_upnow_btn")
    assert hasattr(win, "tab_start_break_btn")
    assert hasattr(win, "tab_snooze_btn")
    assert hasattr(win, "save_button")
    assert hasattr(win, "hide_button")


def test_settings_window_dashboard_status_separation(controller):
    win = controller.window
    controller.config.enabled = True
    controller.config.break_reminder_enabled = True
    controller.apply_config()
    win.refresh_status()

    # KeepAwake status must NOT contain 'Odaklanma'
    assert "Odaklanma" not in win.dash_ka_status.text()
    assert "Odaklanma" not in win.status_label.text()

    # UpNow status must contain 'Odaklanma' during working phase
    assert "Odaklanma" in win.dash_upnow_status.text()
    assert "Odaklanma" in win.upnow_status_label.text()

    # When disabled, both must show identical '⚪ Devre dışı'
    controller.config.enabled = False
    controller.config.break_reminder_enabled = False
    controller.apply_config()
    win.refresh_status()

    assert win.dash_ka_status.text() == "⚪ Devre dışı"
    assert win.status_label.text() == "⚪ Devre dışı"
    assert win.dash_upnow_status.text() == "⚪ Devre dışı"
    assert win.upnow_status_label.text() == "⚪ Devre dışı"


def test_settings_window_load_and_save(controller, monkeypatch):
    win = controller.window

    # Test load_from_config
    controller.config.break_reminder_enabled = True
    controller.config.work_duration_minutes = 45
    controller.config.break_duration_minutes = 15
    controller.config.break_snooze_minutes = 10
    controller.config.break_alert_mode = "nagging"

    win.load_from_config()

    assert win.break_enabled_check.isChecked() is True
    assert win.work_duration_spin.value() == 45
    assert win.break_duration_spin.value() == 15
    assert win.break_snooze_spin.value() == 10
    assert win.break_alert_combo.currentIndex() == 1

    # Test save_from_window
    win.break_enabled_check.setChecked(False)
    win.work_duration_spin.setValue(25)
    win.break_duration_spin.setValue(5)
    win.break_snooze_spin.setValue(8)
    win.break_alert_combo.setCurrentIndex(0)

    assert hasattr(win, "save_from_window"), "SettingsWindow should implement save_from_window"
    win.save_from_window()

    assert controller.config.break_reminder_enabled is False
    assert controller.config.work_duration_minutes == 25
    assert controller.config.break_duration_minutes == 5
    assert controller.config.break_snooze_minutes == 8
    assert controller.config.break_alert_mode == "notification"

    # Test saving via full save() method
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **kw: QMessageBox.StandardButton.Ok)
    save_store_spy = MagicMock()
    monkeypatch.setattr(controller.store, "save", save_store_spy)

    win.break_enabled_check.setChecked(True)
    win.work_duration_spin.setValue(50)
    win.break_snooze_spin.setValue(12)
    win.save()

    assert controller.config.break_reminder_enabled is True
    assert controller.config.work_duration_minutes == 50
    assert controller.config.break_snooze_minutes == 12
    save_store_spy.assert_called_once()


def test_dynamic_snooze_duration_and_button_texts(controller):
    win = controller.window
    controller.config.break_reminder_enabled = True
    controller.config.break_snooze_minutes = 15
    controller.apply_config()
    win.load_from_config()

    assert win.break_snooze_spin.value() == 15
    assert win.dash_snooze_btn.text() == "15 Dakika Ertele"
    assert win.tab_snooze_btn.text() == "15 Dakika Ertele"
    assert controller.snooze_break_action.text() == "15 Dakika Ertele"
    assert controller.nag_dialog.snooze_btn.text() == "15 Dakika Ertele"

    # User changes spinbox value live -> button labels update
    win.break_snooze_spin.setValue(8)
    assert win.dash_snooze_btn.text() == "8 Dakika Ertele"
    assert win.tab_snooze_btn.text() == "8 Dakika Ertele"

    # Clicking snooze button triggers snooze
    controller.break_tracker.start_break_now()
    assert controller.break_tracker.state == BreakState.ON_BREAK
    win.dash_snooze_btn.click()
    assert controller.break_tracker.state == BreakState.WORKING


def test_start_finish_break_button_toggle(controller):
    win = controller.window
    controller.config.break_reminder_enabled = True
    controller.apply_config()
    win.refresh_status()

    # Initially working: text says "Molayı Şimdi Başlat"
    assert win.dash_start_break_btn.text() == "Molayı Şimdi Başlat"
    assert win.tab_start_break_btn.text() == "Molayı Şimdi Başlat"
    assert controller.start_break_action.text() == "Molayı Şimdi Başlat"

    # Click button -> starts break, text toggles to "Molayı Şimdi Bitir"
    win.dash_start_break_btn.click()
    assert controller.break_tracker.state == BreakState.ON_BREAK
    assert win.dash_start_break_btn.text() == "Molayı Şimdi Bitir"
    assert win.tab_start_break_btn.text() == "Molayı Şimdi Bitir"
    assert controller.start_break_action.text() == "Molayı Şimdi Bitir"

    # Click button again -> finishes break, transitions to WORKING, text toggles back
    win.tab_start_break_btn.click()
    assert controller.break_tracker.state == BreakState.WORKING
    assert win.dash_start_break_btn.text() == "Molayı Şimdi Başlat"
    assert win.tab_start_break_btn.text() == "Molayı Şimdi Başlat"
    assert controller.start_break_action.text() == "Molayı Şimdi Başlat"


def test_dashboard_toggle_buttons(controller):
    win = controller.window

    # 1. KeepAwake toggle button
    controller.config.enabled = True
    controller.apply_config()
    win.refresh_status()

    assert win.dash_ka_toggle_btn.text() == "Durdur"
    win.dash_ka_toggle_btn.click()
    assert controller.config.enabled is False
    assert win.dash_ka_toggle_btn.text() == "Başlat"
    assert win.dash_ka_status.text() == "⚪ Devre dışı"

    win.dash_ka_toggle_btn.click()
    assert controller.config.enabled is True
    assert win.dash_ka_toggle_btn.text() == "Durdur"

    # 2. UpNow toggle button
    controller.config.break_reminder_enabled = True
    controller.apply_config()
    win.refresh_status()

    # Verify button order: Durdur/Başlat is first (leftmost)
    upnow_buttons = win.dash_upnow_box.findChildren(QPushButton)
    assert upnow_buttons == [win.dash_upnow_toggle_btn, win.dash_start_break_btn, win.dash_snooze_btn]

    assert win.dash_upnow_toggle_btn.text() == "Durdur"
    assert win.dash_start_break_btn.isEnabled() is True
    assert win.dash_snooze_btn.isEnabled() is True

    win.dash_upnow_toggle_btn.click()
    assert controller.config.break_reminder_enabled is False
    assert win.dash_upnow_toggle_btn.text() == "Başlat"
    assert win.dash_upnow_status.text() == "⚪ Devre dışı"
    assert win.dash_start_break_btn.isEnabled() is False
    assert win.dash_snooze_btn.isEnabled() is False

    win.dash_upnow_toggle_btn.click()
    assert controller.config.break_reminder_enabled is True
    assert win.dash_upnow_toggle_btn.text() == "Durdur"
    assert win.dash_start_break_btn.isEnabled() is True
    assert win.dash_snooze_btn.isEnabled() is True




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
    # Mode: nagging -> shows/raises nag_dialog
    controller.config.break_alert_mode = "nagging"
    controller.nag_dialog.hide()
    assert not controller.nag_dialog.isVisible()

    controller.trigger_break_alert()
    assert controller.nag_dialog.isVisible()
    controller.nag_dialog.hide()

    # Mode: notification -> Nazik mod: violation triggers do NOT spam toasts during break
    controller.config.break_alert_mode = "notification"
    controller.toast_notification.hide()
    controller.trigger_break_alert()
    assert not controller.nag_dialog.isVisible()
    assert not controller.toast_notification.isVisible()


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


def test_break_toast_notification_properties(controller):
    toast = controller.toast_notification
    assert hasattr(toast, "title_label")
    assert hasattr(toast, "msg_label")
    assert hasattr(toast, "snooze_btn")
    assert hasattr(toast, "dismiss_btn")

    toast.show_toast("Test Title", "Test Message")
    assert toast.isVisible()
    assert toast.title_label.text() == "Test Title"
    assert toast.msg_label.text() == "Test Message"

    # Clicking dismiss hides toast
    toast.dismiss_btn.click()
    assert not toast.isVisible()

    # Clicking snooze calls controller.snooze_break
    toast.show_toast("Test Title", "Test Message")
    assert toast.isVisible()
    toast.snooze_btn.click()
    assert not toast.isVisible()


def test_notification_mode_shows_toast_on_break_started(controller):
    controller.config.break_alert_mode = "notification"
    controller.toast_notification.hide()
    assert not controller.toast_notification.isVisible()

    controller.notify_break_started()
    assert controller.toast_notification.isVisible()
    assert "Mola Vakti" in controller.toast_notification.title_label.text()
    assert "Mola İhlali" not in controller.toast_notification.title_label.text()
    controller.toast_notification.hide()


def test_toast_snooze_actions_extend_work_and_break(controller):
    controller.config.break_reminder_enabled = True
    controller.config.break_alert_mode = "notification"
    controller.config.break_snooze_minutes = 5
    controller.apply_config()

    # 1. Molaya girerken (Break started) -> 'Molayı Ertele' ve 'Tamam' (2 şık)
    controller.notify_break_started()
    assert controller.toast_notification.isVisible()
    assert controller.toast_notification.snooze_btn.isVisible()
    assert "Molayı Ertele" in controller.toast_notification.snooze_btn.text()
    assert controller.toast_notification.dismiss_btn.isVisible()
    assert controller.toast_notification.dismiss_btn.text() == "Tamam"

    controller.toast_notification.snooze_btn.click()
    # Working state extended, nudge allowed
    assert controller.break_tracker.state == BreakState.WORKING
    assert controller.break_tracker.is_nudge_allowed() is True
    # Toast switched to feedback (without snooze button)
    assert "Mola Ertelendi" in controller.toast_notification.title_label.text()
    assert not controller.toast_notification.snooze_btn.isVisible()

    controller.toast_notification.hide()

    # 2. Mola bitince (Break finished) -> 'Molayı Uzat' ve 'Tamam' (2 şık)
    controller.notify_break_finished()
    assert controller.toast_notification.isVisible()
    assert "Mola Tamamlandı" in controller.toast_notification.title_label.text()
    assert controller.toast_notification.snooze_btn.isVisible()
    assert "Molayı Uzat" in controller.toast_notification.snooze_btn.text()
    assert controller.toast_notification.dismiss_btn.isVisible()
    assert controller.toast_notification.dismiss_btn.text() == "Tamam"

    controller.toast_notification.snooze_btn.click()
    # Break state restored and extended, nudge locked
    assert controller.break_tracker.state == BreakState.ON_BREAK
    assert controller.break_tracker.is_nudge_allowed() is False
    # Toast switched to feedback (without snooze button)
    assert "Mola Uzatıldı" in controller.toast_notification.title_label.text()
    assert not controller.toast_notification.snooze_btn.isVisible()

    controller.toast_notification.hide()


