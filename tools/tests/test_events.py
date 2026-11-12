# -*- coding: utf-8 -*-
"""사건 기록(record_events) 검사 — update_data.py 를 통째로 import 하지 않고(.env·프로파일 필요) 필요한 함수만 꺼내 돌린다.

    python -X utf8 -m unittest tools/tests/test_events.py
"""
import ast
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / 'update_data.py'
WANT_FUNCS = {'_atomic_write_text', '_ev_load', '_ev_num', '_ev_rain_band', '_ev_river_name',
              '_ev_warn_names', '_ev_trim', 'record_events', '_canon_region'}
WANT_CONSTS = {'EVENTS_KEEP_H', 'EVENTS_MAX_RAIN', 'EVENTS_MAX_OTHER', 'EVENT_RAIN_BANDS'}


def load(tmp):
    tree = ast.parse(SOURCE.read_text(encoding='utf-8'))
    body = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in WANT_FUNCS:
            body.append(node)
        elif isinstance(node, ast.Assign) and any(getattr(t, 'id', None) in WANT_CONSTS for t in node.targets):
            body.append(node)
    ns = {'Path': Path, 'os': os, 'json': json, 'datetime': datetime, 'timedelta': timedelta,
          'EVENTS_PATH': Path(tmp) / 'events.json', 'EVENTS_STATE_PATH': Path(tmp) / 'events_state.json',
          # _canon_region 이 보는 프로파일 값(경기북부 꼴)
          'SIGUN_SET': {'수원', '용인', '화성', '가평', '고양', '파주', '동두천'}, 'SIDO_WORDS': ['경기'],
          'WIDE_LABEL': '경기도', 'P': {'full': '경기도'}}
    exec(compile(ast.Module(body=body, type_ignores=[]), str(SOURCE), 'exec'), ns)
    return ns


def region(name, rn60=None, rn1=None, rain=0):
    d = {'name': name, 'rain': rain, 'detail': {'aws': {}, 'observation': {}}}
    if rn60 is not None:
        d['detail']['aws']['rn60'] = rn60
    if rn1 is not None:
        d['detail']['observation']['rn1'] = rn1
    return d


def river(code, value, warning=3.0, danger=5.0, name='신천 (동두천 송천교)', **extra):
    d = {'code': code, 'name': name, 'sigun': '동두천', 'value': value, 'warning': warning, 'danger': danger}
    d.update(extra)
    return d


def warn(typ, area):
    return {'type': typ, 'area': area}


class EventsTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.ns = load(self.dir.name)
        self.rec = self.ns['record_events']
        self.t0 = datetime(2026, 11, 13, 9, 0, 0)

    def tearDown(self):
        self.dir.cleanup()

    def run_at(self, minutes, data, **kw):
        n = self.rec(data, now=self.t0 + timedelta(minutes=minutes), **kw)
        return n, data

    def new(self, n, d):
        return [(e['text'], e.get('area')) for e in d['events'][:n]]

    # ── 특보 ──
    def test_first_round_makes_no_events_and_no_since(self):
        d = {'warnings': [warn('호우경보', '수원, 용인')], 'regions': [region('수원', 40)], 'rivers': [river('1', 6.0)]}
        n, d = self.run_at(0, d)
        self.assertEqual((n, d['events']), (0, []))
        self.assertNotIn('since', d['warnings'][0])

    def test_issue_expand_and_since(self):
        self.run_at(0, {'warnings': []})
        n, d = self.run_at(5, {'warnings': [warn('호우주의보', '수원, 용인')]})
        self.assertEqual(self.new(n, d), [('호우주의보 발효', '수원, 용인')])
        self.assertEqual(d['events'][0]['lv'], 'warn')
        self.assertEqual(d['warnings'][0]['since'], '2026-11-13 09:05')
        n, d = self.run_at(10, {'warnings': [warn('호우주의보', '수원, 용인, 화성')]})
        self.assertEqual(self.new(n, d), [('호우주의보 발효', '화성')])
        self.assertEqual(d['warnings'][0]['since'], '2026-11-13 09:05')

    def test_same_area_spelled_two_ways_is_one_event(self):
        # 통보문은 '가평', 허브는 '가평군'·'파주시남부' — 같은 지역이다
        self.run_at(0, {'warnings': []})
        n, d = self.run_at(5, {'warnings': [warn('호우주의보', '가평군')]})
        self.assertEqual(self.new(n, d), [('호우주의보 발효', '가평')])
        n, d = self.run_at(10, {'warnings': [warn('호우주의보', '가평, 경기도'), warn('호우주의보', '가평군'),
                                             warn('호우주의보', '파주시남부')]})
        self.assertEqual(self.new(n, d), [('호우주의보 발효', '경기도, 파주')])

    def test_lift_needs_two_complete_rounds_and_uses_first_missing_time(self):
        self.run_at(0, {'warnings': []})
        self.run_at(5, {'warnings': [warn('호우주의보', '수원, 용인')]})
        # 한 회차만 비어 온 것(통보문이 빈 응답) — 해제가 아니다
        n, d = self.run_at(10, {'warnings': []})
        self.assertEqual(n, 0)
        n, d = self.run_at(15, {'warnings': [warn('호우주의보', '수원, 용인')]})
        self.assertEqual(n, 0)
        self.assertEqual(d['warnings'][0]['since'], '2026-11-13 09:05')
        # 진짜 해제 — 두 회차 연속 없음. 시각은 처음 빠진 09:20
        n, d = self.run_at(20, {'warnings': [warn('호우주의보', '수원')]})
        self.assertEqual(n, 0)
        n, d = self.run_at(25, {'warnings': [warn('호우주의보', '수원')]})
        self.assertEqual(self.new(n, d), [('호우주의보 해제', '용인')])
        self.assertEqual((d['events'][0]['lv'], d['events'][0]['ts']), ('clear', '2026-11-13 09:20:00'))

    def test_upgrade_to_gyeongbo_is_not_a_lift(self):
        self.run_at(0, {'warnings': []})
        self.run_at(5, {'warnings': [warn('호우주의보', '수원')]})
        n, d = self.run_at(10, {'warnings': [warn('호우경보', '수원')]})
        self.assertEqual(self.new(n, d), [('호우경보 발효', '수원')])
        self.assertEqual(d['events'][0]['lv'], 'severe')
        n, d = self.run_at(15, {'warnings': [warn('호우경보', '수원')]})
        self.assertEqual(n, 0)      # 주의보가 사라진 것은 격상 — 해제 줄 없음

    def test_incomplete_rounds_do_not_touch_warnings(self):
        self.run_at(0, {'warnings': []})
        self.run_at(5, {'warnings': [warn('호우주의보', '수원')]})
        for m in (10, 15, 20):
            n, _ = self.run_at(m, {'warnings': []}, warn_complete=False)
            self.assertEqual(n, 0)
        n, d = self.run_at(25, {'warnings': [warn('호우주의보', '수원')]})
        self.assertEqual(n, 0)
        self.assertEqual(d['warnings'][0]['since'], '2026-11-13 09:05')

    def test_first_complete_round_after_incomplete_start_is_silent(self):
        # 서버가 특보 발효 중에 켜졌는데 첫 회차에 한쪽 출처가 실패 — 다음 온전한 회차에 '방금 발효'로 쏟아지면 안 된다
        n, d = self.run_at(0, {'warnings': [warn('호우경보', '수원')]}, warn_complete=False)
        self.assertEqual(n, 0)
        n, d = self.run_at(5, {'warnings': [warn('호우경보', '수원, 용인')]})
        self.assertEqual(n, 0)
        self.assertNotIn('since', d['warnings'][0])
        # 그 뒤 새로 늘어난 지역은 적는다. since 는 '모르는 지역'이 섞여 있으면 붙이지 않는다
        n, d = self.run_at(10, {'warnings': [warn('호우경보', '수원, 용인, 화성')]})
        self.assertEqual(self.new(n, d), [('호우경보 발효', '화성')])
        self.assertNotIn('since', d['warnings'][0])

    # ── 강수 ──
    def test_rain_bands_up_and_hysteresis_down(self):
        self.run_at(0, {'regions': [region('수원', 0)]})
        n, d = self.run_at(5, {'regions': [region('수원', 6.0)]})
        self.assertEqual(self.new(n, d), [('수원 시간당 5mm 넘음', None)])
        n, d = self.run_at(10, {'regions': [region('수원', 32.0)]})
        self.assertEqual((d['events'][0]['text'], d['events'][0]['lv'], d['events'][0]['where']),
                         ('수원 시간당 30mm 넘음', 'severe', ['수원']))
        n, _ = self.run_at(15, {'regions': [region('수원', 4.5)]})      # 5mm 의 80% 이상 → 아직 내린 게 아니다
        self.assertEqual(n, 0)
        n, d = self.run_at(20, {'regions': [region('수원', 1.0)]})
        self.assertEqual(self.new(n, d), [('수원 시간당 5mm 아래로', None)])

    def test_rain_uses_observed_values_only(self):
        self.run_at(0, {'regions': [region('수원', 25.0)]})
        # 실측이 빠진 회차 — region['rain'] 에는 예보값(0)이 들어 있다. '5mm 아래로'가 나오면 안 된다
        n, _ = self.run_at(5, {'regions': [region('수원', None, rain=0)]})
        self.assertEqual(n, 0)
        n, _ = self.run_at(10, {'regions': [region('수원', float('nan'), rain=0)]})
        self.assertEqual(n, 0)
        n, _ = self.run_at(15, {'regions': [region('수원', 26.0)]})      # 돌아와도 '20mm 넘음'이 또 나오지 않는다
        self.assertEqual(n, 0)
        # rn60 이 없으면 초단기실황 rn1(실측)을 쓴다
        n, d = self.run_at(20, {'regions': [region('수원', None, rn1=55.0)]})
        self.assertEqual(self.new(n, d), [('수원 시간당 50mm 넘음', None)])

    def test_bad_band_in_state_does_not_raise(self):
        self.run_at(0, {'regions': [region('수원', 1)]})
        p = self.ns['EVENTS_STATE_PATH']
        s = json.loads(p.read_text(encoding='utf-8'))
        s['rain']['수원'] = 9
        p.write_text(json.dumps(s, ensure_ascii=False), encoding='utf-8')
        n, _ = self.run_at(5, {'regions': [region('수원', 2)]})
        self.assertEqual(n, 0)

    # ── 하천 ──
    def test_river_crossings_skip_dam_suspect_and_impossible_values(self):
        base = [river('1', 1.0), river('2', 1.0, api='dam'), river('3', 1.0, suspect=True), river('4', 1.0)]
        self.run_at(0, {'rivers': base})
        now = [river('1', 3.2), river('2', 9.0, api='dam'), river('3', 9.0, suspect=True), river('4', 89.92)]
        n, d = self.run_at(5, {'rivers': now})
        self.assertEqual([(e['text'], e['code']) for e in d['events'][:n]], [('신천 · 송천교 주의수위 넘음', '1')])
        n, d = self.run_at(10, {'rivers': [river('1', 5.3)]})
        self.assertEqual((d['events'][0]['text'], d['events'][0]['lv'], d['events'][0]['sub']),
                         ('신천 · 송천교 위험수위 넘음', 'severe', '5.30m · 기준 5.0m'))
        n, _ = self.run_at(15, {'rivers': [river('1', 4.99)]})          # 2cm 여유 안 → 아직 위험수위
        self.assertEqual(n, 0)
        n, d = self.run_at(20, {'rivers': [river('1', 4.5)]})
        self.assertEqual((d['events'][0]['text'], d['events'][0]['lv']), ('신천 · 송천교 위험수위 아래로', 'warn'))
        n, d = self.run_at(25, {'rivers': [river('1', 2.0)]})
        self.assertEqual((d['events'][0]['text'], d['events'][0]['lv']), ('신천 · 송천교 주의수위 아래로', 'clear'))
        # 같은 관측소가 두 줄(관서 둘이 함께 봄)이어도 한 번만
        self.run_at(30, {'rivers': [river('9', 1.0), river('9', 1.0)]})
        n, _ = self.run_at(35, {'rivers': [river('9', 3.5), river('9', 3.5)]})
        self.assertEqual(n, 1)

    def test_river_without_warning_level(self):
        self.run_at(0, {'rivers': [river('7', 1.0, warning=None)]})
        n, d = self.run_at(5, {'rivers': [river('7', 5.5, warning=None)]})
        self.assertEqual(d['events'][0]['text'], '신천 · 송천교 위험수위 넘음')
        n, d = self.run_at(10, {'rivers': [river('7', 2.0, warning=None)]})
        self.assertEqual((d['events'][0]['text'], d['events'][0]['lv']), ('신천 · 송천교 위험수위 아래로', 'clear'))

    # ── 보관 ──
    def test_retention_and_per_kind_caps(self):
        self.run_at(0, {'regions': [region('수원', 0)]})
        self.run_at(5, {'regions': [region('수원', 6)]})
        n, d = self.run_at(73 * 60, {'regions': [region('수원', 25)]})    # 73시간 뒤 — 옛 줄은 빠진다
        self.assertEqual([e['text'] for e in d['events']], ['수원 시간당 20mm 넘음'])
        trim = self.ns['_ev_trim']
        many = [{'ts': '2026-11-13 09:%02d:00' % (i % 60), 'kind': 'rain', 'k': 'p%d' % i} for i in range(500)]
        many += [{'ts': '2026-11-13 08:00:00', 'kind': 'warn', 'k': 'w1'}, {'ts': '2026-11-13 08:00:01', 'kind': 'river', 'k': 'r1'}]
        out = trim(many, '2026-11-01 00:00:00')
        self.assertEqual(sum(1 for e in out if e['kind'] == 'rain'), 200)
        self.assertEqual({e['k'] for e in out if e['kind'] != 'rain'}, {'w1', 'r1'})   # 강수 줄에 밀려나지 않는다

    def test_missing_log_file_inherits_previous_events(self):
        prev = [{'ts': '2026-11-13 08:30:00', 'kind': 'warn', 'lv': 'warn', 'text': '호우주의보 발효', 'k': 'old1'}]
        n, d = self.run_at(0, {'regions': [region('수원', 0)]}, prev_events=prev)
        self.assertEqual([e['k'] for e in d['events']], ['old1'])
        # 파일이 생긴 뒤에는 파일이 기준
        n, d = self.run_at(5, {'regions': [region('수원', 7)]}, prev_events=[])
        self.assertEqual([e['text'] for e in d['events']], ['수원 시간당 5mm 넘음', '호우주의보 발효'])

    def test_corrupt_files_and_garbage_input_do_not_raise(self):
        self.run_at(0, {'regions': [region('수원', 0)]})
        self.ns['EVENTS_PATH'].write_text('{broken', encoding='utf-8')
        self.ns['EVENTS_STATE_PATH'].write_text('[1,2', encoding='utf-8')
        d = {'warnings': [None, {'area': '수원'}, {'type': '호우경보'}, warn('호우경보', '수원')],
             'regions': [None, {}, {'name': '수원'}, region('용인', 60)],
             'rivers': [None, {'code': '1'}, river('', 9), river('5', 'x'), river('6', 1, danger=0)]}
        n, d = self.run_at(5, d)
        self.assertEqual((n, d['events']), (0, []))
        json.loads(self.ns['EVENTS_STATE_PATH'].read_text(encoding='utf-8'))

    def test_state_write_failure_raises_before_events_are_written(self):
        self.run_at(0, {'regions': [region('수원', 0)]})
        before = self.ns['EVENTS_PATH'].read_text(encoding='utf-8')
        real = self.ns['_atomic_write_text']

        def boom(path, text):
            if Path(path).name == 'events_state.json':
                raise OSError('disk full')
            return real(path, text)
        self.ns['_atomic_write_text'] = boom
        with self.assertRaises(OSError):
            self.run_at(5, {'regions': [region('수원', 30)]})
        self.assertEqual(self.ns['EVENTS_PATH'].read_text(encoding='utf-8'), before)


if __name__ == '__main__':
    unittest.main()
