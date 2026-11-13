# -*- coding: utf-8 -*-
"""관서 현황판 서버(/api/board*) 검사 — 인자: 기준 주소, 방 이름(시험용)"""
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

B = sys.argv[1].rstrip('/')
ROOM = sys.argv[2]
CODE = sys.argv[3] if len(sys.argv) > 3 else ''
H = {'content-type': 'application/json', 'user-agent': 'Mozilla/5.0 board-test'}
fails = []


def post(p, body, key=ROOM, code=CODE, raw=None):
    data = raw if raw is not None else json.dumps({'key': key, 'code': code, **body}, ensure_ascii=False).encode('utf-8')
    r = urllib.request.Request(B + p, data=data, headers=H)
    try:
        with urllib.request.urlopen(r, timeout=15) as f:
            return f.status, json.load(f)
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.load(e)
        except Exception:
            return e.code, {}


def get(q, code=CODE):
    u = B + '/api/board?key=' + ROOM + '&code=' + urllib.parse.quote(code) + q
    try:
        with urllib.request.urlopen(urllib.request.Request(u, headers=H), timeout=15) as f:
            return f.status, json.load(f)
    except urllib.error.HTTPError as e:
        return e.code, json.load(e)


def check(name, cond, got=None):
    print(('ok   ' if cond else 'FAIL ') + name + ('' if cond else '  → ' + json.dumps(got, ensure_ascii=False)[:200]))
    if not cond:
        fails.append(name)


def rows(q=''):
    s, d = get(q)
    return d.get('rows', []) if s == 200 else None


def find(rs, station, kind, id_):
    return next((r for r in rs if r['station'] == station and r['kind'] == kind and r['id'] == id_), None)


now = int(time.time() * 1000)
tag = str(now)[-6:]
A, Bst = '시험가' + tag[-2:], '시험나' + tag[-2:]

s, d = post('/api/board/set', {'station': A, 'kind': 'todo', 'id': 't1', 'text': '비상근무 편성 보고', 'extra': 'severe', 'ts': now - 5000})
check('set → ok·applied·ts 는 보낸 시각', s == 200 and d.get('ok') and d.get('applied') is True and d.get('ts') == now - 5000, d)
s, d = post('/api/board/set', {'station': A, 'kind': 'todo', 'id': 't1', 'text': 'OLD', 'ts': now - 60000})
check('옛 시각의 set 은 적용 안 됨(applied:false)', s == 200 and d.get('applied') is False, d)
r = find(rows(), A, 'todo', 't1')
check('그대로 남은 글', r and r['text'] == '비상근무 편성 보고' and r['del'] == 0, r)

# 지움 표시와 늦은 재전송
s, d = post('/api/board/del', {'station': A, 'kind': 'todo', 'id': 't1', 'ts': now - 1000})
check('del → applied', s == 200 and d.get('applied') is True, d)
check('전체 목록에는 지운 줄이 안 나온다', find(rows(), A, 'todo', 't1') is None)
rs = rows('&since=' + str(now - 3000))
r = find(rs, A, 'todo', 't1')
check('since 목록에는 지움 표시(del:1)가 나온다', r is not None and r['del'] == 1, rs)
s, d = post('/api/board/set', {'station': A, 'kind': 'todo', 'id': 't1', 'text': '늦게 온 옛 체크', 'ts': now - 4000})
check('지운 뒤 도착한 옛 체크는 되살아나지 않는다', d.get('applied') is False and find(rows(), A, 'todo', 't1') is None, d)
s, d = post('/api/board/set', {'station': A, 'kind': 'todo', 'id': 't1', 'text': '다시 체크', 'ts': now})
check('지운 뒤 새 체크는 살아난다', d.get('applied') is True and find(rows(), A, 'todo', 't1')['text'] == '다시 체크', d)
s, d = post('/api/board/del', {'station': A, 'kind': 'todo', 'id': 't1', 'ts': now - 2000})
check('새 체크 뒤 도착한 옛 지움은 무시', d.get('applied') is False and find(rows(), A, 'todo', 't1') is not None, d)

# 시각 보정
s, d = post('/api/board/set', {'station': A, 'kind': 'note', 'id': 'n1', 'text': '미래 시각', 'ts': now + 3600000})
check('미래 시각은 지금으로', abs(d.get('ts', 0) - time.time() * 1000) < 15000, d)
s, d = post('/api/board/set', {'station': A, 'kind': 'beat', 'id': 'now', 'extra': {'lv': 'warn', 'why': '호우주의보'}, 'ts': now - 900000})
check('beat 는 늘 서버의 지금', abs(d.get('ts', 0) - time.time() * 1000) < 15000, d)

# 관서별 / 전체 / cfg
post('/api/board/set', {'station': Bst, 'kind': 'chk', 'id': 'z1', 'text': '침수위험 상패동 일대'})
post('/api/board/set', {'station': Bst, 'kind': 'beat', 'id': 'now', 'extra': {'lv': 'safe'}})
post('/api/board/set', {'station': A, 'kind': 'cfg', 'id': 'todo', 'extra': {'v': 1, 'items': [{'id': 'a', 'stage': 'warn', 'text': '순찰 계획 확인'}]}})
post('/api/board/set', {'station': Bst, 'kind': 'cfg', 'id': 'todo', 'extra': {'v': 1, 'items': []}})
rs = rows('&station=' + urllib.parse.quote(A))
check('station= 은 그 관서 줄과 그 관서 beat 만', rs and all(r['station'] == A for r in rs) and any(r['kind'] == 'beat' for r in rs), rs)
check('station= 목록에 cfg 는 없다(따로 청해야)', not any(r['kind'] == 'cfg' for r in rs), rs)
rs = rows('&cfg=' + urllib.parse.quote(A))
check('전체 목록 — 두 관서 beat, cfg 는 청한 관서 것만',
      sum(1 for r in rs if r['kind'] == 'beat' and r['station'] in (A, Bst)) == 2
      and [r['station'] for r in rs if r['kind'] == 'cfg'] == [A], [(r['station'], r['kind']) for r in rs])
t1 = int(time.time() * 1000) + 50
time.sleep(0.2)
check('since — 바뀐 게 없으면 비어 있다', rows('&since=' + str(t1) + '&cfg=' + urllib.parse.quote(A)) == [])

# 체크 초기화
post('/api/board/set', {'station': A, 'kind': 'todo', 'id': 't2', 'text': '둘째'})
s, d = post('/api/board/clear', {'station': A, 'kind': 'todo'})
check('clear — 그 관서 todo 를 모두 지움 표시', s == 200 and d.get('n') == 2 and not any(r['kind'] == 'todo' and r['station'] == A for r in rows()), d)
check('clear — 다른 관서·다른 종류는 그대로', find(rows(), Bst, 'chk', 'z1') is not None and find(rows(), A, 'note', 'n1') is not None)
s, d = post('/api/board/clear', {'station': A, 'kind': 'note'})
check('clear 는 chk·todo 만', s == 400, d)

# 거부
s, d = post('/api/board/set', {'station': A, 'kind': 'note', 'id': 'p1', 'text': '연락처 010-1234-5678'})
check('개인정보(글) 거부', s == 400 and '개인정보' in d.get('why', ''), d)
s, d = post('/api/board/set', {'station': A, 'kind': 'beat', 'id': 'now', 'extra': {'lv': 'warn', 'why': '담당 010 1234 5678'}})
check('개인정보(beat why) 거부', s == 400, d)
s, d = post('/api/board/set', {'station': A, 'kind': 'cfg', 'id': 'todo', 'extra': {'items': [{'text': '101동 202호 확인'}]}})
check('개인정보(목록 항목) 거부', s == 400, d)
s, d = post('/api/board/set', {'station': A, 'kind': 'beat', 'id': 'now', 'extra': {'lv': 'warn', 'since': now, 'todo': {'n': 5, 'm': 2}}})
check('숫자만 든 beat 는 통과(13자리 시각을 긴 숫자로 오인하지 않음)', s == 200 and d.get('ok'), d)
check('잘못된 종류', post('/api/board/set', {'station': A, 'kind': 'hack', 'id': '1'})[0] == 400)
check('id 없음', post('/api/board/set', {'station': A, 'kind': 'note', 'id': ''})[0] == 400)
check('관서 없음', post('/api/board/set', {'station': '', 'kind': 'note', 'id': '1'})[0] == 400)
check('너무 긴 extra', post('/api/board/set', {'station': A, 'kind': 'todo', 'id': 'x', 'extra': 'x' * 1001})[0] == 400)
check('없는 주소', post('/api/board/zzz', {'station': A, 'kind': 'todo'})[0] == 404)
check('지역키가 문자열이 아님 → 400(500 아님)', post('', {}, raw=json.dumps({'key': 123, 'station': A, 'kind': 'note', 'id': '1'}).encode())[0] in (400, 404)
      and post('/api/board/set', {}, raw=json.dumps({'key': 123, 'station': A, 'kind': 'note', 'id': '1'}).encode())[0] == 400)
check('지역키 꼴이 아님 → 400', post('/api/board/set', {'station': A, 'kind': 'note', 'id': '1'}, key='NOPE!')[0] == 400)

# 열쇠
if CODE:
    check('틀린 열쇠 → 401 (set)', post('/api/board/set', {'station': A, 'kind': 'note', 'id': 'k', 'text': 'x'}, code='wrong')[0] == 401)
    check('틀린 열쇠 → 401 (del)', post('/api/board/del', {'station': A, 'kind': 'note', 'id': 'k'}, code='wrong')[0] == 401)
    check('틀린 열쇠 → 401 (clear)', post('/api/board/clear', {'station': A, 'kind': 'todo'}, code='wrong')[0] == 401)
    check('틀린 열쇠 → 401 (list)', get('', code='wrong')[0] == 401)

# 기존 출동 메모 주소 그대로
s, d = post('/api/note', {'station': A, 'type': '침수', 'place': '시험'})
check('출동 메모 기록 그대로', s == 200 and d.get('ok'), d)
if d.get('id'):
    post('/api/del', {'id': d['id']})

# 뒷정리 — 시험 줄 지움 표시
for st in (A, Bst):
    post('/api/board/clear', {'station': st, 'kind': 'todo'})
    post('/api/board/clear', {'station': st, 'kind': 'chk'})
    post('/api/board/del', {'station': st, 'kind': 'note', 'id': 'n1'})
    post('/api/board/del', {'station': st, 'kind': 'beat', 'id': 'now'})
    post('/api/board/del', {'station': st, 'kind': 'cfg', 'id': 'todo'})

print('\n실패 %d건' % len(fails) + (': ' + ', '.join(fails) if fails else ''))
sys.exit(1 if fails else 0)
