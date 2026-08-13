import sys
import os
import json
import random
import tempfile
import ctypes
import winreg
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, time as dt_time
from pathlib import Path

from PySide6.QtCore import QTimer, QTime, QObject
from PySide6.QtGui import QAction
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QStyle,
    QSystemTrayIcon,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)

from updater import UpdateManager, run_silent_install

APP_NAME = "KeepAwake"
APP_VERSION = "1.2.0"
SINGLE_INSTANCE_NAME = "KeepAwake.SingleInstance"

ES_SYSTEM_REQUIRED = 0x00000001
ES_DISPLAY_REQUIRED = 0x00000002
ES_CONTINUOUS = 0x80000000

INPUT_MOUSE = 0
MOUSEEVENTF_MOVE = 0x0001

DAY_KEYS = [
    "monday", "tuesday", "wednesday", "thursday",
    "friday", "saturday", "sunday"
]
DAY_LABELS_TR = ["Pzt", "Sal", "Çar", "Per", "Cum", "Cmt", "Paz"]


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


@dataclass
class AppConfig:
    enabled: bool = True
    idle_minutes: int = 4
    check_interval_seconds: int = 5
    start_time: str = "08:30"
    end_time: str = "17:30"
    days: list[str] | None = None
    prevent_sleep: bool = True
    keep_display_on: bool = True
    simulate_mouse_input: bool = True
    cooldown_min_seconds: int = 70
    cooldown_max_seconds: int = 110
    start_with_windows: bool = True
    auto_check_updates: bool = True

    def __post_init__(self):
        if self.days is None:
            self.days = DAY_KEYS[:5]


class ConfigStore:
    def __init__(self):
        appdata = os.environ.get("APPDATA")
        if appdata:
            self.dir = Path(appdata) / APP_NAME
        else:
            self.dir = Path.home() / "AppData" / "Roaming" / APP_NAME
        self.path = self.dir / "config.json"

    def load(self) -> AppConfig:
        if not self.path.exists():
            return AppConfig()

        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            allowed = set(AppConfig.__dataclass_fields__.keys())
            filtered = {k: v for k, v in data.items() if k in allowed}
            return AppConfig(**filtered)
        except Exception:
            return AppConfig()

    def save(self, config: AppConfig) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(".tmp")
        temp.write_text(
            json.dumps(asdict(config), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        temp.replace(self.path)


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


def startup_registry_path() -> str:
    return r"Software\Microsoft\Windows\CurrentVersion\Run"


def get_executable_command() -> str:
    if getattr(sys, "frozen", False):
        executable = Path(sys.executable).resolve()
        return f'"{executable}" --background'

    script = Path(__file__).resolve()
    python_exe = Path(sys.executable)
    pythonw = python_exe.with_name("pythonw.exe")
    runner = pythonw if pythonw.exists() else python_exe
    return f'"{runner}" "{script}" --background'


def is_startup_enabled() -> bool:
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            startup_registry_path(),
            0,
            winreg.KEY_READ,
        ) as key:
            winreg.QueryValueEx(key, APP_NAME)
            return True
    except (FileNotFoundError, OSError):
        return False


def set_startup_enabled(enabled: bool) -> None:
    path = startup_registry_path()

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
                get_executable_command(),
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


def parse_hhmm(value: str) -> dt_time:
    hour, minute = map(int, value.split(":"))
    return dt_time(hour=hour, minute=minute)


def is_inside_schedule(config: AppConfig, now: datetime) -> bool:
    selected = set(config.days or [])
    if not selected:
        return False

    start = parse_hhmm(config.start_time)
    end = parse_hhmm(config.end_time)
    current = now.time().replace(second=0, microsecond=0)

    # Aynı gün: örn. 08:30 -> 17:30
    if start <= end:
        return DAY_KEYS[now.weekday()] in selected and start <= current <= end

    # Geceyi aşan program: örn. Cuma 22:00 -> Cumartesi 02:00
    if current >= start:
        return DAY_KEYS[now.weekday()] in selected

    previous_day = (now.weekday() - 1) % 7
    return current <= end and DAY_KEYS[previous_day] in selected


def format_duration(seconds: float) -> str:
    seconds = max(0, int(seconds))

    if seconds < 60:
        return f"{seconds} sn"

    minutes, sec = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes} dk {sec} sn"

    hours, minute = divmod(minutes, 60)
    return f"{hours} sa {minute} dk"


class SingleInstance:
    def __init__(self, app: QApplication):
        self.app = app
        self.server = None

    def notify_existing(self, command: bytes) -> bool:
        socket = QLocalSocket()
        socket.connectToServer(SINGLE_INSTANCE_NAME)

        if not socket.waitForConnected(300):
            return False

        socket.write(command)
        socket.flush()
        socket.waitForBytesWritten(300)
        socket.disconnectFromServer()
        return True

    def become_primary(self, on_command):
        QLocalServer.removeServer(SINGLE_INSTANCE_NAME)

        self.server = QLocalServer(self.app)
        if not self.server.listen(SINGLE_INSTANCE_NAME):
            raise RuntimeError("KeepAwake IPC sunucusu başlatılamadı.")

        def handle_connection():
            socket = self.server.nextPendingConnection()
            if socket is None:
                return

            if socket.waitForReadyRead(300):
                command = bytes(socket.readAll()).decode(
                    "utf-8", errors="ignore"
                ).strip()
                on_command(command)

            socket.disconnectFromServer()
            socket.deleteLater()

        self.server.newConnection.connect(handle_connection)


class SettingsWindow(QMainWindow):
    def __init__(self, controller):
        super().__init__()
        self.controller = controller

        self.setWindowTitle(f"{APP_NAME} {APP_VERSION}")
        self.setMinimumWidth(540)

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)

        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        root.addWidget(self.status_label)

        general_box = QGroupBox("Genel")
        general_form = QFormLayout(general_box)

        self.enabled_cb = QCheckBox("KeepAwake etkin")
        general_form.addRow(self.enabled_cb)

        self.startup_cb = QCheckBox("Windows ile otomatik başlat")
        general_form.addRow(self.startup_cb)

        self.auto_update_cb = QCheckBox("Güncellemeleri otomatik kontrol et")
        general_form.addRow(self.auto_update_cb)

        self.idle_spin = QSpinBox()
        self.idle_spin.setRange(1, 240)
        self.idle_spin.setSuffix(" dakika")
        general_form.addRow("Idle eşiği:", self.idle_spin)

        self.check_spin = QSpinBox()
        self.check_spin.setRange(1, 60)
        self.check_spin.setSuffix(" saniye")
        general_form.addRow("Kontrol sıklığı:", self.check_spin)

        root.addWidget(general_box)

        schedule_box = QGroupBox("Çalışma programı")
        schedule_layout = QVBoxLayout(schedule_box)

        day_row = QHBoxLayout()
        self.day_checks = []

        for label in DAY_LABELS_TR:
            cb = QCheckBox(label)
            self.day_checks.append(cb)
            day_row.addWidget(cb)

        day_row.addStretch()
        schedule_layout.addLayout(day_row)

        time_form = QFormLayout()

        self.start_edit = QTimeEdit()
        self.start_edit.setDisplayFormat("HH:mm")

        self.end_edit = QTimeEdit()
        self.end_edit.setDisplayFormat("HH:mm")

        time_form.addRow("Başlangıç:", self.start_edit)
        time_form.addRow("Bitiş:", self.end_edit)
        schedule_layout.addLayout(time_form)

        root.addWidget(schedule_box)

        behavior_box = QGroupBox("Windows güç davranışı")
        behavior_layout = QVBoxLayout(behavior_box)

        self.prevent_sleep_cb = QCheckBox(
            "Sistemin uykuya geçmesini engelle"
        )
        self.display_cb = QCheckBox(
            "Ekranın otomatik kapanmasını engelle"
        )
        self.mouse_input_cb = QCheckBox(
            "Idle eşiğine gelince fareyi 1 px sağa/sola hareket ettir"
        )

        behavior_layout.addWidget(self.prevent_sleep_cb)
        behavior_layout.addWidget(self.display_cb)
        behavior_layout.addWidget(self.mouse_input_cb)

        cooldown_form = QFormLayout()

        self.cooldown_min_spin = QSpinBox()
        self.cooldown_min_spin.setRange(0, 3600)
        self.cooldown_min_spin.setSuffix(" saniye")

        self.cooldown_max_spin = QSpinBox()
        self.cooldown_max_spin.setRange(0, 3600)
        self.cooldown_max_spin.setSuffix(" saniye")

        cooldown_form.addRow(
            "Nudge sonrası min. cooldown:",
            self.cooldown_min_spin,
        )
        cooldown_form.addRow(
            "Nudge sonrası maks. cooldown:",
            self.cooldown_max_spin,
        )
        behavior_layout.addLayout(cooldown_form)

        note = QLabel(
            "Mouse input yalnızca idle eşiğine ulaşıldığında 1 px sağa ve "
            "tekrar sola hareket üretir. Başarılı nudge sonrasında program, "
            "belirlediğiniz minimum ve maksimum değerler arasında rastgele "
            "bir cooldown süresi seçer."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: gray;")
        behavior_layout.addWidget(note)

        root.addWidget(behavior_box)

        button_row = QHBoxLayout()
        button_row.addStretch()

        self.save_button = QPushButton("Kaydet")
        self.save_button.clicked.connect(self.save)
        button_row.addWidget(self.save_button)

        self.hide_button = QPushButton("Tray'e Küçült")
        self.hide_button.clicked.connect(self.hide)
        button_row.addWidget(self.hide_button)

        root.addLayout(button_row)

        self.load_from_config()

    def load_from_config(self):
        config = self.controller.config

        self.enabled_cb.setChecked(config.enabled)
        self.startup_cb.setChecked(is_startup_enabled())
        self.auto_update_cb.setChecked(config.auto_check_updates)
        self.idle_spin.setValue(config.idle_minutes)
        self.check_spin.setValue(config.check_interval_seconds)

        start_hour, start_minute = map(int, config.start_time.split(":"))
        end_hour, end_minute = map(int, config.end_time.split(":"))

        self.start_edit.setTime(QTime(start_hour, start_minute))
        self.end_edit.setTime(QTime(end_hour, end_minute))

        selected = set(config.days or [])
        for key, checkbox in zip(DAY_KEYS, self.day_checks):
            checkbox.setChecked(key in selected)

        self.prevent_sleep_cb.setChecked(config.prevent_sleep)
        self.display_cb.setChecked(config.keep_display_on)
        self.mouse_input_cb.setChecked(config.simulate_mouse_input)
        self.cooldown_min_spin.setValue(config.cooldown_min_seconds)
        self.cooldown_max_spin.setValue(config.cooldown_max_seconds)

        self.refresh_status()

    def save(self):
        selected_days = [
            key
            for key, checkbox in zip(DAY_KEYS, self.day_checks)
            if checkbox.isChecked()
        ]

        if not selected_days:
            QMessageBox.warning(
                self,
                APP_NAME,
                "En az bir çalışma günü seçmelisin.",
            )
            return

        config = self.controller.config
        config.enabled = self.enabled_cb.isChecked()
        config.start_with_windows = self.startup_cb.isChecked()
        config.auto_check_updates = self.auto_update_cb.isChecked()
        config.idle_minutes = self.idle_spin.value()
        config.check_interval_seconds = self.check_spin.value()
        config.start_time = self.start_edit.time().toString("HH:mm")
        config.end_time = self.end_edit.time().toString("HH:mm")
        config.days = selected_days
        config.prevent_sleep = self.prevent_sleep_cb.isChecked()
        config.keep_display_on = self.display_cb.isChecked()
        config.simulate_mouse_input = self.mouse_input_cb.isChecked()

        cooldown_min = self.cooldown_min_spin.value()
        cooldown_max = self.cooldown_max_spin.value()

        if cooldown_min > cooldown_max:
            QMessageBox.warning(
                self,
                APP_NAME,
                "Minimum cooldown, maksimum cooldown değerinden büyük olamaz.",
            )
            return

        config.cooldown_min_seconds = cooldown_min
        config.cooldown_max_seconds = cooldown_max

        try:
            set_startup_enabled(config.start_with_windows)
        except OSError as exc:
            QMessageBox.critical(
                self,
                APP_NAME,
                f"Windows başlangıç ayarı değiştirilemedi:\n{exc}",
            )
            return

        self.controller.store.save(config)
        self.controller.apply_config()
        self.refresh_status()

        QMessageBox.information(
            self,
            APP_NAME,
            "Ayarlar kaydedildi.",
        )

    def refresh_status(self):
        self.status_label.setText(self.controller.status_text())

    def closeEvent(self, event):
        # X uygulamayı kapatmaz; yalnızca ayar penceresini gizler.
        event.ignore()
        self.hide()


class KeepAwakeController(QObject):
    def __init__(self, app: QApplication):
        super().__init__()

        self.app = app
        self.store = ConfigStore()
        self.config = self.store.load()
        self.paused_until: datetime | None = None
        self.execution_state_active = False
        self.last_nudge_at: datetime | None = None
        self.last_nudge_ok: bool | None = None
        self.cooldown_until: datetime | None = None
        self.last_cooldown_seconds: float | None = None

        # Registry gerçek başlangıç durumunun kaynak noktasıdır.
        self.config.start_with_windows = is_startup_enabled()

        self.window = SettingsWindow(self)

        self.tray = QSystemTrayIcon(self)
        self.tray.setIcon(
            self.app.style().standardIcon(
                QStyle.StandardPixmap.SP_ComputerIcon
            )
        )

        self.menu = QMenu()

        self.status_action = QAction("Durum hazırlanıyor…")
        self.status_action.setEnabled(False)
        self.menu.addAction(self.status_action)

        self.menu.addSeparator()

        open_action = QAction("Ayarları Aç")
        open_action.triggered.connect(self.show_settings)
        self.menu.addAction(open_action)

        update_action = QAction("Güncellemeleri Kontrol Et")
        update_action.triggered.connect(self.check_for_updates_manual)
        self.menu.addAction(update_action)

        self.enable_action = QAction("Etkin")
        self.enable_action.setCheckable(True)
        self.enable_action.setChecked(self.config.enabled)
        self.enable_action.toggled.connect(self.set_enabled_from_tray)
        self.menu.addAction(self.enable_action)

        pause_15 = QAction("15 Dakika Duraklat")
        pause_15.triggered.connect(lambda: self.pause_for(15))
        self.menu.addAction(pause_15)

        pause_60 = QAction("1 Saat Duraklat")
        pause_60.triggered.connect(lambda: self.pause_for(60))
        self.menu.addAction(pause_60)

        pause_today = QAction("Bugün İçin Duraklat")
        pause_today.triggered.connect(self.pause_until_tomorrow)
        self.menu.addAction(pause_today)

        resume_action = QAction("Duraklatmayı İptal Et")
        resume_action.triggered.connect(self.resume_now)
        self.menu.addAction(resume_action)

        self.menu.addSeparator()

        exit_action = QAction("Çıkış")
        exit_action.triggered.connect(self.quit)
        self.menu.addAction(exit_action)

        self.tray.setContextMenu(self.menu)
        self.tray.activated.connect(self.on_tray_activated)
        self.tray.show()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)

        self._update_check_manual = False
        self.update_manager = UpdateManager(APP_VERSION, self)
        self.update_manager.update_available.connect(self.on_update_available)
        self.update_manager.up_to_date.connect(self.on_up_to_date)
        self.update_manager.check_failed.connect(self.on_update_check_failed)
        self.update_manager.download_finished.connect(
            self.on_update_download_finished
        )

        if self.config.auto_check_updates:
            QTimer.singleShot(5000, self.check_for_updates_auto)

        self.apply_config()
        self.tick()

    def apply_config(self):
        interval_ms = max(1, self.config.check_interval_seconds) * 1000
        self.timer.setInterval(interval_ms)

        if not self.timer.isActive():
            self.timer.start()

        if self.enable_action.isChecked() != self.config.enabled:
            self.enable_action.blockSignals(True)
            self.enable_action.setChecked(self.config.enabled)
            self.enable_action.blockSignals(False)

        self.tick()

    def set_enabled_from_tray(self, checked: bool):
        self.config.enabled = checked
        self.store.save(self.config)
        self.window.load_from_config()
        self.tick()

    def pause_for(self, minutes: int):
        self.paused_until = datetime.now() + timedelta(minutes=minutes)
        self.tick()

    def pause_until_tomorrow(self):
        now = datetime.now()
        tomorrow = (now + timedelta(days=1)).date()
        self.paused_until = datetime.combine(tomorrow, dt_time.min)
        self.tick()

    def resume_now(self):
        self.paused_until = None
        self.tick()

    def is_paused(self, now: datetime) -> bool:
        if self.paused_until is None:
            return False

        if now >= self.paused_until:
            self.paused_until = None
            return False

        return True

    def schedule_active(self, now: datetime) -> bool:
        if not self.config.enabled:
            return False

        if self.is_paused(now):
            return False

        return is_inside_schedule(self.config, now)

    def cooldown_active(self, now: datetime) -> bool:
        if self.cooldown_until is None:
            return False

        if now >= self.cooldown_until:
            self.cooldown_until = None
            return False

        return True

    def begin_post_nudge_cooldown(self, now: datetime) -> None:
        minimum = max(0, int(self.config.cooldown_min_seconds))
        maximum = max(0, int(self.config.cooldown_max_seconds))

        if minimum > maximum:
            minimum, maximum = maximum, minimum

        duration = random.uniform(minimum, maximum)
        self.last_cooldown_seconds = duration
        self.cooldown_until = now + timedelta(seconds=duration)

    def tick(self):
        now = datetime.now()
        idle = get_idle_seconds()
        active = self.schedule_active(now)

        # Orijinal betiğe daha sadık davranış:
        # Güç/ekran keep-awake seçildiyse çalışma programı aktif olduğu sürece
        # Windows'a sürekli olarak bu isteği bildir.
        power_requested = (
            self.config.prevent_sleep
            or self.config.keep_display_on
        )

        if active and power_requested:
            self.execution_state_active = set_execution_state(
                self.config.prevent_sleep,
                self.config.keep_display_on,
            )
        else:
            if self.execution_state_active:
                clear_execution_state()
            self.execution_state_active = False

        # Mouse hareketi ise yalnızca kullanıcı belirlenen idle eşiğine
        # ulaştığında yapılır. Başarılı SendInput son kullanıcı input zamanını
        # yenilediği için bir sonraki nudge yeniden idle eşiği dolunca gelir.
        if (
            active
            and self.config.simulate_mouse_input
            and not self.cooldown_active(now)
            and idle >= self.config.idle_minutes * 60
        ):
            self.last_nudge_ok = nudge_mouse()
            self.last_nudge_at = now

            if self.last_nudge_ok:
                self.begin_post_nudge_cooldown(now)
                idle = get_idle_seconds()

        status = self.status_text(now=now, idle=idle)
        self.status_action.setText(status)
        self.tray.setToolTip(f"{APP_NAME}\n{status}")

        if self.window is not None:
            self.window.refresh_status()

    def status_text(
        self,
        now: datetime | None = None,
        idle: float | None = None,
    ) -> str:
        now = now or datetime.now()
        idle = get_idle_seconds() if idle is None else idle

        if not self.config.enabled:
            return "⚪ Devre dışı"

        if self.is_paused(now):
            return (
                "⏸ Duraklatıldı · "
                f"{self.paused_until.strftime('%d.%m %H:%M')} tarihine kadar"
            )

        if not is_inside_schedule(self.config, now):
            return "⚪ Program dışı saat"

        parts = ["🟢 Program aktif"]

        if self.config.prevent_sleep or self.config.keep_display_on:
            if self.execution_state_active:
                parts.append("Windows keep-awake açık")
            else:
                parts.append("Windows keep-awake uygulanamadı")

        if self.config.simulate_mouse_input:
            threshold = self.config.idle_minutes * 60

            if self.cooldown_active(now):
                remaining_cd = (self.cooldown_until - now).total_seconds()
                parts.append(
                    f"cooldown {format_duration(remaining_cd)}"
                )
            elif idle < threshold:
                remaining = threshold - idle
                parts.append(
                    f"mouse nudge {format_duration(remaining)} sonra"
                )
            else:
                parts.append("mouse nudge bekleniyor")

            if self.last_nudge_at is not None:
                result = "başarılı" if self.last_nudge_ok else "başarısız"
                parts.append(
                    f"son nudge {self.last_nudge_at.strftime('%H:%M:%S')} {result}"
                )

            if self.last_cooldown_seconds is not None:
                parts.append(
                    f"son cooldown {self.last_cooldown_seconds:.1f} sn"
                )

        return " · ".join(parts)

    def show_settings(self):
        self.window.load_from_config()
        self.window.show()
        self.window.raise_()
        self.window.activateWindow()

    def on_tray_activated(self, reason):
        if reason in (
            QSystemTrayIcon.ActivationReason.DoubleClick,
            QSystemTrayIcon.ActivationReason.Trigger,
        ):
            self.show_settings()

    def handle_ipc_command(self, command: str):
        command = command.upper()

        if command == "SHOW":
            self.show_settings()

        elif command == "QUIT":
            self.quit()

    def check_for_updates_manual(self):
        self._update_check_manual = True
        self.update_manager.check()

    def check_for_updates_auto(self):
        self._update_check_manual = False
        self.update_manager.check()

    def on_update_available(self, version: str, url: str, sha256: str):
        answer = QMessageBox.question(
            self.window,
            APP_NAME,
            f"Yeni sürüm mevcut: {version} (mevcut sürüm: {APP_VERSION}).\n\n"
            "Şimdi indirilip sessizce kurulsun mu? Kurulum sırasında "
            "KeepAwake kapanıp otomatik olarak yeniden açılacak.",
        )

        if answer != QMessageBox.StandardButton.Yes:
            return

        dest_dir = Path(tempfile.gettempdir()) / APP_NAME
        self.update_manager.download(url, sha256, dest_dir)

    def on_up_to_date(self):
        if self._update_check_manual:
            QMessageBox.information(
                self.window, APP_NAME, "KeepAwake zaten güncel."
            )

    def on_update_check_failed(self, reason: str):
        if self._update_check_manual:
            QMessageBox.warning(
                self.window,
                APP_NAME,
                f"Güncelleme kontrolü başarısız oldu:\n{reason}",
            )

    def on_update_download_finished(self, success: bool, path_or_error: str):
        if not success:
            QMessageBox.warning(
                self.window,
                APP_NAME,
                f"Güncelleme indirilemedi:\n{path_or_error}",
            )
            return

        try:
            run_silent_install(path_or_error)
        except OSError as exc:
            QMessageBox.critical(
                self.window,
                APP_NAME,
                f"Güncelleme başlatılamadı:\n{exc}",
            )
            return

        self.quit()

    def quit(self):
        clear_execution_state()
        self.tray.hide()
        self.app.quit()


def main():
    if sys.platform != "win32":
        print("KeepAwake yalnızca Windows'ta çalışır.")
        return 1

    background = "--background" in sys.argv
    quit_requested = "--quit" in sys.argv

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    app.setQuitOnLastWindowClosed(False)

    single = SingleInstance(app)

    # Uninstaller çalışan örneğe temiz çıkış komutu gönderebilir.
    if quit_requested:
        single.notify_existing(b"QUIT")
        return 0

    # Zaten çalışıyorsa ikinci tray ikonu yaratma.
    command = b"PING" if background else b"SHOW"

    if single.notify_existing(command):
        return 0

    controller = KeepAwakeController(app)
    single.become_primary(controller.handle_ipc_command)

    # Windows başlangıcı: hiçbir pencere göstermeden tray.
    # Elle açılış: ayar penceresini göster.
    if not background:
        controller.show_settings()

    return_code = app.exec()
    clear_execution_state()
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
