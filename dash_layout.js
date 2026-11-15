/* ============================================================================
   대시보드(지도.html) 배치 편집기 — 2026-09-18 사장님 지시(상황실 편집기의 확장)
   ----------------------------------------------------------------------------
   지도 화면은 폰~벽면까지 반응형이라 상황실처럼 격자에 못 놓는다. 여기서 뜻이 있는 편집은
     · 섹션 순서 바꾸기 (리본 / 상황도 / 관서별 기상 / 예보·산불·미세먼지 / 기상영상)
     · 섹션·카드 숨기기
     · 지도 크기 (보통 / 크게 / 아주 크게)
   화면(React/dc-runtime)은 건드리지 않는다 — CSS 변수(--ds-<id>-o / -d, --ds-map)만 :root 에 쓴다.

   저장: localStorage ggDashLayout:<권역>   심기: ?dl=<코드> (저장 후 주소에서 제거) · ?dl=reset
   안전: 상황도(지도)·기상특보·재난문자·하천은 숨길 수 없다. 편집 모드는 저장하지 않으며
         3분 무조작 시 자동 종료. 되돌리기 1단계 보관. 잘못된 저장값은 무시하고 기본.
   ============================================================================ */
(function () {
  'use strict';
  var VER = 1;
  var SECTIONS = [
    { id: 'ribbon',   name: '종합 상태 띠' },
    { id: 'hero',     name: '상황도 + 특보·문자·하천', noHide: true },
    { id: 'stations', name: '관서별 현재 기상' },
    { id: 'trio',     name: '예보 · 산불 · 미세먼지' },
    { id: 'imgs',     name: '기상영상' }
  ];
  var CARDS = [
    { id: 'warn',   name: '기상특보',   noHide: true, sec: 'hero' },
    { id: 'msg',    name: '재난문자',   noHide: true, sec: 'hero' },
    { id: 'river',  name: '하천 수위',  noHide: true, sec: 'hero' },
    { id: 'hourly', name: '시간대별 예보', sec: 'trio' },
    { id: 'fire',   name: '산불 위험도',  sec: 'trio' },
    { id: 'pm',     name: '미세먼지',     sec: 'trio' }
  ];
  var MAPS = [[1, '보통'], [1.35, '크게'], [1.8, '아주 크게']];
  var DEFAULT = { order: SECTIONS.map(function (s) { return s.id; }), hide: {}, map: 1 };
  var DISP = { ribbon: 'block', hero: 'grid', stations: 'block', trio: 'grid', imgs: 'block',
               warn: 'flex', msg: 'flex', river: 'flex', hourly: 'block', fire: 'block', pm: 'flex' };

  function scopeKey() {
    var RC = window.REGION_CONF || {}, g = RC.scopes || {}, sc = null;
    try { sc = new URLSearchParams(location.search).get('scope'); } catch (e) {}
    if (sc && !g[sc] && g['경기' + sc]) sc = '경기' + sc;
    if (!sc) { try { var v = localStorage.getItem('ggScope'); if (v === '전체') return '전체'; if (v && g[v]) sc = v; } catch (e) {} }
    if (!sc) { try { sc = (RC.hostScope || {})[location.hostname.split('.')[0]] || null; } catch (e) {} }
    return (sc && g[sc]) ? sc : '전체';
  }
  var SCOPE = scopeKey(), KEY = 'ggDashLayout:' + SCOPE, KEY_PREV = KEY + ':prev';
  var ALL = SECTIONS.concat(CARDS), BY = {}; ALL.forEach(function (x) { BY[x.id] = x; });

  function clone(L) { return JSON.parse(JSON.stringify(L)); }
  function validate(L) {
    if (!L || typeof L !== 'object' || !Array.isArray(L.order)) return null;
    var ids = SECTIONS.map(function (s) { return s.id; });
    var order = L.order.filter(function (x) { return ids.indexOf(x) >= 0; });
    ids.forEach(function (x) { if (order.indexOf(x) < 0) order.push(x); });      // 빠진 섹션은 뒤에
    if (new Set(order).size !== ids.length) return null;
    var hide = {};
    ALL.forEach(function (x) { if (L.hide && L.hide[x.id] && !x.noHide) hide[x.id] = true; });
    var map = MAPS.map(function (m) { return m[0]; }).indexOf(+L.map) >= 0 ? +L.map : 1;
    return { order: order, hide: hide, map: map };
  }
  function isDefault(L) { return L.order.join() === DEFAULT.order.join() && !Object.keys(L.hide).length && L.map === 1; }

  /* 짧은 코드: D1<권역>.<섹션 순서 첫글자 5자>.<숨김 id 첫글자들>.<지도단계>  예) D1북.rhsti..1 */
  var INITIAL = { ribbon: 'r', hero: 'h', stations: 's', trio: 't', imgs: 'i', warn: 'w', msg: 'm', river: 'v', hourly: 'y', fire: 'f', pm: 'p' };
  var BY_INI = {}; Object.keys(INITIAL).forEach(function (k) { BY_INI[INITIAL[k]] = k; });
  function encode(L) {
    return 'D' + VER + SCOPE.replace('경기', '').charAt(0) + '.' + L.order.map(function (x) { return INITIAL[x]; }).join('')
      + '.' + Object.keys(L.hide).map(function (x) { return INITIAL[x]; }).join('') + '.' + (MAPS.map(function (m) { return m[0]; }).indexOf(L.map) + 1);
  }
  function decode(code) {
    try {
      var m = String(code || '').trim().match(/^D(\d)[전북남]?\.([a-z]+)\.([a-z]*)\.(\d)$/); if (!m || +m[1] !== VER) return null;
      var order = m[2].split('').map(function (c) { return BY_INI[c]; }), hide = {};
      m[3].split('').forEach(function (c) { if (BY_INI[c]) hide[BY_INI[c]] = true; });
      var map = (MAPS[+m[4] - 1] || MAPS[0])[0];
      return validate({ order: order, hide: hide, map: map });
    } catch (e) { return null; }
  }

  function stripParam() { try { var u = new URL(location.href); u.searchParams.delete('dl'); history.replaceState(null, '', u); } catch (e) {} }
  function save(L) { try { var c = localStorage.getItem(KEY); if (c) localStorage.setItem(KEY_PREV, c); localStorage.setItem(KEY, JSON.stringify(L)); return true; }
    catch (e) { console.warn('[dash] 저장 실패 — 이 PC는 배치를 기억하지 못합니다. 주소에 ?dl= 코드를 넣으세요.'); return false; } }
  function load() {
    try { var u = new URLSearchParams(location.search).get('dl');
      if (u === 'reset') { localStorage.removeItem(KEY); localStorage.removeItem(KEY_PREV); stripParam(); }
      else if (u) { var d = decode(u); if (d) { save(d); stripParam(); return d; } console.warn('[dash] dl 코드가 잘못됨 — 무시'); }
    } catch (e) {}
    try { var v = validate(JSON.parse(localStorage.getItem(KEY) || 'null')); if (v) return v; } catch (e) {}
    return validate(clone(DEFAULT));
  }

  var LAYOUT = load();
  function apply(L) {
    var st = document.documentElement.style;
    L.order.forEach(function (id, i) { st.setProperty('--ds-' + id + '-o', i + 1); });
    ALL.forEach(function (x) { st.setProperty('--ds-' + x.id + '-d', L.hide[x.id] ? 'none' : DISP[x.id]); });
    st.setProperty('--ds-map', L.map);
    /* 지도 열 비율: 1.6fr × 배율. calc() 는 fr 을 못 받아 열 정의 전체를 문자열로 준다 */
    st.setProperty('--ds-hero-cols', 'minmax(0,' + (1.6 * L.map).toFixed(2) + 'fr) minmax(330px,1fr)');
    window.DASH_LAYOUT = L;
  }
  apply(LAYOUT);

  /* ═══════════ 편집 UI ═══════════ */
  var EDIT = false, idleT = null, IDLE_MS = 180000, hud = null, badge = null, tags = [];
  function $(tag, css, html) { var e = document.createElement(tag); if (css) e.style.cssText = css; if (html != null) e.innerHTML = html; return e; }
  function toast(msg, ms) { var t = $('div', 'position:fixed;left:50%;bottom:24px;transform:translateX(-50%);z-index:9500;background:#0f1b2d;color:#fff;border-radius:12px;padding:11px 18px;font:600 14px/1.4 system-ui,sans-serif;box-shadow:0 8px 30px rgba(0,0,0,.35);', msg);
    document.body.appendChild(t); setTimeout(function () { t.remove(); }, ms || 2200); }
  function touch() { clearTimeout(idleT); if (EDIT) idleT = setTimeout(function () { setEdit(false); toast('3분 동안 조작이 없어 편집을 끝냈습니다'); }, IDLE_MS); }

  function renderBadge() {
    if (!badge) { badge = $('div', 'position:fixed;left:12px;bottom:14px;z-index:9400;display:flex;gap:6px;'); document.body.appendChild(badge); }
    badge.innerHTML = '';
    var b1 = $('button', 'cursor:pointer;opacity:.45;padding:7px 12px;border-radius:10px;border:1px solid var(--border,#d3dbe9);background:var(--surface,#fff);color:var(--ink,#0f1b2d);font:700 12px system-ui,sans-serif;box-shadow:var(--sh1,0 1px 3px rgba(0,0,0,.1));', '✎ 배치 편집');
    b1.onmouseenter = function () { b1.style.opacity = 1; }; b1.onmouseleave = function () { b1.style.opacity = .45; };
    b1.onclick = function () { setEdit(!EDIT); };
    badge.appendChild(b1);
    if (!isDefault(LAYOUT)) {
      var b2 = $('button', 'cursor:pointer;opacity:.75;padding:7px 12px;border-radius:10px;border:1px solid #e0930a;background:var(--surface,#fff);color:#e0930a;font:700 12px system-ui,sans-serif;', '사용자 배치 · 되돌리기');
      b2.onclick = function () { if (confirm('기본 배치로 되돌릴까요? (직전 배치는 1단계 보관됩니다)')) { LAYOUT = validate(clone(DEFAULT)); apply(LAYOUT); save(LAYOUT); refresh(); toast('기본 배치로 되돌렸습니다'); } };
      badge.appendChild(b2);
    }
  }
  function setEdit(on) {
    EDIT = on; touch();
    if (!hud) { hud = $('div', 'position:fixed;left:50%;top:12px;transform:translateX(-50%);z-index:9450;display:none;max-width:min(96vw,980px);background:var(--surface,#fff);border:2px solid #e0930a;border-radius:14px;padding:12px 14px;color:var(--ink,#0f1b2d);font:600 13px/1.35 system-ui,sans-serif;box-shadow:0 12px 40px rgba(0,0,0,.28);user-select:none;'); document.body.appendChild(hud); }
    hud.style.display = on ? 'block' : 'none';
    if (on) toast('편집 모드 · 3분 무조작 시 자동 종료');
    refresh();
  }
  function refresh() { renderBadge(); drawTags(); if (EDIT) renderHud(); }

  /* 편집 중 각 섹션·카드 위에 이름표 */
  function drawTags() {
    tags.forEach(function (t) { t.remove(); }); tags = [];
    if (!EDIT) return;
    ALL.forEach(function (x) {
      var el = document.querySelector('[data-dash="' + x.id + '"]'); if (!el) return;
      var hidden = !!LAYOUT.hide[x.id];
      var isSec = !!SECTIONS.filter(function (s) { return s.id === x.id; }).length;
      el.style.outline = hidden ? '2px dotted #8593aa' : (isSec ? '2px dashed #e0930a' : '2px dashed #2563eb');
      el.style.outlineOffset = isSec ? '-4px' : '-2px';
      if (hidden) el.style.setProperty('display', DISP[x.id], 'important'), el.style.opacity = '.35';
      var lab = $('div', 'position:absolute;z-index:9300;background:' + (isSec ? '#e0930a' : '#2563eb') + ';color:#fff;border-radius:7px;padding:2px 8px;font:700 11px system-ui,sans-serif;pointer-events:none;white-space:nowrap;', (isSec ? '섹션 · ' : '') + x.name + (hidden ? ' (숨김)' : ''));
      document.body.appendChild(lab); tags.push(lab);
      var r = el.getBoundingClientRect(); lab.style.left = (r.left + window.scrollX + 8) + 'px'; lab.style.top = (r.top + window.scrollY + 6) + 'px';
    });
  }
  function clearMarks() { ALL.forEach(function (x) { var el = document.querySelector('[data-dash="' + x.id + '"]'); if (!el) return; el.style.outline = ''; el.style.outlineOffset = ''; el.style.opacity = ''; el.style.removeProperty('display'); }); }

  function renderHud() {
    var B = function (a, v, t, on) { return '<button data-a="' + a + '" data-v="' + (v || '') + '" style="cursor:pointer;border:1px solid var(--border,#d3dbe9);border-radius:8px;padding:5px 9px;font:700 12px system-ui;background:' + (on ? '#e0930a' : 'var(--surface2,#f3f7fc)') + ';color:' + (on ? '#fff' : 'var(--ink,#0f1b2d)') + ';">' + t + '</button>'; };
    var h = '<div style="display:flex;flex-direction:column;gap:9px;">';
    h += '<div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;"><span style="color:#e0930a;">✎ 배치 편집</span><span style="color:var(--ink3,#8593aa);font-weight:500;">섹션 순서는 ▲▼, 카드는 👁로 숨김 · 3분 무조작 시 자동 종료</span></div>';
    h += '<div style="display:flex;flex-direction:column;gap:4px;">';
    LAYOUT.order.forEach(function (id, i) {
      var s = BY[id], hid = !!LAYOUT.hide[id];
      h += '<div style="display:flex;align-items:center;gap:6px;padding:4px 6px;border-radius:8px;background:var(--surface2,#f3f7fc);' + (hid ? 'opacity:.55;' : '') + '">';
      h += B('up', id, '▲', false) + B('down', id, '▼', false);
      h += '<span style="min-width:170px;">' + s.name + (hid ? ' <span style="color:#8593aa">(숨김)</span>' : '') + '</span>';
      h += s.noHide ? '<span style="color:#8593aa;font-size:11px;">숨길 수 없음</span>' : B('hide', id, hid ? '👁 보이기' : '👁 숨기기', false);
      var cards = CARDS.filter(function (c) { return c.sec === id; });
      if (cards.length) { h += '<span style="border-left:1px solid var(--border,#d3dbe9);height:18px;margin:0 4px;"></span>';
        cards.forEach(function (c) { var ch = !!LAYOUT.hide[c.id];
          h += c.noHide ? '<span style="font-size:11px;color:#8593aa;padding:0 4px;">' + c.name + '</span>' : B('hide', c.id, (ch ? '☐ ' : '☑ ') + c.name, false); }); }
      h += '</div>';
    });
    h += '</div>';
    h += '<div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap;"><span style="color:var(--ink3,#8593aa);">지도 크기</span>';
    MAPS.forEach(function (m) { h += B('map', m[0], m[1], LAYOUT.map === m[0]); });
    h += '<span style="border-left:1px solid var(--border,#d3dbe9);height:18px;margin:0 6px;"></span>';
    h += B('copy', '', '배치 코드 복사') + B('paste', '', '코드 붙여넣기') + B('undo', '', '직전으로') + B('reset', '', '기본 배치');
    h += '<button data-a="done" style="cursor:pointer;border:0;border-radius:8px;padding:6px 14px;font:800 12px system-ui;background:#e0930a;color:#fff;margin-left:auto;">완료</button></div></div>';
    hud.innerHTML = h;
    hud.querySelectorAll('button[data-a]').forEach(function (b) { b.onclick = function () { act(b.dataset.a, b.dataset.v); }; });
  }
  function act(a, v) {
    touch(); var L = clone(LAYOUT), i;
    switch (a) {
      case 'up':   i = L.order.indexOf(v); if (i > 0) { L.order.splice(i, 1); L.order.splice(i - 1, 0, v); } break;
      case 'down': i = L.order.indexOf(v); if (i < L.order.length - 1) { L.order.splice(i, 1); L.order.splice(i + 1, 0, v); } break;
      case 'hide': if (L.hide[v]) delete L.hide[v]; else L.hide[v] = true; break;
      case 'map':  L.map = +v; break;
      case 'copy': var code = encode(LAYOUT);
        (navigator.clipboard ? navigator.clipboard.writeText(code) : Promise.reject()).then(function () { toast('복사됨: ' + code, 4000); }, function () { prompt('배치 코드 (복사하세요)', code); }); return;
      case 'paste': var s = prompt('배치 코드를 붙여넣으세요'); if (s == null) return; var d = decode(s);
        if (!d) { toast('코드가 올바르지 않습니다', 3000); return; } L = d; toast('적용했습니다'); break;
      case 'undo': try { var pv = validate(JSON.parse(localStorage.getItem(KEY_PREV) || 'null')); if (!pv) { toast('직전 배치가 없습니다'); return; } L = pv; toast('직전 배치로'); } catch (e) { return; } break;
      case 'reset': if (!confirm('기본 배치로 되돌릴까요?')) return; L = clone(DEFAULT); toast('기본 배치'); break;
      case 'done': setEdit(false); clearMarks(); toast('편집 끝'); return;
    }
    var vv = validate(L); if (!vv) { toast('적용할 수 없는 배치입니다'); return; }
    clearMarks(); LAYOUT = vv; apply(LAYOUT); save(LAYOUT); refresh();
  }
  window.addEventListener('resize', function () { if (EDIT) drawTags(); });
  window.addEventListener('scroll', function () { if (EDIT) drawTags(); }, { passive: true });

  function boot() { if (!document.querySelector('[data-dash-main]')) { setTimeout(boot, 300); return; } renderBadge(); }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot); else boot();
  window.DASH_EDITOR = { open: function () { setEdit(true); }, code: function () { return encode(LAYOUT); }, layout: function () { return clone(LAYOUT); } };
})();
