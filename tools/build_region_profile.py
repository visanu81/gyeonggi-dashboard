# -*- coding: utf-8 -*-
"""지역 프로파일 생성기 — 시군 목록만 주면 상황판에 필요한 지역 상수를 자동으로 만든다.

왜 있는가:
  경기북부 프로파일(REGIONS·AWS_STATIONS·RIVER_STATIONS·PM_STATIONS)은 손으로 모은
  값이라, 다른 지역(경기남부 등)을 추가할 때 같은 작업을 사람이 반복하면 반드시
  빠지거나 틀린다. 이 도구는 공공 API 원장에서 기계적으로 뽑아낸다.

무엇을 만드는가 (시군별):
  · nx/ny  기상청 동네예보 격자   ← 대표 관측소 좌표를 DFS 격자변환
  · sgg    산불위험 시군구코드    ← 법정동코드 5자리 + '00000'
  · AWS    방재기상관측소 목록    ← apihub stn_inf(inf=AWS)를 법정동코드로 매칭
  · 하천   수위관측소 + 기준수위  ← 한강홍수통제소 info (attwl=관심, almwl=경계)
  · 미세먼지 측정소              ← 에어코리아 시도별 실시간 측정소명

검증:
  --verify 로 실행하면 경기북부 운영값(update_data.py의 실제 상수)을 그대로
  재현하는지 대조한다. 재현되지 않으면 생성 로직을 믿을 수 없다는 뜻이므로
  남부 결과도 쓰면 안 된다.

실행:
  python tools/build_region_profile.py --verify          # 북부 재현 검증만
  python tools/build_region_profile.py --build south     # 남부 프로파일 출력
"""
import argparse
import json
import math
import re
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import requests

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / '.tmp'
LAW10 = re.compile(r'^\d{10}$')


def load_env():
    env = {}
    p = ROOT / '.env'
    if not p.exists():
        return env
    for line in p.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if line and not line.startswith('#') and '=' in line:
            k, v = line.split('=', 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env


ENV = load_env()

# ────────────────────────────────────────────────────────────────
# 시군 정의 — 법정동코드 4자리(시·군 단위). 구가 신설돼도(화성 만세구 41591)
# 4자리 접두사는 그대로라 자동으로 따라온다.
#   ※ 5자리로 하면 화성(41590)이 만세구(41591) 지점을 통째로 놓친다 — 실제로 겪음.
#   ※ 고양/일산만 예외: 한 시(4128)를 두 관서로 나누므로 5자리로 명시한다.
# ────────────────────────────────────────────────────────────────
NORTH_SIGUN = {
    '의정부': ['4115'], '양주': ['4163'], '동두천': ['4125'], '포천': ['4165'],
    '연천': ['4180'], '가평': ['4182'], '남양주': ['4136'], '구리': ['4131'],
    '파주': ['4148'], '고양': ['41280', '41281'], '일산': ['41285', '41287'],
}
SOUTH_SIGUN = {
    '수원': ['4111'], '성남': ['4113'], '안양': ['4117'], '부천': ['4119'],
    '광명': ['4121'], '평택': ['4122'], '안산': ['4127'], '과천': ['4129'],
    '오산': ['4137'], '시흥': ['4139'], '군포': ['4141'], '의왕': ['4143'],
    '하남': ['4145'], '용인': ['4146'], '이천': ['4150'], '안성': ['4155'],
    '김포': ['4157'], '화성': ['4159'], '광주': ['4161'], '여주': ['4167'],
    '양평': ['4183'],
}
# 시군 대표 AWS 지점명 — 지점명이 시군명과 다른 곳만 명시(나머지는 이름 일치로 자동)
REP_STATION_ALIAS = {
    '광주': '경기광주', '가평': '경기가평',
}

# ────────────────────────────────────────────────────────────────
# 기상청 DFS 격자 변환 (Lambert Conformal Conic)
# ────────────────────────────────────────────────────────────────
_RE, _GRID = 6371.00877, 5.0
_SLAT1, _SLAT2, _OLON, _OLAT, _XO, _YO = 30.0, 60.0, 126.0, 38.0, 43, 136
_DEG = math.pi / 180.0
_re_ = _RE / _GRID
_s1, _s2 = _SLAT1 * _DEG, _SLAT2 * _DEG
_ol, _oa = _OLON * _DEG, _OLAT * _DEG
_sn = math.log(math.cos(_s1) / math.cos(_s2)) / math.log(
    math.tan(math.pi * .25 + _s2 * .5) / math.tan(math.pi * .25 + _s1 * .5))
_sf = (math.tan(math.pi * .25 + _s1 * .5) ** _sn) * math.cos(_s1) / _sn
_ro = _re_ * _sf / (math.tan(math.pi * .25 + _oa * .5) ** _sn)


def to_grid(lat, lon):
    """위경도 → 기상청 동네예보 격자 (nx, ny)."""
    ra = _re_ * _sf / (math.tan(math.pi * .25 + lat * _DEG * .5) ** _sn)
    th = lon * _DEG - _ol
    if th > math.pi:
        th -= 2 * math.pi
    if th < -math.pi:
        th += 2 * math.pi
    th *= _sn
    return int(ra * math.sin(th) + _XO + .5), int(_ro - ra * math.cos(th) + _YO + .5)


def dms_to_deg(s):
    """한강홍수통제소 좌표 '127-08-53' → 127.148..."""
    p = [x for x in str(s).strip().split('-') if x != '']
    if len(p) < 2:
        return None
    try:
        d, m = float(p[0]), float(p[1])
        sec = float(p[2]) if len(p) > 2 else 0.0
    except ValueError:
        return None
    return round(d + m / 60 + sec / 3600, 6)


# ────────────────────────────────────────────────────────────────
# 원장 수집 (캐시)
# ────────────────────────────────────────────────────────────────
def _cached(name, fetch, refresh=False):
    p = CACHE / name
    if p.exists() and not refresh:
        return p.read_text(encoding='utf-8')
    CACHE.mkdir(exist_ok=True)
    text = fetch()
    p.write_text(text, encoding='utf-8')
    return text


def fetch_aws_inventory(refresh=False):
    """기상청 API허브 AWS 지점원장.

    ⚠ 파싱 함정: 고정폭이 아니고 지점명 뒤에 '*'가 붙는 지점이 있어 컬럼이 밀린다
    (477 상패, 485 신천에서 실제로 겪음 — 인덱스로 읽으면 두 지점이 통째로 누락).
    법정동코드는 '10자리 순수숫자' 토큰으로만 식별한다. 다른 컬럼엔 그런 값이 없다.
    """
    key = ENV.get('KMA_APIHUB_KEY', '')

    def _get():
        url = ('https://apihub.kma.go.kr/api/typ01/url/stn_inf.php'
               f'?inf=AWS&stn=&tm=&help=1&authKey={key}')
        r = requests.get(url, timeout=30)
        r.raise_for_status()
        r.encoding = 'euc-kr'
        return r.text

    out = []
    for line in _cached('stn_aws_inf.txt', _get, refresh).splitlines():
        s = line.strip()
        if not s or s.startswith('#'):
            continue
        f = s.split()
        if len(f) < 12:
            continue
        try:
            stn, lon, lat = int(f[0]), float(f[1]), float(f[2])
        except ValueError:
            continue
        li = next((i for i, v in enumerate(f) if LAW10.match(v)), None)
        if li is None:
            continue
        out.append({'stn': stn, 'lon': lon, 'lat': lat, 'name': f[8],
                    'law': f[li], 'addr': ' '.join(f[li + 2:])})
    return out


def fetch_river_inventory(refresh=False):
    """한강홍수통제소 수위관측소 원장 (기준수위 포함)."""
    key = ENV.get('HRFCO_KEY', '')

    def _get():
        r = requests.get(f'https://api.hrfco.go.kr/{key}/waterlevel/info.json',
                         timeout=30, headers={'User-Agent': 'Mozilla/5.0'})
        r.raise_for_status()
        return r.text

    return json.loads(_cached('hrfco_wl_info.json', _get, refresh)).get('content', [])


def fetch_dam_inventory(refresh=False):
    """한강홍수통제소 댐 원장 — 댐은 수위관측소 원장에 없어 따로 받아야 한다."""
    key = ENV.get('HRFCO_KEY', '')

    def _get():
        r = requests.get(f'https://api.hrfco.go.kr/{key}/dam/info.json',
                         timeout=30, headers={'User-Agent': 'Mozilla/5.0'})
        r.raise_for_status()
        return r.text

    return json.loads(_cached('hrfco_dam_info.json', _get, refresh)).get('content', [])


def fetch_pm_stations(refresh=False):
    """에어코리아 시도(경기) 실시간 측정소명 목록."""
    key = ENV.get('DATA_GO_KR_KEY', '')

    def _get():
        r = requests.get(
            'https://apis.data.go.kr/B552584/ArpltnInforInqireSvc/getCtprvnRltmMesureDnsty',
            params={'serviceKey': key, 'returnType': 'json', 'numOfRows': 500,
                    'pageNo': 1, 'sidoName': '경기', 'ver': '1.3'}, timeout=30)
        r.raise_for_status()
        return r.text

    js = json.loads(_cached('airkorea_gg.json', _get, refresh))
    return [it.get('stationName') for it in js['response']['body'].get('items', [])
            if it.get('stationName')]


# ────────────────────────────────────────────────────────────────
# 생성
# ────────────────────────────────────────────────────────────────
def match_law(rows, prefixes, field='law'):
    return sorted([r for r in rows if any(str(r[field]).startswith(p) for p in prefixes)],
                  key=lambda r: r['stn'])


def build_aws(sigun_map, inventory):
    return {area: match_law(inventory, pre) for area, pre in sigun_map.items()}


def build_regions(sigun_map, aws_by_area):
    """시군별 nx/ny + 산불 시군구코드.

    대표지점 = 시군명과 같은 이름의 AWS 지점(예: '수원', '평택'). 관할 안의 실제
    관측지점이라 예보격자로도 타당하다. 동명 지점이 없으면 관측소 좌표 평균.
    """
    out = []
    for area, prefixes in sigun_map.items():
        st = aws_by_area.get(area) or []
        want = REP_STATION_ALIAS.get(area, area)
        rep = next((r for r in st if r['name'] == want), None)
        if rep:
            lat, lon, src = rep['lat'], rep['lon'], f"AWS {rep['stn']} {rep['name']}"
        elif st:
            lat = sum(r['lat'] for r in st) / len(st)
            lon = sum(r['lon'] for r in st) / len(st)
            src = f'관측소 {len(st)}곳 평균'
        else:
            out.append({'name': area, 'nx': None, 'ny': None,
                        'sgg': prefixes[0][:5].ljust(5, '0') + '00000', 'src': '없음'})
            continue
        nx, ny = to_grid(lat, lon)
        out.append({'name': area, 'nx': nx, 'ny': ny,
                    'sgg': prefixes[0][:5].ljust(5, '0') + '00000',
                    'src': src, 'lat': round(lat, 5), 'lon': round(lon, 5)})
    return out


def build_rivers(sigun_map, inventory, per_sigun=3):
    """시군별 수위관측소. warning=attwl(관심), danger=almwl(경계) — 임의값 아님.

    선정 기준: ①홍수예보지점(fstnyn=Y) 우선 ②기준수위 둘 다 있는 곳
    ③시군당 최대 per_sigun개. 관측소를 다 넣으면 5분 주기 수집이 감당 못 한다.

    ⚠ addr(주소)로 매칭하면 안 된다. 정부 원장에 오타가 있다 —
      1018690 안양시(충훈1교)의 addr은 '경기도 얀양시'라서 '안양'으로 못 찾는다.
      관측소명(obsnm)은 '안양시(충훈1교)' 형태로 정확하므로 이쪽을 기준으로 삼고,
      addr은 '경기'가 들어가는지 정도만(광주광역시 배제) 본다.
      obsnm을 '앞에서부터' 맞추므로 '양주시('가 '남양주시('에 걸리지도 않는다.
    """
    out = {}
    for area in sigun_map:
        cands = []
        for c in inventory:
            obsnm = (c.get('obsnm') or '').strip()
            if not (obsnm.startswith(f'{area}시(') or obsnm.startswith(f'{area}군(')):
                continue
            if '경기' not in (c.get('addr') or '') + obsnm:
                continue
            att, alm = c.get('attwl'), c.get('almwl')
            try:
                att = float(att) if att not in ('', None) else None
                alm = float(alm) if alm not in ('', None) else None
            except ValueError:
                att = alm = None
            if att is None or alm is None:
                continue
            if c['wlobscd'] in RIVER_EXCLUDE:
                continue
            cands.append({
                'code': c['wlobscd'], 'obsnm': c.get('obsnm', ''),
                'warning': att, 'danger': alm,
                'fcst': (c.get('fstnyn') or '') == 'Y',
                'lat': dms_to_deg(c.get('lat')), 'lon': dms_to_deg(c.get('lon')),
                'addr': c.get('addr', ''), 'etc': c.get('etcaddr', ''),
            })
        cands.sort(key=lambda x: (not x['fcst'], x['code']))
        out[area] = cands[:per_sigun]
    return out


# 기준수위가 평상시 수위보다 낮아 '항상 주의'로 뜨는 관측소 — 넣으면 안 된다.
# 매일 경보가 떠 있으면 사람이 경보를 무시하게 되고, 진짜 호우 때 안 보게 된다.
# --check-rivers 로 찾아낸 것만 근거와 함께 적는다.
RIVER_EXCLUDE = {
    '1019661': '김포 사우교 — 한강 하구 조위 영향. 관심수위 1.0m인데 평상시 0.98~1.15m로'
               ' 하루 21시간이 초과 상태. 김포는 전류리(관심 4.1m)로 대신한다.',
}


def _km(lat1, lon1, lat2, lon2):
    return math.hypot((lat1 - lat2) * 111.0, (lon1 - lon2) * 88.0)


def check_rivers(stations, key, hours=24):
    """선정된 관측소가 '평상시에도 관심수위를 넘는지' 실제 24시간 자료로 검사.

    기준수위는 지자체가 정한 값이라 관측소 이설·하상 변동 뒤 갱신이 안 된 곳이 있다.
    그런 곳을 그냥 넣으면 상황판에 매일 주의가 떠 있게 된다 — 경보 피로.
    """
    now = datetime.now()
    sdt = (now - timedelta(hours=hours)).strftime('%Y%m%d%H')
    edt = now.strftime('%Y%m%d%H')
    sess = requests.Session()
    sess.headers.update({'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json'})
    suspect = []
    for st in stations:
        try:
            r = sess.get(f'https://api.hrfco.go.kr/{key}/waterlevel/list/1H/'
                         f'{st["code"]}/{sdt}/{edt}.json', timeout=12)
            r.raise_for_status()
            vals = []
            for e in r.json().get('content', []):
                try:
                    vals.append(float(e.get('wl')))
                except (TypeError, ValueError):
                    pass
        except Exception as e:
            print(f'  ? {st["obsnm"]:24s} 조회 실패 {type(e).__name__}')
            continue
        if not vals:
            print(f'  ? {st["obsnm"]:24s} 자료 없음 — 관측 중단 의심')
            continue
        over = sum(1 for v in vals if v >= st['warning'])
        mark = ' '
        if over > len(vals) * 0.5:
            suspect.append((st, over, len(vals), min(vals), max(vals)))
            mark = '!'
        print(f'  {mark} {st["obsnm"]:24s} 최근{len(vals)}시간 {min(vals)}~{max(vals)}m'
              f' / 관심 {st["warning"]}m · 초과 {over}시간')
    return suspect


def add_nearby_rivers(rivers, regions, inventory, radius_km=12.0):
    """자체 관측소가 없는 시군에 '인근' 관측소를 붙인다.

    과천·시흥·군포·의왕·하남은 관내에 한강홍수통제소 수위관측소가 아예 없다.
    그렇다고 비워두면 호우 때 그 관서만 하천 정보가 통째로 없다. 반경 안의 가장
    가까운 경기도 관측소를 붙이되 nearby=True로 표시해, 화면에서 '관할 하천'이
    아니라 '인근'임이 드러나게 한다 (다른 시 하천을 자기 관할로 오인하면 안 된다).
    """
    pos = {r['name']: (r.get('lat'), r.get('lon')) for r in regions}
    for area, st in rivers.items():
        if st:
            continue
        la, lo = pos.get(area, (None, None))
        if la is None:
            continue
        best = None
        for c in inventory:
            if '경기' not in (c.get('addr') or ''):
                continue
            y, x = dms_to_deg(c.get('lat')), dms_to_deg(c.get('lon'))
            if y is None or x is None:
                continue
            try:
                att, alm = float(c.get('attwl')), float(c.get('almwl'))
            except (TypeError, ValueError):
                continue
            d = _km(la, lo, y, x)
            if d <= radius_km and (best is None or d < best[0]):
                best = (d, c, att, alm)
        if best:
            d, c, att, alm = best
            rivers[area] = [{
                'code': c['wlobscd'], 'obsnm': c.get('obsnm', ''),
                'warning': att, 'danger': alm,
                'fcst': (c.get('fstnyn') or '') == 'Y', 'nearby': True,
                'dist_km': round(d, 1),
                'lat': dms_to_deg(c.get('lat')), 'lon': dms_to_deg(c.get('lon')),
                'addr': c.get('addr', ''), 'etc': c.get('etcaddr', ''),
            }]
    return rivers


# 시군 대표 미세먼지 측정소 (에어코리아 등록명).
#
# 왜 자동이 아닌가: 에어코리아 실시간 API 응답에는 시도(경기)까지만 있고 시군 정보가
# 없다. 시군까지 알려주는 '측정소정보 서비스(MsrstnInfoInqireSvc)'는 별도 활용신청이
# 필요해 현재 키로는 403이다. 그래서 대표 측정소는 표로 두되, 아래 build_pm()이
# '그 이름이 경기 실시간 목록에 실제로 존재하는지'를 매번 대조해 오타·폐소를 잡는다.
# → 활용신청이 승인되면 이 표 없이 주소로 자동 매핑할 수 있다(fetch_pm_stations 확장).
PM_STATION_TABLE = {
    'north': {
        '의정부': '의정부동', '양주': '백석읍', '동두천': '보산동', '포천': '이동읍',
        '연천': '연천', '가평': '가평', '남양주': '와부읍', '구리': '교문동',
        '파주': '운정', '고양': '행신동',
    },
    'south': {
        '수원': '신풍동', '성남': '성남대로(모란역)', '안양': '안양2동',
        '부천': '송내대로(중동)', '광명': '철산동', '평택': '비전동', '안산': '고잔동',
        '과천': '과천동', '오산': '오산동', '시흥': '정왕동', '군포': '산본동',
        '의왕': '고천동', '하남': '신장동', '용인': '김량장동', '이천': '부발읍',
        '안성': '공도읍', '김포': '사우동', '화성': '남양읍', '광주': '경안동',
        '여주': '가남읍', '양평': '양평읍',
    },
}


WAMIS_OBS = 'http://www.wamis.go.kr:8080/wamis/openapi/wkw/wl_obsinfo?obscd={}&output=json'


def river_name(code, sess=None):
    """관측소가 있는 하천 이름 — WAMIS(국가수자원관리종합정보시스템) 관측소 제원.

    한강홍수통제소 원장엔 하천명 필드가 없다(수계 엔드포인트도 값이 비어 온다).
    WAMIS의 wl_obsinfo 에 rivnm 이 있고 관측소 코드가 홍수통제소와 같아 그대로 붙는다.
    경기북부 운영 표기(왕숙천·중랑천·임진강·한탄강)와 12/12 일치, 불일치 0을 확인했다.

    ⚠ 유역면적이 작은데 rivnm이 '한강'으로 오는 지점이 있다(용인 월촌교 149km²).
      지류인데 본류 이름이 붙어 화면에서 한강 본류로 오해할 수 있으므로 버린다.
      진짜 본류(여주대교·양평교·전류리·팔당대교)는 유역이 1만km² 이상이라 남는다.
    """
    # ⚠ WAMIS는 연달아 부르면 간헐적으로 연결을 끊는다(35개소 중 5곳이 조용히 실패했다).
    #   재시도 없이 두면 '하천명 없음'과 구분이 안 돼 이름이 빠진 채로 굳는다.
    sess = sess or requests
    d = None
    for attempt in range(3):
        try:
            j = sess.get(WAMIS_OBS.format(code), timeout=25).json()
            d = (j.get('list') or [{}])[0]
            break
        except Exception:
            time.sleep(1.0 + attempt)
    if d is None:
        return None
    try:
        nm = (d.get('rivnm') or '').strip()
        if not nm:
            return None
        if nm in ('한강', '낙동강', '금강', '영산강', '섬진강'):
            try:
                if float(d.get('bsnara') or 0) < 1000:
                    return None      # 본류 이름이 붙은 지류 — 오해 소지
            except (TypeError, ValueError):
                return None
        return nm
    except Exception:
        return None


CCTV_URL = 'https://n.flood.go.kr/main/cctvView.do?obscd={}&fcodvcd=01'
_LURL = re.compile(r'var\s+lurl\s*=\s*"([^"]*)"')
_HURL = re.compile(r'var\s+hurl\s*=\s*"([^"]*)"')


def has_cctv(code, sess=None):
    """그 관측소에 실시간 CCTV가 있는지.

    한강홍수통제소에 CCTV 목록 API가 없어서, 화면이 쓰는 CCTV 페이지를 직접 열어 본다.
    페이지는 어느 지점이든 똑같이 나오지만 안에 박히는 채널번호(lurl/hurl)가
    CCTV 없는 지점에선 빈 문자열로 온다 — 이게 유일하게 믿을 수 있는 구분점이다.
    (경기북부 18개소의 손으로 정한 값을 18/18 그대로 재현함을 확인)
    """
    sess = sess or requests
    try:
        r = sess.get(CCTV_URL.format(code), timeout=20)
        if r.status_code != 200:
            return False
        l = _LURL.search(r.text)
        h = _HURL.search(r.text)
        return bool((l and l.group(1)) or (h and h.group(1)))
    except Exception:
        return False


def build_river_meta(codes, inventory, dam_inv=None, with_cctv=True):
    """하천 상세용 정보 — 홍수 4단계·계획홍수위·영점표고·관할기관·주소·CCTV.

    화면(지도.html)의 하천 상세는 이 값으로 '관심→주의→경계→심각' 4단계 눈금을 그린다.
    지금까지 경기북부 18개소만 손으로 박아 두어서 경기남부는 상세가 빈약했다.
    한강홍수통제소 원장에 이미 다 있는 값이라 기계로 뽑는다.
      att=관심(attwl) wrn=주의(wrnwl) alm=경계(almwl) srs=심각(srswl)
      pfh=계획홍수위  gdt=영점표고  fstn=홍수예보지점
    """
    # ⚠ 정부 원장에 빈 항목(null)이 섞여 온다 — 댐 원장 73건 중 16건이 null이었다.
    #   거르지 않으면 여기서 통째로 죽는다.
    by_code = {c['wlobscd']: c for c in inventory if c and c.get('wlobscd')}
    dams = {d['dmobscd']: d for d in (dam_inv or []) if d and d.get('dmobscd')}
    sess = requests.Session()
    sess.headers.update({'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})

    def num(v):
        try:
            f = float(str(v).strip())
            return int(f) if f == int(f) else f
        except (TypeError, ValueError):
            return None

    out = {}
    for code in codes:
        c = by_code.get(code)
        d = dams.get(code)
        if c is None and d is None:
            continue
        src = c or d
        m = {}
        if d is not None and c is None:
            m['kind'] = 'dam'
        if src.get('agcnm'):
            m['agc'] = src['agcnm']
        addr = ' '.join(x for x in (src.get('addr', ''), src.get('etcaddr', '')) if x).strip()
        if addr:
            m['addr'] = addr
        for key, fld in (('gdt', 'gdt'), ('att', 'attwl'), ('wrn', 'wrnwl'),
                         ('alm', 'almwl'), ('srs', 'srswl'), ('pfh', 'pfh')):
            v = num(src.get(fld))
            if v is not None:
                m[key] = v
        if c is not None:
            m['fstn'] = (c.get('fstnyn') or '') == 'Y'
        if with_cctv:
            m['cctv'] = has_cctv(code, sess)
            time.sleep(0.25)      # 홍수통제소에 몰아치지 않게
        out[code] = m
    return out


def build_pm(profile, names):
    """대표 측정소 표를 실시간 목록과 대조. 없는 이름은 떨궈서 화면에 빈칸이 뜨게 한다
    (엉뚱한 측정소로 대체하면 다른 시군 공기질을 그 시군 값으로 보여주게 된다)."""
    live = set(names)
    table = PM_STATION_TABLE.get(profile, {})
    ok = {a: s for a, s in table.items() if s in live}
    missing = {a: s for a, s in table.items() if s not in live}
    return ok, missing


def verify_north():
    """경기북부 운영값 재현 검증 — 통과해야 남부 결과를 신뢰할 수 있다."""
    CUR_AWS = {
        '연천': [343, 456, 478, 479, 480, 491, 538, 652, 692],
        '파주': [99, 309, 481, 482, 483, 503, 506, 567],
        '동두천': [98, 454, 477],
        '포천': [359, 360, 361, 452, 473, 474, 475, 476, 504, 507, 539, 568, 599],
        '양주': [351, 352, 372, 373, 375, 598],
        '가평': [455, 485, 486, 505, 531, 542], '일산': [589], '고양': [450, 540],
        '의정부': [431, 532], '남양주': [451, 484, 541], '구리': [368, 569],
    }
    CUR_SGG = {
        '의정부': '4115000000', '양주': '4163000000', '동두천': '4125000000',
        '포천': '4165000000', '연천': '4180000000', '가평': '4182000000',
        '남양주': '4136000000', '구리': '4131000000', '파주': '4148000000',
        '고양': '4128000000',
    }
    inv = fetch_aws_inventory()
    aws = build_aws(NORTH_SIGUN, inv)
    ok = True
    print('=== [1] AWS 관측소 매핑 재현 ===')
    for area, exp in CUR_AWS.items():
        got = [r['stn'] for r in aws.get(area, [])]
        same = got == exp
        ok &= same
        print(f'  {"O" if same else "X"} {area:4s} {len(got)}개소')
        if not same:
            print(f'      기대 {exp}\n      생성 {got}')

    print('=== [2] 산불 시군구코드 재현 ===')
    regs = {r['name']: r for r in build_regions(NORTH_SIGUN, aws)}
    for area, exp in CUR_SGG.items():
        got = regs[area]['sgg']
        same = got == exp
        ok &= same
        print(f'  {"O" if same else "X"} {area:4s} {got}')

    print('=== [3] 하천 기준수위 재현 (warning=attwl, danger=almwl) ===')
    riv = {c['wlobscd']: c for c in fetch_river_inventory()}
    CUR_RIV = {'1022668': (3.4, 5.0), '1018638': (4.9, 8.0), '1018665': (2.6, 6.0),
               '1018661': (3.7, 5.4), '1018666': (4.4, 6.5), '1019667': (1.6, 3.0),
               '1022647': (4.3, 7.4), '1013655': (2.8, 5.0)}
    for code, (w, d) in CUR_RIV.items():
        c = riv.get(code)
        if not c:
            print(f'  X {code} 원장에 없음'); ok = False; continue
        got = (float(c['attwl']), float(c['almwl']))
        same = abs(got[0] - w) < 1e-6 and abs(got[1] - d) < 1e-6
        ok &= same
        print(f'  {"O" if same else "X"} {code} {c.get("obsnm","")} {got} (운영 {(w, d)})')

    print('=== [4] 하천 상세정보(RIVER_META) 재현 — 지도.html 운영값 대조 ===')
    meta_path = ROOT / '.tmp' / '_north_rivermeta.json'
    if not meta_path.exists():
        print('  · 비교본(.tmp/_north_rivermeta.json)이 없어 건너뜀')
    else:
        cur = json.loads(meta_path.read_text(encoding='utf-8'))
        # riv 는 코드→레코드 dict 이므로 값 목록으로 넘긴다
        gen = build_river_meta(list(cur), list(riv.values()), fetch_dam_inventory(),
                               with_cctv=False)
        for code, exp in cur.items():
            g = gen.get(code, {})
            bad = []
            for k in ('att', 'wrn', 'alm', 'srs', 'pfh', 'gdt'):
                if k not in exp:
                    continue
                if abs(float(exp[k]) - float(g.get(k, -9e9))) > 1e-6:
                    bad.append(f'{k}: 운영 {exp[k]} vs 생성 {g.get(k)}')
            if exp.get('agc') and exp['agc'] != g.get('agc'):
                bad.append(f'관할: {exp["agc"]} vs {g.get("agc")}')
            ok &= not bad
            print(f'  {"O" if not bad else "X"} {code} {exp.get("addr","")[:24]}'
                  + ('  ' + ' / '.join(bad) if bad else ''))

    print()
    print('==> 전부 일치 — 생성 로직 신뢰 가능' if ok else '==> 불일치! 남부 생성 금지')
    return ok


def build(profile):
    sigun = SOUTH_SIGUN if profile == 'south' else NORTH_SIGUN
    inv = fetch_aws_inventory()
    aws = build_aws(sigun, inv)
    regs = build_regions(sigun, aws)
    riv_inv = fetch_river_inventory()
    rivers = add_nearby_rivers(build_rivers(sigun, riv_inv), regs, riv_inv)
    try:
        pm, pm_missing = build_pm(profile, fetch_pm_stations())
        if pm_missing:
            print(f'[경고] 실시간 목록에 없는 측정소(제외됨): {pm_missing}', file=sys.stderr)
    except Exception as e:
        print(f'[경고] 미세먼지 측정소 조회 실패: {type(e).__name__} {e}', file=sys.stderr)
        pm, pm_missing = {}, {}
    # 하천 상세정보 + CCTV — 화면의 하천 상세가 4단계 눈금을 그리는 데 쓴다.
    codes = sorted({st['code'] for lst in rivers.values() for st in lst})
    print(f'하천 상세·CCTV 조회 중… {len(codes)}개소 (홍수통제소에 한 곳씩 물어봐 좀 걸립니다)')
    meta = build_river_meta(codes, riv_inv, fetch_dam_inventory(), with_cctv=True)
    ncc = sum(1 for m in meta.values() if m.get('cctv'))
    print(f'  → CCTV 있는 곳 {ncc}/{len(codes)}개소')

    out = {'profile': profile, 'regions': regs,
           'aws': {a: [[r['stn'], r['name']] for r in st] for a, st in aws.items()},
           'rivers': rivers, 'river_meta': meta, 'pm': pm, 'pm_missing': pm_missing}
    path = CACHE / f'region_profile_{profile}.json'
    path.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding='utf-8')
    print(f'생성 완료 → {path}')
    return out


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--verify', action='store_true', help='경기북부 운영값 재현 검증')
    ap.add_argument('--build', choices=['north', 'south'], help='프로파일 생성')
    ap.add_argument('--refresh', action='store_true', help='원장 캐시 무시하고 새로 받기')
    ap.add_argument('--check-rivers', action='store_true',
                    help='선정된 수위관측소가 평상시에도 관심수위를 넘는지 실제 자료로 검사')
    a = ap.parse_args()
    if a.refresh:
        for f in ('stn_aws_inf.txt', 'hrfco_wl_info.json', 'airkorea_gg.json'):
            (CACHE / f).unlink(missing_ok=True)
    if a.verify or not a.build:
        if not verify_north() and a.build:
            sys.exit(1)
    if a.build:
        out = build(a.build)
        if a.check_rivers:
            print('\n=== 수위관측소 현실성 검사 (최근 24시간) ===')
            flat = [st for lst in out['rivers'].values() for st in lst]
            uniq = list({st['code']: st for st in flat}.values())
            sus = check_rivers(uniq, ENV.get('HRFCO_KEY', ''))
            if sus:
                print('\n!! 평상시에도 관심수위를 넘는 관측소 — RIVER_EXCLUDE 검토:')
                for st, over, tot, lo, hi in sus:
                    print(f'   {st["code"]} {st["obsnm"]} '
                          f'관심 {st["warning"]}m · 실측 {lo}~{hi}m · {over}/{tot}시간 초과')
            else:
                print('\n==> 상시 경보로 뜰 관측소 없음')
