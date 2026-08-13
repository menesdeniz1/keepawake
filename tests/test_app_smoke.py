import sys

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication(sys.argv)


def test_controller_lifecycle(qapp, tmp_path, monkeypatch):
    monkeypatch.delenv("APPDATA", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    import app as ka

    controller = ka.KeepAwakeController(qapp)
    try:
        assert controller.status_text() != ""

        controller.tick()

        controller.pause_for(15)
        assert "Duraklatıldı" in controller.status_text()
        controller.resume_now()

        controller.set_enabled_from_tray(False)
        assert controller.status_text() == "⚪ Devre dışı"
        controller.set_enabled_from_tray(True)
    finally:
        controller.quit()
