#!/usr/bin/env bash
# 경기남부 배포본을 로컬에 그대로 재현한다 (확인용).
#
# deploy-weather.yml 이 GitHub Actions에서 하는 변환을 똑같이 수행하므로,
# 운영에 올리기 전에 '남부에서 실제로 어떻게 보이는지'를 미리 볼 수 있다.
# 경기남부 전용 화면은 테스트2(gyeonggi-dashboard-2)로는 확인이 안 되기 때문에
# (테스트2는 북부 데이터를 본다) 이 스크립트가 그 자리를 대신한다.
#
# 쓰는 법
#   bash tools/build_south_preview.sh          # 기본 위치에 생성
#   bash tools/build_south_preview.sh <폴더>   # 원하는 위치에
#   그 뒤 그 폴더를 정적 서버로 띄워서 본다 (python -m http.server)
set -e
cd "$(dirname "$0")/.."
SRC=$(pwd)
DST="${1:-$SRC/.tmp/south-preview}"

rm -rf "$DST"; mkdir -p "$DST"
for f in *.html *.js *.json *.svg; do [ -f "$f" ] && cp "$f" "$DST/"; done
cp -r images "$DST/" 2>/dev/null || true

cd "$DST"
rm -f 상황판.html 상황판-south.html          # 안 쓰는 옛 스냅샷은 제외

# ── deploy-weather.yml 과 같은 순서 ──
mv data-south.js       data.js
mv map-geo-south.js    map-geo.js
mv region-south.js     region.js
mv risk-zones-south.js risk-zones.js

grep -rl 'gyeonggi-dashboard\.visanu81\.workers\.dev' --include='*.html' --include='*.js' . \
  | xargs -r sed -i 's|gyeonggi-dashboard\.visanu81\.workers\.dev|weather.visanu81.workers.dev|g'
grep -rl '경기북부' --include='*.html' . | xargs -r sed -i 's|경기북부|경기남부|g'
grep -rl '동두천소방서 · 11개 소방관서' --include='*.html' . \
  | xargs -r sed -i 's|동두천소방서 · 11개 소방관서|경기남부 · 21개 시군|g'
grep -rl '11개 소방관서' --include='*.html' . \
  | xargs -r sed -i 's|11개 소방관서|21개 시군|g; s|10개 시군|21개 시군|g'

# ── 여기서부터는 미리보기 전용 ──
# 아직 배포 안 된 남부 주소 대신 로컬 파일을 보게 한다.
grep -rl 'weather\.visanu81\.workers\.dev' --include='*.html' --include='*.js' . \
  | xargs -r sed -i 's|https://weather\.visanu81\.workers\.dev/|/|g'

echo "생성: $DST"
echo "--- 남은 북부 흔적(있으면 확인) ---"
grep -rn 'gyeonggi-dashboard\.visanu81\|경기북부\|11개 소방관서' \
  --include='*.html' --include='*.js' . | head || echo "없음"
