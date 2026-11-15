// 최소 service worker — Chrome PWA installability 기준 충족용
// 캐시 정책은 적용하지 않음 (A 옵션 — 매번 네트워크 fresh fetch)
// 추후 오프라인 캐시(B)·푸시(C)가 필요해지면 이 파일을 확장.

self.addEventListener('install', (event) => {
  // 새 SW를 즉시 활성화 (기존 SW 대기 안 함)
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  // 활성화 즉시 모든 열린 탭 제어
  event.waitUntil(self.clients.claim());
});

self.addEventListener('fetch', (event) => {
  // 빈 fetch 핸들러 — 브라우저 기본 동작 그대로
  // (이 핸들러가 존재하는 것만으로도 Chrome이 PWA로 인식)
});
