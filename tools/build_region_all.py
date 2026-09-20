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
ROW_SIZES = [5, 6, 6, 6, 6, 5]      # 행별 관서 수 (합 34, 위=북쪽)


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

    # 경기도 소방서 순서 (사장님 지정, 2026-08-19). 가평은 동두천-가평-연천 사이.
    order = ['수원', '성남', '분당', '부천', '안양', '안산', '용인', '평택', '송탄',
             '광명', '시흥', '군포', '화성', '이천', '김포', '광주', '안성', '하남',
             '의왕', '오산', '여주', '양평', '과천', '고양', '일산', '의정부',
             '남양주', '파주', '구리', '포천', '양주', '동두천', '가평', '연천']
    if len(order) != 34:
        raise SystemExit(f'관서가 34개가 아니다: {len(order)}개')
    # 송탄은 지도 경계가 없다(평택시에 하위 구가 없어 시군구 자료로 분리 불가).
    # 배치도 자리는 필요하므로 평택 중심에서 북쪽으로 조금 올린 가상 좌표를 쓴다
    # — 송탄소방서 관할이 평택 북부(서정동·진위면·서탄면)라 방향이 맞다.
    if '송탄' not in cent and '평택' in cent:
        px, py = cent['평택']
        cent['송탄'] = (px, py - 40)
    missing = [x for x in order if x not in cent]
    if missing:
        raise SystemExit(f'배치 좌표가 없는 관서: {missing}')

    # 소방서가 시(市)를 나눠 맡는 곳 — 하위관서: 소속 시군.
    # 기상청 자료는 시군 단위라 하천·산불권역은 소속 시군 것을 그대로 물려받고,
    # 실측 강수·바람만 자기 관할 관측소 값으로 갈라진다(프로파일에서 관측소를 나눠 뒀다).
    SUB = {'분당': '성남', '송탄': '평택', '일산': '고양'}
    n_admin = dict(n['admin'])
    n_rmatch = dict(n['riverMatch'])
    n_fgroup = dict(n['fireGroup'])

    conf = {
        'key': 'all',
        'label': '경기도',
        'office': '경기도',
        'home': '수원',                       # 도청 소재지. merge_all.py 의 HOME_FROM 과 맞출 것
        'countText': '34개 소방서',
        'dataHost': 'https://ggweather.visanu81.workers.dev',
        # 특보 area 에 이 낱말이 있으면 '관할 전역'. '경기도'는 절대 넣지 말 것 —
        # area 가 '경기도, 고양'처럼 늘 도명으로 시작해 모든 관서가 걸린다.
        # 소방서가 시(市)를 나눠 맡는 곳만 하천을 '관측소 코드'로 직접 지정한다.
        # 시군으로 고르면 송탄에 평택 도심 하천이, 성남에 분당구 하천이 뜬다
        # (2026-08-19 사장님 지적). 근거는 한강홍수통제소 원장의 관측소 주소:
        #   1018650 궁내교=성남 분당구 정자동 / 1018653 둔전교=성남 수정구 둔전동
        #   1101635 군문교=평택 군문동 / 1101663 진위1교=평택 진위면
        #   1101670 동연교=평택 고덕면 (평택 관할 — 사장님 확인 2026-08-19)
        #   1019667 원당교=고양 덕양구  → 일산 관내엔 수위관측소가 없다(빈 목록)
        # 표에 없는 관서는 지금처럼 시군으로 고른다.
        'riverCodes': {
            '분당': ['1018650'],
            '성남': ['1018653'],
            '송탄': ['1101663'],
            '평택': ['1101635', '1101670'],
            '고양': ['1019667'],
            '일산': [],
        },
        # 권역 필터 — 화면 위 '경기 전체 / 경기북부 / 경기남부' 선택.
        # 고르면 지도·관서목록·상단요약·특보·하천이 모두 그 권역만 보인다.
        # 목록은 손으로 적지 않고 북부 원본(region.js)에 있는지로 나눈다 —
        # 관서가 늘거나 옮겨져도 다시 생성만 하면 맞는다.
        'scopes': {
            '경기북부': [x for x in order if x in set(n['order'])],
            '경기남부': [x for x in order if x not in set(n['order'])],
        },
        'wideNames': ['경기북부', '경기남부'],
        # 접속 주소(호스트 첫 토막) → 기본 권역/기본 관서. 세 주소가 같은 전체판을
        # 서빙하되, 북부 주소로 열면 북부부터 보이게 한다(2026-08-28 사장님 결정).
        # 저장된 사용자 선택(localStorage)이 있으면 그게 우선이다.
        'hostScope': {'gyeonggi-dashboard': '경기북부', 'gyeonggi-dashboard-2': '경기북부',
                      'weather': '경기남부'},
        'hostHome': {'gyeonggi-dashboard': '동두천', 'gyeonggi-dashboard-2': '동두천',
                     'weather': '수원'},
        'order': order,
        'warnOrder': ['경기도'] + order,
        'pos': build_pos(cent, order),
        'admin': merge_dict(n_admin, s['admin'], 'admin'),
        'riverMatch': merge_dict(n_rmatch, s['riverMatch'], 'riverMatch'),
        'fireGroup': merge_dict(n_fgroup, s['fireGroup'], 'fireGroup'),
        # 관서명 → 데이터상의 시군명. 하위관서는 소속 시군 값을 본다.
        # (기온·예보·특보·미세먼지가 시군 단위로만 나오기 때문. 실측 강수·바람은
        #  관서명 키로 따로 들어와서 이 별칭과 무관하게 관할 값이 쓰인다.)
        'alias': dict(SUB),
        'floodKeywords': sorted(set(n['floodKeywords']) | set(s['floodKeywords'])),
        # 임진강 필승교·군남댐은 경기 전체에서도 늘 봐야 하는 지점이라 그대로 둔다
        'topRiversTitle': n.get('topRiversTitle') or '주요 감시',
        'topRivers': list(n.get('topRivers') or []),
        'meteoV2': True,
        'riverMeta': merge_dict(n['riverMeta'], s['riverMeta'], 'riverMeta'),
    }

    # 하위관서 — 소속 시군 값을 물려받는다
    ADMIN_SUB = {'분당': '성남시 분당구', '송탄': '평택시 송탄', '일산': '고양시 일산'}
    for sub, parent in SUB.items():
        conf['admin'][sub] = ADMIN_SUB[sub]
        if parent in conf['riverMatch']:
            conf['riverMatch'][sub] = list(conf['riverMatch'][parent])
        if parent in conf['fireGroup']:
            conf['fireGroup'][sub] = conf['fireGroup'][parent]
    miss = [x for x in order if x not in conf['admin']]
    if miss:
        raise SystemExit(f'admin 이 빠진 관서: {miss}')

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
