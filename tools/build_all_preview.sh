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
# 위험구역은 아직 경기 전체용 시트가 없다 → 북부 것을 그대로 두면 동두천·의정부만
# 뜨는데, 그건 '경기 전체'에서 오해를 부른다. 빈 목록으로 시작한다.
cat > risk-zones.js <<'RZ'
// 경기 전체(ggweather) — 인명피해 우려지역. 아직 시트가 없어 비어 있다.
// 채우려면 관서별 탭이 있는 구글시트를 만들고 RISK_SHEET_URL 을 넣으면 된다.
window.RISK_ZONES = {};
window.RISK_SHEET_URL = '';
RZ
rm -f risk-zones-south.js

grep -rl 'gyeonggi-dashboard\.visanu81\.workers\.dev' --include='*.html' --include='*.js' . \
  | xargs -r sed -i 's|gyeonggi-dashboard\.visanu81\.workers\.dev|ggweather.visanu81.workers.dev|g'
grep -rl '경기북부' --include='*.html' . | xargs -r sed -i 's|경기북부|경기도|g'
grep -rl '동두천소방서 · 11개 소방관서' --include='*.html' . \
  | xargs -r sed -i 's|동두천소방서 · 11개 소방관서|경기도 · 31개 시군|g'
grep -rl '11개 소방관서' --include='*.html' . \
  | xargs -r sed -i 's|11개 소방관서|31개 시군|g; s|10개 시군|31개 시군|g'

# ── 여기서부터는 미리보기 전용 ──
# 아직 배포 안 된 주소 대신 로컬 파일을 보게 한다.
grep -rl 'ggweather\.visanu81\.workers\.dev' --include='*.html' --include='*.js' . \
  | xargs -r sed -i 's|https://ggweather\.visanu81\.workers\.dev/|/|g'

echo "생성: $DST"
echo "--- 남은 북부 흔적(있으면 확인) ---"
grep -rn 'gyeonggi-dashboard\.visanu81\|경기북부\|11개 소방관서\|21개 시군' \
  --include='*.html' --include='*.js' . | head || echo "없음"
