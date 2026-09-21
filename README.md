# KeepAwake

A small Windows and Linux/X11 system-tray utility for configurable idle and
power-management behavior. Includes platform-specific backends, scheduling,
and an updater. Native Wayland support is limited; see the platform notes below.

## Engineering overview

Configure when the utility should prevent sleep or generate a small mouse movement after an idle threshold. Scheduling supports selected weekdays, overnight time ranges and temporary pauses.

- **Shared core:** configuration, scheduling and version comparison are separated from operating-system integration.
- **Native backends:** Windows uses native idle/input/power APIs; Linux uses X11 and `systemd-inhibit`.
- **Desktop delivery:** tray controls, single-instance behavior, Windows installer and an update flow with SHA-256 verification.
- **Tests:** core tests run without a desktop; X11 integration tests require a display. A skipped platform test is not a verified platform result.

Start with [core.py](core.py), [Windows integration](backend_windows.py), [Linux integration](backend_linux.py) or [tests](tests/). The detailed Turkish manual below covers setup, packaging and updates. This is an inactive portfolio project; historical version notes remain available as development history.

## Türkçe kullanım ve geliştirme kılavuzu

Windows ve Linux (X11) için system-tray tabanlı küçük bir güç yönetimi
uygulaması.

## Platform desteği

| Özellik | Windows | Linux (X11) |
|---|---|---|
| Idle algılama | `GetLastInputInfo` | MIT-SCREEN-SAVER (python-xlib) |
| Mouse nudge | `SendInput` | XTest (python-xlib) |
| Uyku engelleme | `SetThreadExecutionState` | `systemd-inhibit` |
| Otomatik başlatma | Registry `Run` anahtarı | `~/.config/autostart/*.desktop` |
| Kurulum paketi | Inno Setup installer | (henüz yok — `python app.py` ile çalıştır) |

Platform seçimi `app.py`'de `sys.platform`'a göre otomatik yapılır
(`backend_windows.py` / `backend_linux.py`); ortak/platform bağımsız mantık
(`AppConfig`, zamanlama, sürüm karşılaştırma) `core.py`'de yaşar.

**Linux kısıtları:** idle algılama ve mouse nudge yalnızca X11'de (XWayland
dahil) çalışır — native Wayland oturumunda sessizce devre dışı kalır, hata
vermez. `systemd-inhibit` masaüstü ortamından bağımsızdır ama ekranın açık
kalması esas olarak mouse nudge'ın idle sayacını sıfırlamasıyla sağlanır.
Henüz bir `.deb`/AppImage paketi yok; Linux'ta doğrudan
`python app.py` ile çalıştırılır (bkz. "Geliştirme modunda çalıştırma").

## Ne yapıyor?

- Windows başlangıcında `--background` ile açılır.
- Başlangıçta hiçbir ayar penceresi göstermez; direkt system tray'e düşer.
- Başlat menüsünden elle açılırsa Ayarlar ekranını gösterir.
- Penceredeki `X` uygulamayı kapatmaz, tekrar tray'e küçültür.
- Tray menüsündeki `Çıkış` gerçekten uygulamayı kapatır.
- İkinci kez açılırsa ikinci tray ikonu oluşturmaz; mevcut pencereyi öne getirir.

## Ayarlanabilenler

- Etkin / devre dışı
- Oturum açılışında otomatik başlat (Windows: Registry, Linux: autostart)
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

Ayar dosyası:

- Windows: `%APPDATA%\KeepAwake\config.json`
- Linux: `$XDG_CONFIG_HOME/KeepAwake/config.json` (tanımlı değilse `~/.config/KeepAwake/config.json`)

## Windows ile başlangıç

Uygulama HKCU altındaki kullanıcı başlangıç kaydını kullanır ve şu şekilde açılır:

`KeepAwake.exe --background`

Bu yüzden Windows oturumu açıldığında ayarlar penceresi önünüze gelmez.

## Güç yönetimi ve mouse input yaklaşımı

Bu sürüm iki davranışı birbirinden bağımsız ayarlayabilir:

1. Windows native keep-awake:
   - sistem uykusunu engeller,
   - ekranın otomatik kapanmasını engeller,
   - seçili çalışma programı boyunca aktif kalır.

2. Mouse nudge:
   - yalnızca seçili çalışma programı içindeyken,
   - kullanıcı `idle_minutes` eşiğine ulaştığında,
   - fareyi 1 piksel sağa ve tekrar sola hareket ettirir.
   - başarılı input sonrasında Windows'un son-input zamanı yenilendiği için,
     bir sonraki nudge yeniden idle eşiği dolduğunda gerçekleşir.

Bu, orijinal betikteki `SendInput(+1) -> 30 ms -> SendInput(-1)`
davranışını uygulamaya taşır.

## Geliştirme modunda çalıştırma

PowerShell:

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

Linux'ta (bash):

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

`core.py` testleri (zamanlama, sürüm karşılaştırma, config) her platformda
çalışır. `backend_linux.py`'nin idle/mouse-nudge testleri gerçek bir X11
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
