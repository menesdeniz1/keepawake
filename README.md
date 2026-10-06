# KeepAwake

A small Windows, Linux/X11 and macOS system-tray utility for configurable idle and
power-management behavior. Includes platform-specific backends, scheduling,
an updater, and the UpNow break tracker. Native Wayland support is limited; see the platform notes below.

## Engineering overview

Configure when the utility should prevent sleep or generate a small mouse movement after an idle threshold. Scheduling supports selected weekdays, overnight time ranges and temporary pauses.

- **Shared core:** configuration, scheduling, break tracking and version comparison are separated from operating-system integration.
- **Native backends:** Windows uses native idle/input/power APIs; Linux uses X11 and `systemd-inhibit`; macOS uses Quartz (ApplicationServices) and `caffeinate`.
- **Desktop delivery:** tray controls, single-instance behavior, Windows installer and an update flow with SHA-256 verification.
- **Tests:** core tests run without a desktop; X11 integration tests require a display. A skipped platform test is not a verified platform result.

Start with [core.py](core.py), [Windows integration](backend_windows.py), [Linux integration](backend_linux.py), [macOS integration](backend_macos.py) or [tests](tests/). The detailed Turkish manual below covers setup, packaging and updates. This is an inactive portfolio project; historical version notes remain available as development history.

## Türkçe kullanım ve geliştirme kılavuzu

Windows, Linux (X11) ve macOS için system-tray tabanlı küçük bir güç yönetimi
ve mola takip uygulaması.

## Platform desteği

| Özellik | Windows | Linux (X11) | macOS |
|---|---|---|---|
| Idle algılama | `GetLastInputInfo` | MIT-SCREEN-SAVER (python-xlib) | `CGEventSourceSecondsSinceLastEventType` (Quartz) |
| Mouse nudge | `SendInput` | XTest (python-xlib) | `CGEventCreateMouseEvent` (Quartz) |
| Uyku engelleme | `SetThreadExecutionState` | `systemd-inhibit` | `caffeinate` alt süreci |
| Otomatik başlatma | Registry `Run` anahtarı | `~/.config/autostart/*.desktop` | `~/Library/LaunchAgents/com.menesdeniz.keepawake.plist` |
| Kurulum paketi | Inno Setup installer | (henüz yok — `python app.py` ile çalıştır) | (henüz yok — `python app.py` ile çalıştır) |

Platform seçimi `app.py`'de `sys.platform`'a göre otomatik yapılır
(`backend_windows.py` / `backend_linux.py` / `backend_macos.py`); ortak/platform bağımsız mantık
(`AppConfig`, zamanlama, sürüm karşılaştırma, `BreakTracker`) `core.py`'de yaşar.

**macOS desteği:** Idle algılama ve fare nudge işlemleri `ApplicationServices` / Quartz API'si üzerinden ctypes ile native olarak yürütülür. Sistem ve ekran uykusunu engelleme `caffeinate -di` alt süreciyle sağlanır. Otomatik başlatma `~/Library/LaunchAgents/` altına `.plist` yazılarak `launchctl` ile entegre edilir.

**Linux kısıtları:** idle algılama ve mouse nudge yalnızca X11'de (XWayland
dahil) çalışır — native Wayland oturumunda sessizce devre dışı kalır, hata
vermez. `systemd-inhibit` masaüstü ortamından bağımsızdır ama ekranın açık
kalması esas olarak mouse nudge'ın idle sayacını sıfırlamasıyla sağlanır.
Henüz bir `.deb`/AppImage paketi yok; Linux'ta doğrudan
`python app.py` ile çalıştırılır (bkz. "Geliştirme modunda çalıştırma").

## Ne yapıyor?

- Windows başlangıcında `--background` ile açılır.
- Başlangıçta hiçbir ayar penceresi göstermez; direkt system tray'e düşer.
- Başlat menüsünden veya dock/spotlight'tan elle açılırsa Ayarlar ekranını gösterir.
- Penceredeki `X` uygulamayı kapatmaz, tekrar tray'e küçültür.
- Tray menüsündeki `Çıkış` gerçekten uygulamayı kapatır.
- İkinci kez açılırsa ikinci tray ikonu oluşturmaz; mevcut pencereyi öne getirir.

## Ayarlanabilenler

- Etkin / devre dışı
- Oturum açılışında otomatik başlat (Windows: Registry, Linux: autostart, macOS: LaunchAgents)
- Idle eşiği: 1-240 dakika
- Kontrol sıklığı: 1-60 saniye
- Pazartesi-Pazar gün seçimi
- Başlangıç ve bitiş saati
- Geceyi aşan programlar, örn. `22:00 -> 02:00`
- Sistem uykusunu engelle
- Ekranın otomatik kapanmasını engelle
- Idle eşiğinde 1 px sağ/sol mouse input üret
- Tray'den 15 dakika duraklat
- Tray'den 1 saat duraklat
- Bugün için duraklat
- **UpNow Mola Takipçisi:**
  - Etkin / devre dışı (varsayılan: kapalı)
  - Çalışma süresi: 1-180 dakika (varsayılan: 50 dk)
  - Mola süresi: 1-60 dakika (varsayılan: 10 dk)
  - Mola uyarı modu: Masaüstü bildirimi (`notification`) veya Zorlayıcı pencere (`nagging`)

Ayar dosyası:

- Windows: `%APPDATA%\KeepAwake\config.json`
- Linux: `$XDG_CONFIG_HOME/KeepAwake/config.json` (tanımlı değilse `~/.config/KeepAwake/config.json`)
- macOS: `~/.config/KeepAwake/config.json`

## UpNow - Mola Takipçisi

Masa başında uzun süre kesintisiz çalışmayı önlemek ve düzenli mola alışkanlığı kazandırmak için entegre mola takip modülü.

### Temel Özellikler

- **50 dk Çalışma / 10 dk Mola Döngüsü:** Varsayılan olarak 50 dakika kesintisiz çalışma ve 10 dakika dinlenme periyodu uygular. Süreler Ayarlar penceresinden ihtiyaca göre değiştirilebilir.
- **Mola Sırasında Fare Hareketi (Nudge) Kilidi:** Mola başladığında KeepAwake otomatik fare nudge üretimini kilitler. Bu sayede kullanıcı masadan ayrıldığında bilgisayar yapay olarak uyanık tutulmaz ve güç tasarrufu/ekran kilidi işlevleri normal işler.
- **İhlal Algılama ve Akıllı Uyarı:** Mola anında kullanıcının bilgisayarda hareket (klavye veya fare) oluşturması durumunda sistem mola ihlali (`break_violation`) durumuna geçer ve kullanıcıyı uyarır. Kullanıcı masadan kalkıp bilgisayarı boş bıraktığında (15 saniye idle eşiği) sistem otomatik olarak normal mola durumuna döner.
- **İki Farklı Uyarı Modu:**
  1. *Bildirim Modu (`notification`):* Sistem tepsisi üzerinden standart balon/bildirim mesajı gönderir.
  2. *Zorlayıcı (Nagging) Pencere Modu (`nagging`):* Ekranın tam ortasında her zaman en üstte (`WindowStaysOnTopHint`) kalan bir uyarı penceresi açılır. Pencere kalan mola süresini dinamik olarak gösterir.
- **Zorlayıcı Pencere Seçenekleri:**
  - *Hemen Başla:* Molayı sonlandırıp yeni bir çalışma periyodu başlatır.
  - *5 Dk Ertele:* Molayı 5 dakika erteler ve çalışma moduna döner.
  - *Mola Takibini Duraklat:* Mola takipçisini geçici olarak duraklatır.
  - *Otomatik Kapanma:* Kullanıcı masadan kalkıp bilgisayarı bıraktığında (15 sn idle), uyarı penceresi otomatik kapanır ve mola sayacı arka planda işlemeye devam eder.
- **Yüzen Canlı Sayaç Kapsülü (Floating Pill):** Mola başladığında ekranın sağ üst köşesinde zarif, yarı saydam ve kompakt bir sayaç kapsülü belirir (`☕ 09:45 | +5 Dk Uzat | 5 Dk Ertele | Acil Bitir | ✕`). Odak çalmaz (`WindowDoesNotAcceptFocus`), ekranın istenen yerine sürüklenebilir, kapatılabilir veya Ayarlar sekmesinden kapatılıp açılabilir. Windows, macOS ve Linux platformlarının tamamında yerel ve akıcı çalışır.
- **Dinamik Erteleme ve Uzatma Desteği:** Ayarlar penceresinden hem erteleme hem de mola uzatma süreleri (1-60 dk) bağımsız olarak belirlenebilir; bildirimler, floating kapsül ve nagging diyaloğundaki butonlar seçilen süreleri dinamik olarak yansıtır.
- **Varsayılan Olarak Kapalı (Opt-in):** Mevcut KeepAwake iş akışını bozmamak için özellik varsayılan olarak devre dışıdır.
- **Tray Menüsünden ve Ayarlar Penceresinden Tam Yönetim:**
  - *Tray Menüsü:* Anlık mola durumu (ör. `UpNow: 42 dk kaldı`, `Mola: 08:30 kaldı`), "Molayı Başlat", "5 Dk Ertele" ve "Mola Takibini Duraklat / Devam Ettir" eylemleri.
  - *Ayarlar Penceresi:* Mola Takipçisini Etkinleştir, Çalışma Süresi (dk), Mola Süresi (dk), Erteleme Süresi (dk), Uzatma Süresi (dk), Uyarı Modu ve Canlı Sayaç Kapsülü onay kutusu.

## Windows ile başlangıç

Uygulama HKCU altındaki kullanıcı başlangıç kaydını kullanır ve şu şekilde açılır:

`KeepAwake.exe --background`

Bu yüzden Windows oturumu açıldığında ayarlar penceresi önünüze gelmez.

## Güç yönetimi ve mouse input yaklaşımı

Bu sürüm iki davranışı birbirinden bağımsız ayarlayabilir:

1. Platforma özgü keep-awake:
   - sistem uykusunu engeller,
   - ekranın otomatik kapanmasını engeller,
   - seçili çalışma programı boyunca aktif kalır.

2. Mouse nudge:
   - yalnızca seçili çalışma programı içindeyken ve mola durumunda değilken,
   - kullanıcı `idle_minutes` eşiğine ulaştığında,
   - fareyi 1 piksel sağa ve tekrar sola hareket ettirir.
   - başarılı input sonrasında son-input zamanı yenilendiği için,
     bir sonraki nudge yeniden idle eşiği dolduğunda gerçekleşir.

Bu, `SendInput(+1) -> 30 ms -> SendInput(-1)` (macOS'ta `CGEventCreateMouseEvent`)
davranışını uygulamaya taşır.

## Geliştirme modunda çalıştırma

PowerShell (Windows):

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python app.py
```

Tray başlangıcını test etmek için:

```powershell
python app.py --background
```

Linux ve macOS'ta (bash/zsh):

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

## Testleri çalıştırma

```bash
pip install -r requirements-dev.txt
pytest tests/ -v
```

`core.py` testleri (zamanlama, mola takipçisi, sürüm karşılaştırma, config) her platformda
çalışır. `backend_macos.py` testleri macOS ortamında CoreGraphics ve caffeinate kontrolü yapar.
`backend_linux.py`'nin idle/mouse-nudge testleri gerçek bir X11
bağlantısı ister; X yoksa (ör. headless CI) otomatik `skip` edilir — Xvfb ile
çalıştırmak için: `Xvfb :99 & DISPLAY=:99 pytest tests/ -v`. `updater.py`
testleri yerel bir `http.server` fixture'ı kullanır, gerçek ağ erişimi
gerektirmez.

## EXE + gerçek installer oluşturma

Gerekenler:

1. Windows 10/11
2. Python 3.11+
3. Inno Setup 6

Proje klasöründe PowerShell açıp:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\build.ps1
```

çalıştırın.

Script sırayla:

1. `.venv` oluşturur.
2. PySide6 ve PyInstaller kurar.
3. `dist\KeepAwake\KeepAwake.exe` üretir.
4. Inno Setup varsa installer'ı derler.
5. Son dosyayı üretir:

`output\KeepAwakeSetup.exe`

## Uninstall nasıl çalışıyor?

Kurulduktan sonra normal Windows uygulaması gibi kaldırılabilir.

### Yol 1 — Windows Ayarları

`Ayarlar > Uygulamalar > Yüklü uygulamalar > KeepAwake > Kaldır`

### Yol 2 — Başlat menüsü

`KeepAwake > KeepAwake Kaldır`

### Yol 3 — Uninstaller EXE

Kurulum klasöründeki Inno Setup uninstaller'ı çalıştırılabilir.

Uninstall sırasında:

1. Çalışan KeepAwake'e `--quit` gönderilir ve uygulama temiz kapanır.
2. Windows otomatik başlangıç kaydı silinir.
3. Program dosyaları kaldırılır.
4. `%APPDATA%\KeepAwake` ayar klasörünü de silmek isteyip istemediğiniz sorulur.

`Evet`:
ayarlar dahil temiz kurulum yapılmış gibi her şey kaldırılır.

`Hayır`:
ayarlar korunur. Daha sonra KeepAwake'i tekrar kurarsanız önceki ayarlarınız kalır.

## SmartScreen notu

Kendi bilgisayarınızda oluşturduğunuz, dijital imzası olmayan EXE ve installer
Windows SmartScreen tarafından "tanınmayan uygulama" olarak gösterilebilir.

Kişisel kullanımda bu beklenen bir durumdur. Başkalarına dağıtılacak gerçek
ürün sürümünde code-signing sertifikasıyla imzalama eklenebilir.


## v1.2 - Ayarlanabilir cooldown

Başarılı bir mouse nudge sonrasında program, kullanıcı tarafından belirlenen minimum ve maksimum değerler arasında rastgele bir cooldown seçer.

Varsayılanlar:

- Idle eşiği: `4 dakika`
- Kontrol sıklığı: `5 saniye`
- Mouse hareketi: `+1 px -> 30 ms -> -1 px`
- Minimum cooldown: `70 saniye`
- Maksimum cooldown: `110 saniye`

Minimum ve maksimum cooldown değerleri Ayarlar ekranından `0-3600 saniye` arasında değiştirilebilir. Minimum değer maksimumdan büyükse uygulama kaydetmeye izin vermez. Cooldown sürerken yeni mouse nudge üretilmez.

Eski v1.1 config dosyaları geriye dönük uyumludur; yeni cooldown alanları yoksa otomatik olarak `70` ve `110` varsayılanları kullanılır.

## v1.3 - Otomatik güncelleme ve Linux desteği

- Uygulama artık kendini `latest.json` manifestiyle kontrol edip SHA256
  doğrulamalı sessiz kurulumla güncelleyebiliyor (bkz. "Otomatik güncelleme").
- Linux (X11) desteği eklendi: idle algılama, mouse nudge, uyku engelleme ve
  otomatik başlatma artık platforma özgü backend'ler üzerinden çalışıyor
  (bkz. "Platform desteği").
- `core.py` + `backend_windows.py`/`backend_linux.py` ayrımıyla kod tabanı
  platform bağımsız çekirdek ve platforma özgü backend olarak ikiye bölündü.
- `tests/` altında gerçek (mock olmayan) bir test paketi eklendi.
- Eski v1.2 config dosyaları geriye dönük uyumludur; yeni `auto_check_updates`
  alanı yoksa otomatik olarak `true` varsayılanı kullanılır.

## v1.4 - UpNow Mola Takipçisi ve macOS Desteği

- **UpNow Mola Takipçisi:** Masa başı kesintisiz çalışmayı önlemek için 50 dk çalışma / 10 dk mola döngüsü, mola sırasında fare nudge engelleme, hareket algılandığında zorlayıcı pencere veya bildirim uyarıları ve tray menüsü/ayarlar entegrasyonu eklendi.
- **macOS Desteği:** `ApplicationServices` / Quartz (CoreGraphics) ile native idle algılama ve fare nudge, `caffeinate` ile uyku yönetimi ve LaunchAgents plist ile otomatik başlatma desteği sağlandı (`backend_macos.py`).
- **Geriye Dönük Uyumluluk:** Eski config dosyaları UpNow kapalı olacak şekilde sorunsuz yüklenir.

## Otomatik güncelleme

KeepAwake, repo kökündeki [`latest.json`](latest.json) manifestini kontrol ederek
kendini günceller.

### Nasıl çalışır?

1. Uygulama açılışta (5 sn gecikmeyle) ve Ayarlar'da "Güncellemeleri otomatik
   kontrol et" açıksa, `raw.githubusercontent.com/menesdeniz1/keepawake/main/latest.json`
   dosyasını okur. Tray menüsündeki **"Güncellemeleri Kontrol Et"** ile elle de
   tetiklenebilir.
2. Manifestteki `version`, uygulamanın kendi sürümünden (`VERSION`) daha
   yeniyse ve `url` + `sha256` alanları doluysa, kullanıcıya bir onay
   penceresi gösterilir.
3. Onaylanırsa installer indirilir, **SHA256 doğrulanır** (uyuşmuyorsa
   kurulum iptal edilir), sonra `KeepAwakeSetup.exe /VERYSILENT
   /SUPPRESSMSGBOXES /NORESTART /CLOSEAPPLICATIONS` ile sessizce çalıştırılır.
4. Sessiz kurulum bittiğinde installer, uygulamayı `--background` ile
   yeniden açar (ayarlar penceresi açılmadan, doğrudan tray'e döner).

`sha256` boşsa veya `url` boşsa güncelleme **hiçbir zaman** teklif edilmez —
bu, yarım/hatalı bir release yayınlandığında istemcilerin sessizce
doğrulanmamış bir exe çalıştırmasını engeller.

### Yeni sürüm yayınlama süreci

1. `VERSION` dosyasını ve `installer.iss` içindeki `MyAppVersion` /
   `OutputBaseFilename` değerlerini yeni sürüme güncelle.
2. Windows'ta `.\build.ps1` çalıştırıp `output\KeepAwakeSetup-vX.Y.Z.exe`
   dosyasını üret.
3. GitHub'da bu commit için bir **Release** oluştur, `KeepAwakeSetup-vX.Y.Z.exe`
   dosyasını release asset olarak yükle, indirme linkini kopyala.
4. Dosyanın SHA256'sını hesapla (PowerShell: `Get-FileHash
   output\KeepAwakeSetup-vX.Y.Z.exe -Algorithm SHA256`).
5. Repo kökündeki `latest.json`'ı güncelle (`version`, `url`, `sha256`, `notes`)
   ve `main`'e push et.

Adım 5'ten önce eski sürümler hâlâ eski manifesti görür; `latest.json` push
edilene kadar hiçbir istemci yeni sürümü fark etmez, yani release'i
yayınlamakla istemcilere duyurmak birbirinden ayrı, kontrollü adımlardır.
