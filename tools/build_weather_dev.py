# -*- coding: utf-8 -*-
"""weather 개조 작업장 빌드 — 2026-09-17 사장님 지시.

weather.visanu81.workers.dev:
  /            → 대문. 처음 온 사람은 /전국.html(시도 고르기)로, 고른 적 있으면 그 시도(/서울/)로,
                 경기를 골랐으면 그 자리에서 경기 전체판 지도가 뜬다(주소가 /지도 로 안 바뀜) — 2026-09-20
  /<시도>/     → 그 시도 지도(index=지도 화면). 어느 화면이든 열면 그 시도가 '고른 시도'로 기억된다(localStorage.ggSido)
  /전국.html   → 시도 고르기
  /new/*       → 옛 주소. _redirects 로 같은 경로의 루트로 301 (북마크 보호)
(2026-09-17~19 에는 루트가 '서비스 개편 중' 안내였고 작업 화면은 /new/ 아래였다.)

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
DEV_DIR = ''                    # 작업 화면이 사는 하위 경로 — '' = 루트 (2026-09-20). 예전엔 'new'
BASE = '/' + (DEV_DIR + '/' if DEV_DIR else '')       # '/' 또는 '/new/'
OLD_DIRS = ['new']              # 예전 하위 경로 — 같은 경로의 루트로 301

# Cloudflare Workers 정적 자산의 _redirects (Pages 와 같은 문법). 옛 /new/상황실.html 북마크가 계속 열리게.
REDIRECTS = ''.join(f'/{d}/* /:splat 301\n' for d in OLD_DIRS)

# 루트 대문 스크립트 — 처음 온 사람은 전국에서 시도를 고르고, 고른 적 있으면 그 시도로 (2026-09-20 사장님 지시).
# 옛 값('/new/서울/')이 남아 있어도 _redirects 가 /서울/ 로 넘기고 거기서 새 값으로 덮어쓴다.
GATE = """<script>
(function(){ try{ var s=localStorage.getItem('ggSido');
  if(!s){ location.replace('전국.html'); }
  else if(s!=='/' && s.charAt(0)==='/' && s.indexOf('//')<0){ location.replace(s); } }catch(e){} })();
</script>
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


def _profile_keys():
    prof_dir = ROOT / 'tools' / 'profiles'
    keys = [f.stem for f in prof_dir.glob('*.json')] if prof_dir.is_dir() else []
    return keys + ['north', 'south', 'all']


def _drop_profile_files(folder):
    """다른 시도의 원본 파일(data-<key>.js·region-<key>.js·map-geo-<key>.js·상황판-<key>.html)을 치운다.
    ⚠ 접두사로 지우면 안 된다 — data-adapter.js 가 같이 날아가 화면이 샘플 데이터로 돈다(실제로 겪음)."""
    names = set()
    for k in _profile_keys():
        names.update({f'data-{k}.js', f'region-{k}.js', f'map-geo-{k}.js', f'risk-zones-{k}.js',
                      f'상황판-{k}.html'})
    for f in list(folder.iterdir()):
        if f.is_file() and f.name in names:
            f.unlink()


def build_sido_sites():
    """/new/<시도>/ 하위 사이트를 SITE 안에 만든다. 돌아온 값: [(key, 표시명, 폴더명)]"""
    import json
    out = []
    prof_dir = ROOT / 'tools' / 'profiles'
    if not prof_dir.is_dir():
        return out
    for pf in sorted(prof_dir.glob('*.json')):
        prof = json.loads(pf.read_text(encoding='utf-8'))
        key, wide = prof['key'], prof['wide_label']
        need = [f'data-{key}.js', f'region-{key}.js', f'map-geo-{key}.js']
        missing = [n for n in need if not (ROOT / n).exists()]
        if missing:
            print(f'  · {wide}: 파일 없음 {missing} — 건너뜀')
            continue
        folder = prof['label']          # 주소는 짧은 이름(/new/강원/, /new/충북/)
        sub = SITE / folder
        sub.mkdir()
        for f in SITE.iterdir():
            if f.is_file() and f.suffix in ('.html', '.js', '.json', '.svg'):
                shutil.copy(f, sub / f.name)
        if (SITE / 'images').is_dir():
            shutil.copytree(SITE / 'images', sub / 'images')
        # 데이터는 서버(origin/main)에 있으면 그것, 없으면 로컬 수집본
        try:
            (sub / 'data.js').write_bytes(sh('git', 'show', f'origin/main:data-{key}.js'))
            src = '서버'
        except SystemExit:
            shutil.copy(ROOT / f'data-{key}.js', sub / 'data.js')
            src = '로컬 수집본'
        shutil.copy(ROOT / f'region-{key}.js', sub / 'region.js')
        shutil.copy(ROOT / f'map-geo-{key}.js', sub / 'map-geo.js')
        _drop_profile_files(sub)
        admins = list(prof['admin'].values())
        n = len(prof['regions'])
        cnt = (f'{n}개 ' + ('구·군' if any(a.endswith('군') for a in admins) else '구'))             if any(a.endswith('구') for a in admins) else f'{n}개 시군'
        for f in sub.glob('*.html'):
            body = f.read_text(encoding='utf-8')
            body = body.replace('경기도 · 34개 소방서', f'{wide} · {cnt}')
            body = body.replace('34개 소방서', cnt).replace('경기도', wide)
            if src == '서버':
                # 서버가 수집하는 시도는 운영 주소의 데이터·이미지를 직접 읽게 한다 —
                # 작업장을 다시 배포하지 않아도 5분마다 갱신된다(경기 전체판과 같은 방식).
                live = f'https://gyeonggi-dashboard.visanu81.workers.dev/data-{key}.js'
                body = body.replace('src="data.js"', f'src="{live}"')
                body = body.replace("'data.js?_t='", f"'{live}?_t='")
                body = body.replace("IMGH=''", "IMGH='https://gyeonggi-dashboard.visanu81.workers.dev/'")
                body = body.replace("'images/kma_", "'https://gyeonggi-dashboard.visanu81.workers.dev/images/kma_")
                body = body.replace('"images/kma_', '"https://gyeonggi-dashboard.visanu81.workers.dev/images/kma_')
            f.write_text(body, encoding='utf-8')
        out.append((key, wide, folder, src))
        print(f'  · 시도판 {wide}: 데이터={src}, 시군 {len(prof["regions"])}곳')
    return out


# 관서 선택창의 '시도' 줄 순서 — 북→남. 경기는 루트(BASE)에 있다.
SIDO_ORDER = ['seoul', 'incheon', 'gyeonggi', 'gangwon', 'sejong', 'daejeon', 'chungbuk', 'chungnam',
              'jeonbuk', 'jngj', 'gyeongbuk', 'daegu', 'gyeongnam', 'busan', 'ulsan', 'jeju']


def inject_sido_list(root, sidos):
    """각 폴더의 region.js 끝에 시도 목록(sidoList)과 현재 시도(sidoCurrent)를 붙인다.
    지도·호우 화면의 관서 선택창이 이걸 읽어 '시도' 줄을 그린다(2026-09-19 사장님 지시)."""
    import json
    entries = {'gyeonggi': {'label': '경기도', 'base': BASE}}
    for key, wide, folder, src in sidos:
        entries[key] = {'label': wide, 'base': f'{BASE}{folder}/'}
    ordered = [entries[k] for k in SIDO_ORDER if k in entries] + \
              [v for k, v in entries.items() if k not in SIDO_ORDER]
    lst = json.dumps(ordered, ensure_ascii=False)
    targets = [(root / 'region.js', '경기도')] + [(root / folder / 'region.js', wide) for _, wide, folder, _ in sidos]
    for path, cur in targets:
        if not path.exists():
            continue
        body = path.read_text(encoding='utf-8')
        base = next((e['base'] for e in ordered if e['label'] == cur), BASE)
        body += (f'\n// 전국판 시도 선택 — tools/build_weather_dev.py 가 배포할 때 붙인다\n'
                 f'window.REGION_CONF.sidoList = {lst};\n'
                 f'window.REGION_CONF.sidoCurrent = {json.dumps(cur, ensure_ascii=False)};\n'
                 f'// 이 시도의 어느 화면이든 열면 "고른 시도"로 기억 → 다음에 대문(/)이 바로 여기로 (2026-09-20)\n'
                 f'try{{ localStorage.setItem("ggSido", {json.dumps(base, ensure_ascii=False)}); }}catch(e){{}}\n')
        path.write_text(body, encoding='utf-8')


def landing_html(sidos):
    rows = ''.join(
        f'<a class="row" href="./{folder}/" onclick="remember(\'{BASE}{folder}/\')"><b>{wide}</b>'
        f'<span>{"5분마다 갱신" if src == "서버" else "시험판 · 갱신 안 됨"}</span></a>'
        for key, wide, folder, src in sorted(sidos, key=lambda s: (s[3] != '서버', s[2])))
    return f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>전국 기상·재난 상황판 — 시도 선택</title>
<style>
  body{{margin:0;background:#0b1220;color:#f3f6fc;font-family:'Pretendard Variable',Pretendard,'맑은 고딕',system-ui,sans-serif;}}
  .wrap{{max-width:560px;margin:40px auto;padding:0 16px;}}
  h1{{font-size:22px;margin:0 0 6px;}} p{{color:#93a5c4;font-size:14px;margin:0 0 22px;}}
  a.row{{display:flex;justify-content:space-between;align-items:center;padding:16px 18px;margin:8px 0;
        background:#141e33;border:1px solid #28313f;border-radius:14px;color:#f3f6fc;text-decoration:none;}}
  a.row span{{color:#93a5c4;font-size:13px;}} a.row.gg b{{color:#ffb020;}}
</style></head><body><div class="wrap">
<h1>전국 기상·재난 상황판</h1><p>시도를 고르세요. 화면 안의 '내 관서 선택'에서도 시도를 바꿀 수 있습니다.</p>
<div id="recent"></div>
<a class="row gg" href="./" onclick="remember('{BASE}')"><b>경기도</b><span>34개 소방서 · 운영과 같은 데이터</span></a>
{rows}
</div>
<script>
/* 고른 시도를 기억 — 다음부터 대문(/)이 바로 그 시도로 간다. 시도 폴더의 region.js 도 열릴 때 같은 값을 쓴다. */
function remember(base) {{ try {{ localStorage.setItem('ggSido', base); }} catch (e) {{}} }}
/* 마지막에 본 시도를 맨 위에 */
try {{
  var b = localStorage.getItem('ggSido');
  if (b) {{
    var a = document.querySelector('a.row[href="./' + b.replace('{BASE}', '') + '"]');
    if (a) {{
      var r = document.getElementById('recent');
      r.innerHTML = '<a class="row" style="border-color:#ffb020" href="' + b + '"><b>최근 본 시도 · ' + a.querySelector('b').textContent + '</b><span>바로가기</span></a>';
    }}
  }}
}} catch (e) {{}}
</script>
</body></html>
"""


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
    # 기상청 이미지(레이더·위성·특보발효도·강수예측)도 서버가 올린 최신 것으로 — 작업 트리 것은 옛날이다
    for img in (SITE / 'images').glob('*.png'):
        try:
            img.write_bytes(sh('git', 'show', f'origin/main:images/{img.name}'))
        except SystemExit:
            pass
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

    # 3-b) 시도판 — 생성 프로파일(tools/profiles/*.json)마다 /new/<시도>/ 하위 사이트 (전국 확장 1단계)
    #      경기 전체판 코드를 그대로 복사하고 데이터·지도·화면설정 세 파일만 그 시도 것으로 갈아끼운다.
    #      데이터는 서버가 아직 그 시도를 수집하지 않으면 작업 트리의 로컬 수집본을 쓴다.
    sidos = build_sido_sites()
    _drop_profile_files(SITE)      # 경기 전체판에는 다른 시도 파일이 필요 없다

    # 4) 배포 폴더 조립: 루트(BASE) = 작업 화면, 옛 /new/* 는 _redirects 로 루트로
    PUB.mkdir(parents=True, exist_ok=True)
    shutil.copytree(SITE, PUB / DEV_DIR, dirs_exist_ok=True)
    (PUB / '_redirects').write_text(REDIRECTS, encoding='utf-8')
    # 경기 전체판(BASE 루트)도 운영 ggweather 의 데이터·이미지를 직접 읽게 — 빌드 시점 스냅샷이 아니라 5분 갱신.
    # (시도판은 build_sido_sites 에서 같은 방식으로 gyeonggi-dashboard 의 data-<key>.js 를 읽는다)
    for f in (PUB / DEV_DIR).glob('*.html'):
        body = f.read_text(encoding='utf-8')
        live = 'https://ggweather.visanu81.workers.dev/'
        body = body.replace('src="data.js"', f'src="{live}data.js"').replace("'data.js?_t='", f"'{live}data.js?_t='")
        body = body.replace("IMGH=''", f"IMGH='{live}'")
        body = body.replace("'images/kma_", f"'{live}images/kma_").replace('"images/kma_', f'"{live}images/kma_')
        f.write_text(body, encoding='utf-8')
    (PUB / DEV_DIR / '전국.html').write_text(landing_html(sidos), encoding='utf-8')
    inject_sido_list(PUB / DEV_DIR, sidos)
    # 5) 대문 — index.html 을 지도 화면 그대로 (주소가 /지도 로 안 바뀐다). 루트 대문엔 '처음이면 전국에서
    #    고르고, 고른 적 있으면 그 시도로' 스크립트를 charset 바로 뒤, region.js 보다 앞에 둔다(ggSido 를 덮어쓰기 전).
    (PUB / DEV_DIR / 'index.html').write_text(
        (PUB / DEV_DIR / '지도.html').read_text(encoding='utf-8').replace('<meta charset="utf-8">', '<meta charset="utf-8">\n' + GATE, 1),
        encoding='utf-8')
    for _, _, folder, _ in sidos:
        shutil.copy(PUB / DEV_DIR / folder / '지도.html', PUB / DEV_DIR / folder / 'index.html')
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
