# -*- coding: utf-8 -*-
"""관서 지도(map-geo*.js) 생성기 — 행정경계 GeoJSON → SVG path.

투영식은 기존 map-geo.js(경기북부)를 역산해 복원한 것이다. --verify 로 돌리면
북부 지도를 다시 그려 현재 운영 파일과 좌표가 일치하는지 대조한다. 일치해야
같은 방식으로 만든 남부 지도도 믿을 수 있다.

  x = (lon - minLon) * kx * scale + pad      kx    = cos(지도 중앙 위도)
  y = (maxLat - lat) * scale + pad           scale = (W - 2*pad) / (경도폭 * kx)
  W = 1000, pad = 12,  H = 위도폭 * scale + 2*pad

원본: 통계청 2013 시군구 경계(공개 데이터). 시(市) 하위 구(區)는 관서 단위로 묶는다.
  · --merge: 구 경계선을 지운다(수원 4구·용인 3구가 한 덩어리로 보인다).
    같은 원본에서 온 인접 폴리곤은 변(邊)을 공유하므로, 양쪽에 반대 방향으로
    한 번씩 나타나는 변만 지우면 외곽선만 남는다(불리언 연산 라이브러리 불필요).
  · 미지정 시 구를 그냥 이어붙인다 — 기존 북부 파일이 이 방식이라 재현 검증용.

실행:
  python tools/build_map_geo.py --verify
  python tools/build_map_geo.py --profile south --merge --out map-geo-south.js
"""
import argparse
import json
import math
import sys
from pathlib import Path

import requests

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / '.tmp' / 'skorea_municipalities.json'
SOURCE_URL = ('https://cdn.jsdelivr.net/gh/southkorea/southkorea-maps@master/'
              'kostat/2013/json/skorea_municipalities_geo_simple.json')

W, PAD = 1000, 12

# 관서 → 통계청 시군구 코드. 시 하위 구는 관서 단위로 묶는다.
GROUPS = {
    'north': {
        '의정부': ['31030'], '양주': ['31260'], '동두천': ['31080'], '포천': ['31270'],
        '연천': ['31350'], '가평': ['31370'], '남양주': ['31130'], '구리': ['31120'],
        '파주': ['31200'],
        '고양': ['31101'],                    # 덕양구
        '일산': ['31103', '31104'],           # 일산동구·일산서구
    },
    'south': {
        '수원': ['31011', '31012', '31013', '31014'],
        '성남': ['31021', '31022', '31023'],
        '안양': ['31041', '31042'],
        '부천': ['31051', '31052', '31053'],
        '광명': ['31060'], '평택': ['31070'],
        '안산': ['31091', '31092'],
        '과천': ['31110'], '오산': ['31140'], '시흥': ['31150'], '군포': ['31160'],
        '의왕': ['31170'], '하남': ['31180'],
        '용인': ['31191', '31192', '31193'],
        '이천': ['31210'], '안성': ['31220'], '김포': ['31230'], '화성': ['31240'],
        '광주': ['31250'], '여주': ['31280'], '양평': ['31380'],
    },
}
# 경기 전체(ggweather) — 북부 10 + 남부 21 = 경기도 31개 시군.
# ⚠ 일산은 여기서 고양에 합친다. 일산은 '소방서 관할' 단위지 시군이 아니라서,
#   경기도 지도에 따로 그리면 없는 행정구역이 하나 생긴 것처럼 보인다.
#   (북부 전용 지도에서는 관서가 단위라 지금처럼 나눠 그리는 게 맞다)
# 소방서 단위라 성남·고양은 구(區)로 쪼갠다. 일산은 북부와 같은 방식.
#   ⚠ 송탄은 여기 없다 — 평택시는 하위 구가 없어 2013 시군구 경계로는 분리가 안 된다.
#     그래서 지도에는 평택 한 덩어리로만 그려지고, 송탄은 관서 배치도·레일·상세에만
#     나온다(읍면동 경계 자료를 새로 가져오면 쪼갤 수 있으나 이번 범위 밖).
GROUPS['all'] = dict(GROUPS['south'])
GROUPS['all'].update({k: v for k, v in GROUPS['north'].items() if k != '고양'})
GROUPS['all']['성남'] = ['31021', '31022']       # 수정구·중원구
GROUPS['all']['분당'] = ['31023']                # 분당구
GROUPS['all']['고양'] = GROUPS['north']['고양']  # 덕양구
GROUPS['all']['일산'] = GROUPS['north']['일산']  # 일산동구·일산서구

# 화면 표시 순서(북→남, 서→동). 지도 자체엔 영향 없고 파일 내 순서만 정한다.
ORDER = {
    'north': ['의정부', '양주', '동두천', '포천', '연천', '가평', '남양주', '구리',
              '파주', '고양', '일산'],
    'south': ['김포', '하남', '부천', '광명', '양평', '과천', '성남', '광주', '시흥',
              '안양', '군포', '의왕', '안산', '수원', '용인', '이천', '여주', '화성',
              '오산', '안성', '평택'],
}
# 경기 전체 = 경기도 소방서 순서(사장님 지정, 2026-08-19). 가평은 동두천-가평-연천.
# 송탄은 지도 경계가 없어 빠진다(위 GROUPS 주석 참조) — 33개.
ORDER['all'] = ['수원', '성남', '분당', '부천', '안양', '안산', '용인', '평택',
                '광명', '시흥', '군포', '화성', '이천', '김포', '광주', '안성',
                '하남', '의왕', '오산', '여주', '양평', '과천', '고양', '일산',
                '의정부', '남양주', '파주', '구리', '포천', '양주', '동두천',
                '가평', '연천']


def load_geojson(refresh=False):
    if CACHE.exists() and not refresh:
        return json.loads(CACHE.read_text(encoding='utf-8'))
    CACHE.parent.mkdir(exist_ok=True)
    r = requests.get(SOURCE_URL, timeout=120)
    r.raise_for_status()
    CACHE.write_bytes(r.content)
    print(f'경계자료 내려받음 {len(r.content):,} bytes → {CACHE}')
    return json.loads(r.content.decode('utf-8'))


def rings_of(feature):
    """Polygon/MultiPolygon → 외곽 링 목록 (구멍은 무시 — 시군 경계엔 없다)."""
    g = feature['geometry']
    if g['type'] == 'Polygon':
        return [g['coordinates'][0]]
    return [poly[0] for poly in g['coordinates']]


def merge_rings(rings):
    """인접 폴리곤을 합쳐 외곽선만 남긴다.

    같은 원본에서 나온 인접 폴리곤은 경계 변을 정확히 공유한다. 어떤 변이 정방향과
    역방향으로 한 번씩 나타나면 그건 두 폴리곤 사이의 내부 경계선이므로 지운다.
    남은 변을 이어붙이면 외곽 링이 된다. 공유 변이 하나도 없으면(떨어진 섬 등)
    원래 링을 그대로 돌려준다.
    """
    edges = {}
    for ring in rings:
        pts = ring[:-1] if ring[0] == ring[-1] else ring[:]
        n = len(pts)
        for i in range(n):
            a, b = tuple(pts[i]), tuple(pts[(i + 1) % n])
            edges[(a, b)] = edges.get((a, b), 0) + 1

    kept = {}
    for (a, b), cnt in edges.items():
        rev = edges.get((b, a), 0)
        remain = cnt - rev
        if remain > 0:
            kept[(a, b)] = remain
    if not kept:
        return rings

    nxt = {}
    for (a, b), cnt in kept.items():
        nxt.setdefault(a, []).extend([b] * cnt)

    out = []
    while any(nxt.get(k) for k in nxt):
        start = next(k for k in nxt if nxt[k])
        ring, cur = [start], start
        while True:
            opts = nxt.get(cur)
            if not opts:
                break
            nb = opts.pop(0)
            if nb == start:
                break
            ring.append(nb)
            cur = nb
            if len(ring) > 100000:      # 자료가 깨졌을 때 무한루프 방지
                break
        if len(ring) >= 3:
            out.append([list(p) for p in ring] + [list(start)])
    return out or rings


def area_centroid(rings):
    """면적 가중 무게중심 — 라벨을 놓을 자리. 가장 큰 링 기준(섬에 라벨이 가면 안 된다)."""
    best, best_a = None, -1
    for ring in rings:
        pts = ring[:-1] if ring[0] == ring[-1] else ring
        a = cx = cy = 0.0
        n = len(pts)
        for i in range(n):
            x1, y1 = pts[i]
            x2, y2 = pts[(i + 1) % n]
            cr = x1 * y2 - x2 * y1
            a += cr
            cx += (x1 + x2) * cr
            cy += (y1 + y2) * cr
        if abs(a) < 1e-12:
            continue
        a *= 0.5
        if abs(a) > best_a:
            best_a = abs(a)
            best = (cx / (6 * a), cy / (6 * a))
    return best


# 통계청 시군구 코드 앞 2자리 → 시도 (전국 확장용). 법정동코드와 다르다(강원 51 ↔ 통계청 32).
KOSTAT_SIDO = {'11': '서울', '21': '부산', '22': '대구', '23': '인천', '24': '광주', '25': '대전',
               '26': '울산', '29': '세종', '31': '경기', '32': '강원', '33': '충북', '34': '충남',
               '35': '전북', '36': '전남', '37': '경북', '38': '경남', '39': '제주'}


def groups_from_profile(key, geo):
    """생성 프로파일(tools/profiles/<key>.json)의 시군을 경계자료에서 이름으로 찾는다.
    시 하위 구('수원시 장안구' 식으로 name 이 따로 있는 경우)는 시로 묶는다."""
    prof = json.loads((ROOT / 'tools' / 'profiles' / f'{key}.json').read_text(encoding='utf-8'))
    prefixes = tuple(prof.get('kostat') or [next(k for k, v in KOSTAT_SIDO.items() if v == prof['label'])])
    admin = prof['admin']                      # 시군 → '춘천시'
    alias = prof.get('map_alias') or {}        # 이름이 바뀐 곳(미추홀구←남구·청주←청원군)
    anyp = set(prof.get('map_any_prefix') or [])   # 소속이 바뀐 곳(군위군: 경북→대구)
    groups = {}
    for f in geo['features']:
        code = str(f['properties']['code'])
        name = f['properties']['name']
        if not (code.startswith(prefixes) or name in anyp):
            continue
        for area, adm in admin.items():
            names = alias.get(area) or [adm]
            if any(name == n or name.startswith(n) for n in names):
                groups.setdefault(area, []).append(code)
                break
    missing = [a for a in admin if a not in groups]
    if missing:
        raise SystemExit(f'경계자료에서 못 찾은 시군: {missing}')
    # [0]은 시도 전역 이름(세종은 단위 이름과 같아 중복이 난다) → 뒤부터, 중복 제거
    order = list(dict.fromkeys(a for a in prof['region_order'][1:] if a in groups))
    return groups, order


# ── 먼 섬 분리 (2026-09-19 사장님: "인천이나 몇몇 시도가 지도 거리 때문에 보기 좋지 않아") ──
# 백령도(인천, 본토에서 150km)·울릉도·독도(경북, 220km)·흑산도·가거도(전남) 같은 먼 섬을 본토와
# 한 상자에 넣으면 본토가 구석에 손톱만 하게 찍힌다. 그래서 링(폴리곤)들을 '가까운 것끼리' 묶고,
# 면적이 가장 큰 무리(본토)만으로 지도 틀을 잡는다. 나머지(먼 섬)는 구석의 작은 상자(inset)에
# 따로 축척을 잡아 그린다 — 종이 지도의 '울릉도·독도' 상자와 같은 관례.
#   · 두 링의 경계 상자 사이 빈틈이 GAP_KM 보다 작으면 같은 무리(섬이 징검다리처럼 이어지면 본토로 붙는다)
#   · 상자 자리: 먼 섬이 본토의 서쪽이면 왼쪽, 동쪽이면 오른쪽 / 북쪽이면 위, 남쪽이면 아래
#   · 경기 세 지도(north·south·all)는 먼 섬이 없어 결과가 한 글자도 안 바뀐다(--verify 로 확인)
GAP_KM = 25.0
INSET_W_RATIO = 0.24        # 상자 너비 = 지도 너비의 24%
INSET_H_MAX = 0.42          # 상자 높이 ≤ 지도 높이의 42%
INSET_PAD = 10


def _ring_bbox(r):
    xs = [q[0] for q in r]; ys = [q[1] for q in r]
    return min(xs), max(xs), min(ys), max(ys)


def _ring_area(r):
    a = 0.0
    for i in range(len(r) - 1):
        a += r[i][0] * r[i + 1][1] - r[i + 1][0] * r[i][1]
    return abs(a) / 2


def _bbox_gap_km(a, b, kx):
    """두 경계 상자 사이 빈틈(km). 겹치면 0."""
    dx = max(0.0, max(a[0], b[0]) - min(a[1], b[1])) * 111.0 * kx
    dy = max(0.0, max(a[2], b[2]) - min(a[3], b[3])) * 111.0
    return math.hypot(dx, dy)


def split_remote(shapes, kx, force=()):
    """{area: [ring]} → (core {area: [ring]}, remote {area: [ring]}). remote 가 비면 먼 섬 없음.
    force 에 든 단위(인천 옹진처럼 섬으로만 된 군)는 가까운 섬까지 통째로 상자로 보낸다 — 안 그러면
    덕적군도가 징검다리로 본토에 붙어 지도가 남쪽으로 길어진다."""
    items = [(area, r, _ring_bbox(r), _ring_area(r)) for area, rs in shapes.items() for r in rs
             if area not in force]
    n = len(items)
    parent = list(range(n))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(n):
        for j in range(i + 1, n):
            if _bbox_gap_km(items[i][2], items[j][2], kx) < GAP_KM:
                parent[find(i)] = find(j)
    area_sum = {}
    for i, it in enumerate(items):
        area_sum[find(i)] = area_sum.get(find(i), 0.0) + it[3]
    core_id = max(area_sum, key=area_sum.get)
    core, remote = {}, {}
    for i, (area, r, _, _) in enumerate(items):
        (core if find(i) == core_id else remote).setdefault(area, []).append(r)
    for area in force:
        if area in shapes:
            remote.setdefault(area, []).extend(shapes[area])
    return core, remote


def build(profile, merge=False):
    geo = load_geojson()
    by_code = {str(f['properties']['code']): f for f in geo['features']}
    force_inset = ()
    if profile in GROUPS:
        groups, order = GROUPS[profile], ORDER[profile]
    else:
        groups, order = groups_from_profile(profile, geo)
        prof = json.loads((ROOT / 'tools' / 'profiles' / f'{profile}.json').read_text(encoding='utf-8'))
        force_inset = tuple(prof.get('map_inset_units') or ())

    shapes = {}
    for area in order:
        rings = []
        for code in groups[area]:
            f = by_code.get(code)
            if f is None:
                raise SystemExit(f'경계자료에 코드 {code}({area})가 없습니다')
            rings.extend(rings_of(f))
        shapes[area] = merge_rings(rings) if merge else rings

    pts = [p for rs in shapes.values() for r in rs for p in r]
    min_lon = min(p[0] for p in pts)
    max_lon = max(p[0] for p in pts)
    min_lat = min(p[1] for p in pts)
    max_lat = max(p[1] for p in pts)
    kx = math.cos(math.radians((min_lat + max_lat) / 2))

    # 먼 섬 분리 — 본토(core)만으로 틀을 잡는다. 먼 섬이 없으면 예전과 완전히 같다.
    core, remote = split_remote(shapes, kx, force_inset)
    if remote:
        cpts = [p for rs in core.values() for r in rs for p in r]
        min_lon = min(p[0] for p in cpts); max_lon = max(p[0] for p in cpts)
        min_lat = min(p[1] for p in cpts); max_lat = max(p[1] for p in cpts)
        kx = math.cos(math.radians((min_lat + max_lat) / 2))
    scale = (W - 2 * PAD) / ((max_lon - min_lon) * kx)
    H = round((max_lat - min_lat) * scale + 2 * PAD)

    # 먼 섬 상자(inset) — 자기 축척으로 구석에
    inset = None
    ox = oy = 0.0
    W_out, H_out = W, H
    if remote:
        rpts = [p for rs in remote.values() for r in rs for p in r]
        r_min_lon = min(p[0] for p in rpts); r_max_lon = max(p[0] for p in rpts)
        r_min_lat = min(p[1] for p in rpts); r_max_lat = max(p[1] for p in rpts)
        iw = W * INSET_W_RATIO
        iscale = (iw - 2 * INSET_PAD) / max(1e-9, (r_max_lon - r_min_lon) * kx)
        ih = (r_max_lat - r_min_lat) * iscale + 2 * INSET_PAD
        if ih > H * INSET_H_MAX:                      # 남북으로 길면 높이에 맞춰 줄인다
            iscale = (H * INSET_H_MAX - 2 * INSET_PAD) / max(1e-9, (r_max_lat - r_min_lat))
            iw = (r_max_lon - r_min_lon) * kx * iscale + 2 * INSET_PAD
            ih = H * INSET_H_MAX
        ccx = (min_lon + max_lon) / 2; ccy = (min_lat + max_lat) / 2
        rcx = (r_min_lon + r_max_lon) / 2; rcy = (r_min_lat + r_max_lat) / 2
        west, north = rcx < ccx, rcy > ccy
        # 본토 조각들의 화면 상자(임시 투영)로 네 구석의 겹침을 재고, 안 겹치는 구석이 있으면 그리로.
        # 전부 겹치면(경북처럼 시도가 틀을 꽉 채우면) 캔버스를 넓혀 먼 섬 쪽 바깥에 붙인다.
        def _sc(lon, lat):
            return ((lon - min_lon) * kx * scale + PAD, (max_lat - lat) * scale + PAD)
        boxes = []
        for rs in core.values():
            for r in rs:
                ps = [_sc(*q) for q in r]
                boxes.append((min(x for x, _ in ps), max(x for x, _ in ps), min(y for _, y in ps), max(y for _, y in ps)))

        def _overlap(x0, y0):
            s = 0.0
            for bx0, bx1, by0, by1 in boxes:
                s += max(0.0, min(x0 + iw, bx1) - max(x0, bx0)) * max(0.0, min(y0 + ih, by1) - max(y0, by0))
            return s
        corners = [(PAD, PAD), (W - PAD - iw, PAD), (PAD, H - PAD - ih), (W - PAD - iw, H - PAD - ih)]
        pref = corners.index((PAD if west else W - PAD - iw, PAD if north else H - PAD - ih))
        corners = [corners[pref]] + [c for i, c in enumerate(corners) if i != pref]
        best = min(corners, key=lambda c: _overlap(*c))
        ox = oy = 0.0                                   # 본토 조각을 밀어낼 양(캔버스를 왼쪽/위로 넓힐 때)
        if _overlap(*best) <= iw * ih * 0.02:
            ix, iy = best
        elif abs(rcx - ccx) * kx >= abs(rcy - ccy):      # 동서로 더 먼 섬 → 옆에 붙인다
            if west:
                ox = iw + 12; ix, iy = PAD, PAD
            else:
                ix, iy = W + 12, PAD
            W_out = W + iw + 12
        else:                                             # 남북 → 위/아래
            if north:
                oy = ih + 12; ix, iy = PAD, PAD
            else:
                ix, iy = PAD, H + 12
            H_out = H + ih + 12
        W_out, H_out = round(W_out, 1), round(H_out, 1)
        inset = {'x': round(ix, 1), 'y': round(iy, 1), 'w': round(iw, 1), 'h': round(ih, 1),
                 'areas': sorted(remote),
                 'proj': {'minLon': round(r_min_lon, 6), 'maxLat': round(r_max_lat, 6),
                          'kx': round(kx, 6), 'scale': round(iscale, 4), 'pad': INSET_PAD}}

        def prj_inset(lon, lat):
            return (num(ix + (lon - r_min_lon) * kx * iscale + INSET_PAD),
                    num(iy + (r_max_lat - lat) * iscale + INSET_PAD))

    def num(v):
        """자바스크립트와 같은 표기 — 855.0이 아니라 855. 기존 파일과 문자열까지 맞춘다."""
        v = round(v, 1)
        return int(v) if v == int(v) else v

    def prj(lon, lat):
        return (num((lon - min_lon) * kx * scale + PAD + ox),
                num((max_lat - lat) * scale + PAD + oy))

    regions = []
    for area in order:
        subpaths, xs, ys = [], [], []
        core_rings = core.get(area, []) if remote else shapes[area]
        for ring in core_rings:
            r = ring[:-1] if ring[0] == ring[-1] else ring
            proj = [prj(lon, lat) for lon, lat in r]
            xs += [p[0] for p in proj]
            ys += [p[1] for p in proj]
            # 마지막에 첫 점을 다시 찍고 Z — 기존 파일과 동일한 형식
            subpaths.append('M' + 'L'.join(f'{x},{y}' for x, y in proj + [proj[0]]) + 'Z')
        # 먼 섬은 상자 안에. 라벨(cx·cy)·경계상자는 본토 조각 기준, 본토 조각이 없는 관서(옹진·울릉)는 상자 기준
        ixs, iys = [], []
        for ring in (remote.get(area, []) if remote else []):
            r = ring[:-1] if ring[0] == ring[-1] else ring
            proj = [prj_inset(lon, lat) for lon, lat in r]
            ixs += [p[0] for p in proj]
            iys += [p[1] for p in proj]
            subpaths.append('M' + 'L'.join(f'{x},{y}' for x, y in proj + [proj[0]]) + 'Z')
        if xs:
            c = area_centroid(core_rings)
            cx, cy = prj(c[0], c[1]) if c else (num(sum(xs) / len(xs)), num(sum(ys) / len(ys)))
        else:
            c = area_centroid(remote[area])
            cx, cy = prj_inset(c[0], c[1]) if c else (num(sum(ixs) / len(ixs)), num(sum(iys) / len(iys)))
            xs, ys = ixs, iys
        bx, by = min(xs), min(ys)
        regions.append({'name': area, 'd': ''.join(subpaths),
                        'cx': cx, 'cy': cy, 'bx': bx, 'by': by,
                        'bw': num(max(xs) - bx), 'bh': num(max(ys) - by)})

    out = {'viewBox': f'0 0 {W_out} {H_out}', 'W': W_out, 'H': H_out, 'regions': regions,
           'proj': {'minLon': round(min_lon, 6), 'maxLat': round(max_lat, 6),
                    'kx': round(kx, 6), 'scale': round(scale, 4), 'pad': PAD + ox,
                    **({'padY': PAD + oy} if oy else {})}}
    if inset:
        out['insets'] = [inset]
        print(f'  먼 섬 상자: {", ".join(inset["areas"])} → ({inset["x"]},{inset["y"]}) {inset["w"]}x{inset["h"]}')
    return out


def emit(obj):
    return 'window.MAPGEO = ' + json.dumps(obj, ensure_ascii=False,
                                           separators=(',', ':')) + ';'


def verify():
    """현재 운영중인 map-geo.js(북부)를 그대로 재현하는지 대조."""
    cur_txt = (ROOT / 'map-geo.js').read_text(encoding='utf-8')
    cur = json.loads(cur_txt[cur_txt.index('=') + 1:].strip().rstrip(';'))
    new = build('north', merge=False)

    ok = True
    for k in ('viewBox', 'W', 'H'):
        same = cur[k] == new[k]
        ok &= same
        print(f'  {"O" if same else "X"} {k}: {new[k]} (운영 {cur[k]})')
    for k in cur['proj']:
        same = abs(float(cur['proj'][k]) - float(new['proj'][k])) < 1e-4
        ok &= same
        print(f'  {"O" if same else "X"} proj.{k}: {new["proj"][k]} (운영 {cur["proj"][k]})')

    cr = {r['name']: r for r in cur['regions']}
    for r in new['regions']:
        c = cr.get(r['name'])
        if not c:
            print(f'  X {r["name"]}: 운영 파일에 없음'); ok = False; continue
        dsame = c['d'] == r['d']
        csame = all(abs(c[k] - r[k]) < 0.15 for k in ('cx', 'cy'))
        bsame = all(abs(c[k] - r[k]) < 0.15 for k in ('bx', 'by', 'bw', 'bh'))
        ok &= dsame and bsame
        mark = 'O' if (dsame and bsame) else ('~' if bsame else 'X')
        note = '' if dsame else '  (경로 다름)'
        if not csame:
            note += f'  라벨위치 {r["cx"]},{r["cy"]} vs 운영 {c["cx"]},{c["cy"]}'
        print(f'  {mark} {r["name"]:4s} 점 {r["d"].count(",")}개{note}')
    print('\n==> 북부 지도 재현 성공 — 생성기 신뢰 가능' if ok
          else '\n==> 재현 실패 — 남부 지도 생성 금지')
    return ok


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--verify', action='store_true')
    ap.add_argument('--profile', help='north·south·all 또는 생성 프로파일 키(gangwon …)')
    ap.add_argument('--merge', action='store_true', help='시 안의 구 경계선 제거')
    ap.add_argument('--out', help='출력 파일명 (프로젝트 루트 기준)')
    a = ap.parse_args()
    if a.verify or not a.profile:
        verify()
    if a.profile:
        obj = build(a.profile, merge=a.merge)
        out = ROOT / (a.out or f'map-geo-{a.profile}.js')
        out.write_text(emit(obj), encoding='utf-8')
        print(f'생성 완료 → {out}  ({len(obj["regions"])}개 관서, viewBox {obj["viewBox"]})')
