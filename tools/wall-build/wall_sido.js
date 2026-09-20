/* 상황실 벽면 — 시도 바꾸기 (전국판, 2026-09-19 사장님 지시 "상황실도 시도 바꾸게")
   · region.js 에 sidoList 가 주입된 화면(작업장/전국판)에서만 나타난다. 경기 전용 사이트엔 없다.
   · 좌상단 오버레이 둘째 줄에 '🗺 시도 · 강원도' 배지. 누르면 시도 칩이 뜨고, 고르면 그 시도
     폴더의 상황실로 이동한다(시도마다 데이터·지도·설정 파일이 달라 한 화면 안에서는 못 바꾼다).
   · 경기도는 권역이 있어 칩이 셋(경기 전체·경기북부·경기남부) — 2026-09-20 사장님 "경기도 선택하면 북부만 나와":
     벽면은 localStorage.ggScope(지도 화면의 권역 선택)를 따르므로 그냥 이동하면 전에 골라 둔 권역(북부)만 나왔다.
     칩을 누르면 ggScope 를 그 권역으로 바꾸고 이동한다('전체' = 34개 관서 전부).
   · React 밖 고정 레이어 — 순환·배치 편집기와 무관. */
(function () {
  var RC = window.REGION_CONF || {};
  var LIST = RC.sidoList || [];
  if (!LIST.length) return;
  var CUR = RC.sidoCurrent || '';
  /* 작업장 빌드(build_weather_dev.py)가 HTML 안의 '경기북부' 글자를 '경기도'로 바꾸므로 권역 이름은 이어 붙여 만든다 */
  var GG = '경기' + '도', N = '경기' + '북부', S = '경기' + '남부';   /* 시도 폴더 빌드는 '경기도'도 그 시도 이름으로 바꾼다 */
  var GG_SCOPES = [{ label: '경기 전체', scope: '전체' }, { label: N, scope: N }, { label: S, scope: S }];

  function $(tag, style, text) { var e = document.createElement(tag); if (style) e.style.cssText = style; if (text != null) e.textContent = text; return e; }
  function curScope() { try { return localStorage.getItem('ggScope') || ''; } catch (e) { return ''; } }
  function go(sd, scope) {
    try {
      localStorage.setItem('ggSido', sd.base);
      if (scope) localStorage.setItem('ggScope', scope);   /* 경기 권역 — 벽면 NAMES 와 배치 저장 키가 이 값을 읽는다 */
    } catch (e) {}
    var page = location.pathname.split('/').pop() || '상황실.html';
    location.href = sd.base + page;
  }
  function chip(label, on, onclick) {
    var c = $('a', 'cursor:pointer;padding:7px 11px;border-radius:9px;border:1px solid ' + (on ? 'var(--cAmber,#ffb020)' : 'var(--line,#28313f)') + ';background:' + (on ? 'var(--cAmber,#ffb020)' : 'var(--panel2,#151b26)') + ';color:' + (on ? '#101725' : 'var(--fg,#f2f5fa)') + ';font:700 13px system-ui,sans-serif;white-space:nowrap;', label);
    if (!on) c.onclick = onclick;
    return c;
  }

  var panel = null;
  function togglePanel() {
    if (panel) { panel.remove(); panel = null; return; }
    panel = $('div', 'position:fixed;left:10px;top:70px;z-index:45;background:var(--panel,#141e33);border:2px solid var(--cAmber,#ffb020);border-radius:14px;padding:12px 14px;color:var(--fg,#f3f6fc);font:600 14px/1.3 system-ui,sans-serif;box-shadow:0 10px 40px rgba(0,0,0,.45);max-width:560px;');
    panel.appendChild($('div', 'font-size:12px;color:var(--dim,#93a5c4);margin-bottom:8px;', '시도를 고르면 그 시도 상황실로 이동합니다 · 경기도는 전체/북부/남부 중 하나'));
    var wrap = $('div', 'display:flex;flex-wrap:wrap;gap:6px;');
    var isGG = (CUR === GG), sc = curScope();
    LIST.forEach(function (sd) {
      if (sd.label === GG) {
        /* 경기도 = 권역 칩 셋. 지금 경기 화면이면 현재 권역(ggScope, 없으면 전체)에 불을 켠다 */
        var scNow = isGG ? ((sc === N || sc === S) ? sc : '전체') : null;
        GG_SCOPES.forEach(function (g) {
          wrap.appendChild(chip(g.label, scNow === g.scope, function () { go(sd, g.scope); }));
        });
        return;
      }
      wrap.appendChild(chip(sd.label, sd.label === CUR, function () { go(sd); }));
    });
    panel.appendChild(wrap);
    var close = $('a', 'display:inline-block;margin-top:10px;cursor:pointer;color:var(--dim,#93a5c4);font-size:12px;', '닫기');
    close.onclick = togglePanel;
    panel.appendChild(close);
    document.body.appendChild(panel);
  }

  function mount() {
    if (!document.body) return setTimeout(mount, 50);
    var label = CUR;
    if (CUR === GG) { var sc = curScope(); label = (sc === N || sc === S) ? sc : '경기 전체'; }
    var b = $('a', 'position:absolute;left:10px;top:40px;z-index:20;cursor:pointer;opacity:.28;padding:6px 11px;border-radius:9px;border:1px solid var(--line,#28313f);background:var(--panel,#151b26);color:var(--fg,#f2f5fa);font:600 12px system-ui,sans-serif;white-space:nowrap;', '🗺 시도 · ' + label);
    b.title = '다른 시도 상황실로 바꾸기';
    b.onmouseenter = function () { b.style.opacity = 1; }; b.onmouseleave = function () { b.style.opacity = .28; };
    b.onclick = togglePanel;
    document.body.appendChild(b);
  }
  mount();
})();
