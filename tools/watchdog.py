# -*- coding: utf-8 -*-
"""워치독 — 서버 '바깥'(GitHub Actions)에서 운영 사이트의 데이터가 멈췄는지 본다.

왜 필요한가
  서버(네이버)가 디스크 부족으로 멈추면 서버 안의 알림(텔레그램 알리미·disk_guard)도 같이 죽는다.
  실제로 2026-07-06(이틀)·10-26~10-31(5일)·11-01(하루) 세 번, 아무 알림 없이 화면만 멈춰 있었다.
  그래서 서버와 무관한 GitHub Actions 가 30분마다 '사이트에 실제로 나가 있는 data.js'를 받아 본다.

판정
  - data.js 를 끝까지 읽을 수 없으면(잘림·깨짐) 바로 '멈춤' — 11-01 처럼 디스크가 차면 파일이 4KB 단위로 잘린다.
  - `updated`(KST)가 STALE_MIN 분보다 오래면 '멈춤'. 평소 배포 간격 최대 40분 + 반영 몇 분이라 60분이면 오경보가 없다.
    (지도.html 의 '⚠ N분째 갱신 없음' 배지는 50분 — 화면은 먼저, 워치독은 그 뒤에)

알림 (상태는 GitHub Actions 캐시의 .watchdog/state.json 에 남긴다)
  - 정상 → 멈춤: 즉시 1회
  - 멈춤이 이어지면: REMIND_H 시간마다 1회
  - 멈춤 → 정상: '복구' 1회
  알림을 내는 회차는 텔레그램(키가 있으면)으로 보내고, 멈춤 알림이면 이 작업을 '실패'로 끝내
  GitHub 가 실패 메일을 보내게 한다(키가 없어도 메일은 간다). 그 밖의 회차는 조용히 성공.

로컬 시험:  python tools/watchdog.py --dry-run          (알림 안 보냄, 판정만 출력)
            python tools/watchdog.py --dry-run --stale-min 1   (일부러 멈춤으로 판정)
"""
import argparse
import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))
SITES = [
    # 2026-11-10 ggweather·weather 전국판 통합 — 두 주소의 경기 화면은 운영 주소의 합본(data-all.js)을 읽는다
    ('경기 전체(data-all.js)', 'https://gyeonggi-dashboard.visanu81.workers.dev/data-all.js'),
    ('경기북부(gyeonggi-dashboard)', 'https://gyeonggi-dashboard.visanu81.workers.dev/data.js'),
]
STALE_MIN = 60
REMIND_H = 6
STATE_PATH = os.path.join('.watchdog', 'state.json')
MARK = 'window.DASHBOARD_DATA'


def now_kst():
    return datetime.now(KST)


def check(url, stale_min):
    """→ (멈춤?, 한 줄 설명)"""
    try:
        req = urllib.request.Request(url + '?wd=' + str(int(now_kst().timestamp())),
                                     headers={'Cache-Control': 'no-cache', 'User-Agent': 'gg-watchdog'})
        with urllib.request.urlopen(req, timeout=30) as r:
            text = r.read().decode('utf-8', errors='replace')
    except Exception as e:
        return True, f'받기 실패 ({type(e).__name__})'
    try:
        i = text.index('{', text.index(MARK) if MARK in text else 0)
        data = json.loads(text[i:].rstrip().rstrip(';').strip())
    except Exception:
        return True, f'파일이 깨짐/잘림 ({len(text):,}B) — 서버 디스크 부족 때의 증상'
    upd = data.get('updated') or ''
    try:
        t = datetime.strptime(upd, '%Y-%m-%d %H:%M:%S').replace(tzinfo=KST)
    except ValueError:
        return True, f"갱신시각 읽기 실패 ('{upd}')"
    age = int((now_kst() - t).total_seconds() // 60)
    if age > stale_min:
        return True, f'{age // 60}시간 {age % 60}분째 멈춤 (마지막 {upd[5:16]})' if age >= 60 else f'{age}분째 멈춤 (마지막 {upd[5:16]})'
    return False, f'정상 ({age}분 전 {upd[11:16]})'


def load_state():
    try:
        with open(STATE_PATH, encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def save_state(st):
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    with open(STATE_PATH, 'w', encoding='utf-8') as f:
        json.dump(st, f, ensure_ascii=False)


def send_telegram(msg):
    tok, chat = os.environ.get('TELEGRAM_BOT_TOKEN', ''), os.environ.get('TELEGRAM_CHAT_ID', '')
    if not tok or not chat:
        print('텔레그램 키 없음 — 메일(작업 실패 알림)로만 알린다')
        return
    body = urllib.parse.urlencode({'chat_id': chat, 'text': msg, 'disable_web_page_preview': 'true'}).encode()
    try:
        urllib.request.urlopen(f'https://api.telegram.org/bot{tok}/sendMessage', body, timeout=20).read()
        print('텔레그램 보냄')
    except Exception as e:
        print(f'텔레그램 실패 ({type(e).__name__})')   # 메시지에 토큰이 섞이지 않게 종류만


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--stale-min', type=int, default=STALE_MIN)
    a = ap.parse_args()

    results = [(name, *check(url, a.stale_min)) for name, url in SITES]
    stale = any(s for _, s, _ in results)
    lines = [f"{'🔴' if s else '🟢'} {name}: {why}" for name, s, why in results]
    print('\n'.join(lines))

    st = load_state()
    now = now_kst()
    was_stale = bool(st.get('stale_since'))
    last_alert = datetime.fromisoformat(st['last_alert']) if st.get('last_alert') else None
    msg, fail = None, False

    if stale and not was_stale:
        st['stale_since'] = now.isoformat()
        msg, fail = '🐶 [워치독] 상황판 데이터가 멈췄습니다', True
    elif stale and (last_alert is None or now - last_alert >= timedelta(hours=REMIND_H)):
        since = datetime.fromisoformat(st['stale_since'])
        h = int((now - since).total_seconds() // 3600)
        msg, fail = f'🐶 [워치독] 아직 멈춰 있습니다 (감지 후 {h}시간)', True
    elif not stale and was_stale:
        since = datetime.fromisoformat(st['stale_since'])
        m = int((now - since).total_seconds() // 60)
        msg = f'✅ [워치독] 상황판 데이터가 다시 갱신됩니다 (멈춤 감지 후 {m // 60}시간 {m % 60}분)'
        st.pop('stale_since', None)

    if msg:
        full = msg + '\n' + '\n'.join(lines)
        if stale:
            full += ('\n\n먼저 볼 것: 네이버 서버 디스크 (콘솔에서 df -h /)'
                     '\n지난 사례 3번 모두 디스크 부족 — workflows/운영현황.md \'워치독\' 참고')
        print('\n--- 알림 ---\n' + full)
        if not a.dry_run:
            send_telegram(full)
            st['last_alert'] = now.isoformat()
    st['last_check'] = now.isoformat()
    st['last_result'] = 'stale' if stale else 'ok'
    if not a.dry_run:
        save_state(st)
    return 1 if (fail and not a.dry_run) else 0


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    sys.exit(main())
