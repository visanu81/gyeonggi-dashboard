"""갱신.bat을 CP949(ANSI Korean)로 저장 — Windows cmd 호환용 일회성 스크립트."""

content = r"""@echo off
chcp 65001 > nul
title 경기북부 기상재난 상황판 - 데이터 갱신
cd /d "%~dp0"
echo.
echo ====================================================
echo    경기북부 기상재난 상황판 - 데이터 갱신
echo ====================================================
echo.

python tools\update_data.py
set RESULT=%errorlevel%

echo.
echo ====================================================
if %RESULT% NEQ 0 (
  echo    [실패] 데이터 갱신 중 오류 발생
) else (
  echo    [완료] 데이터 갱신 + GitHub 푸시 성공
  echo.
  echo    위 메시지에서 다음 줄을 확인하세요:
  echo      - [GitHub 푸시] 줄이 있으면 사이트 반영됨
  echo      - 없거나 빨간 글씨면 push 실패 (정부망 차단일 수 있음)
  echo.
  echo    Cloudflare가 1-2분 후 자동 재배포합니다.
)
echo ====================================================
echo.
echo    아무 키나 누르면 창이 닫힙니다.
pause > nul
"""

# UTF-8 with BOM — cmd가 BOM 보고 UTF-8로 해석. chcp 65001과 짝.
with open(r'갱신.bat', 'wb') as f:
    f.write(b'\xef\xbb\xbf')  # UTF-8 BOM
    f.write(content.encode('utf-8'))

print('갱신.bat -> UTF-8 BOM 저장 OK')
