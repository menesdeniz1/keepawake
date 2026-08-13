"""Windows platform backend: idle algılama, mouse nudge, güç durumu, autostart."""

import sys
import ctypes
import winreg
from pathlib import Path

from core import APP_NAME

ES_SYSTEM_REQUIRED = 0x00000001
ES_DISPLAY_REQUIRED = 0x00000002
ES_CONTINUOUS = 0x80000000

INPUT_MOUSE = 0
MOUSEEVENTF_MOVE = 0x0001


class LASTINPUTINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", ctypes.c_uint),
        ("dwTime", ctypes.c_uint32),
    ]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", ctypes.c_long),
        ("dy", ctypes.c_long),
        ("mouseData", ctypes.c_uint32),
        ("dwFlags", ctypes.c_uint32),
        ("time", ctypes.c_uint32),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class INPUTUNION(ctypes.Union):
    _fields_ = [
        ("mi", MOUSEINPUT),
    ]


class INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [
        ("type", ctypes.c_uint32),
        ("u", INPUTUNION),
    ]


def get_idle_seconds() -> float:
    """Windows'taki son kullanıcı girdisinden beri geçen süre."""
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32

    info = LASTINPUTINFO()
    info.cbSize = ctypes.sizeof(info)

    if not user32.GetLastInputInfo(ctypes.byref(info)):
        return 0.0

    # LASTINPUTINFO.dwTime 32 bittir. Farkı aynı 32-bit tick alanında
    # alarak GetTickCount wrap-around durumunu doğru ele alırız.
    now32 = kernel32.GetTickCount() & 0xFFFFFFFF
    elapsed_ms = (now32 - info.dwTime) & 0xFFFFFFFF
    return elapsed_ms / 1000.0


def set_execution_state(prevent_sleep: bool, keep_display_on: bool) -> bool:
    flags = ES_CONTINUOUS

    if prevent_sleep:
        flags |= ES_SYSTEM_REQUIRED

    if keep_display_on:
        flags |= ES_DISPLAY_REQUIRED

    return ctypes.windll.kernel32.SetThreadExecutionState(flags) != 0


def clear_execution_state() -> None:
    ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS)


def nudge_mouse() -> bool:
    """Fareyi 1 piksel sağa ve tekrar sola hareket ettirir."""
    user32 = ctypes.windll.user32

    def send_relative_move(dx: int) -> bool:
        item = INPUT(
            type=INPUT_MOUSE,
            mi=MOUSEINPUT(
                dx=dx,
                dy=0,
                mouseData=0,
                dwFlags=MOUSEEVENTF_MOVE,
                time=0,
                dwExtraInfo=0,
            ),
        )
        sent = user32.SendInput(
            1,
            ctypes.byref(item),
            ctypes.sizeof(INPUT),
        )
        return sent == 1

    if not send_relative_move(1):
        return False

    # Orijinal davranıştaki kısa sağ-sol aralığı.
    ctypes.windll.kernel32.Sleep(30)

    return send_relative_move(-1)


def _startup_registry_path() -> str:
    return r"Software\Microsoft\Windows\CurrentVersion\Run"


def _get_executable_command() -> str:
    if getattr(sys, "frozen", False):
        executable = Path(sys.executable).resolve()
        return f'"{executable}" --background'

    script = Path(__file__).resolve().parent / "app.py"
    python_exe = Path(sys.executable)
    pythonw = python_exe.with_name("pythonw.exe")
    runner = pythonw if pythonw.exists() else python_exe
    return f'"{runner}" "{script}" --background'


def is_startup_enabled() -> bool:
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            _startup_registry_path(),
            0,
            winreg.KEY_READ,
        ) as key:
            winreg.QueryValueEx(key, APP_NAME)
            return True
    except (FileNotFoundError, OSError):
        return False


def set_startup_enabled(enabled: bool) -> None:
    path = _startup_registry_path()

    if enabled:
        with winreg.CreateKeyEx(
            winreg.HKEY_CURRENT_USER,
            path,
            0,
            winreg.KEY_SET_VALUE,
        ) as key:
            winreg.SetValueEx(
                key,
                APP_NAME,
                0,
                winreg.REG_SZ,
                _get_executable_command(),
            )
        return

    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            path,
            0,
            winreg.KEY_SET_VALUE,
        ) as key:
            winreg.DeleteValue(key, APP_NAME)
    except (FileNotFoundError, OSError):
        pass
