# UpNow Yüzen Canlı Sayaç Kapsülü (Floating Pill Timer) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Mola sırasında ekranın sağ üstünde yüzen, pencereleri kapatmayan, sürüklenebilen, canlı geri sayım ve hızlı aksiyon butonlarını (`+Uzat`, `Ertele`, `Acil Bitir`) barındıran modern bir kapsül widget (`BreakFloatingPill`) eklemek.

**Architecture:** PySide6 tabanlı `BreakFloatingPill(QWidget)` oluşturularak `KeepAwakeController` yaşam döngüsüne bağlanır. Mola başladığında ve uzatıldığında ekranda belirip canlı geri sayımı yürütür; mola bitince veya ertelenince kendiliğinden kaybolur. Yapılandırma `AppConfig.break_floating_timer_enabled` ile yönetilir ve `SettingsWindow` içerisinden açılıp kapatılabilir.

**Tech Stack:** Python 3.14, PySide6 (Qt6 Widgets, FramelessWindow, TranslucentBackground), pytest, macOS/Win/Linux cross-platform.

**Spec:** [docs/superpowers/specs/2026-10-06-upnow-floating-pill-timer-design.md](../specs/2026-10-06-upnow-floating-pill-timer-design.md)

## Global Constraints

- Varsayılan olarak etkindir: `break_floating_timer_enabled: bool = True`.
- Kapsül pencere odağını çalmaz (`Qt.WindowType.WindowDoesNotAcceptFocus`).
- Görev çubuğunda/Dock'ta ayrı ikon oluşturmaz (`Qt.WindowType.Tool`).
- Çapraz platform uyumluluğu: macOS, Windows ve Linux'ta pürüzsüz çalışır.
- Eski `config.json` dosyaları geriye dönük hatasız yüklenir (`getattr(config, "break_floating_timer_enabled", True)`).

## Review Focus

- Odak çalmama: Kapsül açıldığında veya butonlarına tıklandığında kullanıcının klavye odağını aktif pencereden çalmaması.
- Yaşam döngüsü senkronizasyonu: Mola bittiğinde veya ertelendiğinde kapsülün ekranda asılı kalmaması (`hide()`).
- Sürüklenebilirlik sınırları: Ekran dışına kaçmadan sürüklenebilmesi.
- Buton aksiyonlarının doğruluğu: `+Uzat` (mola uzatma), `Ertele` (çalışma uzatma), `Acil Bitir` (hemen çalışma başlatma).
- Ayarlar penceresi kaydetme/yükleme turunun (round-trip) hatasız çalışması.

---

### Task 1: Veri Modeli Genişletmesi (`core.py`)

**Files:**
- Modify: `core.py`
- Test: `tests/test_break_tracker.py`

- [ ] **Step 1: Test yazımı**
  `tests/test_break_tracker.py` içine `break_floating_timer_enabled` alanının varsayılan olarak `True` geldiğini ve `ConfigStore` üzerinden serileştirilip yüklendiğini doğrulayan test ekle.

- [ ] **Step 2: Testi çalıştır ve başarısız olduğunu doğrula**
  `.venv/bin/pytest tests/test_break_tracker.py -k test_app_config_floating_timer -v`

- [ ] **Step 3: `core.py` implementasyonu**
  `AppConfig` sınıfına `break_floating_timer_enabled: bool = True` ekle.

- [ ] **Step 4: Testleri doğrula**
  `.venv/bin/pytest tests/test_break_tracker.py -v`

- [ ] **Step 5: Commit**
  `git commit -am "feat(core): add break_floating_timer_enabled to AppConfig"`

---

### Task 2: Yüzen Sayaç Kapsülü Bileşeni (`BreakFloatingPill`) (`app.py`)

**Files:**
- Modify: `app.py`
- Test: `tests/test_ui_break.py`

- [ ] **Step 1: Test yazımı**
  `tests/test_ui_break.py` içinde `test_break_floating_pill_properties_and_actions` testi yaz:
  - `BreakFloatingPill` sınıfının varlığı, window flags (`FramelessWindowHint`, `WindowStaysOnTopHint`, `Tool`, `WindowDoesNotAcceptFocus`), `WA_TranslucentBackground`.
  - Bileşenlerin varlığı: `timer_label`, `extend_btn`, `snooze_btn`, `emergency_btn`, `close_btn`.
  - Buton tıklamalarının controller çağrıları (`extend_break`, `extend_work`, `start_work_now`).
  - `update_status("04:35")` güncellemesi.

- [ ] **Step 2: Testi çalıştır ve başarısız olduğunu doğrula**
  `.venv/bin/pytest tests/test_ui_break.py -k test_break_floating_pill -v`

- [ ] **Step 3: `BreakFloatingPill` implementasyonu**
  `app.py` içine `BreakFloatingPill(QWidget)` sınıfını ekle:
  - Koyu yarı saydam kapsül kartı (`QFrame#pillFrame`).
  - Canlı sayaç etiketi ve şık butonlar.
  - Sürükleme fonksiyonları (`mousePressEvent`, `mouseMoveEvent`, `mouseReleaseEvent`).
  - Ekranın sağ üstüne yerleşim (`reposition`).

- [ ] **Step 4: Testleri doğrula**
  `.venv/bin/pytest tests/test_ui_break.py -k test_break_floating_pill -v`

- [ ] **Step 5: Commit**
  `git commit -am "feat(ui): implement BreakFloatingPill widget with draggable capsule and actions"`

---

### Task 3: Controller Yaşam Döngüsü ve Ayarlar Entegrasyonu (`app.py`)

**Files:**
- Modify: `app.py`
- Test: `tests/test_ui_break.py`

- [ ] **Step 1: Test yazımı**
  `tests/test_ui_break.py` içine:
  - `test_controller_floating_pill_lifecycle`: Mola başlayınca kapsülün açılması, mola bitince/ertelenince kapanması.
  - `test_settings_window_floating_pill_toggle`: `SettingsWindow` içinde kapsül checkbox'ının yer alması, yüklenmesi ve kaydedilmesi.

- [ ] **Step 2: Testi çalıştır ve başarısız olduğunu doğrula**
  `.venv/bin/pytest tests/test_ui_break.py -k "floating_pill_lifecycle or floating_pill_toggle" -v`

- [ ] **Step 3: Controller & SettingsWindow implementasyonu**
  - `KeepAwakeController.__init__`: `self.floating_pill = BreakFloatingPill(self)`.
  - `KeepAwakeController.tick`: Mola durumunda sayaç güncelleme ve görünürlük yönetimi.
  - `notify_break_started`: Kapsülü aç.
  - `notify_break_finished`, `extend_work`, `start_work_now`: Kapsülü gizle.
  - `SettingsWindow`: `break_floating_check` checkbox'ını UpNow sekmesine ekle, `load_from_config` ve `save_from_window` içine bağla.

- [ ] **Step 4: Tüm testleri doğrula**
  `.venv/bin/pytest tests/ -v`

- [ ] **Step 5: Commit**
  `git commit -am "feat(app): integrate BreakFloatingPill into controller lifecycle and settings"`

---

### Task 4: Tam Doğrulama ve Canlı Test

**Files:**
- Test: Tüm testler (`tests/`)

- [ ] **Step 1: Tüm test paketini çalıştır**
  `.venv/bin/pytest tests/ -v` (Tüm testlerin yeşil olduğunu teyit et).

- [ ] **Step 2: Uygulamayı arka planda tam izinlerle canlı olarak başlat**
  `.venv/bin/python app.py --background`

- [ ] **Step 3: GitHub'a pushla**
  `git push origin feature/upnow-break-tracker`
