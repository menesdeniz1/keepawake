$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "=== KeepAwake Windows Build ===" -ForegroundColor Cyan
Write-Host ""

if (-not (Get-Command py -ErrorAction SilentlyContinue)) {
    throw "Python launcher (py.exe) bulunamadı. Python 3.11+ kurup tekrar deneyin."
}

if (-not (Test-Path ".venv")) {
    Write-Host "[1/5] Sanal ortam oluşturuluyor..."
    py -3 -m venv .venv
}
else {
    Write-Host "[1/5] Sanal ortam zaten var."
}

$python = Join-Path $PWD ".venv\Scripts\python.exe"

Write-Host "[2/5] Bağımlılıklar kuruluyor/güncelleniyor..."
& $python -m pip install --upgrade pip
& $python -m pip install -r requirements.txt

Write-Host "[3/5] Eski build çıktıları temizleniyor..."
Remove-Item -Recurse -Force build -ErrorAction SilentlyContinue
Remove-Item -Recurse -Force dist -ErrorAction SilentlyContinue
Remove-Item -Recurse -Force output -ErrorAction SilentlyContinue

Write-Host "[4/5] KeepAwake.exe oluşturuluyor..."
& $python -m PyInstaller `
    --noconfirm `
    --clean `
    --windowed `
    --onedir `
    --noupx `
    --name KeepAwake `
    app.py

$isccCandidates = @(
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
)

$iscc = $isccCandidates |
    Where-Object { Test-Path $_ } |
    Select-Object -First 1

if (-not $iscc) {
    Write-Host ""
    Write-Host "KeepAwake.exe hazır:" -ForegroundColor Green
    Write-Host "dist\KeepAwake\KeepAwake.exe"
    Write-Host ""
    Write-Host "Inno Setup 6 bulunamadı." -ForegroundColor Yellow
    Write-Host "Inno Setup 6'yı kurup build.ps1'i tekrar çalıştırırsanız"
    Write-Host "output\KeepAwakeSetup-v1.2.exe de oluşturulur."
    exit 0
}

Write-Host "[5/5] KeepAwakeSetup-v1.2.exe oluşturuluyor..."
& $iscc "installer.iss"
if ($LASTEXITCODE -ne 0) {
    throw "Inno Setup derlemesi başarısız oldu. Exit code: $LASTEXITCODE"
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host "HAZIR: output\KeepAwakeSetup-v1.2.exe" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host ""
