# -*- coding: utf-8 -*-
"""경기북부 기상·재난 상황판 데이터 수집기.

기상청·환경공단·산림청·한강홍수통제소·행안부 공공 API를 호출해
프로젝트 루트의 data.js 파일을 갱신한다. index.html이 이 파일을 읽음.
실행: python tools/update_data.py
"""
import json
import subprocess
import sys
import time
import traceback
from datetime import datetime, timedelta
from pathlib import Path

import requests

# Windows 콘솔 한글 출력
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT / '.env'
OUTPUT_PATH = ROOT / 'data.js'
TEMPLATE_PATH = ROOT / 'index.html'
COMBINED_OUTPUT_PATH = ROOT / '상황판.html'


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
    for key in ('DATA_GO_KR_KEY', 'HRFCO_KEY', 'SAFETY_DATA_KEY'):
        env.setdefault(key, os.environ.get(key, ''))
    return env


ENV = load_env()
DATA_KEY = ENV.get('DATA_GO_KR_KEY', '')
HRFCO_KEY = ENV.get('HRFCO_KEY', '')
SAFETY_KEY = ENV.get('SAFETY_DATA_KEY', '')

# 경기북부 10개 시군 + 기상청 격자좌표(nx,ny) + 산불위험 시군구코드
REGIONS = [
    {'name': '의정부', 'nx': 61, 'ny': 130, 'sgg': '4115000000'},
    {'name': '양주',   'nx': 61, 'ny': 131, 'sgg': '4163000000'},
    {'name': '동두천', 'nx': 61, 'ny': 134, 'sgg': '4125000000'},
    {'name': '포천',   'nx': 64, 'ny': 133, 'sgg': '4165000000'},
    {'name': '연천',   'nx': 61, 'ny': 138, 'sgg': '4180000000'},
    {'name': '가평',   'nx': 73, 'ny': 133, 'sgg': '4182000000'},
    {'name': '남양주', 'nx': 64, 'ny': 128, 'sgg': '4136000000'},
    {'name': '구리',   'nx': 62, 'ny': 127, 'sgg': '4131000000'},
    {'name': '파주',   'nx': 56, 'ny': 131, 'sgg': '4148000000'},
    {'name': '고양',   'nx': 57, 'ny': 128, 'sgg': '4128000000'},
]

# 미세먼지 측정소: 시군 → 대표 측정소명 매핑 (에어코리아 실제 등록명 기준)
PM_STATIONS = {
    '의정부': '의정부동',   '양주': '백석읍',     '동두천': '보산동',
    '포천': '이동읍',       '연천': '연천',       '가평': '가평',
    '남양주': '와부읍',     '구리': '교문동',     '파주': '운정',
    '고양': '행신동',
}


def now_str():
    return datetime.now().strftime('%H:%M:%S')


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
    """PCP(1시간 강수량) 문자열을 mm 숫자로."""
    if not val or val in ('강수없음', '-', 'null'):
        return 0
    val = str(val).replace('mm', '').strip()
    if val.startswith('30.0~50.0'): return 40
    if val.startswith('50.0'): return 60
    if val == '1mm 미만': return 0.5
    try:
        return float(val)
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


def fetch_one_region_forecast(region):
    base_date, base_time = fcst_base_time()
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

        weather_text = pty_map.get(pty) if pty != '0' else sky_map.get(sky, '맑음')
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
    today = now.strftime('%Y%m%d')
    for it in items:
        if it['fcstDate'] != today: continue
        if it['category'] == 'TMX' and result['tmax'] is None:
            try: result['tmax'] = float(it['fcstValue'])
            except: pass
        elif it['category'] == 'TMN' and result['tmin'] is None:
            try: result['tmin'] = float(it['fcstValue'])
            except: pass

    # 강수형태 우선, 없으면 하늘상태
    pty_map = {'1': '비', '2': '비/눈', '3': '눈', '4': '소나기', '5': '빗방울', '6': '진눈깨비', '7': '눈날림'}
    sky_map = {'1': '맑음', '3': '구름많음', '4': '흐림'}
    if pty and pty != '0' and pty_map.get(pty):
        result['weather'] = pty_map[pty]
    elif sky and sky_map.get(sky):
        result['weather'] = sky_map[sky]

    # 위험도 판정: 강수량 기반
    if result['rain'] >= 20: result['level'] = 'danger'; result['tag'] = '경보'
    elif result['rain'] >= 10: result['level'] = 'warning'; result['tag'] = '호우'
    elif result['rain'] >= 3: result['level'] = 'warning'

    return result


def fetch_current_observation(region):
    """초단기실황 — 매 정시 발표, 발표 후 ~10분에 안정.
    실제 측정값(예보 아님): T1H 기온, RN1 1시간 강수, REH 습도, WSD 풍속, VEC 풍향, PTY 강수형태."""
    now = datetime.now()
    base = now - timedelta(minutes=40)  # 안전하게 40분 전
    base_date = base.strftime('%Y%m%d')
    base_time = base.strftime('%H00')

    url = 'https://apis.data.go.kr/1360000/VilageFcstInfoService_2.0/getUltraSrtNcst'
    params = {
        'serviceKey': DATA_KEY,
        'pageNo': 1, 'numOfRows': 30,
        'dataType': 'JSON',
        'base_date': base_date, 'base_time': base_time,
        'nx': region['nx'], 'ny': region['ny'],
    }
    r = requests.get(url, params=params, timeout=10)
    r.raise_for_status()
    items = r.json()['response']['body']['items']['item']

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


def update_rain_history(region_name, rn1):
    """시간별 강수 기록 누적 저장 및 1/3/6/12시간 누적 반환."""
    history_path = ROOT / '.tmp' / 'rain_history.json'
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


def fetch_all_regions():
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

        # 풍향 한글 + 체감온도
        obs = detail.get('observation', {})
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
        detail['tmax'] = item.get('tmax')
        detail['tmin'] = item.get('tmin')
        detail['pop'] = item.get('pop', 0)

        # 24시간 hourly를 detail로 옮김 (단기예보에서 추출한 것)
        detail['hourly'] = item.pop('_hourly', [])

        item['detail'] = detail
        regions.append(item)
    return regions


# ============================================================
# 2. 기상청 단기예보 - 시간대별 12시간 (동두천)
# ============================================================

def fetch_hourly_forecast(nx=61, ny=134, hours=12):
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
        if pty in ('1', '4'): icon = '🌧'
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

NORTH_GG_KEYWORDS = ['경기북부', '경기도', '수도권', '동두천', '양주', '의정부', '포천', '연천',
                     '가평', '남양주', '구리', '파주', '고양']


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

    # 최신순 정렬
    bulletins['warnings_full'].sort(key=lambda x: x['tmFc'], reverse=True)
    bulletins['info_list'].sort(key=lambda x: x['tmFc'], reverse=True)
    return bulletins


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
    body = r.json()['response']['body']
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
            matched = [k for k in NORTH_GG_KEYWORDS if k in body_text]
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
    if pm10 <= 30 and pm25 <= 15:
        return 'good', '좋음'
    if pm10 <= 80 and pm25 <= 35:
        return 'normal', '보통'
    if pm10 <= 150 and pm25 <= 75:
        return 'bad', '나쁨'
    return 'vbad', '매우나쁨'


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
            pm10 = int(float(it.get('pm10Value', 0) or 0))
            pm25 = int(float(it.get('pm25Value', 0) or 0))
            grade, grade_text = pm_grade(pm10, pm25)
            result.append({'region': region_name, 'pm10': pm10, 'pm25': pm25, 'grade': grade, 'gradeText': grade_text})
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
        north_sigun = {'의정부', '양주', '동두천', '포천', '연천', '가평',
                       '남양주', '구리', '파주', '고양'}
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

    # 경기북부 시군명 → 표시명 매핑 (고양시는 3개 구로 나오므로 다 매핑)
    sigun_map = {
        '의정부시': '의정부', '양주시': '양주',     '동두천시': '동두천',
        '포천시':  '포천',   '연천군': '연천',     '가평군':  '가평',
        '남양주시': '남양주', '구리시': '구리',     '파주시':  '파주',
        '고양시덕양구': '고양', '고양시일산동구': '고양', '고양시일산서구': '고양', '고양시': '고양',
    }

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

    groups = {
        '의정부·양주': ['의정부', '양주'],
        '동두천·연천': ['동두천', '연천'],
        '포천·가평':   ['포천', '가평'],
        '파주·고양':   ['파주', '고양'],
    }
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
RIVER_STATIONS = [
    {'code': '1022668', 'name': '신천 (동두천 송천교)',   'warning': 3.4,  'danger': 5.0,  'has_cctv': True,  'api': 'waterlevel'},
    {'code': '1021701', 'name': '임진강 (군남댐)',        'warning': 31.5, 'danger': 35.0, 'has_cctv': False, 'api': 'dam'},
    {'code': '1021650', 'name': '임진강 (연천 필승교)',   'warning': 1.0,  'danger': 7.5,  'has_cctv': False, 'api': 'waterlevel'},
    {'code': '1022670', 'name': '신천 (연천)',           'warning': 3.5,  'danger': 5.5,  'has_cctv': True,  'api': 'waterlevel'},
    {'code': '1021680', 'name': '임진강 (연천 임진교)',   'warning': 5.9,  'danger': 10.8, 'has_cctv': True,  'api': 'waterlevel'},
    {'code': '1022640', 'name': '한탄강 (포천 용담교)',   'warning': 9.5,  'danger': 18.0, 'has_cctv': True,  'api': 'waterlevel'},
    {'code': '1018638', 'name': '왕숙천 (남양주 왕숙교)', 'warning': 4.9,  'danger': 8.0,  'has_cctv': True,  'api': 'waterlevel'},
    {'code': '1018665', 'name': '중랑천 (의정부 신곡교)', 'warning': 2.6,  'danger': 6.0,  'has_cctv': True,  'api': 'waterlevel'},
]


def fetch_rivers():
    """관측소별 24시간 수위 시계열 수집.
    한강홍수통제소 API가 연결 끊김이 잦아서 GitHub Actions 환경 등에서 안정적으로 잡히도록:
    - 타임아웃 45초 (이전 20초)
    - 최대 6회 재시도 (이전 3회)
    - 시도 사이 점진 대기 (3, 4, 5, 6, 7초)
    - 관측소 사이 0.8초 텀 (서버 부담 완화)
    - 브라우저처럼 보이는 User-Agent 헤더
    """
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

    for st_idx, st in enumerate(RIVER_STATIONS):
        if st_idx > 0:
            time.sleep(0.8)  # 관측소 사이 텀

        last_err = None
        api = st.get('api', 'waterlevel')
        wl_field = 'swl' if api == 'dam' else 'wl'  # 댐은 저수위(swl), 하천은 수위(wl)

        for attempt in range(6):
            try:
                url = f'http://api.hrfco.go.kr/{HRFCO_KEY}/{api}/list/1H/{st["code"]}/{sdt}/{edt}.json'
                r = sess.get(url, timeout=45)
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
                if latest >= st['danger']:    level = 'danger'
                elif latest >= st['warning']: level = 'warning'
                else:                          level = 'safe'

                def delta(hours_ago):
                    if len(history) < hours_ago + 1: return None
                    return round(latest - history[-(hours_ago + 1)]['value'], 2)

                item = {
                    'name': st['name'],
                    'code': st['code'],
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
                result.append(item)
                break
            except Exception as e:
                last_err = e
                # 점진 대기: 3초, 4초, 5초, 6초, 7초
                time.sleep(3 + attempt)
        else:
            print(f'    하천 {st["name"]}: 6회 시도 모두 실패 — {last_err}')
    return result


# ============================================================
# 7. 재난문자 (행안부 — 키 발급 시 활성화)
# ============================================================

def fetch_flood_forecast():
    """한강홍수통제소 홍수예보 발령 정보.
    endpoint: http://api.hrfco.go.kr/{KEY}/fldfct/list.json
    응답: 최근 24시간 전체 관측소 발령 정보 (관측소 코드 미명시 시 전체).
    평상시는 code=990(자료없음)으로 빈 응답.

    응답 필드: ANCDT(발표일시), ANCNM(발표자), FCTDT(수위도달예상),
              KIND(주의보/경보), NO(번호), OBSNM(지점), RVRNM(강명),
              STTCURDT(현재일시), STTCURHGT(현재수위표수위), STTCURSEALVL(현재해발수위),
              STTNM(관측소코드), WRNARANM(주의지역).
    """
    if not HRFCO_KEY:
        return []
    url = f'http://api.hrfco.go.kr/{HRFCO_KEY}/fldfct/list.json'
    try:
        r = requests.get(url, timeout=15, headers={
            'User-Agent': 'Mozilla/5.0',
            'Accept': 'application/json',
        })
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        print(f'    홍수예보: {e}')
        return []

    code = str(data.get('code', ''))
    if code != '200':
        # 990 = 자료 없음 (평상시 정상), 그 외 코드는 오류
        return []
    items = data.get('links', []) or []

    # 경기북부 관련 키워드: 시군명 + 북부 흐르는 주요 강·하천
    north_keywords = {'의정부', '양주', '동두천', '포천', '연천', '가평',
                      '남양주', '구리', '파주', '고양',
                      '임진강', '한탄강', '신천', '왕숙천', '중랑천',
                      '경기북부', '경기'}

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

    north_sigun = ['동두천', '양주', '의정부', '포천', '연천',
                   '가평', '남양주', '구리', '파주', '고양']
    gun_names = {'연천', '가평'}

    def is_gyeonggi(rcptn):
        """경기도 전체 메시지만 통과 (서울·인천 등 제외)."""
        s = rcptn.strip()
        return s.startswith('경기도') or s.startswith('경기북부') or s.startswith('경기남부')

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
        return []

    import re as _re
    result = []
    for it in items:
        rcptn = str(it.get('RCPTN_RGN_NM', ''))
        if not is_gyeonggi(rcptn):
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
            'text': msg[:300],
            'region': region,
            '_sn': int(it.get('SN', 0)),
        })

    # SN 내림차순 (최신 발송 우선)
    result.sort(key=lambda x: x['_sn'], reverse=True)
    for r_ in result:
        r_.pop('_sn', None)

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
    실패해도 다음 회차에 재시도되므로 가벼운 try/except로 묶음."""
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
        # 4. push (PAT 자동 인증)
        push = subprocess.run(
            ['git', 'push'],
            cwd=str(ROOT), capture_output=True, text=True, timeout=60
        )
        if push.returncode == 0:
            print('  ✓ GitHub 푸시 완료')
        else:
            err = (push.stderr or push.stdout or '').strip()[:200]
            print(f'  ✗ GitHub 푸시 실패: {err}')
    except subprocess.TimeoutExpired:
        print('  ✗ GitHub 푸시 타임아웃 (다음 회차 재시도)')
    except FileNotFoundError:
        print('  ! git 명령 못 찾음 — Git for Windows 설치 필요')
    except Exception as e:
        print(f'  ✗ GitHub 푸시 오류: {e}')


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


def main():
    print(f'[{now_str()}] 데이터 수집 시작')
    data = {
        'updated': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'regions': [], 'warnings': [], 'rivers': [],
        'messages': [], 'forecast': [], 'pm': [], 'fire': [],
        'bulletins': {'warnings_full': [], 'info_list': []},
        'fire_stats': {'incidents_year': [], 'summary': None},
    }

    print('[시군별 현재 기상]')
    data['regions'] = fetch_all_regions()

    print('[시간대별 예보 - 동두천]')
    try:
        data['forecast'] = fetch_hourly_forecast()
        print(f'  ✓ {len(data["forecast"])}시간치')
    except Exception as e:
        print(f'  ✗ {e}')

    print('[기상특보]')
    try:
        w_result = fetch_warnings()
        # 하위호환을 위해 data['warnings']는 발효 특보 배열(기존 형식) 유지
        data['warnings'] = w_result['active']
        # 예비특보는 별도 키로 저장
        data['prelim_warnings'] = w_result['prelim']
        print(f'  ✓ 발효 {len(data["warnings"])}건 / 예비 {len(data["prelim_warnings"])}그룹')
    except Exception as e:
        print(f'  ✗ {e}'); traceback.print_exc()
        data['warnings'] = []
        data['prelim_warnings'] = []

    print('[기상청 통보문·기상정보]')
    try:
        data['bulletins'] = fetch_warning_bulletins()
        print(f'  ✓ 통보문 {len(data["bulletins"]["warnings_full"])}건 / 기상정보 {len(data["bulletins"]["info_list"])}건')
    except Exception as e:
        print(f'  ✗ {e}')

    print('[미세먼지]')
    try:
        data['pm'] = fetch_pm()
        print(f'  ✓ {len(data["pm"])}개 측정소')
    except Exception as e:
        print(f'  ✗ {e}')

    print('[산불 위험도]')
    try:
        data['fire'] = fetch_fire()
        print(f'  ✓ {len(data["fire"])}개 권역')
    except Exception as e:
        print(f'  ✗ {e}')

    print('[산불 발생 통계]')
    try:
        data['fire_stats'] = fetch_fire_incidents()
        sm = data['fire_stats'].get('summary') or {}
        print(f'  ✓ 올해 전국 {sm.get("total_year", 0)}건 / 경기북부 {sm.get("north_year", 0)}건')
    except Exception as e:
        print(f'  ✗ {e}')

    print('[하천 수위]')
    try:
        data['rivers'] = fetch_rivers()
        print(f'  ✓ {len(data["rivers"])}개 관측소')
    except Exception as e:
        print(f'  ✗ {e}')

    print('[홍수예보]')
    try:
        data['flood_forecast'] = fetch_flood_forecast()
        north_n = sum(1 for f in data['flood_forecast'] if f.get('north_match'))
        print(f'  ✓ 전국 {len(data["flood_forecast"])}건 (북부 매칭 {north_n}건)')
    except Exception as e:
        print(f'  ✗ {e}')
        data['flood_forecast'] = []

    print('[재난문자]')
    try:
        data['messages'] = fetch_messages()
        print(f'  ✓ {len(data["messages"])}건')
    except Exception as e:
        print(f'  ✗ {e}')

    save_data(data)
    save_combined_html(data)
    print(f'[{now_str()}] ✓ data.js + 상황판.html 저장 완료')

    print('[GitHub 푸시]')
    git_push_data()
    print(f'[{now_str()}] 전체 작업 완료')


if __name__ == '__main__':
    main()
