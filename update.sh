cd /root/gyeonggi-dashboard

# ── 중복 실행 방지 ─────────────────────────────────────────────────
# 지역이 둘로 늘어 한 회차가 3분 가까이 걸린다. 네트워크가 느린 날엔 5분을 넘겨
# 다음 cron과 겹칠 수 있고, 그러면 두 프로세스가 같은 저장소에 동시에 커밋한다.
# 이미 돌고 있으면 이번 회차는 조용히 건너뛴다(다음 5분에 다시 온다).
exec 9>/tmp/gg-dashboard-update.lock
if ! flock -n 9; then
  echo "⏭  이전 회차가 아직 실행 중 — 이번 회차 건너뜀 $(date '+%F %R')" >> cron.log
  exit 0
fi

# 디스크 자동 정리 — 용량이 꽉 차면 git 갱신·상태저장이 실패해 알림이 폭주한다.
# 매 실행 앞단에서 로그와 git 잔여물을 정리해 서버가 스스로 용량을 회복하게 한다.
: > cron.log 2>/dev/null || true          # cron.log 비우기 (append로 무한 증가 방지)
[ -f warn.log ] && : > warn.log 2>/dev/null || true
find . -maxdepth 2 -name '*.tmp.*' -mmin +60 -delete 2>/dev/null || true  # 원자적저장 임시파일 잔재
git gc --prune=now --quiet 2>/dev/null || true   # .git 압축

# fix_gyeonggi.sh(auto-trade, 06시)가 .git을 재생성하며 남긴 잠금 잔재 자가정리 (없으면 무시)
rm -f .git/index.lock 2>/dev/null || true

# ── 원격 동기화 ────────────────────────────────────────────────────
# 예전엔 무조건 reset --hard 했다. 이제는 배포하는 회차에만 커밋하므로(update_data.py
# push_only), 배포 사이의 회차에는 아직 안 올린 데이터 변경이 작업트리에 남아 있다.
# 무조건 되돌리면 그걸 매번 지워버린다(위성영상·강수누적 기록이 5분마다 원복).
# → 원격이 우리보다 앞서 있을 때(코드 배포·히스토리 압축)만 되돌린다.
git fetch origin -q
if ! git merge-base --is-ancestor origin/main HEAD 2>/dev/null; then
  git reset --hard origin/main -q          # 원격에 새 코드 있음 — 데이터는 이번 회차에 다시 만든다
fi
# push 목적지(upstream) 자동복구 — .git이 재생성돼 upstream이 날아가도 다음 push 정상화
git branch --set-upstream-to=origin/main main 2>/dev/null || true

# ── check_warnings.py(1분 즉시 특보 알리미) cron 자가등록 ─────────────
# SSH 없이 서버가 스스로 1분 알림 cron을 등록한다. crontab에 update.sh 라인이
# 있을 때만(=정상 crontab이 읽힌 것 확인 → 오토트레이딩 등 기존 cron 안전) +
# check_warnings가 아직 없을 때만 전체 crontab 뒤에 한 줄 추가한다.
CRON_NOW=$(crontab -l 2>/dev/null)
if echo "$CRON_NOW" | grep -q 'update.sh' && ! echo "$CRON_NOW" | grep -qF 'check_warnings.py'; then
  ( echo "$CRON_NOW"; echo '* * * * * cd /root/gyeonggi-dashboard && /usr/bin/python3 tools/check_warnings.py >> warn.log 2>&1' ) | crontab - \
    && echo "🔔 check_warnings 1분 cron 자가등록 $(date '+%F %R')" >> cron.log
fi

# ── 히스토리 자동 압축 ──────────────────────────────────────────────
# 5분마다 data.js+기상영상을 커밋하므로 방치하면 저장소가 하루 수백MB씩 커진다
# (과거 staging 브랜치 5GB 디스크 폭주와 같은 패턴). 임계를 넘으면 전체 트리를
# 1커밋으로 눌러 새로 시작. --force-with-lease 라서 그 사이 다른 푸시(코드 배포)가
# 끼어들면 안전하게 포기하고 다음 회차에 재시도한다.
#
# ⚠ 이 압축은 히스토리를 통째로 갈아치우므로, 다른 클론(개발 PC)은 그때부터
#   공통 조상이 사라져 rebase가 불가능해진다. 그래서 '꼭 필요할 때만' 돌려야 한다.
#   예전엔 '커밋 300개'로 판단했는데, 커밋 수는 용량의 대리지표일 뿐이라 디스크가
#   멀쩡한데도 하루 한 번씩 압축이 돌았다. 이제 실제 .git 용량을 직접 본다.
#   (커밋 수는 du가 없는 환경을 위한 백스톱으로만 남긴다)
GITMB=$(du -sm .git 2>/dev/null | cut -f1)
CNT=$(git rev-list --count HEAD 2>/dev/null || echo 0)
FLUSH_MB=1200        # .git 이 1.2GB를 넘으면 압축
FLUSH_CNT=2000       # 용량 측정이 안 될 때의 안전장치
if [ "${GITMB:-0}" -gt "$FLUSH_MB" ] || [ "${CNT:-0}" -gt "$FLUSH_CNT" ]; then
  BASE=$(git rev-parse origin/main 2>/dev/null)
  git branch -qD _flush 2>/dev/null || true
  # add -A 필수 — 배포 사이 회차의 데이터는 아직 커밋 전이라 인덱스에 없다.
  # (--orphan은 HEAD 트리만 인덱스에 올린다) 없으면 압축이 옛 데이터로 되돌린다.
  if [ -n "$BASE" ] && git checkout -q --orphan _flush && git add -A \
     && git commit -qm "flush: 히스토리 압축 (이전 ${CNT}커밋) $(date '+%F %R')"; then
    git branch -qM main
    if git push -qu --force-with-lease=refs/heads/main:${BASE} origin main 2>>cron.log; then
      git gc --prune=now --quiet 2>/dev/null || true
      echo "🧹 히스토리 압축: ${CNT}커밋 / .git ${GITMB}MB → 1커밋 (임계 ${FLUSH_MB}MB)" >> cron.log
    else
      git fetch origin -q && git reset --hard origin/main -q   # 푸시 경합 — 포기·원상복구
    fi
  else
    git checkout -qf main 2>/dev/null || true
    git fetch origin -q && git reset --hard origin/main -q
  fi
fi

# ── 지역별 수집 ────────────────────────────────────────────────────
# 경기북부(약 2분)와 경기남부(약 3분)를 순서대로 돌리면 5분 cron을 넘겨 다음 회차와
# 겹친다. 서로 건드리는 파일이 없으므로(상태폴더 .tmp/ vs .tmp/south/, 남부는
# 기상청 이미지를 북부 것을 재사용) 동시에 돌리고 둘 다 끝난 뒤 한 번만 푸시한다.
# → 걸리는 시간 = 둘 중 긴 쪽(약 3분).
#
# 푸시를 각자 하게 두면 같은 저장소에 동시에 커밋해 경합이 난다. 그래서 수집은
# --no-push로 파일만 만들고, 마지막 --push-only가 한꺼번에 커밋·푸시·배포한다.
/usr/bin/python3 tools/update_data.py --profile south --no-push >> cron.log 2>&1 &
SOUTH_PID=$!
/usr/bin/python3 tools/update_data.py --no-push >> cron.log 2>&1
wait $SOUTH_PID
/usr/bin/python3 tools/update_data.py --push-only >> cron.log 2>&1
