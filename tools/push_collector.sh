#!/usr/bin/env bash
# 서버용 브랜치(collector-nationwide)를 운영 main 에 올린다 — 사장님이 직접 실행하는 스크립트.
#
# 왜 이런 게 필요한가: 수집 서버(ncp-server)가 5분마다 main 에 데이터 커밋을 올린다. 그래서
# 어제 만든 브랜치를 그냥 push 하면 "뒤처졌다(rejected)"며 거부되고, 사람이 손으로 맞춰 눌러도
# 그 사이에 또 커밋이 올라와 다시 거부된다(2026-09-19 실제로 두 번 겪음).
# → 받아(fetch) → 최신 main 위로 올려(rebase) → 밀기(push)를 한 숨에 하고, 거부되면 바로 다시 한다.
#
# 작업 트리는 건드리지 않는다(임시 worktree 에서 rebase). 강제 푸시(-f)는 절대 쓰지 않는다 —
# 서버 커밋을 지우면 그 회차 데이터가 날아간다.
#
#   bash tools/push_collector.sh            # 기본: collector-nationwide → main
#   bash tools/push_collector.sh 다른브랜치  # 다른 브랜치를 main 에 올릴 때
set -u
cd "$(dirname "$0")/.."
BR="${1:-collector-nationwide}"

for i in 1 2 3 4 5 6; do
  git fetch origin main -q
  WT="$(mktemp -d)"
  if ! git worktree add -q "$WT" "$BR"; then
    echo "✗ 브랜치 $BR 를 열 수 없다"; exit 1
  fi
  if ! (cd "$WT" && git rebase -q origin/main); then
    (cd "$WT" && git rebase --abort) 2>/dev/null
    git worktree remove --force "$WT"
    echo "✗ 최신 main 과 충돌 — 직접 확인 필요"; exit 1
  fi
  git worktree remove --force "$WT"
  if git push origin "$BR:main"; then
    echo "✓ 완료: main = $(git rev-parse --short "$BR")  ($i번째 시도)"
    echo "  서버가 5분 안에 새 코드를 받아 강원 수집을 시작한다."
    exit 0
  fi
  echo "· 서버 커밋과 겹쳐 거부됨 — 다시 맞춰서 재시도 ($i/6)"
  sleep 2
done
echo "✗ 6번 연속 거부 — 잠시 뒤 다시 실행"; exit 1
