# -*- coding: utf-8 -*-
"""기상·재난 상황판 데이터 수집기 (지역 프로파일 방식).

기상청·환경공단·산림청·한강홍수통제소·행안부 공공 API를 호출해 data 파일을 갱신한다.
지역마다 다른 값(시군·관측소·특보구역)은 tools/region_profiles.py 에 있고,
이 파일의 함수들은 지역을 가리지 않는다.

실행:
  python tools/update_data.py                                 경기북부 → data.js
  python tools/update_data.py --profile south --no-push       경기남부 → data-south.js
"""
import json
import os
import subprocess
import sys
import time
import traceback
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from pathlib import Path

import requests

# Windows 콘솔 한글 출력
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

# ───────────────────────────────────────────────────────────────
# 모든 시각을 한국 표준시(KST)로 통일.
#
# - GitHub Actions(Linux): 기본 UTC라 datetime.now()가 9시간 전을 반환.
#   → os.environ['TZ']='Asia/Seoul' + time.tzset()으로 KST 적용.
# - Windows(사장님 PC): 시스템 시계가 이미 KST.
#   ⚠️ 주의: Windows Python은 'Asia/Seoul'(IANA 형식)을 파싱하지 못하고
#   tzset()도 없어서, os.environ['TZ']='Asia/Seoul'을 설정하면 오히려
#   datetime.now()가 UTC로 깨진다(데이터 시각이 9시간 늦게 찍힘).
#   따라서 Windows에서는 TZ를 절대 건드리지 않는다.
if sys.platform != 'win32':
    os.environ['TZ'] = 'Asia/Seoul'
    time.tzset()        # Unix(GitHub Actions Linux) 전용
# ───────────────────────────────────────────────────────────────

ROOT = Path(__file__).resolve().parent.parent


def _atomic_write_text(path, text):
    """상태파일을 원자적으로 저장 — 같은 폴더에 임시파일을 쓴 뒤 os.replace로 교체.

    write_text는 대상 파일을 먼저 0으로 비우고 쓰므로, ①1분/5분 알리미가 동시에
    읽고 쓸 때 다른 쪽이 '비워진 순간'을 읽거나 ②디스크가 꽉 차 쓰기가 실패하면
    파일이 잘려 중복 방지 상태가 통째로 날아간다(→ 같은 특보 반복 발송).
    os.replace는 원자적이라 읽는 쪽은 항상 '완전한 이전' 또는 '완전한 새' 상태만
    보고, 쓰기 실패 시에는 직전 정상 파일이 그대로 보존된다. 실패해도 예외를 올려
    호출부가 '저장 성공'으로 오판하지 않게 한다."""
    path = Path(path)
    path.parent.mkdir(exist_ok=True)
    tmp = path.with_name(f'{path.name}.tmp.{os.getpid()}')
    try:
        tmp.write_text(text, encoding='utf-8')
        os.replace(tmp, path)   # 원자적 교체 (POSIX rename)
    except Exception:
        try:
            tmp.unlink()        # 실패 시 임시파일 청소 (디스크 낭비 방지)
        except OSError:
            pass
        raise


# ───────────────────────────────────────────────────────────────
# 지역 프로파일 — 어느 지역 상황판을 만들 것인가
#
#   python tools/update_data.py                  → 경기북부 (기본, 기존과 동일)
#   python tools/update_data.py --profile south  → 경기남부 (data-south.js)
#   ... --no-push     : 깃 푸시·배포 생략 (여러 지역을 연달아 돌릴 때 마지막 회차만 푸시)
#   ... --no-notify   : 텔레그램 알림 생략
#
# 지역마다 다른 값(시군 목록·관측소·특보구역)은 전부 tools/region_profiles.py에 있다.
# 아래 상수들은 그 프로파일에서 꺼내 쓰는 것이고, 함수 본문은 지역을 가리지 않는다.
# ───────────────────────────────────────────────────────────────
sys.path.insert(0, str(Path(__file__).resolve().parent))
import region_profiles as _rp   # noqa: E402


def _argval(flag, default=None):
    if flag in sys.argv:
        i = sys.argv.index(flag)
        if i + 1 < len(sys.argv):
            return sys.argv[i + 1]
    return default


PROFILE_NAME = _argval('--profile', 'north')
P = _rp.get(PROFILE_NAME)
NO_PUSH = '--no-push' in sys.argv
NO_NOTIFY = '--no-notify' in sys.argv or not P['notify']

ENV_PATH = ROOT / '.env'
OUTPUT_PATH = ROOT / P['data_file']
TEMPLATE_PATH = ROOT / 'index.html'
COMBINED_OUTPUT_PATH = ROOT / P['combined_file']

# 상태파일 폴더 — 지역마다 완전히 분리한다. 같이 쓰면 남부 특보가 북부 알림
# 중복방지 기록을 덮어써서 '이미 보냄' 판정이 뒤섞인다(알림 누락·중복의 원인).
TMP = (ROOT / '.tmp') if PROFILE_NAME == 'north' else (ROOT / '.tmp' / PROFILE_NAME)
TMP.mkdir(parents=True, exist_ok=True)


def load_env(path=ENV_PATH):
    env = {}
    if path.exists():
        with open(path, encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                if '=' in line:
                    k, v = line.split('=', 1)
                    env[k.strip()] = v.strip()
    # GitHub Actions 등 .env 없는 환경에서는 OS 환경변수로 fallback
    import os
    for key in ('DATA_GO_KR_KEY', 'HRFCO_KEY', 'SAFETY_DATA_KEY', 'KMA_APIHUB_KEY',
                'TELEGRAM_BOT_TOKEN', 'TELEGRAM_CHAT_ID'):
        env.setdefault(key, os.environ.get(key, ''))
    return env


ENV = load_env()
DATA_KEY = ENV.get('DATA_GO_KR_KEY', '')
HRFCO_KEY = ENV.get('HRFCO_KEY', '')
SAFETY_KEY = ENV.get('SAFETY_DATA_KEY', '')
KMA_APIHUB_KEY = ENV.get('KMA_APIHUB_KEY', '')  # 기상청 API 허브 (apihub.kma.go.kr)
TELEGRAM_BOT_TOKEN = ENV.get('TELEGRAM_BOT_TOKEN', '')  # 텔레그램 봇 (급변 알림)
TELEGRAM_CHAT_ID = ENV.get('TELEGRAM_CHAT_ID', '')

# ───────────────────────────────────────────────────────────────
# 보안: 로그(cron.log)에 API 키가 평문으로 남는 것을 차단.
#
# requests 예외 메시지에는 호출 URL이 통째로 들어있고(serviceKey=…·
# authKey=… 포함), 이를 print하면 키가 cron.log에 그대로 찍힌다.
# 아래에서 stdout/stderr를 감싸 모든 출력에서 알려진 비밀값과
# 자격증명 패턴을 '***'로 치환한다. 새 fetch_* 함수가 추가돼도 자동 보호.
# ───────────────────────────────────────────────────────────────
import re as _re

# .env에서 읽은 실제 비밀값 (빈 값은 제외 — ''.replace는 모든 위치에 끼어듦)
_SECRETS = [v for v in (DATA_KEY, HRFCO_KEY, SAFETY_KEY, KMA_APIHUB_KEY,
                        TELEGRAM_BOT_TOKEN) if v]
# URL 자격증명 패턴 — 값이 .env와 안 맞아도(또는 git 원격 URL의 토큰까지) 잡음
_CRED_QUERY = _re.compile(r'(?i)(serviceKey|authKey)=[^&\s\'"]+')
_CRED_TOKEN = _re.compile(r'(?:ghp_[A-Za-z0-9]{20,}'
                          r'|github_pat_[A-Za-z0-9_]{20,}'
                          r'|bot\d{6,}:[A-Za-z0-9_-]{30,})')


def _redact(text):
    """문자열에서 비밀값·자격증명을 '***'로 가린다. 로그·에러 출력 전용."""
    s = str(text)
    for secret in _SECRETS:
        s = s.replace(secret, '***')
    s = _CRED_QUERY.sub(r'\1=***', s)
    s = _CRED_TOKEN.sub('***', s)
    return s


class _RedactingStream:
    """stdout/stderr 프록시 — write되는 모든 텍스트에서 비밀값을 가린다."""

    def __init__(self, stream):
        self._stream = stream

    def write(self, data):
        return self._stream.write(_redact(data))

    def flush(self):
        return self._stream.flush()

    def __getattr__(self, name):
        return getattr(self._stream, name)


sys.stdout = _RedactingStream(sys.stdout)
sys.stderr = _RedactingStream(sys.stderr)

# 시군 목록 + 기상청 격자좌표(nx,ny) + 산불위험 시군구코드 — 지역 프로파일에서
REGIONS = P['regions']

# 미세먼지 측정소: 시군 → 대표 측정소명 매핑 (에어코리아 실제 등록명 기준)
PM_STATIONS = P['pm_stations']

# 이 상황판이 담당하는 시군 집합 — 특보·재난문자·산불통계 필터의 공통 기준.
SIGUN_SET = {r['name'] for r in REGIONS}
# 시(市)가 아니라 군(郡)인 곳 — 재난문자 발신처 표기('연천군' vs '파주시')에 쓴다.
GUN_NAMES = {'연천', '가평', '양평'} & SIGUN_SET



def now_str():
    return datetime.now().strftime('%H:%M:%S')


# ============================================================
# 1-A. AWS 방재기상관측 — 관서별 실측 강수 (기상청 공식 누적)
# ============================================================
# 왜 필요한가: rain_cumul(자체누적)은 RN1을 우리가 직접 쌓아 만든 값이라
#   서버·cron이 한 시간 멈추면 그 시간이 0으로 빠져 '실제보다 적게' 나온다
#   — 호우 상황에서 가장 나쁜 실패 방향. AWS는 기상청이 계산한 공식 누적을 준다.
# 지점 목록은 apihub stn_inf(inf=AWS)를 법정동코드(LAW_ID 앞5자리)로 매칭해 뽑았다.
#   ※ 지점'명'으로 매칭하면 오탐남(포항시남구 → '구리'로 걸림). 코드로만 매칭할 것.
#   ※ 이 매핑 덕에 고양(덕양 41281)과 일산(41285/41287)이 처음으로 진짜 분리된다.
AWS_STATIONS = P['aws_stations']
# 일산은 관측소가 1개뿐 → 그게 결측이면 인접 관서로 대체하고 화면에 대체 사실을 표기한다
AWS_FALLBACK = P['aws_fallback']


def _aws_num(v):
    """AWS 강수·풍속 값 → float. 결측은 None.

    ⚠ 0으로 바꾸면 호우 중에 '비 안 옴'으로 표시된다 — 가장 위험한 오표시.
    결측 표기가 -99/-99.9/-9 등으로 섞여 나오므로 특정 값이 아니라 '음수 전체'를
    결측으로 본다. 강수량·풍속은 음수가 존재할 수 없으므로 안전하다.
    (기온 등 음수가 정상인 항목에는 이 함수를 쓰지 말 것.)
    """
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if f < 0 else f


def fetch_aws_rain():
    """AWS 매분자료 1회 호출로 전 관서 실측 강수·돌풍 수집.

    엔드포인트는 cgi-bin 경로이고 EUC-KR이다(/url/ 경로로 부르면 404).
    컬럼: YYMMDDHHMI STN WD1 WS1 WDS WSS WD10 WS10 TA RE RN-15m RN-60m RN-12H RN-DAY HM PA PS TD
    반환: {관서: {rn15, rn60, rn12h, rnday, wss, station, stn, ok, total, (alt)}}
          자료 없으면 {'ok': 0, 'total': N} — 0으로 채우지 않는다.
    실패 시 예외 → 호출측이 이전 값 보존.
    """
    if not KMA_APIHUB_KEY:
        return {}
    tm = (datetime.now() - timedelta(minutes=10)).strftime('%Y%m%d%H%M')
    url = ('https://apihub.kma.go.kr/api/typ01/cgi-bin/url/nph-aws2_min'
           f'?tm2={tm}&stn=0&disp=0&help=0&authKey={KMA_APIHUB_KEY}')
    r = requests.get(url, timeout=15)
    r.raise_for_status()
    r.encoding = 'euc-kr'
    text = r.text
    if '활용신청' in text[:300]:
        raise RuntimeError('AWS 활용신청 필요(403)')

    obs = {}
    for line in text.split('\n'):
        s = line.strip()
        if not s or s.startswith('#'):
            continue
        f = s.split()
        if len(f) < 14:
            continue
        try:
            stn = int(f[1])
        except ValueError:
            continue
        obs[stn] = {'wds': _aws_num(f[4]), 'wss': _aws_num(f[5]), 'ws10': _aws_num(f[7]),
                    'rn15': _aws_num(f[10]), 'rn60': _aws_num(f[11]),
                    'rn12h': _aws_num(f[12]), 'rnday': _aws_num(f[13])}
    if not obs:
        raise RuntimeError('AWS 응답에 관측 지점 없음')

    def pick(area):
        """관서 안에서 '가장 많이 온 지점'을 고른다.
        평균을 내면 국지호우가 묻힌다 — 소방은 관할 내 최악지점이 기준."""
        best, ok = None, 0
        for stn, sname in AWS_STATIONS.get(area, []):
            o = obs.get(stn)
            if not o or all(o[k] is None for k in ('rn15', 'rn60', 'rn12h', 'rnday')):
                continue
            ok += 1
            key = (o['rn60'] or 0, o['rn12h'] or 0, o['rnday'] or 0)
            if best is None or key > best[0]:
                best = (key, stn, sname, o)
        return best, ok

    def pick_wind(area):
        """관서 안에서 '바람이 가장 센 지점'을 따로 고른다.
        ⚠ 비가 제일 많은 지점과 바람이 제일 센 지점은 다르다. 강수 대표지점의 돌풍을
          그대로 쓰면 관할 최대 돌풍을 놓친다 — 강풍은 별도로 뽑아야 한다."""
        best = None
        for stn, sname in AWS_STATIONS.get(area, []):
            o = obs.get(stn)
            if not o or o.get('wss') is None:
                continue
            if best is None or o['wss'] > best[0]:
                best = (o['wss'], stn, sname, o)
        if not best:
            return None
        _, stn, sname, o = best
        return {'wss': o['wss'], 'wds': o.get('wds'), 'ws10': o.get('ws10'),
                'station': sname, 'stn': stn}

    out = {}
    for area in AWS_STATIONS:
        best, ok = pick(area)
        total = len(AWS_STATIONS.get(area, []))
        alt = None
        if best is None and area in AWS_FALLBACK:      # 일산처럼 관측소가 전멸한 경우
            alt = AWS_FALLBACK[area]
            best, ok = pick(alt)                       # ⚠ ok도 대체분으로 갱신(안 하면 화면에 '자료없음'으로 뜸)
            total = len(AWS_STATIONS.get(alt, []))     # ok/total을 같은 관서 기준으로 통일
        if best is None:
            out[area] = {'ok': 0, 'total': total}      # 자료없음 (0 아님)
            continue
        _, stn, sname, o = best
        out[area] = {'rn15': o['rn15'], 'rn60': o['rn60'], 'rn12h': o['rn12h'],
                     'rnday': o['rnday'], 'wss': o['wss'], 'station': sname,
                     'stn': stn, 'ok': ok, 'total': total}
        # 강풍은 별도 지점 — 관할 내 '가장 센 바람'(대체 관서를 썼으면 그쪽 기준)
        w = pick_wind(alt or area)
        if w:
            out[area]['wind'] = w
        if alt:
            out[area]['alt'] = alt                     # 대체 관서 — 화면에 반드시 표기
    return out


# ============================================================
# 1. 기상청 단기예보 (시군별 현재 기온/강수/풍속/습도/날씨)
# ============================================================

def fcst_base_time():
    """단기예보 발표시각: 02/05/08/11/14/17/20/23시.
    발표 후 10분 이내엔 이전 발표분 사용."""
    now = datetime.now()
    issue = [23, 20, 17, 14, 11, 8, 5, 2]
    target = now - timedelta(minutes=10)
    for h in issue:
        cand = target.replace(hour=h, minute=0, second=0, microsecond=0)
        if cand <= target:
            return cand.strftime('%Y%m%d'), f'{h:02d}00'
    # 새벽 0~1시: 전날 23시
    prev = (target - timedelta(days=1)).replace(hour=23, minute=0, second=0)
    return prev.strftime('%Y%m%d'), '2300'


def parse_pcp(val):
    """PCP(1시간 강수량) 문자열을 mm 숫자로.

    기상청 표기: '강수없음' | '1.0mm 미만' | '1.2mm' | '30.0~50.0mm' | '50.0mm 이상'
    ⚠ 'mm'을 먼저 지우므로, 이 아래 비교문에 'mm'을 넣으면 영원히 안 맞는다.
      (과거 `val == '1mm 미만'` 검사가 이 때문에 죽은 코드였고, 실제 값 '1.0mm 미만'이
       숫자변환 실패로 0이 되어 '약한 비'가 '비 안 옴'으로 표시됐다.)
    """
    if val is None:
        return 0
    s = str(val).strip()
    if not s or s in ('강수없음', '-', 'null'):
        return 0
    s = s.replace('mm', '').strip()          # '1.0 미만' · '30.0~50.0' · '50.0 이상'
    try:
        if '미만' in s:                       # '1.0 미만' → 절반으로 대표(0.5)
            return float(s.replace('미만', '').strip()) / 2
        if '~' in s:                          # '30.0~50.0' → 중간값(40)
            lo, hi = s.split('~')[:2]
            return (float(lo.strip()) + float(hi.strip())) / 2
        if '이상' in s:                       # '50.0 이상' → 하한 + 10(60)
            return float(s.replace('이상', '').strip()) + 10
        return float(s)
    except ValueError:
        return 0


def deg_to_dir(deg):
    """풍향 0~360° → 16방위 한글."""
    try:
        deg = float(deg)
    except (TypeError, ValueError):
        return '-'
    dirs = ['북', '북북동', '북동', '동북동', '동', '동남동', '남동', '남남동',
            '남', '남남서', '남서', '서남서', '서', '서북서', '북서', '북북서']
    idx = int((deg + 11.25) // 22.5) % 16
    return dirs[idx]


def feels_like(temp, humid, wind):
    """체감온도 (간이식). 기온·습도·풍속 기반.
    - 10°C 이하: 윈드칠(풍속 영향 큼)
    - 27°C 이상: 열지수(습도 영향 큼)
    - 그 사이: 기온 거의 그대로 (풍속 약간 보정)
    """
    if temp is None or humid is None or wind is None:
        return None
    try:
        t, h, w = float(temp), float(humid), float(wind)
    except (TypeError, ValueError):
        return None
    # 윈드칠 (기온이 낮을 때)
    if t <= 10 and w >= 1.3:
        v = w * 3.6  # m/s → km/h
        wc = 13.12 + 0.6215 * t - 11.37 * (v ** 0.16) + 0.3965 * t * (v ** 0.16)
        return round(wc, 1)
    # 열지수 (기온이 높을 때)
    if t >= 27 and h >= 40:
        # 간이 열지수
        hi = t + 0.348 * (h / 100 * 6.105 * 2.71828 ** (17.27 * t / (237.7 + t))) - 0.7 * w - 4.25
        return round(hi, 1)
    # 보통 범위: 기온 - 풍속 영향
    return round(t - max(0, (w - 2) * 0.3), 1)


VILAGE_CACHE_PATH = TMP / 'vilage_fcst.json'


def _vilage_cache_load():
    try:
        return json.loads(VILAGE_CACHE_PATH.read_text(encoding='utf-8'))
    except Exception:
        return {}


def fetch_one_region_forecast(region):
    """단기예보(3일치). 발표시각(base_time)이 같으면 응답도 같으므로 캐시한다.

    왜: 단기예보는 하루 8번(02·05·08·11·14·17·20·23시)만 새로 나온다. 5분 cron이
    매번 부르면 시군 하나당 하루 288번 부르면서 같은 답을 받는다. 지역이 둘로 늘면
    공공데이터포털 호출이 하루 9천여 건 늘어 일일 한도를 건드릴 수 있다.
    발표시각을 열쇠로 캐시하면 시군당 하루 8번이면 끝난다(≈97% 감소).
    ⚠ 캐시 열쇠에 nx·ny를 반드시 넣을 것 — 빼면 모든 시군이 첫 시군의 예보를 쓴다.
    """
    base_date, base_time = fcst_base_time()
    ck = f"{region['nx']},{region['ny']},{base_date},{base_time}"
    cache = _vilage_cache_load()

    if ck in cache:
        # 캐시엔 '가공 전 예보표'만 담는다. 완성된 결과를 담으면 '지금 이후 24시간'
        # 구간이 발표시각에 얼어붙어 시간이 지나도 옛 시간대가 계속 보인다.
        by_time = {tuple(k.split('|')): v for k, v in cache[ck].items()}
    else:
        url = 'https://apis.data.go.kr/1360000/VilageFcstInfoService_2.0/getVilageFcst'
        params = {
            'serviceKey': DATA_KEY,
            'pageNo': 1,
            'numOfRows': 1000,
            'dataType': 'JSON',
            'base_date': base_date,
            'base_time': base_time,
            'nx': region['nx'],
            'ny': region['ny'],
        }
        r = requests.get(url, params=params, timeout=15)
        r.raise_for_status()
        body = r.json()['response']['body']
        items = body['items']['item']

        # 시각별 카테고리 모음
        by_time = {}
        for it in items:
            key = (it['fcstDate'], it['fcstTime'])
            by_time.setdefault(key, {})[it['category']] = it['fcstValue']

        # 같은 발표시각 것만 남기고 저장 (지난 발표분은 버려 파일이 안 커지게)
        try:
            fresh = {k: v for k, v in cache.items()
                     if k.endswith(f'{base_date},{base_time}')}
            fresh[ck] = {'|'.join(k): v for k, v in by_time.items()}
            _atomic_write_text(VILAGE_CACHE_PATH,
                               json.dumps(fresh, ensure_ascii=False, separators=(',', ':')))
        except Exception as e:
            print(f'    단기예보 캐시 저장 실패(무시): {type(e).__name__}')

    # 시간순 정렬, 현재 시각 이후 24시간
    now = datetime.now()
    sorted_keys = sorted(by_time.keys())
    future = []
    for d, t in sorted_keys:
        dt = datetime.strptime(d + t, '%Y%m%d%H%M')
        if dt >= now.replace(minute=0, second=0, microsecond=0):
            future.append((d, t, dt))
    if not future and sorted_keys:
        d, t = sorted_keys[0]
        future = [(d, t, datetime.strptime(d + t, '%Y%m%d%H%M'))]

    # 24시간 hourly 상세 데이터 구성
    pty_map = {'1': '비', '2': '비/눈', '3': '눈', '4': '소나기',
               '5': '빗방울', '6': '진눈깨비', '7': '눈날림'}
    sky_map = {'1': '맑음', '3': '구름많음', '4': '흐림'}

    hourly = []
    for d, t, dt in future[:24]:
        cats = by_time[(d, t)]
        pty = cats.get('PTY', '0')
        sky = cats.get('SKY', '1')
        temp = float(cats.get('TMP', 0))
        humid = int(float(cats.get('REH', 0)))
        wind = float(cats.get('WSD', 0))
        rain = parse_pcp(cats.get('PCP', '0'))
        pop = int(float(cats.get('POP', 0))) if cats.get('POP') else 0
        try: vec = float(cats.get('VEC', 0))
        except: vec = 0

        # 아이콘 (밤/낮 구분)
        if pty in ('1', '4', '5'):       icon = '🌧'
        elif pty in ('2', '3', '6', '7'): icon = '🌨'
        elif sky == '4':                  icon = '☁'
        elif sky == '3':                  icon = '🌥'
        else:
            icon = '🌙' if (dt.hour < 6 or dt.hour >= 19) else '☀'

        weather_text = (pty_map.get(pty) if pty != '0' else None) or sky_map.get(sky, '맑음')
        feel = feels_like(temp, humid, wind)

        hourly.append({
            'time': d + t,
            'hour': f'{dt.hour}시',
            'icon': icon,
            'weather': weather_text,
            'temp': round(temp, 1),
            'feels_like': round(feel, 1) if feel is not None else round(temp, 1),
            'rain_mm': rain,
            'rain_pop': pop,
            'wind_ms': round(wind, 1),
            'wind_deg': vec,
            'wind_dir': deg_to_dir(vec),
            'humid': humid,
        })

    # 첫 번째 항목을 현재 값으로 사용 (광역 모드 카드용)
    result = {'name': region['name'], 'temp': 0.0, 'weather': '맑음',
              'rain': 0, 'wind': 0, 'humid': 0, 'level': 'normal',
              'vec': None, 'tmax': None, 'tmin': None, 'pop': 0,
              '_hourly': hourly}

    if hourly:
        h0 = hourly[0]
        result['temp']    = h0['temp']
        result['weather'] = h0['weather']
        result['rain']    = h0['rain_mm']
        result['wind']    = h0['wind_ms']
        result['humid']   = h0['humid']
        result['vec']     = h0['wind_deg']
        result['pop']     = h0['rain_pop']

    # 오늘 일 최고/최저
    # ⚠ 반드시 by_time으로 순회할 것 — items는 '캐시를 안 쓴 회차'에만 만들어진다.
    #   예전엔 여기서 items를 써서, 캐시가 맞는 회차(=5분 주기의 약 97%)마다
    #   UnboundLocalError로 이 함수가 통째로 죽었다. 죽으면 호출부가 '수집 실패'로 보고
    #   직전 값을 되살리므로, 시군 기온·습도가 예보 발표시각 사이(최대 3시간) 얼어붙었다.
    #   갱신 시각(updated)은 매 회차 새로 찍혀서 화면에는 정상으로 보였다 — 그래서
    #   2026-08-17 전체 점검 전까지 아무도 몰랐다. (실측: 의정부 05:10~07:11 22.8° 고정)
    #   by_time은 캐시·비캐시 양쪽 모두에 있다.
    today = now.strftime('%Y%m%d')
    for (fdate, _ftime), cats in by_time.items():
        if fdate != today: continue
        if result['tmax'] is None and 'TMX' in cats:
            try: result['tmax'] = float(cats['TMX'])
            except: pass
        if result['tmin'] is None and 'TMN' in cats:
            try: result['tmin'] = float(cats['TMN'])
            except: pass

    # (weather는 위 308-310에서 hourly[0]=현재 시각 값으로 이미 설정됨.
    #  여기서 루프 마지막 pty/sky로 덮으면 '24시간 뒤' 날씨가 되어버려 제거함.)

    # 위험도 판정: 강수량 기반 (예보값 기준 초기 산정 — 실측 수신 시 fetch_all_regions에서 재산정)
    if result['rain'] >= 20: result['level'] = 'danger'; result['tag'] = '경보'
    elif result['rain'] >= 10: result['level'] = 'warning'; result['tag'] = '호우'
    elif result['rain'] >= 3: result['level'] = 'warning'

    return result


ULTRA_FCST_PATH = TMP / 'ultra_fcst.json'


def _ultra_base():
    """초단기예보 발표시각 — 매시 30분 발표, 안정까지 ~15분. 45분 여유를 둔다."""
    b = datetime.now() - timedelta(minutes=45)
    return b.strftime('%Y%m%d'), b.strftime('%H') + '30'


def fetch_ultra_short_fcst_all():
    """초단기예보 — 관서별 '앞으로 6시간' 강수 예측. (지금 상황판엔 1~6시간 앞을 볼 수단이 없다)

    ⚠ 함정 1: 초단기'실황' RN1은 숫자(0.5)인데 초단기'예보' RN1은 글자('강수없음','1.0mm 미만')다.
              이름이 같아 실황 파서를 재사용하면 조용히 깨진다 → parse_pcp()로 변환.
    ⚠ 함정 2: 초단기예보는 1시간에 한 번(매시 30분)만 갱신된다. 5분 cron마다 10관서를 부르면
              하루 2,880회가 낭비되고 일일 한도를 넘으면 '같은 키'를 쓰는 단기예보·실황까지
              전부 막혀 대시보드가 죽는다. → 발표시각이 바뀔 때만 호출하고 .tmp에 캐시.

    반환: {관서: [{time,'rain_mm','pop','pty','sky','temp','lgt'} …최대 6개]}
    """
    base_date, base_time = _ultra_base()
    # ⚠ 캐시 키에 '스키마 버전'을 붙인다. 발표시각만으로 키를 만들면, 코드에 필드를 새로
    #   추가해도 같은 발표분 동안(최대 1시간) 옛 모양 캐시가 계속 나가 새 필드가 비어 보인다.
    #   (실제로 바람 wsd/vec를 추가한 날 그 증상이 났다.) 필드를 바꿀 때 이 숫자를 올릴 것.
    SCHEMA = 2
    key = f'{base_date}{base_time}v{SCHEMA}'

    # 같은 발표분이면 재호출하지 않는다
    try:
        if ULTRA_FCST_PATH.exists():
            cached = json.loads(ULTRA_FCST_PATH.read_text(encoding='utf-8'))
            if cached.get('key') == key and cached.get('data'):
                print(f'  · 초단기예보 캐시 재사용 ({base_time} 발표분)')
                return cached['data']
    except Exception:
        pass

    url = 'https://apis.data.go.kr/1360000/VilageFcstInfoService_2.0/getUltraSrtFcst'
    PTY_TXT = {0: '없음', 1: '비', 2: '비/눈', 3: '눈', 4: '소나기',
               5: '빗방울', 6: '진눈깨비', 7: '눈날림'}
    out = {}
    for r in REGIONS:
        try:
            resp = requests.get(url, params={
                'serviceKey': DATA_KEY, 'pageNo': 1, 'numOfRows': 300, 'dataType': 'JSON',
                'base_date': base_date, 'base_time': base_time,
                'nx': r['nx'], 'ny': r['ny'],
            }, timeout=10)
            resp.raise_for_status()
            j = resp.json()
            if str(j['response']['header']['resultCode']) != '00':
                raise RuntimeError(j['response']['header'].get('resultMsg', '?'))
            items = j['response']['body']['items']['item']
        except Exception as e:
            print(f'  · 초단기예보 {r["name"]} 실패: {type(e).__name__}')
            continue

        by = {}
        for it in items:
            # ⚠ 날짜+시각으로 키를 잡는다. fcstTime('HHMM')만 쓰면 저녁 발표분이 자정을 넘길 때
            #   '2300'→'0000'이 문자열 정렬에서 뒤집혀 6시간 예보 순서가 꼬인다(자정 전후 몇 시간).
            by.setdefault(it['fcstDate'] + it['fcstTime'], {})[it['category']] = it['fcstValue']
        rows = []
        for t in sorted(by):
            c = by[t]
            try:
                pty = int(float(c.get('PTY', 0)))
            except (TypeError, ValueError):
                pty = 0
            def _num(k):
                try:
                    return float(c[k])
                except (KeyError, TypeError, ValueError):
                    return None
            rows.append({
                'time': f'{t[8:10]}:{t[10:12]}',   # t = 'YYYYMMDDHHMM'
                'rain_mm': parse_pcp(c.get('RN1', '강수없음')),   # ⚠ 글자 → mm
                'pop': _num('POP'),
                'pty': pty,
                'pty_txt': PTY_TXT.get(pty, '?'),
                'sky': _num('SKY'),
                'temp': _num('T1H'),
                'lgt': _num('LGT'),          # 낙뢰
                'wsd': _num('WSD'),          # 풍속 — 응답에 이미 오는데 안 읽고 있었다
                'vec': _num('VEC'),          # 풍향(도)
            })
        if rows:
            out[r['name']] = rows[:6]

    if out:
        try:
            ULTRA_FCST_PATH.parent.mkdir(parents=True, exist_ok=True)
            ULTRA_FCST_PATH.write_text(json.dumps({'key': key, 'data': out}, ensure_ascii=False),
                                       encoding='utf-8')
        except Exception:
            pass
    return out


# ============================================================
# 1-B2. 물때(조석) — 파주 임진강 하구. 국립해양조사원 조석예보(고,저조)
# ============================================================
TIDE_PATH = TMP / 'tide.json'

# 강화대교 관측소코드(DT_0032). 강화 만조/간조 시각 +2시간 = 임진강 두포리(파주).
#   → 파주 현장 실무 방식. 두포리 자체 조위관측소는 없어 강화 예보를 위상보정해 쓴다.
TIDE_OBSCODE = 'DT_0032'
TIDE_SHIFT_MIN = 120          # 두포리 위상지연(분)
TIDE_STATION = '강화대교'
TIDE_TARGET = '임진강 두포리(파주)'
TIDE_SV = 2                   # 캐시 스키마 버전 — 필드 추가 시 올려 옛 캐시 무효화


def _mulddae(lun_day):
    """음력일(1~30) → 서해(강화) 물때(몇물). '7물때식'.
    검증: badatime 강화대교 8일 연속 대조 통과(음력11→2물·12→3물 … 음력16→7물).
    i=((L-1)%15)+1 ; i1~7→(i+6)물[7~13물], i8→조금, i9→무시, i10~15→(i-9)물[1~6물]."""
    try:
        L = int(lun_day)
    except (TypeError, ValueError):
        return None
    i = ((L - 1) % 15) + 1
    if 1 <= i <= 7:
        return f'{i + 6}물'
    if i == 8:
        return '조금'
    if i == 9:
        return '무시'
    return f'{i - 9}물'   # 10~15 → 1~6물(6물=사리)


def _moon_phase(lun_day):
    """음력일(1~30) → 달 위상 {emoji,name}. (달이 차고 기우는 대략적 위상)"""
    try:
        L = int(lun_day)
    except (TypeError, ValueError):
        return None
    if L <= 1 or L >= 30:
        return {'emoji': '🌑', 'name': '삭(그믐)'}
    if L <= 6:
        return {'emoji': '🌒', 'name': '초승달'}
    if L <= 8:
        return {'emoji': '🌓', 'name': '상현달'}
    if L <= 13:
        return {'emoji': '🌔', 'name': '상현망간'}
    if L <= 16:
        return {'emoji': '🌕', 'name': '보름달'}
    if L <= 21:
        return {'emoji': '🌖', 'name': '하현망간'}
    if L <= 23:
        return {'emoji': '🌗', 'name': '하현달'}
    return {'emoji': '🌘', 'name': '그믐달'}


def _load_klc():
    """음력 변환 클래스 로드 — 저장소 vendor 우선(서버 pip 불필요), 없으면 설치본.
    tools/가 sys.path에 있어(스크립트 실행/모듈 import 모두) 'vendor.…'로 잡힌다."""
    try:
        from vendor.korean_lunar_calendar import KoreanLunarCalendar
        return KoreanLunarCalendar
    except Exception:
        pass
    try:
        from korean_lunar_calendar import KoreanLunarCalendar
        return KoreanLunarCalendar
    except Exception:
        return None


def fetch_tide():
    """파주 임진강 물때 — 강화대교 조석예보 고저조를 받아 두포리(+2h)로 환산.

    ⚠ 함정 1: 이 게이트웨이(apis.data.go.kr/1192136)는 User-Agent 헤더가 없으면
              파이썬 기본 UA를 막아 403 Forbidden을 준다. 헤더 필수.
    ⚠ 함정 2: date 파라미터는 어떤 이름/형식으로도 무시되고 '오늘'만 준다.
              조석 극값은 하루 종일 불변이므로, 날짜로 캐시해 하루 1회만 실제 호출.
    ⚠ 함정 3: extrSe는 만조/간조 구분이 아니라 그날의 순번(1·2·3·4)이다.
              만조/간조는 조위값 크기(이웃 대비 극대=만조)로 판정한다.

    반환: {station,target,obscode,shift_min,date,amp_cm,spring,events:[{kind,ganghwa,dupo,cm}]} 또는 None
    """
    if not DATA_KEY:
        return None
    today = datetime.now().strftime('%Y-%m-%d')

    # 음력 라이브러리 가용 여부 — vendor(저장소내장) 우선. 있으면 물때/음력을 채운다.
    _KLC = _load_klc()
    _klc_ok = _KLC is not None

    # 날짜 캐시 — 같은 날+같은 스키마면 재호출하지 않는다(하루 1회).
    #   단, 라이브러리가 새로 설치돼 물때를 채울 수 있게 됐는데 캐시엔 없으면 재계산한다
    #   (서버 자가설치 후 당일 바로 물때가 뜨도록).
    try:
        if TIDE_PATH.exists():
            cached = json.loads(TIDE_PATH.read_text(encoding='utf-8'))
            if (cached.get('date') == today and cached.get('events') and cached.get('_sv') == TIDE_SV
                    and (cached.get('mulddae') or not _klc_ok)):
                return cached
    except Exception:
        pass

    url = 'https://apis.data.go.kr/1192136/tideFcstHghLw/GetTideFcstHghLwApiService'
    try:
        r = requests.get(url, params={
            'serviceKey': DATA_KEY, 'pageNo': 1, 'numOfRows': 100,
            'obsCode': TIDE_OBSCODE,
        }, headers={'User-Agent': 'Mozilla/5.0'}, timeout=12)
        r.raise_for_status()
        root = ET.fromstring(r.text)
    except Exception as e:
        print(f'  · 조석예보 실패: {type(e).__name__}')
        return None

    raw = []
    for it in root.iter('item'):
        dt = (it.findtext('predcDt') or '').strip()       # 'YYYY-MM-DD HH:MM'
        val = (it.findtext('predcTdlvVl') or '').strip()   # 조위 cm
        if len(dt) < 16:
            continue
        try:
            cm = float(val)
        except (TypeError, ValueError):
            cm = None
        raw.append({'dt': dt, 'cm': cm})
    if not raw:
        return None
    raw.sort(key=lambda x: x['dt'])

    # 만조/간조 판정: 이웃 대비 극대=만조, 극소=간조 (극값은 시간순 교대)
    events = []
    for i, e in enumerate(raw):
        neigh = []
        if i > 0 and raw[i - 1]['cm'] is not None:
            neigh.append(raw[i - 1]['cm'])
        if i < len(raw) - 1 and raw[i + 1]['cm'] is not None:
            neigh.append(raw[i + 1]['cm'])
        kind = 'high'
        if e['cm'] is not None and neigh:
            kind = 'high' if e['cm'] >= max(neigh) else 'low'
        gh = e['dt'][11:16]                                 # 강화 'HH:MM'
        try:
            base = datetime.strptime(e['dt'], '%Y-%m-%d %H:%M')
            dupo = (base + timedelta(minutes=TIDE_SHIFT_MIN)).strftime('%H:%M')
        except ValueError:
            dupo = gh
        events.append({'kind': kind, 'ganghwa': gh, 'dupo': dupo, 'cm': e['cm']})

    cms = [e['cm'] for e in raw if e['cm'] is not None]
    amp = round(max(cms) - min(cms)) if cms else 0          # 강화 기준 조차(cm)
    # 물때(사리/조금) 정성 판정 — 강화대교 조차 기준(대조차 700cm+, 소조차 200cm대)
    spring = '사리' if amp >= 600 else '중간' if amp >= 400 else '조금'

    result = {
        'station': TIDE_STATION, 'target': TIDE_TARGET, 'obscode': TIDE_OBSCODE,
        'shift_min': TIDE_SHIFT_MIN, 'date': today, 'amp_cm': amp,
        'spring': spring, 'events': events, '_sv': TIDE_SV,
    }

    # 음력·물때(몇물)·달모양 — vendor 음력 라이브러리로 계산(순수 오프라인·무료).
    #   물때 공식은 badatime 대조로 검증됨(_mulddae). 실패해도 나머지는 정상 표출.
    if _KLC is not None:
        try:
            _n = datetime.now()
            _cal = _KLC()
            _cal.setSolarDate(_n.year, _n.month, _n.day)
            _ld = _cal.lunarDay
            result['lunar'] = f'{_cal.lunarMonth}.{_ld}'
            result['mulddae'] = _mulddae(_ld)
            result['moon'] = _moon_phase(_ld)
        except Exception:
            pass
    try:
        TIDE_PATH.parent.mkdir(parents=True, exist_ok=True)
        TIDE_PATH.write_text(json.dumps(result, ensure_ascii=False), encoding='utf-8')
    except Exception:
        pass
    return result


# ============================================================
# 1-C. 태풍 (기상청 apihub) — 진행 중인 태풍의 진로·제원
# ============================================================
def _typ_num(v):
    """태풍 수치 — 결측은 -999로 온다. None으로 바꾼다."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if f <= -900 else f


def fetch_typhoon():
    """진행 중인 태풍과 그 진로. 태풍이 없으면 [] (에러가 아니라 정상 — 1년의 대부분).

    typ_lst(연도별 목록)에서 NOW=1(진행중)을 찾고, typ_data로 그 태풍의 진로를 받는다.
      · FT=0 → 지나온 경로(분석), FT=1 → 예상 진로(예측)
      · EFF: 1상륙 2직접영향 3간접영향 4없음  ← 한반도 영향 여부를 API가 직접 알려준다
    ⚠ 파싱 함정: 마지막 LOC('일본 도쿄 남')에 공백이 있어 split()하면 뒤가 깨진다.
      필요한 값(좌표·기압·풍속·반경)은 전부 앞 16칸이라 f[0:16]만 쓴다.
    ⚠ 예측(FT=1)은 '진행 중인 태풍'에만 붙는다. 종료된 태풍은 분석만 남는다
      → 예측 경로는 실제 태풍이 와야 실물 검증된다(파싱은 분석과 동일 포맷이라 안전).
    """
    if not KMA_APIHUB_KEY:
        return []
    base = 'https://apihub.kma.go.kr/api/typ01/url'
    yy = datetime.now().year

    def _get(url):
        r = requests.get(url, timeout=12)
        r.raise_for_status()
        r.encoding = 'euc-kr'
        if '활용신청' in r.text[:300]:
            raise RuntimeError('태풍 API 활용신청 필요')
        return r.text

    # 1) 올해 목록에서 진행 중인 태풍 찾기
    lst = _get(f'{base}/typ_lst.php?YY={yy}&disp=0&help=0&authKey={KMA_APIHUB_KEY}')
    active = []
    for line in lst.split('\n'):
        s = line.strip()
        if not s or s.startswith('#'):
            continue
        f = s.split()
        if len(f) < 7:
            continue
        try:
            seq, now, eff = f[1], f[2], f[3]
        except IndexError:
            continue
        if now != '1':                      # 1=진행중, 2=종료
            continue
        active.append({'seq': seq, 'eff': eff, 'name': f[6] if len(f) > 6 else '',
                       'name_en': f[7] if len(f) > 7 else ''})
    if not active:
        return []                            # 태풍 없음 — 정상

    EFF_TXT = {'1': '상륙', '2': '직접영향', '3': '간접영향', '4': '영향없음'}
    out = []
    for a in active:
        try:
            d = _get(f'{base}/typ_data.php?YY={yy}&typ={a["seq"]}&mode=1&disp=0&help=0'
                     f'&authKey={KMA_APIHUB_KEY}')
        except Exception as e:
            print(f'    태풍 {a["seq"]}호 진로 실패: {type(e).__name__}')
            continue
        past, fcst = [], []
        for line in d.split('\n'):
            s = line.strip()
            if not s or s.startswith('#'):
                continue
            f = s.split()
            if len(f) < 16:
                continue
            lat, lon = _typ_num(f[7]), _typ_num(f[8])
            if lat is None or lon is None:
                continue
            pt = {
                'tm': f[6],                       # 예측시각(UTC) — FT=0이면 분석시각과 같다
                'lat': lat, 'lon': lon,
                'dir': f[9] if f[9] != '-999' else '',
                'sp': _typ_num(f[10]),            # 진행속도 km/h
                'ps': _typ_num(f[11]),            # 중심기압 hPa
                'ws': _typ_num(f[12]),            # 최대풍속 m/s
                'rad15': _typ_num(f[13]),         # 강풍반경(15m/s) km
                'rad25': _typ_num(f[14]),         # 폭풍반경(25m/s) km
                'rad70': _typ_num(f[15]),         # 70% 예상확률반경(예보원) km
            }
            (fcst if f[0] == '1' else past).append(pt)
        if not past and not fcst:
            continue
        cur = past[-1] if past else fcst[0]       # 현재 = 마지막 분석값
        out.append({
            'seq': a['seq'], 'name': a['name'], 'name_en': a['name_en'],
            'eff': a['eff'], 'eff_txt': EFF_TXT.get(a['eff'], a['eff']),
            'near_kr': a['eff'] in ('1', '2', '3'),
            'now': {'lat': cur['lat'], 'lon': cur['lon'], 'ps': cur['ps'], 'ws': cur['ws'],
                    'dir': cur['dir'], 'sp': cur['sp'],
                    'rad15': cur['rad15'], 'rad25': cur['rad25'], 'tm': cur['tm']},
            'past': past[-40:], 'fcst': fcst[:12],
        })
    # 한반도 영향 태풍을 앞으로
    out.sort(key=lambda x: (0 if x['near_kr'] else 1, x['seq']))
    return out


def fetch_current_observation(region):
    """초단기실황 — 매 정시 발표, 발표 후 ~10분에 안정.
    실제 측정값(예보 아님): T1H 기온, RN1 1시간 강수, REH 습도, WSD 풍속, VEC 풍향, PTY 강수형태."""
    now = datetime.now()
    url = 'https://apis.data.go.kr/1360000/VilageFcstInfoService_2.0/getUltraSrtNcst'

    def _try(base):
        base_date = base.strftime('%Y%m%d')
        base_time = base.strftime('%H00')
        r = requests.get(url, params={
            'serviceKey': DATA_KEY,
            'pageNo': 1, 'numOfRows': 30,
            'dataType': 'JSON',
            'base_date': base_date, 'base_time': base_time,
            'nx': region['nx'], 'ny': region['ny'],
        }, timeout=10)
        r.raise_for_status()
        resp = r.json()['response']
        if str(resp.get('header', {}).get('resultCode', '')) != '00':
            return None   # NO_DATA(03) 등 — 아직 미발표
        items = (resp.get('body', {}).get('items', {}) or {}).get('item')
        if not items:
            return None
        obs = {}
        for it in items:
            cat, val = it['category'], it['obsrValue']
            if cat == 'T1H':   obs['t1h'] = float(val)
            elif cat == 'RN1':
                try:    obs['rn1'] = float(val)
                except: obs['rn1'] = 0
            elif cat == 'REH': obs['reh'] = int(float(val))
            elif cat == 'WSD': obs['wsd'] = float(val)
            elif cat == 'VEC': obs['vec'] = float(val)
            elif cat == 'PTY': obs['pty'] = val
        obs['base_time'] = f'{base_time[:2]}:{base_time[2:]}'
        return obs

    # 15분 지났으면 이번 정시(최신) 우선, 미발표면 직전 정시로 폴백 → 최신성+안정성
    candidates = []
    if now.minute >= 15:
        candidates.append(now)
    candidates.append(now - timedelta(hours=1))
    for base in candidates:
        obs = _try(base)
        if obs is not None:
            return obs
    raise RuntimeError('초단기실황 NO_DATA (이번·직전 정시 모두)')


def update_rain_history(region_name, rn1):
    """시간별 강수 기록 누적 저장 및 1/3/6/12시간 누적 반환."""
    history_path = TMP / 'rain_history.json'
    history_path.parent.mkdir(exist_ok=True)

    now = datetime.now()
    current_hour = now.strftime('%Y%m%d%H')

    history = {}
    if history_path.exists():
        try:
            with open(history_path, encoding='utf-8') as f:
                history = json.load(f)
        except Exception:
            history = {}

    if region_name not in history:
        history[region_name] = {}
    # 시간 단위로 덮어씀 — 한 시간 안에 여러 번 호출돼도 마지막 값 사용
    history[region_name][current_hour] = float(rn1 or 0)

    # 14시간 이상 된 데이터 정리
    cutoff = (now - timedelta(hours=14)).strftime('%Y%m%d%H')
    history[region_name] = {k: v for k, v in history[region_name].items() if k > cutoff}

    with open(history_path, 'w', encoding='utf-8') as f:
        json.dump(history, f, ensure_ascii=False, indent=2)

    def sum_last(n_hours):
        cutoff_h = (now - timedelta(hours=n_hours - 1)).strftime('%Y%m%d%H')
        return round(sum(v for k, v in history[region_name].items() if k >= cutoff_h), 1)

    return {'1h': sum_last(1), '3h': sum_last(3), '6h': sum_last(6), '12h': sum_last(12)}


def persist_today_minmax(region_name, tmax, tmin, hourly):
    """오늘 일 최고/최저 기온을 자정까지 유지.

    기상청 단기예보는 미래만 줘서, 저녁이 되면 오늘의 TMX(최고)·TMN(최저)이
    예보에서 빠진다(낮엔 나오다가 저녁에 사라짐). 그래서:
      1) 낮에 받은 TMX/TMN을 파일에 저장(날짜 바뀌면 리셋)
      2) 저녁에 예보값이 없으면 저장된 오늘 값을 사용
      3) 저장값도 없으면(서버 첫 가동 등) hourly(향후 24h) 기온으로 근사
    반환: (tmax, tmin)"""
    path = TMP / 'today_minmax.json'
    today = datetime.now().strftime('%Y%m%d')

    store = {}
    try:
        if path.exists():
            with open(path, encoding='utf-8') as f:
                store = json.load(f)
    except Exception:
        store = {}
    # 날짜가 바뀌면 초기화
    if store.get('date') != today:
        store = {'date': today, 'regions': {}}

    rec = store.setdefault('regions', {}).setdefault(region_name, {})
    # 새 예보값이 있으면 더 극단으로 갱신
    if tmax is not None:
        rec['tmax'] = tmax if rec.get('tmax') is None else max(rec['tmax'], tmax)
    if tmin is not None:
        rec['tmin'] = tmin if rec.get('tmin') is None else min(rec['tmin'], tmin)

    out_max, out_min = rec.get('tmax'), rec.get('tmin')
    # 저장값도 없으면 hourly로 근사 (오늘 데이터가 아예 없는 경우)
    if (out_max is None or out_min is None) and hourly:
        temps = [h.get('temp') for h in hourly if h.get('temp') is not None]
        if temps:
            if out_max is None:
                out_max = max(temps)
            if out_min is None:
                out_min = min(temps)

    try:
        path.parent.mkdir(exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(store, f, ensure_ascii=False)
    except Exception:
        pass

    return out_max, out_min


def fetch_all_regions(aws=None):
    aws = aws or {}
    regions = []
    for r in REGIONS:
        item = {'name': r['name'], 'temp': 0, 'weather': '?', 'rain': 0,
                'wind': 0, 'humid': 0, 'level': 'normal'}
        try:
            item = fetch_one_region_forecast(r)
            print(f'  ✓ {r["name"]}', end='')
        except Exception as e:
            print(f'  ✗ {r["name"]}: {e}')

        # 초단기실황 + 누적 강수
        detail = {}
        try:
            obs = fetch_current_observation(r)
            detail['observation'] = obs
            cumul = update_rain_history(r['name'], obs.get('rn1', 0))
            detail['rain_cumul'] = cumul
            print(f'  · 실황 {obs.get("t1h", "-")}° / 강수 {cumul["1h"]}mm')
        except Exception as e:
            print(f'  · 실황 실패: {e}')
            detail['observation'] = {}
            detail['rain_cumul'] = {'1h': 0, '3h': 0, '6h': 0, '12h': 0}

        # AWS 실측(기상청 공식 누적) — 자체누적(rain_cumul)보다 신뢰도가 높다.
        # 화면은 AWS가 있으면 AWS를, 없으면 rain_cumul을 쓰고 출처를 표기한다.
        detail['aws'] = aws.get(r['name'], {})

        # 풍향 한글 + 체감온도
        obs = detail.get('observation', {})

        # === 카드 표시값을 실측(초단기실황)으로 통일 — 상세 모달과 불일치 해소 ===
        # 기존엔 카드=단기예보(TMP/PCP/REH), 상세=실측(T1H/RN1/REH)이라 값이 달랐음.
        # (예: 비 안 오는데 카드에 '강수 6mm' 예보값 표시 → 오해)
        # 카드는 '현재 기상'이므로 실측값을 우선 사용. weather(하늘상태)는
        # 실측에 SKY가 없어 예보값을 유지하되, 강수형태(pty)가 있으면 보정.
        if obs.get('t1h') is not None:
            item['temp'] = round(float(obs['t1h']), 1)
        if obs.get('reh') is not None:
            item['humid'] = int(float(obs['reh']))
        if obs.get('wsd') is not None:
            item['wind'] = round(float(obs['wsd']), 1)
        if obs.get('rn1') is not None:
            item['rain'] = round(float(obs['rn1']), 1)
            # 실측 강수로 위험도·태그 재산정 (카드 숫자와 태그 일치; 예보 기반 잔재 제거)
            rn = item['rain']
            item.pop('tag', None)
            if rn >= 20:   item['level'] = 'danger';  item['tag'] = '경보'
            elif rn >= 10: item['level'] = 'warning'; item['tag'] = '호우'
            elif rn >= 3:  item['level'] = 'warning'
            else:          item['level'] = 'normal'
        # 실측 강수형태로 하늘상태 보정 (비/눈 오는데 '맑음' 표시 방지)
        _pty = obs.get('pty')
        if _pty not in (None, '', 0, '0'):
            _pty_map = {1: '비', 2: '비/눈', 3: '눈', 4: '소나기',
                        5: '빗방울', 6: '진눈깨비/빗방울', 7: '눈날림'}
            try:
                _pi = int(float(_pty))
                if _pi in _pty_map:
                    item['weather'] = _pty_map[_pi]
            except (ValueError, TypeError):
                pass

        if 'vec' in obs:
            detail['wind_dir_name'] = deg_to_dir(obs['vec'])
        elif item.get('vec') is not None:
            detail['wind_dir_name'] = deg_to_dir(item['vec'])
        else:
            detail['wind_dir_name'] = '-'
        t = obs.get('t1h', item.get('temp'))
        h = obs.get('reh', item.get('humid'))
        w = obs.get('wsd', item.get('wind'))
        detail['feels_like'] = feels_like(t, h, w)
        detail['pop'] = item.get('pop', 0)

        # 24시간 hourly를 detail로 옮김 (단기예보에서 추출한 것)
        detail['hourly'] = item.pop('_hourly', [])

        # 오늘 최고/최저 — 저녁이 되면 단기예보(TMX/TMN)에서 사라지므로
        # 낮에 받은 값을 파일에 저장해 자정까지 유지. 저장값도 없으면(서버 첫 가동 등)
        # hourly(향후 24h) 기온으로 근사 → 빈 값(-) 방지.
        tmx, tmn = persist_today_minmax(r['name'], item.get('tmax'),
                                        item.get('tmin'), detail['hourly'])
        detail['tmax'] = tmx
        detail['tmin'] = tmn
        item['tmax'] = tmx
        item['tmin'] = tmn

        item['detail'] = detail
        regions.append(item)
    return regions


# ============================================================
# 2. 기상청 단기예보 - 시간대별 12시간 (중점 관서)
# ============================================================
_HOME = next((r for r in REGIONS if r['name'] == P['home']), REGIONS[0])


def fetch_hourly_forecast(nx=None, ny=None, hours=12):
    nx = _HOME['nx'] if nx is None else nx
    ny = _HOME['ny'] if ny is None else ny
    base_date, base_time = fcst_base_time()
    url = 'https://apis.data.go.kr/1360000/VilageFcstInfoService_2.0/getVilageFcst'
    params = {
        'serviceKey': DATA_KEY,
        'pageNo': 1,
        'numOfRows': 1000,
        'dataType': 'JSON',
        'base_date': base_date,
        'base_time': base_time,
        'nx': nx, 'ny': ny,
    }
    r = requests.get(url, params=params, timeout=15)
    r.raise_for_status()
    items = r.json()['response']['body']['items']['item']

    # 시각별로 묶기
    by_time = {}
    for it in items:
        key = (it['fcstDate'], it['fcstTime'])
        by_time.setdefault(key, {})[it['category']] = it['fcstValue']

    # 현재 시각부터 hours개 정렬
    now = datetime.now()
    sorted_keys = sorted(by_time.keys())
    result = []
    for d, t in sorted_keys:
        dt = datetime.strptime(d + t, '%Y%m%d%H%M')
        if dt < now.replace(minute=0):
            continue
        cats = by_time[(d, t)]
        pty = cats.get('PTY', '0')
        sky = cats.get('SKY', '1')
        if pty in ('1', '4', '5'): icon = '🌧'
        elif pty in ('2', '3', '6', '7'): icon = '🌨'
        elif sky == '4': icon = '☁'
        elif sky == '3': icon = '🌥'
        else:
            icon = '🌙' if (dt.hour < 6 or dt.hour >= 19) else '☀'
        result.append({
            'time': f'{dt.hour:02d}시',
            'icon': icon,
            'temp': int(float(cats.get('TMP', 0))),
            'rain': int(float(cats.get('POP', 0))),
        })
        if len(result) >= hours:
            break
    return result


# ============================================================
# 3. 기상특보 (경기북부 발효 현황)
# ============================================================

WRN_TYPES = ['호우경보', '호우주의보', '강풍경보', '강풍주의보', '대설경보', '대설주의보',
             '한파경보', '한파주의보', '폭염경보', '폭염주의보', '풍랑경보', '풍랑주의보',
             '건조경보', '건조주의보', '황사경보', '태풍경보', '태풍주의보']

NORTH_GG_KEYWORDS = P['keywords']


def _kw_in_text(text, kw):
    """text에 지역 kw가 포함되는지 — '양주'가 '남양주'에 부분포함되는 충돌 방지.
    kw를 부분으로 갖는 더 긴 지역명(남양주⊃양주)을 먼저 제거한 뒤 검사."""
    t = text
    for other in NORTH_GG_KEYWORDS:
        if other != kw and kw in other:
            t = t.replace(other, '')
    return kw in t

# 기상청 API허브 wrn_reg.php 기반 REG_ID → 시군명 정적 매핑
# 경기북부 10개 시군 + 경기도 전체 광역 코드
NORTH_GG_REG_MAP = P['reg_map']


def fetch_warning_bulletins():
    """기상청 통보문·기상정보 목록 + 본문 일괄 수집.
    - getWthrWrnList:  특보 통보문 발표·해제 이력 (최근 7일)
    - getWthrWrnMsg:   특보 통보문 전문 (t1~t7)
    - getWthrInfoList: 기상정보문 목록 (매일 발표되는 기상 해설)"""
    base = 'https://apis.data.go.kr/1360000/WthrWrnInfoService'
    now = datetime.now()
    from_dt = (now - timedelta(days=3)).strftime('%Y%m%d')
    to_dt = now.strftime('%Y%m%d')

    bulletins = {'warnings_full': [], 'info_list': []}

    # 1) 통보문 본문 (전문)
    try:
        r = requests.get(f'{base}/getWthrWrnMsg', params={
            'serviceKey': DATA_KEY, 'pageNo': 1, 'numOfRows': 15,
            'dataType': 'JSON', 'stnId': 109,
            'fromTmFc': from_dt, 'toTmFc': to_dt,
        }, timeout=15)
        r.raise_for_status()
        items = r.json()['response']['body'].get('items', {})
        if items:
            items = items.get('item', [])
            if isinstance(items, dict): items = [items]
            for it in items:
                tmFc = str(it.get('tmFc', ''))
                bulletins['warnings_full'].append({
                    'title': it.get('t1', '') or '특보 통보문',
                    'current': it.get('t2', ''),   # 현재 상황
                    'time': it.get('t3', ''),       # 시각
                    'extra': it.get('t4', ''),
                    'summary': it.get('t6', '') or '',  # 종합 의견
                    'other': it.get('other', ''),
                    'tmFc': tmFc,
                    'tmFc_display': f'{tmFc[:4]}-{tmFc[4:6]}-{tmFc[6:8]} {tmFc[8:10]}:{tmFc[10:12]}' if len(tmFc) >= 12 else tmFc,
                    'seq': it.get('tmSeq', ''),
                })
    except Exception as e:
        print(f'    통보문: {e}')

    # 2) 기상정보 목록 (매일 발표되는 기상 해설)
    try:
        r = requests.get(f'{base}/getWthrInfoList', params={
            'serviceKey': DATA_KEY, 'pageNo': 1, 'numOfRows': 10,
            'dataType': 'JSON', 'stnId': 109,
            'fromTmFc': from_dt, 'toTmFc': to_dt,
        }, timeout=15)
        r.raise_for_status()
        items = r.json()['response']['body'].get('items', {})
        if items:
            items = items.get('item', [])
            if isinstance(items, dict): items = [items]
            for it in items:
                tmFc = str(it.get('tmFc', ''))
                bulletins['info_list'].append({
                    'title': it.get('title', ''),
                    'tmFc': tmFc,
                    'tmFc_display': f'{tmFc[:4]}-{tmFc[4:6]}-{tmFc[6:8]} {tmFc[8:10]}:{tmFc[10:12]}' if len(tmFc) >= 12 else tmFc,
                    'seq': it.get('tmSeq', ''),
                })
    except Exception as e:
        print(f'    기상정보: {e}')

    # 3) 기상정보 본문 (전국 해설 — 소나기·안개·폭염 등 현황/전망) — getWthrInfo
    #    레이더 카드 옆에 표시할 최신 기상정보 1건. 108(전국) 우선, 없으면 109(수도권).
    try:
        for stn in ('108', '109'):
            r = requests.get(f'{base}/getWthrInfo', params={
                'serviceKey': DATA_KEY, 'pageNo': 1, 'numOfRows': 5,
                'dataType': 'JSON', 'stnId': stn,
                'fromTmFc': from_dt, 'toTmFc': to_dt,
            }, timeout=15)
            r.raise_for_status()
            items = r.json()['response']['body'].get('items', {})
            its = items.get('item', []) if items else []
            if isinstance(its, dict):
                its = [its]
            if its:
                # 최신(tmFc 최대) 1건 선택
                latest = max(its, key=lambda x: str(x.get('tmFc', '')))
                tmFc = str(latest.get('tmFc', ''))
                content = (latest.get('t1') or '').strip()
                if content:
                    bulletins['info_detail'] = {
                        'content': content,
                        'tmFc': tmFc,
                        'tmFc_display': f'{tmFc[:4]}-{tmFc[4:6]}-{tmFc[6:8]} {tmFc[8:10]}:{tmFc[10:12]}' if len(tmFc) >= 12 else tmFc,
                        'stnId': stn,
                        'region': '전국' if stn == '108' else '수도권',
                    }
                    break  # 찾으면 종료 (108 우선)
    except Exception as e:
        print(f'    기상정보 본문: {type(e).__name__}')

    # 최신순 정렬
    bulletins['warnings_full'].sort(key=lambda x: x['tmFc'], reverse=True)
    bulletins['info_list'].sort(key=lambda x: x['tmFc'], reverse=True)
    return bulletins


def fetch_mid_forecast():
    """기상청 중기전망(날씨해설) — 8~14일 중기 육상 전망 전문(wfSv).
    MidFcstInfoService/getMidFcst. 발표시각 06시/18시.
    날씨누리 '날씨해설'의 중기전망 내용과 동일.
    반환: {'content', 'tmFc', 'tmFc_display'} 또는 None."""
    now = datetime.now()
    hh = now.hour
    # 가장 최근 발표시각 (06시/18시). 발표 직후 30분은 미생산 가능 → 한 단계 이전도 폴백.
    candidates = []
    if hh >= 18:
        candidates = [now.strftime('%Y%m%d') + '1800', now.strftime('%Y%m%d') + '0600']
    elif hh >= 6:
        candidates = [now.strftime('%Y%m%d') + '0600', (now - timedelta(days=1)).strftime('%Y%m%d') + '1800']
    else:
        candidates = [(now - timedelta(days=1)).strftime('%Y%m%d') + '1800', (now - timedelta(days=1)).strftime('%Y%m%d') + '0600']

    for tmfc in candidates:
        try:
            r = requests.get(
                'https://apis.data.go.kr/1360000/MidFcstInfoService/getMidFcst',
                params={'serviceKey': DATA_KEY, 'pageNo': 1, 'numOfRows': 1,
                        'dataType': 'JSON', 'stnId': '108', 'tmFc': tmfc},
                timeout=15)
            if r.status_code != 200:
                continue
            items = r.json()['response']['body'].get('items', {})
            its = items.get('item', []) if items else []
            if isinstance(its, dict):
                its = [its]
            if its and its[0].get('wfSv'):
                return {
                    'content': its[0]['wfSv'].strip(),
                    'tmFc': tmfc,
                    'tmFc_display': f'{tmfc[:4]}-{tmfc[4:6]}-{tmfc[6:8]} {tmfc[8:10]}:{tmfc[10:12]}',
                }
        except Exception as e:
            print(f'    중기전망({tmfc}): {type(e).__name__}')
    return None


class _SkipSatellite(Exception):
    """위성영상 갱신 건너뜀 — 아직 30분이 안 지났다는 신호(오류 아님)."""


def download_kma_images():
    """기상청 API 허브에서 특보 발효 이미지·초단기 강수예측 이미지를 받아 images/ 폴더에 저장.

    - nph-wrn7: 전국 특보 발효 현황 컬러맵 (tm 필요)
    - nph-qpf_ana_img: 초단기 강수예측 분석 이미지

    Returns: {wrn: {ok, ts, path}, qpf: {ok, ts, path}}
    키가 URL에 포함되므로 사용자 브라우저에 노출되지 않도록 — 사장님 PC만 호출,
    이미지 파일만 git push되어 사이트에 노출.
    """
    import os
    if not KMA_APIHUB_KEY:
        return {'wrn': {'ok': False}, 'qpf': {'ok': False}}

    # 프로젝트 루트의 images/ 폴더
    proj_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    img_dir = os.path.join(proj_root, 'images')
    os.makedirs(img_dir, exist_ok=True)

    now = datetime.now()
    tm = now.strftime('%Y%m%d%H%M')
    ts = now.strftime('%Y-%m-%d %H:%M')

    result = {}

    # 1) nph-wrn7 (전국 특보 발효 현황)
    try:
        url = f'https://apihub.kma.go.kr/api/typ03/cgi/wrn/nph-wrn7?tm={tm}&authKey={KMA_APIHUB_KEY}'
        r = requests.get(url, timeout=15)
        if r.status_code == 200 and r.headers.get('Content-Type', '').startswith('image/'):
            path = os.path.join(img_dir, 'kma_warn.png')
            with open(path, 'wb') as f:
                f.write(r.content)
            result['wrn'] = {'ok': True, 'ts': ts, 'bytes': len(r.content)}
        else:
            result['wrn'] = {'ok': False, 'err': f'HTTP {r.status_code}'}
    except Exception as e:
        result['wrn'] = {'ok': False, 'err': _redact(e)}

    # 2) nph-qpf_ana_img (초단기 강수예측 분석)
    # KMA가 데이터 미생산 시점에는 PNG로 "err = -11" 텍스트만 그려서 응답함
    # → IHDR 청크의 bit_depth + color_type으로 정상 이미지 검증
    def _is_real_image_png(content):
        """PNG 헤더(IHDR) 분석으로 KMA 에러 이미지를 걸러낸다.

        실측(2026-07-15, 9개 시각 조사):
          · 에러 이미지(err=-11) : 835x820 **1-bit** colormap, 877~883 bytes
          · 정상 강수예측        : 835x820 **8-bit** indexed, 20,324~24,591 bytes
        → bit_depth 하나로 완전히 갈린다(1 vs 8). 크기는 보조 하한일 뿐이다.

        ⚠ 과거 버그: 크기 하한이 30KB였다. 이 값은 '비가 많이 오던 때'(색이 많아
          PNG가 50KB+로 커짐)를 보고 잡은 것이라, 비가 적어 이미지가 20~25KB로
          작아지면 **정상 이미지를 전부 에러로 오판**해 폴백 8개가 모두 실패하고
          예측영상이 몇 시간씩 옛 그림에 멈춰 있었다(실측: 6시간 13분 정지).
          '비가 적을 때 갱신이 죽는' 구조라 호우 초입에 특히 위험했다.
        """
        if not content.startswith(b'\x89PNG'):
            return False
        # IHDR: bytes 16=width, 20=height, 24=bit_depth, 25=color_type
        if len(content) < 26:
            return False
        bit_depth = content[24]
        # 정상 KMA 이미지는 8-bit indexed 또는 24-bit RGB / 에러 이미지는 1-bit 단색
        if bit_depth < 4:
            return False
        # 잘린 응답 방어용 하한만 둔다. 에러 883B vs 정상 20KB+ 사이라 여유가 크다.
        if len(content) < 5000:
            return False
        return True

    try:
        path = os.path.join(img_dir, 'kma_qpf.png')
        ok = False
        # 강수예측은 tm 파라미터 없으면 최신 자동. 데이터 미생산 시 폴백을 위해
        # 명시적 tm으로 1시간씩 과거로 폴백 (KMA는 매 10분 생산이지만 처리 지연)
        for back_min in (0, 10, 20, 30, 60, 90, 120, 180):
            if back_min == 0:
                url = f'https://apihub.kma.go.kr/api/typ03/cgi/dfs/nph-qpf_ana_img?authKey={KMA_APIHUB_KEY}'
            else:
                qpf_dt = now - timedelta(minutes=back_min)
                qpf_dt = qpf_dt.replace(minute=(qpf_dt.minute // 10) * 10, second=0, microsecond=0)
                qpf_tm = qpf_dt.strftime('%Y%m%d%H%M')
                url = f'https://apihub.kma.go.kr/api/typ03/cgi/dfs/nph-qpf_ana_img?tm={qpf_tm}&authKey={KMA_APIHUB_KEY}'
            try:
                r = requests.get(url, timeout=15)
            except Exception:
                continue
            if r.status_code == 200 and _is_real_image_png(r.content):
                with open(path, 'wb') as f:
                    f.write(r.content)
                result['qpf'] = {'ok': True, 'ts': ts, 'bytes': len(r.content),
                                 'back_min': back_min}
                ok = True
                break
        if not ok:
            # 모든 시점 fail — 기존 정상 PNG 파일이 있으면 보존, 에러 이미지면 삭제 X
            # (사장님 PC 또는 다음 회차에서 정상 받을 때까지)
            result['qpf'] = {'ok': False, 'err': 'KMA 데이터 미생산 (err -11)'}
    except Exception as e:
        result['qpf'] = {'ok': False, 'err': _redact(e)}

    # 3) 레이더 합성영상 (rdr_cmp_file.php) — 5분 주기. 발표 지연 감안해 15분 전 + 5분배수로 정렬
    try:
        radar_dt = now - timedelta(minutes=15)
        # 분을 5의 배수로 내림
        radar_dt = radar_dt.replace(minute=(radar_dt.minute // 5) * 5, second=0, microsecond=0)
        radar_tm = radar_dt.strftime('%Y%m%d%H%M')
        url = f'https://apihub.kma.go.kr/api/typ04/url/rdr_cmp_file.php?tm={radar_tm}&data=img&cmp=cmb&authKey={KMA_APIHUB_KEY}'
        r = requests.get(url, timeout=20)
        # 응답이 PNG가 아니면 (예: "# file not exist") 더 이전 시각으로 폴백 시도
        if r.status_code == 200 and not r.content.startswith(b'\x89PNG'):
            for back in (5, 10, 15, 30):
                radar_dt_alt = radar_dt - timedelta(minutes=back)
                radar_tm_alt = radar_dt_alt.strftime('%Y%m%d%H%M')
                url_alt = f'https://apihub.kma.go.kr/api/typ04/url/rdr_cmp_file.php?tm={radar_tm_alt}&data=img&cmp=cmb&authKey={KMA_APIHUB_KEY}'
                r = requests.get(url_alt, timeout=20)
                if r.status_code == 200 and r.content.startswith(b'\x89PNG'):
                    radar_tm = radar_tm_alt
                    break
        if r.status_code == 200 and r.content.startswith(b'\x89PNG'):
            path = os.path.join(img_dir, 'kma_radar.png')
            with open(path, 'wb') as f:
                f.write(r.content)
            result['radar'] = {'ok': True, 'ts': ts, 'tm': radar_tm, 'bytes': len(r.content)}
        else:
            result['radar'] = {'ok': False, 'err': f'HTTP {r.status_code} (no PNG)'}
    except Exception as e:
        result['radar'] = {'ok': False, 'err': _redact(e)}

    # 4) 천리안 GK2A 위성 IR105 + 한반도 (10분 주기, 자료 publish 약 6시간 지연)
    # 06시 발표 자료가 12시쯤 공개되는 식. 안전하게 6시간 전부터 10분 배수로 시도.
    #
    # ⚠ 이 파일만 900KB로 다른 이미지(8~26KB)보다 40배 무겁다. 5분마다 새로 받아
    #   커밋하면 하루 260MB가 깃에 쌓이고(전체 증가량의 절반), 그만큼 히스토리 압축이
    #   자주 돌아 다른 클론의 히스토리를 깨뜨린다.
    #   어차피 6시간 지연 공개 자료라 5분 단위 신선도가 의미 없으므로 30분마다만 갱신한다.
    #   (건너뛰면 result에 'satellite' 키를 안 넣는다 → main()이 이전 메타를 그대로 보존)
    try:
        sat_path = os.path.join(img_dir, 'kma_satellite.png')
        _sat_fresh = False
        try:
            if os.path.exists(sat_path):
                _age_min = (time.time() - os.path.getmtime(sat_path)) / 60
                _sat_fresh = _age_min < 30
        except OSError:
            _sat_fresh = False
        if _sat_fresh:
            raise _SkipSatellite()
        ok = False
        # 6시간 전부터 24시간 전까지 1시간 간격으로 폴백
        for back_min in (360, 420, 480, 540, 600, 720, 1080, 1440):
            sat_dt = now - timedelta(minutes=back_min)
            sat_dt = sat_dt.replace(minute=(sat_dt.minute // 10) * 10, second=0, microsecond=0)
            sat_date = sat_dt.strftime('%Y%m%d%H%M')
            url = f'https://apihub.kma.go.kr/api/typ05/api/GK2A/LE1B/IR105/KO/image?date={sat_date}&authKey={KMA_APIHUB_KEY}'
            r = requests.get(url, timeout=20)
            if r.status_code == 403:
                result['satellite'] = {'ok': False, 'err': '활용신청 대기'}
                ok = True
                break
            if r.status_code == 200 and _is_real_image_png(r.content):
                with open(sat_path, 'wb') as f:
                    f.write(r.content)
                result['satellite'] = {'ok': True, 'ts': ts, 'date': sat_date, 'bytes': len(r.content)}
                ok = True
                break
        if not ok:
            result['satellite'] = {'ok': False, 'err': '최근 24h 정상 이미지 없음'}
    except _SkipSatellite:
        pass          # 30분 안 지남 — 이전 이미지·메타 그대로 사용(깃 커밋량 절감)
    except Exception as e:
        result['satellite'] = {'ok': False, 'err': _redact(e)}

    return result


def fetch_apihub_warnings():
    """기상청 API 허브 wrn_now_data_new.php — 현재 발효 중인 특보·예비특보 종합.

    공공데이터포털 getPwnStatus가 t6/t7 텍스트로만 주는 것을 구조화된 행 데이터로 받음.
    응답: EUC-KR 텍스트, 헤더 #로 시작.
    필드: REG_UP, REG_UP_KO, REG_ID, REG_KO, TM_FC, TM_EF, WRN, LVL, CMD, ED_TM
      - WRN/LVL/CMD: 한글 그대로 ('호우','예비','발표' 등)
      - LVL='예비' → 예비특보, '주의'→주의보, '경보'→경보
      - 이미 '현재 살아있는' 발표만 들어옴 (해제·만료 자동 제외됨)

    이 endpoint는 wrn_met_data.php(이력)보다 정확. 사장님이 본 호우 예비특보가 직접 들어옴.
    """
    if not KMA_APIHUB_KEY:
        return []

    url = 'https://apihub.kma.go.kr/api/typ01/url/wrn_now_data_new.php'
    try:
        r = requests.get(url, params={'authKey': KMA_APIHUB_KEY}, timeout=15)
        r.raise_for_status()
        # 응답은 EUC-KR 인코딩
        text = r.content.decode('euc-kr', errors='replace')
    except Exception as e:
        print(f'    [apihub] 특보현황: {e}')
        return None   # 수집 실패 — 정상 0건([])과 구분(main에서 이전값 보존)

    north = SIGUN_SET   # 이 상황판 관할 시군 (프로파일)

    items = []
    for line in text.split('\n'):
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        # 줄 끝 '=' 제거 후 쉼표 분리
        line = line.rstrip(' =').rstrip(',').rstrip()
        parts = [p.strip() for p in line.split(',')]
        if len(parts) < 10:
            continue
        reg_up, reg_up_ko, reg_id, reg_ko, tm_fc, tm_ef, wrn, lvl, cmd, ed_tm = parts[:10]

        # 해제 또는 변경해제는 제외 (현재 살아있는 것만)
        if cmd in ('해제', '대치해제', '변경해제'):
            continue

        # 지역 매칭 — '이름에 글자가 들어있나'가 아니라 특보구역 '코드'로 판정한다.
        # ⚠ 예전엔 f'{reg_up_ko} {reg_ko}'에 관할 시군명이 들어있는지만 봤다. 그래서
        #   관할에 '광주'(경기 광주시)가 있는 경기남부에서, 광주'광역시'의 특보구역인
        #   '광주동부·광주서부'(L1130xxx)가 통째로 우리 관할로 잡혔다. 광주광역시에
        #   호우경보가 나면 경기남부 상황실에 '호우경보 발효'가 뜬다는 뜻이다.
        #   (2026-08-17 전체 점검에서 발견 — 2026-08-15 가짜 재난문자와 같은 부류)
        #   NORTH_GG_REG_MAP은 프로파일이 들고 있는 '관할 특보구역 코드' 정본이라
        #   이름 충돌이 원천적으로 없다. 경기 육상 특보구역은 전부 L101xxxx 계열이다.
        _rid = str(reg_id or '')
        is_north_gg = _rid in NORTH_GG_REG_MAP
        # 경기 전체(관할 밖 경기 시군 포함) — 화면의 '경기도 특보' 집계용
        is_gyeonggi = is_north_gg or _rid.startswith('L101')

        # 시간 포맷
        def fmt(s):
            s = str(s or '')
            if len(s) >= 12:
                return f'{s[4:6]}/{s[6:8]} {s[8:10]}:{s[10:12]}'
            return s

        items.append({
            'reg_up': reg_up,
            'reg_up_ko': reg_up_ko,
            'reg_id': reg_id,
            'reg_ko': reg_ko,
            'region_name': reg_ko,            # 표시용 (지역명)
            'broader_region': reg_up_ko,      # 상위 광역
            'tm_fc': tm_fc, 'tm_ef': tm_ef,
            'tm_fc_disp': fmt(tm_fc),
            'tm_ef_disp': fmt(tm_ef),
            'wrn_name': wrn,                  # 한글 그대로 ('호우','강풍','풍랑'...)
            'lvl_name': lvl,                  # '예비'/'주의'/'경보'
            'cmd_name': cmd,                  # '발표'/'대치'/'연장'/'변경'
            'ed_tm': ed_tm,                   # 해제 예고 시각 텍스트
            'is_north_gg': is_north_gg,
            'is_gyeonggi': is_gyeonggi,
            'is_prelim': lvl == '예비',
        })

    # 정렬: 북부 > 경기 > 그 외, 예비/주의/경보 순서는 LVL 한글이라 별도 정렬 안 함
    def sort_key(it):
        return (
            0 if it['is_north_gg'] else (1 if it['is_gyeonggi'] else 2),
            0 if it['lvl_name'] == '경보' else (1 if it['lvl_name'] == '주의' else 2),
        )
    items.sort(key=sort_key)
    return items


def parse_prelim_warnings(t7_text, tmFc=''):
    """t7 필드(예비특보)의 텍스트를 구조화된 객체로 파싱.

    t7 예시:
      "(1) 강풍 예비특보\r\n
       o 05월 20일 오후(12시~18시) : 서해5도\r\n
       o 05월 20일 밤(18시~24시) : 제주도(제주도산지, ...)\r\n
       (2) 풍랑 예비특보\r\n
       o 05월 20일 오후(12시~18시) : 서해중부안쪽먼바다, ..."

    리턴: [{type, items:[{time, area, north_match:bool}]}]
    """
    import re as _re
    if not t7_text or t7_text.strip() in ('o 없음', '없음', ''):
        return []

    # 줄 단위 분리 (CRLF·LF 모두)
    lines = [ln.strip() for ln in _re.split(r'[\r\n]+', t7_text) if ln.strip()]

    groups = []
    cur = None
    for ln in lines:
        # 그룹 헤더: "(1) 강풍 예비특보"
        m = _re.match(r'\(\d+\)\s*(.+?예비특보)', ln)
        if m:
            cur = {'type': m.group(1).strip(), 'items': []}
            groups.append(cur)
            continue
        # 항목: "o 05월 20일 오후(12시~18시) : 서해5도"
        m = _re.match(r'^[o○\-•]\s*(.+?)\s*:\s*(.+)$', ln)
        if m and cur is not None:
            time_str = m.group(1).strip()
            area = m.group(2).strip()
            north_match = any(k in area for k in NORTH_GG_KEYWORDS)
            cur['items'].append({'time': time_str, 'area': area, 'north_match': north_match})

    # 발표 시각 형식 변환
    tmFc_str = ''
    if len(tmFc) >= 12:
        tmFc_str = f'{tmFc[4:6]}/{tmFc[6:8]} {tmFc[8:10]}:{tmFc[10:12]}'

    # 각 그룹에 발표 시각 부여 + 빈 그룹 제거
    result = []
    for g in groups:
        if not g['items']:
            continue
        north_count = sum(1 for it in g['items'] if it['north_match'])
        g['tmFc'] = tmFc_str
        g['north_count'] = north_count   # 경기북부 매칭 항목 수
        g['total_count'] = len(g['items'])
        result.append(g)
    return result


def fetch_warnings():
    """현재 발효 중인 기상특보(t6) + 예비특보(t7) — 경기북부 시군 매칭."""
    url = 'https://apis.data.go.kr/1360000/WthrWrnInfoService/getPwnStatus'
    params = {
        'serviceKey': DATA_KEY,
        'pageNo': 1,
        'numOfRows': 50,
        'dataType': 'JSON',
        'stnId': 109,  # 경기도 (북부)
    }
    r = requests.get(url, params=params, timeout=15)
    r.raise_for_status()
    resp = r.json()['response']
    code = str(resp.get('header', {}).get('resultCode', ''))
    # data.go.kr은 인증오류·쿼터초과·일시장애에도 HTTP 200 + 비정상 resultCode를 준다.
    # '00'(정상)이 아니면 예외로 올려 main에서 이전 특보 보존(해제→재발효 오알림 방지).
    if code != '00':
        raise RuntimeError(f"기상특보 API resultCode={code} "
                           f"{resp.get('header', {}).get('resultMsg', '')}")
    body = resp['body']
    items_obj = body.get('items', {})
    if not items_obj:
        return {'active': [], 'prelim': []}
    items = items_obj.get('item', []) if isinstance(items_obj, dict) else items_obj
    if isinstance(items, dict):
        items = [items]

    active = []
    prelim_all = []
    seen = set()
    for it in items:
        tmFc = str(it.get('tmFc', ''))
        time_str = f'{tmFc[8:10]}:{tmFc[10:12]}' if len(tmFc) >= 12 else ''

        # t6 = 발효 중 특보 (예: "호우주의보 : 동두천시, 양주시, ...")
        # 여러 줄 가능, 각 줄이 하나의 특보
        t6 = it.get('t6', '') or ''
        for line in t6.split('\n'):
            line = line.strip().lstrip('o○').strip()
            if ':' not in line:
                continue
            head, body_text = line.split(':', 1)
            head, body_text = head.strip(), body_text.strip()
            wrn_type = next((w for w in WRN_TYPES if w in head), None)
            if not wrn_type:
                continue
            matched = [k for k in NORTH_GG_KEYWORDS if _kw_in_text(body_text, k)]
            if not matched:
                continue
            area_text = ', '.join(matched)
            key = (wrn_type, area_text)
            if key in seen:
                continue
            seen.add(key)
            level = 'severe' if '경보' in wrn_type else 'warning'
            active.append({'type': wrn_type, 'area': area_text, 'time': time_str, 'level': level})

        # t7 = 예비특보 (별도 구조라 별도 파서 사용)
        t7 = it.get('t7', '') or ''
        prelim_all.extend(parse_prelim_warnings(t7, tmFc))

    return {'active': active[:8], 'prelim': prelim_all}


# ============================================================
# 4. 미세먼지 (에어코리아 - 시도별 실시간 측정정보)
# ============================================================

def pm_grade(pm10, pm25):
    # 측정 누락(None)은 등급에서 제외. 둘 다 없으면 '정보없음'.
    if pm10 is None and pm25 is None:
        return 'none', '정보없음'
    def g10(v):
        if v is None: return -1
        return 0 if v <= 30 else 1 if v <= 80 else 2 if v <= 150 else 3
    def g25(v):
        if v is None: return -1
        return 0 if v <= 15 else 1 if v <= 35 else 2 if v <= 75 else 3
    lvl = max(g10(pm10), g25(pm25), 0)   # 측정된 항목 중 가장 나쁜 등급
    return [('good', '좋음'), ('normal', '보통'), ('bad', '나쁨'), ('vbad', '매우나쁨')][lvl]


def fetch_pm():
    url = 'https://apis.data.go.kr/B552584/ArpltnInforInqireSvc/getCtprvnRltmMesureDnsty'
    params = {
        'serviceKey': DATA_KEY,
        'returnType': 'json',
        'numOfRows': 200,
        'pageNo': 1,
        'sidoName': '경기',
        'ver': '1.3',
    }
    r = requests.get(url, params=params, timeout=15)
    r.raise_for_status()
    body = r.json()['response']['body']
    items = body.get('items', [])

    by_station = {it['stationName']: it for it in items if it.get('stationName')}

    result = []
    for region_name, station in PM_STATIONS.items():
        it = by_station.get(station)
        if not it:
            # 측정소명이 정확히 일치하지 않으면 부분 일치 시도
            for sname, sit in by_station.items():
                if region_name in sname or sname in (PM_STATIONS.get(region_name, '')):
                    it = sit; break
        if not it:
            continue
        try:
            def _pmv(key):
                v = it.get(key, '')
                try:
                    return int(float(v)) if v not in ('', '-', None) else None
                except (ValueError, TypeError):
                    return None
            pm10 = _pmv('pm10Value')
            pm25 = _pmv('pm25Value')
            grade, grade_text = pm_grade(pm10, pm25)
            # 오존·통합대기지수(CAI) — 응답에 이미 포함, 파싱만 추가
            def _f(key):
                v = it.get(key, '')
                try:
                    return float(v) if v not in ('', '-', None) else None
                except (ValueError, TypeError):
                    return None
            o3 = _f('o3Value')             # 오존 농도 (ppm)
            khai = _f('khaiValue')         # 통합대기환경지수 (0~500)
            khai_grade = it.get('khaiGrade', '') or ''   # 1좋음 2보통 3나쁨 4매우나쁨
            cai_text = {'1': '좋음', '2': '보통', '3': '나쁨', '4': '매우나쁨'}.get(str(khai_grade), '')
            result.append({
                'region': region_name, 'pm10': pm10, 'pm25': pm25,
                'grade': grade, 'gradeText': grade_text,
                'o3': o3, 'khai': khai, 'cai_grade': khai_grade, 'cai_text': cai_text,
            })
        except Exception:
            continue
    return result


# ============================================================
# 5. 산불 위험도 (국립산림과학원)
# ============================================================

def fetch_fire_incidents():
    """산림청 산불발생통계정보 — 최근 1년치 산불 발생 통계.
    endpoint: https://apis.data.go.kr/1400000/forestStusService/getfirestatsservice
    응답: XML. 필드 — damagearea, firecause, locsi(시도), locgungu(시군구),
                       startyear/startmonth/startday/starttime."""
    import re as _re
    url = 'https://apis.data.go.kr/1400000/forestStusService/getfirestatsservice'
    now = datetime.now()
    # 최근 365일치 수집
    sdt = (now - timedelta(days=365)).strftime('%Y%m%d')
    edt = now.strftime('%Y%m%d')

    try:
        r = requests.get(url, params={
            'ServiceKey': DATA_KEY,  # 활용가이드 표기대로 대문자 S
            'searchStDt': sdt,
            'searchEdDt': edt,
            'numOfRows': 2000,  # 1년치 충분히
            'pageNo': 1,
        }, timeout=60)
        if r.status_code != 200:
            print(f'    산불발생: HTTP {r.status_code}')
            return {'incidents': [], 'summary': None}

        # XML 파싱 (간단한 정규식)
        items = []
        for m in _re.finditer(r'<item>(.*?)</item>', r.text, _re.DOTALL):
            block = m.group(1)
            rec = {}
            for tag in _re.findall(r'<([a-zA-Z]+)>([^<]*)</\1>', block):
                rec[tag[0]] = tag[1]
            items.append(rec)

        if not items:
            return {'incidents': [], 'summary': {
                'total': 0, 'north': 0, 'gyeonggi': 0,
                'this_year_total': 0, 'this_year_north': 0,
                'latest_north': [], 'latest_all': [],
            }}

        # 정규화: 시작일·발생일 텍스트, 지역 정리
        north_sigun = SIGUN_SET   # 이 상황판 관할 시군 (프로파일)
        cur_year = now.strftime('%Y')

        def norm(it):
            sigun = it.get('locgungu', '')
            sido = it.get('locsi', '')
            occr_dt = f"{it.get('startyear','')}-{it.get('startmonth','').zfill(2)}-{it.get('startday','').zfill(2)} {it.get('starttime','')}"
            end_dt = f"{it.get('endyear','')}-{it.get('endmonth','').zfill(2)}-{it.get('endday','').zfill(2)} {it.get('endtime','')}"
            try:
                damage = float(it.get('damagearea', 0) or 0)
            except ValueError:
                damage = 0
            return {
                'sido': sido,
                'sigungu': sigun,
                'address': f"{sido} {sigun} {it.get('locmenu','')} {it.get('locdong','')} {it.get('locbunji','')}".strip(),
                'cause': it.get('firecause', ''),
                'occur_time': occr_dt.strip(' :-'),
                'end_time': end_dt.strip(' :-'),
                'damage_area': damage,
                'year': it.get('startyear', ''),
                'is_north': sigun in north_sigun,
                'is_gyeonggi': '경기' in sido,
                'is_this_year': it.get('startyear', '') == cur_year,
            }

        normalized = [norm(it) for it in items]
        # 최신순 정렬 (occur_time desc)
        normalized.sort(key=lambda x: x['occur_time'], reverse=True)

        north_all = [x for x in normalized if x['is_north']]
        gg_all    = [x for x in normalized if x['is_gyeonggi']]
        this_yr_total = sum(1 for x in normalized if x['is_this_year'])
        this_yr_north = sum(1 for x in normalized if x['is_this_year'] and x['is_north'])

        summary = {
            'total': len(normalized),            # 최근 1년 전국
            'north': len(north_all),             # 최근 1년 경기북부
            'gyeonggi': len(gg_all),             # 최근 1년 경기도 전체
            'this_year_total': this_yr_total,    # 올해 전국
            'this_year_north': this_yr_north,    # 올해 경기북부
            'latest_north': north_all[:8],       # 최근 경기북부 산불 8건
            'latest_all': normalized[:5],        # 최근 전국 5건
        }
        return {'incidents': north_all, 'summary': summary}
    except Exception as e:
        print(f'    산불발생: {e}')
        return {'incidents': [], 'summary': None}


def fetch_fire():
    """국립산림과학원 산불위험예보 V2 — 시군구별 위험도.
    응답의 d1~d4 는 해당 시군 안에서 각 위험단계(낮음·보통·높음·매우높음) 면적 비율(%).
    한 시군 안에 더 높은 단계가 1%라도 있으면 그 단계로 표시."""
    url = 'https://apis.data.go.kr/1400377/forestPointV2/forestPointListSigunguSearchV2'
    r = requests.get(url, params={
        'serviceKey': DATA_KEY,
        'pageNo': 1,
        'numOfRows': 300,
        '_type': 'json',
    }, timeout=15)
    r.raise_for_status()
    body = r.json()['response']['body']
    items_obj = body.get('items', {})
    if not items_obj:
        return []
    items = items_obj.get('item', [])
    if isinstance(items, dict):
        items = [items]

    # 산불 API의 시군 표기 → 관서명 (구가 있는 시는 구 단위로 내려온다)
    sigun_map = P['fire_sigun_map']

    region_max = {}
    for it in items:
        if str(it.get('doname', '')) != '경기도':
            continue
        sigun = str(it.get('sigun', '')).strip()
        target = sigun_map.get(sigun)
        if not target:
            continue
        d2 = float(it.get('d2', 0) or 0)
        d3 = float(it.get('d3', 0) or 0)
        d4 = float(it.get('d4', 0) or 0)
        if d4 > 0:   level = 4
        elif d3 > 0: level = 3
        elif d2 > 0: level = 2
        else:        level = 1
        region_max[target] = max(region_max.get(target, 0), level)

    groups = P['fire_groups']
    text_map = {1: '낮음', 2: '보통', 3: '높음', 4: '매우높음'}
    result = []
    for group_name, sigungus in groups.items():
        levels = [region_max.get(s, 1) for s in sigungus]
        max_level = max(levels)
        result.append({'region': group_name, 'level': max_level, 'levelText': text_map[max_level]})
    return result


# ============================================================
# 6. 하천 수위 (한강홍수통제소)
# ============================================================

# 경기북부 주요 관측소 — 한강홍수통제소 실제 등록 코드 및 기준수위
# has_cctv: CCTV iframe 표시 여부 (False 시 자료 페이지 링크)
# api: 'waterlevel' (일반 하천) 또는 'dam' (댐 시설 — 저수위·저수율·유입·방류)
# 하천·댐 관측소.
#  · warning/danger = 한강홍수통제소 info API의 attwl(관심)/almwl(경계). 임의값 아님.
#    (2026-07-23 API 조회로 확정. 기존 8개소는 이 매핑과 이미 일치함을 실측 확인.)
#  · 댐은 attwl이 없어 fldlmtwl(홍수기제한수위)/pfh(계획홍수위)를 쓴다. 없으면 warning=None
#    (riverLevel이 null을 안전하게 건너뜀). 군남댐은 기존 수동값 유지.
#  · sigun = 관서 매칭용 명시 필드. 예전엔 이름 문자열로 매칭해서 '양주'가 '남양주'에도
#    걸려 남양주 하천이 양주 관서에 뜨는 충돌이 있었다. 이름에 의존하지 않는다.
RIVER_STATIONS = P['river_stations']


def river_level(value, warning, danger):
    """수위 → 단계. 기준값이 없는 관측소(댐 중 제한수위 미제공)가 있어 None을 견뎌야 한다.
    None 비교는 파이썬에서 TypeError라, 방어 없이 쓰면 그 관측소가 통째로 사라진다."""
    if value is None:
        return 'safe'
    if danger is not None and value >= danger:
        return 'danger'
    if warning is not None and value >= warning:
        return 'warning'
    return 'safe'


def fetch_rivers():
    """관측소별 24시간 수위 시계열 수집.
    한강홍수통제소(api.hrfco.go.kr)가 외국 IP(GitHub Actions 미국 서버 등)에서
    매우 느리거나 timeout. 환경별 차등 처리:
    - 정상(한국 IP): timeout 8초 × 2회 재시도 → 첫 시도에서 거의 성공
    - 외국 IP: timeout 5초 × 1회 → 약 5-10초 안에 fail, main()에서 기존 데이터 보존
    """
    import os
    # GitHub Actions 환경 감지 — 자동 단축 모드
    is_ci = bool(os.environ.get('GITHUB_ACTIONS'))
    max_attempts = 1 if is_ci else 2
    req_timeout = 5 if is_ci else 8
    retry_wait = 1 if is_ci else 2
    station_gap = 0.2 if is_ci else 0.8

    result = []
    now = datetime.now()
    sdt = (now - timedelta(hours=24)).strftime('%Y%m%d%H')
    edt = now.strftime('%Y%m%d%H')

    sess = requests.Session()
    sess.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                      '(KHTML, like Gecko) Chrome/120.0 Safari/537.36',
        'Accept': 'application/json',
        'Connection': 'close',
    })

    # 같은 관측소를 여러 관서가 나눠 쓰는 경우가 있다(안양천 충훈1교 = 안양·과천·군포·의왕).
    # 코드별로 한 번만 부르고 결과를 돌려쓴다 — 안 그러면 5분마다 같은 호출을 네 번 한다.
    fetched = {}

    for st_idx, st in enumerate(RIVER_STATIONS):
        cache_key = (st['code'], st.get('api', 'waterlevel'))
        if cache_key in fetched:
            base = fetched[cache_key]
            if base is not None:
                item = dict(base)
                item.update({'name': st['name'], 'sigun': st.get('sigun', ''),
                             'warning': st.get('warning'), 'danger': st.get('danger'),
                             'has_cctv': st.get('has_cctv', False)})
                item['level'] = river_level(item.get('value'), st.get('warning'),
                                            st.get('danger'))
                result.append(item)
            continue

        if st_idx > 0:
            time.sleep(station_gap)  # 관측소 사이 텀

        last_err = None
        api = st.get('api', 'waterlevel')
        wl_field = 'swl' if api == 'dam' else 'wl'  # 댐은 저수위(swl), 하천은 수위(wl)
        fetched[cache_key] = None   # 실패해도 같은 코드를 다시 부르지 않도록 자리 예약

        for attempt in range(max_attempts):
            try:
                url = f'https://api.hrfco.go.kr/{HRFCO_KEY}/{api}/list/1H/{st["code"]}/{sdt}/{edt}.json'
                r = sess.get(url, timeout=req_timeout)
                r.raise_for_status()
                content = r.json().get('content', [])
                if not content:
                    break

                # 시계열 history 구성 (시간 오름차순으로 정렬)
                history = []
                dam_info_latest = None
                for entry in content:
                    v = entry.get(wl_field, '')
                    if v in ('', None) or str(v).strip() == '':
                        continue
                    try:
                        vf = float(v)
                    except ValueError:
                        continue
                    ymdhm = str(entry.get('ymdhm', ''))
                    history.append({'time': ymdhm, 'value': vf})
                    # 댐이면 추가 필드도 같이
                    if api == 'dam':
                        def safe_f(k):
                            x = entry.get(k, '')
                            try: return float(x)
                            except: return None
                        dam_info_latest = {
                            'storage_rate': safe_f('ecpc'),   # 저수율 %
                            'inflow': safe_f('inf'),          # 유입량 m³/s
                            'outflow': safe_f('sfw'),         # 방류량 m³/s
                            'total_outflow': safe_f('tototf'),# 총유출량
                        }

                if not history:
                    break
                history.sort(key=lambda h: h['time'])
                latest = history[-1]['value']
                level = river_level(latest, st.get('warning'), st.get('danger'))

                def delta(hours_ago):
                    if len(history) < hours_ago + 1: return None
                    return round(latest - history[-(hours_ago + 1)]['value'], 2)

                item = {
                    'name': st['name'],
                    'code': st['code'],
                    'sigun': st.get('sigun', ''),   # 관서 매칭용(이름 문자열 매칭의 양주/남양주 충돌 방지)
                    'value': latest,
                    'warning': st['warning'],
                    'danger': st['danger'],
                    'level': level,
                    'history': history[-24:],
                    'delta_1h': delta(1),
                    'delta_3h': delta(3),
                    'has_cctv': st.get('has_cctv', True),
                    'api': api,
                }
                if api == 'dam' and dam_info_latest:
                    item['dam_info'] = dam_info_latest
                fetched[cache_key] = item
                result.append(item)
                break
            except Exception as e:
                last_err = e
                time.sleep(retry_wait)
        else:
            print(f'    하천 {st["name"]}: {max_attempts}회 실패 — {type(last_err).__name__}')
    return result


def fetch_rivers_light():
    """하천 '현재 수위·단계'만 가볍게 수집 — 1분 알리미(check_warnings.py)용.
    fetch_rivers는 24시간 이력을 받아 무겁다. 여기선 최근 3시간만 받아 최신값·단계만 판정한다.
    실패한 관측소는 결과에서 제외(omit) → notify_rivers가 이전 상태를 보존해 오알림을 막는다."""
    if not HRFCO_KEY:
        return []
    now = datetime.now()
    sdt = (now - timedelta(hours=3)).strftime('%Y%m%d%H')
    edt = now.strftime('%Y%m%d%H')
    sess = requests.Session()
    sess.headers.update({'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json',
                         'Connection': 'close'})
    out = []
    seen = {}   # 여러 관서가 공유하는 관측소는 한 번만 호출하고 값을 돌려쓴다
    for i, st in enumerate(RIVER_STATIONS):
        api = st.get('api', 'waterlevel')
        key = (st['code'], api)
        if key in seen:
            if seen[key] is not None:
                out.append(dict(seen[key], name=st['name'],
                                warning=st.get('warning'), danger=st.get('danger'),
                                level=river_level(seen[key]['value'], st.get('warning'),
                                                  st.get('danger'))))
            continue
        if i > 0:
            time.sleep(0.2)
        wl_field = 'swl' if api == 'dam' else 'wl'
        seen[key] = None
        try:
            url = f'https://api.hrfco.go.kr/{HRFCO_KEY}/{api}/list/1H/{st["code"]}/{sdt}/{edt}.json'
            r = sess.get(url, timeout=6)
            r.raise_for_status()
            content = r.json().get('content', [])
            best_t, latest = '', None
            for entry in content:                     # content 정렬을 신뢰하지 않고 최대 ymdhm 채택
                v = entry.get(wl_field, '')
                if v in ('', None) or str(v).strip() == '':
                    continue
                try:
                    vf = float(v)
                except (ValueError, TypeError):
                    continue
                t = str(entry.get('ymdhm', ''))
                if t >= best_t:                        # YYYYMMDDHH 사전순 = 시간순
                    best_t, latest = t, vf
            if latest is None:
                continue
            level = river_level(latest, st.get('warning'), st.get('danger'))
            rec = {'name': st['name'], 'code': st['code'], 'value': round(latest, 3),
                   'warning': st['warning'], 'danger': st['danger'], 'level': level, 'api': api}
            seen[key] = rec
            out.append(rec)
        except Exception:
            continue   # 실패 관측소는 제외 → notify_rivers가 이전 상태 보존
    return out


# ============================================================
# 7. 재난문자 (행안부 — 키 발급 시 활성화)
# ============================================================

def fetch_flood_forecast():
    """한강홍수통제소 홍수예보 발령 정보.
    endpoint: https://api.hrfco.go.kr/{KEY}/fldfct/list.json
    응답: 최근 24시간 전체 관측소 발령 정보 (관측소 코드 미명시 시 전체).
    평상시는 code=990(자료없음)으로 빈 응답.

    응답 필드: ANCDT(발표일시), ANCNM(발표자), FCTDT(수위도달예상),
              KIND(주의보/경보), NO(번호), OBSNM(지점), RVRNM(강명),
              STTCURDT(현재일시), STTCURHGT(현재수위표수위), STTCURSEALVL(현재해발수위),
              STTNM(관측소코드), WRNARANM(주의지역).
    """
    if not HRFCO_KEY:
        return []
    import os
    # CI 환경에서는 짧은 timeout — 외국 IP는 어차피 막히면 빠르게 포기
    ci_timeout = 5 if os.environ.get('GITHUB_ACTIONS') else 15
    url = f'https://api.hrfco.go.kr/{HRFCO_KEY}/fldfct/list.json'
    try:
        r = requests.get(url, timeout=ci_timeout, headers={
            'User-Agent': 'Mozilla/5.0',
            'Accept': 'application/json',
        })
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        print(f'    홍수예보: {type(e).__name__}')
        return []

    code = str(data.get('code', ''))
    if code != '200':
        # 990 = 자료 없음 (평상시 정상), 그 외 코드는 오류
        return []
    items = data.get('links', []) or []

    # 경기북부 관련 키워드: 시군명 + 북부 흐르는 주요 강·하천
    north_keywords = P['flood_keywords']   # 관할 시군 + 그 지역 주요 하천명

    result = []
    for it in items:
        wrn_area = str(it.get('WRNARANM', ''))
        rvr = str(it.get('RVRNM', ''))
        obs = str(it.get('OBSNM', ''))
        kind = str(it.get('KIND', ''))

        # 종류 → 단계
        if '경보' in kind:    level = 'severe'
        elif '주의보' in kind: level = 'warning'
        else:                 level = 'info'

        # 경기북부 매칭
        search_text = f'{wrn_area} {rvr} {obs}'
        north_match = any(k in search_text for k in north_keywords)

        # 시간 포맷 (yyyymmddhhmm → mm/dd hh:mm)
        def fmt_dt(s):
            s = str(s or '')
            if len(s) >= 12:
                return f'{s[4:6]}/{s[6:8]} {s[8:10]}:{s[10:12]}'
            return s

        result.append({
            'kind': kind,
            'no': str(it.get('NO', '')),
            'announce_time': fmt_dt(it.get('ANCDT', '')),
            'forecast_time': fmt_dt(it.get('FCTDT', '')),
            'announcer': str(it.get('ANCNM', '')),
            'river': rvr,
            'station': obs,
            'station_code': str(it.get('STTNM', '')),
            'area': wrn_area,
            'current_level': str(it.get('STTCURHGT', '')),
            'sea_level': str(it.get('STTCURSEALVL', '')),
            'level': level,
            'north_match': north_match,
        })
    # 최신순(발표일시 내림차순) — fmt_dt 변환 전 ANCDT 기준 정렬은 어렵지만 API가 일반적으로 최신순 제공
    return result


def fetch_messages():
    """행안부 긴급재난문자 (safetydata.go.kr DSSP-IF-00247).
    경기도 전역 메시지를 받고, region 필드에 정확한 시군명을 부여.
    HTML의 동두천 중점 모드는 region이 '동두천' 또는 '경기도'(전역)만 표시.
    광역 모드는 모든 경기도 메시지 표시."""
    if not SAFETY_KEY:
        print('    재난문자: SAFETY_DATA_KEY 미설정')
        return []

    url = 'https://www.safetydata.go.kr/V2/api/DSSP-IF-00247'
    now = datetime.now()
    today = now.strftime('%Y%m%d')

    north_sigun = [r['name'] for r in REGIONS]   # 관할 시군 (프로파일)
    gun_names = GUN_NAMES

    import re as _re

    def is_north_gyeonggi(rcptn):
        """이 상황판 관할 메시지만 통과.
        - 관할 시군이 포함되면 → 포함 (예: 경기도 동두천시)
        - 시군명 없는 '경기도' 전역 → 포함 (관할도 해당)
        - 반대편 광역('경기남부'↔'경기북부') 또는 관할 밖 시군 → 제외
        - 서울·인천 등 비경기 → 제외"""
        s = rcptn.strip()
        if not s.startswith('경기'):
            return False
        if s.startswith(P['exclude_prefix']):
            return False
        if any(k in s for k in north_sigun):
            return True
        m = _re.search(r'경기[도북부남]*\s*([가-힣]+?)(시|군)', s)
        if m:
            return m.group(1) in north_sigun   # 특정 시군이면 북부만
        return True   # 시군명 없는 경기 전역

    try:
        r = requests.get(url, params={
            'serviceKey': SAFETY_KEY,
            'pageNo': 1,
            'numOfRows': 100,
            'crtDt': today,
        }, timeout=15)
        r.raise_for_status()
        items = r.json().get('body') or []
    except Exception as e:
        print(f'    재난문자: {e}')
        return None   # 수집 실패 — 정상 0건([])과 구분(main에서 이전 목록 보존)

    result = []
    for it in items:
        rcptn = str(it.get('RCPTN_RGN_NM', ''))
        if not is_north_gyeonggi(rcptn):
            continue
        msg = str(it.get('MSG_CN', '')).strip()
        crt = str(it.get('CRT_DT', ''))
        time_str = crt[11:16] if len(crt) >= 16 else ''

        # 송출 시군 추출 - 우리 북부 시군 우선
        sender, region = None, None
        for k in north_sigun:
            if k in rcptn:
                sender = k + ('군' if k in gun_names else '시')
                region = k
                break

        # 북부가 아니면: "경기도 광주시" 같은 패턴에서 시군명 추출
        if not region:
            m = _re.search(r'경기[도북부남]*\s+([가-힣]+?)(시|군)', rcptn)
            if m:
                sender = m.group(1) + m.group(2)
                region = m.group(1)
            else:
                # "경기도", "경기북부" 등 도 전역
                sender = '경기도'
                region = '경기도'

        result.append({
            'sender': sender,
            'time': time_str,
            'date': crt[:10],   # 'YYYY/MM/DD' — 알림 중복판정 키 안정화용(화면 미표시)
            'text': msg[:300],
            'region': region,
            'sn': int(it.get('SN', 0)),   # 고유번호 — 알림 중복판정 키용(화면 미표시)
        })

    # SN 내림차순 (최신 발송 우선)
    result.sort(key=lambda x: x['sn'], reverse=True)

    return result[:20]


# ============================================================
# 저장
# ============================================================

def save_data(data):
    """data.js 저장 — 공백·들여쓰기 제거하여 약 50% 압축."""
    with open(OUTPUT_PATH, 'w', encoding='utf-8') as f:
        f.write('// 자동 생성. ')
        f.write(f'마지막 갱신: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}\n')
        f.write('window.DASHBOARD_DATA = ')
        json.dump(data, f, ensure_ascii=False, separators=(',', ':'))
        f.write(';\n')


def git_push_data():
    """수집한 데이터를 GitHub에 자동 푸시.
    .git/config의 PAT가 박힌 remote URL을 사용하므로 인증 자동.

    핵심: 사장님 PC와 GitHub Actions가 둘 다 5분마다 push하면 origin이 앞서있어
    push가 거부(non-fast-forward)됨. 그대로 두면 local에 commit이 수백 개 누적.
    → push 실패 시 'git pull --rebase'로 원격 변경을 가져와 내 commit을 그 위에 얹고,
      데이터 파일 충돌은 내 최신값 우선(--strategy-option=theirs)으로 자동 해결 후 재push.
    이렇게 하면 양쪽이 충돌 없이 공존(누적 0)."""
    try:
        # 1. 모든 변경사항 stage (.gitignore가 .env·.tmp 등 자동 제외)
        subprocess.run(
            ['git', 'add', '-A'],
            cwd=str(ROOT), check=False, capture_output=True
        )
        # 2. 변경사항 있는지 확인
        diff = subprocess.run(
            ['git', 'diff', '--staged', '--quiet'],
            cwd=str(ROOT), capture_output=True
        )
        if diff.returncode == 0:
            print('  · 변경사항 없음 — 푸시 생략')
            return
        # 3. commit
        msg = f'데이터 갱신 {datetime.now().strftime("%Y-%m-%d %H:%M")}'
        subprocess.run(
            ['git', 'commit', '-m', msg],
            cwd=str(ROOT), check=False, capture_output=True
        )
        # 4. push 시도 → 실패하면 원격 동기화(rebase) 후 재시도 (최대 2회)
        for attempt in range(2):
            # 목적지 명시(origin HEAD:main) — .git 재생성 등으로 upstream이 날아가도
            # 'git push'가 "no upstream"으로 실패하지 않도록. (2026-07-12 프리즈 원인 차단)
            push = subprocess.run(
                ['git', 'push', 'origin', 'HEAD:main'],
                cwd=str(ROOT), capture_output=True, text=True, timeout=60
            )
            if push.returncode == 0:
                print('  ✓ GitHub 푸시 완료')
                return
            # push 실패 — origin이 앞서있을 가능성. rebase로 동기화.
            print(f'  · 푸시 거부(시도 {attempt + 1}) — 원격 변경 가져와 재시도')
            pull = subprocess.run(
                ['git', 'pull', '--rebase', '--strategy-option=theirs',
                 'origin', 'main'],
                cwd=str(ROOT), capture_output=True, text=True, timeout=120
            )
            if pull.returncode != 0:
                # rebase 실패(드묾) — 안전하게 중단. 다음 회차에 재시도.
                subprocess.run(['git', 'rebase', '--abort'],
                               cwd=str(ROOT), check=False, capture_output=True)
                err = (pull.stderr or pull.stdout or '').strip()[:150]
                print(f'  ✗ 원격 동기화 실패 — 다음 회차 재시도: {err}')
                return
        print('  ✗ 재시도 후에도 푸시 실패 — 다음 회차 재시도')
    except subprocess.TimeoutExpired:
        print('  ✗ GitHub 푸시 타임아웃 (다음 회차 재시도)')
        subprocess.run(['git', 'rebase', '--abort'],
                       cwd=str(ROOT), check=False, capture_output=True)
    except FileNotFoundError:
        print('  ! git 명령 못 찾음 — Git for Windows 설치 필요')
    except Exception as e:
        print(f'  ✗ GitHub 푸시 오류: {e}')


# ============================================================
# 적응형 배포 — GitHub Actions 무료시간 절약
# ============================================================
DEPLOY_STATE_PATH = TMP / 'last_deploy.json'


def _load_deploy_state():
    try:
        return json.loads(DEPLOY_STATE_PATH.read_text(encoding='utf-8'))
    except Exception:
        return {}


def _save_deploy_state(ts, sig):
    try:
        _atomic_write_text(DEPLOY_STATE_PATH, json.dumps({'ts': ts, 'sig': sig}, ensure_ascii=False))
    except Exception:
        pass


def _trigger_deploy():
    """deploy-trigger 브랜치에 현재 HEAD를 push해 Cloudflare 배포를 띄운다.
    기존 git push(원격 URL의 PAT) 재사용 → 새 토큰·도구 불필요. 성공 시 True."""
    try:
        r = subprocess.run(['git', 'push', 'origin', 'HEAD:deploy-trigger', '-f'],
                           cwd=str(ROOT), capture_output=True, text=True, timeout=60)
        return r.returncode == 0
    except Exception:
        return False


def deploy_decision(data, extra=None):
    """배포가 필요한지 '판단만' 한다(실행 없음). → (사유 or None, 서명, 경과분)
    extra: 함께 볼 다른 지역의 data (한 번의 배포가 두 사이트를 같이 올리므로,
           남부에만 특보가 떠도 즉시 나가야 한다).

    · 이슈(특보/예비특보/하천 주의·위험 목록 '변화') → 즉시 (중복 방지 4분 쿨다운)
    · 특보 발효 중 → 20분마다
    · 평소 → 40분마다

    실행에서 분리한 이유: 커밋도 이 판단을 따르게 하려고. 예전엔 5분마다 무조건
    커밋하고 배포만 걸렀는데, 배포는 평균 40분에 한 번이라 나머지 커밋 7개는
    아무도 보지 않는 데이터였다. 그 커밋들이 저장소를 하루 수십MB씩 불려
    히스토리 압축을 자주 부르고, 압축이 돌 때마다 개발 PC 클론의 공통 조상이
    사라져 작업이 끊겼다."""
    now = datetime.now()
    st = _load_deploy_state()
    last = _safe_dt(st.get('ts', '')) if st.get('ts') else None
    mins = (now - last).total_seconds() / 60 if last else 1e9
    parts = [_deploy_sig(d) for d in ([data] + list(extra or []))]
    sig = '@@'.join(p[0] for p in parts)      # 지역별 서명을 이어붙임
    rapid = any(p[1] for p in parts)
    changed = (sig != st.get('sig', ''))

    if changed and mins >= 4:
        reason = '이슈변화'
    elif rapid and mins >= 20:
        reason = '급변특보중'
    elif mins >= 40:
        reason = '평소'
    else:
        reason = None   # 배포 안 함 — 상태 미변경(변화 있으면 쿨다운 후 다음 회차에 반영)
    return reason, sig, mins


def _deploy_sig(data):
    """한 지역 데이터의 '상황 서명'과 급변 여부. 서명이 바뀌면 화면을 새로 내보낸다."""
    warns = sorted((str(w.get('type', '')) + '|' + str(w.get('area', ''))) for w in (data.get('warnings') or []))
    prelims = sorted(str(g.get('type', '')) for g in (data.get('prelim_warnings') or []))
    risky = sorted((str(r.get('code', '')) + ':' + str(r.get('level', '')))
                   for r in (data.get('rivers') or []) if r.get('level') in ('warning', 'danger'))
    # ⚠ 홍수예보 발령·태풍·새 재난문자도 화면을 빨리 갱신해야 한다. 예전엔 sig에 없어서,
    #   특보 변화가 없으면 이것들이 새로 떠도 화면이 최대 40분 늦었다(텔레그램만 즉시 나감).
    flood = sorted(str(f.get('river', '')) + '!' + str(f.get('kind', '')) for f in (data.get('flood_forecast') or []))
    typ = sorted(str(t.get('seq', '')) + '!' + str(t.get('eff', '')) for t in (data.get('typhoon') or []))
    _sns = [str(m.get('sn', '')) for m in (data.get('messages') or []) if m.get('sn')]
    msg_fp = str(len(_sns)) + ':' + (max(_sns) if _sns else '')   # 새 재난문자 오면 fp 변함
    # 물때(조석) — 하루 1회(자정) 날짜가 바뀔 때만 변한다. sig에 없으면 새 날짜 물때가
    #   최대 40분 늦게 뜬다(홍수예보·태풍을 sig에 넣은 것과 같은 이유). 낮 동안은 불변.
    _tide = data.get('tide') or {}
    tide_fp = str(_tide.get('date', '')) + ':' + '/'.join(
        e.get('dupo', '') for e in (_tide.get('events') or []) if e.get('kind') == 'high')
    sig = '#'.join(['/'.join(warns), '/'.join(prelims), '/'.join(risky),
                    '/'.join(flood), '/'.join(typ), msg_fp, tide_fp])   # +물때(날짜변경시)
    # 급변 특보(호우·태풍 등)·하천 위험·홍수예보·태풍은 20분(빠르게), 안정 특보(폭염·한파 등)·평소는 40분.
    # 폭염특보가 며칠 이어져도 화면을 20분마다 새로 그릴 필요는 없어 용량을 아낀다.
    RAPID = ('호우', '태풍', '대설', '강풍', '풍랑', '홍수', '해일')
    rapid = bool(risky) or bool(flood) or bool(typ) \
                        or any(any(k in x for k in RAPID) for x in warns) \
                        or any(any(k in x for k in RAPID) for x in prelims)
    return sig, rapid


def run_deploy(reason, sig, mins):
    """배포 트리거 실행 — deploy-trigger 브랜치 push(cloudflare-deploy.yml).
    긴급 알림은 별개(1분 텔레그램)."""
    if _trigger_deploy():
        _save_deploy_state(datetime.now().isoformat(timespec='seconds'), sig)
        print(f'  ✈ Cloudflare 배포 트리거 ({reason}, 이전 배포 {mins:.0f}분 전)')
        return True
    print('  ✗ 배포 트리거 실패(git push deploy-trigger) — 다음 회차/안전스케줄에 재시도')
    return False


def maybe_deploy(data):
    """판단 → 필요하면 배포. 조건 미충족이면 아무것도 안 함(=Actions 무료시간 0)."""
    reason, sig, mins = deploy_decision(data)
    if not reason:
        return False
    return run_deploy(reason, sig, mins)


def save_combined_html(data):
    """index.html에 data를 인라인으로 박은 자급자족 단일 HTML 생성.
    이 파일 하나만 들고 다녀도 모든 데이터+디자인이 들어있다."""
    if not TEMPLATE_PATH.exists():
        print(f'  ✗ 템플릿 없음: {TEMPLATE_PATH}'); return
    with open(TEMPLATE_PATH, encoding='utf-8') as f:
        html = f.read()

    # <script src="data.js" ...> 부분을 인라인 데이터로 치환 (minify)
    data_json = json.dumps(data, ensure_ascii=False, separators=(',', ':'))
    snapshot_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    inline_script = (
        f'<!-- {snapshot_time} 스냅샷. 이 파일 하나로 작동. -->\n'
        f'<script>window.DASHBOARD_DATA = {data_json};</script>'
    )

    import re
    pattern = r'<script src="data\.js"[^>]*></script>'
    if re.search(pattern, html):
        html = re.sub(pattern, inline_script, html)
    else:
        print('  ⚠ index.html 안에서 data.js 참조를 못 찾음 — 단일 HTML 미생성')
        return

    # 단일 HTML에선 5분 자동 새로고침 의미 없음. 제거.
    html = re.sub(
        r"setInterval\(\(\) => \{ location\.reload\(\); \}, 5 \* 60 \* 1000\);",
        f"// 단일 HTML 스냅샷 — 자동 새로고침 비활성 (생성 시각: {snapshot_time})",
        html
    )

    with open(COMBINED_OUTPUT_PATH, 'w', encoding='utf-8') as f:
        f.write(html)


def load_previous_data(path=None):
    """data.js에서 window.DASHBOARD_DATA JSON 부분을 파싱해서 dict로 반환.
    GitHub Actions에서 hrfco(한강홍수통제소)가 외국 IP로 접근 불가일 때
    rivers·flood_forecast 같은 필드를 이전 값으로 보존하기 위한 폴백 소스.
    path를 주면 다른 지역의 data.js도 읽는다(전국 공통 이미지 메타 공유용)."""
    try:
        path = OUTPUT_PATH if path is None else Path(path)
        if not path.exists():
            return {}
        text = path.read_text(encoding='utf-8')
        # 'window.DASHBOARD_DATA = ' 다음의 JSON을 추출
        marker = 'window.DASHBOARD_DATA = '
        idx = text.find(marker)
        if idx < 0:
            return {}
        json_text = text[idx + len(marker):].rstrip().rstrip(';').strip()
        return json.loads(json_text)
    except Exception as e:
        print(f'  · data.js 로드 실패: {type(e).__name__}')
        return {}


# ============================================================
# 텔레그램 급변 알림
# ============================================================

SUBSCRIBERS_PATH = TMP / 'telegram_subscribers.json'
SENT_MESSAGES_PATH = TMP / 'sent_disaster_msgs.json'


def _load_sent_messages():
    """이미 텔레그램으로 보낸 재난문자 키 기록 {key: 최초발송시각ISO}.
    prev(data.js)가 수집 실패 등으로 비어도 재발송을 막는 영구 기록
    (.tmp, git 미추적 → 서버 git reset에도 보존)."""
    try:
        if SENT_MESSAGES_PATH.exists():
            return json.loads(SENT_MESSAGES_PATH.read_text(encoding='utf-8'))
    except Exception:
        pass
    return {}


def _save_sent_messages(log):
    """2일 지난 키는 정리(무한 증가 방지) 후 저장."""
    try:
        cutoff = datetime.now() - timedelta(days=2)
        pruned = {}
        for k, v in log.items():
            try:
                if datetime.fromisoformat(v) >= cutoff:
                    pruned[k] = v
            except Exception:
                pruned[k] = v   # 시각 파싱 실패 키는 안전하게 보존
        _atomic_write_text(SENT_MESSAGES_PATH, json.dumps(pruned, ensure_ascii=False))
    except Exception:
        pass


def send_telegram_to(chat_id, text):
    """특정 chat_id로 텔레그램 메시지 발송."""
    if not TELEGRAM_BOT_TOKEN or not chat_id:
        return False
    try:
        r = requests.post(
            f'https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage',
            json={'chat_id': chat_id, 'text': text,
                  'parse_mode': 'HTML', 'disable_web_page_preview': True},
            timeout=10)
        return r.status_code == 200
    except Exception as e:
        print(f'    텔레그램 발송 오류: {type(e).__name__}')
        return False


def send_telegram(text):
    """사장님(.env CHAT_ID)에게만 발송 — 연결 테스트·하위호환용."""
    return send_telegram_to(TELEGRAM_CHAT_ID, text)


def _load_subscribers():
    try:
        if SUBSCRIBERS_PATH.exists():
            return json.loads(SUBSCRIBERS_PATH.read_text(encoding='utf-8'))
    except Exception:
        pass
    return {'subscribers': {}, 'offset': 0}


def _save_subscribers(state):
    try:
        _atomic_write_text(SUBSCRIBERS_PATH, json.dumps(state, ensure_ascii=False))
    except Exception:
        pass


def sync_telegram_subscribers():
    """봇에 온 메시지를 확인해 구독자 명단을 관리.
    /start·구독 → 추가(환영 메시지), /stop·해제 → 제거.
    getUpdates의 offset으로 같은 메시지를 두 번 처리하지 않음.
    반환: 현재 구독자 chat_id 리스트."""
    if not TELEGRAM_BOT_TOKEN:
        return []
    state = _load_subscribers()
    subs = state.get('subscribers', {})   # {chat_id(str): 이름}
    offset = state.get('offset', 0)
    try:
        r = requests.get(
            f'https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates',
            params={'offset': offset + 1, 'timeout': 0}, timeout=15)
        for upd in (r.json().get('result') or []):
            offset = max(offset, upd.get('update_id', 0))
            msg = upd.get('message') or {}
            chat = msg.get('chat') or {}
            cid = str(chat.get('id', '') or '')
            text = (msg.get('text') or '').strip().lower()
            name = chat.get('first_name') or chat.get('username') or cid
            if not cid:
                continue
            if text in ('/start', '/subscribe', '구독'):
                if cid not in subs:
                    subs[cid] = name
                    send_telegram_to(cid,
                        f'✅ <b>{P["label"]} 기상·재난 알림</b> 구독 완료\n'
                        '특보·하천수위·재난문자 급변 시 이곳으로 알려드립니다.\n'
                        '구독 해제는 /stop')
            elif text in ('/stop', '/unsubscribe', '해제'):
                if cid in subs:
                    subs.pop(cid, None)
                    send_telegram_to(cid, '🔕 알림 구독이 해제되었습니다.\n다시 받으려면 /start')
    except Exception as e:
        print(f'    구독자 동기화 오류: {type(e).__name__}')
    state['subscribers'] = subs
    state['offset'] = offset
    _save_subscribers(state)
    return list(subs.keys())


NOTIFY_OFF_PATH = ROOT / 'NOTIFY_OFF'


def send_telegram_all(text):
    """사장님(.env CHAT_ID) + 모든 구독자에게 발송. (성공수, 전체수) 반환.

    긴급 차단 스위치: 저장소 루트에 NOTIFY_OFF 파일이 있으면 모든 방송 알림을
    무조건 건너뛴다(0,0 반환). 상태파일·디스크와 무관하게 동작하므로, 서버 접속
    없이 main에 NOTIFY_OFF를 커밋하는 것만으로 반복 알림 폭주를 즉시 멈출 수 있다.
    (재개하려면 NOTIFY_OFF를 지우고 커밋하면 됨.)"""
    if NOTIFY_OFF_PATH.exists():
        print('  ⏸ NOTIFY_OFF 존재 — 방송 알림 일시 중단')
        return 0, 0
    targets = set()
    if TELEGRAM_CHAT_ID:
        targets.add(str(TELEGRAM_CHAT_ID))
    targets.update(_load_subscribers().get('subscribers', {}).keys())
    ok = 0
    for cid in targets:
        if send_telegram_to(cid, text):
            ok += 1
    return ok, len(targets)


def merge_apihub_warnings(d):
    """index.html normalizeWarningsFromApihub의 서버판 —
    화면과 알림이 같은 특보를 보도록, 허브 특보(apihub_warnings)의 북부 발효특보를
    warnings에 dedup 병합하고 예비특보를 prelim_warnings로 그룹화한다.
    (화면엔 떠도 알림은 안 가던 누락 방지. 클라이언트 병합과 멱등.)"""
    aw = d.get('apihub_warnings') or []
    if not aw:
        return
    # 예비특보 그룹화 (wrn_name 기준)
    prelim_by = {}
    for w in aw:
        if not w.get('is_prelim'):
            continue
        group = (w.get('wrn_name') or '특보') + ' 예비특보'
        g = prelim_by.setdefault(group, {'type': group, 'items': []})
        time_label = f"{w.get('tm_ef_disp')} 발효" if w.get('tm_ef_disp') else (w.get('tm_fc_disp') or '')
        rn, br = w.get('region_name'), w.get('broader_region')
        area_label = f"{rn} ({br})" if rn and rn != br else (rn or br or w.get('reg_id'))
        g['items'].append({'time': time_label, 'area': area_label,
                           'north_match': bool(w.get('is_north_gg'))})
    if prelim_by:
        groups = []
        for g in prelim_by.values():
            g['north_count'] = sum(1 for it in g['items'] if it['north_match'])
            g['total_count'] = len(g['items'])
            groups.append(g)
        d['prelim_warnings'] = groups
    # 발효특보 (북부만) warnings에 dedup 병합
    existing = {f"{w.get('type')}|{w.get('area')}" for w in (d.get('warnings') or [])}
    add = []
    for w in aw:
        if w.get('is_prelim') or not w.get('is_north_gg'):
            continue
        typ = f"{w.get('wrn_name')}{'경보' if w.get('lvl_name') == '경보' else '주의보'}"
        # ⚠ 허브는 특보가 아닌 '현상'도 같이 보낸다(실측: 폭염 91·열대야 63·강풍 19·풍랑 10건).
        #   '열대야'에 주의보를 갖다붙이면 '열대야주의보'라는 없는 특보가 만들어지고,
        #   warnings에 섞여 텔레그램 알림까지 나간다. 정식 특보명만 통과시킨다.
        if typ not in WRN_TYPES:
            continue
        area = w.get('region_name') or w.get('reg_ko')
        key = f"{typ}|{area}"
        if key in existing:
            continue
        existing.add(key)
        add.append({'type': typ, 'area': area, 'time': w.get('tm_fc_disp') or '',
                    'level': 'severe' if w.get('lvl_name') == '경보' else 'warning'})
    if add:
        d['warnings'] = (d.get('warnings') or []) + add


WARN_STATE_PATH = TMP / 'notified_warnings.json'


def _load_warn_state():
    try:
        if WARN_STATE_PATH.exists():
            return json.loads(WARN_STATE_PATH.read_text(encoding='utf-8'))
    except Exception:
        pass
    return {'active': [], 'prelim': []}


def _save_warn_state(state):
    try:
        _atomic_write_text(WARN_STATE_PATH, json.dumps(state, ensure_ascii=False))
    except Exception:
        pass


NOTIFY_RESET_PATH = ROOT / 'NOTIFY_RESET'
RESET_DONE_PATH = TMP / 'notify_reset_done'


def apply_notify_reset():
    """NOTIFY_RESET(토큰 파일)로 특보 알림 상태를 1회 초기화한다.
    NOTIFY_OFF 차단 중 발효돼 '발송함'으로 잘못 기록된 특보를, 차단 해제 후 현재 발효분으로
    다시 감지·발송시키기 위한 복구 스위치. 처리 토큰을 .tmp/notify_reset_done(git 미추적)에
    따로 남겨, 원격에 NOTIFY_RESET 파일이 남아 매 회차 복원돼도 같은 토큰이면 건너뛴다(폭주 방지).
    상태파일 본체(active/sent_prelim)와 분리하므로 notify_warnings의 저장과 충돌하지 않는다."""
    try:
        if not NOTIFY_RESET_PATH.exists():
            return
        try:
            token = NOTIFY_RESET_PATH.read_text(encoding='utf-8').strip()
        except Exception:
            token = ''
        done = ''
        try:
            if RESET_DONE_PATH.exists():
                done = RESET_DONE_PATH.read_text(encoding='utf-8').strip()
        except Exception:
            done = ''
        if token and done == token:
            return
        st = _load_warn_state()
        st['active_regions'] = {}
        st.pop('active', None)      # 구버전 키 정리
        st['sent_prelim'] = {}
        _save_warn_state(st)
        _atomic_write_text(RESET_DONE_PATH, token or 'reset')
        print(f'  🔄 NOTIFY_RESET 적용(token={token!r}) — 특보 상태 초기화(현재 발효분 재발송)')
    except Exception as e:
        print(f'  NOTIFY_RESET 처리 오류: {e}')


def _safe_dt(s):
    try:
        return datetime.fromisoformat(s)
    except Exception:
        return None


_REGION_ORDER = P['region_order']


def _canon_region(name):
    """지역명을 시군 단위로 정규화 — 묶음형/개별형·세부구역 중복 제거용.
    가평군→가평, 고양시→고양, 파주시남부→파주, 양주시동북부→양주.
    광역어(경기북부·경기도·수도권)→'경기도'. 알림 판정을 '종류별 시군 집합'으로 하기 위한 것."""
    import re as _re
    n = (name or '').strip()
    if not n:
        return None
    if n in ('경기북부', '경기남부', '경기도', '수도권', '경기'):
        return '경기도'
    n = _re.sub(r'(동북부|서북부|동남부|서남부|남부|북부|동부|서부|중부|내륙|산지|앞바다|해안)', '', n)
    n = _re.sub(r'(특별자치시|특별자치도|특별시|광역시|자치시|자치도)', '', n)
    n = _re.sub(r'(시|군|구|도)$', '', n)
    return n.strip() or None


def _sort_regions(regs):
    return sorted(regs, key=lambda r: (_REGION_ORDER.index(r) if r in _REGION_ORDER else 99, r))


def notify_warnings(warnings, prelim):
    """기상특보 발효/해제·예비특보 알림 — 누적상태(.tmp/notified_warnings.json) 공유.
    check_warnings.py(1분)와 update_data.py(5분)가 상태를 공유한다.
    - 발효특보: 종류별 '발효 시군 집합'을 저장하고, 회차마다 집합에 '추가된 시군(=발효)'과
      '빠진 시군(=해제)'만 알린다. 기상청이 지역을 재편해도(예: 가평 경보→주의보) 바뀐 시군만
      알리고 안 바뀐 지역은 조용. 묶음형("경기도, 가평, …")과 개별형("가평군")의 중복은 시군
      정규화(_canon_region)로 제거. 화면 데이터(data['warnings'])는 건드리지 않음.
    - 예비특보: '이미 발표한 것'(sent_prelim) 누적기록으로 판정(반복 발송 차단).
    봇 미설정·첫 실행·NOTIFY_OFF는 발송 없이 기록만(폭주 방지)."""
    if not TELEGRAM_BOT_TOKEN:
        return
    if NOTIFY_OFF_PATH.exists():
        return   # 알림 차단 중엔 상태를 건드리지 않는다 — 해제 후 현재 발효분을 정상 감지·발송
    import re as _re
    first_run = not WARN_STATE_PATH.exists()
    state = _load_warn_state()
    # 구버전 상태 이관: sent_prelim 없으면 예비특보 이관, active_regions 없으면 발효/해제 발송 억제(1회)
    prelim_migrating = (not first_run) and ('sent_prelim' not in state)
    active_migrating = (not first_run) and ('active_regions' not in state)

    # 현재 발효특보 → 종류별 시군 집합 (묶음/개별 중복 제거)
    cur_regions = {}      # {종류: set(시군)}
    type_time = {}        # {종류: 대표 발효시각}
    for w in (warnings or []):
        t = (w.get('type', '') or '').strip()
        if not t:
            continue
        regs = set()
        for part in str(w.get('area', '') or '').split(','):
            c = _canon_region(part)
            if c:
                regs.add(c)
        if regs:
            cur_regions.setdefault(t, set()).update(regs)
            if not type_time.get(t) and w.get('time'):
                type_time[t] = w.get('time')
    prev_regions = {k: set(v) for k, v in (state.get('active_regions') or {}).items()}

    # 예비특보 종류 정규화(공백 흔들림 제거)
    cur_prelim = {_re.sub(r'\s+', ' ', (g.get('type', '') or '').strip())
                  for g in (prelim or []) if g.get('type')}
    sent_prelim = dict(state.get('sent_prelim', {}))   # {종류: 최초 발표 ISO}

    now_iso = datetime.now().isoformat(timespec='seconds')
    if prelim_migrating:
        for t in cur_prelim:
            sent_prelim.setdefault(t, now_iso)

    msgs = []
    # 발효특보: 종류별 시군 집합의 델타(추가=발효 / 제거=해제)만 알림
    if not (first_run or active_migrating):
        for t in cur_regions:
            added = cur_regions[t] - prev_regions.get(t, set())
            if added:
                msgs.append(f"🚨 <b>기상특보 발효</b>\n{t} · {', '.join(_sort_regions(added))}"
                            + (f"\n발효 {type_time.get(t, '')}" if type_time.get(t) else ''))
        for t in prev_regions:
            removed = prev_regions[t] - cur_regions.get(t, set())
            if removed:
                msgs.append(f"✅ <b>기상특보 해제</b>\n{t} · {', '.join(_sort_regions(removed))}")

    new_prelim = [t for t in cur_prelim if t not in sent_prelim]
    for t in new_prelim:
        msgs.append(f"⚠️ <b>예비특보 발표</b>\n{t}")

    # sent_prelim 정리: 2일 지났고 현재 목록에도 없는 종류만 제거(무한 증가 방지)
    cutoff = datetime.now() - timedelta(days=2)
    sent_prelim = {t: v for t, v in sent_prelim.items()
                   if (t in cur_prelim) or ((_safe_dt(v) or cutoff) >= cutoff)}

    cur_saved = {k: _sort_regions(v) for k, v in cur_regions.items()}

    def _save(record_new_prelim):
        sp = dict(sent_prelim)
        if record_new_prelim:
            for t in new_prelim:
                sp[t] = now_iso
        _save_warn_state({'active_regions': cur_saved, 'sent_prelim': sp})

    if first_run:
        # 첫 실행: 현재 발효·예비를 '이미 알림'으로 기록만(발송 억제)
        _save_warn_state({'active_regions': cur_saved,
                          'sent_prelim': {t: now_iso for t in cur_prelim}})
        return
    if not msgs:
        _save(False)   # active_migrating이면 여기서 새 형식으로 조용히 이관됨
        return
    header = f"📡 <b>{P['label']} 기상특보</b>\n"
    body = "\n\n".join(msgs[:8])
    if len(msgs) > 8:
        body += f"\n\n…외 {len(msgs) - 8}건"
    sent, total = send_telegram_all(header + body)
    print(f"  ✓ 특보 알림 {len(msgs)}건 → {sent}/{total}명")
    # 발송 성공(또는 대상 0명) 시에만 상태 확정 — 실패 시 다음 회차 재시도
    if sent > 0 or total == 0:
        _save(True)


RIVER_STATE_PATH = TMP / 'notified_rivers.json'


def _load_river_state():
    try:
        if RIVER_STATE_PATH.exists():
            return json.loads(RIVER_STATE_PATH.read_text(encoding='utf-8'))
    except Exception:
        pass
    return {}


def _save_river_state(state):
    try:
        _atomic_write_text(RIVER_STATE_PATH, json.dumps(state, ensure_ascii=False))
    except Exception:
        pass


def notify_rivers(rivers):
    """하천 수위 주의/위험 단계 '진입' 알림 — 누적상태(.tmp/notified_rivers.json) 기반.
    check_warnings.py(1분, 주 담당)와 update_data.py(5분, 백업)가 상태를 공유해 중복 발송이 없다.
    관측소별 '마지막으로 인지한 단계'를 저장하고, 현재 단계가 그보다 높아질 때만(=상승 진입) 알린다.
    단계가 내려가면 상태도 내려 기록(재상승 시 다시 알림). 이번 회차에 수집 못한 관측소는 이전
    상태를 그대로 보존해(수집 실패로 사라진 관측소를 '해소'로 오판하지 않음) 재알림·오알림을 막는다.
    봇 미설정·NOTIFY_OFF·첫 실행은 발송 없이 기록만(배포 직후·차단 중 폭주 방지)."""
    if not TELEGRAM_BOT_TOKEN:
        return
    if NOTIFY_OFF_PATH.exists():
        return   # 알림 차단 중엔 상태 미변경 (해제 후 정상 감지)
    rank_map = {'safe': 0, 'normal': 0, 'warning': 1, 'danger': 2}
    stage_name = {1: '주의', 2: '위험'}
    first_run = not RIVER_STATE_PATH.exists()
    state = _load_river_state()
    new_state = {}
    msgs = []
    for r in (rivers or []):
        code = r.get('code')
        if not code:
            continue
        cur = rank_map.get(r.get('level'), 0)
        prev_rank = int(state.get(code, 0) or 0)
        new_state[str(code)] = cur
        if cur > prev_rank and cur >= 1:
            stage = stage_name.get(cur, '')
            val = r.get('value')
            thr = r.get('danger') if cur == 2 else r.get('warning')
            msgs.append(f"🌊 <b>하천 수위 {stage}단계 진입</b>\n{r.get('name', '')}"
                        + (f"\n현재 {val}m / {stage}수위 {thr}m" if val is not None else ''))
    # 이번 회차에 수집 못한 관측소는 이전 단계 그대로 보존
    for code, rk in state.items():
        new_state.setdefault(str(code), rk)
    if first_run:
        _save_river_state(new_state)   # 첫 실행: 현재 단계 기록만(발송 억제 — 배포 직후 폭주 방지)
        return
    if not msgs:
        _save_river_state(new_state)
        return
    header = f"🌊 <b>{P['label']} 하천 수위</b>\n"
    body = "\n\n".join(msgs[:8])
    if len(msgs) > 8:
        body += f"\n\n…외 {len(msgs) - 8}건"
    sent, total = send_telegram_all(header + body)
    print(f"  ✓ 하천 수위 알림 {len(msgs)}건 → {sent}/{total}명")
    # 발송 성공(또는 대상 0명) 시에만 상태 확정 — 실패 시 상태 미저장 → 다음 회차 재시도
    if sent > 0 or total == 0:
        _save_river_state(new_state)


def detect_and_notify(prev, data):
    """이전 데이터(prev)와 현재(data)를 비교해 급변 시 텔레그램 알림.
    조건: ③-2 댐 방류량 급증 ④재난문자 신규. (①②특보=notify_warnings, ③하천수위=notify_rivers 전담)
    - 봇 미설정이면 skip. 첫 실행(prev 없음)도 skip(알림 폭주 방지).
    - 사장님(.env) + 구독자 전원에게 발송."""
    if not TELEGRAM_BOT_TOKEN:
        return
    if NOTIFY_OFF_PATH.exists():
        return   # 알림 차단 중엔 상태를 건드리지 않는다(해제 후 정상 감지)
    if not prev:
        return

    msgs = []

    # ①② 기상특보·예비특보 = notify_warnings(), ③ 하천 수위 주의/위험 = notify_rivers()가 전담한다.
    #    (둘 다 check_warnings.py 1분 주기 + 여기 5분 백업, 공유 상태로 중복 방지) → 여기선 ③-2·④만 처리.
    prev_r = {r.get('code'): r for r in (prev.get('rivers') or [])}

    # ③-2 댐 방류량 급증 (홍수 조절 방류 → 임진강·신천 하류 수난 위험 직결)
    for r in (data.get('rivers') or []):
        if r.get('api') != 'dam':
            continue
        pr = prev_r.get(r.get('code'))
        if not pr:
            continue
        cur_out = (r.get('dam_info') or {}).get('outflow')
        prev_out = (pr.get('dam_info') or {}).get('outflow')
        if cur_out is None or prev_out is None:
            continue
        # 급증: 현재 200㎥/s 이상 + 이전 대비 1.5배 이상 + 절대 100㎥/s 이상 증가
        if cur_out >= 200 and cur_out >= prev_out * 1.5 and (cur_out - prev_out) >= 100:
            msgs.append(f"🚨 <b>댐 방류량 급증</b>\n{r.get('name', '')}\n"
                        f"{prev_out:.0f} → {cur_out:.0f} ㎥/s\n하류 수위 상승 주의")

    # ④ 재난문자 신규 — 누적 발송기록(.tmp)으로 판정해 재발송을 원천 차단.
    #    prev(직전 data.js)가 수집 실패 등으로 비어도 이미 보낸 문자는 다시 안 보냄.
    def mkey(m):
        # 고유번호(SN) 우선 + 날짜·발신자·시각·본문 — 본문 절단·크로스데이 충돌 방지
        return (f"{m.get('sn','')}|{m.get('date','')}|{m.get('sender','')}"
                f"|{m.get('time','')}|{(m.get('text','') or '')[:40]}")
    first_run = not SENT_MESSAGES_PATH.exists()   # 최초 1회는 발송 없이 기록만(폭주 방지)
    sent_log = _load_sent_messages()
    now_iso = datetime.now().isoformat(timespec='seconds')
    new_disaster = []   # 이번에 새로 보낼 (키, 메시지) — 발송 성공 후에만 기록(유실 방지)
    for m in (data.get('messages') or []):
        k = mkey(m)
        if k in sent_log:
            sent_log[k] = now_iso   # last-seen 갱신 — 보존 중인 문자가 prune돼 재발송되는 것 방지
            continue
        if first_run:
            sent_log[k] = now_iso   # 첫 실행은 발송 없이 기록만
        else:
            text = (m.get('text', '') or '')[:200]
            new_disaster.append((k, f"📢 <b>재난문자</b> · {m.get('sender', '')}\n{text}"))
    for _k, _block in new_disaster:
        msgs.append(_block)
    _save_sent_messages(sent_log)   # last-seen·first_run 갱신분 저장(재난문자 키는 발송 성공 후)

    if not msgs:
        return

    # 여러 건이면 묶어 발송 (최대 8건, 초과 시 요약) — 사장님 + 구독자 전원
    header = f"📡 <b>{P['label']} 기상·재난 상황판</b>\n"
    body = "\n\n".join(msgs[:8])
    if len(msgs) > 8:
        body += f"\n\n…외 {len(msgs) - 8}건"
    sent, total = send_telegram_all(header + body)
    print(f"  ✓ 텔레그램 알림 {len(msgs)}건 → {sent}/{total}명 발송")
    # 재난문자 키는 발송 성공(최소 1명 또는 구독자 0명)일 때만 기록 — 실패 시 다음 회차 재시도
    if new_disaster and (sent > 0 or total == 0):
        for _k, _block in new_disaster:
            sent_log[_k] = now_iso
        _save_sent_messages(sent_log)


EFF_HUMID_PATH = TMP / 'humid_daily.json'


def apply_effective_humidity(regions):
    """실효습도(effective humidity) — 산불·화재 위험 지표. 상황실 v2 '출동 영향 판단'에 사용.
    기상청식: 최근 며칠 '일별 최저습도'의 가중합(비율 r=0.7, 오늘 가중치 최대). 이력이 짧으면
    가중평균(Σr^n·H / Σr^n)으로 안정 추정 — 하루치면 오늘 최저습도, 며칠 쌓이면 정확해진다.
    일별 최저습도를 .tmp/humid_daily.json에 누적(당일은 갱신), 최근 7일만 유지."""
    today = datetime.now().strftime('%Y-%m-%d')
    try:
        store = json.loads(EFF_HUMID_PATH.read_text(encoding='utf-8')) if EFF_HUMID_PATH.exists() else {}
    except Exception:
        store = {}
    R = 0.7
    for reg in regions or []:
        nm = reg.get('name')
        h = reg.get('humid')
        if not nm or h is None:
            continue
        try:
            h = float(h)
        except (TypeError, ValueError):
            continue
        rec = store.get(nm, {})
        rec[today] = min(float(rec.get(today, h)), h)          # 당일 최저 갱신
        days = sorted(rec.keys(), reverse=True)[:7]            # 최근 7일
        rec = {dk: rec[dk] for dk in days}
        store[nm] = rec
        vals = [rec[dk] for dk in days]                         # 최신순(오늘=index 0)
        s = sum((R ** n) * hv for n, hv in enumerate(vals))
        w = sum(R ** n for n in range(len(vals)))
        reg['effHumid'] = round(s / w) if w else round(h)
    try:
        _atomic_write_text(EFF_HUMID_PATH, json.dumps(store, ensure_ascii=False))
    except Exception:
        pass


def push_only():
    """수집 없이 커밋·푸시·배포만. 지역별 수집을 동시에 돌린 뒤 마지막에 한 번 호출한다.
    (각 수집은 --no-push로 파일만 만들고, 여기서 한꺼번에 올린다 — 푸시 경합 방지)

    ⚠ 배포할 때만 커밋한다. 배포 안 하는 회차의 데이터는 화면에 안 나가므로
      기록할 이유가 없다. 그동안 쌓인 변경은 파일로 남아 있다가(update.sh가
      함부로 되돌리지 않음) 다음 배포 회차에 한 커밋으로 같이 올라간다.
      → 커밋 수·저장소 증가량이 약 1/8로 줄어 히스토리 압축이 드물어진다."""
    print(f'[{now_str()}] 푸시 전용 모드')
    # 배포 한 번이 두 사이트를 같이 올리므로 판단도 두 지역을 같이 본다.
    others = [load_previous_data(ROOT / p['data_file'])
              for k, p in _rp.PROFILES.items() if k != PROFILE_NAME]
    reason, sig, mins = deploy_decision(load_previous_data(), others)
    if not reason:
        print(f'  · 배포 조건 미충족(이전 배포 {mins:.0f}분 전) — 커밋·푸시 생략, '
              f'변경은 다음 배포 때 함께 올림')
        print(f'[{now_str()}] 종료')
        return
    git_push_data()
    run_deploy(reason, sig, mins)
    print(f'[{now_str()}] 푸시 완료')


def main():
    if '--push-only' in sys.argv:
        push_only()
        return
    print(f'[{now_str()}] 데이터 수집 시작 — {P["label"]}')
    apply_notify_reset()   # NOTIFY_RESET 스위치 — 특보 알림 상태 복구(1회)
    # 이전 data.js — hrfco 실패 시 폴백용
    prev = load_previous_data()
    data = {
        'updated': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'regions': [], 'warnings': [], 'rivers': [],
        'messages': [], 'forecast': [], 'pm': [], 'fire': [],
        'bulletins': {'warnings_full': [], 'info_list': []},
        'fire_stats': {'incidents_year': [], 'summary': None},
    }

    # AWS 실측 강수 (관서별 공식 누적) — 1회 호출로 전 관서 배분.
    # 실패해도 다른 수집은 계속. 이전 값 보존(호우 중 '자료 사라짐' 방지).
    print('[AWS 실측 강수]')
    try:
        data['aws'] = fetch_aws_rain()
        _ok = sum(1 for v in data['aws'].values() if v.get('ok'))
        print(f'  ✓ AWS {_ok}/{len(data["aws"])}개 관서 수신')
    except Exception as e:
        data['aws'] = prev.get('aws') or {}
        print(f'  ✗ AWS 실패: {type(e).__name__} → 이전 값 보존({len(data["aws"])}개)')

    # 초단기예보 — 앞으로 6시간 강수 예측 (1시간에 1회만 실제 호출, 그 외엔 캐시)
    print('[6시간 강수예측]')
    try:
        data['ultra_fcst'] = fetch_ultra_short_fcst_all()
        print(f'  ✓ 6시간 예측 {len(data["ultra_fcst"])}개 관서')
    except Exception as e:
        data['ultra_fcst'] = prev.get('ultra_fcst') or {}
        print(f'  ✗ 6시간 예측 실패: {type(e).__name__} → 이전 값 보존')

    # 태풍 — 진행 중인 것만. 1년의 대부분은 [](정상)이라 실패와 구분해서 다룬다.
    print('[태풍]')
    try:
        data['typhoon'] = fetch_typhoon()
        if data['typhoon']:
            _t = data['typhoon'][0]
            print(f'  ✓ 진행중 {len(data["typhoon"])}개 — {_t["seq"]}호 {_t["name"]} ({_t["eff_txt"]})')
        else:
            print('  · 진행 중인 태풍 없음')
    except Exception as e:
        # 실패 시 이전 값을 쓰면 '끝난 태풍'이 계속 떠 있게 된다 → 빈 값이 안전
        data['typhoon'] = []
        print(f'  ✗ 태풍 수집 실패: {type(e).__name__} → 표시 안 함')

    # 물때(조석) — 파주 임진강 하구. 강화대교 예보 +2h = 두포리. 하루 1회 실호출(날짜캐시).
    print('[물때(조석)]')
    if not P.get('tide'):
        data['tide'] = None
        print('  · 이 지역은 해당 없음 — 건너뜀')
    else:
        try:
            _tide = fetch_tide()
            if _tide and _tide.get('events'):
                data['tide'] = _tide
                _hi = [e['dupo'] for e in _tide['events'] if e['kind'] == 'high']
                print(f'  ✓ 두포리 만조 {", ".join(_hi) or "-"} · 조차 {_tide["amp_cm"]}cm({_tide["spring"]})')
            else:
                data['tide'] = prev.get('tide') or None
                print('  · 조석 데이터 없음 → 이전 값 보존')
        except Exception as e:
            data['tide'] = prev.get('tide') or None
            print(f'  ✗ 물때 실패: {type(e).__name__} → 이전 값 보존')

    print('[시군별 현재 기상]')
    data['regions'] = fetch_all_regions(data.get('aws') or {})
    # 개별 시군이 forecast+실황 모두 실패하면 weather='?'로 남음 → 이전 정상값 보존
    prev_regions = {r.get('name'): r for r in (prev.get('regions') or [])}
    for i, r in enumerate(data['regions']):
        if r.get('weather') in ('?', None, ''):
            pr = prev_regions.get(r.get('name'))
            if pr and pr.get('weather') not in ('?', None, ''):
                data['regions'][i] = pr
                print(f'  · {r.get("name")} 수집 실패 → 이전 값 보존')

    # 실효습도 — 최근 며칠 일별최저습도 가중합(산불·화재 위험). 이력이 쌓일수록 정확.
    try:
        apply_effective_humidity(data['regions'])
    except Exception as e:
        print(f'  · 실효습도 계산 건너뜀: {type(e).__name__}')

    print(f'[시간대별 예보 - {P["home"]}]')
    try:
        fc = fetch_hourly_forecast()
        # 예보 수집 실패 시 빈 배열로 덮지 않음 — 화면이 가짜 샘플(폭우)로 대체되는 것 방지
        if not fc and prev.get('forecast'):
            data['forecast'] = prev['forecast']
            print(f'  · 예보 수집 실패 — 이전 {len(data["forecast"])}시간치 보존')
        else:
            data['forecast'] = fc
            print(f'  ✓ {len(data["forecast"])}시간치')
    except Exception as e:
        print(f'  ✗ {e}')
        data['forecast'] = prev.get('forecast', [])

    warn_ok = False
    print('[기상특보]')
    try:
        w_result = fetch_warnings()
        # 하위호환을 위해 data['warnings']는 발효 특보 배열(기존 형식) 유지
        data['warnings'] = w_result['active']
        # 예비특보는 별도 키로 저장
        data['prelim_warnings'] = w_result['prelim']
        warn_ok = True
        print(f'  ✓ 발효 {len(data["warnings"])}건 / 예비 {len(data["prelim_warnings"])}그룹')
    except Exception as e:
        print(f'  ✗ {e}'); traceback.print_exc()
        # 수집 실패 — 이전 값 보존 (특보 해제→재발효 오알림 방지)
        data['warnings'] = prev.get('warnings', [])
        data['prelim_warnings'] = prev.get('prelim_warnings', [])
        if data['warnings'] or data['prelim_warnings']:
            print(f'  · 이전 특보 {len(data["warnings"])}건/예비 '
                  f'{len(data["prelim_warnings"])}그룹 보존')

    apihub_ok = False
    print('[기상청 API허브 특보자료]')
    try:
        aw = fetch_apihub_warnings()   # 실패 시 None, 성공 시 list(정상 0건이면 [])
        apihub_ok = aw is not None     # 특보 알림 핑퐁 방지 — 허브 성공 시에만 알림 판정
        # 수집 실패(None)일 때만 이전 값 보존 — 정상 0건([])은 그대로 저장해 특보 해제 반영
        if aw is None and prev.get('apihub_warnings'):
            data['apihub_warnings'] = prev['apihub_warnings']
            print(f'  · 허브 수집 실패 — 이전 {len(data["apihub_warnings"])}건 보존')
        else:
            data['apihub_warnings'] = aw or []
            gg_n = sum(1 for w in data['apihub_warnings'] if w.get('is_gyeonggi'))
            north_n = sum(1 for w in data['apihub_warnings'] if w.get('is_north_gg'))
            prelim_n = sum(1 for w in data['apihub_warnings'] if w.get('is_prelim'))
            print(f'  ✓ 전체 {len(data["apihub_warnings"])}건 (경기 {gg_n}건 · {P["label"]} {north_n}건 · 예비 {prelim_n}건)')
    except Exception as e:
        print(f'  ✗ {e}')
        data['apihub_warnings'] = prev.get('apihub_warnings', [])

    print('[기상청 이미지 (특보 발효도·강수예측·레이더·위성)]')
    _shared = P.get('share_images_from')
    if _shared:
        # 레이더·위성·특보발효도는 전국 공통 이미지다. 다른 지역 회차가 이미 받아
        # images/ 에 저장해 뒀으므로 그 메타데이터만 가져다 쓴다(중복 다운로드 방지).
        data['kma_images'] = (load_previous_data(ROOT / _shared).get('kma_images')
                              or prev.get('kma_images') or {})
        print(f'  · 전국 공통 이미지 — {_shared} 것을 그대로 사용'
              f' ({len(data["kma_images"])}종)')
    else:
        try:
            data['kma_images'] = download_kma_images()
            # 이미지가 ok=False면 이전 정상 메타데이터 보존
            # (GitHub Actions가 받은 에러 이미지가 사장님 PC의 정상 이미지 표시를 막지 않게)
            prev_imgs = prev.get('kma_images') or {}
            for key in ('wrn', 'qpf', 'radar', 'satellite'):
                cur = data['kma_images'].get(key, {})
                prev_meta = prev_imgs.get(key, {})
                if not cur.get('ok') and prev_meta.get('ok'):
                    # 키가 아예 없으면 '아직 갱신 주기가 아님'(위성은 30분 주기),
                    # 키는 있는데 ok=False면 진짜 수집 실패. 로그에서 구분해야
                    # 나중에 로그만 보고 장애로 오해하지 않는다.
                    why = '갱신 주기 아님' if not cur else '수집 실패'
                    data['kma_images'][key] = prev_meta
                    print(f'  · {key}: {why} → 이전 이미지·메타 유지')
            wrn_ok = data['kma_images'].get('wrn', {}).get('ok')
            qpf_ok = data['kma_images'].get('qpf', {}).get('ok')
            radar_ok = data['kma_images'].get('radar', {}).get('ok')
            sat_ok = data['kma_images'].get('satellite', {}).get('ok')
            print(f'  특보발효도:{"✓" if wrn_ok else "✗"}  강수예측:{"✓" if qpf_ok else "✗"}  레이더:{"✓" if radar_ok else "✗"}  위성:{"✓" if sat_ok else "✗"}')
        except Exception as e:
            print(f'  ✗ {e}')
            data['kma_images'] = prev.get('kma_images') or {}

    print('[기상청 통보문·기상정보]')
    try:
        b = fetch_warning_bulletins()
        # 일시 장애 시 빈 dict 반환(예외 안 남) → 이전 값 보존(통보문/기상정보 깜빡임 방지)
        if not b.get('warnings_full') and not b.get('info_list') and prev.get('bulletins', {}).get('warnings_full'):
            data['bulletins'] = prev['bulletins']
            print('  · 통보문 수집 실패 — 이전 값 보존')
        else:
            data['bulletins'] = b
            print(f'  ✓ 통보문 {len(b["warnings_full"])}건 / 기상정보 {len(b["info_list"])}건')
    except Exception as e:
        print(f'  ✗ {e}')
        data['bulletins'] = prev.get('bulletins', {'warnings_full': [], 'info_list': []})

    print('[중기전망(날씨해설)]')
    try:
        mid = fetch_mid_forecast()
        if mid:
            data['mid_forecast'] = mid
            print(f'  ✓ {len(mid["content"])}자 ({mid["tmFc_display"]} 발표)')
        elif prev.get('mid_forecast'):
            # 권한 미적용·일시 실패 시 이전 값 보존
            data['mid_forecast'] = prev['mid_forecast']
            print('  · 이번 회차 실패 — 이전 날씨해설 보존')
        else:
            print('  · 데이터 없음 (중기예보 권한 적용 대기 중)')
    except Exception as e:
        print(f'  ✗ {e}')
        if prev.get('mid_forecast'):
            data['mid_forecast'] = prev['mid_forecast']

    print('[미세먼지]')
    try:
        pm = fetch_pm()
        if not pm and prev.get('pm'):
            data['pm'] = prev['pm']
            print(f'  · 미세먼지 수집 실패 — 이전 {len(data["pm"])}개 보존')
        else:
            data['pm'] = pm
            print(f'  ✓ {len(data["pm"])}개 측정소')
    except Exception as e:
        print(f'  ✗ {e}')
        data['pm'] = prev.get('pm', [])

    print('[산불 위험도]')
    try:
        fire = fetch_fire()
        if not fire and prev.get('fire'):
            data['fire'] = prev['fire']
            print(f'  · 산불위험 수집 실패 — 이전 {len(data["fire"])}개 권역 보존')
        else:
            data['fire'] = fire
            print(f'  ✓ {len(data["fire"])}개 권역')
    except Exception as e:
        print(f'  ✗ {e}')
        data['fire'] = prev.get('fire', [])

    print('[산불 발생 통계]')
    try:
        fs = fetch_fire_incidents()
        # summary가 None(HTTP 오류 등)이면 이전 값 보존
        if not fs.get('summary') and prev.get('fire_stats', {}).get('summary'):
            data['fire_stats'] = prev['fire_stats']
            print('  · 산불통계 수집 실패 — 이전 값 보존')
        else:
            data['fire_stats'] = fs
            sm = fs.get('summary') or {}
            print(f'  ✓ 올해 전국 {sm.get("this_year_total", 0)}건 / {P["label"]} {sm.get("this_year_north", 0)}건')
    except Exception as e:
        print(f'  ✗ {e}')
        data['fire_stats'] = prev.get('fire_stats', {'incidents_year': [], 'summary': None})

    print('[하천 수위]')
    try:
        rivers = fetch_rivers()
        # GitHub Actions(외국 IP)에서 hrfco 차단 시 — 이전 data.js 값 보존
        if not rivers and prev.get('rivers'):
            data['rivers'] = prev['rivers']
            print(f'  · hrfco 실패 — 이전 {len(data["rivers"])}개 관측소 데이터 보존 (사장님 PC 갱신 시 최신화)')
        else:
            data['rivers'] = rivers
            print(f'  ✓ {len(data["rivers"])}개 관측소')
    except Exception as e:
        print(f'  ✗ {e}')
        # 예외 시에도 이전 데이터 보존
        if prev.get('rivers'):
            data['rivers'] = prev['rivers']

    print('[홍수예보]')
    try:
        flood = fetch_flood_forecast()
        # hrfco 차단 시 빈 리스트 반환 — 평상시는 원래 빈 게 정상이라
        # 이전 값이 비어있지 않을 때만(즉 실제 발령 중일 때만) 보존
        if not flood and prev.get('flood_forecast'):
            data['flood_forecast'] = prev['flood_forecast']
            print(f'  · hrfco 실패 — 이전 홍수예보 {len(data["flood_forecast"])}건 보존')
        else:
            data['flood_forecast'] = flood
            north_n = sum(1 for f in flood if f.get('north_match'))
            print(f'  ✓ 전국 {len(flood)}건 ({P["label"]} 매칭 {north_n}건)')
    except Exception as e:
        print(f'  ✗ {e}')
        data['flood_forecast'] = prev.get('flood_forecast', [])

    print('[재난문자]')
    fetched_msgs = None
    try:
        fetched_msgs = fetch_messages()   # 실패 시 None, 정상 시 list(빈 것 포함)
    except Exception as e:
        print(f'  ✗ {e}')
    if fetched_msgs is None:
        # 수집 실패 — 이전 목록 보존 (재발송·화면 깜빡임 방지)
        data['messages'] = prev.get('messages', [])
        print(f'  · 수집 실패 — 이전 {len(data["messages"])}건 보존')
    else:
        data['messages'] = fetched_msgs
        print(f'  ✓ {len(fetched_msgs)}건')

    # 화면(normalizeWarningsFromApihub)과 동일하게 허브 특보를 warnings/prelim에 병합.
    try:
        merge_apihub_warnings(data)
    except Exception as e:
        print(f'  · 허브 특보 병합 오류: {e}')

    # 급변 감지 → 텔레그램 알림 (봇 미설정 시 자동 skip)
    print('[텔레그램 급변 알림]')
    if NO_NOTIFY:
        print('  · 이 회차는 알림 대상 아님 — 건너뜀')
    else:
        try:
            subs = sync_telegram_subscribers()   # 새 /start·/stop 반영 후
            # 특보 알림 — getPwnStatus·허브 모두 성공(완전 목록)일 때만 → 1분 알리미와 일관(핑퐁 방지)
            if warn_ok and apihub_ok:
                notify_warnings(data.get('warnings'), data.get('prelim_warnings'))  # ①②특보(공유상태)
            notify_rivers(data.get('rivers'))    # ③하천 수위 주의/위험(공유상태, 1분 알리미 백업)
            detect_and_notify(prev, data)        # ③-2 댐방류 ④재난문자
            if subs:
                print(f'  · 구독자 {len(subs)}명')
        except Exception as e:
            print(f'  ✗ {e}')

    save_data(data)
    save_combined_html(data)
    print(f'[{now_str()}] ✓ {P["data_file"]} + {P["combined_file"]} 저장 완료')

    if NO_PUSH:
        # 여러 지역을 연달아 돌릴 때 앞 회차는 저장만 하고, 마지막 회차가 한꺼번에
        # 커밋·푸시한다(git add -A 라 다른 지역 파일도 같이 올라간다).
        print('[GitHub 푸시] · --no-push — 저장만 하고 건너뜀')
    else:
        print('[GitHub 푸시]')
        git_push_data()
        maybe_deploy(data)   # 적응형 배포(이슈 즉시·특보중 20분·평소 40분) — Actions 무료시간 절약
    print(f'[{now_str()}] 전체 작업 완료 ({P["label"]})')


if __name__ == '__main__':
    main()
