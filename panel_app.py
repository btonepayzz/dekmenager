"""
Railway / sunucu: aiohttp ile kucuk panel + Telethon session (kullanici adina dosya).
Oturum: EncryptedCookieStorage (PANEL_FERNET_KEY).
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import secrets
from pathlib import Path
from aiohttp import web
from aiohttp_session import get_session, setup, SimpleCookieStorage
from aiohttp_session.cookie_storage import EncryptedCookieStorage
from cryptography.fernet import Fernet

try:
    from telethon import TelegramClient
    from telethon.errors import SessionPasswordNeededError
except ImportError:
    TelegramClient = None
    SessionPasswordNeededError = Exception


def _sessions_dir() -> Path:
    p = Path(os.getenv("SESSIONS_DIR", "sessions")).resolve()
    p.mkdir(parents=True, exist_ok=True)
    return p


def _active_session_file() -> Path:
    return Path(os.getenv("ACTIVE_TELETHON_SESSION_FILE", "active_telethon_session.txt")).resolve()


def session_slug(username: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9_-]+", "_", (username or "").strip())[:48]
    return s or "user"


def _load_panel_users() -> dict[str, str]:
    """
    PANEL_USERS: alice:secret1,bob:secret2
    veya tek kullanici: PANEL_USERNAME + PANEL_PASSWORD
    """
    raw = os.getenv("PANEL_USERS", "").strip()
    users: dict[str, str] = {}
    if raw:
        for part in raw.split(","):
            part = part.strip()
            if ":" not in part:
                continue
            u, p = part.split(":", 1)
            u, p = u.strip(), p.strip()
            if u and p:
                users[u] = p
        return users
    u = os.getenv("PANEL_USERNAME", "admin").strip()
    p = os.getenv("PANEL_PASSWORD", "").strip()
    if u and p:
        users[u] = p
    return users


def _telethon_api() -> tuple[int, str]:
    api_id_raw = os.getenv("TELETHON_API_ID", "").strip()
    api_hash = os.getenv("TELETHON_API_HASH", "").strip()
    if not api_id_raw or not api_hash:
        raise RuntimeError("TELETHON_API_ID ve TELETHON_API_HASH panel icin zorunlu.")
    return int(api_id_raw), api_hash


def _forwarding_config_path() -> Path:
    return Path(os.getenv("FORWARDING_CONFIG_FILE", "forwarding_config.json")).resolve()


def _html_page(title: str, body: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="tr"><head><meta charset="utf-8"/><meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>{title}</title>
<style>
body{{font-family:system-ui,sans-serif;max-width:42rem;margin:2rem auto;padding:0 1rem;background:#0f172a;color:#e2e8f0;}}
a{{color:#38bdf8;}} input,button,textarea{{font-size:1rem;padding:.5rem .75rem;border-radius:.375rem;border:1px solid #334155;background:#1e293b;color:#e2e8f0;}}
textarea{{width:100%;box-sizing:border-box;min-height:5rem;font-family:inherit;}}
button{{cursor:pointer;background:#2563eb;border-color:#1d4ed8;}} .card{{background:#1e293b;border:1px solid #334155;border-radius:.5rem;padding:1.25rem;margin:1rem 0;}}
.hint{{font-size:.875rem;color:#94a3b8;margin:.25rem 0 0;}}
.warn{{color:#fbbf24;}}
.msg{{white-space:pre-wrap;background:#0c1222;padding:.75rem;border-radius:.375rem;border:1px solid #334155;}}
label{{display:block;margin:.5rem 0 .25rem;color:#94a3b8;font-size:.875rem;}}
</style></head><body>
<h1>{title}</h1>
{body}
</body></html>"""


async def handle_health(_request: web.Request) -> web.Response:
    return web.Response(text="ok")


async def handle_login_get(request: web.Request) -> web.Response:
    session = await get_session(request)
    if session.get("user"):
        raise web.HTTPFound(location="/panel")
    body = """
<p>Telegram bot ile ayni makinede calisan panel. Giris yap, Telethon oturumu ac, cikista session silinir.</p>
<form method="post" action="/login">
<label>Kullanici adi</label><br/><input name="username" autocomplete="username" required/><br/>
<label>Sifre</label><br/><input name="password" type="password" autocomplete="current-password" required/><br/><br/>
<button type="submit">Giris</button>
</form>
"""
    return web.Response(text=_html_page("Panel girisi", body), content_type="text/html", charset="utf-8")


async def handle_login_post(request: web.Request) -> web.Response:
    data = await request.post()
    username = str(data.get("username", "")).strip()
    password = str(data.get("password", "")).strip()
    users = _load_panel_users()
    if not users:
        return web.Response(
            text=_html_page("Hata", "<p>PANEL_USERS veya PANEL_USERNAME/PANEL_PASSWORD ayarlanmamis.</p>"),
            content_type="text/html",
            charset="utf-8",
            status=500,
        )
    expected = users.get(username)
    if not expected or not secrets.compare_digest(password, expected):
        return web.Response(
            text=_html_page("Hata", "<p>Kullanici adi veya sifre hatali.</p><p><a href='/login'>Geri</a></p>"),
            content_type="text/html",
            charset="utf-8",
            status=401,
        )
    session = await get_session(request)
    session["user"] = username
    session["slug"] = session_slug(username)
    raise web.HTTPFound(location="/panel")


async def handle_logout(request: web.Request) -> web.Response:
    session = await get_session(request)
    slug = session.get("slug") or session_slug(str(session.get("user", "")))
    user = session.get("user")
    sessions_dir = _sessions_dir()

    pending: dict[str, dict] = request.app.get("telethon_pending", {})
    if slug in pending:
        client = pending[slug].get("client")
        if client:
            try:
                await client.disconnect()
            except Exception:
                pass
        del pending[slug]

    sessions_dir = _sessions_dir()
    for name in (f"{slug}.session", f"{slug}.session-journal"):
        try:
            (sessions_dir / name).unlink(missing_ok=True)
        except Exception:
            pass

    active = _active_session_file()
    try:
        expected_base = str((sessions_dir / slug).resolve())
        if active.is_file():
            line = active.read_text(encoding="utf-8").strip().splitlines()[0].strip()
            if line == expected_base or line.rstrip("/").endswith(slug):
                active.unlink(missing_ok=True)
    except Exception:
        pass

    session.invalidate()
    return web.Response(
        text=_html_page(
            "Cikis",
            f"<p>Oturum kapatildi{f' ({user})' if user else ''}. Telethon session dosyalari silindi.</p><p><a href='/login'>Tekrar giris</a></p>",
        ),
        content_type="text/html",
        charset="utf-8",
    )


async def handle_panel(request: web.Request) -> web.Response:
    session = await get_session(request)
    user = session.get("user")
    slug = session.get("slug")
    if not user or not slug:
        raise web.HTTPFound(location="/login")

    sessions_dir = _sessions_dir()
    session_path = sessions_dir / f"{slug}.session"
    has_session = session_path.is_file()
    cfg_path = _forwarding_config_path()
    body = f"""
<p>Giris: <strong>{user}</strong> (session dosyasi: <code>sessions/{slug}.session</code>)</p>
<div class="card">
<h2>Bot chat ID ayarlari</h2>
<p>OCR/mesajlar icin yetkili chat ID listesi ve opsiyonel yonlendirme hedefleri. Kayit <code>{cfg_path.name}</code> dosyasina yazilir.</p>
<p class="hint warn" id="botEnvLock"></p>
<label>Yetkili chat ID'ler (bos = herkes)</label>
<p class="hint">Virgul veya bosluk ile ayirin. Gruba botu ekleyip bir mesajda chat id ogrenin.</p>
<textarea id="authChats" placeholder="-1001234567890, -491234567"></textarea>
<label>OCR kopyasi hedef chat ID (bos = kapali)</label>
<p class="hint">Bot, OCR metnini bu chat'e de gonderir (<code>FORWARD_CHAT_ID</code> ile ayni).</p>
<input id="forwardChat" type="text" placeholder="-1001234567890"/>
<label>Sadece bu kaynak chat ID'de oto yonlendirme (bos = tum yetkili chatler)</label>
<input id="forwardOnly" type="text" placeholder="-491234567"/>
<button type="button" id="btnSaveBot">Chat ayarlarini kaydet</button>
<p class="hint" id="botSaveOut"></p>
</div>
<div class="card">
<h2>Telethon baglanti</h2>
<p>API bilgisi env: <code>TELETHON_API_ID</code>, <code>TELETHON_API_HASH</code></p>
<p>Mevcut session dosyasi: <strong>{'var' if has_session else 'yok'}</strong></p>
<label>Telefon (+90...)</label>
<input id="phone" type="text" placeholder="+905551234567"/>
<button type="button" id="btnSend">Kod gonder</button>
<label>Kod</label>
<input id="code" type="text" placeholder="Telegram kodu"/>
<button type="button" id="btnCode">Giris (kod)</button>
<label>2FA sifresi (gerekirse)</label>
<input id="pwd2fa" type="password"/>
<button type="button" id="btn2fa">2FA onayla</button>
<div id="out" class="msg" style="margin-top:1rem;"></div>
</div>
<p><a href="/logout">Cikis yap (session dosyasini da siler)</a></p>
<script>
const out = document.getElementById('out');
function show(t) {{ out.textContent = t; }}
async function post(url, body) {{
  const r = await fetch(url, {{ method: 'POST', headers: {{'Content-Type':'application/json'}}, body: JSON.stringify(body) }});
  const j = await r.json().catch(() => ({{}}));
  if (!r.ok) throw new Error(j.error || r.statusText);
  return j;
}}
document.getElementById('btnSend').onclick = async () => {{
  try {{
    const phone = document.getElementById('phone').value.trim();
    const j = await post('/api/telethon/send_code', {{ phone }});
    show(JSON.stringify(j, null, 2));
  }} catch(e) {{ show('Hata: ' + e.message); }}
}};
document.getElementById('btnCode').onclick = async () => {{
  try {{
    const code = document.getElementById('code').value.trim();
    const j = await post('/api/telethon/confirm_code', {{ code }});
    show(JSON.stringify(j, null, 2));
  }} catch(e) {{ show('Hata: ' + e.message); }}
}};
document.getElementById('btn2fa').onclick = async () => {{
  try {{
    const password = document.getElementById('pwd2fa').value;
    const j = await post('/api/telethon/confirm_password', {{ password }});
    show(JSON.stringify(j, null, 2));
  }} catch(e) {{ show('Hata: ' + e.message); }}
}};
const botOut = document.getElementById('botSaveOut');
const botEnvEl = document.getElementById('botEnvLock');
async function loadBotSettings() {{
  try {{
    const r = await fetch('/api/bot-settings');
    const j = await r.json().catch(() => ({{}}));
    if (!r.ok) throw new Error(j.error || r.statusText);
    document.getElementById('authChats').value = j.authorized_chat_ids || '';
    document.getElementById('forwardChat').value = j.forward_chat_id || '';
    document.getElementById('forwardOnly').value = j.forward_only_source_chat_id || '';
    const L = j.env_lock || {{}};
    const bits = [];
    if (L.authorized_chat_ids) bits.push('AUTHORIZED_CHAT_IDS');
    if (L.forward_chat_id) bits.push('FORWARD_CHAT_ID');
    if (L.forward_only_source_chat_id) bits.push('FORWARD_ONLY_SOURCE_CHAT_ID');
    botEnvEl.textContent = bits.length
      ? 'Railway/env bu alanlari eziyor: ' + bits.join(', ') + ' — panelden kayitsa dosyaya yazilir ama bot env degerini kullanir.'
      : '';
  }} catch (e) {{ botEnvEl.textContent = 'Ayarlar yuklenemedi: ' + e.message; }}
}}
document.getElementById('btnSaveBot').onclick = async () => {{
  try {{
    botOut.textContent = 'Kaydediliyor...';
    const body = {{
      authorized_chat_ids: document.getElementById('authChats').value.trim(),
      forward_chat_id: document.getElementById('forwardChat').value.trim(),
      forward_only_source_chat_id: document.getElementById('forwardOnly').value.trim(),
    }};
    const r = await fetch('/api/bot-settings', {{ method: 'POST', headers: {{'Content-Type':'application/json'}}, body: JSON.stringify(body) }});
    const j = await r.json().catch(() => ({{}}));
    if (!r.ok) throw new Error(j.error || r.statusText);
    botOut.textContent = 'Kaydedildi: ' + (j.path || '');
    loadBotSettings();
  }} catch (e) {{ botOut.textContent = 'Hata: ' + e.message; }}
}};
loadBotSettings();
</script>
"""
    return web.Response(text=_html_page("Telethon panel", body), content_type="text/html", charset="utf-8")


async def _require_panel_user(request: web.Request) -> tuple[str, str]:
    session = await get_session(request)
    user = session.get("user")
    slug = session.get("slug")
    if not user or not slug:
        raise web.HTTPUnauthorized()
    return str(user), str(slug)


async def api_send_code(request: web.Request) -> web.Response:
    if TelegramClient is None:
        return web.json_response({"error": "telethon kurulu degil"}, status=500)
    user, slug = await _require_panel_user(request)
    try:
        payload = await request.json()
    except Exception:
        return web.json_response({"error": "json body gerekli"}, status=400)
    phone = str(payload.get("phone", "")).strip()
    if not phone:
        return web.json_response({"error": "phone gerekli"}, status=400)

    api_id, api_hash = _telethon_api()
    sessions_dir = _sessions_dir()
    session_base = str((sessions_dir / slug).resolve())

    pending = request.app.setdefault("telethon_pending", {})
    if slug in pending:
        old = pending[slug].get("client")
        if old:
            try:
                await old.disconnect()
            except Exception:
                pass

    client = TelegramClient(session_base, api_id, api_hash)
    await client.connect()
    await client.send_code_request(phone)
    pending[slug] = {"client": client, "phone": phone}
    return web.json_response({"ok": True, "user": user, "session_file": f"sessions/{slug}.session", "phone_sent": True})


async def api_confirm_code(request: web.Request) -> web.Response:
    if TelegramClient is None:
        return web.json_response({"error": "telethon kurulu degil"}, status=500)
    user, slug = await _require_panel_user(request)
    try:
        payload = await request.json()
    except Exception:
        return web.json_response({"error": "json body gerekli"}, status=400)
    code = str(payload.get("code", "")).strip()
    if not code:
        return web.json_response({"error": "code gerekli"}, status=400)

    pending = request.app.get("telethon_pending", {})
    entry = pending.get(slug)
    if not entry:
        return web.json_response({"error": "once /api/telethon/send_code cagirin"}, status=400)
    client: TelegramClient = entry["client"]
    phone = entry["phone"]

    try:
        await client.sign_in(phone=phone, code=code)
    except SessionPasswordNeededError:
        return web.json_response({"ok": True, "needs_password": True})
    except Exception as exc:
        return web.json_response({"error": str(exc)}, status=400)

    await client.disconnect()
    del pending[slug]

    sessions_dir = _sessions_dir()
    active = _active_session_file()
    session_base = str((sessions_dir / slug).resolve())
    active.write_text(session_base + "\n", encoding="utf-8")

    return web.json_response(
        {
            "ok": True,
            "authorized": True,
            "session_file": str((sessions_dir / f"{slug}.session").resolve()),
            "active_marker_written": str(active),
        }
    )


async def api_confirm_password(request: web.Request) -> web.Response:
    if TelegramClient is None:
        return web.json_response({"error": "telethon kurulu degil"}, status=500)
    user, slug = await _require_panel_user(request)
    try:
        payload = await request.json()
    except Exception:
        return web.json_response({"error": "json body gerekli"}, status=400)
    password = str(payload.get("password", ""))
    pending = request.app.get("telethon_pending", {})
    entry = pending.get(slug)
    if not entry:
        return web.json_response({"error": "once kod adimini baslatin"}, status=400)
    client: TelegramClient = entry["client"]

    try:
        await client.sign_in(password=password)
    except Exception as exc:
        return web.json_response({"error": str(exc)}, status=400)

    await client.disconnect()
    del pending[slug]

    active = _active_session_file()
    sessions_dir = _sessions_dir()
    session_base = str((sessions_dir / slug).resolve())
    active.write_text(session_base + "\n", encoding="utf-8")

    return web.json_response(
        {
            "ok": True,
            "authorized": True,
            "session_file": str((sessions_dir / f"{slug}.session").resolve()),
            "active_marker_written": str(active),
        }
    )


async def api_bot_settings_get(request: web.Request) -> web.Response:
    await _require_panel_user(request)
    path = _forwarding_config_path()
    data: dict = {}
    if path.is_file():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                data = loaded
        except Exception:
            pass

    def _s(key: str) -> str:
        v = data.get(key, "")
        return str(v).strip() if v is not None else ""

    return web.json_response(
        {
            "authorized_chat_ids": _s("authorized_chat_ids"),
            "forward_chat_id": _s("forward_chat_id"),
            "forward_only_source_chat_id": _s("forward_only_source_chat_id"),
            "file_path": str(path),
            "env_lock": {
                "authorized_chat_ids": bool(os.getenv("AUTHORIZED_CHAT_IDS", "").strip()),
                "forward_chat_id": bool(os.getenv("FORWARD_CHAT_ID", "").strip()),
                "forward_only_source_chat_id": bool(os.getenv("FORWARD_ONLY_SOURCE_CHAT_ID", "").strip()),
            },
        }
    )


async def api_bot_settings_post(request: web.Request) -> web.Response:
    await _require_panel_user(request)
    try:
        payload = await request.json()
        if not isinstance(payload, dict):
            return web.json_response({"error": "json nesnesi gerekli"}, status=400)
    except Exception:
        return web.json_response({"error": "json body gerekli"}, status=400)

    path = _forwarding_config_path()
    existing: dict = {}
    if path.is_file():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                existing = loaded
        except Exception:
            existing = {}

    for key in ("authorized_chat_ids", "forward_chat_id", "forward_only_source_chat_id"):
        if key in payload:
            existing[key] = str(payload.get(key, "") or "").strip()

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(existing, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    try:
        from ocr import configure_runtime_settings

        configure_runtime_settings()
    except Exception as exc:
        return web.json_response({"ok": True, "path": str(path), "reload_warning": str(exc)})

    return web.json_response({"ok": True, "path": str(path)})


def _fernet_key_from_seed(seed: str) -> bytes:
    """Herhangi bir metinden Fernet uyumlu 32 bayt anahtar (urlsafe b64)."""
    digest = hashlib.sha256(seed.encode("utf-8")).digest()
    key = base64.urlsafe_b64encode(digest)
    Fernet(key)
    return key


def _cookie_fernet_key_bytes() -> bytes:
    """
    Oncelik: PANEL_FERNET_KEY (Fernet.generate_key ciktisi, urlsafe b64, 44 karakter civari).
    Gecersizse: bu metinden turetilir (cokmez).
    Yoksa: TELEGRAM_BOT_TOKEN / SECRET_KEY / RAILWAY_ENVIRONMENT seed.
    Hicbiri yoksa: rastgele.
    """
    explicit = os.getenv("PANEL_FERNET_KEY", "").strip()
    if explicit:
        try:
            key_bytes = explicit.encode("ascii")
            Fernet(key_bytes)
            return key_bytes
        except (ValueError, UnicodeEncodeError):
            print(
                "UYARI: PANEL_FERNET_KEY Fernet icin gecersiz (32 bayt urlsafe b64 degil); "
                "degerden turetilen anahtar kullaniliyor."
            )
            return _fernet_key_from_seed("panel_fernet_explicit::" + explicit)

    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if token:
        return _fernet_key_from_seed(token + "::dekmenager_panel_v1")

    for env_name in ("SECRET_KEY", "RAILWAY_ENVIRONMENT"):
        seed = os.getenv(env_name, "").strip()
        if seed:
            return _fernet_key_from_seed(seed + "::panel_cookie")

    print(
        "UYARI: PANEL_FERNET_KEY / TELEGRAM_BOT_TOKEN / SECRET_KEY bos; "
        "rastgele cookie anahtari (her restartta panel oturumu sifirlanir). "
        "Uretmek icin: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
    )
    return Fernet.generate_key()


def create_app() -> web.Application:
    app = web.Application()
    # aiohttp-session >=2.x: bytes verilirse tekrar b64 encode edilir; hazir Fernet anahtarini
    # Fernet ORNEGI olarak ver (cift encode hatasi olmasin).
    try:
        key_bytes = _cookie_fernet_key_bytes()
        fernet_obj = Fernet(key_bytes)
        setup(app, EncryptedCookieStorage(fernet_obj))
    except Exception as exc:
        print(
            f"UYARI: EncryptedCookieStorage baslatilamadi ({exc!r}); "
            "SimpleCookieStorage (sifresiz oturum cookie'si) kullaniliyor."
        )
        setup(app, SimpleCookieStorage())

    app.router.add_get("/health", handle_health)
    app.router.add_get("/", handle_login_get)
    app.router.add_get("/login", handle_login_get)
    app.router.add_post("/login", handle_login_post)
    app.router.add_get("/logout", handle_logout)
    app.router.add_get("/panel", handle_panel)
    app.router.add_post("/api/telethon/send_code", api_send_code)
    app.router.add_post("/api/telethon/confirm_code", api_confirm_code)
    app.router.add_post("/api/telethon/confirm_password", api_confirm_password)
    app.router.add_get("/api/bot-settings", api_bot_settings_get)
    app.router.add_post("/api/bot-settings", api_bot_settings_post)

    app["telethon_pending"] = {}
    return app


def run_panel_blocking(host: str = "0.0.0.0", port: int | None = None) -> None:
    p = port if port is not None else int(os.environ.get("PORT", "8080"))
    web.run_app(create_app(), host=host, port=p, access_log=None)
