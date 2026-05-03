"""Masaustu: GUI ayarlari + bot. Bulut (Railway): railway_main.py kullan."""

from forwarding_gui import run_setup_gui
from ocr import run


def main() -> None:
    print("Ayar penceresi aciliyor...")
    print("Ayarlarini kaydedip pencereyi kapattiginda bot baslayacak.")
    run_setup_gui()
    print("Bot baslatiliyor...")
    run()


if __name__ == "__main__":
    main()
