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
 *   POST /api/board/set               한 줄 올리기/고치기     (열쇠 필요)
 *   POST /api/board/del               한 줄 지우기           (열쇠 필요)
 *   GET  /api/board?key=all&hours=48  모든 관서의 줄(cfg= 로 그 관서의 목록 설정도) (열쇠 필요)
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
    this.sql.exec(`CREATE TABLE IF NOT EXISTS board(
      station TEXT, kind TEXT, id TEXT, ts INTEGER, text TEXT, extra TEXT,
      PRIMARY KEY(station, kind, id))`);
    this.sql.exec(`CREATE INDEX IF NOT EXISTS i_board_ts ON board(ts)`);
  }

  /* ── 관서 현황판 ── */
  async boardSet(r) {
    /* 같은 줄을 두 화면이 올리면 더 나중 시각의 것이 남는다(늦게 도착한 옛 값이 새 값을 덮지 않게) */
    this.sql.exec(`INSERT INTO board(station,kind,id,ts,text,extra) VALUES(?,?,?,?,?,?)
      ON CONFLICT(station,kind,id) DO UPDATE SET ts=excluded.ts, text=excluded.text, extra=excluded.extra
      WHERE excluded.ts >= board.ts`, r.station, r.kind, r.id, r.ts, r.text, r.extra);
    this.sql.exec(`DELETE FROM board WHERE kind<>'cfg' AND ts < ?`, Date.now() - BOARD_KEEP_DAYS * 86400000);
    const n = [...this.sql.exec('SELECT COUNT(*) AS c FROM board')][0].c;
    if (n > BOARD_MAX_ROWS) this.sql.exec(`DELETE FROM board WHERE rowid IN
      (SELECT rowid FROM board WHERE kind<>'cfg' ORDER BY ts ASC LIMIT ?)`, n - BOARD_MAX_ROWS);
    return { ok: true, ts: r.ts };
  }

  async boardDel(station, kind, id) {
    this.sql.exec('DELETE FROM board WHERE station=? AND kind=? AND id=?', station, kind, id);
    return { ok: true };
  }

  /* 모든 관서의 줄. beat 는 기간과 상관없이(마지막 접속 시각을 보여 주려고), cfg 는 부탁한 관서 것만(크다). */
  async boardList(hours, cfgStation) {
    const from = Date.now() - hours * 3600000;
    const rows = [...this.sql.exec(
      `SELECT station,kind,id,ts,text,extra FROM board
       WHERE (kind IN ('chk','todo','note') AND ts>=?) OR kind='beat' OR (kind='cfg' AND station=?)
       ORDER BY ts DESC LIMIT 5000`, from, cfgStation || '')];
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
    const bkey = (body.key || key).trim();
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
      if (p === '/api/board/set' && request.method === 'POST') {
        if (!(await broom.ok(code))) return j({ ok: false, why: '열쇠가 필요합니다' }, 401);
        const station = String(body.station || '').slice(0, 20).trim();
        const kind = String(body.kind || '');
        const id = String(body.id || '').slice(0, 120);
        if (!station) return j({ ok: false, why: '관서가 없습니다' }, 400);
        if (!BOARD_KINDS.includes(kind) || !id) return j({ ok: false, why: '종류나 id 가 올바르지 않습니다' }, 400);
        const text = String(body.text || '').slice(0, BOARD_TEXT).trim();
        let extra = body.extra == null ? '' : (typeof body.extra === 'string' ? body.extra : JSON.stringify(body.extra));
        if (extra.length > (kind === 'cfg' ? BOARD_EXTRA_CFG : BOARD_EXTRA)) return j({ ok: false, why: '내용이 너무 깁니다' }, 400);
        /* 개인정보 — 사람이 적는 글만 본다(beat 의 숫자 묶음을 긴 숫자로 오인하지 않게) */
        let bad = (kind === 'beat') ? null : looksPersonal(text);
        if (!bad && kind === 'cfg' && extra) {
          try { for (const it of (JSON.parse(extra).items || [])) { bad = looksPersonal(it && it.text); if (bad) break; } }
          catch (e) { return j({ ok: false, why: '목록 형식이 아닙니다' }, 400); }
        }
        if (bad) return j({ ok: false, why: bad + ' — 개인정보는 적지 않습니다' }, 400);
        /* 시각 — 화면이 보낸 값을 쓰되(체크한 시각), 미래이거나 너무 옛날이면 지금으로 */
        const now = Date.now();
        let ts = +body.ts;
        if (!(ts > now - BOARD_KEEP_DAYS * 86400000 && ts < now + 5 * 60000)) ts = now;
        return j(await broom.boardSet({ station, kind, id, ts, text, extra }));
      }

      if (p === '/api/board/del' && request.method === 'POST') {
        if (!(await broom.ok(code))) return j({ ok: false, why: '열쇠가 필요합니다' }, 401);
        const kind = String(body.kind || '');
        if (!BOARD_KINDS.includes(kind)) return j({ ok: false, why: '종류가 올바르지 않습니다' }, 400);
        return j(await broom.boardDel(String(body.station || '').slice(0, 20).trim(), kind, String(body.id || '').slice(0, 120)));
      }

      if (p === '/api/board') {
        if (!(await room.ok(code))) return j({ ok: false, why: '열쇠가 필요합니다' }, 401);
        const hours = Math.min(24 * BOARD_KEEP_DAYS, Math.max(1, +(url.searchParams.get('hours') || 48)));
        return j({ ok: true, now: Date.now(), rows: await room.boardList(hours, (url.searchParams.get('cfg') || '').slice(0, 20).trim()) });
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
