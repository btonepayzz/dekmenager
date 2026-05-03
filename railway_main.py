"""
Railway entry: lightweight HTTP health on $PORT + Telegram bot (long polling).
Desktop kullanim icin main.py (GUI) kullan.
"""

from __future__ import annotations

import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from ocr import run as run_bot


def _start_health_server() -> None:
    port_raw = os.environ.get("PORT", "").strip()
    if not port_raw:
        return
    port = int(port_raw)

    class _Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args) -> None:
            return

        def do_GET(self) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"ok")

    server = HTTPServer(("0.0.0.0", port), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    print(f"Health: http://0.0.0.0:{port}/")


def main() -> None:
    _start_health_server()
    run_bot()


if __name__ == "__main__":
    main()
