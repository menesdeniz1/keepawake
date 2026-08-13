# KeepAwake 1.2

Windows için system-tray tabanlı küçük bir güç yönetimi uygulaması.

## Ne yapıyor?

- Windows başlangıcında `--background` ile açılır.
- Başlangıçta hiçbir ayar penceresi göstermez; direkt system tray'e düşer.
- Başlat menüsünden elle açılırsa Ayarlar ekranını gösterir.
- Penceredeki `X` uygulamayı kapatmaz, tekrar tray'e küçültür.
- Tray menüsündeki `Çıkış` gerçekten uygulamayı kapatır.
- İkinci kez açılırsa ikinci tray ikonu oluşturmaz; mevcut pencereyi öne getirir.

## Ayarlanabilenler

- Etkin / devre dışı
- Windows ile otomatik başlat
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

`%APPDATA%\KeepAwake\config.json`

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
