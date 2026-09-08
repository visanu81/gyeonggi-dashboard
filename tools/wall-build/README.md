# 상황실.html (v2 벽면 상황판) 빌드 도구

사장님이 Claude Design에서 만든 단독실행본을 그대로 쓰되, 데모 데이터만 우리 실시간 데이터로
바꿔 끼우고, 시간대별 예보는 실제 예보 메테오그램으로 개조한다.

## 정식 빌드 — build_wall.py ★현재 배포본
`design_clean.html`(번들에서 화면만 추출한 깨끗한 HTML)에 **번들 폰트를 data-URI로 인라인** +
데이터·로직·메테오그램 개조를 적용 → `../../상황실.html` (약 4MB).
- 깨끗한 HTML이라 템플릿 수정이 쉽고, 폰트는 번들과 동일하게 임베드(CDN 0·글꼴 깜빡임 0).
- 적용 내용:
  1. **폰트 인라인**: `original_bundle.html`의 `__bundler/manifest`(UUID→base64)에서 폰트 92개를
     추출해 @font-face `url("UUID")` → `url(data:font/woff2;base64,…)`.
  2. **폰트고정**: helmet의 `html,body{…overflow:hidden;}` 규칙에 `font-family:Pretendard Variable` 추가.
     (원본이 이 규칙에 font-family를 빠뜨려 관서명·온도가 벽면 Chrome에서 맑은고딕으로 떨어졌음.
      dc-runtime이 부팅 때 head를 helmet으로 재구성하므로 outer `<head>` 삽입은 무효 — 반드시 이 규칙에.)
  3. **로직패치**: warnsOf(실특보 우선) / st()의 feels·effHum·gust 실값 우선 / NAMES 김포→연천.
  4. **메테오그램**: st()에 hourly 주입, `meteoEl`(React SVG: 기온선+체감점선+강수막대+값라벨) 메서드,
     renderVals `meteo` 바인딩, 템플릿 막대그리드 → `{{ meteo }}`.
  5. **WALL_DATA 변환기(INJECT)**: data.js(운영 절대URL,5분)→stations(hourly 포함)·rivers·msgs·warns,
     위험구역=구글시트 관서별 탭(30분). 버그수정: 하천 긴시군 매칭·전관서 [] 초기화·worst 가드.

재빌드: `python tools/wall-build/build_wall.py`
디자인 갱신 시: Downloads의 새 단독실행본을 `original_bundle.html`로 교체(폰트·매니페스트 원천) +
새 화면추출을 `design_clean.html`로 교체 후 재빌드.
검증: 이 환경은 스크린샷 불가(브라우저창 미표시) → svgCount·polyline·getComputedStyle 구조검증으로 대체.

## 폐기 — build_bundle.py *비배포*
번들(4MB·JSON이스케이프본) 자체에 주입하던 방식. 폰트는 완벽했으나 템플릿(메테오그램 등) 수정이
JSON이스케이프 때문에 난해해, 폰트를 인라인한 build_wall.py로 대체함. 기록 보존용.

## 파일
- `original_bundle.html` — 원본 단독실행본 복사(4MB, untracked·배포 미포함). 폰트 매니페스트 원천.
- `design_clean.html` — 화면만 추출(폰트 UUID참조 유지). build_wall.py 입력.
- `build_wall.py` — ★정식 빌드
- `build_bundle.py` — 폐기(참고용)
