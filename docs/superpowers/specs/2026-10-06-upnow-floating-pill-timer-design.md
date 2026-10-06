# UpNow Yüzen Canlı Sayaç Kapsülü (Floating Pill Timer) Tasarım Dokümanı

**Tarih:** 2026-10-06  
**Durum:** Onaylandı (Geliştirme Öncesi Tasarım)  
**Hedef:** Windows, macOS ve Linux üzerinde mola süresince ekranın üzerinde yüzen, pencereleri kapatmayan, sürüklenip taşınabilen ve canlı geri sayım ile hızlı aksiyonları (`+Uzat`, `Ertele`, `Acil Bitir`) barındıran modern bir kapsül penceresi sunmak.

---

## 1. Arka Plan & Problem

UpNow mola takipçisinde, mola başladığında nazik bildirim kartı sağ üstte çıkar ve birkaç saniye sonra kendiliğinden kapanır. Kullanıcı "Molayı Uzat" dediğinde de bildirim kapanır. 
Bu durumda kullanıcının ekranında veya masadan uzaktayken görebileceği **canlı ve sürekli bir mola süresi göstergesi** kalmamaktadır. 

İşletim sistemlerinin menü/tray çubuğu kısıtlamaları (Windows'un ikon yanına metin koydurmaması, Linux'ta tema uyumsuzlukları vb.) nedeniyle menü çubuğu yerine **yüzen modern mini kapsül (Dynamic Island / Pill Widget)** tüm işletim sistemlerinde (macOS, Windows 11/10, Linux) %100 aynı görsel şıklık ve tutarlılıkla çalışan en ideal çözümdür.

---

## 2. Tasarım & Bileşen Mimarisi

### 2.1 Kapsül Formu ve Görsel Düzen (Dark Glassmorphic Pill)

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│  ☕ 04:35  │  +5 Dk Uzat  │  5 Dk Ertele  │  Acil Bitir  │   ✕   │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

* **Genişlik & Yükseklik:** ~380px genişlik, ~36px yükseklik (kompakt, ince ve zarif).
* **Kenarlık:** `border-radius: 18px`, `border: 1px solid #45475a`.
* **Arka Plan:** Koyu yarı saydam (`rgba(30, 30, 46, 0.92)`).
* **Bileşenler:**
  1. `self.timer_label (QLabel)`: `☕ MM:SS` (saniyeler anlık geriye akar, kalın ve vurgulu renk).
  2. `self.extend_btn (QPushButton)`: `+{extend_min} Dk Uzat` (molayı uzatır).
  3. `self.snooze_btn (QPushButton)`: `{snooze_min} Dk Ertele` (molayı erteler, çalışmaya döner).
  4. `self.emergency_btn (QPushButton)`: `Acil Bitir` (molayı derhal bitirir).
  5. `self.close_btn (QPushButton)`: `✕` (kapsülü o mola için ekrandan gizler).

### 2.2 Pencere Özellikleri (Window Flags)

* `Qt.WindowType.FramelessWindowHint`: Başlık çubuğu veya pencere kenarlığı olmadan saf kapsül.
* `Qt.WindowType.WindowStaysOnTopHint`: Her zaman en üstte kalır.
* `Qt.WindowType.Tool`: Görev çubuğunda/Dock'ta ayrı bir uygulama ikonu oluşturmaz.
* `Qt.WindowType.WindowDoesNotAcceptFocus`: Kullanıcının aktif çalıştığı veya yazdığı pencereden odağı çalmaz.
* `WA_TranslucentBackground = True`: Kapsülün dışındaki tüm pikseller şeffaftır, arkadaki ekranı gösterir.

### 2.3 Sürüklenebilirlik (Draggable)

* Kapsülün boş bir yerine fare ile sol tıklanıp basılı tutulduğunda serbestçe sürüklenebilir (`mousePressEvent`, `mouseMoveEvent`, `mouseReleaseEvent`).
* Kullanıcı bir konuma bıraktığında, mola devam ettiği sürece o konumda kalır.
* Varsayılan ilk konumu: Ekranın sağ üst köşesi (örneğin sağdan 20px, üstten 40px).

---

## 3. Yaşam Döngüsü (Lifecycle & Coordination)

1. **Mola Başladığında (`notify_break_started`):**
   - Kapsül görünür hale gelir (`self.floating_pill.show()`).
   - Geri sayım canlı olarak her saniye güncellenir.
2. **Kullanıcı `+X Dk Uzat` Tıkladığında:**
   - `controller.extend_break()` çağrılır.
   - Kapsül ekranda kalmaya devam eder, yeni eklenen süreyle sayaç uzar.
3. **Kullanıcı `X Dk Ertele` Tıkladığında:**
   - `controller.extend_work()` çağrılır.
   - Mola ertelendiği için kapsül kapanır (`hide()`).
4. **Kullanıcı `Acil Bitir` Tıkladığında:**
   - `controller.start_work_now()` çağrılır.
   - Mola bittiği için kapsül kapanır (`hide()`).
5. **Mola Süresi Doğal Olarak Bittiğinde (`notify_break_finished`):**
   - Kapsül otomatik olarak kapanır (`hide()`).
6. **Kullanıcı `✕` Tıkladığında:**
   - Sadece kapsül gizlenir (`hide()`), mola arka planda devam eder.

---

## 4. Ayarlar & Yapılandırma (`AppConfig`)

* `core.AppConfig`:
  - `break_floating_timer_enabled: bool = True` (Varsayılan olarak açık).
* `app.SettingsWindow`:
  - "UpNow (Mola Takipçisi)" sekmesinde:
    `self.break_floating_check = QCheckBox("Mola sırasında ekranda yüzen canlı sayaç kapsülü göster")`
  - Ayar açılıp kapatıldığında kapsülün otomatik açılması denetlenir.

---

## 5. Doğrulama ve Test Stratejisi

* `tests/test_ui_break.py`:
  - `BreakFloatingPill` widget özellikleri (flags, widgets, butonlar).
  - Sürükleme ve buton tıklama fonksiyonları (`extend_break`, `extend_work`, `start_work_now`).
  - Mola başlayınca açılma, bitince kapanma testleri.
  - SettingsWindow ayar kaydetme/yükleme testleri.
