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
GROUPS['all'] = dict(GROUPS['south'])
GROUPS['all'].update({k: v for k, v in GROUPS['north'].items() if k not in ('고양', '일산')})
GROUPS['all']['고양'] = GROUPS['north']['고양'] + GROUPS['north']['일산']   # 덕양+일산동+일산서

# 화면 표시 순서(북→남, 서→동). 지도 자체엔 영향 없고 파일 내 순서만 정한다.
ORDER = {
    'north': ['의정부', '양주', '동두천', '포천', '연천', '가평', '남양주', '구리',
              '파주', '고양', '일산'],
    'south': ['김포', '하남', '부천', '광명', '양평', '과천', '성남', '광주', '시흥',
              '안양', '군포', '의왕', '안산', '수원', '용인', '이천', '여주', '화성',
              '오산', '안성', '평택'],
}
ORDER['all'] = (['연천', '포천', '동두천', '양주', '파주', '가평', '의정부', '고양',
                 '남양주', '구리']                       # 북부 10 (일산은 고양에 포함)
                + ORDER['south'])                        # 남부 21


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


def build(profile, merge=False):
    geo = load_geojson()
    by_code = {str(f['properties']['code']): f for f in geo['features']}
    groups, order = GROUPS[profile], ORDER[profile]

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
    scale = (W - 2 * PAD) / ((max_lon - min_lon) * kx)
    H = round((max_lat - min_lat) * scale + 2 * PAD)

    def num(v):
        """자바스크립트와 같은 표기 — 855.0이 아니라 855. 기존 파일과 문자열까지 맞춘다."""
        v = round(v, 1)
        return int(v) if v == int(v) else v

    def prj(lon, lat):
        return (num((lon - min_lon) * kx * scale + PAD),
                num((max_lat - lat) * scale + PAD))

    regions = []
    for area in order:
        subpaths, xs, ys = [], [], []
        for ring in shapes[area]:
            r = ring[:-1] if ring[0] == ring[-1] else ring
            proj = [prj(lon, lat) for lon, lat in r]
            xs += [p[0] for p in proj]
            ys += [p[1] for p in proj]
            # 마지막에 첫 점을 다시 찍고 Z — 기존 파일과 동일한 형식
            subpaths.append('M' + 'L'.join(f'{x},{y}' for x, y in proj + [proj[0]]) + 'Z')
        c = area_centroid(shapes[area])
        cx, cy = prj(c[0], c[1]) if c else (num(sum(xs) / len(xs)), num(sum(ys) / len(ys)))
        bx, by = min(xs), min(ys)
        regions.append({'name': area, 'd': ''.join(subpaths),
                        'cx': cx, 'cy': cy, 'bx': bx, 'by': by,
                        'bw': num(max(xs) - bx), 'bh': num(max(ys) - by)})

    return {'viewBox': f'0 0 {W} {H}', 'W': W, 'H': H, 'regions': regions,
            'proj': {'minLon': round(min_lon, 6), 'maxLat': round(max_lat, 6),
                     'kx': round(kx, 6), 'scale': round(scale, 4), 'pad': PAD}}


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
    ap.add_argument('--profile', choices=['north', 'south', 'all'])
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
