"""Platform bağımsız çekirdek: config, zamanlama ve sürüm karşılaştırma mantığı.

Bu modül kasıtlı olarak Qt'ye ve işletim sistemine özgü hiçbir şeye bağımlı
değil, böylece herhangi bir platformda (GUI kurulu olmadan bile) test
edilebilir.
"""

import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, time as dt_time, timedelta
from enum import Enum
from pathlib import Path

APP_NAME = "KeepAwake"
APP_VERSION = "1.3.2"

DAY_KEYS = [
    "monday", "tuesday", "wednesday", "thursday",
    "friday", "saturday", "sunday",
]
DAY_LABELS_TR = ["Pzt", "Sal", "Çar", "Per", "Cum", "Cmt", "Paz"]


def _safe_hhmm_str(val: str, default: str) -> str:
    try:
        parts = str(val).split(":")
        if len(parts) == 2:
            h, m = int(parts[0]), int(parts[1])
            if 0 <= h <= 23 and 0 <= m <= 59:
                return f"{h:02d}:{m:02d}"
    except Exception:
        pass
    return default


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

    # UpNow Mola Takipçisi Alanları (Varsayılan: Kapalı)
    break_reminder_enabled: bool = False
    work_duration_minutes: int = 50
    break_duration_minutes: int = 10
    break_snooze_minutes: int = 5
    break_extend_minutes: int = 5
    break_alert_mode: str = "notification"  # "notification" veya "nagging"
    break_violation_threshold_seconds: int = 15
    break_alert_cooldown_seconds: int = 60
    break_floating_timer_enabled: bool = True

    def __post_init__(self):
        # Durations & interval validation (strictly positive)
        self.work_duration_minutes = max(1, int(self.work_duration_minutes))
        self.break_duration_minutes = max(1, int(self.break_duration_minutes))
        self.break_snooze_minutes = max(1, int(self.break_snooze_minutes))
        self.break_extend_minutes = max(1, int(self.break_extend_minutes))
        self.idle_minutes = max(1, int(self.idle_minutes))
        self.check_interval_seconds = max(1, int(self.check_interval_seconds))
        self.break_violation_threshold_seconds = max(1, int(self.break_violation_threshold_seconds))
        self.break_alert_cooldown_seconds = max(1, int(self.break_alert_cooldown_seconds))

        # Cooldown bounds validation
        self.cooldown_min_seconds = max(1, int(self.cooldown_min_seconds))
        self.cooldown_max_seconds = max(1, int(self.cooldown_max_seconds))
        if self.cooldown_min_seconds > self.cooldown_max_seconds:
            self.cooldown_min_seconds, self.cooldown_max_seconds = (
                self.cooldown_max_seconds,
                self.cooldown_min_seconds,
            )

        # Time format validation
        self.start_time = _safe_hhmm_str(self.start_time, "08:30")
        self.end_time = _safe_hhmm_str(self.end_time, "17:30")

        if self.days is None or not isinstance(self.days, list):
            self.days = DAY_KEYS[:5]
        else:
            self.days = [d for d in self.days if d in DAY_KEYS]


class BreakState(str, Enum):
    DISABLED = "disabled"
    WORKING = "working"
    ON_BREAK = "on_break"
    BREAK_VIOLATION = "break_violation"
    PAUSED = "paused"


class BreakTracker:
    def __init__(self, config: AppConfig, now: datetime | None = None):
        self.config = config
        self.state: BreakState = BreakState.DISABLED
        self.target_time: datetime | None = None
        self._last_alert_time: datetime | None = None
        self._last_tick_time: datetime | None = None
        self._paused_state: BreakState | None = None
        self._paused_remaining_seconds: float = 0.0

        current = now or datetime.now()
        self._last_tick_time = current
        if self.config.break_reminder_enabled:
            self._start_working(current)
        else:
            self.state = BreakState.DISABLED

    @property
    def next_state_time(self) -> datetime | None:
        return self.target_time

    def _start_working(self, now: datetime) -> None:
        self.state = BreakState.WORKING
        self.target_time = now + timedelta(minutes=self.config.work_duration_minutes)
        self._last_alert_time = None

    def _start_break(self, now: datetime) -> None:
        self.state = BreakState.ON_BREAK
        self.target_time = now + timedelta(minutes=self.config.break_duration_minutes)
        self._last_alert_time = None

    def start_break_now(self, now: datetime | None = None) -> None:
        current = now or datetime.now()
        self._start_break(current)

    def extend_work(self, minutes: int | None = None, now: datetime | None = None) -> None:
        """Çalışmayı uzatır (molaya girmeyi erteler)."""
        if minutes is None:
            minutes = getattr(self.config, "break_snooze_minutes", 5)
        current = now or datetime.now()
        if self.state == BreakState.PAUSED:
            self._paused_state = BreakState.WORKING
            self._paused_remaining_seconds += minutes * 60
            return

        was_working = self.state == BreakState.WORKING
        self.state = BreakState.WORKING
        self._last_alert_time = None
        if was_working and self.target_time is not None and self.target_time > current:
            self.target_time += timedelta(minutes=minutes)
        else:
            self.target_time = current + timedelta(minutes=minutes)

    def extend_break(self, minutes: int | None = None, now: datetime | None = None) -> None:
        """Molayı uzatır (çalışmaya dönmeyi erteler)."""
        if minutes is None:
            minutes = getattr(self.config, "break_extend_minutes", 5)
        current = now or datetime.now()
        if self.state == BreakState.PAUSED:
            self._paused_state = BreakState.ON_BREAK
            self._paused_remaining_seconds += minutes * 60
            return

        was_on_break = self.state in (BreakState.ON_BREAK, BreakState.BREAK_VIOLATION)
        self.state = BreakState.ON_BREAK
        self._last_alert_time = None
        if was_on_break and self.target_time is not None and self.target_time > current:
            self.target_time += timedelta(minutes=minutes)
        else:
            self.target_time = current + timedelta(minutes=minutes)

    def snooze(self, minutes: int | None = None, now: datetime | None = None) -> None:
        if minutes is None:
            minutes = getattr(self.config, "break_snooze_minutes", 5)
        current = now or datetime.now()
        if self.state in (BreakState.ON_BREAK, BreakState.BREAK_VIOLATION):
            self.state = BreakState.WORKING
            self.target_time = current + timedelta(minutes=minutes)
            self._last_alert_time = None
        elif self.state == BreakState.WORKING:
            if self.target_time is not None and self.target_time > current:
                self.target_time += timedelta(minutes=minutes)
            else:
                self.target_time = current + timedelta(minutes=minutes)
        elif self.state == BreakState.PAUSED:
            self._paused_state = BreakState.WORKING
            self._paused_remaining_seconds += minutes * 60

    def toggle_pause(self, now: datetime | None = None) -> bool:
        current = now or datetime.now()
        if self.state != BreakState.PAUSED:
            self._paused_remaining_seconds = self.remaining_seconds(current)
            self._paused_state = self.state
            self.state = BreakState.PAUSED
            return True
        else:
            self.state = self._paused_state or (
                BreakState.WORKING if self.config.break_reminder_enabled else BreakState.DISABLED
            )
            self.target_time = current + timedelta(seconds=self._paused_remaining_seconds)
            self._paused_state = None
            return False

    def is_nudge_allowed(self) -> bool:
        return self.state not in (BreakState.ON_BREAK, BreakState.BREAK_VIOLATION)

    def remaining_seconds(self, now: datetime | None = None) -> int:
        if self.state == BreakState.PAUSED:
            return max(0, int(self._paused_remaining_seconds))
        if self.target_time is None:
            return 0
        current = now or datetime.now()
        diff = (self.target_time - current).total_seconds()
        return max(0, int(diff))

    def tick(self, now: datetime | None = None, idle_seconds: float = 0.0) -> None:
        if not self.config.break_reminder_enabled:
            self.state = BreakState.DISABLED
            self.target_time = None
            return

        current = now or datetime.now()

        # Handle system clock rollback (NTP sync / DST change)
        if self._last_tick_time is not None and current < self._last_tick_time:
            backward_jump = self._last_tick_time - current
            if self.target_time is not None:
                self.target_time -= backward_jump
            if self._last_alert_time is not None and self._last_alert_time > current:
                self._last_alert_time -= backward_jump

        self._last_tick_time = current

        if self.state == BreakState.DISABLED:
            self._start_working(current)
            return

        if self.state == BreakState.PAUSED:
            return

        if self.state == BreakState.WORKING:
            if self.target_time is not None and current >= self.target_time:
                self._start_break(current)
                if idle_seconds < self.config.break_violation_threshold_seconds:
                    self.state = BreakState.BREAK_VIOLATION
        elif self.state in (BreakState.ON_BREAK, BreakState.BREAK_VIOLATION):
            if self.target_time is not None and current >= self.target_time:
                self._start_working(current)
            else:
                if idle_seconds < self.config.break_violation_threshold_seconds:
                    self.state = BreakState.BREAK_VIOLATION
                else:
                    self.state = BreakState.ON_BREAK

    def should_alert(self, now: datetime | None = None) -> bool:
        if self.state != BreakState.BREAK_VIOLATION:
            return False
        current = now or datetime.now()
        if self._last_alert_time is None:
            return True
        cooldown = self.config.break_alert_cooldown_seconds
        return (current - self._last_alert_time).total_seconds() >= cooldown

    def record_alert(self, now: datetime | None = None) -> None:
        self._last_alert_time = now or datetime.now()

    def status_text(self, now: datetime | None = None) -> str:
        if self.state == BreakState.DISABLED:
            return "Mola Takibi: Devre Dışı"
        if self.state == BreakState.PAUSED:
            return "Mola Takibi: Duraklatıldı"

        rem = self.remaining_seconds(now)
        if self.state == BreakState.WORKING:
            if rem >= 3600:
                hours, remainder = divmod(rem, 3600)
                minutes, seconds = divmod(remainder, 60)
                time_str = f"{hours}:{minutes:02d}:{seconds:02d}"
            else:
                minutes, seconds = divmod(rem, 60)
                time_str = f"{minutes:02d}:{seconds:02d}"
            return f"Odaklanma: {time_str} kaldı"
        else:
            minutes, seconds = divmod(rem, 60)
            time_str = f"{minutes:02d}:{seconds:02d}"
            return f"Mola Vakti: {time_str} kaldı (Masadan Kalk!)"

    def update_config(self, config: AppConfig, now: datetime | None = None, current: datetime | None = None) -> None:
        curr = current or now or datetime.now()
        was_enabled = self.config.break_reminder_enabled
        old_work_duration = self.config.work_duration_minutes
        old_break_duration = self.config.break_duration_minutes
        self.config = config
        if not config.break_reminder_enabled:
            self.state = BreakState.DISABLED
            self.target_time = None
        elif not was_enabled and config.break_reminder_enabled:
            self._start_working(curr)
        else:
            # Active state duration reconciliation based on elapsed time
            if self.state == BreakState.WORKING and self.target_time is not None:
                started_at = self.target_time - timedelta(minutes=old_work_duration)
                self.target_time = started_at + timedelta(minutes=config.work_duration_minutes)
            elif self.state in (BreakState.ON_BREAK, BreakState.BREAK_VIOLATION) and self.target_time is not None:
                started_at = self.target_time - timedelta(minutes=old_break_duration)
                self.target_time = started_at + timedelta(minutes=config.break_duration_minutes)

    def reset(self, now: datetime | None = None) -> None:
        current = now or datetime.now()
        if self.config.break_reminder_enabled:
            self._start_working(current)
        else:
            self.state = BreakState.DISABLED
            self.target_time = None



class ConfigStore:
    def __init__(self, path: Path | None = None):
        if path is not None:
            self.path = Path(path)
            self.dir = self.path.parent
        else:
            self.dir = self._config_dir()
            self.path = self.dir / "config.json"

    @staticmethod
    def _config_dir() -> Path:
        appdata = os.environ.get("APPDATA")
        if appdata:
            return Path(appdata) / APP_NAME

        xdg_config = os.environ.get("XDG_CONFIG_HOME")
        if xdg_config:
            return Path(xdg_config) / APP_NAME

        return Path.home() / ".config" / APP_NAME

    def load(self) -> AppConfig:
        if not self.path.exists():
            return AppConfig()

        try:
            content = self.path.read_text(encoding="utf-8")
            data = json.loads(content)
            if not isinstance(data, dict):
                raise ValueError("Config JSON must be a dictionary")
            allowed = set(AppConfig.__dataclass_fields__.keys())
            filtered = {k: v for k, v in data.items() if k in allowed}
            return AppConfig(**filtered)
        except Exception:
            try:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                backup_path = self.path.with_name(f"config.json.corrupt.{timestamp}")
                self.path.replace(backup_path)
            except Exception:
                pass
            return AppConfig()

    def save(self, config: AppConfig) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(".tmp")
        temp.write_text(
            json.dumps(asdict(config), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        if os.name == "posix":
            try:
                os.chmod(temp, 0o600)
            except OSError:
                pass
        temp.replace(self.path)
        if os.name == "posix":
            try:
                os.chmod(self.path, 0o600)
            except OSError:
                pass


def parse_hhmm(value: str) -> dt_time:
    try:
        parts = str(value).split(":")
        if len(parts) == 2:
            h, m = int(parts[0]), int(parts[1])
            if 0 <= h <= 23 and 0 <= m <= 59:
                return dt_time(hour=h, minute=m)
    except Exception:
        pass
    return dt_time(hour=9, minute=0)


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


def parse_version(text: str) -> tuple[int, ...]:
    return tuple(int(part) for part in text.strip().split("."))


def is_newer(remote_version: str, current_version: str) -> bool:
    return parse_version(remote_version) > parse_version(current_version)
