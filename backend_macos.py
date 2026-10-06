"""macOS platform backend: idle algılama, mouse nudge, uyku engelleme (caffeinate), autostart (LaunchAgents)."""

import sys
import time
import plistlib
import subprocess
from pathlib import Path
import ctypes
from ctypes import c_double, c_uint32, c_void_p, Structure

from core import APP_NAME

# LaunchAgents yapılandırması
LAUNCH_AGENTS_DIR = Path.home() / "Library" / "LaunchAgents"
PLIST_LABEL = "com.menesdeniz.keepawake"
PLIST_FILE = LAUNCH_AGENTS_DIR / f"{PLIST_LABEL}.plist"

# Quartz / CoreGraphics sabitleri
kCGEventSourceStateCombinedSessionState = 0
kCGAnyInputEventType = 0xFFFFFFFF
kCGEventMouseMoved = 5
kCGHIDEventTap = 0


class CGPoint(Structure):
    _fields_ = [
        ("x", c_double),
        ("y", c_double),
    ]


_core_graphics = None
_core_foundation = None

try:
    _core_graphics = ctypes.cdll.LoadLibrary(
        "/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices"
    )
    _core_graphics.CGEventSourceSecondsSinceLastEventType.restype = c_double
    _core_graphics.CGEventSourceSecondsSinceLastEventType.argtypes = [c_uint32, c_uint32]

    _core_graphics.CGEventCreate.restype = c_void_p
    _core_graphics.CGEventCreate.argtypes = [c_void_p]

    _core_graphics.CGEventGetLocation.restype = CGPoint
    _core_graphics.CGEventGetLocation.argtypes = [c_void_p]

    _core_graphics.CGEventCreateMouseEvent.restype = c_void_p
    _core_graphics.CGEventCreateMouseEvent.argtypes = [c_void_p, c_uint32, CGPoint, c_uint32]

    _core_graphics.CGEventPost.restype = None
    _core_graphics.CGEventPost.argtypes = [c_uint32, c_void_p]

    _core_foundation = ctypes.cdll.LoadLibrary(
        "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation"
    )
    _core_foundation.CFRelease.restype = None
    _core_foundation.CFRelease.argtypes = [c_void_p]
except Exception:
    _core_graphics = None
    _core_foundation = None


_caffeinate_proc: subprocess.Popen | None = None
_caffeinate_flags: frozenset[str] = frozenset()


def get_idle_seconds() -> float:
    """macOS Quartz CGEventSourceSecondsSinceLastEventType ile idle süresini saniye cinsinden döner."""
    if _core_graphics is None:
        return 0.0

    try:
        return float(
            _core_graphics.CGEventSourceSecondsSinceLastEventType(
                kCGEventSourceStateCombinedSessionState,
                kCGAnyInputEventType,
            )
        )
    except Exception:
        return 0.0


def nudge_mouse() -> bool:
    """Fareyi 1 piksel sağa ve tekrar sola hareket ettirir."""
    if _core_graphics is None or _core_foundation is None:
        return False

    try:
        ev = _core_graphics.CGEventCreate(None)
        if not ev:
            return False
        loc = _core_graphics.CGEventGetLocation(ev)
        _core_foundation.CFRelease(ev)

        # 1 piksel sağa
        p1 = CGPoint(loc.x + 1, loc.y)
        m1 = _core_graphics.CGEventCreateMouseEvent(None, kCGEventMouseMoved, p1, 0)
        if not m1:
            return False
        _core_graphics.CGEventPost(kCGHIDEventTap, m1)
        _core_foundation.CFRelease(m1)

        time.sleep(0.03)

        # Geri sola (orijinal konuma)
        p2 = CGPoint(loc.x, loc.y)
        m2 = _core_graphics.CGEventCreateMouseEvent(None, kCGEventMouseMoved, p2, 0)
        if not m2:
            return False
        _core_graphics.CGEventPost(kCGHIDEventTap, m2)
        _core_foundation.CFRelease(m2)

        return True
    except Exception:
        return False


def set_execution_state(prevent_sleep: bool = True, keep_display_on: bool = True) -> bool:
    """caffeinate alt işlemi ile sistem ve ekran uykusunu engeller."""
    global _caffeinate_proc, _caffeinate_flags

    flags = set()
    if prevent_sleep:
        flags.add("-i")
    if keep_display_on:
        flags.add("-d")

    if not flags:
        clear_execution_state()
        return True

    frozen_flags = frozenset(flags)
    already_running = _caffeinate_proc is not None and _caffeinate_proc.poll() is None
    if already_running and frozen_flags == _caffeinate_flags:
        return True

    clear_execution_state()

    cmd = ["caffeinate", *sorted(flags)]
    try:
        _caffeinate_proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        _caffeinate_flags = frozen_flags
        return True
    except OSError:
        _caffeinate_proc = None
        _caffeinate_flags = frozenset()
        return False


def clear_execution_state() -> None:
    """Çalışan caffeinate alt sürecini sonlandırır."""
    global _caffeinate_proc, _caffeinate_flags

    if _caffeinate_proc is not None and _caffeinate_proc.poll() is None:
        try:
            _caffeinate_proc.terminate()
        except OSError:
            pass

    _caffeinate_proc = None
    _caffeinate_flags = frozenset()


def _get_program_arguments() -> list[str]:
    if getattr(sys, "frozen", False):
        return [str(Path(sys.executable).resolve()), "--background"]

    script = str(Path(__file__).resolve().parent / "app.py")
    return [sys.executable, script, "--background"]


def is_startup_enabled() -> bool:
    """Uygulamanın LaunchAgents üzerinde otomatik başlatma kaydı olup olmadığını denetler."""
    return PLIST_FILE.exists()


def set_startup_enabled(enabled: bool) -> None:
    """Uygulamanın LaunchAgents kaydını oluşturur veya kaldırır."""
    if not enabled:
        PLIST_FILE.unlink(missing_ok=True)
        return

    LAUNCH_AGENTS_DIR.mkdir(parents=True, exist_ok=True)
    data = {
        "Label": PLIST_LABEL,
        "ProgramArguments": _get_program_arguments(),
        "RunAtLoad": True,
    }
    with PLIST_FILE.open("wb") as f:
        plistlib.dump(data, f)


def show_platform_notification(title: str, message: str) -> bool:
    """macOS üzerinde osascript kullanarak yerel sistem bildirimi gönderir."""
    try:
        proc = subprocess.run(
            [
                "osascript",
                "-e",
                'on run argv\n'
                '  display notification (item 2 of argv) with title (item 1 of argv) sound name "Glass"\n'
                'end run',
                title,
                message,
            ],
            check=False,
            capture_output=True,
            timeout=5,
        )
        return proc.returncode == 0
    except Exception:
        return False

