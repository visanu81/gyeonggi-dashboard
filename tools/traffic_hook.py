# -*- coding: utf-8 -*-
"""교통상황판을 이 서버에서 돌려주는 다리.

기상상황판 cron(update.sh)이 5분마다 이걸 부른다.

왜 이 서버에 얹었나
  교통상황판(traffic.visanu81.workers.dev)도 자기 cron 이 있는데 그게 조용히
  실패해 하루 넘게 데이터가 안 올라왔다. 네이버클라우드 콘솔은 붙여넣기가 안 되고
  한글이 깨져서 사장님이 서버에 들어가 고치기가 어렵다. 기상상황판 cron 은 5분마다
  확실히 도는 게 확인됐으니, 여기에 얹으면 교통상황판도 확실히 돈다.

왜 셸이 아니라 파이썬인가
  · 서버에 curl 이 없을 수 있다. python3 는 기상상황판이 쓰고 있어 확실히 있다.
  · 파이썬 기본 요청은 Cloudflare 가 403 으로 막는다 → User-Agent 를 붙인다.
    (이걸 몰라서 한참 헤맸다.)

★ 기상상황판에 절대 영향을 주면 안 된다.
  무슨 일이 나도 예외를 삼키고 조용히 끝낸다. 종료코드도 항상 0 이다.
"""
import io
import os
import subprocess
import sys
import tarfile
import tempfile
import urllib.request

BASE = 'https://traffic.visanu81.workers.dev'
DIR = '/root/traffic-board'
LOCK = '/tmp/traffic-board.lock'
# 인증키 파일을 받아올 때 쓰는 열쇠. 이 저장소는 비공개라 여기 둔다.
# 실제 인증키(ITS·올리기 열쇠)는 여기 없고 Cloudflare 에 있다 — 저장소가 새면
# 이 열쇠만 바꾸면 된다.
ENV_KEY = 'IelcydSAoHBMENUmXPo-c6ftzvFkr_0V'
UA = {'User-Agent': 'gyeonggi-dashboard-server/1.0'}


def get(path, timeout=60):
    req = urllib.request.Request(BASE + path, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def log(msg):
    print(msg)
    sys.stdout.flush()


def mark(tag):
    """어디까지 왔는지 클라우드에 남긴다.

    서버 로그는 사장님이 콘솔에 들어가야 볼 수 있는데 그게 어려워서 이 다리를
    만든 것이다. 그러니 이 다리가 실패하면 그것도 밖에서 보여야 한다.
    원인이 잡히면 이 줄들은 지운다.
    """
    try:
        urllib.request.urlopen(
            urllib.request.Request(BASE + '/__ping?w=' + tag, headers=UA),
            timeout=10).read()
    except Exception:
        pass


def refresh_code():
    """올라온 코드가 서버 것과 다르면 갈아끼운다. 바꿨으면 True."""
    try:
        want = get('/codever', 20).decode('utf-8').strip()
    except Exception as exc:
        log('판 번호를 못 읽음(그냥 진행): %s' % exc)
        return False
    if not want:
        return False

    have = ''
    try:
        have = io.open(os.path.join(DIR, '.codever'), encoding='utf-8').read().strip()
    except Exception:
        pass
    if have == want:
        return False

    log('코드 갱신 %s -> %s' % (have or 'none', want))
    blob = get('/code', 90)
    tmp = os.path.join(tempfile.mkdtemp(), 'code.tar.gz')
    with open(tmp, 'wb') as f:
        f.write(blob)

    # 깨진 걸 풀면 서버가 죽는다. 먼저 열어보고 나서 덮어쓴다.
    with tarfile.open(tmp) as tar:
        names = tar.getnames()
        if 'update.sh' not in names:
            log('꾸러미가 이상하다(update.sh 없음) — 건너뛴다')
            return False
        if not os.path.isdir(DIR):
            os.makedirs(DIR)
        tar.extractall(DIR)

    os.chmod(os.path.join(DIR, 'update.sh'), 0o755)
    io.open(os.path.join(DIR, '.codever'), 'w', encoding='utf-8').write(want)

    # 갈아끼운 김에 물려 있을지 모르는 잠금과 실패 기록을 치운다.
    for p in (LOCK, os.path.join(DIR, '.tmp', 'cache', 'state.json')):
        try:
            os.remove(p)
        except Exception:
            pass
    log('코드 갱신 완료')
    return True


def ensure_env():
    """인증키 파일이 없으면 받아온다.

    코드 꾸러미(/code)에는 인증키를 일부러 안 넣는다(열쇠 없이 받을 수 있어서).
    그러다 보니 서버에 .env 가 하나도 없어 수집이 종료코드 2 로 죽고 있었다.
    진단 신호 H7-exit-2 로 밝혀진 원인이다.
    """
    path = os.path.join(DIR, '.env')
    try:
        cur = io.open(path, encoding='utf-8').read()
        for row in cur.splitlines():
            if row.startswith('ITS_KEY=') and row[8:].strip():
                return           # 이미 쓸 만한 게 있다
    except Exception:
        pass

    req = urllib.request.Request(BASE + '/__env?key=' + ENV_KEY, headers=UA)
    body = urllib.request.urlopen(req, timeout=30).read().decode('utf-8')
    if 'ITS_KEY=' not in body:
        return
    if not os.path.isdir(DIR):
        os.makedirs(DIR)
    io.open(path, 'w', encoding='utf-8').write(body)
    try:
        os.chmod(path, 0o600)            # 남이 못 읽게
    except Exception:
        pass
    log('인증키 파일을 받아 넣었다')


def main():
    try:
        ensure_env()
    except Exception as exc:
        log('인증키 파일 준비 실패(그냥 진행): %s' % exc)
    try:
        refresh_code()
    except Exception as exc:
        log('코드 갱신 실패(그냥 진행): %s' % exc)

    run = os.path.join(DIR, 'update.sh')
    if not os.path.exists(run):
        log('교통상황판이 아직 안 깔렸다 — 다음 회차에 다시 시도한다')
        return

    try:
        r = subprocess.run(['bash', run], timeout=300,
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        log('update.sh 종료코드 %s' % r.returncode)
        tail = r.stdout.decode('utf-8', 'replace').strip().splitlines()[-6:]
        for line in tail:
            log('  ' + line)
    except Exception as exc:
        log('update.sh 실행 실패: %s' % exc)


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:          # 어떤 일이 있어도 기상상황판엔 영향 없게
        log('예상 못한 오류(무시): %s' % exc)
    sys.exit(0)
