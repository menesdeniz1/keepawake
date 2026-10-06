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
    )
elif sys.platform.startswith("linux"):
    from backend_linux import (
        clear_execution_state,
        get_idle_seconds,
        is_startup_enabled,
        nudge_mouse,
        set_execution_state,
        set_startup_enabled,
    )
elif sys.platform == "darwin":
    from backend_macos import (
        clear_execution_state,
        get_idle_seconds,
        is_startup_enabled,
        nudge_mouse,
        set_execution_state,
        set_startup_enabled,
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
        self.setWindowTitle(f"{APP_NAME} - Mola Zamanı")
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
        self.snooze_btn = QPushButton("5 Dakika Ertele")
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

    def on_snooze(self):
        if hasattr(self.controller, "snooze_break"):
            self.controller.snooze_break(5)
        elif hasattr(self.controller, "break_tracker"):
            self.controller.break_tracker.snooze(5)
        self.hide()

    def on_finish(self):
        if hasattr(self.controller, "start_work_now"):
            self.controller.start_work_now()
        elif hasattr(self.controller, "break_tracker"):
            self.controller.break_tracker.reset()
        self.hide()

    def closeEvent(self, event):
        event.ignore()
        self.hide()


def make_info_badge(tooltip_text: str) -> QLabel:
    badge = QLabel("ⓘ")
    badge.setCursor(Qt.CursorShape.PointingHandCursor)
    badge.setToolTip(tooltip_text)
    badge.setStyleSheet("""
        QLabel {
            color: #3b82f6;
            font-size: 13px;
            font-weight: bold;
            padding: 1px 5px;
            border-radius: 8px;
            background-color: rgba(59, 130, 246, 0.12);
        }
        QLabel:hover {
            color: #60a5fa;
            background-color: rgba(59, 130, 246, 0.28);
        }
    """)
    return badge


def make_form_row(label_text: str, widget: QWidget, tooltip_text: str | None = None) -> tuple[QWidget, QWidget]:
    if not tooltip_text:
        return QLabel(label_text), widget

    container = QWidget()
    row = QHBoxLayout(container)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(4)
    lbl = QLabel(label_text)
    badge = make_info_badge(tooltip_text)
    row.addWidget(lbl)
    row.addWidget(badge)
    row.addStretch()
    return container, widget


class SettingsWindow(QMainWindow):
    def __init__(self, controller):
        super().__init__()
        self.controller = controller

        self.setWindowTitle(f"{APP_NAME} {APP_VERSION}")
        self.setMinimumWidth(560)
        self.setMinimumHeight(520)

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)

        self.tabs = QTabWidget()

        # ==========================================
        # --- SEKME 1: KeepAwake (Uyanık Tutucu) ---
        # ==========================================
        keepawake_scroll = QScrollArea()
        keepawake_scroll.setWidgetResizable(True)
        keepawake_scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        keepawake_page = QWidget()
        keepawake_layout = QVBoxLayout(keepawake_page)
        keepawake_layout.setContentsMargins(10, 10, 10, 10)
        keepawake_layout.setSpacing(12)

        # KeepAwake Status Card (Tutarlı Üst Panel)
        ka_status_card = QGroupBox("KeepAwake Durumu")
        ka_status_card.setStyleSheet("QGroupBox { font-weight: bold; }")
        ka_status_layout = QVBoxLayout(ka_status_card)
        ka_status_layout.setSpacing(6)

        ka_header = QHBoxLayout()
        ka_title = QLabel("Çalışma Durumu:")
        ka_title.setStyleSheet("font-weight: 500;")
        self.ka_badge = QLabel("🟢 ETKİN")
        self.ka_badge.setStyleSheet("font-weight: bold; padding: 3px 10px; border-radius: 6px; background: rgba(34, 197, 94, 0.15); color: #22c55e;")
        ka_header.addWidget(ka_title)
        ka_header.addWidget(self.ka_badge)
        ka_header.addStretch()
        ka_status_layout.addLayout(ka_header)

        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet("padding: 4px 0; color: #475569;")
        ka_status_layout.addWidget(self.status_label)
        keepawake_layout.addWidget(ka_status_card)

        # Genel Grubu
        general_box = QGroupBox("Genel Yapılandırma")
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
        lbl_idle, spin_idle = make_form_row(
            "Idle eşiği:",
            self.idle_spin,
            "Kullanıcı bu süre boyunca klavye veya fareye dokunmazsa bilgisayar boşta (idle) kabul edilir."
        )
        general_form.addRow(lbl_idle, spin_idle)

        self.check_spin = QSpinBox()
        self.check_spin.setRange(1, 60)
        self.check_spin.setSuffix(" saniye")
        lbl_check, spin_check = make_form_row(
            "Kontrol sıklığı:",
            self.check_spin,
            "Zamanlayıcı ve boşta kalma kontrollerinin kaç saniyede bir tekrarlanacağı."
        )
        general_form.addRow(lbl_check, spin_check)

        keepawake_layout.addWidget(general_box)

        # Çalışma Programı Grubu
        schedule_box = QGroupBox("Çalışma Programı")
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

        time_form.addRow("Mesai Başlangıç:", self.start_edit)
        time_form.addRow("Mesai Bitiş:", self.end_edit)
        schedule_layout.addLayout(time_form)

        keepawake_layout.addWidget(schedule_box)

        # Güç Davranışı Grubu
        behavior_box = QGroupBox("Güç ve Simülasyon Davranışı")
        behavior_layout = QVBoxLayout(behavior_box)

        self.prevent_sleep_cb = QCheckBox(
            "Sistemin uykuya geçmesini engelle"
        )
        self.display_cb = QCheckBox(
            "Ekranın otomatik kapanmasını engelle"
        )

        mouse_row = QWidget()
        mouse_layout = QHBoxLayout(mouse_row)
        mouse_layout.setContentsMargins(0, 0, 0, 0)
        mouse_layout.setSpacing(6)
        self.mouse_input_cb = QCheckBox(
            "Idle eşiğinde fareyi 1 px sağa/sola hareket ettir (Nudge)"
        )
        mouse_badge = make_info_badge(
            "Mouse input yalnızca idle eşiğine ulaşıldığında 1 px sağa ve tekrar sola mikro hareket üretir.\n"
            "Bu sayede bilgisayarın kilitlenmesi veya uykuya dalması engellenir.\n"
            "Başarılı nudge sonrasında sistem belirlenen cooldown aralığında bekler."
        )
        mouse_layout.addWidget(self.mouse_input_cb)
        mouse_layout.addWidget(mouse_badge)
        mouse_layout.addStretch()

        behavior_layout.addWidget(self.prevent_sleep_cb)
        behavior_layout.addWidget(self.display_cb)
        behavior_layout.addWidget(mouse_row)

        cooldown_form = QFormLayout()

        self.cooldown_min_spin = QSpinBox()
        self.cooldown_min_spin.setRange(0, 3600)
        self.cooldown_min_spin.setSuffix(" saniye")

        self.cooldown_max_spin = QSpinBox()
        self.cooldown_max_spin.setRange(0, 3600)
        self.cooldown_max_spin.setSuffix(" saniye")

        lbl_cmin, spin_cmin = make_form_row(
            "Nudge sonrası min. cooldown:",
            self.cooldown_min_spin,
            "Bir fare hareketinden sonra en az kaç saniye boyunca yeni bir hareket üretilmeyeceği."
        )
        lbl_cmax, spin_cmax = make_form_row(
            "Nudge sonrası maks. cooldown:",
            self.cooldown_max_spin,
            "Bir fare hareketinden sonra en fazla kaç saniye boyunca yeni bir hareket üretilmeyeceği."
        )
        cooldown_form.addRow(lbl_cmin, spin_cmin)
        cooldown_form.addRow(lbl_cmax, spin_cmax)
        behavior_layout.addLayout(cooldown_form)

        keepawake_layout.addWidget(behavior_box)
        keepawake_layout.addStretch()

        keepawake_scroll.setWidget(keepawake_page)
        self.tabs.addTab(keepawake_scroll, "KeepAwake (Uyanık Tutucu)")

        # ==========================================
        # --- SEKME 2: UpNow (Mola Takipçisi) ---
        # ==========================================
        upnow_scroll = QScrollArea()
        upnow_scroll.setWidgetResizable(True)
        upnow_scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        upnow_page = QWidget()
        upnow_layout = QVBoxLayout(upnow_page)
        upnow_layout.setContentsMargins(10, 10, 10, 10)
        upnow_layout.setSpacing(12)

        # UpNow Status Card (KeepAwake ile Birebir Aynı Tasarım)
        upnow_status_card = QGroupBox("UpNow Durumu")
        upnow_status_card.setStyleSheet("QGroupBox { font-weight: bold; }")
        upnow_status_layout = QVBoxLayout(upnow_status_card)
        upnow_status_layout.setSpacing(6)

        upnow_header = QHBoxLayout()
        upnow_title = QLabel("Çalışma Durumu:")
        upnow_title.setStyleSheet("font-weight: 500;")
        self.upnow_badge = QLabel("⚪ DEVRE DIŞI")
        self.upnow_badge.setStyleSheet("font-weight: bold; padding: 3px 10px; border-radius: 6px; background: rgba(148, 163, 184, 0.15); color: #94a3b8;")
        upnow_header.addWidget(upnow_title)
        upnow_header.addWidget(self.upnow_badge)
        upnow_header.addStretch()
        upnow_status_layout.addLayout(upnow_header)

        self.upnow_status_label = QLabel()
        self.upnow_status_label.setWordWrap(True)
        self.upnow_status_label.setStyleSheet("padding: 4px 0; color: #475569;")
        upnow_status_layout.addWidget(self.upnow_status_label)
        upnow_layout.addWidget(upnow_status_card)

        # UpNow Ayarlar Grubu
        upnow_box = QGroupBox("Mola & Ayakta Kalma Yapılandırması")
        upnow_form = QFormLayout(upnow_box)

        self.break_enabled_check = QCheckBox("UpNow mola takipçisini etkinleştir")
        upnow_form.addRow(self.break_enabled_check)

        self.work_duration_spin = QSpinBox()
        self.work_duration_spin.setRange(1, 180)
        self.work_duration_spin.setSuffix(" dk")
        lbl_work, spin_work = make_form_row(
            "Çalışma süresi:",
            self.work_duration_spin,
            "Mola öncesi kesintisiz odaklanma çalışma süresi (varsayılan: 50 dakika)."
        )
        upnow_form.addRow(lbl_work, spin_work)

        self.break_duration_spin = QSpinBox()
        self.break_duration_spin.setRange(1, 60)
        self.break_duration_spin.setSuffix(" dk")
        lbl_break, spin_break = make_form_row(
            "Mola süresi:",
            self.break_duration_spin,
            "Fiziksel mola süresi (varsayılan: 10 dakika). Bu sürede masadan kalkıp esnemeniz beklenir."
        )
        upnow_form.addRow(lbl_break, spin_break)

        self.break_alert_combo = QComboBox()
        self.break_alert_combo.addItem("Nazik Bildirim (Sistem)", "notification")
        self.break_alert_combo.addItem("Zorlayıcı Mod (Uyarı Penceresi)", "nagging")
        lbl_alert, combo_alert = make_form_row(
            "Uyarı modu:",
            self.break_alert_combo,
            "Nazik Mod: Sistem bildirimi ve sesle uyarır.\nZorlayıcı Mod: Ekranda önde duran ve masadan kalkmanızı isteyen uyarı penceresi açar."
        )
        upnow_form.addRow(lbl_alert, combo_alert)

        upnow_layout.addWidget(upnow_box)

        # Hızlı Aksiyonlar Grubu
        actions_box = QGroupBox("Hızlı Mola Kontrolleri")
        actions_layout = QHBoxLayout(actions_box)
        self.tab_start_break_btn = QPushButton("Molayı Şimdi Başlat")
        self.tab_start_break_btn.clicked.connect(self.controller.start_break_now)
        actions_layout.addWidget(self.tab_start_break_btn)

        self.tab_snooze_btn = QPushButton("5 Dakika Ertele")
        self.tab_snooze_btn.clicked.connect(lambda: self.controller.snooze_break(5))
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

        self.setStyleSheet("""
            QToolTip {
                background-color: #1e1e2e;
                color: #cdd6f4;
                border: 1px solid #45475a;
                border-radius: 8px;
                padding: 8px 12px;
                font-size: 12px;
            }
            QTabBar::tab {
                padding: 8px 16px;
                font-weight: 600;
            }
            QPushButton {
                padding: 6px 14px;
                border-radius: 5px;
            }
        """)

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
        combo_idx = 1 if config.break_alert_mode == "nagging" else 0
        self.break_alert_combo.setCurrentIndex(combo_idx)

        self.refresh_status()

    def save_from_window(self):
        config = self.controller.config
        config.break_reminder_enabled = self.break_enabled_check.isChecked()
        config.work_duration_minutes = self.work_duration_spin.value()
        config.break_duration_minutes = self.break_duration_spin.value()
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
        self.refresh_status()

        QMessageBox.information(
            self,
            APP_NAME,
            "Ayarlar kaydedildi.",
        )

    def refresh_status(self):
        self.status_label.setText(self.controller.status_text())

        if hasattr(self, "ka_badge"):
            if self.controller.config.enabled:
                self.ka_badge.setText("🟢 ETKİN")
                self.ka_badge.setStyleSheet("font-weight: bold; padding: 3px 10px; border-radius: 6px; background: rgba(34, 197, 94, 0.15); color: #22c55e;")
            else:
                self.ka_badge.setText("⚪ DEVRE DIŞI")
                self.ka_badge.setStyleSheet("font-weight: bold; padding: 3px 10px; border-radius: 6px; background: rgba(148, 163, 184, 0.15); color: #94a3b8;")

        if hasattr(self, "upnow_status_label"):
            if self.controller.config.break_reminder_enabled:
                from datetime import datetime
                tracker_status = self.controller.break_tracker.status_text(datetime.now())
                self.upnow_status_label.setText(f"Mola Takipçisi Aktif: {tracker_status}")

                if hasattr(self, "upnow_badge"):
                    state = self.controller.break_tracker.state
                    if state in (BreakState.ON_BREAK, BreakState.BREAK_VIOLATION):
                        self.upnow_badge.setText("🔵 MOLADA")
                        self.upnow_badge.setStyleSheet("font-weight: bold; padding: 3px 10px; border-radius: 6px; background: rgba(59, 130, 246, 0.15); color: #3b82f6;")
                    elif state == BreakState.PAUSED:
                        self.upnow_badge.setText("🟡 DURAKLATILDI")
                        self.upnow_badge.setStyleSheet("font-weight: bold; padding: 3px 10px; border-radius: 6px; background: rgba(234, 179, 8, 0.15); color: #eab308;")
                    else:
                        self.upnow_badge.setText("🟢 ETKİN")
                        self.upnow_badge.setStyleSheet("font-weight: bold; padding: 3px 10px; border-radius: 6px; background: rgba(34, 197, 94, 0.15); color: #22c55e;")
            else:
                self.upnow_status_label.setText("UpNow Mola Takipçisi şu anda devre dışı.")
                if hasattr(self, "upnow_badge"):
                    self.upnow_badge.setText("⚪ DEVRE DIŞI")
                    self.upnow_badge.setStyleSheet("font-weight: bold; padding: 3px 10px; border-radius: 6px; background: rgba(148, 163, 184, 0.15); color: #94a3b8;")

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
        self.start_break_action.triggered.connect(self.start_break_now)
        self.menu.addAction(self.start_break_action)

        self.snooze_break_action = QAction("5 Dakika Ertele")
        self.snooze_break_action.triggered.connect(lambda: self.snooze_break(5))
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

    def start_break_now(self):
        self.break_tracker.start_break_now()
        self.tick()

    def snooze_break(self, minutes: int = 5):
        self.break_tracker.snooze(minutes)
        if (
            getattr(self, "nag_dialog", None) is not None
            and self.nag_dialog.isVisible()
        ):
            self.nag_dialog.hide()
        self.tick()

    def start_work_now(self):
        self.break_tracker.reset()
        if (
            getattr(self, "nag_dialog", None) is not None
            and self.nag_dialog.isVisible()
        ):
            self.nag_dialog.hide()
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

        self.break_tracker.tick(now, idle)
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

        status = self.status_text(now=now, idle=idle)
        self.status_action.setText(status)
        self.tray.setToolTip(f"{APP_NAME}\n{status}")

        if self.window is not None:
            self.window.refresh_status()

    def trigger_break_alert(self):
        title = f"{APP_NAME} - Mola Zamanı"
        msg = "Mola zamanı! Lütfen masadan kalkın ve hareket edin."
        if self.config.break_alert_mode == "nagging":
            if getattr(self, "nag_dialog", None) is not None:
                rem = self.break_tracker.remaining_seconds()
                minutes, seconds = divmod(rem, 60)
                self.nag_dialog.update_status(f"{minutes:02d}:{seconds:02d}")
                self.nag_dialog.show()
                self.nag_dialog.raise_()
                self.nag_dialog.activateWindow()
        else:
            if hasattr(self, "tray") and self.tray is not None:
                self.tray.showMessage(
                    title,
                    msg,
                    QSystemTrayIcon.MessageIcon.Warning,
                    5000,
                )

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
                parts.append("keep-awake açık")
            else:
                parts.append("keep-awake uygulanamadı")

        if self.config.simulate_mouse_input:
            threshold = self.config.idle_minutes * 60

            if not self.break_tracker.is_nudge_allowed():
                parts.append("mouse nudge duraklatıldı (mola)")
            elif self.cooldown_active(now):
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

        if self.config.break_reminder_enabled or self.break_tracker.state != BreakState.DISABLED:
            parts.append(self.break_tracker.status_text(now))

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
