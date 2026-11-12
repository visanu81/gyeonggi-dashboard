# 전국판(ggweather + weather) 배포 — 한 줄로 빌드 + 두 주소 배포 (2026-11-10)
#
#   powershell -ExecutionPolicy Bypass -File tools/deploy_nationwide.ps1              # ggweather 만 (기본)
#   powershell -ExecutionPolicy Bypass -File tools/deploy_nationwide.ps1 -Only both   # 완성 후 weather 까지
#   (어느 폴더에서 실행해도 된다. 데이터만 바뀐 경우엔 필요 없다 — 서버 배포가 알아서 반영)
#
# ★ 2026-11-11 사장님 지시: 수정은 ggweather 에만 먼저 올리고, 완성되면 다른 사이트(weather 등)에 적용.
#   그래서 기본값이 ggweather 다. weather 는 '-Only both' 또는 '-Only weather' 로 명시할 때만.
param([ValidateSet('both', 'weather', 'ggweather')][string]$Only = 'ggweather')
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
# 배포 직후에는 옛 version.json 이 잠깐 보일 수 있다(2026-11-12 겪음: 새 판이 올라갔는데 이전 빌드 번호가 찍힘).
# 방금 만든 빌드 번호(로컬 version.json)와 같아질 때까지 몇 번 다시 본다.
$want = $null
try { $want = (Get-Content (Join-Path $root '.tmp/weather-dev/deploy/public/version.json') -Raw -Encoding UTF8 | ConvertFrom-Json).build } catch {}
foreach ($t in $targets) {
    $got = $null
    for ($i = 0; $i -lt 6; $i++) {
        try { $got = (Invoke-RestMethod "https://$t.visanu81.workers.dev/version.json?t=$([DateTime]::Now.Ticks)").build } catch { $got = $null }
        if (-not $want -or $got -eq $want) { break }
        Start-Sleep -Seconds 3
    }
    if ($got -and (-not $want -or $got -eq $want)) { Write-Host "OK $t : 빌드 $got" -ForegroundColor Green }
    elseif ($got) { Write-Host "? $t : 아직 이전 빌드 $got 가 보임 (올린 것: $want) - 잠시 뒤 다시 확인" -ForegroundColor Yellow }
    else { Write-Host "? $t : version.json 확인 실패 (잠시 뒤 다시 확인)" -ForegroundColor Yellow }
}
