/* ============================================================================
   상황실 카드 배치 편집기 — 2026-09-17 사장님 지시("내 입맛대로 카드를 넣고 빼고 배치")
   ----------------------------------------------------------------------------
   화면(React/dc-runtime)은 건드리지 않는다. 카드 위치는 CSS 변수(--wl-<id>-*)로만
   전달하고, 이 파일은 그 변수를 :root 에 쓴다. React 가 0.5초마다 다시 그려도
   :root 변수는 살아남는다(2026-09-17 실측: 리렌더·관서순환·배너 토글 모두 보존).

   격자: 12열 × 24행, 각 카드 = (c, r, cs, rs) + hide + fz(글자 배율)
   저장: localStorage ggWallLayout:<권역>  (권역별 배치. 없으면 기본)
   심기: ?layout=<코드>  → 저장하고 주소에서 지운다.  ?layout=reset → 저장본 삭제
   안전: 경보 카드(특보·하천·재난문자)는 숨길 수 없다. 편집 모드는 3분 무조작이면 자동
         종료되고 순환이 복원된다. 편집 모드 자체는 어디에도 저장하지 않는다.
   ============================================================================ */
(function () {
  'use strict';
  var COLS = 12, ROWS = 24, VER = 1;

  /* 카드 id = '자리'의 이름. 데이터 종류가 바뀌어도 id 는 영구 고정(저장된 배치 보호). */
  var CARDS = [
    { id: 'obs',    name: '현재 실황',       min: [4, 4] },
    { id: 'hourly', name: '시간대별 예보',   min: [4, 5] },
    { id: 'warn',   name: '기상특보',        min: [3, 4], noHide: true },
    { id: 'river',  name: '하천 수위',       min: [3, 4], noHide: true },
    { id: 'impact', name: '출동 영향 판단',  min: [3, 5] },
    { id: 'msg',    name: '재난문자',        min: [3, 5], noHide: true },
    { id: 'idx',    name: '산불·미세먼지·일출', min: [3, 3], disp: 'grid' },   /* 칩 3개 가로 3등분 — flex 로 두면 폭이 내용만큼만 */
    { id: 'ultra',  name: '6시간 강수예측',  min: [3, 4] },
    /* 2026-09-18 추가 — 기본 숨김. 자리가 겹치므로 켜기 전에 다른 카드를 줄여 자리를 내야 한다 */
    { id: 'radar',  name: '레이더 영상',     min: [3, 5] },
    { id: 'typhoon',name: '태풍 현황',       min: [4, 4] },
    { id: 'tide',   name: '물때 (파주)',      min: [3, 4] }
  ];
  /* 기본 배치 = 지금 화면과 같은 모양을 12×24 로 옮긴 것(실측 튜닝). */
  var DEFAULT = {
    obs:    { c: 1, r: 1,  cs: 4, rs: 8 },
    hourly: { c: 1, r: 9, cs: 4, rs: 16 },
    warn:   { c: 5, r: 1,  cs: 4, rs: 6 },
    river:  { c: 5, r: 7,  cs: 4, rs: 6 },
    impact: { c: 5, r: 13, cs: 4, rs: 12 },
    msg:    { c: 9, r: 1,  cs: 4, rs: 10 },
    idx:    { c: 9, r: 11, cs: 4, rs: 6 },
    ultra:  { c: 9, r: 17, cs: 4, rs: 8 },
    radar:  { c: 9, r: 17, cs: 4, rs: 8, hide: true },
    typhoon:{ c: 9, r: 17, cs: 4, rs: 8, hide: true },
    tide:   { c: 9, r: 17, cs: 4, rs: 8, hide: true }
  };
  var BY_ID = {}; CARDS.forEach(function (k) { BY_ID[k.id] = k; });

  /* ── 권역 (상황실 NAMES 와 같은 규칙) ── */
  function scopeKey() {
    var RC = window.REGION_CONF || {}, g = RC.scopes || {}, sc = null;
    try { sc = new URLSearchParams(location.search).get('scope'); } catch (e) {}
    if (sc && !g[sc] && g['경기' + sc]) sc = '경기' + sc;
    if (!sc) { try { var v = localStorage.getItem('ggScope'); if (v === '전체') return '전체'; if (v && g[v]) sc = v; } catch (e) {} }
    if (!sc) { try { sc = (RC.hostScope || {})[location.hostname.split('.')[0]] || null; } catch (e) {} }
    return (sc && g[sc]) ? sc : '전체';
  }
  var SCOPE = scopeKey();
  var KEY = 'ggWallLayout:' + SCOPE, KEY_PREV = KEY + ':prev';

  /* ── 검증: 범위·최소·겹침·전부숨김. 통과 못 하면 null ── */
  function clone(L) { return JSON.parse(JSON.stringify(L)); }
  function overlap(a, b) { return a.c < b.c + b.cs && b.c < a.c + a.cs && a.r < b.r + b.rs && b.r < a.r + a.rs; }
  function validate(L) {
    if (!L || typeof L !== 'object') return null;
    var out = {}, vis = [];
    for (var i = 0; i < CARDS.length; i++) {
      var k = CARDS[i], p = L[k.id];
      if (!p) p = DEFAULT[k.id];
      var c = +p.c | 0, r = +p.r | 0, cs = +p.cs | 0, rs = +p.rs | 0;
      if (c < 1 || r < 1 || cs < k.min[0] || rs < k.min[1] || c + cs - 1 > COLS || r + rs - 1 > ROWS) return null;
      var hide = !!p.hide && !k.noHide;
      var fz = [0.8, 1, 1.2, 1.4].indexOf(+p.fz) >= 0 ? +p.fz : 1;
      out[k.id] = { c: c, r: r, cs: cs, rs: rs, hide: hide, fz: fz };
      if (!hide) vis.push(out[k.id]);
    }
    if (!vis.length) return null;
    for (var a = 0; a < vis.length; a++) for (var b = a + 1; b < vis.length; b++) if (overlap(vis[a], vis[b])) return null;
    return out;
  }

  /* ── 짧은 코드: 카드 순서대로 c r cs rs 를 한 자리(36진)씩 + 숨김/배율 플래그 ──
     예) obs=1,1,4,9 → "1149"  → 8장이면 32자 + 헤더. 사람이 전화로 불러줄 수 있는 길이. */
  function encode(L) {
    var s = 'W' + VER + SCOPE.replace('경기', '').charAt(0) + '.';
    CARDS.forEach(function (k) { var p = L[k.id];
      s += p.c.toString(36) + p.r.toString(36) + p.cs.toString(36) + p.rs.toString(36)
         + (p.hide ? 'x' : '') + (p.fz !== 1 ? ({0.8: 's', 1.2: 'l', 1.4: 'h'})[p.fz] : ''); s += '.'; });
    return s.replace(/\.$/, '');
  }
  function decode(code) {
    try {
      var m = String(code || '').trim().match(/^W(\d)[전북남]?\.(.+)$/); if (!m || +m[1] !== VER) return null;
      var parts = m[2].split('.'); if (parts.length !== CARDS.length) return null;
      var L = {};
      for (var i = 0; i < CARDS.length; i++) {
        var q = parts[i].match(/^([0-9a-z])([0-9a-z])([0-9a-z])([0-9a-z])(x?)([slh]?)$/); if (!q) return null;
        L[CARDS[i].id] = { c: parseInt(q[1], 36), r: parseInt(q[2], 36), cs: parseInt(q[3], 36), rs: parseInt(q[4], 36),
          hide: q[5] === 'x', fz: ({s: 0.8, l: 1.2, h: 1.4})[q[6]] || 1 };
      }
      return validate(L);
    } catch (e) { return null; }
  }

  /* ── 저장·로드 ── */
  function load() {
    try { var u = new URLSearchParams(location.search).get('layout');
      if (u === 'reset') { localStorage.removeItem(KEY); localStorage.removeItem(KEY_PREV); stripParam(); }
      else if (u) { var d = decode(u); if (d) { save(d); stripParam(); return d; } console.warn('[wall] layout 코드가 잘못됨 — 무시'); }
    } catch (e) {}
    try { var v = validate(JSON.parse(localStorage.getItem(KEY) || 'null')); if (v) return v; } catch (e) {}
    return validate(clone(DEFAULT));
  }
  function stripParam() { try { var url = new URL(location.href); url.searchParams.delete('layout'); history.replaceState(null, '', url); } catch (e) {} }
  function save(L) {
    try { var cur = localStorage.getItem(KEY); if (cur) localStorage.setItem(KEY_PREV, cur);
      localStorage.setItem(KEY, JSON.stringify(L)); return true; }
    catch (e) { console.warn('[wall] 저장 실패 — 이 PC는 배치를 기억하지 못합니다. 바로가기 주소에 ?layout= 코드를 넣으세요.'); return false; }
  }
  function isDefault(L) { return CARDS.every(function (k) { var a = L[k.id], b = DEFAULT[k.id];
    return a.c === b.c && a.r === b.r && a.cs === b.cs && a.rs === b.rs && !!a.hide === !!b.hide && a.fz === 1; }); }

  /* ── 적용: :root 변수 (React 마운트 전에 한 번, 편집 중엔 매 변경마다) ── */
  var LAYOUT = load();
  function apply(L) {
    var st = document.documentElement.style;
    CARDS.forEach(function (k) { var p = L[k.id], pre = '--wl-' + k.id + '-';
      st.setProperty(pre + 'c', p.c); st.setProperty(pre + 'r', p.r);
      st.setProperty(pre + 'cs', p.cs); st.setProperty(pre + 'rs', p.rs);
      st.setProperty(pre + 'd', p.hide ? 'none' : (k.disp || 'flex')); st.setProperty(pre + 'fz', p.fz); });
    window.WALL_LAYOUT = L;
  }
  apply(LAYOUT);

  /* ════════════════════════ 편집 모드 (DOM 준비 후) ════════════════════════ */
  var EDIT = false, sel = null, idleT = null, IDLE_MS = 180000, ov = null, hud = null, badge = null, raf = 0;

  function $(tag, css, html) { var e = document.createElement(tag); if (css) e.style.cssText = css; if (html != null) e.innerHTML = html; return e; }
  function cardEl(id) { return document.querySelector('[data-card="' + id + '"]'); }
  function gridEl() { return document.querySelector('[data-wall-grid]'); }
  function stageScale() { var s = document.querySelector('[data-wall-grid]'); if (!s) return 1;
    var st = s.closest('div[style*="3840px"]') || s.parentElement; return st.getBoundingClientRect().width / 3840; }

  function toast(msg, ms) { var t = $('div', 'position:fixed;left:50%;bottom:28px;transform:translateX(-50%);z-index:60;background:var(--panel,#141e33);color:var(--fg,#f3f6fc);border:1px solid var(--cAmber,#ffb020);border-radius:12px;padding:12px 20px;font:600 15px/1.4 system-ui,sans-serif;box-shadow:0 8px 30px rgba(0,0,0,.5);', msg);
    document.body.appendChild(t); setTimeout(function () { t.remove(); }, ms || 2200); }

  function ctl(on) { try { window.dispatchEvent(new CustomEvent('wall:edit', { detail: { on: on } })); } catch (e) {} }
  function touch() { clearTimeout(idleT); if (EDIT) idleT = setTimeout(function () { setEdit(false); toast('3분 동안 조작이 없어 편집을 끝냈습니다 · 순환 재개'); }, IDLE_MS); }

  /* 배지: 사용자 배치일 때 좌상단에 상시 (← 상황판 링크 옆 관례) */
  function renderBadge() {
    if (!badge) { badge = $('div', 'position:absolute;left:190px;top:8px;z-index:20;display:flex;gap:6px;'); document.body.appendChild(badge); }
    var custom = !isDefault(LAYOUT);
    badge.innerHTML = '';
    var b1 = $('a', 'cursor:pointer;opacity:.28;padding:6px 11px;border-radius:9px;border:1px solid var(--line,#28313f);background:var(--panel,#151b26);color:var(--fg,#f2f5fa);font:600 12px system-ui,sans-serif;white-space:nowrap;', '✎ 배치 편집');
    b1.onmouseenter = function () { b1.style.opacity = 1; }; b1.onmouseleave = function () { b1.style.opacity = .28; };
    b1.onclick = function () { setEdit(!EDIT); };
    badge.appendChild(b1);
    if (custom) { var b2 = $('a', 'cursor:pointer;opacity:.5;padding:6px 11px;border-radius:9px;border:1px solid var(--cAmber,#ffb020);background:var(--panel,#151b26);color:var(--cAmber,#ffb020);font:600 12px system-ui,sans-serif;white-space:nowrap;', '사용자 배치 · 되돌리기');
      b2.onclick = function () { if (confirm('기본 배치로 되돌릴까요? (직전 배치는 1단계 보관됩니다)')) { LAYOUT = validate(clone(DEFAULT)); save(LAYOUT); apply(LAYOUT); refresh(); toast('기본 배치로 되돌렸습니다'); } };
      badge.appendChild(b2); }
  }

  /* 오버레이: React 밖 고정 레이어. 카드 위치는 매 프레임 실측해 따라간다. */
  function ensureOverlay() {
    if (ov) return;
    ov = $('div', 'position:fixed;inset:0;z-index:30;pointer-events:none;display:none;');
    document.body.appendChild(ov);
    hud = $('div', 'position:fixed;left:50%;top:10px;transform:translateX(-50%);z-index:40;display:none;background:#141e33;border:2px solid #ffb020;border-radius:14px;padding:10px 14px;color:#f3f6fc;font:600 14px/1.3 system-ui,sans-serif;box-shadow:0 10px 40px rgba(0,0,0,.55);pointer-events:auto;user-select:none;');
    document.body.appendChild(hud);
  }
  function setEdit(on) {
    ensureOverlay(); EDIT = on; sel = null;
    ov.style.display = on ? 'block' : 'none'; hud.style.display = on ? 'block' : 'none';
    ctl(on); touch(); if (on) { toast('편집 모드 · 관서 순환 멈춤 · 3분 무조작 시 자동 종료'); loop(); } else { cancelAnimationFrame(raf); }
    refresh();
  }
  function refresh() { renderBadge(); if (EDIT) { renderHud(); drawBoxes(); } }

  /* 카드 상자·손잡이 */
  var boxes = {};
  function drawBoxes() {
    ov.innerHTML = ''; boxes = {};
    CARDS.forEach(function (k) {
      var p = LAYOUT[k.id], el = cardEl(k.id); if (!el) return;
      var b = $('div', 'position:absolute;border:3px dashed rgba(255,176,32,.7);border-radius:12px;box-sizing:border-box;pointer-events:auto;cursor:move;');
      if (p.hide) b.style.cssText += 'border-style:dotted;border-color:rgba(142,155,176,.6);background:rgba(20,30,51,.55);';
      if (sel === k.id) b.style.cssText += 'border-color:#ffb020;border-style:solid;box-shadow:0 0 0 4px rgba(255,176,32,.25);';
      var lab = $('div', 'position:absolute;left:6px;top:6px;background:#141e33;color:#ffb020;border:1px solid #ffb020;border-radius:8px;padding:3px 9px;font:700 13px system-ui,sans-serif;white-space:nowrap;', k.name + (p.hide ? ' (숨김)' : ''));
      b.appendChild(lab);
      if (!p.hide) { var rz = $('div', 'position:absolute;right:-2px;bottom:-2px;width:26px;height:26px;background:#ffb020;border-radius:8px 0 10px 0;cursor:nwse-resize;', ''); rz.dataset.rz = '1'; b.appendChild(rz); }
      b.onpointerdown = function (ev) { if (ev.target.dataset.rz) startResize(ev, k.id); else startDrag(ev, k.id); };
      ov.appendChild(b); boxes[k.id] = b;
    });
    positionBoxes();
  }
  function positionBoxes() {
    CARDS.forEach(function (k) { var b = boxes[k.id], el = cardEl(k.id); if (!b || !el) return;
      var p = LAYOUT[k.id];
      if (p.hide) { var g = cellRect(p); Object.assign(b.style, { left: g.x + 'px', top: g.y + 'px', width: g.w + 'px', height: g.h + 'px' }); return; }
      var r = el.getBoundingClientRect(); Object.assign(b.style, { left: r.left + 'px', top: r.top + 'px', width: r.width + 'px', height: r.height + 'px' }); });
  }
  function loop() { if (!EDIT) return; positionBoxes(); raf = requestAnimationFrame(loop); }
  /* 격자 셀 → 화면 좌표 (숨긴 카드 상자용) */
  function cellRect(p) { var g = gridEl().getBoundingClientRect(), cw = g.width / COLS, rh = g.height / ROWS;
    return { x: g.left + (p.c - 1) * cw, y: g.top + (p.r - 1) * rh, w: p.cs * cw, h: p.rs * rh }; }
  function toCell(x, y) { var g = gridEl().getBoundingClientRect();
    return { c: Math.max(1, Math.min(COLS, Math.floor((x - g.left) / (g.width / COLS)) + 1)),
             r: Math.max(1, Math.min(ROWS, Math.floor((y - g.top) / (g.height / ROWS)) + 1)) }; }

  function tryApply(id, np) {
    var L = clone(LAYOUT); L[id] = Object.assign({}, L[id], np);
    var v = validate(L); if (!v) return false;
    LAYOUT = v; apply(LAYOUT); save(LAYOUT); return true;
  }
  function flash(id) { var b = boxes[id]; if (!b) return; b.style.borderColor = '#ff5a5a'; setTimeout(function () { drawBoxes(); }, 350); }

  /* 드래그 이동 (책상 PC용 보조) — 스테이지 배율은 매 이동마다 다시 잰다 */
  function startDrag(ev, id) {
    ev.preventDefault(); sel = id; touch(); drawBoxes();
    var p0 = LAYOUT[id], start = toCell(ev.clientX, ev.clientY), last = null;
    var b = boxes[id]; b.setPointerCapture(ev.pointerId); document.body.style.userSelect = 'none';
    b.onpointermove = function (e) { touch(); var cur = toCell(e.clientX, e.clientY);
      var nc = p0.c + (cur.c - start.c), nr = p0.r + (cur.r - start.r);
      nc = Math.max(1, Math.min(COLS - p0.cs + 1, nc)); nr = Math.max(1, Math.min(ROWS - p0.rs + 1, nr));
      if (last && last.c === nc && last.r === nr) return; last = { c: nc, r: nr };
      var L = clone(LAYOUT); L[id].c = nc; L[id].r = nr; var ok = !!validate(L);
      b.style.borderColor = ok ? '#ffb020' : '#ff5a5a';
      if (ok) { LAYOUT = validate(L); apply(LAYOUT); } };
    b.onpointerup = function () { b.onpointermove = null; b.onpointerup = null; document.body.style.userSelect = '';
      save(LAYOUT); drawBoxes(); renderHud(); };
  }
  function startResize(ev, id) {
    ev.preventDefault(); ev.stopPropagation(); sel = id; touch(); drawBoxes();
    var p0 = LAYOUT[id], start = toCell(ev.clientX, ev.clientY), b = boxes[id];
    b.setPointerCapture(ev.pointerId); document.body.style.userSelect = 'none';
    b.onpointermove = function (e) { touch(); var cur = toCell(e.clientX, e.clientY);
      var ncs = Math.max(BY_ID[id].min[0], p0.cs + (cur.c - start.c)), nrs = Math.max(BY_ID[id].min[1], p0.rs + (cur.r - start.r));
      ncs = Math.min(ncs, COLS - p0.c + 1); nrs = Math.min(nrs, ROWS - p0.r + 1);
      var L = clone(LAYOUT); L[id].cs = ncs; L[id].rs = nrs; var ok = !!validate(L);
      b.style.borderColor = ok ? '#ffb020' : '#ff5a5a'; if (ok) { LAYOUT = validate(L); apply(LAYOUT); } };
    b.onpointerup = function () { b.onpointermove = null; b.onpointerup = null; document.body.style.userSelect = '';
      save(LAYOUT); drawBoxes(); renderHud(); };
  }

  /* 편집 패널 — 버튼만으로 완결 (벽면 PC 주 수단) */
  function renderHud() {
    var k = sel ? BY_ID[sel] : null, p = sel ? LAYOUT[sel] : null;
    var h = '<div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap;">';
    h += '<span style="color:#ffb020;">✎ 편집 중</span><span style="color:#8e9bb0;">· 순환 멈춤 · 3분 무조작 시 자동 종료</span>';
    h += '<select data-a="sel" style="background:#0b1220;color:#f3f6fc;border:1px solid #28313f;border-radius:8px;padding:5px 8px;font:600 13px system-ui;"><option value="">카드 선택…</option>';
    CARDS.forEach(function (c) { h += '<option value="' + c.id + '"' + (sel === c.id ? ' selected' : '') + '>' + c.name + (LAYOUT[c.id].hide ? ' (숨김)' : '') + '</option>'; });
    h += '</select>';
    if (k) {
      var B = function (a, t, dis) { return '<button data-a="' + a + '"' + (dis ? ' disabled' : '') + ' style="background:#1b2230;color:#f3f6fc;border:1px solid #28313f;border-radius:8px;padding:5px 10px;font:700 13px system-ui;cursor:pointer;' + (dis ? 'opacity:.35;cursor:default;' : '') + '">' + t + '</button>'; };
      h += '<span style="border-left:1px solid #28313f;height:22px;"></span>';
      h += B('l', '◀') + B('r', '▶') + B('u', '▲') + B('d', '▼');
      h += '<span style="color:#8e9bb0;font-size:12px;">폭</span>' + B('w-', '−') + B('w+', '+');
      h += '<span style="color:#8e9bb0;font-size:12px;">높이</span>' + B('h-', '−') + B('h+', '+');
      h += '<span style="color:#8e9bb0;font-size:12px;">글자</span>';
      [[0.8, '작게'], [1, '보통'], [1.2, '크게'], [1.4, '아주크게']].forEach(function (f) { h += '<button data-a="fz" data-v="' + f[0] + '" style="background:' + (p.fz === f[0] ? '#ffb020' : '#1b2230') + ';color:' + (p.fz === f[0] ? '#101725' : '#f3f6fc') + ';border:1px solid #28313f;border-radius:8px;padding:5px 9px;font:700 12px system-ui;cursor:pointer;">' + f[1] + '</button>'; });
      h += k.noHide ? '<span style="color:#8e9bb0;font-size:12px;">경보 카드 · 숨길 수 없음</span>' : B('hide', p.hide ? '👁 다시 보이기' : '👁 숨기기');
    }
    h += '<span style="border-left:1px solid #28313f;height:22px;"></span>';
    h += '<button data-a="copy" style="background:#1b2230;color:#f3f6fc;border:1px solid #28313f;border-radius:8px;padding:5px 10px;font:700 13px system-ui;cursor:pointer;">배치 코드 복사</button>';
    h += '<button data-a="paste" style="background:#1b2230;color:#f3f6fc;border:1px solid #28313f;border-radius:8px;padding:5px 10px;font:700 13px system-ui;cursor:pointer;">코드 붙여넣기</button>';
    h += '<button data-a="undo" style="background:#1b2230;color:#f3f6fc;border:1px solid #28313f;border-radius:8px;padding:5px 10px;font:700 13px system-ui;cursor:pointer;">직전으로</button>';
    h += '<button data-a="reset" style="background:#1b2230;color:#ff9a3c;border:1px solid #28313f;border-radius:8px;padding:5px 10px;font:700 13px system-ui;cursor:pointer;">기본 배치</button>';
    h += '<button data-a="done" style="background:#ffb020;color:#101725;border:0;border-radius:8px;padding:6px 14px;font:800 13px system-ui;cursor:pointer;">완료</button>';
    h += '</div>';
    hud.innerHTML = h;
    hud.querySelector('[data-a=sel]').onchange = function () { sel = this.value || null; touch(); drawBoxes(); renderHud(); };
    hud.querySelectorAll('button[data-a]').forEach(function (btn) { btn.onclick = function () { act(btn.dataset.a, btn.dataset.v); }; });
  }
  function act(a, v) {
    touch(); var p = sel ? LAYOUT[sel] : null, ok = true;
    switch (a) {
      case 'l': ok = tryApply(sel, { c: p.c - 1 }); break;   case 'r': ok = tryApply(sel, { c: p.c + 1 }); break;
      case 'u': ok = tryApply(sel, { r: p.r - 1 }); break;   case 'd': ok = tryApply(sel, { r: p.r + 1 }); break;
      case 'w-': ok = tryApply(sel, { cs: p.cs - 1 }); break; case 'w+': ok = tryApply(sel, { cs: p.cs + 1 }); break;
      case 'h-': ok = tryApply(sel, { rs: p.rs - 1 }); break; case 'h+': ok = tryApply(sel, { rs: p.rs + 1 }); break;
      case 'fz': ok = tryApply(sel, { fz: +v }); break;
      case 'hide': ok = tryApply(sel, { hide: !p.hide }); if (ok) toast(p.hide ? '다시 보입니다' : '숨겼습니다 — 편집 패널의 카드 목록에서 되살릴 수 있습니다'); break;
      case 'copy': var code = encode(LAYOUT);
        (navigator.clipboard ? navigator.clipboard.writeText(code) : Promise.reject()).then(function () { toast('복사됨: ' + code, 4000); }, function () { prompt('배치 코드 (복사하세요)', code); }); break;
      case 'paste': var s = prompt('배치 코드를 붙여넣으세요'); if (s == null) break;
        var d = decode(s); if (d) { LAYOUT = d; apply(LAYOUT); save(LAYOUT); toast('적용했습니다'); } else { toast('코드가 올바르지 않습니다', 3000); } break;
      case 'undo': try { var pv = validate(JSON.parse(localStorage.getItem(KEY_PREV) || 'null')); if (pv) { LAYOUT = pv; apply(LAYOUT); save(LAYOUT); toast('직전 배치로'); } else toast('직전 배치가 없습니다'); } catch (e) {} break;
      case 'reset': if (confirm('기본 배치로 되돌릴까요?')) { LAYOUT = validate(clone(DEFAULT)); apply(LAYOUT); save(LAYOUT); toast('기본 배치'); } break;
      case 'done': setEdit(false); toast('편집 끝 · 순환 재개'); return;
    }
    if (!ok) { if (sel) flash(sel); toast('그 자리엔 못 놓습니다 (겹침·범위·최소 크기)', 2500); }
    drawBoxes(); renderHud(); renderBadge();
  }

  /* 부팅: DOM 준비 후 배지. 편집 손잡이는 켜야 생긴다. */
  function boot() { if (!gridEl()) { setTimeout(boot, 300); return; } renderBadge(); }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot); else boot();
  window.WALL_EDITOR = { open: function () { setEdit(true); }, code: function () { return encode(LAYOUT); }, layout: function () { return clone(LAYOUT); } };
})();
