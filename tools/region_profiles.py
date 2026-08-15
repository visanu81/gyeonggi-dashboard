# -*- coding: utf-8 -*-
"""지역 프로파일 — 한 코드로 여러 지역 상황판을 돌리기 위한 지역별 상수 모음.

왜 이렇게 나눴나:
  상황판 코드는 원래 경기북부 전용이라 시군 목록·관측소 번호·특보구역 코드가
  update_data.py 곳곳에 흩어져 박혀 있었다. 경기남부를 추가하면서 코드를 통째로
  복사하면 앞으로 기능을 고칠 때마다 두 번씩 고쳐야 하고, 한쪽만 고치는 실수가
  반드시 생긴다. 그래서 '지역마다 다른 값'만 여기로 모으고 코드는 하나로 둔다.

  north = 지금 운영중인 경기북부 값 그대로. 한 글자도 바꾸지 않는다.
          (tools/verify_profiles.py 가 update_data.py 원본과 대조해 검증한다)
  south = tools/build_region_profile.py 가 공공 API 원장에서 생성한 경기남부 값.
          같은 생성기가 북부 운영값을 100% 재현하는 것을 확인한 뒤 만들었다.

새 지역을 추가하려면: build_region_profile.py 에 시군 목록을 넣고 --build 로 뽑아
여기에 프로파일 하나를 더 만들면 된다. 코드는 건드릴 필요 없다.
"""

# ══════════════════════════════════════════════════════════════
# 경기북부 (운영중 — gyeonggi-dashboard.visanu81.workers.dev)
# ══════════════════════════════════════════════════════════════
NORTH_REGIONS = [
    {'name': '의정부', 'nx': 61, 'ny': 130, 'sgg': '4115000000'},
    {'name': '양주',   'nx': 61, 'ny': 131, 'sgg': '4163000000'},
    {'name': '동두천', 'nx': 61, 'ny': 134, 'sgg': '4125000000'},
    {'name': '포천',   'nx': 64, 'ny': 133, 'sgg': '4165000000'},
    {'name': '연천',   'nx': 61, 'ny': 138, 'sgg': '4180000000'},
    {'name': '가평',   'nx': 73, 'ny': 133, 'sgg': '4182000000'},
    {'name': '남양주', 'nx': 64, 'ny': 128, 'sgg': '4136000000'},
    {'name': '구리',   'nx': 62, 'ny': 127, 'sgg': '4131000000'},
    {'name': '파주',   'nx': 56, 'ny': 131, 'sgg': '4148000000'},
    {'name': '고양',   'nx': 57, 'ny': 128, 'sgg': '4128000000'},
]

NORTH_PM_STATIONS = {
    '의정부': '의정부동',   '양주': '백석읍',     '동두천': '보산동',
    '포천': '이동읍',       '연천': '연천',       '가평': '가평',
    '남양주': '와부읍',     '구리': '교문동',     '파주': '운정',
    '고양': '행신동',
}

NORTH_AWS_STATIONS = {
    '연천': [(343, '연천백의'), (456, '연천'), (478, '왕징'), (479, '장남'), (480, '미산'), (491, '군남'), (538, '신서'), (652, '연천청산'), (692, '백학')],
    '파주': [(99, '파주'), (309, '판문점'), (481, '탄현'), (482, '광탄'), (483, '진동'), (503, '도라산'), (506, '파주금촌'), (567, '적성')],
    '동두천': [(98, '동두천'), (454, '하봉암'), (477, '상패')],
    '포천': [(359, '선단동'), (360, '내촌면'), (361, '영중면'), (452, '신북'), (473, '가산'), (474, '영북'), (475, '관인'), (476, '화현'), (504, '포천'), (507, '창수'), (539, '포천이동'), (568, '일동'), (599, '광릉')],
    '양주': [(351, '남면'), (352, '장흥면'), (372, '은현면'), (373, '남방'), (375, '백석읍'), (598, '양주')],
    '가평': [(455, '경기가평'), (485, '신천'), (486, '외서'), (505, '가평조종'), (531, '가평북면'), (542, '청평')],
    '일산': [(589, '고양고봉')],
    '고양': [(450, '주교'), (540, '고양')],
    '의정부': [(431, '신곡'), (532, '의정부')],
    '남양주': [(451, '오남'), (484, '창현'), (541, '남양주')],
    '구리': [(368, '수택동'), (569, '구리')],
}
NORTH_AWS_FALLBACK = {'일산': '고양'}

NORTH_RIVER_STATIONS = [
    {'code': '1022668', 'name': '신천 (동두천 송천교)',   'sigun': '동두천', 'warning': 3.4,  'danger': 5.0,  'has_cctv': True,  'api': 'waterlevel'},
    {'code': '1021701', 'name': '임진강 (연천 군남댐)',   'sigun': '연천',   'warning': 31.5, 'danger': 35.0, 'has_cctv': False, 'api': 'dam'},
    {'code': '1021650', 'name': '임진강 (연천 필승교)',   'sigun': '연천',   'warning': 1.0,  'danger': 7.5,  'has_cctv': False, 'api': 'waterlevel'},
    {'code': '1022670', 'name': '신천 (연천)',           'sigun': '연천',   'warning': 3.5,  'danger': 5.5,  'has_cctv': True,  'api': 'waterlevel'},
    {'code': '1021680', 'name': '임진강 (연천 임진교)',   'sigun': '연천',   'warning': 5.9,  'danger': 10.8, 'has_cctv': True,  'api': 'waterlevel'},
    {'code': '1022640', 'name': '한탄강 (포천 용담교)',   'sigun': '포천',   'warning': 9.5,  'danger': 18.0, 'has_cctv': False,  'api': 'waterlevel'},
    {'code': '1018638', 'name': '왕숙천 (남양주 왕숙교)', 'sigun': '남양주', 'warning': 4.9,  'danger': 8.0,  'has_cctv': True,  'api': 'waterlevel'},
    {'code': '1018665', 'name': '중랑천 (의정부 신곡교)', 'sigun': '의정부', 'warning': 2.6,  'danger': 6.0,  'has_cctv': True,  'api': 'waterlevel'},
    {'code': '1015310', 'name': '북한강 (가평 청평댐)',   'sigun': '가평',   'warning': 50.0, 'danger': 52.0,  'has_cctv': False, 'api': 'dam'},
    {'code': '1017310', 'name': '한강 (남양주 팔당댐)',   'sigun': '남양주', 'warning': None, 'danger': 27.0,  'has_cctv': False, 'api': 'dam'},
    {'code': '1022701', 'name': '한탄강 (연천 한탄강댐)', 'sigun': '연천',   'warning': None, 'danger': 114.4, 'has_cctv': False, 'api': 'dam'},
    {'code': '1013655', 'name': '가평 가평교',            'sigun': '가평',   'warning': 2.8,  'danger': 5.0,  'has_cctv': True , 'api': 'waterlevel'},
    {'code': '1023660', 'name': '임진강 (파주 비룡대교)', 'sigun': '파주',   'warning': 8.9,  'danger': 13.5, 'has_cctv': True , 'api': 'waterlevel'},
    {'code': '1023670', 'name': '임진강 (파주 통일대교)', 'sigun': '파주',   'warning': 5.3,  'danger': 9.5,  'has_cctv': True , 'api': 'waterlevel'},
    {'code': '1019667', 'name': '고양 원당교',            'sigun': '고양',   'warning': 1.6,  'danger': 3.0,  'has_cctv': True , 'api': 'waterlevel'},
    {'code': '1018661', 'name': '양주 마전3교',           'sigun': '양주',   'warning': 3.7,  'danger': 5.4,  'has_cctv': False, 'api': 'waterlevel'},
    {'code': '1022647', 'name': '포천 포천대교',          'sigun': '포천',   'warning': 4.3,  'danger': 7.4,  'has_cctv': True , 'api': 'waterlevel'},
    {'code': '1018666', 'name': '의정부 금신교',          'sigun': '의정부', 'warning': 4.4,  'danger': 6.5,  'has_cctv': False, 'api': 'waterlevel'},
]

NORTH_KEYWORDS = ['경기북부', '경기도', '수도권', '동두천', '양주', '의정부', '포천', '연천',
                  '가평', '남양주', '구리', '파주', '고양']

NORTH_REG_MAP = {
    'L1011100': '동두천', 'L1011200': '연천',  'L1011300': '포천',
    'L1011400': '가평',  'L1011500': '고양',  'L1011600': '양주',
    'L1011700': '의정부', 'L1011800': '파주',  'L1012200': '구리',
    'L1012300': '남양주',
    'L1010000': '경기도(전체)',  # 광역 발표
}

NORTH_REGION_ORDER = ['경기도', '연천', '파주', '동두천', '포천', '양주', '가평', '고양',
                      '의정부', '남양주', '구리']

# 산불위험예보 API가 돌려주는 시군 표기 → 관서명 (고양시는 3개 구로 나뉘어 나온다)
NORTH_FIRE_SIGUN_MAP = {
    '의정부시': '의정부', '양주시': '양주',     '동두천시': '동두천',
    '포천시':  '포천',   '연천군': '연천',     '가평군':  '가평',
    '남양주시': '남양주', '구리시': '구리',     '파주시':  '파주',
    '고양시덕양구': '고양', '고양시일산동구': '고양', '고양시일산서구': '고양', '고양시': '고양',
}
NORTH_FIRE_GROUPS = {
    '의정부·양주': ['의정부', '양주'],
    '동두천·연천': ['동두천', '연천'],
    '포천·가평':   ['포천', '가평'],
    '파주·고양':   ['파주', '고양'],
}

# 홍수예보 매칭 키워드 — 시군명 + 그 지역을 흐르는 주요 하천명
NORTH_FLOOD_KEYWORDS = {'의정부', '양주', '동두천', '포천', '연천', '가평',
                        '남양주', '구리', '파주', '고양',
                        '임진강', '한탄강', '신천', '왕숙천', '중랑천',
                        '경기북부', '경기'}


# ══════════════════════════════════════════════════════════════
# 경기남부 (신규 — weather.visanu81.workers.dev)
#   build_region_profile.py 가 생성. 재생성하려면:
#     python tools/build_region_profile.py --verify --build south
# ══════════════════════════════════════════════════════════════
SOUTH_REGIONS = [
    {'name': '김포', 'nx': 56, 'ny': 128, 'sgg': '4157000000'},
    {'name': '하남', 'nx': 64, 'ny': 126, 'sgg': '4145000000'},
    {'name': '부천', 'nx': 56, 'ny': 125, 'sgg': '4119000000'},
    {'name': '광명', 'nx': 58, 'ny': 125, 'sgg': '4121000000'},
    {'name': '양평', 'nx': 69, 'ny': 125, 'sgg': '4183000000'},
    {'name': '과천', 'nx': 60, 'ny': 124, 'sgg': '4129000000'},
    {'name': '성남', 'nx': 62, 'ny': 124, 'sgg': '4113000000'},
    {'name': '광주', 'nx': 65, 'ny': 124, 'sgg': '4161000000'},
    {'name': '시흥', 'nx': 56, 'ny': 123, 'sgg': '4139000000'},
    {'name': '안양', 'nx': 59, 'ny': 123, 'sgg': '4117000000'},
    {'name': '군포', 'nx': 59, 'ny': 122, 'sgg': '4141000000'},
    {'name': '의왕', 'nx': 60, 'ny': 122, 'sgg': '4143000000'},
    {'name': '안산', 'nx': 57, 'ny': 120, 'sgg': '4127000000'},
    {'name': '수원', 'nx': 60, 'ny': 120, 'sgg': '4111000000'},
    {'name': '용인', 'nx': 64, 'ny': 120, 'sgg': '4146000000'},
    {'name': '이천', 'nx': 69, 'ny': 120, 'sgg': '4150000000'},
    {'name': '여주', 'nx': 71, 'ny': 120, 'sgg': '4167000000'},
    {'name': '화성', 'nx': 57, 'ny': 119, 'sgg': '4159000000'},
    {'name': '오산', 'nx': 61, 'ny': 118, 'sgg': '4137000000'},
    {'name': '안성', 'nx': 65, 'ny': 115, 'sgg': '4155000000'},
    {'name': '평택', 'nx': 62, 'ny': 114, 'sgg': '4122000000'},
]

SOUTH_PM_STATIONS = {
    '수원': '신풍동', '성남': '성남대로(모란역)', '안양': '안양2동',
    '부천': '송내대로(중동)', '광명': '철산동', '평택': '비전동', '안산': '고잔동',
    '과천': '과천동', '오산': '오산동', '시흥': '정왕동', '군포': '산본동',
    '의왕': '고천동', '하남': '신장동', '용인': '김량장동', '이천': '부발읍',
    '안성': '공도읍', '김포': '사우동', '화성': '남양읍', '광주': '경안동',
    '여주': '가남읍', '양평': '양평읍',
}

SOUTH_AWS_STATIONS = {
    '김포': [(427, '양촌'), (441, '김포'), (487, '대곶')],
    '하남': [(428, '하남덕풍'), (444, '하남'), (457, '춘궁')],
    '부천': [(429, '부천원미'), (433, '부천')],
    '광명': [(376, '광명노온'), (437, '광명'), (453, '소하'), (492, '학온동')],
    '양평': [(202, '양평'), (326, '용문산'), (449, '옥천'), (547, '양동'), (573, '청운')],
    '과천': [(116, '관악(레)'), (590, '과천')],
    '성남': [(364, '분당구'), (572, '성남')],
    '광주': [(442, '지월'), (458, '퇴촌'), (459, '오포'), (460, '실촌'), (546, '경기광주')],
    '시흥': [(367, '신현동'), (565, '시흥')],
    '안양': [(365, '석수동'), (377, '안양만안'), (434, '안양')],
    '군포': [(369, '수리산길'), (438, '군포'), (896, '군포금정')],
    '의왕': [(366, '오전동'), (445, '의왕'), (897, '의왕이동')],
    '안산': [(435, '고잔'), (514, '대부도'), (545, '안산'), (966, '풍도')],
    '수원': [(119, '수원'), (430, '경기')],
    '용인': [(370, '이동어비'), (371, '기흥구갈'), (436, '처인역삼'), (549, '용인'), (575, '용인이동'), (576, '백암')],
    '이천': [(203, '이천'), (440, '설봉'), (461, '마장'), (462, '모가'), (533, '백사'), (534, '장호원')],
    '여주': [(447, '북내'), (448, '산북'), (463, '흥천'), (464, '점동'), (465, '가남'), (466, '금사'), (548, '여주'), (574, '대신')],
    '화성': [(432, '향남'), (439, '진안'), (488, '송산'), (489, '서신'), (515, '운평'), (544, '전곡항'), (571, '화성'), (967, '도리도')],
    '오산': [(446, '남촌'), (550, '오산')],
    '안성': [(443, '보개'), (467, '양성'), (468, '서운'), (469, '일죽'), (470, '고삼'), (495, '공도'), (516, '안성')],
    '평택': [(355, '서탄면'), (356, '고덕면'), (358, '현덕면'), (374, '청북'), (471, '송탄'), (472, '포승'), (551, '평택')],
}
SOUTH_AWS_FALLBACK = {}

# warning=관심수위(attwl), danger=경계수위(almwl). 한강홍수통제소 원장 값 그대로.
# nearby=True 는 관내에 관측소가 아예 없어 인근 시의 관측소를 빌려온 것 —
# 화면에서 '관할 하천'으로 오인하지 않도록 이름에 '인근'을 붙여 둔다.
SOUTH_RIVER_STATIONS = [
    # 김포 사우교(1019661)는 뺐다 — 한강 하구 조위 탓에 관심수위 1.0m를 평상시에도
    # 하루 21시간 넘겨, 매일 '주의'가 떠 있게 된다(경보 피로). build_region_profile.py의
    # RIVER_EXCLUDE 참조. 김포는 전류리 하나로 본다.
    {'code': '1019675', 'name': '한강 (김포 전류리)', 'sigun': '김포', 'warning': 4.1, 'danger': 6.8, 'has_cctv': False, 'api': 'waterlevel'},
    {'code': '1018610', 'name': '한강 (하남 인근 · 남양주시 팔당대교)', 'sigun': '하남', 'warning': 7.0, 'danger': 12.7, 'has_cctv': False, 'api': 'waterlevel', 'nearby': True},
    {'code': '1019620', 'name': '굴포천 (부천 도두리2교)', 'sigun': '부천', 'warning': 2.0, 'danger': 3.4, 'has_cctv': False, 'api': 'waterlevel'},
    {'code': '1018693', 'name': '안양천 (광명 시흥대교)', 'sigun': '광명', 'warning': 3.8, 'danger': 6.5, 'has_cctv': False, 'api': 'waterlevel'},
    {'code': '1007680', 'name': '흑천 (양평 흑천교)', 'sigun': '양평', 'warning': 2.2, 'danger': 4.0, 'has_cctv': True, 'api': 'waterlevel'},
    {'code': '1007685', 'name': '한강 (양평 양평교)', 'sigun': '양평', 'warning': 8.5, 'danger': 12.0, 'has_cctv': True, 'api': 'waterlevel'},
    {'code': '1007687', 'name': '흑천 (양평 여물교)', 'sigun': '양평', 'warning': 2.7, 'danger': 4.2, 'has_cctv': False, 'api': 'waterlevel'},
    {'code': '1018690', 'name': '안양천 (안양 충훈1교)', 'sigun': '과천', 'warning': 1.0, 'danger': 4.1, 'has_cctv': False, 'api': 'waterlevel', 'nearby': True},
    {'code': '1018650', 'name': '탄천 (성남 궁내교)', 'sigun': '성남', 'warning': 2.0, 'danger': 4.2, 'has_cctv': False, 'api': 'waterlevel'},
    {'code': '1018653', 'name': '탄천 (성남 둔전교)', 'sigun': '성남', 'warning': 4.2, 'danger': 6.9, 'has_cctv': False, 'api': 'waterlevel'},
    {'code': '1016650', 'name': '경안천 (광주 경안교)', 'sigun': '광주', 'warning': 1.5, 'danger': 5.0, 'has_cctv': True, 'api': 'waterlevel'},
    {'code': '1016660', 'name': '곤지암천 (광주 섬뜰교)', 'sigun': '광주', 'warning': 2.5, 'danger': 5.2, 'has_cctv': True, 'api': 'waterlevel'},
    {'code': '1016606', 'name': '오산천 (광주 동림3교)', 'sigun': '광주', 'warning': 3.4, 'danger': 4.8, 'has_cctv': False, 'api': 'waterlevel'},
    {'code': '1202650', 'name': '안산천 (안산 안산10교)', 'sigun': '시흥', 'warning': 3.7, 'danger': 5.4, 'has_cctv': False, 'api': 'waterlevel', 'nearby': True},
    {'code': '1018690', 'name': '안양천 (안양 충훈1교)', 'sigun': '안양', 'warning': 1.0, 'danger': 4.1, 'has_cctv': False, 'api': 'waterlevel'},
    {'code': '1018690', 'name': '안양천 (안양 충훈1교)', 'sigun': '군포', 'warning': 1.0, 'danger': 4.1, 'has_cctv': False, 'api': 'waterlevel', 'nearby': True},
    {'code': '1018690', 'name': '안양천 (안양 충훈1교)', 'sigun': '의왕', 'warning': 1.0, 'danger': 4.1, 'has_cctv': False, 'api': 'waterlevel', 'nearby': True},
    {'code': '1202650', 'name': '안산천 (안산 안산10교)', 'sigun': '안산', 'warning': 3.7, 'danger': 5.4, 'has_cctv': False, 'api': 'waterlevel'},
    {'code': '1101601', 'name': '수원천 (수원 매세교)', 'sigun': '수원', 'warning': 3.0, 'danger': 4.1, 'has_cctv': False, 'api': 'waterlevel'},
    {'code': '1101604', 'name': '원천리천 (수원 백년교)', 'sigun': '수원', 'warning': 3.3, 'danger': 5.5, 'has_cctv': False, 'api': 'waterlevel'},
    {'code': '1016601', 'name': '양지천 (용인 마전교)', 'sigun': '용인', 'warning': 3.6, 'danger': 4.7, 'has_cctv': False, 'api': 'waterlevel'},
    {'code': '1016607', 'name': '용인 월촌교', 'sigun': '용인', 'warning': 3.1, 'danger': 5.0, 'has_cctv': False, 'api': 'waterlevel'},
    {'code': '1101621', 'name': '송전천 (용인 덕성1교)', 'sigun': '용인', 'warning': 3.5, 'danger': 5.8, 'has_cctv': False, 'api': 'waterlevel'},
    {'code': '1007605', 'name': '청미천 (이천 장호원교)', 'sigun': '이천', 'warning': 2.0, 'danger': 5.4, 'has_cctv': False, 'api': 'waterlevel'},
    {'code': '1007608', 'name': '석원천 (이천 고당교)', 'sigun': '이천', 'warning': 4.2, 'danger': 6.6, 'has_cctv': False, 'api': 'waterlevel'},
    {'code': '1007642', 'name': '복하천 (이천 동산교)', 'sigun': '이천', 'warning': 2.5, 'danger': 4.2, 'has_cctv': False, 'api': 'waterlevel'},
    {'code': '1007615', 'name': '청미천 (여주 원부교)', 'sigun': '여주', 'warning': 4.0, 'danger': 6.5, 'has_cctv': True, 'api': 'waterlevel'},
    {'code': '1007635', 'name': '한강 (여주 여주대교)', 'sigun': '여주', 'warning': 3.3, 'danger': 8.0, 'has_cctv': True, 'api': 'waterlevel'},
    {'code': '1007640', 'name': '양화천 (여주 율극교)', 'sigun': '여주', 'warning': 3.5, 'danger': 5.5, 'has_cctv': True, 'api': 'waterlevel'},
    {'code': '1101605', 'name': '황구지천 (화성 화산교)', 'sigun': '화성', 'warning': 4.3, 'danger': 6.6, 'has_cctv': False, 'api': 'waterlevel'},
    {'code': '1101650', 'name': '황구지천 (화성 수직교)', 'sigun': '화성', 'warning': 3.5, 'danger': 5.6, 'has_cctv': False, 'api': 'waterlevel'},
    {'code': '1202668', 'name': '발안천 (화성 발안천2교)', 'sigun': '화성', 'warning': 3.3, 'danger': 5.1, 'has_cctv': False, 'api': 'waterlevel'},
    {'code': '1101645', 'name': '오산천 (오산 탑동대교)', 'sigun': '오산', 'warning': 1.5, 'danger': 5.2, 'has_cctv': True, 'api': 'waterlevel'},
    {'code': '1007604', 'name': '청미천 (안성 한평교)', 'sigun': '안성', 'warning': 4.0, 'danger': 7.0, 'has_cctv': False, 'api': 'waterlevel'},
    {'code': '1007606', 'name': '죽산천 (안성 두현교)', 'sigun': '안성', 'warning': 3.0, 'danger': 4.9, 'has_cctv': False, 'api': 'waterlevel'},
    {'code': '1101606', 'name': '조령천 (안성 현수교)', 'sigun': '안성', 'warning': 0.9, 'danger': 2.5, 'has_cctv': False, 'api': 'waterlevel'},
    {'code': '1101635', 'name': '안성천 (평택 군문교)', 'sigun': '평택', 'warning': 4.2, 'danger': 7.0, 'has_cctv': True, 'api': 'waterlevel'},
    {'code': '1101663', 'name': '진위천 (평택 진위1교)', 'sigun': '평택', 'warning': 3.5, 'danger': 5.8, 'has_cctv': True, 'api': 'waterlevel'},
    {'code': '1101670', 'name': '진위천 (평택 동연교)', 'sigun': '평택', 'warning': 5.5, 'danger': 8.5, 'has_cctv': True, 'api': 'waterlevel'},
]

SOUTH_KEYWORDS = ['경기남부', '경기도', '수도권', '수원', '성남', '안양', '부천', '광명',
                  '평택', '안산', '과천', '오산', '시흥', '군포', '의왕', '하남', '용인',
                  '이천', '안성', '김포', '화성', '광주', '여주', '양평']

SOUTH_REG_MAP = {
    'L1010200': '광명', 'L1010300': '과천', 'L1010400': '안산', 'L1010500': '시흥',
    'L1010600': '부천', 'L1010700': '김포', 'L1011900': '수원', 'L1012000': '성남',
    'L1012100': '안양', 'L1012400': '오산', 'L1012500': '평택', 'L1012600': '군포',
    'L1012700': '의왕', 'L1012800': '하남', 'L1012900': '용인', 'L1013000': '이천',
    'L1013100': '안성', 'L1013200': '화성', 'L1013300': '여주', 'L1013400': '광주',
    'L1013500': '양평',
    'L1010000': '경기도(전체)',
}

SOUTH_REGION_ORDER = ['경기도', '김포', '하남', '부천', '광명', '양평', '과천', '성남',
                      '광주', '시흥', '안양', '군포', '의왕', '안산', '수원', '용인',
                      '이천', '여주', '화성', '오산', '안성', '평택']

# 구가 있는 시는 산불 API도 구 단위로 준다 → 구까지 다 매핑한다.
SOUTH_FIRE_SIGUN_MAP = {
    '수원시': '수원', '수원시장안구': '수원', '수원시권선구': '수원',
    '수원시팔달구': '수원', '수원시영통구': '수원',
    '성남시': '성남', '성남시수정구': '성남', '성남시중원구': '성남', '성남시분당구': '성남',
    '안양시': '안양', '안양시만안구': '안양', '안양시동안구': '안양',
    '부천시': '부천', '부천시원미구': '부천', '부천시소사구': '부천', '부천시오정구': '부천',
    '안산시': '안산', '안산시상록구': '안산', '안산시단원구': '안산',
    '용인시': '용인', '용인시처인구': '용인', '용인시기흥구': '용인', '용인시수지구': '용인',
    '화성시': '화성', '화성시만세구': '화성',
    '광명시': '광명', '평택시': '평택', '과천시': '과천', '오산시': '오산',
    '시흥시': '시흥', '군포시': '군포', '의왕시': '의왕', '하남시': '하남',
    '이천시': '이천', '안성시': '안성', '김포시': '김포', '광주시': '광주',
    '여주시': '여주', '양평군': '양평',
}
SOUTH_FIRE_GROUPS = {
    '김포·부천·광명': ['김포', '부천', '광명'],
    '시흥·안산·화성': ['시흥', '안산', '화성'],
    '안양·군포·의왕': ['안양', '군포', '의왕'],
    '과천·성남·하남': ['과천', '성남', '하남'],
    '광주·양평·여주': ['광주', '양평', '여주'],
    '수원·용인·오산': ['수원', '용인', '오산'],
    '이천·안성·평택': ['이천', '안성', '평택'],
}

SOUTH_FLOOD_KEYWORDS = {'수원', '성남', '안양', '부천', '광명', '평택', '안산', '과천',
                        '오산', '시흥', '군포', '의왕', '하남', '용인', '이천', '안성',
                        '김포', '화성', '광주', '여주', '양평',
                        '한강', '남한강', '안양천', '탄천', '경안천', '오산천', '진위천',
                        '안성천', '황구지천', '복하천', '청미천', '흑천', '굴포천',
                        '발안천', '신갈천', '왕숙천',
                        '경기남부', '경기'}


# ══════════════════════════════════════════════════════════════
PROFILES = {
    'north': {
        'key': 'north',
        'label': '경기북부',
        'title': '경기북부 기상·재난 상황판',
        'home': '동두천',                 # 기본 중점 관서 (시간대별 예보 기준점)
        'home_office': '동두천소방서',
        'host': 'gyeonggi-dashboard.visanu81.workers.dev',
        'data_file': 'data.js',
        'map_file': 'map-geo.js',
        'combined_file': '상황판.html',
        'notify': True,                   # 텔레그램 알림 대상 지역
        'tide': True,                     # 물때(조석) 카드 — 파주 임진강 전용
        'share_images_from': None,        # 기상청 이미지를 직접 내려받는 쪽
        'regions': NORTH_REGIONS,
        'pm_stations': NORTH_PM_STATIONS,
        'aws_stations': NORTH_AWS_STATIONS,
        'aws_fallback': NORTH_AWS_FALLBACK,
        'river_stations': NORTH_RIVER_STATIONS,
        'keywords': NORTH_KEYWORDS,
        'reg_map': NORTH_REG_MAP,
        'region_order': NORTH_REGION_ORDER,
        'fire_sigun_map': NORTH_FIRE_SIGUN_MAP,
        'fire_groups': NORTH_FIRE_GROUPS,
        'flood_keywords': NORTH_FLOOD_KEYWORDS,
        'exclude_prefix': '경기남부',      # 반대편 광역 발표는 제외
    },
    'south': {
        'key': 'south',
        'label': '경기남부',
        'title': '경기남부 기상·재난 상황판',
        'home': '수원',
        'home_office': '경기남부',
        'host': 'weather.visanu81.workers.dev',
        'data_file': 'data-south.js',
        'map_file': 'map-geo-south.js',
        'combined_file': '상황판-south.html',
        'notify': False,                  # 남부는 알림 대상 아님(북부 구독자에게 안 보냄)
        'tide': False,                    # 남부엔 임진강 물때가 해당 없음
        # 레이더·위성·특보발효도는 전국 공통 이미지다. 지역마다 또 받으면
        # 5분마다 같은 파일을 두 번 받게 되므로 북부가 받은 것을 그대로 쓴다.
        'share_images_from': 'data.js',
        'regions': SOUTH_REGIONS,
        'pm_stations': SOUTH_PM_STATIONS,
        'aws_stations': SOUTH_AWS_STATIONS,
        'aws_fallback': SOUTH_AWS_FALLBACK,
        'river_stations': SOUTH_RIVER_STATIONS,
        'keywords': SOUTH_KEYWORDS,
        'reg_map': SOUTH_REG_MAP,
        'region_order': SOUTH_REGION_ORDER,
        'fire_sigun_map': SOUTH_FIRE_SIGUN_MAP,
        'fire_groups': SOUTH_FIRE_GROUPS,
        'flood_keywords': SOUTH_FLOOD_KEYWORDS,
        'exclude_prefix': '경기북부',
    },
}


def get(name):
    if name not in PROFILES:
        raise SystemExit(f'알 수 없는 지역 프로파일: {name} (가능: {", ".join(PROFILES)})')
    return PROFILES[name]
