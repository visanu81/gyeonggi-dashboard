/* 출동 메모 저장소 — 비 오는 날 나간 출동을 한 줄로 남기고, 그때 기상값을 함께 붙여 둔다.
 *
 * 왜 만드나
 *   소방활동보고(공식 기록)는 '무슨 출동이었나'는 남기지만 '그때 비가 얼마나 왔나'는 안 남긴다.
 *   그 둘을 잇는 게 이 저장소의 전부다. 쌓이면 ① 반복 침수 지점이 보이고 ② 호우 끝난 뒤
 *   '관내 몇 건, 어디가 최다' 보고가 한 번에 나온다.
 *
 * ★ 개인정보는 받지 않는다 (설계 원칙이자 서버에서 강제한다)
 *   신고자·대상자 이름, 연락처, 동·호수, 환자 정보는 입력칸 자체를 두지 않고,
 *   여기서도 전화번호·주민번호 같은 꼴이 들어오면 거부한다(아래 looksPersonal).
 *   그래야 '공개등급 업무자료'로 남아 상용 클라우드에 둬도 규정에 걸리지 않는다.
 *
 * ★ 왜 Durable Object 인가 — 수색현황판과 같은 이유.
 *   여러 관서가 동시에 적어도 서로 지워지지 않는다(한 곳에서 한 줄로 처리).
 *   무료 플랜에서 쓰려면 SQLite 방식이어야 한다(wrangler.toml 참고).
 *
 * 주소
 *   GET  /api/ping                    살아있나
 *   GET  /api/status?key=all          열쇠가 정해졌는지 · 기록 수
 *   POST /api/code                    최초 열쇠 정하기 / 바꾸기
 *   POST /api/note                    메모 한 건 남기기        (열쇠 필요)
 *   GET  /api/notes?key=all&days=14   목록 (station= 로 관서만) (열쇠 필요)
 *   POST /api/del                     한 건 지우기             (열쇠 필요)
 *   GET  /api/stats?key=all&days=90   관서·유형·장소별 집계    (열쇠 필요)
 *
 *   ── 관서 현황판 (2026-11-13) — 각 관서 화면의 체크·점검·한 줄 기록을 본부가 모아 본다 ──
 *   POST /api/board/set               한 줄 올리기/고치기     (열쇠 필요)  → {ok, ts, applied}
 *   POST /api/board/del               한 줄 지움 표시         (열쇠 필요)  → {ok, ts, applied}
 *   POST /api/board/clear             그 관서의 chk 또는 todo 를 모두 지움 표시(체크 초기화)
 *   GET  /api/board?key=all&hours=48  줄 목록 (열쇠 필요). station= 그 관서 것만(관서 화면) · since= 그 뒤 바뀐 것만
 *                                     (지움 표시 del:1 포함) · cfg= 그 관서의 목록 설정도
 *     같은 줄은 '더 나중 시각의 것'이 남는다(지움도 같은 규칙). applied:false 면 서버에 더 새 값이 있다는 뜻.
 *     줄 하나 = (관서, 종류, id). 종류: chk 위험구역 점검 확인 · todo 체크리스트 체크 · note 한 줄 기록
 *     · beat 관서 요약(상태·진행·접속 시각, 관서마다 1줄) · cfg 관서의 체크리스트 목록(관서마다 1줄)
 *     관서 화면이 상태를 통째로 올리지 않고 줄 단위로 올리는 이유: 같은 관서의 PC 둘이 동시에 체크해도
 *     서로 지우지 않게.
 *
 * 지역키(key)는 화면의 REGION_CONF.key 를 그대로 쓴다(경기 전체판은 'all').
 */

import { DurableObject } from "cloudflare:workers";

const TYPES = ['침수', '도로장애', '인명구조', '배수지원', '안전조치', '기타'];
const MAX_MEMO = 60;        // 한 줄 메모 — 길면 사연이 들어가고 개인정보가 섞인다
const MAX_PLACE = 40;
const KEEP_DAYS = 1100;     // 3년쯤 보관(장마 세 번 비교용). 그 이상은 스스로 지운다
const MAX_ROWS = 20000;     // 한 지역 상한 — 넘으면 오래된 것부터

const BOARD_KINDS = ['chk', 'todo', 'note', 'beat', 'cfg'];
const BOARD_TEXT = 80;      // 한 줄 글자 수
const BOARD_EXTRA = 1000;   // 딸린 값(JSON 문자열) 길이 — cfg(체크리스트 목록)만 8000
const BOARD_EXTRA_CFG = 8000;
const BOARD_KEEP_DAYS = 14; // 체크·점검·기록·요약은 2주 뒤 스스로 지운다(cfg 는 남긴다)
const BOARD_MAX_ROWS = 20000;

/* 전화번호·주민번호·카드번호처럼 보이면 막는다. 완벽한 검사가 아니라 '실수 방지'가 목적. */
function looksPersonal(s) {
  const t = String(s || '');
  if (/\d{6}\s*[-–]\s*[1-4]\d{6}/.test(t)) return '주민등록번호처럼 보입니다';
  if (/01[016-9][\s-]?\d{3,4}[\s-]?\d{4}/.test(t)) return '전화번호처럼 보입니다';
  if (/\d[\d\s-]{12,}/.test(t)) return '긴 숫자(전화·카드번호)처럼 보입니다';
  if (/\d+\s*동\s*\d+\s*호/.test(t)) return '동·호수처럼 보입니다';
  return null;
}

function j(data, status = 200, extra = {}) {
  return new Response(JSON.stringify(data), {
    status,
    headers: {
      'content-type': 'application/json; charset=utf-8',
      'cache-control': 'no-store',
      'access-control-allow-origin': '*',
      'access-control-allow-headers': 'content-type',
      'access-control-allow-methods': 'GET,POST,OPTIONS',
      ...extra,
    },
  });
}

/* 열쇠는 그대로 저장하지 않는다 — 한 방향으로 섞은 값만 둔다 */
async function hash(s) {
  const b = await crypto.subtle.digest('SHA-256', new TextEncoder().encode('dispatch:' + s));
  return [...new Uint8Array(b)].map(x => x.toString(16).padStart(2, '0')).join('');
}

export class Log extends DurableObject {
  constructor(ctx, env) {
    super(ctx, env);
    this.sql = ctx.storage.sql;
    this.sql.exec(`CREATE TABLE IF NOT EXISTS notes(
      id TEXT PRIMARY KEY, ts INTEGER, station TEXT, sigun TEXT, type TEXT,
      place TEXT, lat REAL, lng REAL, memo TEXT, wx TEXT, who TEXT)`);
    this.sql.exec(`CREATE INDEX IF NOT EXISTS i_ts ON notes(ts)`);
    this.sql.exec(`CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v TEXT)`);
    /* board2 — del=1 은 '지운 자리 표시'. 지울 때 줄을 없애면, 늦게 도착한 옛 요청이 그 줄을 되살린다
       (PC A 의 실패한 체크가 PC B 의 해제 뒤에 재전송되는 경우). 지운 시각을 남겨 같은 '더 나중 것이 이긴다' 규칙을 쓴다. */
    this.sql.exec(`CREATE TABLE IF NOT EXISTS board2(
      station TEXT, kind TEXT, id TEXT, ts INTEGER, text TEXT, extra TEXT, del INTEGER DEFAULT 0,
      PRIMARY KEY(station, kind, id))`);
    this.sql.exec(`CREATE INDEX IF NOT EXISTS i_b2_ts ON board2(ts)`);
    this.sql.exec(`CREATE INDEX IF NOT EXISTS i_b2_kind ON board2(kind, ts)`);
    this.sql.exec(`DROP TABLE IF EXISTS board`);   // 2026-11-13 오전 몇 시간만 쓰인 첫 판(시험 줄뿐)
  }

  /* ── 관서 현황판 ── 열쇠 확인까지 한 번의 호출로 끝낸다(요청마다 저장소 호출 1회 — 무료 한도) */
  async board(op, code, a) {
    if (!(await this.ok(code))) return { ok: false, why: '열쇠가 필요합니다', status: 401 };
    const now = Date.now();
    if (op === 'list') return { ok: true, now, rows: this._boardList(now, a) };
    if (op === 'clear') {
      /* 그 관서의 한 종류를 모두 지움 표시(체크 초기화) — 화면이 아직 못 받은 줄까지 */
      const n = [...this.sql.exec('SELECT COUNT(*) AS c FROM board2 WHERE station=? AND kind=? AND del=0', a.station, a.kind)][0].c;
      this.sql.exec(`UPDATE board2 SET del=1, ts=?, text='', extra='' WHERE station=? AND kind=? AND del=0`, now, a.station, a.kind);
      return { ok: true, n, ts: now };
    }
    /* set / del — 같은 줄은 더 나중 시각의 것이 남는다. 시각이 같으면 나중에 도착한 것 */
    this.sql.exec(`INSERT INTO board2(station,kind,id,ts,text,extra,del) VALUES(?,?,?,?,?,?,?)
      ON CONFLICT(station,kind,id) DO UPDATE SET ts=excluded.ts, text=excluded.text, extra=excluded.extra, del=excluded.del
      WHERE excluded.ts >= board2.ts`, a.station, a.kind, a.id, a.ts, a.text, a.extra, op === 'del' ? 1 : 0);
    const cur = [...this.sql.exec('SELECT ts, del FROM board2 WHERE station=? AND kind=? AND id=?', a.station, a.kind, a.id)][0];
    const applied = !!cur && cur.ts === a.ts && cur.del === (op === 'del' ? 1 : 0);
    this._boardPrune(now);
    return { ok: true, ts: cur ? cur.ts : a.ts, applied };     // applied=false → 서버에 더 새 값이 있다
  }

  /* 정리는 한 시간에 한 번만 — 쓸 때마다 전체를 세면 무료 한도(읽은 줄 수)를 금방 넘는다 */
  _boardPrune(now) {
    if (now - (+this._meta('board_pruned') || 0) < 3600000) return;
    this._setMeta('board_pruned', String(now));
    this.sql.exec(`DELETE FROM board2 WHERE kind<>'cfg' AND ts < ?`, now - BOARD_KEEP_DAYS * 86400000);
    const n = [...this.sql.exec('SELECT COUNT(*) AS c FROM board2')][0].c;
    if (n > BOARD_MAX_ROWS) this.sql.exec(`DELETE FROM board2 WHERE rowid IN
      (SELECT rowid FROM board2 WHERE kind<>'cfg' ORDER BY ts ASC LIMIT ?)`, n - BOARD_MAX_ROWS);
  }

  /* 줄 목록.
     a.station 이 있으면 그 관서 것만(관서 화면) — 없으면 모든 관서(본부 화면).
     a.since 가 있으면 그 뒤에 바뀐 것만, 지움 표시(del=1)까지 함께 — 없으면 최근 a.hours 시간의 살아 있는 줄 전부.
     beat(관서 요약)는 기간과 상관없이 준다(마지막 접속 시각을 보여 주려고). cfg(목록)는 a.cfg 관서 것만(크다).
     종류마다 따로 묻는다 — 한 질의에 묶어 LIMIT 을 걸면 줄이 많은 날 beat·cfg 가 잘려 나간다. */
  _boardList(now, a) {
    const cols = 'station,kind,id,ts,text,extra,del';
    const from = a.since ? a.since : now - a.hours * 3600000;
    const liveOnly = a.since ? '' : ' AND del=0';
    const cmp = a.since ? 'ts > ?' : 'ts >= ?';
    let rows;
    if (a.station) {
      rows = [...this.sql.exec(`SELECT ${cols} FROM board2 WHERE station=? AND kind IN ('chk','todo','note') AND ${cmp}${liveOnly}
        ORDER BY ts DESC LIMIT 2000`, a.station, from)];
      rows = rows.concat([...this.sql.exec(`SELECT ${cols} FROM board2 WHERE station=? AND kind='beat' AND id='now'`, a.station)]);
    } else {
      rows = [...this.sql.exec(`SELECT ${cols} FROM board2 WHERE kind IN ('chk','todo','note') AND ${cmp}${liveOnly}
        ORDER BY ts DESC LIMIT 4000`, from)];
      rows = rows.concat(a.since
        ? [...this.sql.exec(`SELECT ${cols} FROM board2 WHERE kind='beat' AND ts > ?`, a.since)]
        : [...this.sql.exec(`SELECT ${cols} FROM board2 WHERE kind='beat'`)]);
    }
    if (a.cfg) {
      const c = [...this.sql.exec(`SELECT ${cols} FROM board2 WHERE station=? AND kind='cfg' AND id='todo' AND del=0`, a.cfg)];
      if (c.length && (!a.since || c[0].ts > a.since)) rows.push(c[0]);
    }
    return rows;
  }

  _meta(k) { const r = [...this.sql.exec('SELECT v FROM meta WHERE k=?', k)]; return r.length ? r[0].v : null; }
  _setMeta(k, v) { this.sql.exec('INSERT INTO meta(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=?', k, v, v); }

  async ok(code) {
    const want = this._meta('code');
    if (!want) return true;                       // 아직 열쇠를 안 정했으면 누구나(첫 사용)
    return !!code && (await hash(code)) === want;
  }

  /* 오래된 것·넘치는 것 정리 */
  _prune() {
    this.sql.exec('DELETE FROM notes WHERE ts < ?', Date.now() - KEEP_DAYS * 86400000);
    const n = [...this.sql.exec('SELECT COUNT(*) AS c FROM notes')][0].c;
    if (n > MAX_ROWS) this.sql.exec('DELETE FROM notes WHERE id IN (SELECT id FROM notes ORDER BY ts ASC LIMIT ?)', n - MAX_ROWS);
  }

  async status() {
    const n = [...this.sql.exec('SELECT COUNT(*) AS c FROM notes')][0].c;
    const last = [...this.sql.exec('SELECT ts FROM notes ORDER BY ts DESC LIMIT 1')];
    return { count: n, last: last.length ? last[0].ts : null, locked: !!this._meta('code') };
  }

  async setCode(cur, next) {
    if (!(await this.ok(cur))) return { ok: false, why: '지금 열쇠가 맞지 않습니다' };
    if (!next || String(next).length < 4) return { ok: false, why: '열쇠는 4자 이상' };
    this._setMeta('code', await hash(String(next)));
    return { ok: true };
  }

  async add(rec) {
    const id = crypto.randomUUID().slice(0, 8);
    this.sql.exec('INSERT INTO notes(id,ts,station,sigun,type,place,lat,lng,memo,wx,who) VALUES(?,?,?,?,?,?,?,?,?,?,?)',
      id, rec.ts, rec.station, rec.sigun, rec.type, rec.place, rec.lat, rec.lng, rec.memo, JSON.stringify(rec.wx || {}), rec.who || '');
    this._prune();
    return { ok: true, id };
  }

  async list(days, station) {
    const from = Date.now() - days * 86400000;
    const rows = station
      ? [...this.sql.exec('SELECT * FROM notes WHERE ts>=? AND station=? ORDER BY ts DESC LIMIT 500', from, station)]
      : [...this.sql.exec('SELECT * FROM notes WHERE ts>=? ORDER BY ts DESC LIMIT 500', from)];
    return rows.map(r => ({ ...r, wx: (() => { try { return JSON.parse(r.wx || '{}'); } catch (e) { return {}; } })() }));
  }

  async del(id) { this.sql.exec('DELETE FROM notes WHERE id=?', id); return { ok: true }; }

  async stats(days) {
    const from = Date.now() - days * 86400000;
    const by = (col) => [...this.sql.exec(`SELECT ${col} AS k, COUNT(*) AS c FROM notes WHERE ts>=? AND ${col}<>'' GROUP BY ${col} ORDER BY c DESC LIMIT 20`, from)];
    return {
      total: [...this.sql.exec('SELECT COUNT(*) AS c FROM notes WHERE ts>=?', from)][0].c,
      station: by('station'), type: by('type'), place: by('place'),
    };
  }
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const p = url.pathname;
    /* 브라우저가 POST 전에 보내는 사전 확인 — 204 에는 본문을 넣으면 안 된다(넣으면 500) */
    if (request.method === 'OPTIONS') return new Response(null, { status: 204, headers: {
      'access-control-allow-origin': '*', 'access-control-allow-headers': 'content-type',
      'access-control-allow-methods': 'GET,POST,OPTIONS', 'access-control-max-age': '86400' } });
    if (p === '/api/ping') return j({ ok: true, now: Date.now() });

    const key = (url.searchParams.get('key') || '').trim() || 'all';
    if (!/^[a-z]{2,16}$/.test(key)) return j({ ok: false, why: '지역키가 올바르지 않습니다' }, 400);
    const room = env.LOG.get(env.LOG.idFromName(key));

    let body = {};
    if (request.method === 'POST') { try { body = await request.json(); } catch (e) { body = {}; } }
    const code = String(body.code || url.searchParams.get('code') || '');
    const bkey = String(body.key == null ? key : body.key).trim();
    if (!/^[a-z]{2,16}$/.test(bkey)) return j({ ok: false, why: '지역키가 올바르지 않습니다' }, 400);
    const broom = bkey === key ? room : env.LOG.get(env.LOG.idFromName(bkey));

    try {
      if (p === '/api/status') return j({ ok: true, ...(await room.status()) });

      if (p === '/api/code' && request.method === 'POST')
        return j(await broom.setCode(code, body.next));

      if (p === '/api/note' && request.method === 'POST') {
        if (!(await broom.ok(code))) return j({ ok: false, why: '열쇠가 필요합니다' }, 401);
        const type = TYPES.includes(body.type) ? body.type : '기타';
        const place = String(body.place || '').slice(0, MAX_PLACE).trim();
        const memo = String(body.memo || '').slice(0, MAX_MEMO).trim();
        const bad = looksPersonal(place + ' ' + memo);
        if (bad) return j({ ok: false, why: bad + ' — 개인정보는 적지 않습니다' }, 400);
        const station = String(body.station || '').slice(0, 20).trim();
        if (!station) return j({ ok: false, why: '관서가 없습니다' }, 400);
        const num = (v) => (v == null || isNaN(+v) ? null : +v);
        return j(await broom.add({
          ts: Date.now(), station, sigun: String(body.sigun || '').slice(0, 20),
          type, place, memo, lat: num(body.lat), lng: num(body.lng),
          wx: body.wx || {}, who: String(body.who || '').slice(0, 20),
        }));
      }

      if (p === '/api/notes') {
        if (!(await room.ok(code))) return j({ ok: false, why: '열쇠가 필요합니다' }, 401);
        const days = Math.min(400, Math.max(1, +(url.searchParams.get('days') || 14)));
        return j({ ok: true, notes: await room.list(days, (url.searchParams.get('station') || '').trim()) });
      }

      if (p === '/api/del' && request.method === 'POST') {
        if (!(await broom.ok(code))) return j({ ok: false, why: '열쇠가 필요합니다' }, 401);
        return j(await broom.del(String(body.id || '')));
      }

      /* ── 관서 현황판 ── */
      if (p.startsWith('/api/board/') && request.method === 'POST') {
        const op = p.slice('/api/board/'.length);
        if (!['set', 'del', 'clear'].includes(op)) return j({ ok: false, why: '없는 주소' }, 404);
        const station = String(body.station || '').slice(0, 20).trim();
        const kind = String(body.kind || '');
        if (!station) return j({ ok: false, why: '관서가 없습니다' }, 400);
        if (!BOARD_KINDS.includes(kind)) return j({ ok: false, why: '종류가 올바르지 않습니다' }, 400);
        if (op === 'clear') {
          if (kind !== 'chk' && kind !== 'todo') return j({ ok: false, why: '이 종류는 한꺼번에 지울 수 없습니다' }, 400);
          const r = await broom.board('clear', code, { station, kind });
          return j(r, r.status || 200);
        }
        const id = String(body.id || '').slice(0, 120);
        if (!id) return j({ ok: false, why: 'id 가 없습니다' }, 400);
        /* 시각 — 화면이 서버 시각에 맞춰 보낸 값(누른 때)을 쓴다. 재전송이 늦게 와도 '누른 때'로 겨루게.
           미래이거나 너무 옛날이면 지금으로. 관서 요약(beat)은 늘 서버의 지금 — 접속 시각이 PC 시계에 휘둘리지 않게. */
        const now = Date.now();
        let ts = Math.floor(+body.ts);
        if (kind === 'beat' || !(ts > now - BOARD_KEEP_DAYS * 86400000 && ts <= now + 60000)) ts = now;
        if (op === 'del') {
          const r = await broom.board('del', code, { station, kind, id, ts, text: '', extra: '' });
          return j(r, r.status || 200);
        }
        const text = String(body.text || '').slice(0, BOARD_TEXT).trim();
        const extra = body.extra == null ? '' : (typeof body.extra === 'string' ? body.extra : JSON.stringify(body.extra));
        if (extra.length > (kind === 'cfg' ? BOARD_EXTRA_CFG : BOARD_EXTRA)) return j({ ok: false, why: '내용이 너무 깁니다' }, 400);
        /* 개인정보 — 사람이 적은 글을 본다. 숫자 묶음(JSON)은 통째로 보지 않는다(시각 13자리를 긴 숫자로 오인) */
        let bad = looksPersonal(text);
        try {
          if (!bad && kind === 'cfg' && extra) { for (const it of (JSON.parse(extra).items || [])) { bad = looksPersonal(it && it.text); if (bad) break; } }
          else if (!bad && kind === 'beat' && extra) bad = looksPersonal(JSON.parse(extra).why);
          else if (!bad && extra) bad = looksPersonal(extra);
        } catch (e) { return j({ ok: false, why: '형식이 올바르지 않습니다' }, 400); }
        if (bad) return j({ ok: false, why: bad + ' — 개인정보는 적지 않습니다' }, 400);
        const r = await broom.board('set', code, { station, kind, id, ts, text, extra });
        return j(r, r.status || 200);
      }

      if (p === '/api/board') {
        const q = (n) => (url.searchParams.get(n) || '').slice(0, 20).trim();
        const since = Math.floor(+(url.searchParams.get('since') || 0));
        const r = await room.board('list', code, {
          hours: Math.min(24 * BOARD_KEEP_DAYS, Math.max(1, +(url.searchParams.get('hours') || 48))),
          station: q('station'), cfg: q('cfg'), since: since > 0 ? since : 0,
        });
        return j(r, r.status || 200);
      }

      if (p === '/api/stats') {
        if (!(await room.ok(code))) return j({ ok: false, why: '열쇠가 필요합니다' }, 401);
        const days = Math.min(1100, Math.max(1, +(url.searchParams.get('days') || 90)));
        return j({ ok: true, ...(await room.stats(days)) });
      }
    } catch (e) {
      return j({ ok: false, why: '저장소 오류: ' + (e && e.message ? e.message : String(e)) }, 500);
    }
    return j({ ok: false, why: '없는 주소' }, 404);
  },
};
