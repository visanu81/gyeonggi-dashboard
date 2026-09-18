// ===== 세종 화면 설정 =====
// tools/build_region_js.py 가 tools/profiles/sejong.json + map-geo-sejong.js 로 만든다.
// 직접 고치지 말 것 — 다시 생성하면 날아간다. 프로파일을 고치고 다시 돌릴 것.
//   python tools/build_region_js.py sejong
window.REGION_CONF = {
 "key": "sejong",
 "label": "세종",
 "office": "세종",
 "home": "세종",
 "countText": "1개 시군",
 "dataHost": "https://weather.visanu81.workers.dev",
 "wideNames": [
  "세종",
  "세종남부",
  "세종내륙",
  "세종동부",
  "세종북부",
  "세종산지",
  "세종서부",
  "세종영동",
  "세종영서",
  "세종중부",
  "세종특별자치시"
 ],
 "order": [
  "세종"
 ],
 "warnOrder": [
  "세종",
  "세종"
 ],
 "pos": {
  "세종": [
   2,
   0
  ]
 },
 "admin": {
  "세종": "세종특별자치시"
 },
 "riverMatch": {
  "세종": [
   "세종"
  ]
 },
 "fireGroup": {
  "세종": "세종"
 },
 "alias": {},
 "floodKeywords": [
  "금강",
  "세종",
  "용수천"
 ],
 "topRiversTitle": "주요 감시",
 "topRivers": [],
 "meteoV2": true,
 "riverMeta": {
  "3011675": {
   "agc": "기후에너지환경부",
   "addr": "세종특별자치시 조치원읍 신안리 상조천교 (충청북도 청원군 오송읍 상봉리)",
   "gdt": 29.029,
   "att": 2.3,
   "wrn": 3.2,
   "alm": 4.2,
   "srs": 4.77,
   "pfh": 4.77,
   "fstn": true
  },
  "3012602": {
   "agc": "기후에너지환경부",
   "addr": "세종특별자치시 연기면 세종리 햇무리교",
   "gdt": 9.272,
   "att": 9.1,
   "wrn": 9.5,
   "alm": 12,
   "srs": 15.28,
   "pfh": 15.28,
   "fstn": true
  },
  "3012607": {
   "agc": "기후에너지환경부",
   "addr": "세종특별자치시 금남면 도암리 도암교",
   "gdt": 20.325,
   "att": 1.5,
   "wrn": 2.5,
   "alm": 3.3,
   "srs": 4.1,
   "pfh": 4.1,
   "fstn": true
  }
 }
};
