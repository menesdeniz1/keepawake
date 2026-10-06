import sys
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    sys.platform != "darwin", reason="Yalnızca macOS üzerinde test edilir"
)


def test_macos_get_idle_seconds_type():
    import backend_macos

    idle = backend_macos.get_idle_seconds()
    assert isinstance(idle, float)
    assert idle >= 0.0


def test_macos_nudge_mouse():
    import backend_macos

    result = backend_macos.nudge_mouse()
    assert isinstance(result, bool)
    assert result is True


def test_macos_execution_state_toggle():
    import backend_macos

    backend_macos.set_execution_state(prevent_sleep=True, keep_display_on=True)
    backend_macos.clear_execution_state()


def test_macos_execution_state_no_respawn_when_unchanged(monkeypatch):
    import backend_macos

    calls = []

    class FakeProc:
        def __init__(self):
            self._alive = True

        def poll(self):
            return None if self._alive else 0

        def terminate(self):
            self._alive = False

        def wait(self, timeout=None):
            return 0

    def fake_popen(cmd, **kwargs):
        calls.append(cmd)
        return FakeProc()

    monkeypatch.setattr(backend_macos.subprocess, "Popen", fake_popen)
    backend_macos.clear_execution_state()

    assert backend_macos.set_execution_state(prevent_sleep=True, keep_display_on=True) is True
    assert backend_macos.set_execution_state(prevent_sleep=True, keep_display_on=True) is True
    assert len(calls) == 1, "Aynı durum için gereksiz respawn oldu"

    backend_macos.clear_execution_state()


def test_macos_execution_state_respawns_when_flags_change(monkeypatch):
    import backend_macos

    calls = []

    class FakeProc:
        def __init__(self):
            self._alive = True

        def poll(self):
            return None if self._alive else 0

        def terminate(self):
            self._alive = False

        def wait(self, timeout=None):
            return 0

    def fake_popen(cmd, **kwargs):
        calls.append(cmd)
        return FakeProc()

    monkeypatch.setattr(backend_macos.subprocess, "Popen", fake_popen)
    backend_macos.clear_execution_state()

    backend_macos.set_execution_state(prevent_sleep=True, keep_display_on=True)
    assert "-d" in calls[-1] and "-i" in calls[-1]

    backend_macos.set_execution_state(prevent_sleep=True, keep_display_on=False)
    assert "-i" in calls[-1] and "-d" not in calls[-1]
    assert len(calls) == 2

    backend_macos.clear_execution_state()


def test_macos_execution_state_clears_when_both_false():
    import backend_macos

    backend_macos.set_execution_state(prevent_sleep=False, keep_display_on=False)
    assert backend_macos._caffeinate_proc is None


def test_macos_autostart_plist(tmp_path, monkeypatch):
    import backend_macos

    test_dir = tmp_path / "LaunchAgents"
    test_plist = test_dir / "com.menesdeniz.keepawake.plist"
    monkeypatch.setattr(backend_macos, "LAUNCH_AGENTS_DIR", test_dir)
    monkeypatch.setattr(backend_macos, "PLIST_FILE", test_plist)

    assert backend_macos.is_startup_enabled() is False

    backend_macos.set_startup_enabled(True)
    assert backend_macos.is_startup_enabled() is True
    assert test_plist.exists()

    content = test_plist.read_text(encoding="utf-8")
    assert "com.menesdeniz.keepawake" in content
    assert "--background" in content
    assert "<key>RunAtLoad</key>" in content

    backend_macos.set_startup_enabled(False)
    assert backend_macos.is_startup_enabled() is False
    assert not test_plist.exists()


def test_macos_show_platform_notification(monkeypatch):
    import backend_macos

    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(backend_macos.subprocess, "run", fake_run)
    res = backend_macos.show_platform_notification("Test Title", "Test Message")
    assert res is True
    assert len(calls) == 1
    assert calls[0][0] == "osascript"
    assert "Test Title" in calls[0]
    assert "Test Message" in calls[0]

