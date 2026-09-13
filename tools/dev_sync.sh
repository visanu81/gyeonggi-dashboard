#!/usr/bin/env bash
# 개발 클론을 운영(origin/main)에 안전하게 맞춘다.
#
# 왜 필요한가
#   서버(update.sh)는 저장소가 커지면 히스토리를 통째로 1커밋으로 눌러 강제 푸시한다.
#   그러면 개발 PC의 클론과 origin/main 사이에 '공통 조상'이 사라져서
#   git rebase / git pull 이 "no merge base" 나 엉뚱한 충돌을 낸다.
#   (실제로 겪음 — 압축 커밋이 내 작업을 되돌리는 것처럼 보이는 충돌이 났다)
#
#   히스토리를 맞추려 애쓸 필요가 없다. 코드의 정답은 언제나 origin/main 이고,
#   내 작업은 '파일'로 얹으면 된다. 이 스크립트가 그 과정을 안전하게 해 준다.
#
# 쓰는 법
#   bash tools/dev_sync.sh                # origin/main 에 맞추기
#   bash tools/dev_sync.sh --gc           # 맞춘 뒤 오래된 깃 객체까지 정리(용량 회수)
#
# 안전장치
#   · 커밋 안 한 변경이 있으면 멈춘다(작업물 보호). 커밋하거나 stash 후 다시 실행.
#   · 되돌릴 수 있도록, 맞추기 직전 위치를 백업 브랜치로 남긴다.

set -e
cd "$(dirname "$0")/.."

BR=release          # 개발용 작업 브랜치 이름
DO_GC=0
[ "$1" = "--gc" ] && DO_GC=1

echo "▶ 저장소: $(pwd)"

# 1) 커밋 안 한 변경이 있으면 중단 — 덮어쓰면 작업이 사라진다
if [ -n "$(git status --porcelain --untracked-files=no)" ]; then
  echo "✋ 커밋하지 않은 변경이 있습니다. 먼저 커밋하거나 보관(stash)하세요:"
  git status --short --untracked-files=no | head -20
  exit 1
fi

# 2) 원격 최신 가져오기
echo "▶ origin 가져오는 중…"
git fetch origin --prune -q

# 3) 되돌릴 수 있게 현재 위치를 백업 (같은 이름이 있으면 덮어씀)
CUR=$(git rev-parse --short HEAD 2>/dev/null || echo '-')
git branch -f dev-backup HEAD 2>/dev/null || true
echo "▶ 되돌리기용 백업: dev-backup (= $CUR)"

# 4) origin/main 에 그대로 맞춘다 — rebase 를 쓰지 않는다.
#    히스토리가 갈렸든 말든 '지금 운영에 올라가 있는 상태'가 정답이다.
BEFORE=$(git rev-parse --short origin/main)
git checkout -q -B "$BR" origin/main
echo "▶ $BR 브랜치를 origin/main($BEFORE) 에 맞췄습니다."

# 5) 용량 회수 (선택) — 압축된 옛 히스토리가 로컬에 남아 수 GB를 먹는다
if [ "$DO_GC" = "1" ]; then
  SZ_BEFORE=$(du -sm .git 2>/dev/null | cut -f1)
  echo "▶ 오래된 객체 정리 중… (현재 .git ${SZ_BEFORE}MB, 몇 분 걸릴 수 있음)"
  git reflog expire --expire=now --expire-unreachable=now --all
  git gc --prune=now --quiet
  SZ_AFTER=$(du -sm .git 2>/dev/null | cut -f1)
  echo "▶ .git ${SZ_BEFORE}MB → ${SZ_AFTER}MB"
fi

echo
echo "✅ 완료. 이제 이 위에서 작업하면 됩니다."
echo "   되돌리려면:  git checkout dev-backup"
