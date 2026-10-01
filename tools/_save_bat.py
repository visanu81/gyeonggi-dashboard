"""갱신.bat을 CP949(ANSI Korean)로 저장 — Windows cmd 호환용 일회성 스크립트."""

content = r"""@echo off
chcp 65001 > nul
title Gyeonggi Bukbu Dashboard - Update
cd /d "%~dp0"
echo.
echo ====================================================
echo    Gyeonggi Bukbu Dashboard - Data Update
echo ====================================================
echo.

python tools\update_data.py
set RESULT=%errorlevel%

echo.
echo ====================================================
if %RESULT% NEQ 0 (
  echo    [FAIL] Update error occurred
) else (
  echo    [OK] Update + GitHub push done
  echo.
  echo    Check above messages:
  echo      - Look for [GitHub Push] line - means push success
  echo      - If missing or red text, push failed
  echo.
  echo    Cloudflare auto-deploys in 1-2 minutes.
)
echo ====================================================
echo.
echo    Press any key to close.
pause > nul
"""

# 순수 ASCII만 사용 — BOM·인코딩 모두 무관. Windows cmd 어디서나 작동.
with open(r'갱신.bat', 'wb') as f:
    f.write(content.encode('ascii'))

print('Saved 갱신.bat (ASCII only)')
