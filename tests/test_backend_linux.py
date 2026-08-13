import subprocess
import time

import pytest

import backend_linux as bl

X_AVAILABLE = bl._XLIB_AVAILABLE and bl._get_display() is not None
requires_x11 = pytest.mark.skipif(not X_AVAILABLE, reason="X11 display yok (DISPLAY/Xvfb ayarlı değil)")


@requires_x11
def test_get_idle_seconds_returns_nonnegative_float():
    idle = bl.get_idle_seconds()
    assert isinstance(idle, float)
    assert idle >= 0


@requires_x11
def test_nudge_mouse_resets_idle():
    time.sleep(0.5)
    idle_before = bl.get_idle_seconds()
    assert bl.nudge_mouse() is True
    idle_after = bl.get_idle_seconds()
    assert idle_after < idle_before


def test_set_execution_state_returns_bool_without_crashing():
    # Bu ortamda systemd/dbus oturumu olmayabilir; önemli olan sessizce
    # False dönmesi, exception fırlatmaması.
    result = bl.set_execution_state(prevent_sleep=True, keep_display_on=True)
    bl.clear_execution_state()
    assert isinstance(result, bool)


def test_set_execution_state_no_respawn_when_unchanged(monkeypatch):
    calls = []

    class FakeProc:
        def __init__(self):
            self._alive = True

        def poll(self):
            return None if self._alive else 0

        def wait(self, timeout=None):
            raise subprocess.TimeoutExpired(cmd="fake", timeout=timeout)

        def terminate(self):
            self._alive = False

    def fake_popen(cmd, **kwargs):
        calls.append(cmd)
        return FakeProc()

    monkeypatch.setattr(bl.subprocess, "Popen", fake_popen)
    bl._inhibit_proc = None
    bl._inhibit_what = frozenset()

    assert bl.set_execution_state(True, True) is True
    assert bl.set_execution_state(True, True) is True
    assert len(calls) == 1, "aynı durum için gereksiz respawn oldu"

    bl.clear_execution_state()


def test_set_execution_state_respawns_when_what_changes(monkeypatch):
    class FakeProc:
        def __init__(self):
            self._alive = True

        def poll(self):
            return None if self._alive else 0

        def wait(self, timeout=None):
            raise subprocess.TimeoutExpired(cmd="fake", timeout=timeout)

        def terminate(self):
            self._alive = False

    procs = []

    def fake_popen(cmd, **kwargs):
        p = FakeProc()
        procs.append(p)
        return p

    monkeypatch.setattr(bl.subprocess, "Popen", fake_popen)
    bl._inhibit_proc = None
    bl._inhibit_what = frozenset()

    bl.set_execution_state(True, True)
    first = bl._inhibit_proc
    bl.set_execution_state(True, False)

    assert bl._inhibit_proc is not first
    assert first.poll() is not None, "eski süreç sonlandırılmadı (leak)"

    bl.clear_execution_state()


def test_set_execution_state_detects_quick_failure(monkeypatch):
    class DyingProc:
        def poll(self):
            return 1

        def wait(self, timeout=None):
            return 1  # hemen çıktı -> TimeoutExpired fırlatmıyor

        def terminate(self):
            pass

    monkeypatch.setattr(bl.subprocess, "Popen", lambda cmd, **kw: DyingProc())
    bl._inhibit_proc = None
    bl._inhibit_what = frozenset()

    assert bl.set_execution_state(True, True) is False
    assert bl._inhibit_proc is None


def test_autostart_desktop_file(tmp_path, monkeypatch):
    monkeypatch.setattr(bl, "AUTOSTART_DIR", tmp_path / "autostart")
    monkeypatch.setattr(bl, "AUTOSTART_FILE", tmp_path / "autostart" / "keepawake.desktop")

    assert bl.is_startup_enabled() is False

    bl.set_startup_enabled(True)
    assert bl.is_startup_enabled() is True

    content = bl.AUTOSTART_FILE.read_text()
    assert "Exec=" in content
    assert "--background" in content

    bl.set_startup_enabled(False)
    assert bl.is_startup_enabled() is False
