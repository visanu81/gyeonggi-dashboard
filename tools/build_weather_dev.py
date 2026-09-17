# -*- coding: utf-8 -*-
"""weather 개조 작업장 빌드 — 2026-09-17 사장님 지시.

weather.visanu81.workers.dev 를 두 층으로 만든다:
  /            → '서비스 개편 중' 안내 (기존 북마크 전부 이 안내로)
  /new/        → 실제 작업 중인 화면 = 경기 전체판(권역 선택 포함)

코드는 작업 트리(release, 통일판)에서, 데이터(data.js·data-south.js)만
origin/main(서버가 방금 올린 최신)에서 가져와 합친다. 변환 규칙은
deploy-ggweather.yml(전체판)과 같되, 하위 경로(/new/)에서 돌아가도록
절대주소를 문서 상대경로로 바꾼다.

쓰는 법:
  python tools/build_weather_dev.py          # .tmp/weather-dev/deploy 생성
  cd .tmp/weather-dev/deploy && wrangler deploy   # weather 워커로 배포
"""
import re
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
WORK = ROOT / '.tmp' / 'weather-dev'
SITE = WORK / 'site'
DEPLOY = WORK / 'deploy'
PUB = DEPLOY / 'public'
DEV_DIR = 'new'                 # 작업 화면이 사는 하위 경로

PAGES = ['index.html', '광역.html', '도움말.html', '상황실.html',
         '상황판.html', '지도.html', '호우.html']

NOTICE = """<!doctype html>
<html lang="ko"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>서비스 개편 중 — 경기남부 기상·재난 상황판</title>
<style>
  body{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;
       background:#0b1220;color:#f3f6fc;font-family:'Pretendard Variable',Pretendard,'맑은 고딕',system-ui,sans-serif;}
  .card{max-width:520px;margin:24px;padding:44px 36px;background:#141e33;border:1px solid #28313f;
        border-radius:22px;text-align:center;}
  .icon{font-size:52px;margin-bottom:14px;}
  h1{font-size:24px;margin:0 0 14px;}
  p{font-size:15px;line-height:1.7;color:#93a5c4;margin:0 0 26px;}
  a.btn{display:inline-block;padding:13px 26px;border-radius:12px;background:#ffb020;color:#101725;
        font-weight:700;font-size:15px;text-decoration:none;}
  .foot{margin-top:30px;font-size:12px;color:#5d6b83;}
</style></head><body>
<div class="card">
  <div class="icon">🚧</div>
  <h1>서비스 개편 중입니다</h1>
  <p>경기남부 기상·재난 상황판을 더 나은 모습으로 다듬고 있습니다.<br>
     그동안 <b style="color:#f3f6fc">경기 전체 상황판</b>에서<br>같은 정보를 보실 수 있습니다.</p>
  <a class="btn" href="https://ggweather.visanu81.workers.dev/">경기 전체 상황판 열기 →</a>
  <div class="foot">동두천소방서 소방위 한경승</div>
</div>
</body></html>
"""

WRANGLER = """# weather 개조 작업장 배포 설정 — tools/build_weather_dev.py 가 만든다.
name = "weather"
compatibility_date = "2024-10-21"

[assets]
directory = "public"
"""


def sh(*args):
    r = subprocess.run(args, cwd=str(ROOT), capture_output=True)
    if r.returncode != 0:
        raise SystemExit(f'실패: {" ".join(args)}\n{r.stderr.decode("utf-8", "replace")[:400]}')
    return r.stdout


def main():
    # 폴더 자체는 지우지 않는다 — 배포 셸이 그 안에 서 있으면 Windows 가 잠근다.
    # 내용물만 비운다(같은 이유로 deploy/ 도 파일 단위로 정리).
    if WORK.exists():
        for child in WORK.iterdir():
            if child.is_dir():
                for sub in child.iterdir():
                    shutil.rmtree(sub) if sub.is_dir() else sub.unlink()
            else:
                child.unlink()
    SITE.mkdir(parents=True, exist_ok=True)

    # 1) 코드는 작업 트리에서, 데이터만 origin/main(최신)에서
    for f in ROOT.iterdir():
        if f.suffix in ('.html', '.js', '.json', '.svg') and f.is_file():
            shutil.copy(f, SITE / f.name)
    if (ROOT / 'images').is_dir():
        shutil.copytree(ROOT / 'images', SITE / 'images')
    sh('git', 'fetch', 'origin', 'main', '-q')
    for name in ('data.js', 'data-south.js'):
        (SITE / name).write_bytes(sh('git', 'show', f'origin/main:{name}'))

    # 2) 두 데이터를 합쳐 경기 전체 데이터를 만든다 (merge_all은 저장소 루트 기준이라
    #    가짜 루트를 만들어 그 안에서 돌린다 — 작업 트리의 8월 데이터를 안 건드리기 위해)
    fake = WORK / 'fake'
    (fake / 'tools').mkdir(parents=True)
    shutil.copy(ROOT / 'tools' / 'merge_all.py', fake / 'tools' / 'merge_all.py')
    for name in ('data.js', 'data-south.js'):
        shutil.copy(SITE / name, fake / name)
    r = subprocess.run([sys.executable, '-X', 'utf8', str(fake / 'tools' / 'merge_all.py')],
                       capture_output=True)
    if r.returncode != 0 or not (fake / 'data-all.js').exists():
        raise SystemExit('merge_all 실패: ' + r.stderr.decode('utf-8', 'replace')[:300])
    shutil.copy(fake / 'data-all.js', SITE / 'data-all.js')

    # 3) 전체판 변환 (deploy-ggweather.yml 과 동일 규칙)
    for a, b in [('data-all.js', 'data.js'), ('map-geo-all.js', 'map-geo.js'),
                 ('region-all.js', 'region.js')]:
        if not (SITE / a).exists():
            raise SystemExit(f'전체판 파일이 없다: {a}')
        (SITE / a).replace(SITE / b)
    for leftover in ('data-south.js', 'map-geo-south.js', 'region-south.js',
                     'risk-zones-south.js'):
        (SITE / leftover).unlink(missing_ok=True)
    # 위험구역 — 북부 하드코딩 표본(window.RISK)만 비운다. 시트에서 읽은 값이 덮어쓴다.
    rz = SITE / 'risk-zones.js'
    kept = [ln for ln in rz.read_text(encoding='utf-8').splitlines()
            if not ln.startswith('window.RISK =') and not ln.startswith('window.RISK=')]
    kept.append('window.RISK = [];')
    rz.write_text('\n'.join(kept) + '\n', encoding='utf-8')

    n_files = 0
    for f in sorted(SITE.glob('*')):
        if f.suffix not in ('.html', '.js'):
            continue
        t = f.read_text(encoding='utf-8')
        o = t
        # (a) 광역.html의 데이터 출처 삼항 — 하위 경로에서도 자기 폴더의 data.js를 읽게
        t = re.sub(r"location\.hostname\.includes\('gyeonggi-dashboard-2'\)\s*"
                   r"\?\s*'https://gyeonggi-dashboard\.visanu81\.workers\.dev'\s*:\s*''",
                   "'.'", t)
        # (b) 절대주소 → 문서 상대경로 (/new/ 아래에서 자기 파일을 읽게)
        t = t.replace('https://gyeonggi-dashboard.visanu81.workers.dev/', '')
        # (c) 빠뜨린 무경로 참조 안전망
        t = t.replace('gyeonggi-dashboard.visanu81.workers.dev', 'weather.visanu81.workers.dev')
        if f.suffix == '.html':
            t = t.replace('동두천소방서 · 11개 소방관서', '경기도 · 34개 소방서')
            t = t.replace('경기북부', '경기도')
            t = t.replace('11개 소방관서', '34개 소방서').replace('10개 시군', '34개 소방서')
        if t != o:
            f.write_text(t, encoding='utf-8')
            n_files += 1

    # 4) 배포 폴더 조립: 루트 = 안내, /new/ = 작업 화면
    PUB.mkdir(parents=True, exist_ok=True)
    for name in PAGES:
        (PUB / name).write_text(NOTICE, encoding='utf-8')
    shutil.copytree(SITE, PUB / DEV_DIR)
    (DEPLOY / 'wrangler.toml').write_text(WRANGLER, encoding='utf-8')

    left = []
    for f in (PUB / DEV_DIR).glob('*.html'):
        body = f.read_text(encoding='utf-8')
        if 'gyeonggi-dashboard.visanu81' in body:
            left.append(f.name)
    print(f'빌드 완료: {DEPLOY}')
    print(f'  변환 파일 {n_files}개 · 남은 북부 흔적: {left or "없음"}')
    print(f'  배포:  cd "{DEPLOY}" && wrangler deploy')
    return 0


if __name__ == '__main__':
    sys.exit(main())
