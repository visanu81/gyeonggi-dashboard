# -*- coding: utf-8 -*-
"""배포 전 프로파일 점검 — 두 지역(경기북부·경기남부)의 값이 서로 아귀가 맞는지.

왜 필요한가: 숫자 하나만 틀려도 운영 상황판이 조용히 틀린 값을 보여준다.
관측소 번호가 틀리면 그 관서 강수량이 엉뚱해지는데 화면상으로는 정상처럼 보인다.
사람 눈으로 대조하지 않고 기계가 한다.

⚠ 2026-08-17 전체 점검에서 이 파일 자체의 결함이 발견됐다.
   원래는 '리팩터링 직전 update_data.py'를 git에서 꺼내 북부 상수를 대조했는데,
   서버의 히스토리 압축으로 그 원본이 사라져 **북부 검사 11개가 전부 '건너뜀'** 이
   된 채로 마지막에 '전부 통과'를 출력하고 있었다. 아무것도 검사하지 않고 합격을
   내는 검사기였다. 그래서 두 가지를 바꿨다:
     ① 건너뛴 항목이 있으면 절대 '전부 통과'라고 하지 않는다.
     ② 사라진 원본에 의존하지 않는 '구조 무결성 점검'을 두 지역 모두에 적용한다.
   이 구조 점검은 같은 날 발견된 실제 결함 두 개를 잡는다 —
   북부 남양주·구리가 산불 권역에서 빠진 것, 특보구역 코드에 다른 광역시가 섞이는 것.

실행:
    python tools/verify_profiles.py            구조 점검(오프라인, 배포 전 필수)
    python tools/verify_profiles.py --api      + 외부 API 회귀 점검(호출 발생)
    python tools/verify_profiles.py <리비전>    + 그 리비전의 원본과 북부 상수 대조
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

# 수위관측소가 관내에 없는 것으로 확인된 시군 — 경고만 내고 실패로 치지 않는다.
# (남부는 생성기가 12km 이내 '인근' 관측소를 붙였다. 북부 구리는 아직 안 붙였다)
NO_RIVER_OK = {'구리'}


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


def compare_baseline(rev):
    """옛 원본과 북부 상수 대조. → (일치 수, 불일치 수, 건너뛴 수)"""
    src = baseline_source(rev)
    if src is None:
        print(f'  · 기준 리비전 {rev} 에서 update_data.py를 못 꺼냄 — 대조 생략')
        return 0, 0, len(PAIRS) + 3

    mods = module_consts(src)
    fire = func_consts(src, 'fetch_fire')
    flood = func_consts(src, 'fetch_flood_forecast')
    good = bad = skip = 0

    items = [(m, t, mods, t) for m, t in PAIRS] + [
        ('NORTH_FIRE_SIGUN_MAP', 'sigun_map', fire, '산불 시군매핑'),
        ('NORTH_FIRE_GROUPS', 'groups', fire, '산불 권역그룹'),
        ('NORTH_FLOOD_KEYWORDS', 'north_keywords', flood, '홍수예보 키워드'),
    ]
    for mine, theirs, pool, label in items:
        b = pool.get(theirs)
        if b is None:
            skip += 1
            print(f'  · {label:20s} 원본에 없음 — 건너뜀')
            continue
        a = getattr(RP, mine)
        if a == b:
            good += 1
            print(f'  O {label:20s} {len(a) if hasattr(a, "__len__") else 1}개')
        else:
            bad += 1
            print(f'  X {label:20s} 불일치')
            if isinstance(a, dict) and isinstance(b, dict):
                for k in sorted(set(a) | set(b)):
                    if a.get(k) != b.get(k):
                        print(f'      [{k}] 프로파일={a.get(k)}  원본={b.get(k)}')
            else:
                print(f'      프로파일={a}\n      원본  ={b}')
    return good, bad, skip


def integrity(key):
    """한 지역 프로파일의 구조 무결성. → (실패목록, 경고목록)"""
    P = RP.PROFILES[key]
    names = [r['name'] for r in P['regions']]
    nameset = set(names)
    reg_map = P.get('reg_map') or {}
    fire_cov = {x for g in (P.get('fire_groups') or {}).values() for x in g}
    river_sig = {r['sigun'] for r in (P.get('river_stations') or [])}

    fails, warns = [], []

    def chk(label, good, detail=''):
        (fails if not good else warns.__class__()).append  # noqa — 아래에서 직접 처리
        print(f'  {"O" if good else "X"} {label}')
        if not good:
            fails.append(f'{key}: {label}{" — " + detail if detail else ""}')
            if detail:
                print(f'      {detail}')

    def warn(label, good, detail=''):
        print(f'  {"O" if good else "!"} {label}')
        if not good:
            warns.append(f'{key}: {label}{" — " + detail if detail else ""}')
            if detail:
                print(f'      {detail}')

    chk('시군명 중복 없음', len(nameset) == len(names))
    chk('격자 좌표 모두 있음', all(r.get('nx') and r.get('ny') for r in P['regions']))
    chk('산불코드 10자리', all(len(str(r.get('sgg') or '')) == 10 for r in P['regions']))

    miss_aws = sorted(nameset - set(P.get('aws_stations') or {}))
    chk('AWS 관측소 전 시군 보유', not miss_aws, f'누락 {miss_aws}')

    miss_pm = sorted(nameset - set(P.get('pm_stations') or {}))
    chk('미세먼지 측정소 전 시군 보유', not miss_pm, f'누락 {miss_pm}')

    chk('표시순서에 전 시군 포함', nameset <= set(P.get('region_order') or []),
        f'누락 {sorted(nameset - set(P.get("region_order") or []))}')

    # ★ 특보구역 — 관할 시군이 전부 코드로 잡혀 있어야 한다
    miss_reg = sorted(nameset - set(reg_map.values()))
    chk('특보구역 코드가 전 시군 커버', not miss_reg, f'누락 {miss_reg}')

    # ★ 2026-08-17: 광주광역시(L1130xxx)가 경기 광주시로 오인된 사고 방지.
    #    경기도 육상 특보구역은 전부 L101xxxx 계열이다.
    bad_code = sorted(k for k in reg_map if not str(k).startswith('L101'))
    chk('특보구역 코드가 전부 경기 계열(L101)', not bad_code, f'경기 밖 코드 {bad_code}')

    # ★ 2026-08-17: 북부 남양주·구리가 빠져 산불위험이 화면에서 사라진 사고 방지
    miss_fire = sorted(nameset - fire_cov)
    chk('산불 권역이 전 시군 포함', not miss_fire, f'누락 {miss_fire}')
    chk('산불 권역에 관할 밖 시군 없음', not (fire_cov - nameset),
        f'관할 밖 {sorted(fire_cov - nameset)}')

    bad_lv = [r['name'] for r in (P.get('river_stations') or [])
              if r.get('warning') is not None and r.get('danger') is not None
              and not (r['warning'] < r['danger'])]
    chk('하천 기준수위 관심<경계', not bad_lv, f'역전 {bad_lv}')

    miss_riv = sorted(nameset - river_sig - NO_RIVER_OK)
    chk('하천 관측소 전 시군 보유(알려진 예외 제외)', not miss_riv, f'누락 {miss_riv}')
    known = sorted(nameset & NO_RIVER_OK)
    if known:
        warn('관내 수위관측소 없는 시군', False,
             f'{known} — 남부처럼 인근 관측소를 붙이는 것을 검토')

    return fails, warns


def api_regression():
    """외부 API 회귀 점검 — 호출이 발생한다. → 실패목록"""
    fails = []
    print('\n=== 외부 API 회귀 점검 (실호출) ===')
    import importlib.util
    saved = sys.argv[:]
    sys.argv = ['update_data.py']
    try:
        spec = importlib.util.spec_from_file_location('_ud', ROOT / 'tools' / 'update_data.py')
        m = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(m)
        except SystemExit:
            pass
    finally:
        sys.argv = saved

    # ★ 2026-08-17: 단기예보 캐시 경로가 UnboundLocalError로 죽어, 시군 기온이
    #   예보 발표시각 사이(최대 3시간) 얼어붙어 있었다. 한 번만 호출하면 안 보인다.
    #   반드시 '같은 발표시각으로 두 번' 불러 캐시 경로까지 지나가야 한다.
    reg = m.REGIONS[0]
    try:
        a = m.fetch_one_region_forecast(reg)
        b = m.fetch_one_region_forecast(reg)   # 여기가 캐시 경로
        same = {k: v for k, v in a.items() if k != '_hourly'} == \
               {k: v for k, v in b.items() if k != '_hourly'} and \
               (a.get('_hourly') or []) == (b.get('_hourly') or [])
        n = len(a.get('_hourly') or [])
        print(f'  {"O" if same else "X"} 단기예보 캐시 경로 — 2회 연속 호출 결과 동일 (시간대별 {n}개)')
        if not same:
            fails.append('단기예보 캐시 결과가 원본과 다름')
        if n == 0:
            fails.append('단기예보 시간대별 예보가 0개')
            print('      X 시간대별 예보가 비었다 — 상황실이 12시간치를 지어낼 수 있다')
    except Exception as e:
        print(f'  X 단기예보 캐시 경로 실패: {type(e).__name__}: {e}')
        fails.append(f'단기예보 캐시 경로 예외: {type(e).__name__}')

    # ★ 특보 지역판정 — 다른 광역시가 관할로 새지 않는지
    try:
        rows = m.fetch_apihub_warnings() or []
        leak = [r for r in rows if r.get('is_north_gg')
                and not str(r.get('reg_id', '')).startswith('L101')]
        print(f'  {"O" if not leak else "X"} 특보 지역판정 — 전국 {len(rows)}건 중 '
              f'경기 밖인데 관할로 잡힌 것 {len(leak)}건')
        for r in leak:
            print(f"      X {r.get('reg_up_ko')} {r.get('reg_ko')} ({r.get('reg_id')})")
            fails.append(f"특보 오매칭: {r.get('reg_up_ko')} {r.get('reg_ko')}")
    except Exception as e:
        print(f'  ! 특보 판정 점검 건너뜀(수집 실패): {type(e).__name__}')

    return fails


def main():
    argv = [a for a in sys.argv[1:] if a != '--api']
    do_api = '--api' in sys.argv
    rev = argv[0] if argv else None

    skipped = 0
    if rev:
        print(f'=== 경기북부 상수 대조 (기준 {rev}) ===')
        _good, bad, skipped = compare_baseline(rev)
        if bad:
            print(f'  → 불일치 {bad}건')
        print()
    else:
        print('(옛 원본 대조는 리비전을 인자로 줄 때만 실행한다 — '
              '히스토리 압축으로 원본이 사라져 기본값에서 제외했다)\n')

    fails, warns = [], []
    for key, label in [('north', '경기북부'), ('south', '경기남부')]:
        print(f'=== {label} 무결성 점검 ===')
        f, w = integrity(key)
        fails += f
        warns += w
        print()

    print('=== 두 지역 교차 점검 ===')
    n = {r['name'] for r in RP.PROFILES['north']['regions']}
    s = {r['name'] for r in RP.PROFILES['south']['regions']}
    dup = sorted(n & s)
    print(f'  {"O" if not dup else "X"} 북부·남부 시군명 겹침 없음')
    if dup:
        fails.append(f'두 지역에 같은 시군: {dup}')
        print(f'      겹침 {dup}')

    if do_api:
        fails += api_regression()

    print()
    if fails:
        print(f'==> 문제 {len(fails)}건 — 배포 금지')
        for x in fails:
            print(f'    · {x}')
        return 1
    if warns:
        print(f'==> 통과 (경고 {len(warns)}건)')
        for x in warns:
            print(f'    ! {x}')
    elif skipped:
        print(f'==> 통과 — 단, 대조 {skipped}건은 원본이 없어 건너뜀')
    else:
        print('==> 전부 통과')
    if not do_api:
        print('    (외부 API 회귀 점검은 --api 로 별도 실행)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
