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


def fetch_pm_stations(refresh=False, sido='경기'):
    """에어코리아 시도 실시간 측정소명 목록 (sido = 서울·부산·…·경기·강원·제주)."""
    key = ENV.get('DATA_GO_KR_KEY', '')

    def _get():
        r = requests.get(
            'https://apis.data.go.kr/B552584/ArpltnInforInqireSvc/getCtprvnRltmMesureDnsty',
            params={'serviceKey': key, 'returnType': 'json', 'numOfRows': 500,
                    'pageNo': 1, 'sidoName': sido, 'ver': '1.3'}, timeout=30)
        r.raise_for_status()
        return r.text

    cache_name = 'airkorea_gg.json' if sido == '경기' else f'airkorea_{sido}.json'
    js = json.loads(_cached(cache_name, _get, refresh))
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
                        'sgg': (prefixes[0][:5].ljust(5, '0') + '00000') if prefixes else '',
                        'src': '없음'})
            continue
        nx, ny = to_grid(lat, lon)
        out.append({'name': area, 'nx': nx, 'ny': ny,
                    'sgg': prefixes[0][:5].ljust(5, '0') + '00000',
                    'src': src, 'lat': round(lat, 5), 'lon': round(lon, 5)})
    return out


def build_rivers(sigun_map, inventory, per_sigun=3, sido_word='경기', sigun=None, alias=None):
    alias = alias or {}
    """시군별 수위관측소. warning=attwl(관심), danger=almwl(경계) — 임의값 아님.

    선정 기준: ①홍수예보지점(fstnyn=Y) 우선 ②기준수위 둘 다 있는 곳
    ③시군당 최대 per_sigun개. 관측소를 다 넣으면 5분 주기 수집이 감당 못 한다.

    ⚠ addr(주소)로 매칭하면 안 된다. 정부 원장에 오타가 있다 —
      1018690 안양시(충훈1교)의 addr은 '경기도 얀양시'라서 '안양'으로 못 찾는다.
      관측소명(obsnm)은 '안양시(충훈1교)' 형태로 정확하므로 이쪽을 기준으로 삼고,
      addr은 '경기'가 들어가는지 정도만(광주광역시 배제) 본다.
      obsnm을 '앞에서부터' 맞추므로 '양주시('가 '남양주시('에 걸리지도 않는다.
    """
    words = [sido_word] if isinstance(sido_word, str) else list(sido_word)
    out = {}
    for area in sigun_map:
        admin = (sigun or {}).get(area, {}).get('admin', '')
        cands = []
        for c in inventory:
            obsnm = (c.get('obsnm') or '').strip()
            addr = (c.get('addr') or '').strip()
            toks = addr.split()
            # 시군: 관측소명 접두('안양시(')로. 구(광역시): 관측소명이 '부산시(…)'라 주소의 구로 잡는다.
            by_name = obsnm.startswith(f'{area}시(') or obsnm.startswith(f'{area}군(') or \
                (admin and obsnm.startswith(f'{admin}('))
            # 주소의 시군구 토큰이 이 단위면 통과(광역시 관측소명은 '부산시(…)'라 이름으로 못 잡는다)
            tok_unit = unit_of(toks[1])[0] if len(toks) > 1 else None
            by_addr = tok_unit is not None and (tok_unit == area or alias.get(toks[1]) == area or alias.get(tok_unit) == area)
            if not (by_name or by_addr):
                continue
            if not any(w in addr + obsnm for w in words):
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


def add_nearby_rivers(rivers, regions, inventory, radius_km=12.0, sido_word='경기'):
    words = [sido_word] if isinstance(sido_word, str) else list(sido_word)
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
            if not any(w in (c.get('addr') or '') for w in words):
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
    # 강원 — 2026-09-18 실시간 목록(40곳)과 대조해 시군 소재 측정소를 골랐다.
    # ⚠ '속초'라는 AWS 지점은 고성군에 있고, '우천면' 측정소는 횡성군이다 — 이름만 믿지 말 것.
    'gangwon': {
        '춘천': '중앙로', '원주': '반곡동(명륜동)', '강릉': '옥천동', '동해': '천곡동',
        '태백': '황지동', '속초': '금호동', '삼척': '남양동1', '홍천': '홍천읍',
        '횡성': '횡성읍', '영월': '영월읍', '평창': '평창읍', '정선': '정선읍',
        '철원': '갈말읍', '화천': '화천읍', '양구': '양구읍', '인제': '인제읍',
        '고성': '간성읍', '양양': '양양읍',
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


# ════════════════════════════════════════════════════════════════
# 시도 단위 자동 생성 (전국 확장, 2026-09-18 사장님 결정: 강원 시범 → 전국, 시군구 단위)
#
# 경기북부·남부는 시군 목록·특보구역·산불 표기·키워드를 사람이 적었다. 시도가 17개면
# 그 방식은 반드시 빠지거나 틀린다. 여기서는 '시도 한 줄'만 적으면 나머지를 원장에서
# 기계로 뽑는다:
#   · 단위(시군/구) 목록 ← 기상청 AWS 지점원장의 법정동코드(앞 2자리=시도)·주소
#                         도는 시·군(시 밑의 구는 시로 묶음), 광역시는 구·군. 세종은 통째로 하나.
#   · 특보구역코드    ← 기상청 API허브 wrn_reg.php (지금 유효한 코드만 — 2026-05-31 개편 반영)
#                      시도 아래 모든 구역(세부·권역 포함)을 담는다. 시군에 못 붙는 권역은 권역명으로.
#   · 산불 시군표기   ← 산림청 산불위험 API 가 실제로 쓰는 표기와 대조
#   · 하천·댐        ← 한강홍수통제소 원장(전국). 댐은 warning=홍수기제한수위, danger=계획홍수위
#   · 미세먼지       ← 에어코리아 측정소정보(MsrstnInfoInqireSvc, 2026-09-18 승인) 주소로 자동 매핑
#   · 관측소 없는 단위 ← 통계청 경계 중심좌표로 격자를 정하고, 가장 가까운 이웃의 AWS 를 빌린다
# 결과는 tools/profiles/<key>.json 으로 저장하고 region_profiles.py 가 읽는다.
# ════════════════════════════════════════════════════════════════
def _sido(key, label, full, law, kostat, wrn_up, wrn_stn, pm_sido, words, home, **extra):
    d = {'key': key, 'label': label, 'full': full, 'law': law,
         'kostat': [kostat] if isinstance(kostat, str) else list(kostat),
         'wrn_up': [wrn_up] if isinstance(wrn_up, str) else list(wrn_up),
         'wrn_stn': wrn_stn,
         'pm_sido': [pm_sido] if isinstance(pm_sido, str) else list(pm_sido),
         'sido_words': list(words), 'home': home}
    d.update(extra)
    return d


# law = 법정동코드 앞 2자리(AWS 원장), kostat = 통계청 시군구코드 앞 2자리(지도 경계) — 둘은 다르다.
# wrn_stn = 기상청 특보 API stnId(담당 지방기상청): 109 수도권 · 105 강원 · 131 충북 · 133 대전(충남·세종)
#           · 146 전북 · 156 광주(전남) · 143 대구(경북) · 159 부산(경남·울산) · 184 제주
# sido_words = 주소·발신처·산불 doname 이 이 말로 시작하면 우리 시도 (옛 이름·새 이름 다 적는다)
SIDO = {
    'seoul':     _sido('seoul', '서울', '서울특별시', '11', '11', 'L1100000', 109, '서울', ['서울'], '중구'),
    'busan':     _sido('busan', '부산', '부산광역시', '26', '21', 'L1150000', 159, '부산', ['부산'], '연제구'),
    'daegu':     _sido('daegu', '대구', '대구광역시', '27', '22', 'L1140000', 143, '대구', ['대구'], '중구',
                       map_any_prefix=['군위군']),          # 2023 경북→대구 편입, 2013 경계자료엔 경북 밑
    # 인천: 2026-07 개편(중구·동구→제물포구·영종구, 서구→서해구·검단구)이 2013 경계자료에 없어
    #       지도는 옛 단위(중구·동구·서구)로 그리고, 새 이름은 unit_alias 로 옛 단위에 붙인다.
    #       ⚠ 경계자료가 갱신되면 units·unit_alias 를 걷어내고 자동 발견으로 돌릴 것.
    'incheon':   _sido('incheon', '인천', '인천광역시', '28', '23', ['L1110000', 'L1014000'], 109,
                       '인천', ['인천'], '남동구',   # 서해5도(옹진)는 별도 상위구역(L1014000)
                       units={
                           '중구': {'admin': '중구', 'prefixes': ['28125', '28155'], 'kind': 'gu'},
                           '동구': {'admin': '동구', 'prefixes': ['28140'], 'kind': 'gu'},
                           '미추홀구': {'admin': '미추홀구', 'prefixes': ['28177'], 'kind': 'gu'},
                           '연수구': {'admin': '연수구', 'prefixes': ['28185'], 'kind': 'gu'},
                           '남동구': {'admin': '남동구', 'prefixes': ['28200'], 'kind': 'gu'},
                           '부평구': {'admin': '부평구', 'prefixes': ['28237'], 'kind': 'gu'},
                           '계양구': {'admin': '계양구', 'prefixes': ['28245'], 'kind': 'gu'},
                           '서구': {'admin': '서구', 'prefixes': ['28260', '28275', '28290'], 'kind': 'gu'},
                           '강화': {'admin': '강화군', 'prefixes': ['2871'], 'kind': 'sigun'},
                           '옹진': {'admin': '옹진군', 'prefixes': ['2872'], 'kind': 'sigun'},
                       },
                       map_alias={'미추홀구': ['남구']},
                       unit_alias={'제물포구': '중구', '영종구': '중구', '서해구': '서구', '검단구': '서구'}),
    'daejeon':   _sido('daejeon', '대전', '대전광역시', '30', '25', 'L1120000', 133, '대전', ['대전'], '서구'),
    'ulsan':     _sido('ulsan', '울산', '울산광역시', '31', '26', 'L1160000', 159, '울산', ['울산'], '남구'),
    'sejong':    _sido('sejong', '세종', '세종특별자치시', '36', '29', 'L1170000', 133, '세종', ['세종'], '세종',
                       units={'세종': {'admin': '세종특별자치시', 'prefixes': ['3611']}},
                       map_alias={'세종': ['세종특별자치시', '세종시']}),
    'chungbuk':  _sido('chungbuk', '충북', '충청북도', '43', '33', 'L1040000', 131, '충북', ['충북', '충청북도'], '청주',
                       map_alias={'청주': ['청주시', '청원군']}),   # 2014 통합, 2013 경계자료엔 따로
    'chungnam':  _sido('chungnam', '충남', '충청남도', '44', '34', 'L1030000', 133, '충남', ['충남', '충청남도'], '홍성'),
    'jeonbuk':   _sido('jeonbuk', '전북', '전북특별자치도', '52', '35', 'L1060000', 146, '전북', ['전북', '전라북도'], '전주'),
    # 2026 광주·전남 통합 — 법정동 '12' 하나로 묶였지만 특보구역은 광주(L113)·전남(L105) 둘, 지도도 둘, 미세먼지도 둘
    'jngj':      _sido('jngj', '전남광주', '전남광주통합특별시', '12', ['24', '36'], ['L1050000', 'L1130000', 'L1052400'], 156,   # 흑산도.홍도 별도 상위구역
                       ['광주', '전남'], ['전남광주', '전라남도', '전남', '광주광역시'], '서구', wide='전남광주'),
    'gyeongbuk': _sido('gyeongbuk', '경북', '경상북도', '47', '37', ['L1070000', 'L1600000'], 143, '경북', ['경북', '경상북도'], '안동',   # 울릉도.독도는 별도 상위구역
                       map_exclude=['군위군']),           # 2023 대구로 편입
    'gyeongnam': _sido('gyeongnam', '경남', '경상남도', '48', '38', 'L1080000', 159, '경남', ['경남', '경상남도'], '창원'),
    'jeju':      _sido('jeju', '제주', '제주특별자치도', '50', '39', 'L1090000', 184, '제주', ['제주'], '제주'),
    'gangwon':   _sido('gangwon', '강원', '강원특별자치도', '51', '32', 'L1020000', 105, '강원', ['강원'], '춘천'),
}
# 법정동코드 앞 2자리 → 시도 (참고용). 경기(41)는 손으로 쓴 north·south 프로파일이 정본.
LAW_SIDO = {'11': '서울', '12': '전남광주', '26': '부산', '27': '대구', '28': '인천', '30': '대전',
            '31': '울산', '36': '세종', '41': '경기', '43': '충북', '44': '충남', '47': '경북',
            '48': '경남', '50': '제주', '51': '강원', '52': '전북'}

_ADMIN_SUFFIX = re.compile(r'(특별자치시|특별자치도|특별시|광역시|시|군)$')
_GEO_CACHE = ROOT / '.tmp' / 'skorea_municipalities.json'   # build_map_geo.py 와 같은 파일


def resolve_unit(sd, name):
    """새 이름(제물포구)을 프로파일 단위(중구)로. 별칭이 없으면 그대로."""
    return (sd.get('unit_alias') or {}).get(name, name)


def unit_of(token):
    """주소의 시군구 토큰 → (단위명, 행정명, 종류).
    '춘천시'→('춘천','춘천시','sigun')  '고양시덕양구'→('고양','고양시','sigun')
    '해운대구'→('해운대구','해운대구','gu')  '기장군'→('기장','기장군','sigun')  '조치원읍'→(None,…)"""
    m = re.match(r'^(.+?(?:시|군))(.*구)?$', token)
    if m:
        admin = m.group(1)
        return _ADMIN_SUFFIX.sub('', admin), admin, 'sigun'
    if token.endswith('구') and len(token) >= 2:
        return token, token, 'gu'
    return None, None, None


def _load_geo():
    return json.loads(_GEO_CACHE.read_text(encoding='utf-8')) if _GEO_CACHE.exists() else {'features': []}


def units_from_geo(sd):
    """통계청 경계자료(2013)에서 이 시도의 단위 전수 → {단위: {'admin','kind'}}.
    AWS 원장만 보면 관측소 없는 구(부산 동구·연제구·수영구)가 통째로 빠진다 — 그래서 경계자료가 기준.
    map_alias 의 원본 이름(청원군→청주)은 단위로 세지 않고, map_exclude(경북의 군위군)는 뺀다."""
    alias_src = {n for lst in (sd.get('map_alias') or {}).values() for n in lst}
    excl = set(sd.get('map_exclude') or [])
    anyp = set(sd.get('map_any_prefix') or [])
    out = {}
    for f in _load_geo()['features']:
        code, fname = str(f['properties']['code']), f['properties']['name']
        if not (any(code.startswith(k) for k in sd['kostat']) or fname in anyp):
            continue
        if fname in excl:
            continue
        # 별칭으로 다른 단위에 묶이는 이름(청원군·세종시·남구←미추홀구)은 그 단위 이름으로
        target = next((u for u, lst in (sd.get('map_alias') or {}).items() if fname in lst), None)
        if target:
            adm = (sd.get('units') or {}).get(target, {}).get('admin') or target
            out.setdefault(target, {'admin': adm, 'kind': 'gu' if adm.endswith('구') else 'sigun'})
            continue
        if fname in alias_src:
            continue
        name, admin, kind = unit_of(fname)
        if name:
            out.setdefault(name, {'admin': admin, 'kind': kind})
    return out


def sigun_from_inventory(sd, inventory):
    """단위 목록 → {단위: {'admin': '춘천시', 'prefixes': ['5111'], 'kind': 'sigun'}}.

    단위 전수는 경계자료(units_from_geo)에서, 법정동 접두사는 AWS 원장에서. 원장에만 있는
    단위(경계자료 이후 신설)는 추가한다. 시군은 4자리 접두사(구 신설을 자동으로 따라오게 —
    화성 만세구 사례), 4자리가 겹치는 곳(충북 영동 43740·증평 43745)만 5자리, 구는 5자리.
    """
    if sd.get('units'):
        return {n: dict(v, kind=v.get('kind', 'sigun')) for n, v in sd['units'].items()}
    units = units_from_geo(sd)
    codes = {}
    for r in inventory:
        if not r['law'].startswith(sd['law']):
            continue
        toks = r['addr'].replace('(산지)', '').split()
        if len(toks) < 2:
            continue
        name, admin, kind = unit_of(toks[1])
        if not name:
            continue
        units.setdefault(name, {'admin': admin, 'kind': kind})
        codes.setdefault(name, set()).add(r['law'][:5])
    # 접두사 길이 결정
    four = {}
    for name, cs in codes.items():
        for c in cs:
            four.setdefault(c[:4], set()).add(name)
    out = {}
    for name in sorted(units):
        cs = sorted(codes.get(name, ()))
        if units[name]['kind'] == 'gu':
            prefixes = cs
        else:
            prefixes = sorted({c[:4] if len(four.get(c[:4], ())) == 1 else c for c in cs})
        out[name] = {'admin': units[name]['admin'], 'prefixes': prefixes, 'kind': units[name]['kind']}
    return out


def geo_centroids(sd, sigun):
    """통계청 경계자료(2013)에서 단위별 중심 위경도. 관측소가 없는 단위의 격자·이웃 계산용.
    이름으로 찾는다(시 밑의 구는 시로 묶음). map_alias / map_any_prefix 로 이름·소속 변경을 흡수."""
    geo = _load_geo()
    alias = sd.get('map_alias') or {}
    anyp = set(sd.get('map_any_prefix') or [])
    pts = {}
    for f in geo['features']:
        code = str(f['properties']['code'])
        fname = f['properties']['name']
        in_sido = any(code.startswith(k) for k in sd['kostat'])
        for area, info in sigun.items():
            names = alias.get(area) or [info['admin']]
            hit = any(fname == n or fname.startswith(n) for n in names)
            if not hit or not (in_sido or fname in anyp):
                continue
            g = f['geometry']
            rings = [g['coordinates'][0]] if g['type'] == 'Polygon' else [p[0] for p in g['coordinates']]
            for ring in rings:
                for lon, lat in ring:
                    pts.setdefault(area, [0.0, 0.0, 0])
                    pts[area][0] += lat; pts[area][1] += lon; pts[area][2] += 1
            break
    return {a: (v[0] / v[2], v[1] / v[2]) for a, v in pts.items() if v[2]}


def fetch_wrn_regions(refresh=False):
    """기상청 API허브 특보구역 코드표 (wrn_reg.php). 행: REG_ID TM_ST TM_ED REG_SP REG_UP REG_KO REG_NAME"""
    key = ENV.get('KMA_APIHUB_KEY', '')

    def _get():
        r = requests.get(f'https://apihub.kma.go.kr/api/typ01/url/wrn_reg.php?help=1&authKey={key}',
                         timeout=30)
        r.raise_for_status()
        r.encoding = 'euc-kr'
        return r.text

    rows = []
    for line in _cached('wrn_reg.txt', _get, refresh).splitlines():
        s = line.strip()
        if not s or s.startswith('#'):
            continue
        f = s.split()
        if len(f) < 7:
            continue
        rows.append({'id': f[0], 'st': f[1], 'ed': f[2], 'sp': f[3], 'up': f[4],
                     'ko': f[5], 'name': ' '.join(f[6:])})
    return rows


def build_reg_map(sd, sigun, wrn_rows, now=None):
    """시도 아래 지금 유효한 특보구역 코드 전부 → 단위. 세부구역(강릉시평지·산지)은 그 시군에,
    시군에 안 붙는 권역(서울동북권 등)은 권역명 그대로 — 어느 쪽이든 '관할'로 잡힌다."""
    now = now or datetime.now().strftime('%Y%m%d%H%M')
    reg_map = {}
    parents = set(sd['wrn_up'])
    for _ in range(3):
        new = {}
        for r in wrn_rows:
            if r['up'] not in parents or r['id'] in reg_map or not (r['st'] <= now <= r['ed']):
                continue
            target = None
            for name, info in sigun.items():
                if r['name'].startswith(info['admin']) or r['name'].startswith(name):
                    target = name
                    break
            if target is None and r['up'] in reg_map and not reg_map[r['up']].endswith('(전체)'):
                target = reg_map[r['up']]          # 세부구역은 부모 단위를 물려받는다
            new[r['id']] = target or r['ko']
        if not new:
            break
        reg_map.update(new)
        parents = set(new)
    wide_names = []
    for up in sd['wrn_up']:
        wide = next((r for r in wrn_rows if r['id'] == up), None)
        ko = (wide or {}).get('ko', sd['label'])
        reg_map[up] = f'{ko}(전체)'
        wide_names.append(ko)
    wide_label = sd.get('wide') or wide_names[0]      # 화면·정렬용 시도 전역 이름(통합시는 명시)
    return reg_map, wide_label, wide_names


def fetch_fire_sigun_names(sd, refresh=False):
    """산불위험예보 API가 이 시도에 대해 쓰는 시군 표기(구 포함) 목록."""
    key = ENV.get('DATA_GO_KR_KEY', '')

    def _get():
        r = requests.get('https://apis.data.go.kr/1400377/forestPointV2/forestPointListSigunguSearchV2',
                         params={'serviceKey': key, 'numOfRows': 500, 'pageNo': 1, '_type': 'json'},
                         timeout=30)
        r.raise_for_status()
        return r.text

    try:
        js = json.loads(_cached('forest_sigungu.json', _get, refresh))
        items = js['response']['body']['items']['item']
        if isinstance(items, dict):
            items = [items]
    except Exception as e:
        print(f'[경고] 산불 시군 표기 조회 실패: {type(e).__name__} — 행정명으로 대신함', file=sys.stderr)
        return []
    return sorted({str(it.get('sigun', '')).strip() for it in items
                   if any(str(it.get('doname', '')).startswith(w) for w in sd['sido_words'])})


def build_fire_sigun_map(sigun, fire_names, sd=None):
    """산불 API 표기('춘천시'·'수원시장안구'·'해운대구') → 단위. 행정명 그대로 + API 표기 중 접두 일치.
    새 이름(제물포구)은 unit_alias 로 옛 단위에."""
    m = {info['admin']: name for name, info in sigun.items()}
    alias = (sd or {}).get('unit_alias') or {}
    for fn in fire_names:
        for new, old in alias.items():
            if fn.startswith(new):
                m[fn] = old
                break
        else:
            for name, info in sigun.items():
                if fn.startswith(info['admin']) or fn.startswith(name):
                    m[fn] = name
                    break
    return m


def build_fire_groups(regs):
    """산불 표시 묶음 — 북→남 순으로 3개씩. 화면 칩 하나가 한 묶음(최댓값)이다."""
    order = sorted([r for r in regs if r.get('lat')], key=lambda r: -r['lat'])
    groups = {}
    for i in range(0, len(order), 3):
        chunk = [r['name'] for r in order[i:i + 3]]
        groups['·'.join(chunk)] = chunk
    return groups


def build_dams(sd, sigun, dam_inv):
    """이 시도 안의 댐 — warning=홍수기제한수위(fldlmtwl), danger=계획홍수위(pfh).
    (경기북부 손값과 같은 규칙: 청평댐 50/52·팔당댐 -/27·한탄강댐 -/114.4)"""
    out = []
    for d in dam_inv or []:
        if not d or not d.get('dmobscd'):
            continue
        addr = (d.get('addr') or '')
        if not any(addr.startswith(w) for w in sd['sido_words']):
            continue
        toks = addr.split()
        area = resolve_unit(sd, unit_of(toks[1])[0]) if len(toks) > 1 else None
        if area not in sigun:
            continue

        def num(v):
            try:
                return float(str(v).strip())
            except (TypeError, ValueError):
                return None
        out.append({'code': d['dmobscd'], 'name': f"{d.get('obsnm', '')} ({area})".strip(),
                    'sigun': area, 'warning': num(d.get('fldlmtwl')), 'danger': num(d.get('pfh')),
                    'has_cctv': False, 'api': 'dam'})
    return out


def _bridge(obsnm):
    m = re.search(r'\((.+?)\)', obsnm or '')
    return m.group(1) if m else (obsnm or '')


def fetch_msrstn_list(refresh=False):
    """에어코리아 측정소정보 — 전국 측정소 주소·종류 (2026-09-18 사장님이 활용신청·승인)."""
    key = ENV.get('DATA_GO_KR_KEY', '')

    def _get():
        r = requests.get('https://apis.data.go.kr/B552584/MsrstnInfoInqireSvc/getMsrstnList',
                         params={'serviceKey': key, 'returnType': 'json', 'numOfRows': 2000,
                                 'pageNo': 1}, timeout=60)
        r.raise_for_status()
        if 'response' not in r.text[:200]:
            raise RuntimeError('측정소정보 응답 이상: ' + r.text[:120])
        return r.text

    js = json.loads(_cached('airkorea_msrstn.json', _get, refresh))
    return js['response']['body'].get('items', [])


def build_pm_auto(sd, sigun, msrstn, live_names, centers=None):
    """단위별 대표 측정소 — 측정소 주소의 시군구로 붙이고, 도시대기 > 그 외, 같은 급이면 단위
    중심(대표 관측소)에 가까운 곳. 실시간 목록에 있는 것만(폐소 방지)."""
    rank = {'도시대기': 0, '교외대기': 1, '도로변대기': 2, '국가배경농도': 3}
    centers = centers or {}
    cands = {}
    for it in msrstn:
        addr = (it.get('addr') or '').strip()
        if not any(addr.startswith(w) for w in sd['sido_words']):
            continue
        toks = addr.split()
        if sd.get('units') and len(sd['units']) == 1:
            area = next(iter(sd['units']))               # 세종처럼 단위가 하나
        else:
            area = resolve_unit(sd, unit_of(toks[1])[0]) if len(toks) > 1 else None
        if area not in sigun or it.get('stationName') not in live_names:
            continue
        dist = 0.0
        try:
            la, lo = centers.get(area, (None, None))
            if la is not None:
                dist = _km(la, lo, float(it.get('dmX')), float(it.get('dmY')))
        except (TypeError, ValueError):
            dist = 999.0
        cands.setdefault(area, []).append((rank.get(it.get('mangName'), 5), round(dist, 2), it['stationName']))
    return {a: sorted(v)[0][2] for a, v in cands.items()}


def build_sido(key, with_cctv=True, refresh=False):
    sd = SIDO[key]
    words = sd['sido_words']
    inv = fetch_aws_inventory(refresh)
    sigun = sigun_from_inventory(sd, inv)
    print(f'[{sd["label"]}] 단위 {len(sigun)}곳: {", ".join(sigun)}')
    sigun_map = {n: i['prefixes'] for n, i in sigun.items()}
    aws = build_aws(sigun_map, inv)
    regs = build_regions(sigun_map, aws)
    cent = geo_centroids(sd, sigun)
    aws_fallback = {}
    for r in regs:
        r['admin'] = sigun[r['name']]['admin']
        if r['nx'] is None:
            # 관측소가 없는 단위(서울 일부 구 등) — 경계 중심으로 격자를 정하고 이웃 AWS 를 빌린다
            if r['name'] not in cent:
                raise SystemExit(f'{r["name"]}: 관측소도 경계자료도 없다')
            r['lat'], r['lon'] = round(cent[r['name']][0], 5), round(cent[r['name']][1], 5)
            r['nx'], r['ny'] = to_grid(r['lat'], r['lon'])
            r['src'] = '경계 중심'
            near = [(_km(r['lat'], r['lon'], o['lat'], o['lon']), o['name'])
                    for o in regs if o.get('lat') and o['name'] != r['name'] and aws.get(o['name'])]
            if near:
                aws_fallback[r['name']] = min(near)[1]
    if aws_fallback:
        print(f'  관측소 없는 단위 → 이웃 AWS 대용: {aws_fallback}')

    riv_inv = fetch_river_inventory(refresh)
    rivers = add_nearby_rivers(build_rivers(sigun_map, riv_inv, sido_word=words, sigun=sigun,
                                            alias=sd.get('unit_alias')), regs, riv_inv,
                               sido_word=words)
    dams = build_dams(sd, sigun, fetch_dam_inventory(refresh))

    # 하천 이름(WAMIS) — 표기를 경기와 같게 '하천명 (시군 다리명)' 으로
    sess = requests.Session()
    sess.headers.update({'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
    river_stations, names_cache = [], {}
    for area, lst in rivers.items():
        for st in lst:
            if st['code'] not in names_cache:
                names_cache[st['code']] = river_name(st['code'], sess)
                time.sleep(0.2)
            rn = names_cache[st['code']]
            label = f"{rn} ({area} {_bridge(st['obsnm'])})" if rn else f"{area} {_bridge(st['obsnm'])}"
            if st.get('nearby'):
                toks = (st.get('addr') or '').split()
                near_area = (unit_of(toks[1])[0] or '') if len(toks) > 1 else ''
                tail = f"{area} 인근 · {near_area} {_bridge(st['obsnm'])}".replace('  ', ' ')
                label = f"{rn} ({tail})" if rn else tail
            river_stations.append({'code': st['code'], 'name': label, 'sigun': area,
                                   'warning': st['warning'], 'danger': st['danger'],
                                   'has_cctv': False, 'api': 'waterlevel',
                                   **({'nearby': True} if st.get('nearby') else {})})
    river_stations += dams
    codes = sorted({st['code'] for st in river_stations})
    print(f'하천 {len(river_stations) - len(dams)}곳 + 댐 {len(dams)}곳 — 상세{"·CCTV" if with_cctv else ""} 조회 중…')
    meta = build_river_meta(codes, riv_inv, fetch_dam_inventory(), with_cctv=with_cctv)
    for st in river_stations:
        st['has_cctv'] = bool(meta.get(st['code'], {}).get('cctv'))
    if with_cctv:
        print(f'  → CCTV 있는 곳 {sum(1 for m in meta.values() if m.get("cctv"))}/{len(codes)}곳')

    # 미세먼지 — 측정소정보(주소)로 자동, 실시간 목록에 있는 것만
    pm = {}
    try:
        live = set()
        for s in sd['pm_sido']:
            for attempt in range(3):                    # 에어코리아 실시간 API 는 504 가 잦다
                try:
                    live |= set(fetch_pm_stations(refresh, s))
                    break
                except Exception as e:
                    print(f'  실시간 측정소 목록({s}) {attempt + 1}회 실패: {type(e).__name__}', file=sys.stderr)
                    time.sleep(3)
        if not live:
            raise RuntimeError('실시간 측정소 목록을 못 받았다 — 나중에 다시 생성할 것')
        pm = build_pm_auto(sd, sigun, fetch_msrstn_list(refresh), live,
                           {r['name']: (r.get('lat'), r.get('lon')) for r in regs})
        table = PM_STATION_TABLE.get(key, {})
        for a, s in table.items():                    # 손으로 고른 표가 있으면 그것을 우선
            if s in live:
                pm[a] = s
    except Exception as e:
        print(f'[경고] 미세먼지 측정소 자동 매핑 실패: {type(e).__name__}', file=sys.stderr)
    pm_missing = [a for a in sigun if a not in pm]
    if pm_missing:
        print(f'  미세먼지 측정소 없는 단위: {pm_missing}')

    wrn_rows = fetch_wrn_regions(refresh)
    reg_map, wide_label, wide_names = build_reg_map(sd, sigun, wrn_rows)
    fire_map = build_fire_sigun_map(sigun, fetch_fire_sigun_names(sd, refresh), sd)
    river_words = sorted({n for n in names_cache.values() if n})
    order = [r['name'] for r in sorted(regs, key=lambda r: (-r['lat'], r['lon']))]   # 북→남, 서→동
    gun = [n for n, i in sigun.items() if i['admin'].endswith('군')]

    out = {
        'key': key, 'label': sd['label'], 'title': f"{sd['label']} 기상·재난 상황판",
        'full': sd['full'], 'home': sd['home'], 'home_office': f"{sd['home']}소방서",
        'host': 'weather.visanu81.workers.dev',
        'data_file': f'data-{key}.js', 'map_file': f'map-geo-{key}.js',
        'combined_file': f'상황판-{key}.html',
        'notify': False, 'tide': False, 'share_images_from': 'data.js',
        'wrn_stn': sd['wrn_stn'], 'wrn_prefix': [u[:4] for u in sd['wrn_up']],
        'wide_label': wide_label, 'wide_names': wide_names,
        'pm_sido': sd['pm_sido'], 'sido_words': words,
        'kostat': sd['kostat'], 'map_alias': sd.get('map_alias') or {},
        'unit_alias': sd.get('unit_alias') or {},
        'map_any_prefix': sd.get('map_any_prefix') or [],
        'regions': [{k: r[k] for k in ('name', 'nx', 'ny', 'sgg', 'lat', 'lon', 'admin')} for r in regs],
        'pm_stations': pm,
        'aws_stations': {a: [[r['stn'], r['name']] for r in st] for a, st in aws.items()},
        'aws_fallback': aws_fallback,
        'river_stations': river_stations,
        'river_meta': meta,
        'keywords': [sd['label'], sd['full']] + wide_names + list(sigun) + list((sd.get('unit_alias') or {})),
        'reg_map': reg_map,
        'region_order': [wide_label] + order,
        'fire_sigun_map': fire_map,
        'fire_groups': build_fire_groups(regs),
        'flood_keywords': sorted(set(list(sigun) + river_words + [sd['label']] + wide_names)),
        'exclude_prefix': '',
        'gun_names': gun,
        'admin': {n: i['admin'] for n, i in sigun.items()},
        'generated': datetime.now().strftime('%Y-%m-%d %H:%M'),
    }
    path = ROOT / 'tools' / 'profiles' / f'{key}.json'
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding='utf-8')
    print(f'생성 완료 → {path}')
    n_riv_units = len({s['sigun'] for s in river_stations})
    print(f'  특보구역 {len(reg_map)}코드 · 산불표기 {len(fire_map)} · 미세먼지 {len(pm)}/{len(sigun)}'
          f' · 하천 {len(river_stations)}(단위 {n_riv_units}/{len(sigun)})')
    return out


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
        print(f'[경고] 미세먼지 측정소 조회 실패: {type(e).__name__}', file=sys.stderr)
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
    ap.add_argument('--sido', choices=sorted(SIDO) + ['all'], help='시도 단위 자동 생성 → tools/profiles/<key>.json (all=전부)')
    ap.add_argument('--no-cctv', action='store_true', help='CCTV 유무 조회 생략(빠른 시험용)')
    ap.add_argument('--refresh', action='store_true', help='원장 캐시 무시하고 새로 받기')
    ap.add_argument('--check-rivers', action='store_true',
                    help='선정된 수위관측소가 평상시에도 관심수위를 넘는지 실제 자료로 검사')
    a = ap.parse_args()
    if a.refresh:
        for f in ('stn_aws_inf.txt', 'hrfco_wl_info.json', 'airkorea_gg.json'):
            (CACHE / f).unlink(missing_ok=True)
    if a.sido:
        keys = sorted(SIDO) if a.sido == 'all' else [a.sido]
        for k in keys:
            print(f'\n───── {k} ─────')
            out = build_sido(k, with_cctv=not a.no_cctv, refresh=a.refresh)
        if a.check_rivers:
            print('\n=== 수위관측소 현실성 검사 (최근 24시간) ===')
            uniq = [{'code': s['code'], 'obsnm': s['name'], 'warning': s['warning']}
                    for s in out['river_stations'] if s['api'] == 'waterlevel']
            sus = check_rivers(uniq, ENV.get('HRFCO_KEY', ''))
            if sus:
                print('\n!! 평상시에도 관심수위를 넘는 관측소 — RIVER_EXCLUDE 검토:')
                for st, over, tot, lo, hi in sus:
                    print(f'   {st["code"]} {st["obsnm"]} 관심 {st["warning"]}m · 실측 {lo}~{hi}m · {over}/{tot}시간 초과')
            else:
                print('\n==> 상시 경보로 뜰 관측소 없음')
        sys.exit(0)
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
