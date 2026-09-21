# -*- coding: utf-8 -*-
"""부산 안전ON(safecity.busan.go.kr) 재난 CCTV 목록 → cctv-busan.js  (2026-09-22)

부산시 도시침수 통합플랫폼의 지도 센서 API(/iots/vmap/sensor_cctv2.do, 417대)에서 하천·수문·배수 관련 카메라만 골라
구별로 묶는다. 영상은 https://safecity.busan.go.kr:30443/play/hls/{cctv_cd}/index.m3u8 (CORS *, 2026-09-22 실측) 이라
화면 안에서 직접 재생한다. cctv-links.js 가 이 파일(window.BUSAN_CCTV)을 읽어 부산 관서 항목에 붙인다.
카메라가 바뀌면 가끔 손으로:  python tools/build_busan_cctv.py
"""
import json
import re
import sys
from datetime import datetime
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / 'cctv-busan.js'
UNIT = {'기장군': '기장'}                      # 우리 관서 이름과 다른 것
RIVER = re.compile(r'(천|강|교|하구|배수|수문|저수|재난감시|제방|둔치|보)(_|\(|$|[0-9])')
SKIP = re.compile(r'(방파제|항$|항_|해수욕장|해변|마을|주민센터|산단|역_인근|사거리|교차로|초교|초등학교|대교_아래|항대교|광안대교)')


def main():
    r = requests.get('https://safecity.busan.go.kr/iots/vmap/sensor_cctv2.do',
                     headers={'User-Agent': 'Mozilla/5.0', 'X-Requested-With': 'XMLHttpRequest'}, timeout=40)
    r.raise_for_status()
    by = {}
    total = 0
    for it in r.json():
        names = (it.get('sensor_name') or '').split(',')
        cds = (it.get('cctv_cd') or '').split(',')
        for name, cd in zip(names, cds):
            name, cd = name.strip(), cd.strip()
            if not name or not cd:
                continue
            total += 1
            gu, _, rest = name.partition('_')
            if not gu.endswith(('구', '군')) or not rest:
                continue                      # 구 표기가 없는 것(번호형·재난_…)은 위치를 모르니 뺀다
            if SKIP.search(rest) or not RIVER.search(rest):
                continue
            unit = UNIT.get(gu, gu)
            by.setdefault(unit, []).append({'n': rest.replace('_', ' '), 'cd': cd, 'on': it.get('cctv_onoff') == 't'})
    n = sum(len(v) for v in by.values())
    body = ('/* 부산 안전ON 재난 CCTV(하천·수문·배수) — tools/build_busan_cctv.py 가 만든다(직접 고치지 말 것).\n'
            f'   {datetime.now():%Y-%m-%d %H:%M} 기준 전체 {total}대 중 {n}대, 관서별. 영상: safecity.busan.go.kr:30443/play/hls/{{cd}}/index.m3u8 */\n'
            'window.BUSAN_CCTV = ' + json.dumps(by, ensure_ascii=False, separators=(',', ':')) + ';\n')
    OUT.write_text(body, encoding='utf-8')
    print(f'전체 {total}대 → 하천 관련 {n}대, 관서 {len(by)}곳 → {OUT}')
    for k, v in sorted(by.items(), key=lambda kv: -len(kv[1])):
        print(f'  {k}: {len(v)}  ' + ', '.join(x["n"] for x in v[:6]) + (' …' if len(v) > 6 else ''))
    return 0


if __name__ == '__main__':
    sys.exit(main())
