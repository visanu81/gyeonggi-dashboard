# -*- coding: utf-8 -*-
"""사장님 클로드디자인(단독실행)을 클린 페이지로 변환하고 우리 실데이터(WALL_DATA)를 주입한다.
변환:
 - @font-face(임베드 폰트 4MB) 제거 → Pretendard CDN
 - 번들 support(UUID) → 우리 ./support.js
 - NAMES 김포→연천 (우리 실관서)
디자인 로직 패치(파생 → 실값 우선):
 - warnsOf: EXT().warns 있으면 실제 발효특보 사용(없으면 기존 파생)
 - st(): feels/effHum/gust 를 실값(g.feels/g.eff/g.gust) 우선, 없으면 기존 근사
주입(</body> 앞):
 - risk-zones.js(RISK_SHEET_URL) + data.js + 변환기
 - DASHBOARD_DATA → WALL_DATA(stations·rivers·msgs·warns) 변환, 5분 갱신
 - 위험구역: 관서별 시트 탭 로딩(지도.html loadRiskSheet 포팅), 30분 갱신
결과: 프로젝트 루트 상황실.html
"""
import re, io, sys, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
WB = r'C:/Users/USER/Desktop/AI업무처리/기상,재난상황판/tools/wall-build'
ROOT = r'C:/Users/USER/Desktop/AI업무처리/기상,재난상황판'
h = open(WB + '/design_clean.html', encoding='utf-8').read()

# 1) 폰트: 번들 매니페스트에서 추출해 @font-face url("UUID")를 data-URI로 인라인
#    (CDN 의존 0·글꼴 깜빡임 0. 번들과 동일한 Pretendard 임베드, 단 HTML은 깨끗해 수정 쉬움)
_bundle = open(WB + '/original_bundle.html', encoding='utf-8', errors='replace').read()
_mani = json.loads(re.search(r'<script type="__bundler/manifest">(.*?)</script>', _bundle, re.S).group(1).strip())
_fc = [0]
def _font(m):
    res = _mani.get(m.group(1))
    if res and 'font' in res.get('mime', ''):
        _fc[0] += 1; return 'url(data:%s;base64,%s)' % (res['mime'], res['data'])
    return m.group(0)
h = re.sub(r'url\("([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})"\)', _font, h)
print('폰트 인라인:', _fc[0], '개')
assert _fc[0] >= 80, '폰트 추출 실패'

# 1.5) 기본폰트 고정 — helmet html,body 규칙에 font-family 추가(원본 누락분)
_hb = "html,body{margin:0;padding:0;background:var(--bg,#0d1118);overflow:hidden;}"
assert h.count(_hb) == 1, 'html,body 규칙 이상'
h = h.replace(_hb, _hb[:-1] + "font-family:'Pretendard Variable',Pretendard,system-ui,sans-serif;}")
print('폰트고정: helmet html,body')

# 2) 번들 support 스크립트 → 우리 support.js
h = h.replace('<script src="ae9b4964-bcad-4854-8bd3-dc2becb14f62"></script>',
              '<script src="./support.js"></script>')

# 4-0) region.js를 <body> 맨 앞에 — 화면 컴포넌트보다 먼저 실행돼야 한다
h = h.replace('<body>', '<body>\n<script src="./region.js"></script>', 1)

# 4) NAMES: 김포 → 연천
assert "'김포'" in h, "NAMES '김포' 못 찾음"
h = h.replace("'김포'", "'연천'")

# 4-1) 화면 컴포넌트의 관서 목록도 지역 설정을 따르게 한다.
#     (주입한 변환기만 바꿔선 소용없다 — 순환 표시·'n / 전체' 개수는 이 NAMES가 정한다)
_names_old = ("const NAMES = ['고양','일산','파주','연천','의정부','양주','동두천',"
              "'포천','가평','남양주','구리'];")
_names_new = ("const NAMES = ((typeof window!=='undefined'&&window.REGION_CONF&&window.REGION_CONF.order)"
              " || ['고양','일산','파주','연천','의정부','양주','동두천','포천','가평','남양주','구리']);")
assert _names_old in h, '화면 컴포넌트의 NAMES를 못 찾음 — 디자인 원본이 바뀌었는지 확인'
h = h.replace(_names_old, _names_new, 1)
print('패치: 화면 컴포넌트 NAMES → region.js 연동')

# ── 로직 패치: 파생 → 실값 우선 ─────────────────────────────
def patch(old, new, label):
    global h
    assert old in h, f'패치 실패(원문 없음): {label}'
    h = h.replace(old, new, 1)
    print('패치:', label)

# (a) warnsOf: 실제 발효특보 우선
patch('warnsOf(s){',
      'warnsOf(s){ const _e=EXT(); if(_e.warns) return _e.warns[s.name]||[];',
      'warnsOf → 실특보')

# (b) 체감(feels): 실값 우선
patch('const feels = wet ? +(temp + 1.2).toFixed(1) : +(temp + (humid>60 ? 5.2 : 3.2)).toFixed(1);',
      'const feels = (g && g.feels!=null) ? +g.feels : (wet ? +(temp + 1.2).toFixed(1) : +(temp + (humid>60 ? 5.2 : 3.2)).toFixed(1));',
      'feels → 실값')

# (c) 실효습도(effHum): 실값 우선
patch('const effHum = wet ? Math.min(97, humid + 3) : Math.round(humid - 8 - r3*10);',
      'const effHum = (g && g.eff!=null) ? Math.round(g.eff) : (wet ? Math.min(97, humid + 3) : Math.round(humid - 8 - r3*10));',
      'effHum → 실값')

# (d) 순간풍속(gust): 실값 우선
patch('gust:+(wind*1.7).toFixed(1)',
      'gust:(g && g.gust!=null)?+g.gust:+(wind*1.7).toFixed(1)',
      'gust → 실값')

# (d2) 라이트모드 색상 — 강조색(초록/앰버/주황/빨강/파랑/남색)을 테마별 CSS 변수로.
#      원본은 다크 전용 고정 hex라 라이트에서 앰버 글씨가 흰 배경에 안 보였음(사장님 지적).
#      fit()이 테마 변수(--bg 등)를 세팅하는 자리에 강조색 세트도 함께 세팅 →
#      아래 '전역 hex→var 치환'과 짝을 이룸(모든 hex는 style 값으로만 쓰여 안전, 비교사용 0 확인).
patch("r.setProperty('--acc', acc);",
      "r.setProperty('--acc', dark ? acc : '#E86A12');\n"
      # 강조색: 라이트도 '같은 색상(hue)·채도'를 유지하고 밝기만 최소로 낮춰 흰 배경 대비 3:1 확보.
      # (다크색 그대로면 앰버 1.83:1·초록 1.97:1로 글씨가 뭉갠다. 빨강은 3.06:1이라 그대로 사용)
      # 대문자 표기 = 아래 전역 hex→var 치환 회피(자기참조 방지)
      "    const A = dark ? {cGreen:'#2AD19A',cAmber:'#FFB020',cOrange:'#FF9A3C',cRed:'#FF5A5A',cBlue:'#54AAFF',cIndigo:'#B7C4FF'}\n"
      "                   : {cGreen:'#1DA77A',cAmber:'#CC8400',cOrange:'#EA7100',cRed:'#FF5A5A',cBlue:'#2B96FF',cIndigo:'#728BFF'};\n"
      "    Object.keys(A).forEach(k=>r.setProperty('--'+k, A[k]));\n"
      # 상황단계·경보배너 칩: 다크=옅은 틴트+선명 글씨 / 라이트=선명 단색 배경+검은 글씨.
      # 라이트에서 배경·글씨가 같은 앰버 계열이라 안 읽히던 문제(사장님 지적) 해결이자,
      # 다크의 선명한 색을 '배경'으로 그대로 쓰는 방법(단색 위 검은 글씨 대비 6~11:1).
      "    const L = dark\n"
      "      ? [['rgba(42,209,154,.12)','#2AD19A','rgba(42,209,154,.85)','rgba(42,209,154,.55)'],\n"
      "         ['rgba(255,176,32,.14)','#FFB020','rgba(255,176,32,.9)','rgba(255,176,32,.6)'],\n"
      "         ['rgba(255,122,47,.16)','#FF7A2F','rgba(255,122,47,.92)','rgba(255,122,47,.7)'],\n"
      "         ['rgba(255,77,77,.18)','#FF5A5A','rgba(255,140,140,.95)','rgba(255,77,77,.8)']]\n"
      "      : [['#2AD19A','#0B1220','rgba(11,18,32,.75)','#1DA77A'],\n"
      "         ['#FFB020','#0B1220','rgba(11,18,32,.75)','#CC8400'],\n"
      "         ['#FF7A2F','#0B1220','rgba(11,18,32,.78)','#E05A10'],\n"
      "         ['#FF5A5A','#0B1220','rgba(11,18,32,.82)','#E03A3A']];\n"
      "    L.forEach((v,i)=>{ r.setProperty('--lv'+i+'Bg',v[0]); r.setProperty('--lv'+i+'Fg',v[1]);\n"
      "      r.setProperty('--lv'+i+'Sub',v[2]); r.setProperty('--lv'+i+'Bd',v[3]); });",
      '테마별 강조색·상황단계 칩 변수')

# (d3) 상황단계 색 정의를 테마 변수로 — 원본은 다크 전용 고정 hex라 라이트에서 배경·글씨가 같은 계열
patch("""      { rank:0, name:'평상', fg:'#2ad19a', bg:'rgba(42,209,154,.12)', border:'rgba(42,209,154,.55)', sub:'rgba(42,209,154,.85)' },
      { rank:1, name:'주의', fg:'#ffb020', bg:'rgba(255,176,32,.14)', border:'rgba(255,176,32,.6)', sub:'rgba(255,176,32,.9)' },
      { rank:2, name:'경계', fg:'#ff7a2f', bg:'rgba(255,122,47,.16)', border:'rgba(255,122,47,.7)', sub:'rgba(255,122,47,.92)' },
      { rank:3, name:'심각', fg:'#ff5a5a', bg:'rgba(255,77,77,.18)', border:'rgba(255,77,77,.8)', sub:'rgba(255,140,140,.95)' }""",
      """      { rank:0, name:'평상', fg:'var(--lv0Fg)', bg:'var(--lv0Bg)', border:'var(--lv0Bd)', sub:'var(--lv0Sub)' },
      { rank:1, name:'주의', fg:'var(--lv1Fg)', bg:'var(--lv1Bg)', border:'var(--lv1Bd)', sub:'var(--lv1Sub)' },
      { rank:2, name:'경계', fg:'var(--lv2Fg)', bg:'var(--lv2Bg)', border:'var(--lv2Bd)', sub:'var(--lv2Sub)' },
      { rank:3, name:'심각', fg:'var(--lv3Fg)', bg:'var(--lv3Bg)', border:'var(--lv3Bd)', sub:'var(--lv3Sub)' }""",
      '상황단계 색 → 테마 변수')

# ── 시간대별 예보 → 메테오그램(기온선+체감선+강수막대, 실제 예보) ──
# (e) st() 반환에 실제 hourly 실어보내기
patch('feels, effHum, wet, fireRisk, windDeg: Math.round(r3*360),',
      'feels, effHum, wet, fireRisk, hourly:(g&&g.hourly)?g.hourly:null, '
      'windDeg: (g && g.wdeg != null) ? Math.round(g.wdeg) : null,',
      'st() → hourly + 풍향 실값')

# (f) hours 생성: 합성 → 실제 예보 우선 (정규식으로 블록 교체)
HOURS_NEW = '''// hourly — 실제 예보만 쓴다. 없으면 빈 배열(→ 화면에 '예보 없음').
    // ⚠ 원본 디자인은 예보가 없으면 12시간치를 rnd()로 지어냈다(기온·강수확률·강수량 전부).
    //   비가 오는 상태(s.wet)면 강수확률을 85%에서 시작해 5%씩 낮추고 시간당 최대 2.5mm를
    //   난수로 채웠다 — 상황실 벽면에 '앞으로 12시간 강수 전망'으로 그대로 떴다.
    //   2026-08-15 가짜 재난문자, 08-17 난수 풍향과 같은 부류라 분기째 들어냈다.
    let hours = [];
    if (s.hourly && s.hourly.length){
      hours = s.hourly.map(function(o,k){ var t=(o.t!=null?Math.round(o.t):null);
        return { t:t, feels:(o.feels!=null?Math.round(o.feels):null), rain:(o.rain!=null?o.rain:0),
          pop:(o.pop!=null?Math.round(o.pop):null), label:(o.label||(k===0?'지금':'')),
          icon:(o.icon||'☁️'), wx:(o.wx||null),
          wind:(o.wind!=null?o.wind:null), deg:(o.deg!=null?o.deg:null),
          dir:(o.dir||''), humid:(o.humid!=null?Math.round(o.humid):null) }; });
    }
    const tv = hours.map(function(x){return x.t;}).filter(function(v){return v!=null;});
    const tMin = tv.length?Math.min.apply(null,tv):0, tMax = tv.length?Math.max.apply(null,tv):1;
    const hourList = hours.map(function(x,k){
      return { label: x.label, labelColor: k===0 ? 'var(--acc,#ff7a2f)' : 'var(--dim,#8e9bb0)',
        icon: x.icon, wx: x.wx, temp: x.t, feels: x.feels, rain: x.rain,
        popText: (x.pop!=null?x.pop:0)+'%', popColor: x.pop>=50 ? '#54aaff' : 'var(--dim,#8e9bb0)' };
    });'''
_n = re.subn(r'// hourly — 일교차.*?\'var\(--dim,#8e9bb0\)\' \};\n    \}\);', HOURS_NEW, h, count=1, flags=re.S)
assert _n[1] == 1, 'hours 블록 교체 실패(%d)' % _n[1]
h = _n[0]; print('패치: hours → 실제예보')

# (g) 시간대별 표 주입 — 대시보드(지도.html hourlyTableBody)와 같은 형태
# 사장님 요청(2026-08-17): 벽면의 메테오그램(그래프)을 대시보드의 '시간대별 날씨' 표로.
# 두 화면을 같은 방식으로 읽게 하고, 그래프로는 안 보이던 바람·습도까지 보이게 한다.
#
# 왜 12시간인가 — 벽면은 손으로 넘길 수 없어 가로 스크롤을 못 쓴다. 카드 폭이
# 무대 기준 1224px이라 24시간을 넣으면 한 칸이 51px, 벽면에서 숫자가 안 읽힌다.
# 12시간이면 한 칸 약 90px로 넉넉하다. (대시보드는 스크롤이 되니 24시간 그대로)
#
# 메서드 이름(meteoEl)과 인자는 그대로 둔다 — 아래 (h)(i) 패치가 그 이름을 쓴다.
METEO = r"""meteoEl(hours, tMin, tMax){
    const R = window.React.createElement, N = hours.length;
    const DIM='var(--dim,#8e9bb0)', ACC='var(--acc,#ff7a2f)', BLUE='#54aaff';
    /* 예보가 없으면 지어내지 않고 그대로 말한다(대시보드와 같은 태도). */
    if (!N) return R('div',{style:{display:'flex',alignItems:'center',justifyContent:'center',
      height:'100%',color:DIM,fontSize:'30px',fontWeight:700}}, '시간대별 예보 없음');

    const num=(v,d)=>(v!=null&&!isNaN(v))?(+v).toFixed(d==null?0:d):'-';
    const NOWBG='rgba(255,122,47,.10)';           /* '지금' 칸 세로 밴드 */
    const cell=(child,i,extra)=>R('div',{style:Object.assign({display:'flex',flexDirection:'column',
      alignItems:'center',justifyContent:'center',padding:'7px 2px',minWidth:0,
      background:(i===0?NOWBG:'transparent')}, extra||{})}, child);
    const lab=(txt)=>R('div',{style:{display:'flex',alignItems:'center',justifyContent:'flex-end',
      paddingRight:'16px',fontSize:'25px',fontWeight:700,color:DIM,whiteSpace:'nowrap'}}, txt);

    /* ── 날씨 아이콘 (메테오그램에서 쓰던 통일 SVG 그대로) ── */
    const CLD='M8.5 25a5.2 5.2 0 0 1-.1-10.4 7.8 7.8 0 0 1 15-1.9 5.7 5.7 0 0 1-1 12.3h-13.9z';
    const MOON='M20 4.8a11.6 11.6 0 1 0 7.4 16.2A9.6 9.6 0 0 1 20 4.8z';
    const rays=(cx,cy,ri,ro,sw)=>[0,45,90,135,180,225,270,315].map((a,q)=>{const rd=a*Math.PI/180;
      return R('line',{key:'ry'+q,x1:cx+Math.cos(rd)*ri,y1:cy+Math.sin(rd)*ri,
        x2:cx+Math.cos(rd)*ro,y2:cy+Math.sin(rd)*ro,
        style:{stroke:'#ffb020',strokeWidth:sw,strokeLinecap:'round'}});});
    const WX={
      sun:[R('circle',{key:'c',cx:16,cy:16,r:6.2,style:{fill:'#ffb020'}})].concat(rays(16,16,9,12.6,2.6)),
      moon:[R('path',{key:'m',d:MOON,style:{fill:'#b7c4ff'}})],
      cloud:[R('path',{key:'c',d:CLD,style:{fill:DIM}})],
      cloudsun:[R('circle',{key:'s',cx:21.5,cy:9.5,r:4.4,style:{fill:'#ffb020'}})].concat(rays(21.5,9.5,6.4,8.8,2.2))
        .concat([R('path',{key:'c',d:CLD,transform:'translate(-1.5 3.5) scale(.88)',style:{fill:DIM}})]),
      cloudmoon:[R('path',{key:'m',d:MOON,transform:'translate(12.5 1.5) scale(.42)',style:{fill:'#b7c4ff'}}),
        R('path',{key:'c',d:CLD,transform:'translate(-1.5 3.5) scale(.88)',style:{fill:DIM}})],
      rain:[R('path',{key:'c',d:CLD,transform:'translate(1.5 -2.5) scale(.92)',style:{fill:DIM}})]
        .concat([[10.5,23],[16,24],[21.5,23]].map((p,q)=>R('line',{key:'dp'+q,x1:p[0],y1:p[1],
          x2:p[0]-1.6,y2:p[1]+4.6,style:{stroke:BLUE,strokeWidth:2.6,strokeLinecap:'round'}}))),
      snow:[R('path',{key:'c',d:CLD,transform:'translate(1.5 -2.5) scale(.92)',style:{fill:DIM}})]
        .concat([[10.5,25],[16,27],[21.5,25]].map((p,q)=>R('circle',{key:'sf'+q,cx:p[0],cy:p[1],r:1.7,
          style:{fill:BLUE,opacity:0.85}}))),
      storm:[R('path',{key:'c',d:CLD,transform:'translate(1.5 -3.5) scale(.92)',style:{fill:DIM}}),
        R('path',{key:'b',d:'M17 19l-4.2 6.8h3.4l-2.4 6.2 7.6-8.8h-3.5l2.8-4.2z',style:{fill:'#ffb020'}})]
    };
    const wxSvg=(wx,fb)=>WX[wx]? R('svg',{viewBox:'0 0 32 32',width:52,height:52,style:{display:'block'}},WX[wx])
                               : R('span',{style:{fontSize:'44px',lineHeight:1.1}},fb||'☁️');

    /* ── 기온 행: 표 격자에 정렬된 꺾은선 + 값 (대시보드와 같은 구성) ──
       SVG를 가로로 늘리면(preserveAspectRatio none) 원·글자가 찌그러지므로
       선·면만 SVG로 그리고 점과 숫자는 HTML로 덧놓는다. */
    const GH=196, pT=52, pB=26;
    const tvv=hours.map(h=>(h.t!=null&&!isNaN(h.t))?h.t:null);
    const known=tvv.filter(v=>v!=null);
    let lo=known.length?Math.min.apply(null,known):0, hi=known.length?Math.max.apply(null,known):1;
    if(!(hi-lo>=3)) hi=lo+3;
    const yOf=t=>pT+(1-((t-lo)/(hi-lo)))*(GH-pT-pB);
    const VW=N*100, xOf=i=>(i+0.5)*(VW/N);
    const pts=hours.map((h,i)=>[xOf(i), yOf(tvv[i]!=null?tvv[i]:(lo+hi)/2)]);
    const lineStr=pts.map(p=>p[0].toFixed(1)+','+p[1].toFixed(1)).join(' ');
    const gk=[
      R('defs',{key:'d'},R('linearGradient',{id:'wtG',x1:'0',y1:'0',x2:'0',y2:'1'},
        R('stop',{offset:'0',style:{stopColor:'#ff9a3c',stopOpacity:0.22}}),
        R('stop',{offset:'1',style:{stopColor:'#ff9a3c',stopOpacity:0.02}}))),
      R('rect',{key:'nb',x:0,y:0,width:VW/N,height:GH,style:{fill:NOWBG}}),
      R('polygon',{key:'ar',points:'0,'+GH+' '+lineStr+' '+VW+','+GH,fill:'url(#wtG)',stroke:'none'}),
      R('polyline',{key:'ln',points:lineStr,style:{fill:'none',stroke:'#ff9a3c',strokeWidth:4,
        strokeLinecap:'round',strokeLinejoin:'round',vectorEffect:'non-scaling-stroke'}})
    ];
    const graphRow=R('div',{style:{gridColumn:'2 / -1',position:'relative',height:GH+'px'}},
      R('svg',{viewBox:'0 0 '+VW+' '+GH,preserveAspectRatio:'none',
        style:{position:'absolute',left:0,top:0,width:'100%',height:'100%'}},gk),
      hours.map((h,i)=>[
        R('div',{key:'d'+i,style:{position:'absolute',left:((i+0.5)/N*100)+'%',top:(pts[i][1]/GH*100)+'%',
          transform:'translate(-50%,-50%)',width:(i===0?'15px':'11px'),height:(i===0?'15px':'11px'),
          borderRadius:'50%',boxSizing:'border-box',
          background:(i===0?ACC:'var(--panel,#151b26)'),border:'3px solid '+(i===0?'#fff':'#ff9a3c')}}),
        R('div',{key:'v'+i,style:{position:'absolute',left:((i+0.5)/N*100)+'%',top:(pts[i][1]/GH*100)+'%',
          transform:'translate(-50%,-155%)',fontSize:'29px',fontWeight:800,whiteSpace:'nowrap',
          color:(i===0?ACC:'currentColor'),paintOrder:'stroke',
          WebkitTextStroke:'5px var(--panel,#151b26)'}}, num(h.t)+'°')
      ]));

    /* ── 나머지 행들 — 대시보드와 같은 순서·같은 강조 규칙 ── */
    const kids=[];
    const push=(label,fn,extra)=>{ kids.push(lab(label));
      hours.forEach((h,i)=>kids.push(cell(fn(h,i),i,extra))); };

    push('', (h,i)=>R('div',{style:{fontSize:'29px',fontWeight:800,whiteSpace:'nowrap',
      color:(i===0?ACC:'currentColor')}}, i===0?'지금':(h.label||'')));
    push('날씨', (h)=>wxSvg(h.wx,h.icon));
    kids.push(lab('기온'), graphRow);
    push('체감', (h)=>R('div',{style:{fontSize:'27px',fontWeight:700,color:DIM}}, num(h.feels)+'°'));
    /* 강수 — 있으면 파란 알약, 없으면 옅은 점(대시보드와 동일) */
    push('강수', (h)=>((h.rain||0)>0)
      ? R('div',{style:{fontSize:'25px',fontWeight:800,color:'#fff',background:BLUE,
          padding:'4px 12px',borderRadius:'999px',whiteSpace:'nowrap'}}, num(h.rain,1))
      : R('div',{style:{fontSize:'27px',color:DIM,opacity:0.45,fontWeight:700}}, '·'));
    /* 강수확률 — 숫자 + 미니 막대 */
    push('강수확률', (h)=>{ const p=(h.pop!=null?h.pop:0), col=(p>=60?BLUE:(p>=30?'#7fb8ff':DIM));
      return R('div',{style:{display:'flex',flexDirection:'column',alignItems:'center',gap:'5px',width:'100%'}},
        R('div',{style:{fontSize:'26px',fontWeight:(p>=60?800:600),color:col}}, p+'%'),
        R('div',{style:{width:'62px',height:'7px',borderRadius:'4px',background:'rgba(255,255,255,.10)',overflow:'hidden'}},
          R('div',{style:{width:p+'%',height:'100%',background:col,borderRadius:'4px'}}))); });
    /* 바람 — 방향 원형 칩(회전 화살표) + 방위명 + 풍속. 방향 자료가 없으면 화살표를 숨긴다. */
    push('바람', (h)=>R('div',{style:{display:'flex',flexDirection:'column',alignItems:'center',gap:'3px'}},
      R('div',{style:{width:'46px',height:'46px',borderRadius:'50%',background:'rgba(255,255,255,.07)',
        display:'flex',alignItems:'center',justifyContent:'center'}},
        R('div',{style:{fontSize:'26px',lineHeight:1,fontWeight:800,color:ACC,
          transform:'rotate('+(h.deg!=null?h.deg:0)+'deg)'}}, h.deg!=null?'↑':'')),
      R('div',{style:{fontSize:'20px',color:DIM,whiteSpace:'nowrap'}}, h.dir||''),
      R('div',{style:{fontSize:'24px',fontWeight:700}}, num(h.wind,1))));
    push('습도', (h)=>R('div',{style:{fontSize:'27px',fontWeight:700,color:DIM}},
      h.humid!=null?(h.humid+'%'):'-'));

    return R('div',{style:{display:'grid',gridTemplateColumns:'118px repeat('+N+',1fr)',
      alignItems:'center',height:'100%',alignContent:'space-evenly'}}, kids);
  }"""

patch('  // 특보는 실황값에서 파생',
      '  ' + METEO + '\n\n  // 특보는 실황값에서 파생',
      'meteoEl 주입')

# (h) renderVals에 meteo 바인딩 + pop null 가드
patch('hours: hourList, tMax, tMin, pop: Math.max(...hours.map(h=>h.pop)),',
      'hours: hourList, tMax, tMin, meteo: this.meteoEl(hours, tMin, tMax), pop: Math.max.apply(null, hours.map(function(h){return h.pop||0;})),',
      'renderVals → meteo')

# (i) 템플릿: 막대 그리드 → {{ meteo }} (정규식)
_m = re.subn(r'<div style="flex:1;min-height:0;display:grid;grid-template-columns:repeat\(12,1fr\);gap:10px;">.*?</sc-for>\s*</div>',
             '<div style="flex:1;min-height:0;">{{ meteo }}</div>', h, count=1, flags=re.S)
assert _m[1] == 1, '시간대별 마크업 교체 실패(%d)' % _m[1]
h = _m[0]; print('패치: 템플릿 → 메테오그램')

# ── (u) 관할 위험구역 → 6시간 강수예측 ★사장님 요청(2026-08-17) ──────────
# 왜 바꾸나 — 위험구역은 11개 관서 중 동두천(44)·의정부(19) 두 곳만 구글시트에 등록돼
# 있어, 관서가 15초마다 순환하는 벽면에서 북부는 시간의 82%, 남부는 100%가
# '등록된 위험구역 없음'이었다. 빈 카드가 화면 1/6을 계속 차지하고 있었다.
# 무엇으로 바꾸나 — 6시간 강수예측(초단기예보). 매 회차 수집하면서도 지도·광역·호우·
# 상황실 어디에서도 안 쓰던 유일한 데이터다(전 화면 grep 확인). 시간대별 예보(단기,
# 3시간마다 갱신)와 달리 매시간 갱신이라 앞으로 몇 시간은 훨씬 정확하고,
# 낙뢰(lgt)는 이 자료에만 있다 — 다른 어느 화면에도 안 나온다.
# 위험구역 자체는 지도 화면(관서 focus)에 그대로 남아 있다.

# (u1)은 INJECT(빌드 스크립트 자체 코드)라 아래에서 직접 치환한다.

# (u2) 화면 요소 생성 메서드
ULTRA = r"""ultraEl(rows){
    const R = window.React.createElement;
    const DIM='var(--dim,#8e9bb0)', BLUE='#54aaff', AMBER='#ffb020';
    /* 자료가 없으면 지어내지 않는다(2026-08-15·17에 걷어낸 것과 같은 원칙). */
    if(!rows || !rows.length) return R('div',{style:{flex:1,display:'flex',alignItems:'center',
      justifyContent:'center',fontSize:'38px',fontWeight:700,color:DIM}},'초단기예보 자료 없음');
    const N=rows.length;
    const cell=(o,i)=>{
      const wet=(o.rain||0)>0, hi=(o.pop||0)>=60;
      return R('div',{key:i,style:{flex:'1 1 0',minWidth:0,display:'flex',flexDirection:'column',
        alignItems:'center',justifyContent:'center',gap:'6px',padding:'10px 4px',borderRadius:'14px',
        background:(wet?'rgba(84,170,255,.10)':'transparent')}},
        R('div',{style:{fontSize:'27px',fontWeight:700,color:DIM,whiteSpace:'nowrap'}}, o.time||'-'),
        R('div',{style:{fontSize:'46px',fontWeight:800,lineHeight:1.2,whiteSpace:'nowrap',
          color:(wet?BLUE:'currentColor'),opacity:(wet?1:0.45)}},
          (o.rain!=null? (wet? (+o.rain).toFixed(1) : '0') : '-'),
          R('span',{style:{fontSize:'24px',fontWeight:700,marginLeft:'3px',color:DIM}},'mm')),
        R('div',{style:{fontSize:'26px',fontWeight:(hi?800:600),color:(hi?BLUE:DIM),whiteSpace:'nowrap'}},
          (o.pop!=null?o.pop:0)+'%'),
        /* \uac15\uc218\ud615\ud0dc \u2014 \uae30\uc0c1\uccad\uc740 \ube44\uac00 \uc5c6\uc744 \ub54c '\uc5c6\uc74c'\uc744 \uc900\ub2e4. \uadf8\ub300\ub85c \uc4f0\uba74 \uc5ec\uc12f \uce78\uc774
           \uc804\ubd80 '\uc5c6\uc74c'\uc73c\ub85c \ub3c4\ubc30\ub3fc \uc77d\uc744 \uac8c \uc5c6\ub2e4. \uc2e4\uc81c \ud615\ud0dc(\ube44\u00b7\ub208\u00b7\uc18c\ub098\uae30)\uc77c \ub54c\ub9cc \uc4f4\ub2e4. */
        (function(){ var k=(o.pty && o.pty !== '\uc5c6\uc74c') ? o.pty : '';
          return R('div',{style:{fontSize:'24px',fontWeight:700,whiteSpace:'nowrap',
            color:(o.lgt?AMBER:BLUE),opacity:(k||o.lgt)?1:0}},
            (o.lgt?'\u26a1 ':'')+(k||(o.lgt?'\ub099\ub8b0':'\u00b7'))); })());
    };
    return R('div',{style:{flex:1,minHeight:0,display:'flex',alignItems:'stretch',gap:'6px'}},
      rows.map(cell));
  }"""
patch('  // 특보는 실황값에서 파생',
      '  ' + ULTRA + '\n\n  // 특보는 실황값에서 파생',
      'ultraEl 주입')

# (u3) renderVals에 바인딩 — 합계·최대확률도 같이 계산해 부제에 쓴다
patch('      risks: risks.slice(0,3), noRisk: risks.length === 0, riskCount: risks.length,',
      """      risks: risks.slice(0,3), noRisk: risks.length === 0, riskCount: risks.length,
      ultraEl: this.ultraEl((EXT().ultra||{})[s.name]),
      ultraSum: (function(a){ if(!a||!a.length) return '\\u2014';
        var t=a.reduce(function(x,o){ return x+(o.rain||0); },0);
        var p=a.reduce(function(x,o){ return Math.max(x,o.pop||0); },0);
        var g=a.some(function(o){ return o.lgt; });
        return (t>0? ('6시간 '+t.toFixed(1)+'mm') : '강수 없음')+' \\u00b7 최대확률 '+p+'%'+(g?' \\u00b7 \\u26a1낙뢰':''); })
        ((EXT().ultra||{})[s.name]),""",
      'renderVals → 6시간 강수예측')

# (u4) 카드 마크업 교체 — 제목·부제 + 6칸
_u = re.subn(
    r'<div style="font-size:40px;font-weight:800;">관할 위험구역</div>\s*'
    r'<div style="font-size:30px;font-weight:700;color:var\(--dim,#8e9bb0\);">\{\{ riskCount \}\}곳 등록</div>\s*'
    r'</div>\s*<div style="flex:1;min-height:0;display:flex;flex-direction:column;gap:12px;">.*?</sc-if>\s*</div>',
    '<div style="font-size:40px;font-weight:800;">6시간 강수예측</div>\n'
    '              <div style="font-size:28px;font-weight:700;color:var(--dim,#8e9bb0);">{{ ultraSum }}</div>\n'
    '            </div>\n'
    '            <div style="flex:1;min-height:0;display:flex;">{{ ultraEl }}</div>',
    h, count=1, flags=re.S)
assert _u[1] == 1, '위험구역 카드 마크업 교체 실패(%d)' % _u[1]
h = _u[0]; print('패치: 위험구역 카드 → 6시간 강수예측')

# (j) 하천·댐 카드 재작성 — 공식 기준 판정 + 댐 별도 표기 + 가짜값 제거
#  · 원본은 상태를 '위험수위의 50/70/88%'라는 임의 비율로 매겼다. 우리 데이터엔 한강홍수통제소
#    공식 주의보(warning)/경보(danger) 수위가 있으므로 그걸로 판정한다. (예: 연천 필승교는
#    주의보 1.0m·위험 7.5m라, 비율식이면 주의보를 넘겨도 13%로 '정상' 초록 — 위험한 방향)
#  · 원본은 비 올 때 수위에 rain1h*0.09를 더하고(가짜 가산), 10분 변화량을 난수로 만들었다 →
#    실측 수위와 실제 delta_1h로 교체.
#  · 댐: 상시만수위 유지가 정상이라 '위험수위 대비 %'가 무의미 → 저수율·유입·방류로 표기,
#    막대는 저수율(0~100 유효시), 상태는 수위 추세, 색은 중립(파랑). 단 공식 level이 뜨면 그대로 승격.
RIVERS_NEW = '''const _rlist = ((EXT().rivers || RIVERS)[s.name] || RIVERS['양주']);
    /* 행이 많으면(연천=하천3+댐2) 고정 글자크기가 카드를 넘겨 막대와 글자가 겹친다 → 밀도 자동 조정 */
    const _SZ = [{n:'40px',d:'30px',v:'46px',s:'32px',b:'20px',p:'14px 24px',g:'10px'},
                 {n:'34px',d:'26px',v:'40px',s:'28px',b:'15px',p:'9px 20px',g:'7px'},
                 {n:'28px',d:'21px',v:'32px',s:'23px',b:'10px',p:'6px 16px',g:'4px'}
                ][_rlist.length>=5 ? 2 : (_rlist.length===4 ? 1 : 0)];
    const rv = _rlist.map((r,k)=>{
      const val=+r[1]||0, dg=+r[2]||0, isDam=(r[3]==='dam'), lv=r[4]||'safe';
      const d1=(r[5]==null?null:+r[5]), wn=(r[6]==null?null:+r[6]);
      const rate=(r[7]==null?null:+r[7]), inf=(r[8]==null?null:+r[8]), out=(r[9]==null?null:+r[9]);
      const ratio = dg ? val/dg : 0;
      let color, status;
      if (lv==='danger'){ color='#ff5a5a'; status='위험'; }
      else if (lv==='warning'){ color='#ffb020'; status='주의보'; }
      else if (isDam){ color='#54aaff'; status=(d1==null?'관측':(d1>=0.05?'수위 상승':(d1<=-0.05?'수위 하강':'안정'))); }
      else { color='#2ad19a'; status='정상'; }
      const useRate = isDam && rate!=null && rate>=0 && rate<=100;
      const pctNum = useRate ? rate : Math.min(100, Math.max(0, ratio*100));
      const fmt = v => (v==null ? '-' : (Math.abs(v)>=100 ? String(Math.round(v)) : v.toFixed(1)));
      const trend = (d1==null||d1===0) ? '변화 없음' : ((d1>0?'▲ +':'▼ ')+Math.abs(d1).toFixed(2)+'m/1시간');
      const note = isDam
        ? (useRate ? '저수율 '+rate.toFixed(1)+'%' : '수위/계획홍수위 '+pctNum.toFixed(0)+'%')
          +' · 유입 '+fmt(inf)+' → 방류 '+fmt(out)+'m³/s'
        : trend + (dg ? ' · 위험 '+dg.toFixed(1)+'m' : '');
      return { name:r[0], value:val.toFixed(2), pct:pctNum.toFixed(0)+'%', color, status, delta:note, isDam,
        mkW: (!isDam && wn!=null && dg) ? Math.min(97,(wn/dg)*100).toFixed(0)+'%' : '0%',
        mkD: '97%', mkOp: (isDam ? '0' : '.6'), mkOp2: (isDam ? '0' : '.85'),
        fsN:_SZ.n, fsD:_SZ.d, fsV:_SZ.v, fsS:_SZ.s, barH:_SZ.b, pad:_SZ.p, gap:_SZ.g };
    });'''
_r = re.subn(r"const rv = \(\(EXT\(\)\.rivers.*?\n    \}\);\n", RIVERS_NEW + '\n', h, count=1, flags=re.S)
assert _r[1] == 1, '하천 블록 교체 실패(%d)' % _r[1]
h = _r[0]; print('패치: 하천·댐 → 공식기준 판정')

# (j2) 침수판단 worst — 댐 제외(댐 저수율/수위비는 하천 홍수위와 의미가 달라 판단 오염)
patch('const worst = Math.max(...rv.map(r=>parseFloat(r.pct)));',
      'const _rw = rv.filter(x=>!x.isDam).map(r=>parseFloat(r.pct));\n'
      '    const worst = _rw.length ? Math.max.apply(null,_rw) : 0;',
      'worst → 댐 제외')

# (j3) 막대 눈금선: 고정 70%/88% → 관측소별 공식 주의보 위치, 댐은 숨김
patch('<div style="position:absolute;top:0;bottom:0;width:3px;background:var(--dim,#8e9bb0);opacity:.6;left:70%;"></div>',
      '<div style="position:absolute;top:0;bottom:0;width:3px;background:var(--dim,#8e9bb0);opacity:{{ r.mkOp }};left:{{ r.mkW }};"></div>',
      '주의보 눈금선 → 공식 위치')
patch('<div style="position:absolute;top:0;bottom:0;width:3px;background:#ff4d4d;opacity:.8;left:88%;"></div>',
      '<div style="position:absolute;top:0;bottom:0;width:3px;background:var(--cRed,#ff5a5a);opacity:{{ r.mkOp2 }};left:{{ r.mkD }};"></div>',
      '위험 눈금선 → 막대 끝')

# (j3b) 막대 트랙이 행 5개일 때 flex로 0px까지 눌려 사라짐 → 축소 금지 + 높이도 밀도 연동
patch('<div style="height:20px;border-radius:10px;background:var(--track,#232c3a);overflow:hidden;position:relative;">',
      '<div style="height:{{ r.barH }};flex-shrink:0;border-radius:10px;background:var(--track,#232c3a);overflow:hidden;position:relative;">',
      '막대 축소 금지·높이 연동')

# (j3c) 행 밀도 — 행 수에 따라 글자·여백 자동 축소(고정크기면 5행에서 글자와 막대가 겹침)
patch('gap:10px;background:var(--panel2,#1b2230);border-radius:16px;padding:14px 24px;">',
      'gap:{{ r.gap }};background:var(--panel2,#1b2230);border-radius:16px;padding:{{ r.pad }};">',
      '행 여백 연동')
patch('<div style="font-size:40px;font-weight:700;white-space:nowrap;">{{ r.name }}</div>',
      '<div style="font-size:{{ r.fsN }};font-weight:700;white-space:nowrap;">{{ r.name }}</div>',
      '하천명 크기 연동')
patch('<div style="font-size:30px;font-weight:600;color:var(--dim,#8e9bb0);white-space:nowrap;">{{ r.delta }}</div>',
      '<div style="font-size:{{ r.fsD }};font-weight:600;color:var(--dim,#8e9bb0);white-space:nowrap;">{{ r.delta }}</div>',
      '보조설명 크기 연동')
patch('<div style="margin-left:auto;font-size:46px;font-weight:800;font-variant-numeric:tabular-nums;color:{{ r.color }};white-space:nowrap;">{{ r.value }}m</div>',
      '<div style="margin-left:auto;font-size:{{ r.fsV }};font-weight:800;font-variant-numeric:tabular-nums;color:{{ r.color }};white-space:nowrap;">{{ r.value }}m</div>',
      '수위값 크기 연동')
patch('<div style="font-size:32px;font-weight:800;color:{{ r.color }};white-space:nowrap;">{{ r.status }}</div>',
      '<div style="font-size:{{ r.fsS }};font-weight:800;color:{{ r.color }};white-space:nowrap;">{{ r.status }}</div>',
      '상태 크기 연동')

# (k) 메인 대시보드로 돌아가는 링크 — 상황실은 별도 페이지라 복귀 진입점이 없었다.
#     ⚠ 상단 컨트롤 줄(❚❚ ‹ › ☾)에 넣으면 시계 카드가 640px 고정이라 넘친다(측정: 날짜줄
#       715px > 556px 칸). → 스테이지(3840px, transform:scale) '밖' 고정 컨테이너의 자식으로
#       좌상단 오버레이로 배치. 지도.html 벽면 컨트롤 관례대로 평소 흐릿(.28) → hover 시 선명.
#       스테이지 밖이라 화면 크기와 무관하게 항상 같은 크기로 보인다(벽면에서 과하지 않음).
patch('<div ref="{{ stageRef }}"',
      '<a href="지도.html" title="일반 상황판(대시보드)으로 돌아가기" '
      'style="position:absolute;left:10px;top:8px;z-index:20;opacity:.22;'
      'padding:6px 11px;border-radius:9px;border:1px solid var(--line,#28313f);background:var(--panel,#151b26);'
      'color:var(--fg,#f2f5fa);font-size:12px;font-weight:600;text-decoration:none;white-space:nowrap;" '
      'style-hover="opacity:1;border-color:var(--acc,#ff7a2f)">← 상황판</a>\n'
      '  <a href="도움말.html" title="사용설명서 — 화면 보는 법과 색·기호, 자동 판단 기준" '
      'style="position:absolute;left:98px;top:8px;z-index:20;opacity:.22;'
      'padding:6px 11px;border-radius:9px;border:1px solid var(--line,#28313f);background:var(--panel,#151b26);'
      'color:var(--fg,#f2f5fa);font-size:12px;font-weight:600;text-decoration:none;white-space:nowrap;" '
      'style-hover="opacity:1;border-color:var(--acc,#ff7a2f)">❓ 설명서</a>\n'
      '  <div ref="{{ stageRef }}"',
      '복귀·설명서 링크(좌상단 오버레이)')

# (j5) 출동 영향 판단 — 전역보다 한 단계 더 얇게(사장님 지적: 이 블록이 특히 두껍다).
#      전역 리맵(800→660/700→570/500유지)에 다시 안 걸리도록 그 목록에 없는 값을 쓴다.
patch('<div style="font-size:38px;font-weight:700;line-height:1.05;white-space:nowrap;">{{ i.title }}</div>',
      '<div style="font-size:38px;font-weight:545;line-height:1.05;white-space:nowrap;">{{ i.title }}</div>',
      '출동판단 제목 545')
patch('<div style="font-size:29px;font-weight:500;line-height:1.15;color:var(--dim,#8e9bb0);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">{{ i.note }}</div>',
      '<div style="font-size:29px;font-weight:445;line-height:1.15;color:var(--dim,#8e9bb0);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">{{ i.note }}</div>',
      '출동판단 설명 445')
patch('<div style="margin-left:auto;flex:none;font-size:44px;font-weight:800;color:{{ i.color }};white-space:nowrap;">{{ i.level }}</div>',
      '<div style="margin-left:auto;flex:none;font-size:44px;font-weight:615;color:{{ i.color }};white-space:nowrap;">{{ i.level }}</div>',
      '출동판단 등급 615')

# (j4) 카드 부제 — 하천/댐 기준이 다름을 명시
patch('한강홍수통제소 · 위험수위 대비',
      '한강홍수통제소 · 하천 위험수위 / 댐 저수율',
      '하천카드 부제')

# (j6) 사다리차 판정 → 순간풍속 기준 (지도.html과 통일)
# 원본은 '평균풍속 12/8m/s'로 단계를 정하면서 설명줄엔 순간풍속을 찍었다. 그래서
# 순간풍속이 10m/s를 넘어도 표시는 '정상'으로 남는 일이 생긴다 — 고가 전개 가부는
# 순간풍속이 좌우하므로 위험한 방향의 오표시다. 지도.html은 이미 순간풍속 >10/>8을
# 쓰고 있으니 상황실을 거기에 맞춘다(두 화면이 같은 값을 같은 단계로 말하게).
patch("      level: s.wind>=12 ? '운용 제한' : (s.wind>=8 ? '주의' : '정상'),\n"
      "      note: '순간풍속 '+s.gust+'m/s · 10m/s 초과 시 전개 제한',\n"
      "      color: s.wind>=12 ? '#ff5a5a' : (s.wind>=8 ? '#ffb020' : '#2ad19a'),\n"
      "      bg: s.wind>=12 ? 'rgba(255,77,77,.12)' : (s.wind>=8 ? 'rgba(255,176,32,.1)' : 'rgba(42,209,154,.08)') });",
      "      level: s.gust>10 ? '전개 제한' : (s.gust>8 ? '주의' : '정상'),\n"
      "      note: '순간풍속 '+s.gust+'m/s · 10m/s 초과 시 전개 제한',\n"
      "      color: s.gust>10 ? '#ff5a5a' : (s.gust>8 ? '#ffb020' : '#2ad19a'),\n"
      "      bg: s.gust>10 ? 'rgba(255,77,77,.12)' : (s.gust>8 ? 'rgba(255,176,32,.1)' : 'rgba(42,209,154,.08)') });",
      '사다리차 판정 → 순간풍속(지도와 통일)')

# (j7) 재난문자 — 비 오는 관서에 '가짜 호우 문자'가 뜨던 것 차단 ★중요
# 원본 디자인은 s.wet(강수 중)이면 실제 데이터를 아예 안 보고 문구를 지어냈다:
#   "○○시 · 호우주의보 발효. 하천변·지하공간·지하주차장 접근을 금지하고…"
#   "경기도 · 시간당 N mm의 강한 비가 내리고 있습니다…[경기도청]"
# 디자인 시안에선 그림용이지만 운영 화면에선 '있지도 않은 특보'를 사실처럼 띄운다.
# 2026-08-15 실제로 발생 — 기상청엔 경기북부 호우특보가 0건인데 동두천 화면에
# "호우주의보 발효" 문자가 떠서 사장님이 실제 상황으로 오인할 뻔했다.
# (문자 없는 관서에 샘플이 뜨던 문제는 앞서 msgs 빈 배열로 막았지만, 이 분기는
#  EXT().msgs를 아예 거치지 않아 그 방어를 그냥 통과했다.)
# → 강수 여부와 무관하게 항상 실제 재난문자만 쓴다. 없으면 안 띄운다.
patch("""    let msgs;
    if (s.wet){""",
      """    let msgs;
    if (false){   /* 가짜 호우문자 분기 봉인 — 아래 실데이터 경로만 쓴다 */""",
      '재난문자 → 실데이터만 (가짜 호우문자 차단)')

# 종류(호우·강풍 등)에 따라 색을 준다. 원본 else 분기는 전부 주황 고정이라
# 호우 문자도 폭염과 같은 색으로 보였다. 종류는 update_data.py가 안 주므로 본문에서 뽑는다.
patch("""      msgs = ((EXT().msgs || MSGS)[s.name] || MSGS['기본']).map(m=>({ sender:m[0], kind:m[1], time:m[2], text:m[3],
        color:'#ff9a3c', bg:'rgba(255,154,60,.12)' }));""",
      """      msgs = ((EXT().msgs || MSGS)[s.name] || MSGS['기본']).map(function(m){
        var _t = String(m[3]||''), _k = m[1] || '';
        if(!_k){ var _kw=['호우','침수','태풍','대설','한파','폭염','강풍','산불','화재','지진','실종','교통','대피','미세먼지','해일','홍수'];
                 for(var _i=0;_i<_kw.length;_i++){ if(_t.indexOf(_kw[_i])>=0){ _k=_kw[_i]; break; } } }
        var _c = (_k==='호우'||_k==='침수'||_k==='홍수'||_k==='해일'||_k==='태풍') ? ['#54aaff','rgba(84,170,255,.12)']
               : (_k==='강풍'||_k==='대설'||_k==='한파') ? ['#ffb020','rgba(255,176,32,.12)']
               : ['#ff9a3c','rgba(255,154,60,.12)'];
        return { sender:m[0], kind:_k, time:m[2], text:_t, color:_c[0], bg:_c[1] };
      });""",
      '재난문자 종류별 색 (호우=파랑, 강풍=주황)')

# ── (j8) 풍향 — 난수를 실측값으로 ★중요 ──────────────────────────────
# 원본 디자인은 풍향을 관서번호 기반 의사난수(r3)로 만들었다. 풍속·순간풍속은 실측인데
# 풍향만 지어낸 값이라, 벽면의 화살표와 '남서' 같은 방위 글자가 실제와 무관했다.
# 실제 풍향은 데이터에 이미 있었다(AWS wds, 기상청 실황 vec) — 안 쓰고 있었을 뿐이다.
# 위 stations에 wdeg를 실어 보내고(st() 패치), 값이 없을 땐 '—'로 비운다.
# 주의: windDeg가 null일 때 원본 계산식 (null+22.5)%360/45 → 0 → '북'이 되어
#       '자료 없음'이 '북풍'으로 둔갑한다. 그래서 세 곳 모두 null을 먼저 걸러야 한다.
patch("      windDir: ['북','북동','동','남동','남','남서','서','북서']"
      "[Math.floor(((s.windDeg+22.5)%360)/45)], windDeg: s.windDeg,",
      "      windDir: (s.windDeg==null ? '—' : ['북','북동','동','남동','남','남서','서','북서']"
      "[Math.floor(((s.windDeg+22.5)%360)/45)]), windDeg: (s.windDeg==null ? 0 : s.windDeg),\n"
      "      windArrow: (s.windDeg==null ? '' : '↑'),",
      '풍향 방위글자 → 실값·자료없으면 —')

patch('<div style="font-size:52px;line-height:1;color:var(--acc,#ff7a2f);'
      'transform:rotate({{ windDeg }}deg);">↑</div>',
      '<div style="font-size:52px;line-height:1;color:var(--acc,#ff7a2f);'
      'transform:rotate({{ windDeg }}deg);">{{ windArrow }}</div>',
      '풍향 화살표 → 자료 없으면 숨김')

patch("      note:'실효습도 '+s.effHum+'% · 풍속 '+s.wind+'m/s · 풍향 '"
      "+['북','북동','동','남동','남','남서','서','북서'][Math.floor(((s.windDeg+22.5)%360)/45)],",
      "      note:'실효습도 '+s.effHum+'% · 풍속 '+s.wind+'m/s · 풍향 '"
      "+(s.windDeg==null ? '—' : ['북','북동','동','남동','남','남서','서','북서']"
      "[Math.floor(((s.windDeg+22.5)%360)/45)]),",
      '산불 설명줄 풍향 → 실값')

# ── (m) 하단 관서 레일 — 관서 수에 맞춰 칸·높이 자동 ──────────────────
# 원본은 'repeat(11,1fr)'에 높이 150px로 박혀 있다. 경기북부(11개)에 맞춘 값이라
# 경기남부(21개)에서는 21개가 11칸 그리드에 들어가 2줄이 되는데 높이는 그대로라
# 카드가 절반으로 눌린다(글자·온도가 뭉개짐).
#   · 12개 이하  → 한 줄, 관서 수만큼 칸
#   · 13개 이상  → 두 줄, 절반씩 (카드 크기가 북부와 같아진다)
# 늘어난 높이는 가운데 본문(flex:1)에서 가져오므로 다른 카드가 밀리지 않는다.
patch('<div style="height:150px;flex:none;display:grid;grid-template-columns:repeat(11,1fr);gap:14px;">',
      '<div style="{{ railStyle }}">',
      '관서 레일 → 관서 수에 맞춰 자동')

RAILVALS = '''    const _rn = NAMES.length;
    const _rcols = _rn <= 12 ? _rn : Math.ceil(_rn / 2);
    const _rrows = Math.ceil(_rn / _rcols);
    const _RAIL = 'height:' + (_rrows * 150 + (_rrows - 1) * 14) + 'px;flex:none;display:grid;'
                + 'grid-template-columns:repeat(' + _rcols + ',1fr);gap:14px;';
'''
patch("    return {\n      stageRef: (this.stageRef = this.stageRef || React.createRef()),",
      RAILVALS + "    return {\n      stageRef: (this.stageRef = this.stageRef || React.createRef()),\n"
      "      railStyle: _RAIL,",
      '관서 레일 크기 계산')

# ── (m2) 관서 레일에 강수량 얹기 ★사장님 요청(2026-08-17) ─────────────────
# 사장님: "어느 관서가 지금 제일 많이 맞고 있나"가 벽면에 없다.
# 지금은 관서가 15초마다 돌아 11곳을 다 보려면 2분 45초가 걸린다 — 호우 때 너무 길다.
#
# 카드를 하나 더 만들거나 자동 전환(스와이프)을 넣는 대신 '늘 떠 있는' 하단 레일에
# 한 줄을 얹었다. 전환 타이머를 늘리면 관서 순환(15초)과 겹쳐서 '지금 뭘 보는지'가
# 헷갈리고, 급할 때 보고 싶은 조합을 언제 볼지 모르게 된다 — 벽면에선 치명적이다.
# 레일은 항상 11곳이 동시에 보이므로 비교가 즉시 된다.
#
# 무슨 값인가 — 시간당(rn60)과 일누적(rnday). 12시간 누적은 이미 '현재 실황' 카드에
# 있어 뺐고, 일누적은 지금까지 어느 화면에도 없던 값이다.
# 비가 없는 관서는 '—'로 조용히 두고, 오는 곳만 파랗게 띄워 한눈에 잡히게 한다.

# (m2-1) stAt 반환에 일누적 싣기 (레일이 stAt 결과를 쓴다)
patch('rain1h, sky:SKY[skyIdx],',
      'rain1h, rday:((g && g.rday != null) ? g.rday : 0), sky:SKY[skyIdx],',
      'stAt → 일누적')

# (m2-2) 레일 값 계산 — dc-runtime의 {{ }}에는 삼항연산자를 못 쓰므로 여기서 다 만든다
patch("      return { name:n, temp:ss.temp.toFixed(1), "
      "tag: ws.length ? ws[0].type.replace(/경보|주의보/,'') : '평상',",
      "      const _r1 = ss.rain1h || 0, _rd = ss.rday || 0, _wetR = (_r1 > 0 || _rd > 0);\n"
      "      /* 칸이 좁으면(경기 전체 31개 = 16칸, 한 칸 220px) 긴 문구가 잘린다.\n"
      "         잘린 숫자는 '무엇의 값인지' 모르게 되어 위험하므로, 좁을 땐 누적 하나만\n"
      "         이름표를 붙여 보여준다. 넓을 땐(11·21개 = 326px) 둘 다 보여준다. */\n"
      "      const _narrow = NAMES.length > 22;\n"
      "      return { name:n, temp:ss.temp.toFixed(1), "
      "tag: ws.length ? ws[0].type.replace(/경보|주의보/,'') : '평상',\n"
      "        rainTxt: _wetR ? (_narrow ? ('일 ' + _rd.toFixed(1) + 'mm')\n"
      "               : ('시간당 ' + _r1.toFixed(1) + ' · 일 ' + _rd.toFixed(1) + 'mm')) : '—',\n"
      "        rainColor: cur ? '#12161d' : (_wetR ? '#54aaff' : 'var(--dim,#8e9bb0)'),\n"
      "        rainWeight: _wetR ? 800 : 600,\n"
      "        rainOpacity: _wetR ? 1 : 0.35,",
      '레일 값 → 강수량')

# (m2-3) 레일 칸 마크업 — 세 번째 줄 추가.
# 칸 높이는 150px 고정이라 여백·기온을 조금 줄여 자리를 만든다
# (안쪽 높이 118 → 126px: 관서명 40 + 기온 44 + 강수 26 + gap 12).
patch('style="cursor:pointer;border-radius:18px;padding:16px 18px;display:flex;'
      'flex-direction:column;justify-content:center;gap:6px;',
      'style="cursor:pointer;border-radius:18px;padding:12px 18px;display:flex;'
      'flex-direction:column;justify-content:center;gap:5px;',
      '레일 칸 여백 축소(강수 줄 자리)')
patch('<div style="font-size:50px;font-weight:800;line-height:1;font-variant-numeric:tabular-nums;'
      'color:{{ s.fg }};">{{ s.temp }}°</div>',
      '<div style="font-size:44px;font-weight:800;line-height:1;font-variant-numeric:tabular-nums;'
      'color:{{ s.fg }};">{{ s.temp }}°</div>',
      '레일 기온 50 → 44px')
patch('            <div style="font-size:28px;font-weight:600;color:{{ s.sub }};white-space:nowrap;'
      'overflow:hidden;text-overflow:ellipsis;">{{ s.tag }}</div>\n'
      '          </div>\n'
      '        </div>',
      '            <div style="font-size:28px;font-weight:600;color:{{ s.sub }};white-space:nowrap;'
      'overflow:hidden;text-overflow:ellipsis;">{{ s.tag }}</div>\n'
      '          </div>\n'
      '          <div style="font-size:25px;font-weight:{{ s.rainWeight }};color:{{ s.rainColor }};'
      'opacity:{{ s.rainOpacity }};white-space:nowrap;overflow:hidden;text-overflow:ellipsis;'
      'line-height:1;">{{ s.rainTxt }}</div>\n'
      '        </div>',
      '레일에 강수량 줄 추가')

# (m3) 순환 주기를 관서 수에 맞춘다
# 15초 고정이라 경기 전체(31개)에서는 한 바퀴가 7분 45초다 — 벽면에서 특정 시군을
# 다시 보려면 8분을 기다려야 한다는 뜻이라 쓸 수가 없다. 한 바퀴를 3분 안쪽으로
# 맞추되, 사람이 읽을 수 있는 최소 시간(6초)은 지킨다.
#   11개 → 15초(한 바퀴 2분 45초) · 21개 → 8초(2분 48초) · 31개 → 6초(3분 6초)
#
# ⚠ 고칠 곳이 두 군데다 — 실제 타이머와 화면에 적히는 '순환 N초'. 하나만 고치면
#   '15초'라고 써 놓고 6초마다 넘어가는(또는 그 반대) 화면이 된다.
# ⚠ props.rotateSeconds 에는 디자인 편집기 기본값 15가 늘 들어 있어서 `|| 계산식`
#   폴백이 절대 안 걸린다(실제로 그렇게 만들었다가 31개에서 15초가 그대로 나왔다).
#   그래서 props 를 보지 않고 관서 수로 바로 계산한다.
ROT = 'Math.max(6, Math.min(15, Math.round(170 / Math.max(1, NAMES.length))))'
patch('      const rot = (this.props.rotateSeconds || 15) * 1000;',
      '      const rot = (' + ROT + ') * 1000;',
      '순환 타이머 → 관서 수에 맞춰 자동')
patch('    const rotSec = this.props.rotateSeconds || 15;',
      '    const rotSec = ' + ROT + ';',
      '순환 표시 → 관서 수에 맞춰 자동')

# ── (k) 상단바에 '임진강 감시' 카드 ─────────────────────────────────────
# 필승교·군남댐은 관서 순환과 무관하게 늘 봐야 하는 지점이다(필승교는 북측 황강댐
# 무단방류를 가장 먼저 잡는 상류 지점, 군남댐 방류량은 곧 하류 임진강 수위).
# 지금은 연천 차례가 돌아올 때만 보인다 → 상단바에 고정 카드로 올린다.
#
# 자리는 관서명 칸(1120px)과 날씨 칸의 남는 폭에서 만든다. 무대 안쪽 폭 3728px 기준
#   기존:  1120 | 1fr(1400) | 460 | 640
#   변경:   700 | 1fr(924)  | 860 | 460 | 640      (gap 36 × 4 = 144)
# 어느 지점을 띄울지는 region.js(topRivers)가 정한다. 비어 있으면(경기남부) 카드가
# 빠지고 4칸으로 돌아간다 — 그래서 grid 정의를 renderVals에서 만들어 넣는다.

# (k1) 상단바 그리드를 동적으로
patch('<div style="height:290px;flex:none;display:grid;grid-template-columns:1120px 1fr auto auto;gap:36px;align-items:stretch;">',
      '<div style="{{ topBarStyle }}">',
      '상단바 그리드 → 동적(지역별 칸 수)')

# (k2) 관서명 카드 축소 — 칸이 좁아졌으니 글자도 줄여야 넘치지 않는다(nowrap이라 잘림)
patch('<div style="font-size:150px;font-weight:800;line-height:.95;letter-spacing:-.03em;white-space:nowrap;">{{ stationName }}</div>',
      '<div style="font-size:118px;font-weight:800;line-height:.95;letter-spacing:-.03em;white-space:nowrap;">{{ stationName }}</div>',
      '관서명 150 → 118px')
patch('<div style="font-size:46px;font-weight:600;color:var(--dim,#8e9bb0);white-space:nowrap;">소방관서</div>',
      '<div style="font-size:38px;font-weight:600;color:var(--dim,#8e9bb0);white-space:nowrap;">소방관서</div>',
      "'소방관서' 46 → 38px")

# (k3) 날씨 카드 축소
patch('<div style="display:flex;align-items:center;gap:44px;background:var(--panel,#151b26);border:2px solid var(--line,#28313f);border-radius:24px;padding:0 48px;min-width:0;">\n'
      '        <div style="font-size:112px;line-height:1;flex:none;">{{ icon }}</div>',
      '<div style="display:flex;align-items:center;gap:36px;background:var(--panel,#151b26);border:2px solid var(--line,#28313f);border-radius:24px;padding:0 36px;min-width:0;">\n'
      '        <div style="font-size:92px;line-height:1;flex:none;">{{ icon }}</div>',
      '날씨 카드 여백·아이콘 축소')
patch('<div style="font-size:170px;font-weight:800;line-height:.9;letter-spacing:-.04em;font-variant-numeric:tabular-nums;">{{ temp }}</div>',
      '<div style="font-size:140px;font-weight:800;line-height:.9;letter-spacing:-.04em;font-variant-numeric:tabular-nums;">{{ temp }}</div>',
      '기온 170 → 140px')
patch('<div style="font-size:80px;font-weight:600;color:var(--dim,#8e9bb0);line-height:1;">°C</div>',
      '<div style="font-size:66px;font-weight:600;color:var(--dim,#8e9bb0);line-height:1;">°C</div>',
      "'°C' 80 → 66px")

# (k4) 새 카드 마크업 — 날씨 카드 바로 뒤(상황단계 앞)
#  ⚠ sc-if / sc-for 는 '태그'로 써야 하고, {{ }} 안에 함수·삼항은 못 쓴다.
#     그래서 표시할 글자는 전부 renderVals에서 미리 만들어 넣는다.
#  ⚠ sc-for 중첩은 쓰지 않는다(동작 보장 안 됨) → 값 3칸을 l1/v1 … l3/v3 로 펼쳐 둔다.
KEYCARD = '''
      <sc-if value="{{ hasKeyRivers }}" hint-placeholder-val="{{true}}">
      <div style="display:flex;align-items:center;gap:26px;background:var(--panel,#151b26);border:2px solid var(--line,#28313f);border-radius:24px;padding:0 30px;min-width:0;">
        <div style="width:14px;align-self:stretch;margin:34px 0;border-radius:8px;background:{{ keyAccent }};flex:none;"></div>
        <div style="display:flex;flex-direction:column;gap:12px;min-width:0;flex:1;">
          <div style="font-size:32px;font-weight:700;letter-spacing:.06em;color:var(--dim,#8e9bb0);white-space:nowrap;">{{ keyTitle }}</div>
          <sc-for list="{{ keyRivers }}" as="k" hint-placeholder-count="2">
            <div style="display:flex;align-items:flex-end;gap:18px;">
              <div style="width:132px;flex:none;font-size:42px;font-weight:800;line-height:1.1;color:{{ k.color }};white-space:nowrap;">{{ k.name }}</div>
              <div style="flex:1;min-width:0;">
                <div style="font-size:26px;font-weight:600;color:var(--dim,#8e9bb0);white-space:nowrap;">{{ k.l1 }}</div>
                <div style="font-size:46px;font-weight:800;line-height:1.05;color:{{ k.color }};font-variant-numeric:tabular-nums;white-space:nowrap;">{{ k.v1 }}</div>
              </div>
              <div style="flex:1;min-width:0;">
                <div style="font-size:26px;font-weight:600;color:var(--dim,#8e9bb0);white-space:nowrap;">{{ k.l2 }}</div>
                <div style="font-size:46px;font-weight:800;line-height:1.05;color:var(--fg,#f2f5fa);font-variant-numeric:tabular-nums;white-space:nowrap;">{{ k.v2 }}</div>
              </div>
              <div style="flex:1;min-width:0;">
                <div style="font-size:26px;font-weight:600;color:var(--dim,#8e9bb0);white-space:nowrap;">{{ k.l3 }}</div>
                <div style="font-size:46px;font-weight:800;line-height:1.05;color:var(--fg,#f2f5fa);font-variant-numeric:tabular-nums;white-space:nowrap;">{{ k.v3 }}</div>
              </div>
            </div>
          </sc-for>
        </div>
      </div>
      </sc-if>
'''
patch('      <div style="width:460px;border-radius:24px;padding:24px 32px;',
      KEYCARD + '\n      <div style="width:460px;border-radius:24px;padding:24px 32px;',
      '임진강 감시 카드 삽입')

# (k5) renderVals — 카드에 넣을 값 계산
#   · 표시명은 앞의 시군명을 뗀다('연천 필승교' → '필승교').
#   · 결측은 0이 아니라 '-'. 호우 때 '자료 없음'을 '0'으로 보여주면 가장 위험하다.
#   · 색은 하천 카드와 같은 규칙(정상 초록 / 주의보 노랑 / 위험 빨강).
KEYVALS = '''    const _RC = (typeof window!=='undefined' && window.REGION_CONF) || {};
    const _kraw = (EXT().keyRivers) || [];
    const _kf = (v,d) => (v==null ? '-' : (+v).toFixed(d==null?1:d));
    const _kcol = lv => (lv==='danger' ? '#ff5a5a' : (lv==='warning' ? '#ffb020' : '#2ad19a'));
    const keyRivers = _kraw.map(k => {
      const col = _kcol(k.level);
      if (k.isDam) {
        return { name:k.name, color:col,
          l1:'저수위', v1:_kf(k.value,2)+'m',
          l2:'저수율', v2:(k.rate==null ? '-' : _kf(k.rate,1)+'%'),
          l3:'방류',   v3:(k.outflow==null ? '-' : _kf(k.outflow,1)+'㎥/s') };
      }
      const d1 = k.d1;
      return { name:k.name, color:col,
        l1:'수위',   v1:_kf(k.value,2)+'m',
        l2:'1시간',  v2:(d1==null ? '-' : (d1>0?'▲ +':(d1<0?'▼ ':'– ')) + Math.abs(d1).toFixed(2)+'m'),
        l3:'관심수위', v3:(k.warn==null ? '-' : _kf(k.warn,1)+'m') };
    });
    const _kworst = _kraw.some(k=>k.level==='danger') ? 'danger'
                  : (_kraw.some(k=>k.level==='warning') ? 'warning' : 'safe');
    const _TOPBAR = 'height:290px;flex:none;display:grid;gap:36px;align-items:stretch;grid-template-columns:'
      + (keyRivers.length ? '700px 1fr 860px auto auto' : '700px 1fr auto auto');
'''
patch("    return {\n      stageRef: (this.stageRef = this.stageRef || React.createRef()),",
      KEYVALS + "    return {\n      stageRef: (this.stageRef = this.stageRef || React.createRef()),\n"
      "      keyRivers, hasKeyRivers: keyRivers.length > 0, topBarStyle: _TOPBAR,\n"
      "      keyTitle: (_RC.topRiversTitle || '주요 감시'),\n"
      "      keyAccent: (_kworst==='safe' ? (this.props.accent||'#ff7a2f') : _kcol(_kworst)),",
      '상단바 감시카드 값 계산')

# 5) </body> 앞에 데이터 로더 + 변환기 주입
INJECT = r'''
<script src="./risk-zones.js"></script>
<script src="https://gyeonggi-dashboard.visanu81.workers.dev/data.js"></script>
<script>
/* DASHBOARD_DATA(우리 실시간) → WALL_DATA(디자인 형식) 변환·주입.
   stations·rivers·msgs·warns = data.js(5분 갱신), risks = 구글시트 관서별 탭(30분). */
(function(){
  /* 관서 목록·행정명은 region.js(window.REGION_CONF)에서. 지역이 바뀌면 그 파일만 갈아끼운다.
     region.js가 없으면 지금까지 쓰던 경기북부 값으로 동작한다(하위호환). */
  var RC=(typeof window!=='undefined'&&window.REGION_CONF)||{};
  var NAMES=RC.order||['고양','일산','파주','연천','의정부','양주','동두천','포천','가평','남양주','구리'];
  var ADMIN=RC.admin||{고양:'고양시',파주:'파주시',연천:'연천군',의정부:'의정부시',양주:'양주시',동두천:'동두천시',포천:'포천시',가평:'가평군',남양주:'남양주시',구리:'구리시'};
  /* SIG = 실제 시군(일산은 고양의 일부라 제외). 하천 표시명에서 '괄호 안이 시군인지' 판정용. */
  /* 관서명 → 데이터상의 시군명. 소방서가 시(市)를 나눠 맡는 곳(분당·송탄·일산)은
     기상청 자료가 시군 단위로만 나오므로 소속 시군 값을 본다.
     ⚠ 예전엔 '일산'만 하드코딩돼 있었다. 경기 전체(34관서)를 붙이면서 분당·송탄이
       소속 시군을 못 찾아 기온 0.0°·특보 '평상'으로 떴다 — region.js 의 alias 를
       읽도록 바꿔, 관서가 늘어도 코드를 안 고치게 했다. */
  var ALIAS=((typeof window!=='undefined'&&window.REGION_CONF)||{}).alias||{'일산':'고양'};
  var SIG=NAMES.filter(function(n){ return !ALIAS[n]; });
  function nv(x){ return (x==null||x===''||isNaN(x))?null:+x; }
  function sig(nm){ return ALIAS[nm]||nm; }
  /* 표시명: 괄호 안(예 '임진강 (연천 임진교)'→'연천 임진교'). 단 괄호가 시군뿐이면
     지점 구분이 안 되니 하천명을 붙인다('신천 (연천)'→'연천 신천'). */
  function shortRiver(nm){ var s=String(nm||''), m=s.match(/^\s*([^(]+?)\s*\(([^)]+)\)/);
    if(!m) return s;
    var head=m[1].trim(), inner=m[2].trim();
    if(SIG.indexOf(inner)>=0) return inner+' '+head;
    return inner; }
  /* 상단바 감시카드용 짧은 이름 — '임진강 (연천 필승교)' → '필승교'.
     칸이 좁아 시군명까지 넣으면 넘친다. 어차피 고정 지점이라 어디인지 다 안다. */
  function keyName(nm){ var s=shortRiver(nm).split(' ');
    if(s.length>1 && SIG.indexOf(s[0])>=0) s.shift();
    return s.join(' '); }
  var ICON={'맑음':'☀️','구름많음':'⛅','구름조금':'🌤️','흐림':'☁️','비':'🌧️','소나기':'🌦️','빗방울':'🌧️','비/눈':'🌨️','눈':'❄️','눈날림':'🌨️','진눈깨비':'🌨️','뇌우':'⛈️'};
  function wicon(w){ return ICON[w]||'☁️'; }
  /* 날씨문자 → 통일 SVG 아이콘 타입(메테오그램 wxSvg). 밤(19~06시)엔 해→달 */
  function wxType(w,hourStr){ w=String(w||''); var hh=parseInt(hourStr,10), night=!isNaN(hh)&&(hh<6||hh>=19);
    if(/뇌우|번개|천둥/.test(w)) return 'storm';
    if(/눈|진눈깨비/.test(w)) return 'snow';
    if(/비|소나기|빗방울/.test(w)) return 'rain';
    if(/흐림/.test(w)) return 'cloud';
    if(/구름/.test(w)) return night?'cloudmoon':'cloudsun';
    if(/맑/.test(w)) return night?'moon':'sun';
    return 'cloud'; }
  /* 지도.html _canonRegion 동일 — 특보구역명 → 관서 정규화 */
  function canon(name){ var n=String(name||'').trim(); if(!n) return null;
    if(n==='경기북부'||n==='경기남부'||n==='경기도'||n==='수도권'||n==='경기') return '경기도';
    n=n.replace(/(동북부|서북부|동남부|서남부|남부|북부|동부|서부|중부|내륙|산지|앞바다|해안)/g,'');
    n=n.replace(/(특별자치시|특별자치도|특별시|광역시|자치시|자치도)/g,'');
    n=n.replace(/(시|군|구|도)$/,''); return n.trim()||null; }
  /* 특보 종류 → 색/배경/심각도(sev). 급성경보=3(심각·빨강), 급성주의보=2(경계·주황),
     만성(폭염/한파/건조/황사)=1(주의) — 상황실 24h 빨강맥동 방지. 디자인 팔레트와 동일. */
  function warnStyle(type){ type=String(type||'');
    var isBo=type.indexOf('경보')>=0, chronic=/폭염|한파|건조|황사|오존/.test(type);
    var sev=chronic?1:(isBo?3:2), color, bg;
    if(isBo){ color='#ff5a5a'; bg='rgba(255,77,77,.14)'; }
    else if(chronic){ color='#ffb020'; bg='rgba(255,176,32,.14)'; }
    else { color='#ff9a3c'; bg='rgba(255,154,60,.14)'; }
    return {sev:sev,color:color,bg:bg}; }
  /* 실제 발효특보 → 관서별. 지도.html mapRegions 매칭과 동일(경기도=전역). */
  function warnsByStation(warnings){
    var out={}; NAMES.forEach(function(nm){ out[nm]=[]; });
    (warnings||[]).forEach(function(w){
      var st=warnStyle(w.type), spec={}, province=false;
      String(w.area||'').split(/[,·\/]/).forEach(function(a){ var n=canon(a); if(!n) return;
        if(n==='경기도'){ province=true; }                                    /* '경기도'는 헤더일 수 있어 보류(개별 시군 있으면 무시) */
        else NAMES.forEach(function(nm){ if(sig(nm)===n||nm===n) spec[nm]=1; }); });
      var tgt=spec;
      if(!Object.keys(spec).length && province) NAMES.forEach(function(nm){ tgt[nm]=1; });  /* 개별 시군 없이 '경기도'만 → 전역 발효 */
      Object.keys(tgt).forEach(function(nm){ out[nm].push({type:w.type,area:w.area||'',time:(w.time?w.time+' 발효':''),color:st.color,bg:st.bg,sev:st.sev}); });
    });
    NAMES.forEach(function(nm){ var seen={},arr=[]; out[nm].sort(function(a,b){return b.sev-a.sev;}).forEach(function(x){ if(!seen[x.type]){seen[x.type]=1;arr.push(x);} }); out[nm]=arr; });
    return out;
  }
  function build(D){
    if(!D||!D.regions) return null;
    var byName={}; (D.regions||[]).forEach(function(r){ byName[r.name]=r; });
    var aws=D.aws||{}, pmBy={}; (D.pm||[]).forEach(function(p){ pmBy[p.region]=p; });
    var stations=NAMES.map(function(nm){
      /* 일산은 regions에 없다 → 지역기상은 '고양'. 단 AWS/미세먼지는 일산 고유 키. */
      var r=byName[sig(nm)]||{}, a=aws[nm]||{}, w=a.wind||{}, pm=pmBy[sig(nm)]||{}, det=r.detail||{};
      var hrs=((det.hourly)||[]).slice(0,12).map(function(o,k){   /* 실제 시간대별 예보 → 시간대별 표 */
        return { label:(k===0?'지금':(o.hour||'')), t:nv(o.temp), feels:nv(o.feels_like),
          rain:nv(o.rain_mm), pop:nv(o.rain_pop), icon:(o.icon||wicon(o.weather)), wx:wxType(o.weather,o.hour),
          /* 대시보드(지도.html)의 시간대별 표와 같은 항목을 쓰려고 바람·습도를 추가.
             셋 다 예보에 원래 들어 있던 값인데 벽면에선 안 쓰고 있었다. */
          wind:nv(o.wind_ms), deg:nv(o.wind_deg), dir:(o.wind_dir||''), humid:nv(o.humid) };
      });
      return { temp:nv(r.temp), humid:nv(r.humid), wind:nv(w.ws10!=null?w.ws10:r.wind), gust:nv(w.wss),
        /* 풍향(도) — 풍속과 같은 AWS 지점의 실측(wds)을 쓰고, 없으면 기상청 실황(vec).
           둘 다 없으면 null → 화면에 '—'. 예전엔 이 값이 아예 없어서 벽면이 관서번호로
           만든 난수를 풍향으로 띄웠다(2026-08-17 점검에서 발견). */
        wdeg:nv(w.wds!=null?w.wds:r.vec),
        rain:nv(a.rn60!=null?a.rn60:r.rain), pm10:nv(pm.pm10),
        /* 일누적 강수 — 하단 관서 레일에서 '어디가 제일 많이 맞았나'를 비교하는 값.
           1시간(rain)은 '지금 오나', 일누적은 '얼마나 쌓였나'를 말한다. 일누적은
           지금까지 어느 화면에도 없었다(실황 카드는 1·3·6·12시간만). 2026-08-17 추가. */
        rday:nv(a.rnday),
        feels:nv(det.feels_like!=null?det.feels_like:r.feels), eff:nv(r.effHumid),
        hourly:(hrs.length?hrs:null) };
    });
    /* 하천 → 관서. sigun 없으면 이름에서 시군 추출(가장 긴 매칭 우선: '남양주'가 '양주'보다 먼저).
       전 관서를 []로 초기화 → 하천 없는 관서(예:구리)에 남의 하천 샘플이 뜨는 폴백 차단. */
    var rivers={}; NAMES.forEach(function(nm){ rivers[nm]=[]; });
    /* 관서별 하천코드 표(region.js riverCodes)가 있으면 시군 배분보다 우선한다.
       소방서가 시를 나눠 맡는 곳에서 남의 하천이 '관할'로 뜨는 것을 막는다. */
    var RCODE=((typeof window!=='undefined'&&window.REGION_CONF)||{}).riverCodes||{};
    (D.rivers||[]).forEach(function(rv){
      var sg=rv.sigun;
      /* 코드로 지정된 관서에 먼저 넣는다. 지정 관서가 하나라도 있으면 시군 배분은 건너뛴다. */
      var _placed=false;
      NAMES.forEach(function(nm){ var cs=RCODE[nm];
        if(cs && cs.indexOf(String(rv.code))>=0){ rivers[nm].push(rv); _placed=true; } });
      if(_placed) return;
      if(RCODE[sg]) return;   /* 그 시군은 코드로만 받는다 — 남의 하천이 섞이지 않게 */
      if(!sg){ var best=''; SIG.forEach(function(x){ if(String(rv.name||'').indexOf(x)>=0 && x.length>best.length) best=x; }); sg=best; }
      if(!sg) return;
      /* 댐 = api:'dam'(원천 플래그). 댐은 '위험수위 대비 %'가 무의미(상시만수위 유지가 정상)라
         화면에서 저수율·유입·방류로 따로 표기하고, 침수판단(worst)에서는 제외한다. */
      var isDam=(rv.api==='dam')||!!rv.dam_info, di=rv.dam_info||{};
      var entry=[shortRiver(rv.name), nv(rv.value), nv(rv.danger), (isDam?'dam':''), (rv.level||'safe'),
        nv(rv.delta_1h), nv(rv.warning), nv(di.storage_rate), nv(di.inflow),
        nv(di.total_outflow!=null?di.total_outflow:di.outflow)];
      NAMES.forEach(function(nm){ if(sig(nm)===sg && nm!=='일산') rivers[nm].push(entry); });  /* 시군 관서에만(일산 중복 방지) */
    });
    /* 정렬: 공식 경보 → 주의보 → 하천(위험수위 대비 높은 순) → 댐. 벽면 가독성 위해 최대 5행. */
    NAMES.forEach(function(nm){
      rivers[nm].sort(function(a,b){
        var rk=function(x){ return x[4]==='danger'?0:(x[4]==='warning'?1:(x[3]==='dam'?3:2)); };
        var d=rk(a)-rk(b); if(d) return d;
        return ((b[2]?b[1]/b[2]:0)-(a[2]?a[1]/a[2]:0));
      });
      rivers[nm]=rivers[nm].slice(0,5);
    });
    /* 재난문자 → 관서. 전 관서 키를 항상 설정(빈 []) → 문자 없는 관서에 디자인 샘플문자가 뜨는 폴백 차단. */
    var msgs={};
    NAMES.forEach(function(nm){ var sg=sig(nm);
      msgs[nm]=(D.messages||[]).filter(function(m){ return m.region===sg||m.region===nm||m.region==='경기도'; })
        .map(function(m){ return [m.sender||sg,'',m.time||'',m.text||'']; }).slice(0,4); });
    /* 상단바 '항상 띄울 관측소' — 관서 순환과 무관한 전역 목록.
       region.js의 topRivers(한강홍수통제소 관측소 코드)로 고른다. 이름이 아니라 코드로
       고르는 이유: 표기명이 바뀌어도 안 깨진다. 목록에 없는 코드는 조용히 빠진다
       (엉뚱한 지점을 대신 넣는 것보다 안 보이는 편이 안전). */
    var _want = RC.topRivers || [];
    var _byCode = {}; (D.rivers||[]).forEach(function(rv){ _byCode[String(rv.code)] = rv; });
    var keyRivers = _want.map(function(cd){
      var rv = _byCode[String(cd)]; if(!rv) return null;
      var di = rv.dam_info || {}, isDam = (rv.api==='dam') || !!rv.dam_info;
      return { name:keyName(rv.name), isDam:isDam, level:(rv.level||'safe'),
        value:nv(rv.value), d1:nv(rv.delta_1h), warn:nv(rv.warning), dang:nv(rv.danger),
        rate:nv(di.storage_rate), inflow:nv(di.inflow),
        outflow:nv(di.total_outflow!=null ? di.total_outflow : di.outflow) };
    }).filter(function(x){ return x; });

    /* 6시간 강수예측 — 관서별. ultra_fcst는 시군 키라 관서명을 sig()로 바꿔 찾는다
       (일산은 고양 값을 쓴다 — 지역기상이 같다). 없으면 빈 배열 → 화면에 '자료 없음'.
       2026-08-17 추가: 위험구역 카드 자리에 넣는다. 매 회차 수집하면서도 어느 화면에서도
       안 쓰던 유일한 데이터였다. */
    var ultra={};
    NAMES.forEach(function(nm){
      var a=(D.ultra_fcst||{})[sig(nm)]||[];
      ultra[nm]=a.slice(0,6).map(function(o){
        return { time:String(o.time||'').slice(0,5), rain:nv(o.rain_mm), pop:nv(o.pop),
                 pty:(o.pty_txt||''), lgt:(nv(o.lgt)||0)>0, temp:nv(o.temp) };
      });
    });
    return { stations:stations, rivers:rivers, msgs:msgs, warns:warnsByStation(D.warnings),
             keyRivers:keyRivers, ultra:ultra, updated:D.updated };
  }
  /* ── 위험구역: 구글시트 관서별 탭 (지도.html loadRiskSheet 포팅, name/type/note만) ── */
  function parseCSV(txt){ var lines=txt.replace(/\r/g,'').split('\n').filter(function(l){return l.length;});
    return lines.map(function(line){ var out=[],cur='',q=false; for(var i=0;i<line.length;i++){ var c=line[i];
      if(q){ if(c==='"'){ if(line[i+1]==='"'){cur+='"';i++;} else q=false; } else cur+=c; }
      else { if(c==='"') q=true; else if(c===','){ out.push(cur); cur=''; } else cur+=c; } } out.push(cur); return out; }); }
  function rowsFrom(txt, tabRegion){
    if(!txt || txt.charAt(0)==='<' || txt.indexOf('setResponse')>=0) return [];
    var rows=parseCSV(txt); if(rows.length<2) return [];
    var head=rows[0].map(function(x){return (x||'').trim();});
    var col=function(n){ return head.findIndex(function(x){return x.indexOf(n)>=0;}); };
    var iReg=col('지역'),iType=col('유형');
    var iName=col('이름'); if(iName<0) iName=col('명칭'); if(iName<0) iName=col('주소');
    var iNote=col('설명'); if(iNote<0) iNote=col('주소');
    var res=[];
    for(var i=1;i<rows.length;i++){ var r=rows[i];
      var name=(r[iName]||'').trim(), type=(r[iType]||'').trim(), note=(r[iNote]||'').trim();
      if(!(type||name||note)) continue;                        /* 텅 빈(번호만) 행 제외 */
      var region=tabRegion;
      if(!region){ var cell=(r[iReg]||'').trim(); region=NAMES.find(function(nm){ return cell.indexOf(sig(nm))>=0; }); }
      if(!region) continue;
      if(note===name) note='';                                 /* 설명칸 비어 주소가 중복되면 비움 */
      if(!name && note) { name=note; note=''; }
      res.push([region, name, note, type]);
    }
    return res;
  }
  function loadRisks(){
    var base=window.RISK_SHEET_URL; if(!base) return;
    var sep=base.indexOf('?')>=0?'&':'?';
    var fetchTxt=function(url){ return fetch(url).then(function(r){return r.ok?r.text():'';}).catch(function(){return '';}); };
    var jobs=[]; SIG.forEach(function(sg){ var set=[sg]; if(ADMIN[sg]&&ADMIN[sg]!==sg) set.push(ADMIN[sg]);
      set.forEach(function(t){ jobs.push({region:sg,name:t}); }); });
    jobs.push({region:'일산',name:'일산'});
    Promise.all([fetchTxt(base)].concat(jobs.map(function(j){ return fetchTxt(base+sep+'sheet='+encodeURIComponent(j.name)).then(function(txt){return {region:j.region,txt:txt};}); }))).then(function(all){
      var defTxt=all[0]||'', items=rowsFrom(defTxt,''); var seen={}; if(defTxt) seen[defTxt]=1;   /* 첫 탭: 지역칸으로 구분 */
      all.slice(1).forEach(function(t){ if(t.txt && t.txt!==defTxt && !seen[t.txt]){ seen[t.txt]=1; items=items.concat(rowsFrom(t.txt, t.region)); } });  /* 없는 탭→첫 탭 반환·중복 방어 */
      var byStn={}; NAMES.forEach(function(nm){ byStn[nm]=[]; });
      items.forEach(function(it){ if(byStn[it[0]]) byStn[it[0]].push([it[1], it[2], it[3]]); });
      if(window.WALL_DATA) window.WALL_DATA.risks=byStn;
    }).catch(function(){});
  }
  function apply(D){ var w=build(D); if(!w) return;
    if(window.WALL_DATA && window.WALL_DATA.risks) w.risks=window.WALL_DATA.risks;   /* 로드된 위험구역 보존 */
    else { w.risks={}; NAMES.forEach(function(nm){ w.risks[nm]=[]; }); }             /* 초기: 샘플 대신 '없음' */
    window.WALL_DATA=w;
  }
  if(window.DASHBOARD_DATA) apply(window.DASHBOARD_DATA);
  loadRisks();
  setInterval(function(){
    fetch('https://gyeonggi-dashboard.visanu81.workers.dev/data.js?_t='+Date.now(),{cache:'no-store'})
      .then(function(r){return r.text();}).then(function(t){ var i=t.indexOf('{'),j=t.lastIndexOf('}'); if(i<0||j<0) return;
        try{ apply(JSON.parse(t.slice(i,j+1))); }catch(e){} }).catch(function(){});
  }, 300000);
  setInterval(loadRisks, 1800000);
})();
</script>
'''
h = h.replace('</body>', INJECT + '\n</body>', 1)

# ── 전역 후처리 ────────────────────────────────────────────
# (A) 글꼴 굵기 위계 — 원본이 전부 600~800이라 "다 두껍다"(사장님, 2차 요청으로 한 단계 더).
#     값 800→660, 제목 700→570, 라벨 600→520, 설명 500은 유지.
#     ⚠ 순서 의존: 800→660 먼저, 그 다음 700→570, 마지막 600→520. 새 값(660/570)이
#       다음 규칙의 대상(700/600)과 겹치지 않아 이중 치환이 없다.
#     ⚠ @font-face의 'font-weight: 45 920'(가변 범위)은 숫자 두 개라 매칭 안 됨(안전).
#     ⚠ 출동영향판단은 위에서 545/445/615로 따로 지정 — 이 목록에 없어 여기서 안 건드림.
_wc = {}
for _old, _new in ((800, 660), (700, 570), (600, 520)):
    _wc[_old] = len(re.findall(r'font-?[wW]eight:\s*%d' % _old, h))
    h = re.sub(r'(font-weight:\s*)%d\b' % _old, r'\g<1>%d' % _new, h)
    h = re.sub(r'(fontWeight:)%d\b' % _old, r'\g<1>%d' % _new, h)
print('굵기 리맵: 800→660 %d곳, 700→570 %d곳, 600→520 %d곳' % (_wc[800], _wc[700], _wc[600]))

# (B) 강조색 hex → 테마 변수(라이트모드 가독성). 전부 style 값으로만 쓰임(비교사용 0 확인).
#     SVG는 메테오그램뿐이고 색을 style로 지정해 var() 유효.
_cmap = {'#2ad19a':'--cGreen', '#ffb020':'--cAmber', '#ff9a3c':'--cOrange',
         '#ff5a5a':'--cRed', '#54aaff':'--cBlue', '#b7c4ff':'--cIndigo'}
for _hex, _var in _cmap.items():
    _n2 = h.count(_hex) - h.count('var(%s,%s)' % (_var, _hex))
    h = h.replace(_hex, '§%s§' % _var)                      # 임시 마커(자기재귀 방지)
    h = h.replace('§%s§' % _var, 'var(%s,%s)' % (_var, _hex))
    # var(--cX,var(--cX,#hex)) 중첩 정리(이미 var였던 자리)
    h = h.replace('var(%s,var(%s,%s))' % (_var, _var, _hex), 'var(%s,%s)' % (_var, _hex))
    print('색 변수화: %s → var(%s) %d곳' % (_hex, _var, _n2))

open(ROOT + '/상황실.html', 'w', encoding='utf-8').write(h)
print('상황실.html 저장:', len(h), '바이트')
print('남은 UUID:', len(re.findall(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', h)))
