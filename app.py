import sys
import random
import tempfile
from datetime import datetime, timedelta, time as dt_time
from pathlib import Path

from PySide6.QtCore import QTimer, QTime, QObject, Qt
from PySide6.QtGui import QAction
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QStyle,
    QSystemTrayIcon,
    QTabWidget,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)

from core import (
    APP_NAME,
    APP_VERSION,
    DAY_KEYS,
    DAY_LABELS_TR,
    BreakState,
    BreakTracker,
    ConfigStore,
    format_duration,
    is_inside_schedule,
)
from updater import UpdateManager, run_silent_install

if sys.platform == "win32":
    from backend_windows import (
        clear_execution_state,
        get_idle_seconds,
        is_startup_enabled,
        nudge_mouse,
        set_execution_state,
        set_startup_enabled,
        show_platform_notification,
    )
elif sys.platform.startswith("linux"):
    from backend_linux import (
        clear_execution_state,
        get_idle_seconds,
        is_startup_enabled,
        nudge_mouse,
        set_execution_state,
        set_startup_enabled,
        show_platform_notification,
    )
elif sys.platform == "darwin":
    from backend_macos import (
        clear_execution_state,
        get_idle_seconds,
        is_startup_enabled,
        nudge_mouse,
        set_execution_state,
        set_startup_enabled,
        show_platform_notification,
    )
else:
    print(f"KeepAwake, {sys.platform} platformunu desteklemiyor.")
    raise SystemExit(1)

SINGLE_INSTANCE_NAME = "KeepAwake.SingleInstance"


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


class BreakNagDialog(QDialog):
    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller

        self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)
        self.setWindowTitle("UpNow - Mola Vakti")
        self.setMinimumWidth(380)

        layout = QVBoxLayout(self)
        layout.setSpacing(14)
        layout.setContentsMargins(20, 20, 20, 20)

        self.headline_label = QLabel("Lütfen Masadan Uzaklaşın!")
        self.headline_label.setObjectName("headline")
        self.headline_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        h_font = self.headline_label.font()
        h_font.setPointSize(16)
        h_font.setBold(True)
        self.headline_label.setFont(h_font)
        layout.addWidget(self.headline_label)

        hint = QLabel("Gözlerinizi dinlendirin, ayağa kalkın ve esneyin.")
        hint.setObjectName("hint")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(hint)

        self.countdown_label = QLabel("00:00")
        self.countdown_label.setObjectName("countdown")
        self.countdown_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        c_font = self.countdown_label.font()
        c_font.setPointSize(36)
        c_font.setBold(True)
        self.countdown_label.setFont(c_font)
        layout.addWidget(self.countdown_label)

        btn_row = QHBoxLayout()
        snooze_min = getattr(self.controller.config, "break_snooze_minutes", 5)
        self.snooze_btn = QPushButton(f"{snooze_min} Dakika Ertele")
        self.snooze_btn.clicked.connect(self.on_snooze)
        btn_row.addWidget(self.snooze_btn)

        self.finish_btn = QPushButton("Acil Durum: Molayı Bitir")
        self.finish_btn.clicked.connect(self.on_finish)
        btn_row.addWidget(self.finish_btn)

        # Aliases for compatibility
        self.snooze_button = self.snooze_btn
        self.finish_button = self.finish_btn
        self.headline = self.headline_label

        layout.addLayout(btn_row)

        self.setStyleSheet("""
            QDialog {
                background-color: #1e1e2e;
                color: #cdd6f4;
            }
            QLabel {
                color: #cdd6f4;
            }
            QLabel#headline {
                color: #f38ba8;
            }
            QLabel#hint {
                color: #a6adc8;
            }
            QLabel#countdown {
                color: #89b4fa;
            }
            QPushButton {
                background-color: #313244;
                color: #cdd6f4;
                border: 1px solid #45475a;
                border-radius: 6px;
                padding: 8px 14px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #45475a;
            }
        """)

    def update_status(self, remaining_text: str):
        self.countdown_label.setText(remaining_text)
        snooze_min = getattr(self.controller.config, "break_snooze_minutes", 5)
        self.snooze_btn.setText(f"{snooze_min} Dakika Ertele")

    def on_snooze(self):
        snooze_min = getattr(self.controller.config, "break_snooze_minutes", 5)
        if hasattr(self.controller, "snooze_break"):
            self.controller.snooze_break(snooze_min)
        elif hasattr(self.controller, "break_tracker"):
            self.controller.break_tracker.snooze(snooze_min)
        self.hide()

    def on_finish(self):
        if hasattr(self.controller, "start_work_now"):
            self.controller.start_work_now()
        elif hasattr(self.controller, "break_tracker"):
            self.controller.break_tracker.reset()
        self.hide()

    def closeEvent(self, event):
        # Zorlayıcı modda pencere X ile kapanmaz; kullanıcı Ertele veya Molayı Bitir butonuna basmalıdır.
        event.ignore()


class BreakToastNotification(QWidget):
    """Nazik Mod: Ekranın sağ üst köşesinde zarifçe beliren, odağı çalmayan kayan bildirim kartı."""

    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.ToolTip
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)

        self.auto_hide_timer = QTimer(self)
        self.auto_hide_timer.setSingleShot(True)
        self.auto_hide_timer.timeout.connect(self.hide)

        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)

        self.card = QFrame(self)
        self.card.setObjectName("toastCard")
        card_layout = QVBoxLayout(self.card)
        card_layout.setContentsMargins(14, 12, 14, 12)
        card_layout.setSpacing(8)

        # Üst satır: Başlık ve Kapatma Çarpısı
        top_row = QHBoxLayout()
        self.title_label = QLabel("🔔 UpNow - Mola Vakti", self)
        self.title_label.setObjectName("toastTitle")
        t_font = self.title_label.font()
        t_font.setBold(True)
        t_font.setPointSize(13)
        self.title_label.setFont(t_font)
        top_row.addWidget(self.title_label)
        top_row.addStretch()

        close_btn = QPushButton("✕", self)
        close_btn.setObjectName("toastClose")
        close_btn.setFixedSize(20, 20)
        close_btn.clicked.connect(self.hide)
        top_row.addWidget(close_btn)
        card_layout.addLayout(top_row)

        # Mesaj içeriği
        self.msg_label = QLabel(self)
        self.msg_label.setObjectName("toastMsg")
        self.msg_label.setWordWrap(True)
        card_layout.addWidget(self.msg_label)

        # Butonlar satırı: [ X Dk Ertele ] [ Tamam ]
        btn_row = QHBoxLayout()
        btn_row.addStretch()

        snooze_min = getattr(self.controller.config, "break_snooze_minutes", 5)
        self.snooze_btn = QPushButton(f"{snooze_min} Dk Ertele", self)
        self.snooze_btn.clicked.connect(self.on_snooze)
        btn_row.addWidget(self.snooze_btn)

        self.dismiss_btn = QPushButton("Tamam", self)
        self.dismiss_btn.clicked.connect(self.hide)
        btn_row.addWidget(self.dismiss_btn)

        card_layout.addLayout(btn_row)
        outer_layout.addWidget(self.card)

        self.setStyleSheet("""
            QFrame#toastCard {
                background-color: #1e1e2e;
                border: 1px solid #45475a;
                border-radius: 12px;
            }
            QLabel#toastTitle {
                color: #89b4fa;
            }
            QLabel#toastMsg {
                color: #cdd6f4;
                font-size: 12px;
            }
            QPushButton {
                background-color: #313244;
                color: #cdd6f4;
                border: 1px solid #45475a;
                border-radius: 6px;
                padding: 4px 10px;
                font-size: 11px;
                font-weight: 500;
            }
            QPushButton:hover {
                background-color: #45475a;
            }
            QPushButton#toastClose {
                border: none;
                background: transparent;
                color: #a6adc8;
                font-size: 12px;
                padding: 0;
            }
            QPushButton#toastClose:hover {
                color: #f38ba8;
            }
        """)

    def on_snooze(self):
        snooze_min = getattr(self.controller.config, "break_snooze_minutes", 5)
        if callable(getattr(self, "_on_snooze_callback", None)):
            self._on_snooze_callback(snooze_min)
        elif hasattr(self.controller, "snooze_break"):
            self.controller.snooze_break(snooze_min)
        elif hasattr(self.controller, "break_tracker"):
            self.controller.break_tracker.snooze(snooze_min)
        self.hide()

    def reposition(self):
        screen = QApplication.primaryScreen()
        if screen is not None:
            geom = screen.availableGeometry()
            width = 340
            height = self.sizeHint().height() or 110
            x = geom.right() - width - 20
            y = geom.top() + 40
            self.setGeometry(x, y, width, height)

    def show_toast(
        self,
        title: str,
        message: str,
        timeout_seconds: int = 8,
        snooze_text: str | None = None,
        on_snooze=None,
        show_snooze: bool | None = None,
    ):
        self.title_label.setText(title)
        self.msg_label.setText(message)
        snooze_min = getattr(self.controller.config, "break_snooze_minutes", 5)
        if snooze_text:
            self.snooze_btn.setText(snooze_text)
        else:
            self.snooze_btn.setText(f"{snooze_min} Dk Ertele")
        self._on_snooze_callback = on_snooze
        if show_snooze is None:
            show_snooze = True
        self.snooze_btn.setVisible(show_snooze)
        self.adjustSize()
        self.reposition()
        self.show()
        self.auto_hide_timer.start(timeout_seconds * 1000)

    def closeEvent(self, event):
        event.ignore()
        self.hide()


class SettingsWindow(QMainWindow):
    def __init__(self, controller):
        super().__init__()
        self.controller = controller

        self.setWindowTitle(f"{APP_NAME} {APP_VERSION}")
        self.setMinimumWidth(540)

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)

        self.tabs = QTabWidget()

        # --- Sekme 1: Genel Bakış (Dashboard) ---
        dashboard_scroll = QScrollArea()
        dashboard_scroll.setWidgetResizable(True)
        dashboard_scroll.setFrameShape(QFrame.Shape.NoFrame)
        dashboard_scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        dashboard_page = QWidget()
        dashboard_layout = QVBoxLayout(dashboard_page)

        # KeepAwake Özet Kartı
        self.dash_ka_box = QGroupBox("KeepAwake - Ekran ve Uyku Yönetimi")
        dash_ka_layout = QVBoxLayout(self.dash_ka_box)
        self.dash_ka_status = QLabel()
        self.dash_ka_status.setWordWrap(True)
        dash_ka_layout.addWidget(self.dash_ka_status)

        dash_ka_actions = QHBoxLayout()
        self.dash_ka_toggle_btn = QPushButton("Durdur")
        self.dash_ka_toggle_btn.clicked.connect(self.controller.toggle_keepawake)
        dash_ka_actions.addWidget(self.dash_ka_toggle_btn)
        dash_ka_actions.addStretch()
        dash_ka_layout.addLayout(dash_ka_actions)

        dashboard_layout.addWidget(self.dash_ka_box)

        # UpNow Özet Kartı
        self.dash_upnow_box = QGroupBox("UpNow - Mola Takipçisi")
        dash_upnow_layout = QVBoxLayout(self.dash_upnow_box)
        self.dash_upnow_status = QLabel()
        self.dash_upnow_status.setWordWrap(True)
        dash_upnow_layout.addWidget(self.dash_upnow_status)

        dash_upnow_actions = QHBoxLayout()
        self.dash_upnow_toggle_btn = QPushButton("Durdur")
        self.dash_upnow_toggle_btn.clicked.connect(self.controller.toggle_upnow)
        dash_upnow_actions.addWidget(self.dash_upnow_toggle_btn)

        self.dash_start_break_btn = QPushButton("Molayı Şimdi Başlat")
        self.dash_start_break_btn.clicked.connect(self.controller.toggle_break_or_work)
        dash_upnow_actions.addWidget(self.dash_start_break_btn)

        snooze_min = getattr(self.controller.config, "break_snooze_minutes", 5)
        self.dash_snooze_btn = QPushButton(f"{snooze_min} Dakika Ertele")
        self.dash_snooze_btn.clicked.connect(lambda: self.controller.snooze_break())
        dash_upnow_actions.addWidget(self.dash_snooze_btn)

        dash_upnow_actions.addStretch()
        dash_upnow_layout.addLayout(dash_upnow_actions)
        dashboard_layout.addWidget(self.dash_upnow_box)
        dashboard_layout.addStretch()

        dashboard_scroll.setWidget(dashboard_page)
        self.tabs.addTab(dashboard_scroll, "Genel Bakış")

        # --- Sekme 2: KeepAwake (Uyanık Tutucu) ---
        keepawake_scroll = QScrollArea()
        keepawake_scroll.setWidgetResizable(True)
        keepawake_scroll.setFrameShape(QFrame.Shape.NoFrame)
        keepawake_scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        keepawake_page = QWidget()
        keepawake_layout = QVBoxLayout(keepawake_page)

        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        keepawake_layout.addWidget(self.status_label)

        general_box = QGroupBox("Genel")
        general_form = QFormLayout(general_box)

        self.enabled_cb = QCheckBox("KeepAwake etkin")
        general_form.addRow(self.enabled_cb)

        self.startup_cb = QCheckBox("Oturum açılışında otomatik başlat")
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

        keepawake_layout.addWidget(general_box)

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

        keepawake_layout.addWidget(schedule_box)

        behavior_box = QGroupBox("Güç davranışı")
        behavior_layout = QVBoxLayout(behavior_box)

        self.prevent_sleep_cb = QCheckBox(
            "Sistemin uykuya geçmesini engelle"
        )
        self.display_cb = QCheckBox(
            "Ekranın otomatik kapanmasını engelle"
        )

        mouse_row = QHBoxLayout()
        mouse_row.setContentsMargins(0, 0, 0, 0)
        self.mouse_input_cb = QCheckBox(
            "Idle eşiğine gelince fareyi 1 px sağa/sola hareket ettir"
        )
        info_badge = QLabel("ⓘ")
        info_badge.setCursor(Qt.CursorShape.PointingHandCursor)
        info_badge.setStyleSheet("color: gray; font-size: 13px; font-weight: bold; padding-left: 4px;")
        info_badge.setToolTip(
            "Mouse input yalnızca idle eşiğine ulaşıldığında 1 px sağa ve "
            "tekrar sola mikro hareket üretir.\n"
            "Bu sayede bilgisayarın kilitlenmesi veya uykuya dalması engellenir.\n"
            "Başarılı nudge sonrasında sistem belirlenen cooldown aralığında bekler."
        )
        mouse_row.addWidget(self.mouse_input_cb)
        mouse_row.addWidget(info_badge)
        mouse_row.addStretch()

        behavior_layout.addWidget(self.prevent_sleep_cb)
        behavior_layout.addWidget(self.display_cb)
        behavior_layout.addLayout(mouse_row)

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

        keepawake_layout.addWidget(behavior_box)
        keepawake_layout.addStretch()

        keepawake_scroll.setWidget(keepawake_page)
        self.tabs.addTab(keepawake_scroll, "KeepAwake (Uyanık Tutucu)")

        # --- Sekme 2: UpNow (Mola Takipçisi) ---
        upnow_scroll = QScrollArea()
        upnow_scroll.setWidgetResizable(True)
        upnow_scroll.setFrameShape(QFrame.Shape.NoFrame)
        upnow_scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        upnow_page = QWidget()
        upnow_layout = QVBoxLayout(upnow_page)

        self.upnow_status_label = QLabel()
        self.upnow_status_label.setWordWrap(True)
        upnow_layout.addWidget(self.upnow_status_label)

        upnow_box = QGroupBox("Mola Takipçisi Ayarları")
        upnow_form = QFormLayout(upnow_box)

        self.break_enabled_check = QCheckBox("UpNow mola takipçisini etkinleştir")
        upnow_form.addRow(self.break_enabled_check)

        self.work_duration_spin = QSpinBox()
        self.work_duration_spin.setRange(1, 180)
        self.work_duration_spin.setSuffix(" dk")
        upnow_form.addRow("Çalışma süresi:", self.work_duration_spin)

        self.break_duration_spin = QSpinBox()
        self.break_duration_spin.setRange(1, 60)
        self.break_duration_spin.setSuffix(" dk")
        upnow_form.addRow("Mola süresi:", self.break_duration_spin)

        self.break_snooze_spin = QSpinBox()
        self.break_snooze_spin.setRange(1, 60)
        self.break_snooze_spin.setSuffix(" dk")
        self.break_snooze_spin.valueChanged.connect(self._on_snooze_spin_changed)
        upnow_form.addRow("Erteleme süresi:", self.break_snooze_spin)

        self.break_alert_combo = QComboBox()
        self.break_alert_combo.addItem("Nazik Bildirim (Sistem)", "notification")
        self.break_alert_combo.addItem("Zorlayıcı Mod (Uyarı Penceresi)", "nagging")
        upnow_form.addRow("Uyarı modu:", self.break_alert_combo)

        upnow_layout.addWidget(upnow_box)

        actions_box = QGroupBox("Hızlı Mola Aksiyonları")
        actions_layout = QHBoxLayout(actions_box)
        self.tab_start_break_btn = QPushButton("Molayı Şimdi Başlat")
        self.tab_start_break_btn.clicked.connect(self.controller.toggle_break_or_work)
        actions_layout.addWidget(self.tab_start_break_btn)

        self.tab_snooze_btn = QPushButton(f"{snooze_min} Dakika Ertele")
        self.tab_snooze_btn.clicked.connect(lambda: self.controller.snooze_break())
        actions_layout.addWidget(self.tab_snooze_btn)

        upnow_layout.addWidget(actions_box)
        upnow_layout.addStretch()

        upnow_scroll.setWidget(upnow_page)
        self.tabs.addTab(upnow_scroll, "UpNow (Mola Takipçisi)")

        root.addWidget(self.tabs)

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

        self.break_enabled_check.setChecked(config.break_reminder_enabled)
        self.work_duration_spin.setValue(config.work_duration_minutes)
        self.break_duration_spin.setValue(config.break_duration_minutes)
        self.break_snooze_spin.setValue(config.break_snooze_minutes)
        combo_idx = 1 if config.break_alert_mode == "nagging" else 0
        self.break_alert_combo.setCurrentIndex(combo_idx)

        self.update_snooze_buttons()
        self.refresh_status()

    def _on_snooze_spin_changed(self, value: int):
        text = f"{value} Dakika Ertele"
        if hasattr(self, "dash_snooze_btn"):
            self.dash_snooze_btn.setText(text)
        if hasattr(self, "tab_snooze_btn"):
            self.tab_snooze_btn.setText(text)

    def update_snooze_buttons(self):
        snooze_min = getattr(self.controller.config, "break_snooze_minutes", 5)
        text = f"{snooze_min} Dakika Ertele"
        if hasattr(self, "dash_snooze_btn"):
            self.dash_snooze_btn.setText(text)
        if hasattr(self, "tab_snooze_btn"):
            self.tab_snooze_btn.setText(text)
        if getattr(self.controller, "nag_dialog", None) is not None:
            self.controller.nag_dialog.snooze_btn.setText(text)
        if getattr(self.controller, "snooze_break_action", None) is not None:
            self.controller.snooze_break_action.setText(text)

    def save_from_window(self):
        config = self.controller.config
        config.break_reminder_enabled = self.break_enabled_check.isChecked()
        config.work_duration_minutes = self.work_duration_spin.value()
        config.break_duration_minutes = self.break_duration_spin.value()
        config.break_snooze_minutes = self.break_snooze_spin.value()
        selected_data = self.break_alert_combo.currentData()
        if selected_data:
            config.break_alert_mode = selected_data
        else:
            config.break_alert_mode = (
                "nagging"
                if self.break_alert_combo.currentIndex() == 1
                else "notification"
            )

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

        self.save_from_window()

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
                f"Otomatik başlatma ayarı değiştirilemedi:\n{exc}",
            )
            return

        self.controller.store.save(config)
        self.controller.apply_config()
        self.update_snooze_buttons()
        self.refresh_status()

        QMessageBox.information(
            self,
            APP_NAME,
            "Ayarlar kaydedildi.",
        )

    def refresh_status(self):
        ka_text = self.controller.keepawake_status_text()
        self.status_label.setText(ka_text)
        if hasattr(self, "dash_ka_status"):
            self.dash_ka_status.setText(ka_text)

        if hasattr(self, "upnow_status_label"):
            if not self.controller.config.break_reminder_enabled or self.controller.break_tracker.state == BreakState.DISABLED:
                up_text = "⚪ Devre dışı"
            elif self.controller.break_tracker.state == BreakState.PAUSED:
                up_text = "⏸ Duraklatıldı"
            elif self.controller.break_tracker.state in (BreakState.ON_BREAK, BreakState.BREAK_VIOLATION):
                rem = self.controller.break_tracker.remaining_seconds()
                minutes, seconds = divmod(rem, 60)
                up_text = f"🔵 Mola: {minutes:02d}:{seconds:02d} kaldı (Masadan Kalk!)"
            else:
                from datetime import datetime
                tracker_status = self.controller.break_tracker.status_text(datetime.now())
                up_text = f"🟢 {tracker_status}"

            self.upnow_status_label.setText(up_text)
            if hasattr(self, "dash_upnow_status"):
                self.dash_upnow_status.setText(up_text)

        on_break = self.controller.break_tracker.state in (BreakState.ON_BREAK, BreakState.BREAK_VIOLATION)
        break_btn_text = "Molayı Şimdi Bitir" if on_break else "Molayı Şimdi Başlat"
        if hasattr(self, "dash_start_break_btn"):
            self.dash_start_break_btn.setText(break_btn_text)
        if hasattr(self, "tab_start_break_btn"):
            self.tab_start_break_btn.setText(break_btn_text)

        ka_enabled = self.controller.config.enabled
        if hasattr(self, "dash_ka_toggle_btn"):
            self.dash_ka_toggle_btn.setText("Durdur" if ka_enabled else "Başlat")

        up_enabled = self.controller.config.break_reminder_enabled
        if hasattr(self, "dash_upnow_toggle_btn"):
            self.dash_upnow_toggle_btn.setText("Durdur" if up_enabled else "Başlat")

        if hasattr(self, "dash_start_break_btn"):
            self.dash_start_break_btn.setEnabled(up_enabled)
        if hasattr(self, "dash_snooze_btn"):
            self.dash_snooze_btn.setEnabled(up_enabled)

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
        self.break_tracker = BreakTracker(self.config)
        self.paused_until: datetime | None = None
        self.execution_state_active = False
        self.last_nudge_at: datetime | None = None
        self.last_nudge_ok: bool | None = None
        self.cooldown_until: datetime | None = None
        self.last_cooldown_seconds: float | None = None

        # Registry/autostart dosyası gerçek başlangıç durumunun kaynak noktasıdır.
        self.config.start_with_windows = is_startup_enabled()

        self.window = SettingsWindow(self)
        self.nag_dialog = BreakNagDialog(self)
        self.toast_notification = BreakToastNotification(self)

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

        self.break_action = QAction("Mola Takipçisi (UpNow)")
        self.break_action.setCheckable(True)
        self.break_action.setChecked(self.config.break_reminder_enabled)
        self.break_action.toggled.connect(self.set_break_reminder_enabled_from_tray)
        self.menu.addAction(self.break_action)

        self.start_break_action = QAction("Molayı Şimdi Başlat")
        self.start_break_action.triggered.connect(self.toggle_break_or_work)
        self.menu.addAction(self.start_break_action)

        snooze_min = getattr(self.config, "break_snooze_minutes", 5)
        self.snooze_break_action = QAction(f"{snooze_min} Dakika Ertele")
        self.snooze_break_action.triggered.connect(lambda: self.snooze_break())
        self.menu.addAction(self.snooze_break_action)

        self.toggle_break_pause_action = QAction("Mola Takibini Duraklat / Devam Ettir")
        self.toggle_break_pause_action.triggered.connect(self.toggle_break_pause)
        self.menu.addAction(self.toggle_break_pause_action)

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
        # Mola takipçisi etkinken sayacın canlı ve akıcı geri sayması için 1 saniyelik kontrol;
        # kapalıyken kullanıcının belirlediği check_interval_seconds kullanılır.
        if self.config.break_reminder_enabled:
            interval_ms = 1000
        else:
            interval_ms = max(1, self.config.check_interval_seconds) * 1000
        self.timer.setInterval(interval_ms)

        if not self.timer.isActive():
            self.timer.start()

        if self.enable_action.isChecked() != self.config.enabled:
            self.enable_action.blockSignals(True)
            self.enable_action.setChecked(self.config.enabled)
            self.enable_action.blockSignals(False)

        if (
            hasattr(self, "break_action")
            and self.break_action.isChecked() != self.config.break_reminder_enabled
        ):
            self.break_action.blockSignals(True)
            self.break_action.setChecked(self.config.break_reminder_enabled)
            self.break_action.blockSignals(False)

        if hasattr(self, "snooze_break_action"):
            self.snooze_break_action.setText(f"{self.config.break_snooze_minutes} Dakika Ertele")

        if hasattr(self, "window") and self.window is not None:
            self.window.update_snooze_buttons()

        self.break_tracker.update_config(self.config)
        self.tick()

    def set_enabled_from_tray(self, checked: bool):
        self.config.enabled = checked
        self.store.save(self.config)
        self.window.load_from_config()
        self.tick()

    def set_break_reminder_enabled_from_tray(self, checked: bool):
        self.config.break_reminder_enabled = checked
        self.store.save(self.config)
        self.window.load_from_config()
        self.apply_config()

    def toggle_keepawake(self):
        self.set_enabled_from_tray(not self.config.enabled)

    def toggle_upnow(self):
        self.set_break_reminder_enabled_from_tray(not self.config.break_reminder_enabled)

    def toggle_break_or_work(self):
        if self.break_tracker.state in (BreakState.ON_BREAK, BreakState.BREAK_VIOLATION):
            self.start_work_now()
        else:
            self.start_break_now()

    def start_break_now(self):
        self.break_tracker.start_break_now()
        self.notify_break_started()
        self.tick()

    def extend_work(self, minutes: int | None = None):
        if minutes is None:
            minutes = getattr(self.config, "break_snooze_minutes", 5)
        self.break_tracker.extend_work(minutes)
        if (
            getattr(self, "nag_dialog", None) is not None
            and self.nag_dialog.isVisible()
        ):
            self.nag_dialog.hide()
        title = "UpNow - Mola Ertelendi"
        msg = f"Mola {minutes} dakika ertelendi, çalışmaya devam ediliyor."
        self.show_system_notification(
            title,
            msg,
            QSystemTrayIcon.MessageIcon.Information,
            show_snooze=False,
        )
        self.tick()

    def extend_break(self, minutes: int | None = None):
        if minutes is None:
            minutes = getattr(self.config, "break_snooze_minutes", 5)
        self.break_tracker.extend_break(minutes)
        if (
            getattr(self, "nag_dialog", None) is not None
            and self.nag_dialog.isVisible()
        ):
            self.nag_dialog.hide()
        title = "UpNow - Mola Uzatıldı"
        msg = f"Mola {minutes} dakika uzatıldı, dinlenmeye devam edebilirsiniz."
        self.show_system_notification(
            title,
            msg,
            QSystemTrayIcon.MessageIcon.Information,
            show_snooze=False,
        )
        self.tick()

    def snooze_break(self, minutes: int | None = None):
        if minutes is None:
            minutes = getattr(self.config, "break_snooze_minutes", 5)
        self.break_tracker.snooze(minutes)
        if (
            getattr(self, "nag_dialog", None) is not None
            and self.nag_dialog.isVisible()
        ):
            self.nag_dialog.hide()
        title = "UpNow - Mola Ertelendi"
        msg = f"Mola {minutes} dakika ertelendi."
        self.show_system_notification(
            title,
            msg,
            QSystemTrayIcon.MessageIcon.Information,
            show_snooze=False,
        )
        self.tick()

    def start_work_now(self):
        self.break_tracker.reset()
        if (
            getattr(self, "nag_dialog", None) is not None
            and self.nag_dialog.isVisible()
        ):
            self.nag_dialog.hide()
        if (
            getattr(self, "toast_notification", None) is not None
            and self.toast_notification.isVisible()
        ):
            self.toast_notification.hide()
        self.notify_break_finished()
        self.tick()

    def toggle_break_pause(self):
        result = self.break_tracker.toggle_pause()
        self.tick()
        return result

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

        prev_state = self.break_tracker.state
        self.break_tracker.tick(now, idle)
        curr_state = self.break_tracker.state

        if prev_state == BreakState.WORKING and curr_state in (BreakState.ON_BREAK, BreakState.BREAK_VIOLATION):
            self.notify_break_started()
        elif prev_state in (BreakState.ON_BREAK, BreakState.BREAK_VIOLATION) and curr_state == BreakState.WORKING:
            self.notify_break_finished()

        if self.break_tracker.should_alert(now):
            self.trigger_break_alert()
            self.break_tracker.record_alert(now)

        # Orijinal betiğe daha sadık davranış:
        # Güç/ekran keep-awake seçildiyse çalışma programı aktif olduğu sürece
        # işletim sistemine sürekli olarak bu isteği bildir.
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
        # Mola esnasında ise nudge kilitlenir.
        if (
            active
            and self.config.simulate_mouse_input
            and not self.cooldown_active(now)
            and self.break_tracker.is_nudge_allowed()
            and idle >= self.config.idle_minutes * 60
        ):
            self.last_nudge_ok = nudge_mouse()
            self.last_nudge_at = now

            if self.last_nudge_ok:
                self.begin_post_nudge_cooldown(now)
                idle = get_idle_seconds()

        if (
            getattr(self, "nag_dialog", None) is not None
            and self.nag_dialog.isVisible()
        ):
            if self.break_tracker.state not in (
                BreakState.ON_BREAK,
                BreakState.BREAK_VIOLATION,
            ):
                self.nag_dialog.hide()
            else:
                rem = self.break_tracker.remaining_seconds(now)
                minutes, seconds = divmod(rem, 60)
                self.nag_dialog.update_status(f"{minutes:02d}:{seconds:02d}")

        on_break = self.break_tracker.state in (BreakState.ON_BREAK, BreakState.BREAK_VIOLATION)
        break_btn_text = "Molayı Şimdi Bitir" if on_break else "Molayı Şimdi Başlat"
        if hasattr(self, "start_break_action"):
            self.start_break_action.setText(break_btn_text)

        status = self.status_text(now=now, idle=idle)
        self.status_action.setText(status)
        self.tray.setToolTip(f"{APP_NAME}\n{status}")

        if self.window is not None:
            self.window.refresh_status()

    def show_system_notification(
        self,
        title: str,
        message: str,
        icon: QSystemTrayIcon.MessageIcon = QSystemTrayIcon.MessageIcon.Information,
        snooze_text: str | None = None,
        on_snooze=None,
        show_snooze: bool | None = None,
    ):
        # 1. Native platform notification (e.g. macOS osascript, Linux notify-send)
        try:
            show_platform_notification(title, message)
        except Exception:
            pass

        # 2. Nazik Mod: Ekranın sağ üst köşesinde açılan zarif bildirim kartı
        if hasattr(self, "toast_notification") and self.toast_notification is not None:
            try:
                self.toast_notification.show_toast(
                    title,
                    message,
                    snooze_text=snooze_text,
                    on_snooze=on_snooze,
                    show_snooze=show_snooze,
                )
            except Exception:
                pass

        # 3. Qt tray notification (standard on Windows and Qt-supported tray integrations)
        if hasattr(self, "tray") and self.tray is not None:
            try:
                self.tray.showMessage(title, message, icon, 5000)
            except Exception:
                pass

    def notify_break_started(self):
        duration = self.config.break_duration_minutes
        title = "UpNow - Mola Vakti"
        msg = f"Mola vakti! Lütfen masadan kalkın ve dinlenin ({duration} dk)."

        if self.config.break_alert_mode == "nagging":
            if getattr(self, "nag_dialog", None) is not None:
                rem = self.break_tracker.remaining_seconds()
                minutes, seconds = divmod(rem, 60)
                self.nag_dialog.update_status(f"{minutes:02d}:{seconds:02d}")
                self.nag_dialog.show()
                self.nag_dialog.raise_()
                self.nag_dialog.activateWindow()
        else:
            snooze_min = getattr(self.config, "break_snooze_minutes", 5)
            self.show_system_notification(
                title,
                msg,
                QSystemTrayIcon.MessageIcon.Information,
                snooze_text=f"{snooze_min} Dk Ertele",
                on_snooze=lambda m: self.extend_work(m),
                show_snooze=True,
            )

    def notify_break_finished(self):
        if getattr(self, "nag_dialog", None) is not None and self.nag_dialog.isVisible():
            self.nag_dialog.hide()
        if getattr(self, "toast_notification", None) is not None and self.toast_notification.isVisible():
            self.toast_notification.hide()

        title = "UpNow - Mola Tamamlandı"
        msg = "Mola süresi tamamlandı. Odaklanma süresi başladı, iyi çalışmalar!"
        snooze_min = getattr(self.config, "break_snooze_minutes", 5)
        self.show_system_notification(
            title,
            msg,
            QSystemTrayIcon.MessageIcon.Information,
            snooze_text=f"{snooze_min} Dk Ertele",
            on_snooze=lambda m: self.extend_break(m),
            show_snooze=True,
        )

    def trigger_break_alert(self):
        # Yalnızca zorlayıcı (nagging) modda pencereyi öne getirir.
        # Nazik modda mola başlangıcında bir kere kart çıkar ve kendiliğinden kapanır;
        # mola süresince kullanıcıya ardışık ihlal bildirimi basılmaz.
        if self.config.break_alert_mode == "nagging":
            if getattr(self, "nag_dialog", None) is not None:
                rem = self.break_tracker.remaining_seconds()
                minutes, seconds = divmod(rem, 60)
                self.nag_dialog.update_status(f"{minutes:02d}:{seconds:02d}")
                self.nag_dialog.show()
                self.nag_dialog.raise_()
                self.nag_dialog.activateWindow()

    def keepawake_status_text(
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

        parts = []

        if self.config.simulate_mouse_input:
            threshold = self.config.idle_minutes * 60

            if not self.break_tracker.is_nudge_allowed():
                parts.append("Mouse Nudge: duraklatıldı (mola)")
            elif self.cooldown_active(now):
                remaining_cd = (self.cooldown_until - now).total_seconds()
                parts.append(
                    f"Mouse Nudge: cooldown {format_duration(remaining_cd)}"
                )
            elif idle < threshold:
                remaining = threshold - idle
                parts.append(
                    f"Mouse Nudge: {format_duration(remaining)} sonra"
                )
            else:
                parts.append("Mouse Nudge: bekleniyor")

            if self.last_nudge_at is not None:
                result = "başarılı" if self.last_nudge_ok else "başarısız"
                parts.append(
                    f"son nudge {self.last_nudge_at.strftime('%H:%M:%S')} {result}"
                )

            if self.last_cooldown_seconds is not None:
                parts.append(
                    f"son cooldown {self.last_cooldown_seconds:.1f} sn"
                )
        else:
            parts.append("Aktif")

        if self.config.prevent_sleep or self.config.keep_display_on:
            if not self.execution_state_active:
                parts.append("keep-awake uygulanamadı")

        return f"🟢 {' · '.join(parts)}"

    def status_text(
        self,
        now: datetime | None = None,
        idle: float | None = None,
    ) -> str:
        now = now or datetime.now()
        ka_text = self.keepawake_status_text(now=now, idle=idle)

        if self.config.break_reminder_enabled or self.break_tracker.state != BreakState.DISABLED:
            return f"{ka_text} · {self.break_tracker.status_text(now)}"

        return ka_text

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
        if getattr(self, "nag_dialog", None) is not None:
            self.nag_dialog.hide()
        self.tray.hide()
        self.app.quit()


def main():
    background = "--background" in sys.argv
    quit_requested = "--quit" in sys.argv

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    app.setQuitOnLastWindowClosed(False)

    if not QSystemTrayIcon.isSystemTrayAvailable():
        print(
            "Uyarı: Sistem tepsisi bulunamadı; tray simgesi görünmeyebilir "
            "(bazı Linux masaüstü ortamlarında bir uzantı gerekebilir)."
        )

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

    # Başlangıçta (Windows açılışı / Linux autostart): hiçbir pencere
    # göstermeden tray. Elle açılış: ayar penceresini göster.
    if not background:
        controller.show_settings()

    return_code = app.exec()
    clear_execution_state()
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
