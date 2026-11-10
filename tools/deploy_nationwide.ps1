# 전국판(ggweather + weather) 배포 — 한 줄로 빌드 + 두 주소 배포 (2026-11-10)
#
#   powershell -ExecutionPolicy Bypass -File tools/deploy_nationwide.ps1
#   (어느 폴더에서 실행해도 된다. 데이터만 바뀐 경우엔 필요 없다 — 서버 배포가 알아서 반영)
#
# 옵션:  -Only weather   또는  -Only ggweather   (한 곳만)
param([ValidateSet('both', 'weather', 'ggweather')][string]$Only = 'both')
$ErrorActionPreference = 'Stop'
try { [Console]::OutputEncoding = [Text.Encoding]::UTF8 } catch {}
$root = Resolve-Path (Join-Path $PSScriptRoot '..')
Set-Location $root

Write-Host '1) 빌드 중...' -ForegroundColor Cyan
python tools/build_weather_dev.py
if ($LASTEXITCODE -ne 0) { Write-Host 'X 빌드 실패 - 배포하지 않음' -ForegroundColor Red; exit 1 }

Set-Location (Join-Path $root '.tmp\weather-dev\deploy')
$targets = @()
if ($Only -in 'both', 'weather')   { $targets += 'weather' }
if ($Only -in 'both', 'ggweather') { $targets += 'ggweather' }

foreach ($t in $targets) {
    Write-Host "2) $t 배포 중... (약 3분)" -ForegroundColor Cyan
    npx wrangler deploy --name $t
    if ($LASTEXITCODE -ne 0) { Write-Host "X $t 배포 실패" -ForegroundColor Red; Set-Location $root; exit 1 }
}

Set-Location $root
foreach ($t in $targets) {
    try {
        $v = Invoke-RestMethod "https://$t.visanu81.workers.dev/version.json?t=$([DateTime]::Now.Ticks)"
        Write-Host "OK $t : 빌드 $($v.build)" -ForegroundColor Green
    } catch { Write-Host "? $t : version.json 확인 실패 (잠시 뒤 다시 확인)" -ForegroundColor Yellow }
}
