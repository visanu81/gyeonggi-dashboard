// ===== 제주도 화면 설정 =====
// tools/build_region_js.py 가 tools/profiles/jeju.json + map-geo-jeju.js 로 만든다.
// 직접 고치지 말 것 — 다시 생성하면 날아간다. 프로파일을 고치고 다시 돌릴 것.
//   python tools/build_region_js.py jeju
window.REGION_CONF = {
 "key": "jeju",
 "label": "제주도",
 "office": "제주도",
 "home": "제주",
 "countText": "2개 시군",
 "dataHost": "https://weather.visanu81.workers.dev",
 "wideNames": [
  "제주",
  "제주남부",
  "제주내륙",
  "제주도",
  "제주동부",
  "제주북부",
  "제주산지",
  "제주서부",
  "제주영동",
  "제주영서",
  "제주중부",
  "제주특별자치도"
 ],
 "order": [
  "제주",
  "서귀포"
 ],
 "warnOrder": [
  "제주도",
  "제주",
  "서귀포"
 ],
 "pos": {
  "제주": [
   0,
   0
  ],
  "서귀포": [
   4,
   0
  ]
 },
 "admin": {
  "서귀포": "서귀포시",
  "제주": "제주시"
 },
 "riverMatch": {
  "제주": [
   "제주"
  ],
  "서귀포": [
   "서귀포"
  ]
 },
 "fireGroup": {
  "제주": "제주·서귀포",
  "서귀포": "제주·서귀포"
 },
 "alias": {},
 "floodKeywords": [
  "금성천",
  "서귀포",
  "제주",
  "제주도",
  "창고천",
  "한천"
 ],
 "topRiversTitle": "주요 감시",
 "topRivers": [],
 "meteoV2": true,
 "riverMeta": {
  "6001650": {
   "agc": "기후에너지환경부",
   "addr": "제주특별자치도 제주시 애월읍 금성리",
   "gdt": 16.69,
   "att": 2.2,
   "wrn": 3.5,
   "alm": 4.5,
   "srs": 5.5,
   "pfh": 5.59,
   "fstn": false
  },
  "6002670": {
   "agc": "기후에너지환경부",
   "addr": "제주특별자치도 제주시 오라일동",
   "gdt": 51.85,
   "att": 2.6,
   "wrn": 3.8,
   "alm": 4.9,
   "srs": 6,
   "pfh": 6.08,
   "fstn": false
  },
  "6003620": {
   "agc": "기후에너지환경부",
   "addr": "제주특별자치도 서귀포시 안덕면 감산리",
   "gdt": 5.13,
   "att": 2.4,
   "wrn": 3.7,
   "alm": 4.9,
   "srs": 6.1,
   "pfh": 6.13,
   "fstn": false
  },
  "6004670": {
   "agc": "기후에너지환경부",
   "addr": "제주특별자치도 서귀포시 성산읍 신천리",
   "gdt": 13.48,
   "att": 1.7,
   "wrn": 2.6,
   "alm": 3.5,
   "srs": 4.3,
   "pfh": 4.36,
   "fstn": false
  }
 }
};
