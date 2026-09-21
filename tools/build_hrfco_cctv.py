# -*- coding: utf-8 -*-
"""홍수통제소 수위관측소 CCTV 장치번호표 → cctv-hrfco.js  (2026-09-22)

홍수정보시스템(n.flood.go.kr)의 CCTV 목록에서 관측소코드(obscd) ↔ 장치번호(ldUrl 저해상도·hdUrl 고해상도)를 뽑는다.
화면은 이 번호로 통제소 중계서버(lw.hrfco.go.kr)의 HLS 를 직접 튼다 — 팝업 페이지(cctvView.do) iframe 대신.
  · 스트림은 누가 보기 시작해야 켜진다: getCctvScreen.do 에 POST(deviceId) 한 뒤 몇 초 지나야 m3u8 이 200 이 된다.
  · m3u8·조각(lw.hrfco.go.kr)은 CORS 로 우리 출처를 허용한다(2026-09-22 실측). getCctvScreen.do 응답은 CORS 가 없어
    읽지는 못하지만 no-cors POST 로 '켜기'만은 된다.
장치번호는 거의 안 바뀌므로 가끔 손으로 돌린다:  python tools/build_hrfco_cctv.py
"""
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / 'cctv-hrfco.js'


def main():
    tm = (datetime.now() - timedelta(minutes=10)).strftime('%Y%m%d%H%M')
    r = requests.get('https://n.flood.go.kr/main/getData.do', params={'dataType': 'cctv', 'ymdhm': tm},
                     headers={'User-Agent': 'Mozilla/5.0'}, timeout=40)
    r.raise_for_status()
    rows = r.json()
    table = {}
    for it in rows:
        code, ld, hd = str(it.get('obscd') or ''), str(it.get('ldUrl') or ''), str(it.get('hdUrl') or '')
        if not code or not (ld or hd):
            continue
        table[code] = {'n': it.get('obsnm') or it.get('media_nm') or '', 'ld': ld, 'hd': hd, 'fc': it.get('fcodvcd') or '01'}
    body = ('/* 홍수통제소 수위관측소 CCTV 장치번호표 — tools/build_hrfco_cctv.py 가 만든다(직접 고치지 말 것).\n'
            f'   {datetime.now():%Y-%m-%d %H:%M} 기준 {len(table)}곳. obscd → {{n:이름, ld:저해상도 장치번호, hd:고해상도, fc:fcodvcd}} */\n'
            'window.HRFCO_CCTV = ' + json.dumps(table, ensure_ascii=False, separators=(',', ':')) + ';\n')
    OUT.write_text(body, encoding='utf-8')
    print(f'{len(table)}곳 → {OUT}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
