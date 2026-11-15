// ===== 위험구역 데이터 =====
// [구글시트 실시간 연동] 배포 사이트에서는 RISK_SHEET_URL(웹 게시 CSV)을 자동으로 불러옵니다.
//   시트 열: 지역 | 도로명주소 | 유형 | (등급) | 위도 | 경도
//   지역값은 "동두천시" 처럼 써도 "동두천" 관서로 자동 매칭됩니다.
// [VWorld 위치지도] VWORLD_KEY 에 브이월드 인증키를 넣고, 인증키에 배포 도메인을 등록하면
//   위험구역 상세에서 위·경도로 실제 지도(정적지도)가 표시됩니다. (비우면 안내 폴백)
window.VWORLD_KEY = "CA711B51-FC8E-3021-A91F-0D342A3495F9";
window.RISK_SHEET_URL = "https://docs.google.com/spreadsheets/d/1vrSOXBune7mNa7rCjUEj7D-acaqD5e3dHLcSKgQPPAU/gviz/tq?tqx=out:csv";
window.RISK = [{"id":1,"region":"동두천","name":"경기도 동두천시 송내동 송내동 67, 73번지 일원","type":"산사태취약지구","level":"주의","note":"경기도 동두천시 송내동 송내동 67, 73번지 일원","lat":37.87906036,"lng":127.0767555,"x":434.4,"y":541.9}];
