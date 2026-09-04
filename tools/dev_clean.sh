#!/usr/bin/env bash
# 개발 PC의 .git 용량 회수 — 서버가 히스토리를 압축할 때마다 남는 '옛 히스토리' 청소.
#
# 왜 커지나
#   서버(update.sh)는 저장소가 커지면 히스토리를 1커밋으로 눌러 강제 푸시한다.
#   그때 개발 PC에 남아 있던 옛 브랜치(작업 끝난 것·worktree)는 압축 전 히스토리를
#   통째로 붙들고 있어서, 아무도 안 쓰는 커밋 수천 개가 계속 디스크를 먹는다.
#   (2026-08-11 실측: .git 5.0GB 중 대부분이 7월 이전 staging 브랜치)
#
# 쓰는 법
#   bash tools/dev_clean.sh          # 무엇을 지울지 '보여주기만' (아무것도 안 지움)
#   bash tools/dev_clean.sh --run    # 실제 정리
#
# 안전장치
#   · 현재 작업 브랜치(release)와 원격 추적 브랜치는 절대 건드리지 않는다.
#   · 지우기 전에 "origin/main 에 없는 파일"이 있는지 브랜치마다 확인한다.
#     하나라도 있으면 그 브랜치는 건너뛰고 목록만 보여준다(--all 로 강제 가능).
#   · 커밋 안 한 변경이 있으면 시작조차 안 한다.
#   · 코드의 정답은 언제나 origin/main 이다. 여기서 지우는 건 전부 '이미 반영된' 것.

set -e
cd "$(dirname "$0")/.."

KEEP=release           # 지금 작업 중인 브랜치 — 절대 안 지움
RUN=0; ALL=0
for a in "$@"; do
  [ "$a" = "--run" ] && RUN=1
  [ "$a" = "--all" ] && ALL=1
done
say() { [ "$RUN" = "1" ] && echo "$@" || echo "   (미리보기) $@"; }

echo "▶ 저장소: $(pwd)"
if [ -n "$(git status --porcelain --untracked-files=no)" ]; then
  echo "✋ 커밋하지 않은 변경이 있습니다. 먼저 커밋하거나 보관(stash)하세요."
  git status --short --untracked-files=no | head -20
  exit 1
fi

git fetch origin --prune -q
SZ_BEFORE=$(du -sm .git 2>/dev/null | cut -f1)
echo "▶ 지금 .git 용량: ${SZ_BEFORE}MB"
echo

# worktree 목록을 한 번만 읽어 둔다 (지우는 도중에 바뀌므로)
WT_LIST=$(git worktree list --porcelain | awk '/^worktree /{print substr($0,10)}')
MAIN_WT=$(echo "$WT_LIST" | head -1)
FREED=''      # 이번에 정리돼 '자유로워질' 브랜치들

# ── 1) 다 쓴 worktree 정리 ────────────────────────────────────────
# Claude 작업용 worktree(.claude/worktrees/*)는 작업이 끝나면 남을 이유가 없다.
echo "── 다 쓴 작업폴더(worktree)"
for WT in $WT_LIST; do
  case "$WT" in
    */.claude/worktrees/*) ;;
    *) continue ;;
  esac
  BRWT=$(git -C "$WT" symbolic-ref --short HEAD 2>/dev/null || echo '')
  FREED="$FREED $BRWT"
  echo "  · $WT  [$BRWT]"
  if [ "$RUN" = "1" ]; then
    git worktree remove --force "$WT" && echo "    → 제거함"
  fi
done
[ "$RUN" = "1" ] && git worktree prune || true
echo

# ── 1-2) 남아 있는 작업폴더는 원격 최신으로 맞춘다 ────────────────
# 폴더는 그대로 두되(사장님 바탕화면에 보이는 폴더일 수 있다) 그 안의 브랜치가
# 붙들고 있는 압축 전 옛 히스토리를 놓게 한다. 이게 용량의 대부분이다.
echo "── 남겨둘 작업폴더 — 원격 최신으로 맞춤"
for WT in $WT_LIST; do
  [ "$WT" = "$MAIN_WT" ] && continue
  case "$WT" in */.claude/worktrees/*) continue ;; esac
  BRWT=$(git -C "$WT" symbolic-ref --short HEAD 2>/dev/null || echo '')
  [ -z "$BRWT" ] && continue
  if ! git rev-parse --verify -q "origin/$BRWT" >/dev/null; then
    echo "  ! $WT [$BRWT] — 원격에 같은 이름이 없어 건너뜀"; continue
  fi
  if [ -n "$(git -C "$WT" status --porcelain --untracked-files=no)" ]; then
    echo "  ! $WT [$BRWT] — 커밋 안 한 변경이 있어 건너뜀"; continue
  fi
  AHEAD=$(git rev-list --count "origin/$BRWT..$BRWT" 2>/dev/null || echo 0)
  echo "  · $WT [$BRWT] — 옛 커밋 ${AHEAD}개 놓고 origin/$BRWT 로"
  if [ "$RUN" = "1" ]; then
    git -C "$WT" reset --hard "origin/$BRWT" -q && echo "    → 맞춤"
  fi
done
echo

# ── 2) 이미 반영된 옛 브랜치 삭제 ─────────────────────────────────
echo "── 옛 로컬 브랜치 (origin/main 에 내용이 이미 들어간 것)"
for BR in $(git for-each-ref --format='%(refname:short)' refs/heads/); do
  [ "$BR" = "$KEEP" ] && continue
  # 아직 어딘가에 checkout 돼 있으면 건너뛴다 (위에서 정리될 예정인 것은 제외)
  case " $FREED " in *" $BR "*) IN_WT=0 ;; *) IN_WT=1 ;; esac
  if [ "$IN_WT" = "1" ] && git worktree list --porcelain | grep -qx "branch refs/heads/$BR"; then
    echo "  · $BR — 작업폴더에 열려 있음(위에서 원격 최신으로 맞춤). 브랜치는 유지"
    continue
  fi
  UNIQ=$(git diff --name-only --diff-filter=A origin/main "$BR" | head -20)
  N=$(git rev-list --count "origin/main..$BR" 2>/dev/null || echo '?')
  if [ -n "$UNIQ" ] && [ "$ALL" != "1" ]; then
    echo "  ! $BR (${N}커밋) — origin/main 에 없는 파일이 있어 건너뜀:"
    echo "$UNIQ" | sed 's/^/      /'
    echo "      확인 후 지우려면: bash tools/dev_clean.sh --run --all"
    continue
  fi
  echo "  · $BR (${N}커밋)"
  [ "$RUN" = "1" ] && git branch -D "$BR" >/dev/null && echo "    → 삭제함"
done
echo

# ── 3) 옛 보관함(stash) ───────────────────────────────────────────
if [ -n "$(git stash list)" ]; then
  echo "── 보관함(stash) — 내용 확인 후 직접 판단하세요"
  git stash list | sed 's/^/  · /'
  echo "  (지우려면: git stash drop)"
  echo
fi

# ── 4) 실제 용량 회수 ─────────────────────────────────────────────
if [ "$RUN" = "1" ]; then
  echo "▶ 옛 객체 정리 중… (몇 분 걸릴 수 있습니다)"
  git reflog expire --expire=now --expire-unreachable=now --all
  git gc --prune=now --quiet
  SZ_AFTER=$(du -sm .git 2>/dev/null | cut -f1)
  echo
  echo "✅ 완료 — .git ${SZ_BEFORE}MB → ${SZ_AFTER}MB"
else
  echo "위 목록이 맞으면 실제로 정리:"
  echo "   bash tools/dev_clean.sh --run"
fi
