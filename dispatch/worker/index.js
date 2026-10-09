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
 * 지역키(key)는 화면의 REGION_CONF.key 를 그대로 쓴다(경기 전체판은 'all').
 */

import { DurableObject } from "cloudflare:workers";

const TYPES = ['침수', '도로장애', '인명구조', '배수지원', '안전조치', '기타'];
const MAX_MEMO = 60;        // 한 줄 메모 — 길면 사연이 들어가고 개인정보가 섞인다
const MAX_PLACE = 40;
const KEEP_DAYS = 1100;     // 3년쯤 보관(장마 세 번 비교용). 그 이상은 스스로 지운다
const MAX_ROWS = 20000;     // 한 지역 상한 — 넘으면 오래된 것부터

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
