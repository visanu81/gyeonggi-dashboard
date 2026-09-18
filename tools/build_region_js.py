# -*- coding: utf-8 -*-
"""region-<key>.js 생성 — 생성 프로파일(tools/profiles/<key>.json)로 화면 설정을 만든다.

전국 확장 1단계(2026-09-18). 경기북부·남부의 region.js 는 손으로 썼지만 시도가 17개면
그럴 수 없다. 프로파일(뒷단 값) + 지도(map-geo-<key>.js 의 시군 중심좌표)만으로
화면이 필요로 하는 REGION_CONF 를 전부 만든다.

  · order / warnOrder   북→남·서→동 (프로파일 region_order)
  · pos                 벌집 격자 배치도 — build_region_all.py 와 같은 방식(중심좌표 → 행·열)
  · admin / fireGroup / riverMatch / floodKeywords / riverMeta   프로파일에서
  · wideNames           특보 발표문에서 '시도 전역'을 뜻하는 말들

실행:  python tools/build_region_js.py gangwon        # → region-gangwon.js
       (map-geo-gangwon.js 가 먼저 있어야 한다: build_map_geo.py --profile gangwon --merge)
"""
import json
import math
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent


def load_map(key):
    t = (ROOT / f'map-geo-{key}.js').read_text(encoding='utf-8')
    d = json.loads(t[t.find('{'):t.rfind('}') + 1])
    return {r['name']: (r['cx'], r['cy']) for r in d['regions']}


def build_pos(cent, order):
    """시군 중심좌표 → 벌집 격자. 북→남으로 행을 나누고 행 안에서 서→동.
    지도.html 의 배치:  x = 8 + (열 + (행%2)*0.5) * 88,  y = 16 + 행 * 76"""
    n = len(order)
    cols = 5 if n <= 15 else (6 if n <= 24 else 7)
    rows = max(1, math.ceil(n / cols))
    base, extra = divmod(n, rows)
    row_sizes = [base + (1 if i < extra else 0) for i in range(rows)]
    by_lat = sorted(order, key=lambda a: cent[a][1])          # cy 작을수록 북쪽
    pos, i = {}, 0
    for row, cnt in enumerate(row_sizes):
        band = sorted(by_lat[i:i + cnt], key=lambda a: cent[a][0])
        i += cnt
        used = set()
        for k, name in enumerate(band):
            col = round(k * (cols - 1) / max(1, cnt - 1)) if cnt > 1 else cols // 2
            while col in used and col < cols - 1:
                col += 1
            while col in used and col > 0:
                col -= 1
            used.add(col)
            pos[name] = [col, row]
    return pos, cols


def ascii_map(pos, cols):
    rows = max(p[1] for p in pos.values()) + 1
    out = []
    for r in range(rows):
        cells = {p[0]: n for n, p in pos.items() if p[1] == r}
        line = '　' * (r % 2)
        for c in range(cols):
            line += f'{cells[c]:　<4s}' if c in cells else '　　　　'
        out.append(line.rstrip('　'))
    return '\n'.join(out)


def build(key):
    prof = json.loads((ROOT / 'tools' / 'profiles' / f'{key}.json').read_text(encoding='utf-8'))
    cent = load_map(key)
    wide = prof['wide_label']
    order = list(prof['region_order'][1:])          # [0]은 시도 전역 이름(세종은 단위 이름과 같다)
    missing = [a for a in order if a not in cent]
    if missing:
        raise SystemExit(f'지도에 없는 시군: {missing}')
    pos, cols = build_pos(cent, order)

    fire_group = {}
    for g, members in prof['fire_groups'].items():
        for m in members:
            fire_group[m] = g
    label = prof['label']
    admins = list(prof['admin'].values())
    if any(a.endswith('구') for a in admins):
        count_text = f'{len(order)}개 ' + ('구·군' if any(a.endswith('군') for a in admins) else '구')
    else:
        count_text = f'{len(order)}개 시군'
    conf = {
        'key': key,
        'label': wide,
        'office': wide,
        'home': prof['home'],
        'countText': count_text,
        'dataHost': f"https://{prof['host']}",
        'wideNames': sorted({wide, label, prof['full'], *prof.get('wide_names', []),
                             f'{label}북부', f'{label}중부', f'{label}남부', f'{label}동부', f'{label}서부',
                             f'{label}영동', f'{label}영서', f'{label}산지', f'{label}내륙'}),
        'order': order,
        'warnOrder': [wide] + order,
        'pos': pos,
        'admin': prof['admin'],
        'riverMatch': {a: [a] for a in order},
        'fireGroup': fire_group,
        'alias': {},
        'floodKeywords': sorted(prof['flood_keywords']),
        'topRiversTitle': '주요 감시',
        'topRivers': [],
        'meteoV2': True,
        'riverMeta': prof['river_meta'],
    }
    body = json.dumps(conf, ensure_ascii=False, indent=1)
    out = (f'// ===== {wide} 화면 설정 =====\n'
           f'// tools/build_region_js.py 가 tools/profiles/{key}.json + map-geo-{key}.js 로 만든다.\n'
           f'// 직접 고치지 말 것 — 다시 생성하면 날아간다. 프로파일을 고치고 다시 돌릴 것.\n'
           f'//   python tools/build_region_js.py {key}\n'
           f'window.REGION_CONF = {body};\n')
    path = ROOT / f'region-{key}.js'
    path.write_text(out, encoding='utf-8')
    print(f'생성 완료 → {path}  ({len(order)}개 시군, 배치도 {cols}열)')
    print(ascii_map(pos, cols))
    return conf


if __name__ == '__main__':
    if len(sys.argv) < 2:
        raise SystemExit('사용법: python tools/build_region_js.py <프로파일 키>')
    build(sys.argv[1])
