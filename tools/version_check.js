/* 새 판 알림 — 화면 코드가 새로 배포되면 알려 주고(버튼), 상황실 벽면은 스스로 다시 불러온다.
   (2026-09-20 사장님 "수정되면 다시 로드하라고 메시지 안 떠? 상황실에 상시 띄워놓는다면 필요할 거 같은데")

   · 빌드(tools/build_weather_dev.py)가 페이지마다 window.BUILD_ID 를 박고, 사이트 루트에 /version.json 을 같이 올린다.
   · 60초마다 /version.json 을 받아(캐시 없음) 내 BUILD_ID 와 다르면 위쪽에 띠를 띄운다: "화면이 새 판으로 바뀌었습니다 · 다시 불러오기".
   · 상황실(벽면)은 사람이 앞에 없으니 60초 뒤 스스로 다시 불러온다 — 단 배치 편집 중(window.WALL_EDITING)이면 기다린다.
   · 데이터 갱신(60초 폴링 '새 데이터')과는 별개 — 이건 '코드'가 바뀐 경우다.
   · 받기 실패(오프라인·오류)는 조용히 넘긴다. 다음 60초에 다시. */
(function () {
  var MINE = window.BUILD_ID;
  if (!MINE) return;
  var WALL = false; try { WALL = /상황실/.test(decodeURIComponent(location.pathname)); } catch (e) {}
  var shown = false, timer = null, left = 60;

  function reload() { try { location.reload(); } catch (e) { location.href = location.href; } }
  function bar(text, sub) {
    var b = document.getElementById('gg-newver');
    if (!b) {
      b = document.createElement('div'); b.id = 'gg-newver';
      b.style.cssText = 'position:fixed;left:50%;top:10px;transform:translateX(-50%);z-index:2147483000;display:flex;flex-wrap:wrap;justify-content:center;align-items:center;gap:8px 12px;text-align:center;' +
        'padding:10px 16px;border-radius:12px;background:#ffb020;color:#101725;font:700 14px/1.2 system-ui,-apple-system,sans-serif;' +
        'box-shadow:0 10px 30px rgba(0,0,0,.35);max-width:92vw;';
      var t = document.createElement('span'); t.id = 'gg-newver-t'; b.appendChild(t);
      var s = document.createElement('span'); s.id = 'gg-newver-s'; s.style.cssText = 'font-weight:600;font-size:12px;opacity:.8;'; b.appendChild(s);
      var btn = document.createElement('button'); btn.textContent = '다시 불러오기';
      btn.style.cssText = 'cursor:pointer;border:0;border-radius:8px;padding:7px 12px;background:#101725;color:#ffb020;font:700 13px system-ui,sans-serif;white-space:nowrap;';
      btn.onclick = reload; b.appendChild(btn);
      var x = document.createElement('a'); x.textContent = '나중에'; x.style.cssText = 'cursor:pointer;font-size:12px;opacity:.75;text-decoration:underline;';
      x.onclick = function () { b.remove(); clearInterval(timer); timer = null; shown = false; snooze = Date.now() + 30 * 60000; };
      b.appendChild(x);
      (document.body || document.documentElement).appendChild(b);
    }
    document.getElementById('gg-newver-t').textContent = text;
    document.getElementById('gg-newver-s').textContent = sub || '';
  }
  var snooze = 0;
  function onNew(remote) {
    if (shown || Date.now() < snooze) return;
    shown = true;
    if (!WALL) { bar('화면이 새 판으로 바뀌었습니다', '(' + remote + ')'); return; }
    /* 벽면: 60초 세고 스스로. 편집 중이면 끝날 때까지 보류 */
    left = 60;
    bar('화면이 새 판으로 바뀌었습니다', left + '초 뒤 자동으로 다시 불러옵니다');
    timer = setInterval(function () {
      if (window.WALL_EDITING) { bar('화면이 새 판으로 바뀌었습니다', '배치 편집이 끝나면 다시 불러옵니다'); return; }
      left -= 1;
      if (left <= 0) { clearInterval(timer); reload(); return; }
      bar('화면이 새 판으로 바뀌었습니다', left + '초 뒤 자동으로 다시 불러옵니다');
    }, 1000);
  }
  function check() {
    try {
      fetch('/version.json?_t=' + Date.now(), { cache: 'no-store' })
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (j) { if (j && j.build && j.build !== MINE) onNew(j.at || j.build); })
        .catch(function () {});
    } catch (e) {}
  }
  setTimeout(check, 15000);            /* 첫 확인은 뜬 지 15초 뒤(막 배포된 직후 열었을 때 바로 띄우지 않게) */
  setInterval(check, 60000);
})();
