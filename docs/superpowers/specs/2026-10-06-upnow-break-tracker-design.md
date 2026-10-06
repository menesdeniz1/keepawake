# Tasarım Dokümanı: KeepAwake UpNow (Mola & Ayakta Kalma Takipçisi) Entegrasyonu

* **Tarih**: 6 Ekim 2026  
* **Hedef Proje**: KeepAwake (v1.3.1+)  
* **Dal (Branch)**: `feature/upnow-break-tracker`  
* **Durum**: Tasarım Onaylandı (Spec)

---

## 1. Genel Bakış ve Amaç

Uzun süre masa başında ve bilgisayar karşısında aralıksız çalışmak duruş bozukluklarına, kronik yorgunluğa ve sağlık problemlerine yol açmaktadır. Bu entegrasyonun amacı:
* Kullanıcıya 50 dakika kesintisiz çalışma ve ardından 10 dakika fiziksel mola ritmi sunmak.
* Mola süresince kullanıcının gerçekten bilgisayar başından ayrılıp ayrılmadığını (klavye/fare etkileşimi olup olmadığını) işletim sistemi seviyesinde denetlemek.
* Mola anında bilgisayarda hareket tespit edilirse kullanıcıyı uyararak (bildirim veya ısrarcı/nagging pencere) masadan uzaklaşmaya teşvik etmek.
* Mevcut KeepAwake işlevlerini (uyku engelleme, fare oynatma) bozmadan, mola esnasında otomatik olarak fare oynatmayı askıya alarak sıfır çakışma ile çalışmak.
* Özelliği varsayılan olarak **kapalı (opt-in)** tutarak geriye dönük tam uyumluluk sağlamak.
* KeepAwake'e yerel **macOS desteği** (`backend_macos.py`) kazandırmak.

---

## 2. Mimari ve Bileşen Yapısı

Sistem, KeepAwake'in mevcut katmanlı mimarisine sadık kalacak şekilde üç ana katmandan oluşur:

```
+-------------------------------------------------------------------+
|                            UI Katmanı                             |
|  - QSystemTrayIcon (Canlı süre göstergesi, hızlı aksiyonlar)      |
|  - SettingsWindow (UpNow ayar grubu: süreler, uyarı modu)         |
|  - BreakNagDialog (Zorlayıcı mod için öne çıkan uyarı penceresi)  |
+---------------------------------+---------------------------------+
                                  |
+---------------------------------v---------------------------------+
|                         Çekirdek (core.py)                        |
|  - AppConfig (yeni mola ayar alanları, varsayılanlar)             |
|  - BreakTracker (Saf Python durum makinesi: WORK / BREAK / ALERT) |
|  - Zamanlayıcı koordinasyonu & olay geri çağırımları              |
+---------------------------------+---------------------------------+
                                  |
+---------------------------------v---------------------------------+
|                   Platform Backend'leri Katmanı                   |
|  - backend_windows.py (user32.GetLastInputInfo)                   |
|  - backend_linux.py   (XScreenSaverQueryInfo)                     |
|  - backend_macos.py   (Quartz: CGEventSourceSecondsSinceLastEvent)|
+-------------------------------------------------------------------+
```

---

## 3. Veri Modeli ve Yapılandırma (`core.py`)

`AppConfig` veri sınıfına geriye dönük uyumlu olarak şu alanlar eklenir:

```python
@dataclass
class AppConfig:
    # Mevcut KeepAwake alanları...
    
    # UpNow Mola Takipçisi Alanları (Varsayılan: Kapalı)
    break_reminder_enabled: bool = False
    work_duration_minutes: int = 50
    break_duration_minutes: int = 10
    break_alert_mode: str = "notification"  # "notification" veya "nagging"
    break_violation_threshold_seconds: int = 15
    break_alert_cooldown_seconds: int = 60
```

Eski yapılandırma dosyalarında bu anahtarlar bulunmadığında otomatik olarak varsayılan değerler atanır; mevcut `ConfigStore` filtreleme mantığı sayesinde çökme yaşanmaz.

---

## 4. Durum Makinesi (`BreakTracker`)

`BreakTracker` sınıfı saf Python ile yazılır; Qt veya işletim sistemi kütüphanelerine bağımlı değildir.

### Durumlar:
1. `DISABLED`: Mola takipçisi kapalı.
2. `WORKING`: Çalışma/odaklanma süresi geri sayıyor.
3. `ON_BREAK`: Mola süresi devrede.
4. `BREAK_VIOLATION`: Mola esnasında kullanıcı hareket etti (idle süresi < eşik).
5. `PAUSED`: Kullanıcı toplantı veya manuel sebeple döngüyü duraklattı.

### Geçiş Kuralları ve Zaman Yönetimi:
* Zaman hesaplamaları sayaç artırımıyla değil, `datetime.now()` referans alınarak hedef zaman farklarıyla yapılır (sistem uykusu veya kapak kapatmalarında zaman kayması yaşanmaz).
* Mola bittiğinde bir sonraki `WORKING` periyodu başlar.
* Kullanıcı dilediğinde menüden "5 Dakika Ertele" veya "Molayı Şimdi Başlat" yapabilir.

---

## 5. KeepAwake Çekirdeği ile Koordinasyon (Çakışma Önleme)

KeepAwake'in ana özelliği boşta kalındığında fareyi oynatmaktır (`nudge_mouse`). Bu durum mola denetimiyle doğrudan çelişebilir.

* **Çözüm Kuralı**: `BreakTracker.state == ON_BREAK` veya `BREAK_VIOLATION` olduğu sürece:
  * `KeepAwakeController` içindeki `nudge_mouse` çağrısı **koşulsuz olarak engellenir**.
  * KeepAwake yalnızca ekran/sistem uykusunu engellemeye devam edebilir.
  * Böylece programın kendi ürettiği mikro fare hareketi hiçbir zaman mola ihlali olarak algılanmaz.

---

## 6. Platform Desteği (`backend_macos.py`)

macOS üzerinde `ctypes` ile `ApplicationServices` framework'ü kullanılır:

* **Boşta Kalma Süresi (`get_idle_seconds`)**:
  ```python
  import ctypes
  from ctypes import c_uint32, c_double

  kCGEventSourceStateCombinedSessionState = 0
  kCGAnyInputEventType = ~0

  core_graphics = ctypes.cdll.LoadLibrary(
      "/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices"
  )
  core_graphics.CGEventSourceSecondsSinceLastEventType.restype = c_double
  core_graphics.CGEventSourceSecondsSinceLastEventType.argtypes = [c_uint32, c_uint32]

  def get_idle_seconds() -> float:
      return float(core_graphics.CGEventSourceSecondsSinceLastEventType(
          kCGEventSourceStateCombinedSessionState,
          kCGAnyInputEventType
      ))
  ```
* **Güvenlik ve İzinler**: Bu API macOS'ta "Erişilebilirlik (Accessibility)" veya "Giriş İzleme (Input Monitoring)" izni gerektirmez. Standart kullanıcı haklarıyla çalışır.
* **Uyku Engelleme**: `caffeinate -d -i` arka plan alt işlemi ile yönetilir.
* **Mouse Nudge**: `CGEventCreateMouseEvent` ve `CGEventPost` ile uygulanır.
* **Otomatik Başlatma**: `~/Library/LaunchAgents/com.menesdeniz.keepawake.plist` dosyası ile yönetilir.

---

## 7. Kullanıcı Arayüzü & Deneyim Tasarımı

### 7.1. Sistem Tepsisi (Tray Menüsü)
* **Durum Metni**:
  * Çalışma: `Odaklanma: 42 dk kaldı`
  * Mola: `Mola: 07:15 kaldı (Masadan Kalk!)`
  * Duraklatıldı: `Mola Takibi: Duraklatıldı`
* **Menü Öğeleri**:
  * `[x] Mola Takipçisi (UpNow)` (Hızlı aç/kapa)
  * `Molayı Şimdi Başlat`
  * `5 Dakika Ertele`
  * `Mola Döngüsünü Duraklat (Toplantı Modu)`

### 7.2. Ayarlar Penceresi (`SettingsWindow`)
"UpNow - Mola & Ayakta Kalma Takipçisi" başlığı altında:
* Mola Takipçisini Etkinleştir (Checkbox)
* Çalışma Süresi (dk): SpinBox (Varsayılan: 50)
* Mola Süresi (dk): SpinBox (Varsayılan: 10)
* Uyarı Tarzı: RadioButton / ComboBox
  * `Nazik Bildirim (Sistem Bildirimi)`
  * `Zorlayıcı Mod (Nagging Penceresi)`

### 7.3. Bildirim ve Nagging Diyaloğu
* **Nazik Mod**: `QSystemTrayIcon.showMessage` ile periyodik (60 sn cooldown) uyarı.
* **Nagging Mod**: `BreakNagDialog` (`Qt.WindowStaysOnTopHint`) penceresi açılır. Kalan mola süresi, "Masadan Uzaklaşın" mesajı ve acil durumlar için "Molayı Bitir" / "Ertele" butonları sunar. Kullanıcı masadan uzaklaştığında sessiz moda geçer.

---

## 8. Test ve Doğrulama Stratejisi

1. **Birim Testleri (`tests/test_break_tracker.py`)**:
   * Mock `datetime` ile çalışma süresi dolduğunda otomatik molaya geçişin testi.
   * Mola esnasında `idle_seconds < threshold` olduğunda ihlalin tespit edilmesi testi.
   * `nudge_mouse` engelleyicisinin molada doğru kilitlendiğinin testi.
   * Eski config dosyasıyla geriye dönük uyumluluk testi.
2. **Platform Testi (`tests/test_backend_macos.py`)**:
   * macOS `get_idle_seconds` fonksiyonunun doğru tip ve değer döndürdüğünün testi.
3. **Mevcut Test Paketi**:
   * `pytest tests/` çalıştırılarak mevcut `test_core.py`, `test_updater.py` vb. testlerin %100 yeşil kaldığının doğrulanması.
4. **Smoke Test**:
   * Uygulamanın başlatılması, menü aksiyonlarının tetiklenmesi ve ayarların `config.json` dosyasına hatasız yazıldığının canlı testi.
