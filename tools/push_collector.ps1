# 서버용 브랜치(collector-nationwide)를 운영 main 에 올린다 — 사장님이 직접 실행하는 스크립트(PowerShell 판).
#
# 왜: 수집 서버가 5분마다 main 에 데이터 커밋을 올려서, 브랜치를 그냥 push 하면 "뒤처졌다(rejected)"며
#     거부되고, 손으로 맞춰도 그 사이 또 커밋이 와 다시 거부된다(2026-09-19 두 번 겪음).
#     → 받아(fetch) → 최신 main 위로 올려(rebase) → 밀기(push)를 한 숨에 하고, 거부되면 바로 다시 한다.
#     강제 푸시(-f)는 절대 쓰지 않는다 — 서버 커밋을 지우면 그 회차 데이터가 날아간다.
#     bash 판(push_collector.sh)은 Windows 에서 bash 가 WSL 로 잡히면 안 돌아가서 이 판을 따로 둔다.
#
#   powershell -ExecutionPolicy Bypass -File tools/push_collector.ps1
param([string]$Branch = 'collector-nationwide')
$ErrorActionPreference = 'Continue'
Set-Location (Join-Path $PSScriptRoot '..')

for ($i = 1; $i -le 6; $i++) {
    git fetch origin main -q
    $wt = Join-Path $env:TEMP ("wt-push-" + [guid]::NewGuid().ToString('N').Substring(0, 8))
    git worktree add -q $wt $Branch
    if ($LASTEXITCODE -ne 0) { Write-Host "X 브랜치 $Branch 를 열 수 없다"; exit 1 }
    Push-Location $wt
    git rebase -q origin/main
    $rb = $LASTEXITCODE
    if ($rb -ne 0) { git rebase --abort 2>$null }
    Pop-Location
    git worktree remove --force $wt
    if ($rb -ne 0) { Write-Host "X 최신 main 과 충돌 — 직접 확인 필요"; exit 1 }

    git push origin "${Branch}:main"
    if ($LASTEXITCODE -eq 0) {
        $sha = git rev-parse --short $Branch
        Write-Host "OK 완료: main = $sha  ($i 번째 시도)"
        Write-Host "   서버가 5분 안에 새 코드를 받아 강원 수집을 시작한다."
        exit 0
    }
    Write-Host "· 서버 커밋과 겹쳐 거부됨 — 다시 맞춰서 재시도 ($i/6)"
    Start-Sleep -Seconds 2
}
Write-Host "X 6번 연속 거부 — 잠시 뒤 다시 실행"
exit 1
