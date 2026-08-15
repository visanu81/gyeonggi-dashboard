# -*- coding: utf-8 -*-
"""region_profiles.py의 경기북부 값이 update_data.py 원본과 같은지 대조.

왜 필요한가: 북부 상수를 새 파일로 옮겨 적는 과정에서 숫자 하나만 틀려도
운영 상황판이 조용히 틀린 값을 보여준다(관측소 번호 하나가 틀리면 그 관서 강수량이
엉뚱해지는데 화면상으로는 정상처럼 보인다). 사람 눈으로 대조하지 않고 기계가 한다.

update_data.py를 import하지 않고 소스를 ast로 읽어 비교한다 — import하면 .env를
읽고 API를 부르는 등 부작용이 있고, 리팩터링 후에는 상수가 사라져 비교 자체가 불가능.
그래서 '리팩터링 직전 원본'을 git에서 꺼내 비교한다.

실행:  python tools/verify_profiles.py [기준_git_리비전]
"""
import ast
import subprocess
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
import region_profiles as RP  # noqa: E402

# region_profiles의 이름 → update_data.py 원본에서의 이름
PAIRS = [
    ('NORTH_REGIONS', 'REGIONS'),
    ('NORTH_PM_STATIONS', 'PM_STATIONS'),
    ('NORTH_AWS_STATIONS', 'AWS_STATIONS'),
    ('NORTH_AWS_FALLBACK', 'AWS_FALLBACK'),
    ('NORTH_RIVER_STATIONS', 'RIVER_STATIONS'),
    ('NORTH_KEYWORDS', 'NORTH_GG_KEYWORDS'),
    ('NORTH_REG_MAP', 'NORTH_GG_REG_MAP'),
    ('NORTH_REGION_ORDER', '_REGION_ORDER'),
]


def module_consts(src):
    """모듈 최상단 대입문에서 리터럴 상수만 뽑는다."""
    out = {}
    for node in ast.parse(src).body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        t = node.targets[0]
        if not isinstance(t, ast.Name):
            continue
        try:
            out[t.id] = ast.literal_eval(node.value)
        except (ValueError, TypeError, SyntaxError):
            pass
    return out


def func_consts(src, funcname):
    """함수 안에서 대입된 리터럴 상수 (fetch_fire의 sigun_map/groups 등)."""
    out = {}
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.FunctionDef) and node.name == funcname:
            for sub in ast.walk(node):
                if isinstance(sub, ast.Assign) and len(sub.targets) == 1 \
                        and isinstance(sub.targets[0], ast.Name):
                    try:
                        out[sub.targets[0].id] = ast.literal_eval(sub.value)
                    except (ValueError, TypeError, SyntaxError):
                        pass
    return out


def baseline_source(rev):
    """비교 기준 소스 — git에서 리팩터링 이전 update_data.py를 꺼낸다."""
    try:
        r = subprocess.run(['git', 'show', f'{rev}:tools/update_data.py'],
                           cwd=str(ROOT), capture_output=True, timeout=30)
        if r.returncode == 0 and r.stdout:
            return r.stdout.decode('utf-8')
    except Exception as e:
        print(f'  (git에서 기준 소스를 못 꺼냄: {type(e).__name__})')
    return None


def main():
    rev = sys.argv[1] if len(sys.argv) > 1 else 'HEAD'
    src = baseline_source(rev)
    where = f'git {rev}'
    if src is None:
        src = (ROOT / 'tools' / 'update_data.py').read_text(encoding='utf-8')
        where = '현재 파일'
    print(f'기준: {where}\n')

    mods = module_consts(src)
    fire = func_consts(src, 'fetch_fire')
    flood = func_consts(src, 'fetch_flood_forecast')

    ok = True
    print('=== 경기북부 상수 대조 ===')
    for mine, theirs in PAIRS:
        a, b = getattr(RP, mine), mods.get(theirs)
        if b is None:
            print(f'  · {theirs:20s} 원본에 없음(이미 리팩터링됨) — 건너뜀')
            continue
        same = a == b
        ok &= same
        n = len(a) if hasattr(a, '__len__') else 1
        print(f'  {"O" if same else "X"} {theirs:20s} {n}개')
        if not same:
            if isinstance(a, dict) and isinstance(b, dict):
                for k in set(a) | set(b):
                    if a.get(k) != b.get(k):
                        print(f'      [{k}] 프로파일={a.get(k)}  원본={b.get(k)}')
            else:
                print(f'      프로파일={a}\n      원본  ={b}')

    for mine, theirs, pool, label in [
        ('NORTH_FIRE_SIGUN_MAP', 'sigun_map', fire, '산불 시군매핑'),
        ('NORTH_FIRE_GROUPS', 'groups', fire, '산불 권역그룹'),
        ('NORTH_FLOOD_KEYWORDS', 'north_keywords', flood, '홍수예보 키워드'),
    ]:
        b = pool.get(theirs)
        if b is None:
            print(f'  · {label:14s} 원본에 없음 — 건너뜀')
            continue
        a = getattr(RP, mine)
        same = a == b
        ok &= same
        print(f'  {"O" if same else "X"} {label:14s} {len(a)}개')
        if not same:
            print(f'      프로파일={a}\n      원본  ={b}')

    print('\n=== 경기남부 무결성 점검 ===')
    s = RP.PROFILES['south']
    names = [r['name'] for r in s['regions']]
    checks = [
        ('시군 21개', len(names) == 21),
        ('시군명 중복 없음', len(set(names)) == len(names)),
        ('격자 좌표 모두 있음', all(r['nx'] and r['ny'] for r in s['regions'])),
        ('산불코드 10자리', all(len(r['sgg']) == 10 for r in s['regions'])),
        ('AWS 관측소 모든 시군 보유', all(s['aws_stations'].get(n) for n in names)),
        ('미세먼지 측정소 모든 시군 보유', all(s['pm_stations'].get(n) for n in names)),
        ('하천 관측소 모든 시군 보유',
         all(any(r['sigun'] == n for r in s['river_stations']) for n in names)),
        ('하천 기준수위 관심<경계',
         all(r['warning'] < r['danger'] for r in s['river_stations']
             if r['warning'] is not None and r['danger'] is not None)),
        ('표시순서에 전 시군 포함', set(names) <= set(s['region_order'])),
        ('특보구역 코드 21개 + 광역', len(s['reg_map']) == 22),
        ('산불 권역이 전 시군 포함',
         set(x for g in s['fire_groups'].values() for x in g) == set(names)),
        ('북부와 시군명 겹침 없음',
         not (set(names) & {r['name'] for r in RP.PROFILES['north']['regions']})),
    ]
    for label, good in checks:
        ok &= good
        print(f'  {"O" if good else "X"} {label}')

    print('\n==> 전부 통과' if ok else '\n==> 문제 있음 — 배포 금지')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
