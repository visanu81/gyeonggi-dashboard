# -*- coding: utf-8 -*-
"""region-all.js 생성 — 경기 전체(31개 시군) 화면 설정.

경기북부(region.js) + 경기남부(region-south.js)를 합쳐서 만든다. 두 파일의
키가 하나도 겹치지 않는 것을 확인하고 합치므로(겹치면 예외) 값이 뒤섞이지 않는다.

배치도(pos)만 새로 만든다 — 손으로 31칸을 찍으면 실제 지리와 어긋나기 쉬워서,
map-geo-all.js 가 계산해 둔 시군 중심좌표를 벌집 격자에 담는다.
지도.html 의 배치는  x = 8 + (열 + (행%2)*0.5) * 88,  y = 16 + 행 * 76  이다.

⚠ 일산은 뺀다. 소방서 관할 단위지 시군이 아니라서 경기도 화면엔 31개만 있어야 한다.
   (북부 전용 사이트는 관서가 단위라 지금처럼 11개가 맞다)

실행:  python tools/build_region_all.py
"""
import json
import re
import subprocess
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
COLS = 7          # 벌집 격자 열 수
ROW_SIZES = [4, 6, 5, 5, 6, 5]      # 행별 시군 수 (합 31, 위=북쪽)


def load_conf(js_file):
    """region*.js 를 node 로 읽어 REGION_CONF 를 JSON 으로 받는다."""
    code = (f"global.window={{}};require({json.dumps(str(ROOT / js_file))});"
            "process.stdout.write(JSON.stringify(window.REGION_CONF));")
    r = subprocess.run(['node', '-e', code], capture_output=True, text=True,
                       encoding='utf-8', cwd=str(ROOT))
    if r.returncode != 0:
        raise SystemExit(f'{js_file} 읽기 실패: {r.stderr[:300]}')
    return json.loads(r.stdout)


def load_map():
    t = (ROOT / 'map-geo-all.js').read_text(encoding='utf-8')
    d = json.loads(t[t.find('{'):t.rfind('}') + 1])
    return {r['name']: (r['cx'], r['cy']) for r in d['regions']}


def merge_dict(a, b, label):
    dup = sorted(set(a) & set(b))
    if dup:
        raise SystemExit(f'{label}: 북부·남부에 같은 키가 있다 → {dup}')
    return {**a, **b}


def build_pos(cent, order):
    """시군 중심좌표 → 벌집 격자 자리. 북→남으로 행을 나누고 행 안에서 서→동."""
    if sum(ROW_SIZES) != len(order):
        raise SystemExit(f'ROW_SIZES 합({sum(ROW_SIZES)})과 시군 수({len(order)})가 다르다')
    by_lat = sorted(order, key=lambda n: cent[n][1])      # cy 작을수록 북쪽
    pos, i = {}, 0
    for row, cnt in enumerate(ROW_SIZES):
        band = sorted(by_lat[i:i + cnt], key=lambda n: cent[n][0])   # 행 안에서 서→동
        i += cnt
        # 열을 고르게 펴되, 실제 경도 순서를 유지한다
        used = set()
        for k, name in enumerate(band):
            want = round(k * (COLS - 1) / max(1, cnt - 1)) if cnt > 1 else COLS // 2
            col = want
            while col in used and col < COLS - 1:
                col += 1
            while col in used and col > 0:
                col -= 1
            used.add(col)
            pos[name] = [col, row]
    return pos


def ascii_map(pos, order):
    rows = max(p[1] for p in pos.values()) + 1
    out = []
    for r in range(rows):
        cells = {p[0]: n for n, p in pos.items() if p[1] == r}
        line = '  ' * (r % 2)
        for c in range(COLS):
            line += f'{cells.get(c, ""):　<4s}'.replace(' ', '　') if cells.get(c) else '　　　　'
        out.append(line.rstrip())
    return '\n'.join(out)


def main():
    n = load_conf('region.js')
    s = load_conf('region-south.js')
    cent = load_map()

    order = [x for x in n['order'] if x != '일산'] + list(s['order'])
    missing = [x for x in order if x not in cent]
    if missing:
        raise SystemExit(f'지도에 없는 시군: {missing}')
    if len(order) != 31:
        raise SystemExit(f'시군이 31개가 아니다: {len(order)}개')

    n_admin = {k: v for k, v in n['admin'].items() if k != '일산'}
    n_rmatch = {k: v for k, v in n['riverMatch'].items() if k != '일산'}
    n_fgroup = {k: v for k, v in n['fireGroup'].items() if k != '일산'}

    conf = {
        'key': 'all',
        'label': '경기도',
        'office': '경기도',
        'home': '수원',                       # 도청 소재지. merge_all.py 의 HOME_FROM 과 맞출 것
        'countText': '31개 시군',
        'dataHost': 'https://ggweather.visanu81.workers.dev',
        'order': order,
        'warnOrder': ['경기도'] + order,
        'pos': build_pos(cent, order),
        'admin': merge_dict(n_admin, s['admin'], 'admin'),
        'riverMatch': merge_dict(n_rmatch, s['riverMatch'], 'riverMatch'),
        'fireGroup': merge_dict(n_fgroup, s['fireGroup'], 'fireGroup'),
        'alias': {'일산': '고양'},            # 옛 링크·북부 표기가 들어와도 고양으로 받는다
        'floodKeywords': sorted(set(n['floodKeywords']) | set(s['floodKeywords'])),
        # 임진강 필승교·군남댐은 경기 전체에서도 늘 봐야 하는 지점이라 그대로 둔다
        'topRiversTitle': n.get('topRiversTitle') or '주요 감시',
        'topRivers': list(n.get('topRivers') or []),
        'meteoV2': True,
        'riverMeta': merge_dict(n['riverMeta'], s['riverMeta'], 'riverMeta'),
    }

    body = (
        '// ===== 경기 전체(31개 시군) 화면 설정 =====\n'
        '// tools/build_region_all.py 가 region.js + region-south.js 를 합쳐 만든다.\n'
        '// 직접 고치지 말 것 — 다시 생성하면 날아간다. 두 원본을 고치고 다시 돌릴 것.\n'
        '//   python tools/build_region_all.py\n'
        '// 배포 시 region.js 를 이 파일로 갈아끼운다(.github/workflows/deploy-ggweather.yml).\n'
        'window.REGION_CONF = ' + json.dumps(conf, ensure_ascii=False, indent=1) + ';\n'
    )
    (ROOT / 'region-all.js').write_text(body, encoding='utf-8')

    print(f'region-all.js 저장 ({len(body):,} 바이트)')
    print(f'  시군 {len(order)}개 · 하천기준 {len(conf["riverMeta"])}곳 · '
          f'산불권역 {len(set(conf["fireGroup"].values()))}개 · '
          f'홍수키워드 {len(conf["floodKeywords"])}개')
    print('\n배치도(위=북쪽):')
    print(ascii_map(conf['pos'], order))
    return 0


if __name__ == '__main__':
    sys.exit(main())
