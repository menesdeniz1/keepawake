# UpNow Mola & Ayakta Kalma Takipçisi Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** KeepAwake içine 50 dakika çalışma ve 10 dakika fiziksel mola döngüsünü denetleyen, mola anında bilgisayarda hareket olursa uyaran, isteğe bağlı (opt-in) UpNow modülünü ve macOS backend desteğini eklemek.

**Architecture:** Saf Python durum makinesi (`BreakTracker`), platform bazlı boşta kalma sorgusu (`backend_macos.py`, `backend_windows.py`, `backend_linux.py`) ve PySide6 arayüz entegrasyonu (Tray menüsü, Ayarlar sekmesi, Nagging penceresi). Mola sırasında KeepAwake'in kendi fare oynatması (nudge) kilitlenir.

**Tech Stack:** Python 3.10+, PySide6, ctypes (macOS Quartz/ApplicationServices & Windows User32), pytest.

**Spec:** `docs/superpowers/specs/2026-10-06-upnow-break-tracker-design.md`

## Global Constraints

* Varsayılan olarak kapalıdır: `break_reminder_enabled = False`.
* Mola sırasında fare hareketi (nudge) kesinlikle üretilmez (`cooldown` veya kilit mekanizması).
* macOS boşta kalma sorgusu Accessibility (Erişilebilirlik) izni gerektirmeyen `CGEventSourceSecondsSinceLastEventType` API'si ile yapılır.
* Eski `config.json` dosyaları geriye dönük hatasız yüklenir.
* Tüm adımlar TDD (önce test, sonra uygulama, sonra doğrulama) ile ilerler.

## Review Focus

* Eski `config.json` dosyasında yeni mola anahtarları yokken uygulamanın çökmeden varsayılanlarla açılması.
* Mola anında KeepAwake'in kendi mouse-nudge fonksiyonunun tetiklenmemesi ve yanlış ihlal alarmı üretmemesi.
* Bilgisayar kapağı kapatılıp açıldığında (uyku) sayaçların donmaması veya sapmaması (`datetime.now()` hedef farkı kontrolü).
* Mola ihlali sırasında ardışık sistem bildirimlerinin kullanıcıyı spam'e boğmaması (en az 60 sn cooldown).
* macOS ortamında `sys.platform == "darwin"` kontrolünün çökmeden `backend_macos` üzerinden başarıyla başlatılması.

---

### Task 1: Config Genişletmesi & BreakTracker Durum Makinesi (`core.py`)

**Files:**
- Modify: `core.py`
- Test: `tests/test_break_tracker.py`

**Interfaces:**
- Consumes: `AppConfig`, `ConfigStore`
- Produces: `BreakState` (Enum), `BreakTracker` (durum makinesi: `tick(now, idle_seconds)`, `start_break_now()`, `snooze(minutes)`, `toggle_pause()`, `status_text()`)

- [ ] **Step 1: Write the failing test for BreakTracker and AppConfig**

```python
# tests/test_break_tracker.py
from datetime import datetime, timedelta
import pytest
from core import AppConfig, BreakTracker, BreakState

def test_app_config_break_defaults():
    config = AppConfig()
    assert config.break_reminder_enabled is False
    assert config.work_duration_minutes == 50
    assert config.break_duration_minutes == 10
    assert config.break_alert_mode == "notification"

def test_break_tracker_transitions():
    config = AppConfig(break_reminder_enabled=True, work_duration_minutes=50, break_duration_minutes=10)
    start_time = datetime(2026, 10, 6, 10, 0, 0)
    tracker = BreakTracker(config, now=start_time)
    
    assert tracker.state == BreakState.WORKING
    assert tracker.remaining_seconds(start_time) == 50 * 60

    # 50 dakika sonra mola başlamalı
    break_time = start_time + timedelta(minutes=50, seconds=1)
    tracker.tick(now=break_time, idle_seconds=30.0)
    assert tracker.state == BreakState.ON_BREAK
    assert tracker.is_nudge_allowed() is False

    # Mola sırasında hareket olursa (idle < 15 sn) VIOLATION olmalı
    tracker.tick(now=break_time + timedelta(seconds=10), idle_seconds=2.0)
    assert tracker.state == BreakState.BREAK_VIOLATION
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_break_tracker.py -v`  
Expected: FAIL with `ImportError: cannot import name 'BreakTracker'`

- [ ] **Step 3: Implement BreakState, AppConfig updates, and BreakTracker in `core.py`**

Approach:
- `AppConfig` içine mola alanlarını ekle.
- `BreakState(str, Enum)` tanımla (`DISABLED`, `WORKING`, `ON_BREAK`, `BREAK_VIOLATION`, `PAUSED`).
- `BreakTracker` sınıfını `next_state_time`, `target_time`, `tick()`, `is_nudge_allowed()`, `snooze()`, `start_break_now()` metotlarıyla uygula.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_break_tracker.py tests/test_core.py -v`  
Expected: PASS (tüm mola testleri ve mevcut core testleri yeşil)

- [ ] **Step 5: Commit**

```bash
git add core.py tests/test_break_tracker.py
git commit -m "feat(core): add UpNow break tracker state machine and config schema"
```

---

### Task 2: macOS Platform Backend Desteği (`backend_macos.py`)

**Files:**
- Create: `backend_macos.py`
- Test: `tests/test_backend_macos.py`

**Interfaces:**
- Consumes: `core.APP_NAME`
- Produces: `get_idle_seconds() -> float`, `nudge_mouse() -> bool`, `set_execution_state(prevent_sleep, keep_display) -> None`, `clear_execution_state() -> None`, `is_startup_enabled() -> bool`, `set_startup_enabled(enabled) -> None`

- [ ] **Step 1: Write the failing test for backend_macos**

```python
# tests/test_backend_macos.py
import sys
import pytest

@pytest.mark.skipif(sys.platform != "darwin", reason="Yalnızca macOS üzerinde test edilir")
def test_macos_get_idle_seconds_type():
    import backend_macos
    idle = backend_macos.get_idle_seconds()
    assert isinstance(idle, float)
    assert idle >= 0.0

@pytest.mark.skipif(sys.platform != "darwin", reason="Yalnızca macOS üzerinde test edilir")
def test_macos_execution_state_toggle():
    import backend_macos
    backend_macos.set_execution_state(prevent_sleep=True, keep_display_on=True)
    backend_macos.clear_execution_state()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_backend_macos.py -v`  
Expected: FAIL with `ModuleNotFoundError: No module named 'backend_macos'`

- [ ] **Step 3: Implement `backend_macos.py`**

Approach:
- `get_idle_seconds()`: `ctypes` ile `ApplicationServices.framework` üzerinden `CGEventSourceSecondsSinceLastEventType`.
- `set_execution_state()` / `clear_execution_state()`: `caffeinate -d -i` alt sürecini başlatıp durdurma.
- `nudge_mouse()`: `CGEventCreateMouseEvent` ve `CGEventPost` ile mikro hareket.
- `is_startup_enabled()` / `set_startup_enabled()`: `~/Library/LaunchAgents/` plist kontrolü.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_backend_macos.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend_macos.py tests/test_backend_macos.py
git commit -m "feat(platform): add macOS backend with Quartz idle tracking and caffeinate"
```

---

### Task 3: Controller Koordinasyonu & Mola-Nudge Kilidi (`app.py`)

**Files:**
- Modify: `app.py`
- Test: `tests/test_controller_break.py`

**Interfaces:**
- Consumes: `BreakTracker`, `backend_macos` (darwin), `backend_windows` (win32), `backend_linux` (linux)
- Produces: `KeepAwakeController` koordinasyonu (mola durumunda `nudge_mouse` çalıştırmama, canlı süre güncelleme, mola ihlali sinyalleri)

- [ ] **Step 1: Write the failing test for Controller break coordination**

```python
# tests/test_controller_break.py
from unittest.mock import MagicMock, patch
from core import AppConfig, BreakState

def test_controller_suppresses_nudge_during_break():
    # BreakState.ON_BREAK iken nudge_mouse çağrılmadığını doğrula
    pass
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_controller_break.py -v`  
Expected: FAIL

- [ ] **Step 3: Implement Controller coordination in `app.py`**

Approach:
- Platform importuna `elif sys.platform == "darwin": from backend_macos import ...` ekle.
- `KeepAwakeController.__init__`: `self.break_tracker = BreakTracker(self.config)` bağla.
- `tick()` metodunda: eğer `self.break_tracker.is_nudge_allowed() is False` ise fare oynatma kodunu atla.
- Mola ihlali oluştuğunda seçilen moda (`notification` vs `nagging`) göre bildirim/diyalog tetikle.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_controller_break.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app.py tests/test_controller_break.py
git commit -m "feat(app): integrate BreakTracker into controller with anti-nudge coordination"
```

---

### Task 4: Kullanıcı Arayüzü: Tray Menüsü, Ayarlar ve Nagging Diyaloğu (`app.py`)

**Files:**
- Modify: `app.py`
- Test: `tests/test_ui_break.py`

**Interfaces:**
- Consumes: `KeepAwakeController`, `AppConfig`
- Produces: `BreakNagDialog(QDialog)`, `SettingsWindow` UpNow grubu, Tray menüsü mola aksiyonları

- [ ] **Step 1: Write the failing test for UI components**

```python
# tests/test_ui_break.py
# BreakNagDialog açılış ve kalan süre etiket testi, Ayarlar kaydetme testi
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_ui_break.py -v`  
Expected: FAIL

- [ ] **Step 3: Implement UI components in `app.py`**

Approach:
- `BreakNagDialog`: `Qt.WindowStaysOnTopHint`, koyu tema, geri sayım etiketi, "5 Dk Ertele" ve "Molayı Bitir" butonları.
- `SettingsWindow`: "UpNow - Mola & Ayakta Kalma Takipçisi" QGroupBox; checkbox, çalışma/mola spinbox'ları ve uyarı stili seçimi.
- `QSystemTrayIcon`: Menüye "Mola Takipçisi Etkin", "Molayı Şimdi Başlat", "5 Dk Ertele" aksiyonları ve dinamik durum metni.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_ui_break.py tests/test_app_smoke.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app.py tests/test_ui_break.py
git commit -m "feat(ui): add UpNow tray actions, settings controls, and BreakNagDialog"
```

---

### Task 5: Tam Entegrasyon ve Doğrulama (Full Verification & Smoke Test)

**Files:**
- Test: Tüm testler (`tests/`)

- [ ] **Step 1: Run full test suite**

Run: `pytest tests/ -v`  
Expected: 100% PASS

- [ ] **Step 2: Run manual headless smoke check**

Run: `python3 -c "import app, core; print('Imports and syntax valid')"`  
Expected: Output `Imports and syntax valid`

- [ ] **Step 3: Final commit & documentation update in README.md**

```bash
git add README.md
git commit -m "docs: document UpNow break tracker feature and macOS support"
```
