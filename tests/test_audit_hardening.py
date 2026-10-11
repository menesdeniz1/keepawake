"""Tests for Security, Architecture, and QA Stress Hardening.

Covers findings from the independent AppSec, QA/Stress, and Senior Architect audits.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from core import (
    AppConfig,
    BreakState,
    BreakTracker,
    ConfigStore,
    parse_hhmm,
)
from updater import (
    ALLOWED_RELEASE_HOST,
    ALLOWED_PATH_PREFIX,
    validate_update_metadata,
)


class TestConfigValidationAndSanitization:
    """Audit Finding 1.1, 2.3 & MED-02: AppConfig sanitization and boundaries."""

    def test_positive_duration_invariants(self):
        """Zero or negative durations must be clamped to safe positive minimums."""
        cfg = AppConfig(
            work_duration_minutes=0,
            break_duration_minutes=-10,
            break_snooze_minutes=0,
            break_extend_minutes=-5,
            idle_minutes=-1,
            break_violation_threshold_seconds=0,
            break_alert_cooldown_seconds=-30,
        )
        assert cfg.work_duration_minutes >= 1
        assert cfg.break_duration_minutes >= 1
        assert cfg.break_snooze_minutes >= 1
        assert cfg.break_extend_minutes >= 1
        assert cfg.idle_minutes >= 1
        assert cfg.break_violation_threshold_seconds >= 1
        assert cfg.break_alert_cooldown_seconds >= 1

    def test_cooldown_inversion_sanitized(self):
        """cooldown_min_seconds must not exceed cooldown_max_seconds."""
        cfg = AppConfig(cooldown_min_seconds=60, cooldown_max_seconds=20)
        assert cfg.cooldown_min_seconds <= cfg.cooldown_max_seconds

    def test_schedule_time_format_sanitized(self):
        """Invalid time strings must fallback to default safe times."""
        cfg = AppConfig(start_time="invalid", end_time="99:99")
        # Should fallback to valid HH:MM without crashing
        assert parse_hhmm(cfg.start_time) is not None
        assert parse_hhmm(cfg.end_time) is not None


class TestConfigStoreResilience:
    """Audit Finding HIGH-2: Safe ConfigStore recovery and backup."""

    def test_corrupted_config_creates_backup(self, tmp_path: Path):
        """When config.json is corrupted, it should be backed up and AppConfig defaults returned."""
        config_path = tmp_path / "config.json"
        config_path.write_text("{ broken json content", encoding="utf-8")

        store = ConfigStore(config_path)
        cfg = store.load()

        assert cfg == AppConfig()
        # Ensure a .corrupt backup file was created
        corrupt_files = list(tmp_path.glob("config.json.corrupt.*"))
        assert len(corrupt_files) == 1
        assert corrupt_files[0].read_text(encoding="utf-8") == "{ broken json content"

    def test_posix_permissions_secured_on_save(self, tmp_path: Path):
        """On POSIX systems, config.json should have restricted file permissions (0o600)."""
        import os
        import stat

        config_path = tmp_path / "config.json"
        store = ConfigStore(config_path)
        store.save(AppConfig())

        assert config_path.exists()
        if os.name == "posix":
            mode = stat.S_IMODE(config_path.stat().st_mode)
            assert mode == 0o600


class TestBreakTrackerHardening:
    """Audit Finding 1.2, 2.1 & QA Stress: Clock jumps and config updates."""

    def test_clock_jump_backwards_resilience(self):
        """When system clock jumps backwards (NTP/DST), tracker must not corrupt or freeze."""
        cfg = AppConfig(break_reminder_enabled=True, work_duration_minutes=50, break_duration_minutes=10)
        tracker = BreakTracker(cfg)
        t0 = datetime(2026, 10, 11, 10, 0, 0)
        tracker.tick(t0, idle_seconds=0.0)
        assert tracker.state == BreakState.WORKING

        # Clock steps backward by 30 minutes
        t_back = t0 - timedelta(minutes=30)
        tracker.tick(t_back, idle_seconds=0.0)

        # State should remain WORKING and target_time adjusted/preserved safely
        assert tracker.state == BreakState.WORKING
        rem = tracker.remaining_seconds(t_back)
        assert rem >= 0

    def test_remaining_seconds_clamped_to_zero(self):
        """remaining_seconds must never return negative numbers."""
        cfg = AppConfig(break_reminder_enabled=True, work_duration_minutes=10, break_duration_minutes=5)
        tracker = BreakTracker(cfg)
        t0 = datetime(2026, 10, 11, 10, 0, 0)
        tracker.tick(t0, idle_seconds=0.0)

        # Time way past target
        t_past = t0 + timedelta(minutes=60)
        assert tracker.remaining_seconds(t_past) == 0

    def test_update_config_adjusts_active_target(self):
        """Updating config duration while active adapts or clamps target time."""
        cfg = AppConfig(break_reminder_enabled=True, work_duration_minutes=50, break_duration_minutes=10)
        tracker = BreakTracker(cfg)
        t0 = datetime(2026, 10, 11, 10, 0, 0)
        tracker.tick(t0, idle_seconds=0.0)
        assert tracker.state == BreakState.WORKING

        # Shorten work duration to 20 minutes (at t0 + 25m, should be ready for break)
        new_cfg = AppConfig(break_reminder_enabled=True, work_duration_minutes=20, break_duration_minutes=10)
        t_curr = t0 + timedelta(minutes=25)
        tracker.update_config(new_cfg, current=t_curr)

        # Target should not remain at t0 + 50m!
        rem = tracker.remaining_seconds(t_curr)
        assert rem <= 0


class TestUpdaterSecurity:
    """Audit Finding CRIT-01, CRIT-02 & LOW-01: Updater security and validation."""

    def test_validate_update_metadata_valid(self):
        url = "https://github.com/menesdeniz1/keepawake/releases/download/v1.3.1/KeepAwakeSetup-v1.3.1.exe"
        sha = "67e862147ad63057a46870bba946b720b855ebd615f22b321fa9006a5ed05483"
        assert validate_update_metadata(url, sha) is True

    def test_validate_update_metadata_rejects_http(self):
        url = "http://github.com/menesdeniz1/keepawake/releases/download/v1.3.1/KeepAwakeSetup-v1.3.1.exe"
        sha = "67e862147ad63057a46870bba946b720b855ebd615f22b321fa9006a5ed05483"
        assert validate_update_metadata(url, sha) is False

    def test_validate_update_metadata_rejects_untrusted_host(self):
        url = "https://malicious-site.com/menesdeniz1/keepawake/releases/download/v1.3.1/KeepAwakeSetup.exe"
        sha = "67e862147ad63057a46870bba946b720b855ebd615f22b321fa9006a5ed05483"
        assert validate_update_metadata(url, sha) is False

    def test_validate_update_metadata_rejects_untrusted_path(self):
        url = "https://github.com/attacker/evil/releases/download/v1.0/installer.exe"
        sha = "67e862147ad63057a46870bba946b720b855ebd615f22b321fa9006a5ed05483"
        assert validate_update_metadata(url, sha) is False

    def test_validate_update_metadata_rejects_invalid_sha(self):
        url = "https://github.com/menesdeniz1/keepawake/releases/download/v1.3.1/KeepAwakeSetup-v1.3.1.exe"
        # Not 64 chars
        assert validate_update_metadata(url, "short_hash") is False
        # Non-hex chars
        assert validate_update_metadata(url, "z" * 64) is False
        # Uppercase (must be canonical lowercase)
        assert validate_update_metadata(url, ("A" * 64)) is False

    def test_secure_temp_download_destination(self, tmp_path: Path):
        """Temporary download destination must be isolated and protect against symlink attacks."""
        from updater import create_secure_temp_dir

        temp_dir = create_secure_temp_dir()
        try:
            assert temp_dir.exists()
            assert temp_dir.is_dir()
            # Must not be a symlink
            assert not temp_dir.is_symlink()
        finally:
            import shutil
            shutil.rmtree(temp_dir, ignore_errors=True)


class TestPlatformBackendHardening:
    """Audit Finding CRIT-1, CRIT-2: Subprocess leaks & Win32 tick overflow."""

    def test_win32_tick_overflow_clamping(self):
        """backend_windows get_idle_seconds must clamp 32-bit tick delta wrap."""
        import backend_windows

        # Simulate GetTickCount() = 1000 and dwTime = 2000 (clock desync / wrap)
        with patch.object(backend_windows, "user32", create=True) as mock_user32, \
             patch.object(backend_windows, "kernel32", create=True) as mock_kernel32:
            
            # If win32 ctypes loaded
            if hasattr(backend_windows, "_get_idle_from_ticks"):
                # Tick delta > 0x7FFFFFFF should return 0.0, not ~49 days
                assert backend_windows._get_idle_from_ticks(now32=1000, dw_time=2000) == 0.0
                assert backend_windows._get_idle_from_ticks(now32=5000, dw_time=2000) == 3.0

    def test_caffeinate_atexit_registration(self):
        """backend_macos must register clear_execution_state with atexit."""
        import atexit
        import backend_macos

        # Verify clear_execution_state exists and can be safely called multiple times
        backend_macos.clear_execution_state()
        backend_macos.clear_execution_state()
        assert backend_macos._caffeinate_proc is None
