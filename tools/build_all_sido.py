# -*- coding: utf-8 -*-
"""시도 프로파일 전부 → 지도(map-geo-<key>.js) + 화면설정(region-<key>.js) 일괄 생성.

전국 확장 2단계(2026-09-18). 프로파일(tools/profiles/*.json)은 build_region_profile.py --sido 가 만든다.
여기서는 그 뒤 두 산출물을 시도마다 돌리고 결과를 한 표로 보여준다.

  python tools/build_all_sido.py            # 전부
  python tools/build_all_sido.py busan jeju # 골라서
  python tools/build_all_sido.py --collect  # + 로컬에서 데이터 1회 수집(data-<key>.js) — 작업장 미리보기용
"""
import json
import subprocess
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
PY = [sys.executable, '-X', 'utf8']


def run(args, label):
    r = subprocess.run(PY + args, cwd=str(ROOT), capture_output=True, text=True, encoding='utf-8')
    if r.returncode != 0:
        print(f'  ✗ {label}: {(r.stderr or r.stdout)[-300:].strip()}')
        return False
    return True


def main():
    collect = '--collect' in sys.argv
    keys = [a for a in sys.argv[1:] if not a.startswith('--')]
    profs = sorted((ROOT / 'tools' / 'profiles').glob('*.json'))
    if keys:
        profs = [p for p in profs if p.stem in keys]
    rows = []
    for pf in profs:
        key = pf.stem
        prof = json.loads(pf.read_text(encoding='utf-8'))
        ok_map = run(['tools/build_map_geo.py', '--profile', key, '--merge', '--out', f'map-geo-{key}.js'], f'{key} 지도')
        ok_js = ok_map and run(['tools/build_region_js.py', key], f'{key} 화면설정')
        ok_data = None
        if collect and ok_js:
            ok_data = run(['tools/update_data.py', '--profile', key, '--no-push', '--no-notify'], f'{key} 수집')
        rows.append((prof['label'], key, len(prof['regions']), len(prof['river_stations']),
                     len(prof['pm_stations']), len(prof['reg_map']), ok_map, ok_js, ok_data))
    print(f'{"시도":6s} {"키":10s} {"단위":>4s} {"하천":>4s} {"미세":>4s} {"특보":>4s}  지도 설정 수집')
    for r in rows:
        mk = lambda v: '-' if v is None else ('O' if v else 'X')
        print(f'{r[0]:6s} {r[1]:10s} {r[2]:4d} {r[3]:4d} {r[4]:4d} {r[5]:4d}  {mk(r[6])}   {mk(r[7])}   {mk(r[8])}')


if __name__ == '__main__':
    main()
