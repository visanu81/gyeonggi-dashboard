/* 외부 하천 CCTV 바로가기 — 홍수통제소(n.flood.go.kr, 하천 상세에 이미 삽입) 밖에서 일반에 공개된 실시간 영상.
   2026-09-21 16개 시도 조사(지자체·홍수통제소·KBS 재난포털·유튜브 라이브). 운영 주체가 바뀌거나 주소가 죽으면 여기만 고친다.
   · 시도 키(region.js 의 key) → 관서 이름 → [{n:이름, u:주소}] · '*' 는 그 시도 모든 관서에.
   · KBS 재난포털 카메라는 공유 페이지(cctvShare?cctvId=)가 https 이고 iframe 도 허용된다(2026-09-21 확인).
   · 경기(all·north·south)는 같은 표를 쓴다. 지자체 페이지 중 http 전용(용인)은 새 창으로만 연다.
   · 조사 기록: workflows/운영현황.md '하천 CCTV 출처 조사'. */
(function () {
  var KBS = function (id, name) { return { n: 'KBS ' + name, u: 'https://d.kbs.co.kr/special/cctvShare?cctvId=' + id, kbs: id }; };
  var GG = {
    '가평': [KBS('9972', '가평2교 (북한강)')],
    '구리': [KBS('9974', '수택동 (왕숙천)')],
    '용인': [{ n: '용인시 재난CCTV — 하천 60대', u: 'http://safe.yongin.go.kr/m/cctv.html?cd=1&ct=3&ns=' }],
  };
  var CHEONGJU = [KBS('9968', '사직동 (무심천)')];
  var POHANG = [{ n: '포항시 방재기상정보 CCTV 25대', u: 'https://rain.pohang.go.kr/Front/Camera' }];
  window.CCTV_LINKS = {
    all: GG, north: GG, south: GG,
    seoul: {
      '노원구': [KBS('9966', '월계동 (중랑천)'), { n: '노원구 하천 유튜브 라이브 (중랑천·우이천·당현천)', u: 'https://www.youtube.com/@healinglivenowon7260' }],
      '마포구': [KBS('9965', '성산교 (홍제천)')],
      '서초구': [KBS('9973', '양재동 (양재천)'), KBS('9998', '반포한강공원')],
      '용산구': [KBS('9959', '한남동 (한강)')],
      '관악구': [{ n: '관악구 도림천(별빛내린천) 유튜브 라이브', u: 'https://www.youtube.com/@WelcomeToGwanak' }],
    },
    gangwon: { '춘천': [{ n: '춘천시 재난감시 하천 CCTV 16대', u: 'https://www.chuncheon.go.kr/disaster-safety/rainfall-info/cctv/' }] },
    busan: { '*': [{ n: '부산 안전ON 재난 CCTV (도시침수 통합플랫폼)', u: 'https://safecity.busan.go.kr/' }], '동래구': [KBS('9967', '세병교 (온천천)')] },
    daegu: { '동구': [KBS('9969', '신천동 (신천)')] },
    daejeon: { '*': [{ n: '금강홍수통제소 하천수위 영상 (대전 12지점)', u: 'https://www.geumriver.go.kr/html/sumun/river_movie_all.jsp' }], '유성구': [KBS('9970', '구성동 (갑천)')] },
    sejong: { '세종': [{ n: '세종엔 재난 CCTV', u: 'https://smart.sejong.go.kr/m/calamitycctvs' }, { n: '금강홍수통제소 하천수위 영상', u: 'https://www.geumriver.go.kr/html/sumun/river_movie_all.jsp' }] },
    chungbuk: { '청주동부': CHEONGJU, '청주서부': CHEONGJU, '단양': [KBS('9975', '도담삼봉 (남한강)')] },
    chungnam: { '공주': [KBS('9976', '금강교 (금강)')], '*': [{ n: '금강홍수통제소 하천수위 영상', u: 'https://www.geumriver.go.kr/html/sumun/river_movie_all.jsp' }] },
    jeonbuk: { '*': [{ n: '영산강홍수통제소 주요지점 수위 영상 (만경강·동진강·섬진강)', u: 'https://www.yeongsanriver.go.kr/sumun/video.do?S=S01&M=0202000000' }] },
    jngj: { '나주': [KBS('9978', '나주대교 (영산강)')], '*': [{ n: '영산강홍수통제소 주요지점 수위 영상', u: 'https://www.yeongsanriver.go.kr/sumun/video.do?S=S01&M=0202000000' }] },
    gyeongbuk: { '포항남부': POHANG, '포항북부': POHANG },
    gyeongnam: { '밀양': [KBS('9977', '삼랑진 (낙동강)')] },
    jeju: {
      '제주': [{ n: '제주시 하천감시 CCTV 62대', u: 'https://www.jejusi.go.kr/bangjae/realcctvHls/riverHlsCctv.do' }],
      '서귀포': [{ n: '서귀포시 실시간 하천 CCTV 27대', u: 'https://www.seogwipo.go.kr/field/safety/live/hls.htm' }],
    },
  };
  /* 관서(또는 그 관서의 본체 시군)에 해당하는 링크 목록 */
  window.cctvLinksFor = function (key, station, sigun) {
    var T = window.CCTV_LINKS[key] || {}; var out = [];
    [station, sigun].forEach(function (k) { if (k && T[k]) T[k].forEach(function (x) { if (out.indexOf(x) < 0) out.push(x); }); });
    (T['*'] || []).forEach(function (x) { if (out.indexOf(x) < 0) out.push(x); });
    return out;
  };
})();
