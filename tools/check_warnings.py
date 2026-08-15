#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""기상특보 + 하천 수위 빠른 알리미 — cron 1분 주기.

전체 데이터 갱신(update_data.py, 5분 주기)과 별개로, 기상특보·예비특보와
하천 수위(주의/위험 단계 진입)만 가볍게 확인해 최대 1분 안에 텔레그램으로 알린다.
(특보는 텍스트 API 2개, 하천은 관측소 현재값만 → 부담이 작음.)

update_data.py와 상태파일(.tmp/notified_warnings.json·notified_rivers.json)을 공유하므로
중복 발송이 없다 — 먼저 보낸 쪽이 기록하면 다른 쪽은 이미 보낸 것으로 보고 건너뛴다.
즉 이 1분 알리미가 평소 특보·하천 알림을 담당하고, 5분 갱신이 백업 역할을 한다.

서버 cron 등록 예:
  * * * * * cd /root/gyeonggi-dashboard && /usr/bin/python3 tools/check_warnings.py >> warn.log 2>&1
"""
import sys
from pathlib import Path

# 같은 폴더의 update_data.py 함수 재사용 (수집·병합·발송·상태)
sys.path.insert(0, str(Path(__file__).resolve().parent))
import update_data as ud


def collect_warnings():
    """기상특보(getPwnStatus) + 허브특보(병합)만 수집.
    getPwnStatus 또는 허브 중 하나라도 실패하면 목록이 불완전(북부 개별 특보 누락)해
    5분 갱신과 번갈아 발효/해제 핑퐁을 유발하므로 None 반환 → 이번 회차 판정 보류."""
    try:
        w = ud.fetch_warnings()
    except Exception as e:
        print(f'  특보 수집 실패: {e}')
        return None
    try:
        aw = ud.fetch_apihub_warnings()   # 실패 시 None
    except Exception as e:
        print(f'  허브특보 수집 실패: {e}')
        aw = None
    if aw is None:
        print('  허브특보 실패 — 이번 회차 특보 판정 보류(핑퐁 방지)')
        return None
    d = {'warnings': w.get('active', []), 'prelim_warnings': w.get('prelim', []),
         'apihub_warnings': aw}
    try:
        ud.merge_apihub_warnings(d)   # 북부 발효/예비특보를 warnings/prelim에 병합
    except Exception as e:
        print(f'  허브 병합 오류: {e}')
        return None
    return d


def main():
    if not ud.TELEGRAM_BOT_TOKEN:
        return
    # ① 기상특보·예비특보
    d = collect_warnings()
    if d is not None:
        ud.notify_warnings(d.get('warnings'), d.get('prelim_warnings'))
    # (d is None이면 수집 실패 — 특보 상태 유지, 다음 회차 재시도. 하천은 아래에서 독립 처리)

    # ② 하천 수위 주의/위험 단계 진입 (특보 성공 여부와 무관하게 매분 확인)
    try:
        rivers = ud.fetch_rivers_light()
        if rivers:
            ud.notify_rivers(rivers)
    except Exception as e:
        print(f'  하천 수위 확인 실패: {e}')


if __name__ == '__main__':
    main()
