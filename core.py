"""Platform bağımsız çekirdek: config, zamanlama ve sürüm karşılaştırma mantığı.

Bu modül kasıtlı olarak Qt'ye ve işletim sistemine özgü hiçbir şeye bağımlı
değil, böylece herhangi bir platformda (GUI kurulu olmadan bile) test
edilebilir.
"""

import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, time as dt_time
from pathlib import Path

APP_NAME = "KeepAwake"
APP_VERSION = "1.3.1"

DAY_KEYS = [
    "monday", "tuesday", "wednesday", "thursday",
    "friday", "saturday", "sunday",
]
DAY_LABELS_TR = ["Pzt", "Sal", "Çar", "Per", "Cum", "Cmt", "Paz"]


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


def parse_version(text: str) -> tuple[int, ...]:
    return tuple(int(part) for part in text.strip().split("."))


def is_newer(remote_version: str, current_version: str) -> bool:
    return parse_version(remote_version) > parse_version(current_version)
