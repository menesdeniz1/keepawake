"""Linux (X11) platform backend: idle algılama, mouse nudge, uyku engelleme, autostart.

Yalnızca X11 (ve XWayland üzerinden çalışan uygulamalar) için test edilmiştir
— MIT-SCREEN-SAVER ve XTEST uzantı çağrıları Xvfb üzerinde doğrulandı. Native
Wayland oturumlarında idle algılama ve mouse nudge sessizce devre dışı kalır
(hata fırlatmaz, yalnızca etkisiz olur); sistem uykusunu engelleme
(systemd-inhibit) masaüstü ortamından bağımsız çalışmaya devam eder.
"""

import sys
import subprocess
from pathlib import Path

from core import APP_NAME

try:
    from Xlib import X, display
    from Xlib.ext import xtest

    _XLIB_AVAILABLE = True
except ImportError:
    _XLIB_AVAILABLE = False

AUTOSTART_DIR = Path.home() / ".config" / "autostart"
AUTOSTART_FILE = AUTOSTART_DIR / "keepawake.desktop"

_display = None
_display_failed = False
_inhibit_proc: subprocess.Popen | None = None
_inhibit_what: frozenset = frozenset()


def _get_display():
    global _display, _display_failed

    if _display is not None or _display_failed:
        return _display

    if not _XLIB_AVAILABLE:
        _display_failed = True
        return None

    try:
        _display = display.Display()
    except Exception:
        _display_failed = True
        _display = None

    return _display


def get_idle_seconds() -> float:
    """X11 MIT-SCREEN-SAVER uzantısıyla idle süresini döner.
    X bağlantısı yoksa (ör. native Wayland) 0.0 döner."""
    disp = _get_display()
    if disp is None:
        return 0.0

    try:
        info = disp.screen().root.screensaver_query_info()
        return info.idle / 1000.0
    except Exception:
        return 0.0


def nudge_mouse() -> bool:
    """Fareyi XTest ile 1 piksel sağa ve tekrar sola hareket ettirir."""
    disp = _get_display()
    if disp is None:
        return False

    try:
        xtest.fake_input(disp, X.MotionNotify, x=1, y=0, detail=True)
        disp.sync()
        xtest.fake_input(disp, X.MotionNotify, x=-1, y=0, detail=True)
        disp.sync()
        return True
    except Exception:
        return False


def set_execution_state(prevent_sleep: bool, keep_display_on: bool) -> bool:
    """systemd-inhibit ile sistem uykusunu ve logind idle eylemini engeller.

    Ekranın açık kalması esas olarak periyodik mouse nudge ile sağlanır
    (masaüstü ortamının kendi ekran koruyucusunun idle sayacını sıfırlar);
    buradaki 'idle' kilidi yalnızca systemd-logind'in kendi IdleAction'ı
    içindir ve dağıtıma/masaüstü ortamına göre gerçek etkisi değişebilir.
    """
    global _inhibit_proc, _inhibit_what

    what = set()
    if prevent_sleep:
        what.update({"sleep", "handle-lid-switch"})
    if keep_display_on:
        what.add("idle")

    if not what:
        clear_execution_state()
        return True

    already_running = _inhibit_proc is not None and _inhibit_proc.poll() is None
    if already_running and what == _inhibit_what:
        return True

    clear_execution_state()

    try:
        _inhibit_proc = subprocess.Popen(
            [
                "systemd-inhibit",
                f"--what={':'.join(sorted(what))}",
                f"--who={APP_NAME}",
                "--why=Çalışma programı aktif",
                "--mode=block",
                "sleep",
                "infinity",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        _inhibit_what = frozenset(what)
    except OSError:
        _inhibit_proc = None
        _inhibit_what = frozenset()
        return False

    try:
        # systemd-inhibit bir bus/izin hatasıyla hemen çıkabilir; process'in
        # gerçekten "sleep infinity" ile kilidi tutarak beklemeye devam edip
        # etmediğini kısa bir pencerede doğruluyoruz (poll() spawn sonrası
        # anında çağrılırsa süreç henüz ölmemiş görünüp yanlış True dönebilir).
        _inhibit_proc.wait(timeout=0.3)
    except subprocess.TimeoutExpired:
        return True

    _inhibit_proc = None
    _inhibit_what = frozenset()
    return False


def clear_execution_state() -> None:
    global _inhibit_proc, _inhibit_what

    if _inhibit_proc is not None and _inhibit_proc.poll() is None:
        _inhibit_proc.terminate()

    _inhibit_proc = None
    _inhibit_what = frozenset()


def _get_executable_command() -> str:
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}" --background'

    script = Path(__file__).resolve().parent / "app.py"
    return f'"{sys.executable}" "{script}" --background'


def is_startup_enabled() -> bool:
    return AUTOSTART_FILE.exists()


def set_startup_enabled(enabled: bool) -> None:
    if not enabled:
        AUTOSTART_FILE.unlink(missing_ok=True)
        return

    AUTOSTART_DIR.mkdir(parents=True, exist_ok=True)

    content = (
        "[Desktop Entry]\n"
        "Type=Application\n"
        f"Name={APP_NAME}\n"
        f"Exec={_get_executable_command()}\n"
        "X-GNOME-Autostart-enabled=true\n"
        "NoDisplay=true\n"
    )
    AUTOSTART_FILE.write_text(content, encoding="utf-8")
