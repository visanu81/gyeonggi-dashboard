# -*- coding: utf-8 -*-
"""사내망용 미니 HTTP 서버.
사장님 컴퓨터에서 실행하면 같은 네트워크의 모든 컴퓨터/핸드폰에서
http://[사장님IP]:8000/  주소로 상황판에 접속할 수 있다.

실행: python tools/server.py
또는: 서버시작.bat 더블클릭
"""
import http.server
import socket
import socketserver
import sys
import webbrowser
from pathlib import Path

PORT = 8000
ROOT = Path(__file__).resolve().parent.parent

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    """접근 로그를 간단히 — 너무 시끄러우면 끔."""
    def log_message(self, format, *args):
        # 정적 파일 요청은 출력 안 함 (HTML/JS/CSS)
        msg = format % args
        if any(ext in msg for ext in ['.css', '.js HTTP', '.png', '.jpg', '.ico']):
            return
        print(f'  · {self.address_string()} → {msg}')

    def end_headers(self):
        # 캐시 비활성화: data.js 갱신되면 즉시 반영
        self.send_header('Cache-Control', 'no-store, no-cache, must-revalidate')
        self.send_header('Pragma', 'no-cache')
        self.send_header('Expires', '0')
        super().end_headers()


def get_local_ips():
    """사내망에서 동료가 접속할 수 있는 IP 후보들."""
    ips = set()
    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None):
            ip = info[4][0]
            if ip.startswith(('192.168.', '10.', '172.')):
                ips.add(ip)
    except Exception:
        pass
    try:
        # 외부 연결 시도해서 라우터까지 가는 IP 알아냄 (실제 전송은 안 함)
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        ips.add(s.getsockname()[0])
        s.close()
    except Exception:
        pass
    return sorted(ips)


def main():
    import os
    os.chdir(ROOT)

    ips = get_local_ips()
    print('=' * 60)
    print('  경기북부 기상·재난 상황판 — 사내망 서버 시작')
    print('=' * 60)
    print()
    print('  [사장님 컴퓨터에서 접속]')
    print(f'    http://localhost:{PORT}/')
    print()
    if ips:
        print('  [동료 컴퓨터·핸드폰에서 접속 — 같은 사내망]')
        for ip in ips:
            print(f'    http://{ip}:{PORT}/')
    else:
        print('  ! 사내망 IP를 자동으로 찾지 못했습니다.')
        print('    cmd 창에서 `ipconfig`를 입력해 IPv4 주소를 확인하세요.')
    print()
    print('  [종료] 이 창을 닫거나 Ctrl+C')
    print('=' * 60)
    print()

    try:
        with socketserver.ThreadingTCPServer(('', PORT), QuietHandler) as httpd:
            print(f'서버 가동 중 ... (포트 {PORT})')
            # 사장님 컴퓨터 브라우저 자동 열기
            try:
                webbrowser.open(f'http://localhost:{PORT}/')
            except Exception:
                pass
            httpd.serve_forever()
    except OSError as e:
        print(f'\n[오류] 포트 {PORT}를 이미 사용 중입니다. 다른 서버가 켜져 있을 수 있어요.')
        print(f'      자세한 내용: {e}')
        input('\n아무 키나 누르면 종료...')
    except KeyboardInterrupt:
        print('\n서버 종료')


if __name__ == '__main__':
    main()
