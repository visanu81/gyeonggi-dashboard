# -*- coding: utf-8 -*-
"""경기북부 data.js + 경기남부 data-south.js → 경기 전체 data-all.js

왜 합치나(새로 수집하지 않는 이유)
  경기북부 10개 + 경기남부 21개 = 경기도 31개 시군에 정확히 일치한다(중복·누락 0).
  그래서 '경기 전체' 사이트를 위해 API를 다시 부를 필요가 없다. 새로 수집하면
  회차마다 약 120회가 더 나가고, 관측소·격자를 세 벌 관리하게 되며, 세 값이
  서로 어긋날 여지가 생긴다. 합치면 추가 호출 0회에 원본이 둘뿐이라 어긋날 수 없다.

무엇을 어떻게 합치나
  · 시군 단위(regions·pm·fire·ultra_fcst·aws) → 그냥 이어붙임. 겹치면 예외를 던진다.
  · 특보·재난문자·태풍 등 목록 → 이어붙인 뒤 같은 것 제거.
  · 전국 공통(통보문·중기전망·기상영상) → 더 최근 것.
  · 물때 → 임진강 하구(파주)라 북부 것만 있다. 그대로 쓴다.
  · 산불통계 → '경기' 집계는 두 파일이 같고, 관할 최근 내역만 합쳐 최신순으로.

실행:
  python tools/merge_all.py            # data.js + data-south.js → data-all.js
  python tools/merge_all.py --check    # 만들지 않고 대조만
"""
import json
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
MARK = 'window.DASHBOARD_DATA = '

# 이 지역의 '중점' 시군이 어느 파일에 있는지 — 상단 요약과 forecast 폴백 기준.
# 경기 전체는 도청 소재지인 수원(남부)으로 둔다. region-all.js 의 home 과 맞출 것.
HOME_FROM = 'south'


def load(path):
    t = Path(path).read_text(encoding='utf-8')
    i = t.find(MARK)
    if i < 0:
        raise SystemExit(f'{path}: {MARK} 를 못 찾음')
    return json.loads(t[i + len(MARK):].rstrip().rstrip(';').strip())


def cat_unique(a, b, key):
    """이어붙이되 같은 것은 한 번만. key 는 항목 → 식별자 함수."""
    out, seen = [], set()
    for x in list(a or []) + list(b or []):
        k = key(x)
        if k in seen:
            continue
        seen.add(k)
        out.append(x)
    return out


def cat_strict(a, b, key, label):
    """겹치면 안 되는 목록(시군 단위). 겹치면 조용히 두 배가 되므로 예외를 던진다."""
    dup = sorted({key(x) for x in (a or [])} & {key(x) for x in (b or [])})
    if dup:
        raise SystemExit(f'{label}: 북부·남부에 같은 항목이 있다 → {dup}\n'
                         '  프로파일이 바뀐 것 같다. 합치기 전에 확인할 것.')
    return list(a or []) + list(b or [])


def dict_strict(a, b, label):
    dup = sorted(set(a or {}) & set(b or {}))
    if dup:
        raise SystemExit(f'{label}: 북부·남부에 같은 키가 있다 → {dup}')
    return {**(a or {}), **(b or {})}


# ⚠ 소방서 하위관서(분당·송탄·일산)를 여기서 regions 에 복제하지 않는다.
#   한때 복제했다가 성남·평택·고양이 regions 에 두 번씩 들어가, 시군 집계(최고기온·
#   특보 건수 등)가 이중으로 세어지는 문제가 있었다.
#   기상청 자료는 시군 단위라 '분당의 기온'이라는 건 없다 — 성남 값을 보는 게 맞다.
#   그래서 regions/pm 은 시군 31개 그대로 두고, 화면이 region-all.js 의 alias
#   ({'분당':'성남', ...})로 소속 시군 값을 끌어다 쓴다. 실측 강수·바람만 관서명 키
#   (aws['분당'])로 갈라지는데, 이건 북부에서 일산이 이미 그렇게 동작하는 구조다.


def newer(n, s, key):
    """전국 공통 항목 — 수집이 늦게 끝난 쪽(=더 최근) 것을 쓴다."""
    return s.get(key) if s.get('updated', '') >= n.get('updated', '') else n.get(key)


def merge(n, s):
    out = {'updated': max(n.get('updated', ''), s.get('updated', ''))}

    # ── 시군 단위 — 겹치면 안 된다 ─────────────────────────────
    out['regions'] = cat_strict(n.get('regions'), s.get('regions'),
                                lambda r: r['name'], 'regions(시군)')
    out['pm'] = cat_strict(n.get('pm'), s.get('pm'),
                           lambda p: p['region'], 'pm(미세먼지)')
    out['fire'] = cat_strict(n.get('fire'), s.get('fire'),
                             lambda f: f['region'], 'fire(산불권역)')
    out['aws'] = dict_strict(n.get('aws'), s.get('aws'), 'aws(실측강수)')
    out['ultra_fcst'] = dict_strict(n.get('ultra_fcst'), s.get('ultra_fcst'),
                                    'ultra_fcst(6시간예측)')

    # ── 목록 — 같은 것만 걸러 이어붙임 ──────────────────────────
    # 하천 중복 제거 — 키는 반드시 (코드, 시군) 짝이어야 한다.
    # ⚠ 코드만으로 지우면 '한 관측소를 여러 관서가 나눠 보는' 정상 배정까지 지워진다.
    #   실제로 그랬다(2026-08-19 점검): 안양천 충훈1교는 과천·안양·군포·의왕 4곳이,
    #   안산천 안산10교는 시흥·안산 2곳이 함께 보도록 프로파일에 넣어 뒀는데,
    #   첫 줄(과천·시흥)만 남고 나머지 4줄이 사라져 안양·안산·군포·의왕 네 소방서의
    #   하천 카드가 통째로 '관할 하천 관측소 없음'이 됐다(57곳 → 53곳).
    #   호우 때 그 관서가 볼 수 있는 실시간 수위가 0개가 되는, 가장 위험한 종류의 결함.
    out['rivers'] = cat_unique(n.get('rivers'), s.get('rivers'),
                               lambda r: (str(r.get('code')), r.get('sigun')))
    out['warnings'] = cat_unique(n.get('warnings'), s.get('warnings'),
                                 lambda w: (w.get('type'), w.get('area'), w.get('time')))
    out['prelim_warnings'] = cat_unique(n.get('prelim_warnings'), s.get('prelim_warnings'),
                                        lambda g: g.get('type'))
    out['apihub_warnings'] = cat_unique(
        n.get('apihub_warnings'), s.get('apihub_warnings'),
        lambda w: (w.get('reg_id'), w.get('wrn_name'), w.get('lvl_name'),
                   w.get('tm_fc'), w.get('tm_ef')))
    out['typhoon'] = cat_unique(n.get('typhoon'), s.get('typhoon'),
                                lambda t: str(t.get('seq')))
    out['flood_forecast'] = cat_unique(n.get('flood_forecast'), s.get('flood_forecast'),
                                       lambda f: (f.get('river'), f.get('kind')))
    # 재난문자 — 경기도 전역 발송분은 두 지역에 다 잡힌다 → 일련번호(sn)로 제거
    msgs = cat_unique(n.get('messages'), s.get('messages'),
                      lambda m: str(m.get('sn') or (m.get('time'), m.get('msg'))))
    out['messages'] = sorted(msgs, key=lambda m: str(m.get('sn') or ''), reverse=True)

    # ── 전국 공통 — 더 최근 것 ─────────────────────────────────
    for k in ('bulletins', 'mid_forecast', 'kma_images'):
        out[k] = newer(n, s, k)
    out['forecast'] = (s if HOME_FROM == 'south' else n).get('forecast')
    out['tide'] = n.get('tide') or s.get('tide')      # 임진강 하구(파주) — 북부에만 있다

    # ── 산불통계 — '경기' 집계는 두 파일이 같고, 관할 최근내역만 합친다 ──
    fn, fs = n.get('fire_stats') or {}, s.get('fire_stats') or {}
    sn_, ss_ = fn.get('summary') or {}, fs.get('summary') or {}
    latest = cat_unique(sn_.get('latest_north'), ss_.get('latest_north'),
                        lambda x: (x.get('sigungu'), x.get('address'), x.get('occur_t')))
    latest.sort(key=lambda x: str(x.get('occur_t') or ''), reverse=True)
    out['fire_stats'] = {
        'incidents': fn.get('incidents') or fs.get('incidents'),
        'summary': {**sn_, **ss_,
                    # 이 사이트의 '관할'은 경기 전체다 → 관할 값에 경기 집계를 쓴다
                    'north': sn_.get('gyeonggi', 0),
                    'this_year_north': (sn_.get('this_year_north', 0)
                                        + ss_.get('this_year_north', 0)),
                    'latest_north': latest[:12]},
    }
    return out


def main():
    n = load(ROOT / 'data.js')
    s = load(ROOT / 'data-south.js')
    print(f'북부 {n.get("updated")} · 남부 {s.get("updated")}')
    if n.get('updated') != s.get('updated'):
        print('  ! 두 파일의 수집 시각이 다르다 — 한쪽이 이번 회차에 실패했을 수 있다')

    m = merge(n, s)
    print(f'\n합친 결과: 시군 {len(m["regions"])}개 · 하천 {len(m["rivers"])}곳 · '
          f'특보 {len(m["warnings"])}건 · 재난문자 {len(m["messages"])}건 · '
          f'미세먼지 {len(m["pm"])}곳 · 산불권역 {len(m["fire"])}곳')
    if len(m['regions']) != 31:
        print(f'  ! 시군이 31개가 아니다({len(m["regions"])}개) — 프로파일 확인 필요')
        return 1

    if '--check' in sys.argv:
        print('\n--check — 파일을 만들지 않았다')
        return 0
    body = MARK + json.dumps(m, ensure_ascii=False, separators=(',', ':')) + ';\n'
    tmp = ROOT / 'data-all.js.tmp'
    tmp.write_text(body, encoding='utf-8')
    tmp.replace(ROOT / 'data-all.js')     # 원자적 저장 — 반쪽 파일이 남지 않게
    print(f'\ndata-all.js 저장 ({len(body):,} 바이트)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
