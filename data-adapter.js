// ===== 데이터 어댑터 =====
// 운영 상황판의 window.DASHBOARD_DATA (data.js, Python이 5분마다 자동 생성)를
// 새 지도 디자인이 쓰는 window.DASH 포맷으로 변환한다.
// → data.js 는 그대로 두고(파이썬 갱신 스크립트 무수정), 이 어댑터만 얹으면 실시간 연동.
// window.adaptDashboard() 로 재호출 가능 (새 데이터 반영 시).
(function(){
  var ICON = {'맑음':'☀','구름많음':'⛅','구름조금':'🌤','흐림':'☁','비':'🌧','소나기':'🌦','빗방울':'🌧','비/눈':'🌨','눈':'❄','눈날림':'🌨','진눈깨비':'🌨','뇌우':'⛈'};
  function icon(w){ return ICON[w] || '☁'; }
  function round(v){ return (v!=null && !isNaN(v)) ? Math.round(v) : null; }

  window.adaptDashboard = function(){
    var SRC = (typeof window !== 'undefined') && window.DASHBOARD_DATA;
    if(!SRC || !SRC.regions){ return false; } // 실데이터 없으면 dashboard-data.js 폴백 사용

    var byName = {}; (SRC.regions||[]).forEach(function(r){ byName[r.name] = r; });
    // 관서 목록·별칭은 region.js에서. 지역이 바뀌면 그 파일만 갈아끼운다.
    // (경기북부는 고양시를 고양·일산 두 관서로 나눠 11개, 경기남부는 21개 시군)
    var RC = (window.REGION_CONF||{});
    var ORDER = RC.order || ['연천','파주','동두천','포천','양주','가평','일산','고양','의정부','남양주','구리'];
    var ALIAS = RC.alias || {'일산':'고양'};   // 관서명 → 데이터상의 시군명
    var stations = ORDER.map(function(nm){
      var src = byName[ALIAS[nm] || nm];
      if(!src) return { name:nm, sigun:nm, level:'normal' };
      var det = src.detail || {}, cum = det.rain_cumul || {};
      // 관서별 시간대별 예보 — 선택 관서 전환 시 그 관서 예보를 쓰기 위해 각 station에 포함
      var fc = ((det.hourly)||[]).map(function(h){
        return { hour:h.hour, icon:h.icon || icon(h.weather), weather:h.weather, temp:h.temp,
          feels:h.feels_like, rain:h.rain_mm, pop:h.rain_pop, wind:h.wind_ms, dir:h.wind_dir, deg:h.wind_deg, humid:h.humid };
      });
      return {
        name: nm, sigun: (ALIAS[nm] || nm),
        temp: src.temp, weather: src.weather, icon: icon(src.weather),
        rain: src.rain, wind: src.wind, humid: src.humid, effHumid: src.effHumid,
        feels: round(det.feels_like),
        cum1h: cum['1h']||0, cum3h: cum['3h']||0, cum6h: cum['6h']||0, cum12h: cum['12h']||0,
        // AWS 실측(기상청 공식 누적) — 자체누적(cum*)보다 신뢰도가 높다.
        //  · 실측 격차 예: 남양주 12시간 자체 10.0mm vs AWS 27.0mm. 자체누적은 서버가 멈춘
        //    시간을 0으로 빼먹어 '실제보다 적게' 나온다 → 호우에서 가장 나쁜 방향.
        //  · 반드시 최상위 SRC.aws[nm]를 먼저 본다. det는 일산일 때 '고양'의 detail이라
        //    det.aws를 먼저 보면 일산이 영영 고양 값에 묶인다(SRC.aws에는 일산 키가 따로 있음).
        //  · 결측은 0이 아니라 null이다. rn60/rn12h가 null이면 '자료없음'으로 표시할 것.
        //  · ok:0 이면 그 관서 관측소가 전멸(rn* 키 자체가 없음), alt가 있으면 대체 관서 표기 필수.
        aws: (SRC.aws && SRC.aws[nm]) || det.aws || {},
        // 6시간 강수예측(초단기예보) — 1~6시간 앞. 없으면 빈 배열.
        fcst6: (SRC.ultra_fcst && SRC.ultra_fcst[ALIAS[nm] || nm]) || [],
        obs: det.observation || {}, windDir: det.wind_dir_name || '',
        pop: src.pop, tmax: src.tmax, tmin: src.tmin, level: src.level || 'normal',
        forecast: fc
      };
    });

    var rivers = (SRC.rivers||[]).map(function(r){
      var hist = (r.history||[]).map(function(h){ return +h.value; }).filter(function(v){ return !isNaN(v); });
      // 시각 포함 이력 (최고수위 시각·시간축 표시용) — 값만 뽑던 history와 별도 보존
      var histRaw = (r.history||[]).map(function(h){ return { t: String(h.time||''), v: +h.value }; }).filter(function(o){ return !isNaN(o.v); });
      return {
        name: r.name, code: r.code, sigun: r.sigun || '', value: r.value, warning: r.warning, danger: r.danger,
        level: r.level, delta1: r.delta_1h, delta3: r.delta_3h, cctv: !!r.has_cctv,
        dam: r.dam_info || null,
        history: hist.length>24 ? hist.slice(-24) : hist,
        histRaw: histRaw.length>24 ? histRaw.slice(-24) : histRaw,
        pct: (r.danger ? r.value / r.danger : 0)
      };
    });

    var warnings = (SRC.warnings||[]).map(function(w){
      return {
        type: w.type || w.title || w.name || '특보',
        area: w.area || w.region || w.regions || '',
        level: w.level || (String(w.type||'').indexOf('경보')>=0 ? 'severe' : 'warning'),
        time: w.time || w.announced || w.eff_time || ''
      };
    });

    var prelim = (SRC.prelim_warnings||[]).map(function(p){
      return {
        type: p.type, total: p.total_count, north: p.north_count,
        items: (p.items||[]).slice(0,8).map(function(i){ return { time:i.time, area:i.area, north:!!i.north_match }; })
      };
    });

    // 시간대별 예보: 관할(동두천) 우선, 없으면 의정부
    var focusReg = byName['동두천'] || byName['의정부'] || (SRC.regions||[])[0] || {};
    var hourly = (focusReg.detail && focusReg.detail.hourly) || [];
    var forecast = hourly.map(function(h){
      return { hour:h.hour, icon:h.icon || icon(h.weather), weather:h.weather, temp:h.temp,
        feels:h.feels_like, rain:h.rain_mm, pop:h.rain_pop, wind:h.wind_ms, dir:h.wind_dir, deg:h.wind_deg, humid:h.humid };
    });

    var damR = (SRC.rivers||[]).filter(function(r){ return r.dam_info; })[0] || null;

    // 홍수예보 발령 (한강홍수통제소 fldfct) — 평상시 빈 배열
    var NORTH = (window.REGION_CONF||{}).floodKeywords || ['동두천','연천','포천','가평','고양','양주','의정부','파주','구리','남양주','일산','임진강','한탄강','신천','왕숙천','중랑천'];
    // ⚠ update_data.py fetch_flood_forecast()는 '소문자 키'로 내보낸다
    //   (kind/river/station/area/announce_time/forecast_time/current_level/north_match).
    //   예전엔 원본 대문자(RVRNM·KIND·ANCDT…)를 읽어 전 항목이 빈 문자열이 됐고,
    //   북부 판정까지 빈 글자 매칭으로 실패 → 홍수예보 '발령될 때만' 조용히 사라졌다.
    var flood = (SRC.flood_forecast||[]).map(function(f){
      var river=f.river||'', obs=f.station||'', area=f.area||'';
      var txt = river + obs + area;
      // 파이썬이 이미 북부 판정(north_match)을 해서 준다. 없을 때만 여기서 다시 계산.
      var north = (typeof f.north_match === 'boolean') ? f.north_match
                : NORTH.some(function(k){ return txt.indexOf(k) >= 0; });
      // ⚠ 'level' 이름 충돌 주의: 파이썬의 level은 심각도(severe/warning/info)이고,
      //   여기 level은 예전부터 '현재 수위'(current_level)를 담아 왔다(화면이 그렇게 읽는다).
      //   심각도는 그동안 버려져 경보/주의보 색을 못 칠했다 → severity로 따로 실어 보낸다.
      return { kind:f.kind||'', river:river, obs:obs, area:area,
        announced:f.announce_time||'', forecast:f.forecast_time||'', level:f.current_level||'',
        severity:f.level||'', north:north };
    });

    // 기상영상 갱신시각
    var ki = SRC.kma_images || {};
    var kmaImages = {
      radar:     { file:'images/kma_radar.png',     ts:(ki.radar&&ki.radar.ts)||'' , ok:!(ki.radar&&ki.radar.ok===false) },
      satellite: { file:'images/kma_satellite.png', ts:(ki.satellite&&ki.satellite.ts)||'', ok:!(ki.satellite&&ki.satellite.ok===false) },
      warn:      { file:'images/kma_warn.png',      ts:(ki.wrn&&ki.wrn.ts)||'', ok:!(ki.wrn&&ki.wrn.ok===false) },
      qpf:       { file:'images/kma_qpf.png',       ts:(ki.qpf&&ki.qpf.ts)||'', ok:!(ki.qpf&&ki.qpf.ok===false) }
    };

    window.DASH = {
      updated: SRC.updated,
      stations: stations, rivers: rivers, warnings: warnings, prelim: prelim,
      fire: SRC.fire || [], pm: SRC.pm || [],
      messages: (SRC.messages||[]).map(function(m){ return { sender:m.sender, time:m.time, text:m.text, region:m.region }; }),
      forecast: forecast, focusRegion: (RC.home || '동두천'),
      dam: damR ? { name: damR.name, info: damR.dam_info } : null,
      flood: flood, kmaImages: kmaImages,
      // 태풍 — 진행 중인 것만 온다. 없으면 빈 배열이 '정상'이다(1년의 대부분).
      // ⚠ 끝난 태풍을 이전 값으로 유지하면 그게 곧 오정보라, 서버도 실패 시 빈 배열을 준다.
      typhoon: SRC.typhoon || [],
      midForecast: SRC.mid_forecast || null,
      weatherInfo: (SRC.bulletins && SRC.bulletins.info_detail) || null,
      // 물때(조석) — 파주 임진강 두포리(강화대교 예보 +2h). 없으면 null(파주 외엔 카드 미표시).
      tide: SRC.tide || null
    };
    return true;
  };

  window.adaptDashboard();
})();
