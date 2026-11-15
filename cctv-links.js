/* 외부 하천 CCTV — 홍수통제소(n.flood.go.kr, 하천 상세에 이미 삽입) 밖에서 일반에 공개된 실시간 영상.
   2026-09-21 16개 시도 조사(지자체·홍수통제소·KBS 재난포털·유튜브 라이브). 운영 주체가 바뀌거나 주소가 죽으면 여기만 고친다.
   · 시도 키(region.js 의 key) → 관서 이름 → 항목 목록. '*' 는 그 시도 모든 관서에. 경기(all·north·south)는 같은 표.
   · 항목 종류(화면이 이 순서로 판정):
       {n, kbs:id}          KBS 재난감시 CCTV — 서버가 올리는 data-cctv.js(하루 토큰)에서 재생 주소를 찾아 화면 안 hls 재생
       {n, hls:m3u8, thumb} 직접 HLS(CORS 허용 확인된 곳: 포항시 방재 CCTV) — 화면 안 재생
       {n, frame:url}       뷰어 페이지 iframe(https·X-Frame-Options 없음 확인: 춘천시 하천 CCTV)
       {n, hrfco:obscd}     홍수통제소 수위관측소 CCTV — 장치번호표(cctv-hrfco.js)로 켜고(getCctvScreen.do no-cors POST) 직접 HLS 재생
       {n, u}               새 창 링크(제주시·서귀포·부산 안전ON·용인 등 — 세션/CSRF·http 전용·SPA 라 삽입 불가)
   · 예의: 지자체 뷰어는 30초 뒤 스스로 멈추게 만들어 두었으므로 우리도 직접 재생은 90초 뒤 멈추고 '계속 보기'를 띄운다.
   · 조사 기록: workflows/운영현황.md '하천 CCTV 출처 조사'. */
(function () {
  var KBS = function (id, name) { return { n: 'KBS ' + name, u: 'https://d.kbs.co.kr/special/cctvShare?cctvId=' + id, kbs: id }; };
  var PH = function (cam, name) { return { n: '포항시 ' + name, u: 'https://rain.pohang.go.kr/Front/Camera',
    hls: 'https://safecctv.pohang.go.kr/media/api/v1/hls/vurix/192499/' + cam + '/0/0',
    thumb: 'https://safecctv.pohang.go.kr/media/api/v1/snapshot/vurix/192499/' + cam + '/0/0' }; };
  var CC = function (code, name) { return { n: '춘천시 ' + name, u: 'https://www.chuncheon.go.kr/disaster-safety/rainfall-info/cctv/',
    frame: 'https://rivercctv.chuncheon.go.kr/' + code + '.html' }; };
  var GG = {
    '가평': [KBS('9972', '가평2교 (북한강)')],
    '구리': [KBS('9974', '수택동 (왕숙천)')],
    '용인': [{ n: '용인시 재난CCTV — 하천 60대', u: 'http://safe.yongin.go.kr/m/cctv.html?cd=1&ct=3&ns=' }],
  };
  var CHEONGJU = [KBS('9968', '사직동 (무심천)')];
  /* 포항 방재 CCTV 25대 중 하천·배수 관련(2026-09-21 rain.pohang.go.kr 목록). 남구/북구는 설치 주소로 */
  var POHANG_S = [PH('100028', '냉천교 (냉천)'), PH('100031', '문덕교 (냉천)'), PH('100046', '원용교 (냉천)'), PH('100026', '연일대교'),
    PH('100037', '형산강 하구 (송도)'), PH('100068', '신형산교 상류'), PH('100088', '항만교 (청림동)'), PH('100079', '자명천 (연일읍)'),
    PH('100064', '송동1교 (대송면)'), PH('100027', '대송배수펌프장'), PH('100057', '장기2교'), PH('100075', '상전천 (구룡포)'),
    PH('100054', '오어지'), PH('100034', '오천 양북'), { n: '포항시 방재기상정보 CCTV 전체(25대)', u: 'https://rain.pohang.go.kr/Front/Camera' }];
  var POHANG_N = [PH('100024', '곡강교 (곡강천)'), PH('100060', '송내교 (죽장면)'), PH('100020', '세월교 (하옥)'),
    { n: '포항시 방재기상정보 CCTV 전체(25대)', u: 'https://rain.pohang.go.kr/Front/Camera' }];
  /* 춘천 하천감시 CCTV 16대 — 뷰어 페이지(rivercctv.chuncheon.go.kr/CTV…html)는 iframe 가능(2026-09-21 확인) */
  var CHUNCHEON = [CC('CTV0000002', '태백교'), CC('CTV0000003', '팔미천'), CC('CTV0000004', '오탄리'), CC('CTV0000005', '윗샘밭교'),
    CC('CTV0000006', '강촌교'), CC('CTV0000007', '효자교'), CC('CTV0000008', '한계천'), CC('CTV0000009', '공지천교'), CC('CTV0000010', '한덕교'),
    CC('CTV0000011', '납실교'), CC('CTV0000012', '신연교'), CC('CTV0000013', '퇴계교'), CC('CTV0000014', '소양1교'), CC('CTV0000015', '하일교'),
    CC('CTV0000016', '장학교'), CC('CTV0000017', '만천천')];
  window.CCTV_LINKS = {
    all: GG, north: GG, south: GG,
    seoul: {
      '노원구': [KBS('9966', '월계동 (중랑천)'), { n: '노원구 하천 유튜브 라이브 (중랑천·우이천·당현천)', u: 'https://www.youtube.com/@healinglivenowon7260' }],
      '마포구': [KBS('9965', '성산교 (홍제천)')],
      '서초구': [KBS('9973', '양재동 (양재천)'), KBS('9998', '반포한강공원')],
      '용산구': [KBS('9959', '한남동 (한강)')],
      '관악구': [{ n: '관악구 도림천(별빛내린천) 유튜브 라이브', u: 'https://www.youtube.com/@WelcomeToGwanak' }],
    },
    gangwon: { '춘천': CHUNCHEON },
    busan: { '*': [{ n: '부산 안전ON 재난 CCTV (도시침수 통합플랫폼)', u: 'https://safecity.busan.go.kr/' }], '동래구': [KBS('9967', '세병교 (온천천)')] },
    daegu: { '동구': [KBS('9969', '신천동 (신천)')] },
    daejeon: { '*': [{ n: '금강홍수통제소 하천수위 영상 (대전 12지점)', u: 'https://www.geumriver.go.kr/html/sumun/river_movie_all.jsp' }], '유성구': [KBS('9970', '구성동 (갑천)')] },
    sejong: { '세종': [{ n: '세종엔 재난 CCTV', u: 'https://smart.sejong.go.kr/m/calamitycctvs' }, { n: '금강홍수통제소 하천수위 영상', u: 'https://www.geumriver.go.kr/html/sumun/river_movie_all.jsp' }] },
    chungbuk: { '청주동부': CHEONGJU, '청주서부': CHEONGJU, '단양': [KBS('9975', '도담삼봉 (남한강)')] },
    chungnam: { '공주': [KBS('9976', '금강교 (금강)')], '*': [{ n: '금강홍수통제소 하천수위 영상', u: 'https://www.geumriver.go.kr/html/sumun/river_movie_all.jsp' }] },
    jeonbuk: { '*': [{ n: '영산강홍수통제소 주요지점 수위 영상 (만경강·동진강·섬진강)', u: 'https://www.yeongsanriver.go.kr/sumun/video.do?S=S01&M=0202000000' }] },
    jngj: { '나주': [KBS('9978', '나주대교 (영산강)')], '*': [{ n: '영산강홍수통제소 주요지점 수위 영상', u: 'https://www.yeongsanriver.go.kr/sumun/video.do?S=S01&M=0202000000' }] },
    gyeongbuk: { '포항남부': POHANG_S, '포항북부': POHANG_N },
    gyeongnam: { '밀양': [KBS('9977', '삼랑진 (낙동강)')] },
    jeju: {
      '제주': [{ n: '제주시 하천감시 CCTV 62대', u: 'https://www.jejusi.go.kr/bangjae/realcctvHls/riverHlsCctv.do' }],
      '서귀포': [{ n: '서귀포시 실시간 하천 CCTV 27대', u: 'https://www.seogwipo.go.kr/field/safety/live/hls.htm' }],
    },
  };

  /* 부산 안전ON 재난 CCTV(하천·수문·배수, cctv-busan.js — tools/build_busan_cctv.py) — 직접 HLS(CORS *, 2026-09-22 실측) */
  if (window.BUSAN_CCTV) {
    var B = window.CCTV_LINKS.busan;
    Object.keys(window.BUSAN_CCTV).forEach(function (unit) {
      var items = window.BUSAN_CCTV[unit].map(function (c) { return { n: '부산 안전ON ' + c.n, u: 'https://safecity.busan.go.kr/',
        hls: 'https://safecity.busan.go.kr:30443/play/hls/' + c.cd + '/index.m3u8' }; });
      B[unit] = items.concat(B[unit] || []);
    });
  }

  /* ── 항목 판정 ── */
  window.cctvKey = function (x) { return x.kbs ? 'kbs:' + x.kbs : x.hls ? 'hls:' + x.hls : x.frame ? 'frame:' + x.frame : null; };
  /* KBS 카메라의 재생 요청·정지영상 주소 — 서버가 올리는 data-cctv.js(window.KBS_CCTV, 하루 토큰) 에서 */
  window.kbsCam = function (id) {
    var L = (window.KBS_CCTV && window.KBS_CCTV.cams) || [];
    for (var i = 0; i < L.length; i++) if (String(L[i].id) === String(id)) return L[i];
    return null;
  };
  /* 홍수통제소 관측소의 장치번호 — 서버가 매일 올리는 표(data-cctv.js window.HRFCO_CCTV_LIVE, 새 카메라 자동 반영) 먼저,
     없으면 화면에 박아 둔 표(cctv-hrfco.js) */
  window.hrfcoCam = function (obscd) {
    var L = (window.HRFCO_CCTV_LIVE && window.HRFCO_CCTV_LIVE.table) || {}, T = window.HRFCO_CCTV || {}, k = String(obscd);
    var e = L[k] || T[k]; return (e && (e.ld || e.hd)) ? e : null;
  };
  /* ★ KBS 중계서버가 2026-10-08 부터 핫링크를 막았다 — 스트림(kbscctv-cache.loomex.net)이 Referer 가
     'https://d.kbs.co.kr/' 일 때만 200 이고 우리 출처로는 403. 브라우저는 Referer 를 못 바꾸므로
     화면 안 재생이 불가능하다(정지영상 cctvImg 는 그대로 열린다). → KBS 는 새 창(KBS 포털) 링크로만.
     되살아났는지 가끔 확인: 아래 값을 false 로 두고 재생되면 KBS 가 다시 푼 것. */
  window.KBS_STREAM_BLOCKED = true;
  /* 화면 안에서 틀 수 있나(홍수통제소는 장치번호표가 있을 때만) */
  window.cctvInline = function (x) { return !!(x.hls || x.frame || (x.kbs && !window.KBS_STREAM_BLOCKED && window.kbsCam(x.kbs)) || (x.hrfco && window.hrfcoCam(x.hrfco))); };
  window.cctvPoster = function (x) { if (x.thumb) return x.thumb + (x.thumb.indexOf('?') < 0 ? '?' : '&') + '_t=' + Math.floor(Date.now() / 30000); var c = x.kbs ? window.kbsCam(x.kbs) : null; return c ? c.img : ''; };

  /* ── HLS 재생(hls.js 는 처음 필요할 때 한 번만 내려받음, 사파리는 기본 재생) ── */
  function startHls(video, m3u8, onError) {
    /* MSE 가 있으면 hls.js 로(일부 크로미움이 자체 HLS 를 '될지도'라 하지만 실황에서 멈추는 일이 있어 — 2026-09-22 실측),
       없으면(iOS 사파리) 브라우저 자체 HLS 로 */
    var mse = !!(window.MediaSource || window.WebKitMediaSource);
    if (!mse && video.canPlayType('application/vnd.apple.mpegurl')) {
      /* 브라우저 자체 HLS: 실황 목록은 처음 play() 때 아직 준비가 안 돼 거부되기도 한다 → 준비되면 다시 */
      var tryPlay = function () { video.play().catch(function () {}); };
      video.addEventListener('canplay', tryPlay, { once: true }); video.addEventListener('loadedmetadata', tryPlay, { once: true });
      video.src = m3u8; video.load(); tryPlay(); return;
    }
    var go = function () {
      if (!window.Hls || !window.Hls.isSupported()) { if (onError) onError('hls'); return; }
      if (video._hls) { try { video._hls.destroy(); } catch (e) {} }
      var h = new window.Hls({ enableWorker: true, lowLatencyMode: false }); video._hls = h;
      h.on(window.Hls.Events.ERROR, function (ev, d) { if (d && d.fatal && onError) onError(d.type); });
      h.loadSource(m3u8); h.attachMedia(video);
      h.on(window.Hls.Events.MANIFEST_PARSED, function () { video.play().catch(function () {}); });
    };
    if (window.Hls) return go();
    var s = document.createElement('script'); s.src = 'https://cdn.jsdelivr.net/npm/hls.js@1.5.15/dist/hls.min.js'; s.onload = go;
    s.onerror = function () { if (onError) onError('load'); }; document.head.appendChild(s);
  }
  /* video 요소에 항목을 튼다. KBS 는 요청 주소를 먼저 GET 하면 본문에 서명된 m3u8 주소가 온다(CORS 허용, 2026-09-21 실측).
     90초 뒤 스스로 멈추고 onStop 을 부른다(지자체 서버 예의; 화면이 '계속 보기' 버튼을 띄운다). */
  /* 탭이 가려지면 크로미움이 무음 영상을 멈춘다 → 다시 보이면 살아 있는 재생기만 이어 튼다 */
  if (!window._cctvVisHook) { window._cctvVisHook = true; document.addEventListener('visibilitychange', function () {
    if (document.hidden) return; document.querySelectorAll('video').forEach(function (v) { if (v._live && v.paused) v.play().catch(function () {}); }); }); }
  window.cctvPlay = function (video, x, onError, onStop) {
    if (!video || !x) return;
    window.cctvStop(video); video._live = true;
    /* 켜는 도중(통제소 켜기 대기·KBS 토큰 요청) 다른 항목을 누르면 먼저 것이 나중에 덮어쓰지 않게 — 순번이 바뀌면 옛 요청은 버린다 */
    var seq = video._seq = (video._seq || 0) + 1, live = function () { return video._seq === seq; };
    /* x.stopAfter(ms): 0 이면 스스로 멈추지 않는다 — 상황실 벽면처럼 화면이 60초마다 다음 지점으로 넘기는 곳용. 기본 90초. */
    var stopMs = (x.stopAfter != null) ? +x.stopAfter : 90000;
    var armStop = function () { if (video._stopT) clearTimeout(video._stopT); if (stopMs > 0) video._stopT = setTimeout(function () { window.cctvStop(video); if (onStop) onStop(); }, stopMs); };
    if (x.hls) { startHls(video, x.hls, onError); armStop(); return; }
    if (x.hrfco) {
      /* 통제소 스트림은 누가 보기 시작해야 켜진다 — 켜기 요청(응답은 못 읽어도 됨) 뒤 m3u8 이 200 될 때까지 기다린다 */
      var e = window.hrfcoCam(x.hrfco); if (!e) { if (onError) onError('device'); return; }
      var id = e.ld || e.hd, m3u8 = 'https://lw.hrfco.go.kr/live/cctv' + id + '/hls.m3u8';
      var body = new URLSearchParams({ deviceId: id, fcodvcd: e.fc || '01', type: e.ld ? 'low' : 'high' });
      try { fetch('https://n.flood.go.kr/getCctvScreen.do', { method: 'POST', mode: 'no-cors', body: body }).catch(function () {}); } catch (err) {}
      var tries = 0, wait = function () {
        if (!live()) return; tries++;
        fetch(m3u8, { cache: 'no-store' }).then(function (r) {
          if (!live()) return;
          if (r.ok) { startHls(video, m3u8, onError); armStop(); }
          else if (tries < 8) setTimeout(wait, 1500); else if (onError) onError('start');
        }).catch(function () { if (!live()) return; if (tries < 8) setTimeout(wait, 1500); else if (onError) onError('net'); });
      };
      setTimeout(wait, 1200); return;
    }
    var cam = x.kbs ? window.kbsCam(x.kbs) : null;
    if (cam && window.KBS_STREAM_BLOCKED) { if (onError) onError('KBS 차단'); return; }   /* 위 설명 참고 — 헛되이 기다리지 않는다 */
    if (!cam || !cam.url) { if (onError) onError('token'); return; }
    fetch(cam.url, { cache: 'no-store' }).then(function (r) { return r.ok ? r.text() : ''; })
      .then(function (t) { if (!live()) return; t = String(t || '').trim(); if (/^https?:\/\//.test(t)) { startHls(video, t, onError); armStop(); } else if (onError) onError('token'); })
      .catch(function () { if (!live()) return; if (onError) onError('net'); });
  };
  window.cctvStop = function (video) {
    if (!video) return; video._live = false;
    if (video._stopT) { clearTimeout(video._stopT); video._stopT = null; }
    if (video._hls) { try { video._hls.destroy(); } catch (e) {} video._hls = null; }
    try { video.pause(); video.removeAttribute('src'); video.load(); } catch (e) {}
  };
  /* 하위 호환(예전 이름) */
  window.kbsPlay = function (video, cam, onError) { window.cctvPlay(video, { kbs: cam && cam.id }, onError); };
  window.kbsStop = window.cctvStop;

  /* 관서(또는 그 관서의 본체 시군)에 해당하는 링크 목록 */
  window.cctvLinksFor = function (key, station, sigun) {
    var T = window.CCTV_LINKS[key] || {}; var out = [];
    [station, sigun].forEach(function (k) { if (k && T[k]) T[k].forEach(function (x) { if (out.indexOf(x) < 0) out.push(x); }); });
    (T['*'] || []).forEach(function (x) { if (out.indexOf(x) < 0) out.push(x); });
    return out;
  };
})();
