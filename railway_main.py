"""
Railway: aiohttp panel ($PORT) + Telegram bot (ayri thread, long polling).
Masaustu GUI: main.py
"""

from __future__ import annotations

import os
import threading
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent / ".env", override=False)
except ImportError:
    pass

from panel_app import run_panel_blocking


def _run_bot() -> None:
    from ocr import run as run_bot

    run_bot()


def main() -> None:
    threading.Thread(target=_run_bot, daemon=True).start()
    port = int(os.environ.get("PORT", "8080"))
    print(f"Panel: http://0.0.0.0:{port}/  |  saglik: /health")
    run_panel_blocking(port=port)


if __name__ == "__main__":
    main()
