#!/usr/bin/env bash
# 경기 전체(ggweather) 배포본을 로컬에 그대로 재현한다 (확인용).
#
# deploy-ggweather.yml 이 GitHub Actions에서 하는 변환을 똑같이 수행하므로,
# 운영에 올리기 전에 '경기 전체에서 실제로 어떻게 보이는지'를 미리 볼 수 있다.
# 테스트2(gyeonggi-dashboard-2)는 북부 데이터를 보기 때문에 이 화면 확인엔 못 쓴다.
#
# 쓰는 법
#   bash tools/build_all_preview.sh            # 기본 위치에 생성
#   bash tools/build_all_preview.sh <폴더>     # 원하는 위치에
#   그 뒤 그 폴더를 정적 서버로 띄워서 본다 (python -m http.server)
set -e
cd "$(dirname "$0")/.."
SRC=$(pwd)
DST="${1:-$SRC/.tmp/all-preview}"

# 데이터·설정을 먼저 최신으로 만든다 (수집이 아니라 '합치기'라 API 호출 0회)
python tools/merge_all.py
python tools/build_region_all.py >/dev/null

rm -rf "$DST"; mkdir -p "$DST"
for f in *.html *.js *.json *.svg; do [ -f "$f" ] && cp "$f" "$DST/"; done
cp -r images "$DST/" 2>/dev/null || true

cd "$DST"
rm -f 상황판.html 상황판-south.html          # 안 쓰는 옛 스냅샷은 제외

# ── deploy-ggweather.yml 과 같은 순서 ──
mv data-all.js      data.js
mv map-geo-all.js   map-geo.js
mv region-all.js    region.js
rm -f data-south.js map-geo-south.js region-south.js   # 남부 전용본은 안 쓴다
# 위험구역 — 경기 전체도 같은 구글시트를 그대로 본다(사장님 요청 2026-08-20).
#   화면이 관서마다 '그 이름의 탭'을 찾아 읽으므로, 시트에 탭이 있는 관서만
#   표시되고 없는 관서는 '등록된 위험구역 없음'이 된다 — 걸러낼 필요가 없다.
#   (없는 탭을 부르면 구글이 첫 탭을 돌려주는 함정이 있는데, 첫 탭과 같은 내용이면
#    건너뛰는 안전장치가 지도.html 에 이미 있다.)
# 다만 북부에 하드코딩된 표본(window.RISK)은 지운다 — 경기 전체에선 동두천
#   한 곳만 뜬 것처럼 보여 오해를 부른다. 시트에서 읽은 값이 이걸 덮어쓴다.
grep -v '^window\.RISK *=' risk-zones.js > risk-zones.js.new
echo 'window.RISK = [];' >> risk-zones.js.new
mv risk-zones.js.new risk-zones.js
rm -f risk-zones-south.js

grep -rl 'gyeonggi-dashboard\.visanu81\.workers\.dev' --include='*.html' --include='*.js' . \
  | xargs -r sed -i 's|gyeonggi-dashboard\.visanu81\.workers\.dev|ggweather.visanu81.workers.dev|g'
grep -rl '경기북부' --include='*.html' . | xargs -r sed -i 's|경기북부|경기도|g'
grep -rl '동두천소방서 · 11개 소방관서' --include='*.html' . \
  | xargs -r sed -i 's|동두천소방서 · 11개 소방관서|경기도 · 34개 소방서|g'
grep -rl '11개 소방관서' --include='*.html' . \
  | xargs -r sed -i 's|11개 소방관서|34개 소방서|g; s|10개 시군|34개 소방서|g'

# ── 여기서부터는 미리보기 전용 ──
# 아직 배포 안 된 주소 대신 로컬 파일을 보게 한다.
grep -rl 'ggweather\.visanu81\.workers\.dev' --include='*.html' --include='*.js' . \
  | xargs -r sed -i 's|https://ggweather\.visanu81\.workers\.dev/|/|g'

echo "생성: $DST"
echo "--- 남은 북부 흔적(있으면 확인) ---"
# 제작자 크레딧(제작 : 소방위 한경승 · 동두천소방서)은 남아 있어야 정상이라 뺀다.
grep -rn 'gyeonggi-dashboard\.visanu81\|경기북부\|11개 소방관서\|21개 시군' \
  --include='*.html' --include='*.js' . | grep -v '제작' | head || echo "없음"
