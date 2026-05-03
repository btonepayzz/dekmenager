# dekmenager

Telegram dekont / metin eslestirme botu ve (masaustu) PayZZ otomasyon yardimcisi.

## Hizli baslangic

- Masaustu: `pip install -r requirements.txt` sonra `python main.py`
- Railway: `railway_main.py` — ayni PORT’ta aiohttp panel (`/login`, `/panel`, `/health`) + Telegram bot (thread). `PANEL_FERNET_KEY`, `PANEL_USERNAME` / `PANEL_PASSWORD` veya `PANEL_USERS`, `TELETHON_API_ID` / `TELETHON_API_HASH` zorunlu. Telethon session: `sessions/<kullanici>.session`; bot `active_telethon_session.txt` ile hangi session’i kullanacagini bilir.
- `hesaplar.example.txt` dosyasini `hesaplar.txt` olarak kopyalayip doldurun (git’e hesaplar gitmez)

## Repo

https://github.com/btonepayzz/dekmenager
