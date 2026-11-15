# -*- coding: utf-8 -*-
"""원본 번들(폰트 박힌 4MB 단독실행본)에 우리 데이터·패치만 주입 → 상황실.html.
추출본(50KB+CDN폰트)과 달리 글꼴이 원본과 100% 동일하고 CDN 의존이 없다(벽면 안전).
 - 입력: _refdesign.html(원본 번들 복사본, 프로젝트 루트)
 - 4개 로직 패치(warnsOf 실특보 / feels·effHum·gust 실값) — 번들에 verbatim 존재
 - NAMES 김포→연천
 - 검증된 변환기(INJECT)는 현재 상황실.html(추출본)에서 그대로 추출해 재사용
결과: 상황실.html 덮어씀(번들판)
"""
import re, io, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
ROOT = r'C:/Users/USER/Desktop/AI업무처리/기상,재난상황판'

# 1) 현재 상황실.html(추출본)에서 검증된 주입 스크립트(INJECT) 추출 — risk-zones.js~converter
cur = open(ROOT + '/상황실.html', encoding='utf-8').read()
m = re.search(r'<script src="\./risk-zones\.js"></script>.*?</script>\s*(?=\n?</body>)', cur, re.S)
assert m, 'INJECT 블록을 현재 상황실.html에서 못 찾음(추출본이 아닌 듯)'
INJECT = '\n' + m.group(0) + '\n'
print('INJECT 재사용:', len(INJECT), '바이트')

# 2) 원본 번들 로드 (사장님 Downloads 단독실행본의 복사본)
h = open(ROOT + '/tools/wall-build/original_bundle.html', encoding='utf-8').read()
print('번들 로드:', len(h), '바이트')

# 2.5) 기본폰트 Pretendard 고정 — 디자인 helmet의 html,body 규칙에 font-family가 빠져 있어
#      관서명·온도 등 글꼴 미지정 요소가 브라우저 기본 한글폰트(벽면 Windows=맑은고딕)로 떨어진다.
#      dc-runtime이 부팅 때 head를 helmet으로 재구성하므로 outer head 삽입은 버려진다 → 반드시
#      helmet의 그 규칙 자체에 넣어야 유지된다. 디자인 자체 스타일이라 재구성돼도 살아남음.
_hb_old = "html,body{margin:0;padding:0;background:var(--bg,#0d1118);overflow:hidden;}"
_hb_new = "html,body{margin:0;padding:0;background:var(--bg,#0d1118);overflow:hidden;font-family:'Pretendard Variable',Pretendard,system-ui,sans-serif;}"
assert h.count(_hb_old) == 1, f'html,body 규칙 {h.count(_hb_old)}개(1이어야)'
h = h.replace(_hb_old, _hb_new, 1)
print('폰트고정: helmet html,body 규칙에 font-family 추가')

def patch(old, new, label):
    global h
    assert h.count(old) == 1, f'패치 대상 {h.count(old)}개(1이어야) : {label}'
    h = h.replace(old, new, 1)
    print('패치:', label)

# 3) 4개 로직 패치(추출본과 동일)
patch('warnsOf(s){',
      'warnsOf(s){ const _e=EXT(); if(_e.warns) return _e.warns[s.name]||[];',
      'warnsOf → 실특보')
patch('const feels = wet ? +(temp + 1.2).toFixed(1) : +(temp + (humid>60 ? 5.2 : 3.2)).toFixed(1);',
      'const feels = (g && g.feels!=null) ? +g.feels : (wet ? +(temp + 1.2).toFixed(1) : +(temp + (humid>60 ? 5.2 : 3.2)).toFixed(1));',
      'feels → 실값')
patch('const effHum = wet ? Math.min(97, humid + 3) : Math.round(humid - 8 - r3*10);',
      'const effHum = (g && g.eff!=null) ? Math.round(g.eff) : (wet ? Math.min(97, humid + 3) : Math.round(humid - 8 - r3*10));',
      'effHum → 실값')
patch('gust:+(wind*1.7).toFixed(1)',
      'gust:(g && g.gust!=null)?+g.gust:+(wind*1.7).toFixed(1)',
      'gust → 실값')

# 4) NAMES 김포→연천
assert h.count("'김포'") == 1, "NAMES '김포' 위치 이상"
h = h.replace("'김포'", "'연천'")
print('NAMES 김포→연천')

# 5) 주입(</body> 앞) — 번들은 폰트/런타임 자립이므로 폰트제거·support교체·CDN 없음
assert h.count('</body>') == 1
h = h.replace('</body>', INJECT + '</body>', 1)

open(ROOT + '/상황실.html', 'w', encoding='utf-8').write(h)
print('상황실.html(번들판) 저장:', len(h), '바이트')
