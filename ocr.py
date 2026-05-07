import base64
import io
import json
import os
from pathlib import Path
import re
import time
import unicodedata
from typing import Any

import requests
try:
    from pypdf import PdfReader  # type: ignore[reportMissingImports]
except Exception:
    PdfReader = None
try:
    from telethon import TelegramClient  # type: ignore[reportMissingImports]
except Exception:
    TelegramClient = None


TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()

VISION_API_KEY = os.getenv("VISION_API_KEY", "").strip()

# Opsiyonel: OCR sonucunu ek olarak bu chat'e de yönlendir.
# Boş bırakılırsa sadece fotoğrafı atan kişiye cevap gider.
FORWARD_CHAT_ID = os.getenv("FORWARD_CHAT_ID", "").strip()
FORWARD_ONLY_SOURCE_CHAT_ID = os.getenv("FORWARD_ONLY_SOURCE_CHAT_ID", "").strip()

BOT_API_BASE = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"
FILE_API_BASE = f"https://api.telegram.org/file/bot{TELEGRAM_BOT_TOKEN}"
VISION_URL = f"https://vision.googleapis.com/v1/images:annotate?key={VISION_API_KEY}"
PERSON_LIST_FILE = os.getenv("PERSON_LIST_FILE", "person_list.txt")
ACCOUNTS_RAW_FILE = os.getenv("ACCOUNTS_RAW_FILE", "hesaplar.txt")
ACCOUNTS_FORMATTED_FILE = os.getenv("ACCOUNTS_FORMATTED_FILE", "hesaplar_formatted.txt")
FORWARDING_CONFIG_FILE = os.getenv("FORWARDING_CONFIG_FILE", "forwarding_config.json")
AUTHORIZED_CHAT_IDS: set[str] = set()

PERSON_DEPARTMENT_LIST: list[tuple[str, str]] = [
    ("Serhat Talat Tas", "Ayze"),
    ("evra ekin kabu", "KAYA"),
    ("ILKNUR DEMIRCAN", "Roma"),
    ("afranur atakul", "KAYA"),
    ("emre ulupinar", "POLAT"),
    ("PINAR BUYUKELCI", "Ayze"),
    ("HATIP SURE", "Kaplan"),
    ("NEDIM BAYCAN", "Kaplan"),
    ("YILMAZ ISIK", "Kaplan"),
    ("BARAN BAYCAN", "Kaplan"),
    ("AHMET BAYCAN", "Kaplan"),
    ("SUATCAN GUMUSTEKIN", "Amca"),
    ("yusuf sensoy", "POLAT"),
    ("EMRE TASTAN", "Carlos"),
    ("ARDA EFECAN IRIZ", "Carlos"),
    ("HUSEYIN TORUN", "Carlos"),
    ("SAHIN YAZAR", "Amca"),
    ("Selahattin Yavuz", "Roma"),
    ("HALIL CAN ADAMHASAN", "POLAT"),
    ("merve cay cetinkaya", "Barcelona"),
    ("muharrem bozkurt", "Truva"),
    ("DERVIS MUHAMMET SENSOY", "POLAT"),
    ("eymen yurdunuseven", "Tahran"),
    ("GULLU TASCI", "KIBRIS"),
    ("Ahmet mert Cakir", "Truva"),
    ("HUSNIYE SARIKAYA", "Tokyo"),
    ("FATMAGUL SARIKAYA", "Tokyo"),
    ("ANIL DURNA", "YAVUZ"),
    ("CEYLAN KAPLAN", "Tokyo"),
    ("nisa dogan", "KIBRIS"),
    ("FATMAGUL SARIAKAYA", "Tokyo"),
    ("IBRAHIM TUTAK", "Tokyo"),
    ("efe promax", "KAYA"),
    ("Feyyaz Akin", "HERMES"),
    ("RAMAZAN AKIN", "HERMES"),
    ("HARUN COBAN", "HERMES"),
    ("SABIHE AKIN", "HERMES"),
    ("GUCLULER TARIM HAYVANCILIK GIDA INSAAT ELEKTRIK ELEKTRONIK M", "ANKARA"),
    ("GUCLULER TARIM HAYVANCILIK GID SA", "ANKARA"),
    ("YUNUS EMRE ELMAS", "Amca"),
    ("ahmet kaan kuru", "Aslan"),
    ("yusuf gursel anac", "Aslan"),
]


def load_person_list_from_file(file_path: str) -> list[tuple[str, str]]:
    if not os.path.exists(file_path):
        return []

    with open(file_path, "r", encoding="utf-8") as f:
        lines = [line.strip() for line in f if line.strip()]

    loaded: list[tuple[str, str]] = []
    i = 0
    while i + 2 < len(lines):
        name_line = lines[i]
        code_line = lines[i + 1]
        dept_line = lines[i + 2]

        # Beklenen format: isim / kod / "Departman <tab> ..."
        # Kod satiri yoksa kaydi atla.
        if "-" not in code_line and "HRMS" not in code_line and "BRZL" not in code_line and "ALS1" not in code_line:
            i += 1
            continue

        department = parse_department_line(dept_line)
        if department:
            loaded.append((name_line, department))
        i += 3

    return loaded


def parse_department_line(dept_line: str) -> str:
    if "\t" in dept_line:
        return dept_line.split("\t")[0].strip()

    # Tab yoksa "Departman 2 0 ₺0 Aktif" gibi satırlarda
    # sona gelen sayisal/statik kolonlari temizler.
    cleaned = re.sub(r"\s+\d+\s+\d+\s+₺?\d+\s+(Aktif|Pasif)\s*$", "", dept_line, flags=re.IGNORECASE)
    return cleaned.strip()


def normalize_text(value: str) -> str:
    lowered = value.casefold().strip()
    translit_map = str.maketrans(
        {
            "ı": "i",
            "ş": "s",
            "ğ": "g",
            "ü": "u",
            "ö": "o",
            "ç": "c",
        }
    )
    lowered = lowered.translate(translit_map)
    lowered = unicodedata.normalize("NFKD", lowered)
    lowered = lowered.encode("ascii", "ignore").decode("ascii")
    lowered = re.sub(r"\s+", " ", lowered)
    return lowered.strip()


def normalize_iban(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "", value).upper()


def is_iban_line(value: str) -> bool:
    candidate = normalize_iban(value)
    return candidate.startswith("TR") and len(candidate) >= 16


def is_metadata_line(value: str) -> bool:
    low = normalize_text(value)
    blocked = (
        "gunluk islem limiti",
        "maksimum islem tutari",
        "minimum islem tutari",
        "gunluk toplam",
        "herkese acik",
        "fast acik",
        "fast kapali",
        "hesap bilgileri",
        "site erisimi",
        "durum",
        "islemler",
        "limitler",
    )
    return any(token in low for token in blocked)


def parse_accounts_from_raw(file_path: str) -> list[tuple[str, str, str]]:
    if not os.path.exists(file_path):
        return []

    with open(file_path, "r", encoding="utf-8") as f:
        lines = [line.strip() for line in f if line.strip()]

    loaded: list[tuple[str, str, str]] = []
    seen: set[tuple[str, str, str]] = set()

    # Daha güvenli parse: IBAN satırlarını anchor al, üstteki 2 satırdan ad/departman çek.
    for i, current in enumerate(lines):
        if not is_iban_line(current):
            continue

        if i < 3:
            continue

        normalized_iban = normalize_iban(current)
        full_name = lines[i - 2]
        department = lines[i - 3]

        if is_metadata_line(full_name) or is_metadata_line(department):
            continue

        if len(normalize_text(full_name)) < 3 or len(normalize_text(department)) < 2:
            continue

        key = (normalize_text(full_name), normalize_text(department), normalized_iban)
        if key in seen:
            continue
        seen.add(key)
        loaded.append((full_name, department, normalized_iban))

    return loaded


def parse_accounts_from_text(content: str) -> list[tuple[str, str, str, str]]:
    lines = [line.strip() for line in content.splitlines() if line.strip()]
    parsed: list[tuple[str, str, str, str]] = []
    seen: set[tuple[str, str, str]] = set()

    for i, current in enumerate(lines):
        if not is_iban_line(current):
            continue
        if i < 3:
            continue

        department = lines[i - 3]
        full_name = lines[i - 2]
        bank_name = lines[i - 1]
        iban = normalize_iban(current)

        if (
            is_metadata_line(department)
            or is_metadata_line(full_name)
            or is_metadata_line(bank_name)
        ):
            continue

        if len(normalize_text(department)) < 2 or len(normalize_text(full_name)) < 3:
            continue

        key = (normalize_text(full_name), normalize_text(department), iban)
        if key in seen:
            continue
        seen.add(key)
        parsed.append((department, full_name, bank_name, iban))

    return parsed


def append_accounts_to_raw_file(accounts: list[tuple[str, str, str, str]], file_path: str) -> int:
    if not accounts:
        return 0

    existing = parse_accounts_from_raw(file_path)
    existing_keys = {(normalize_text(name), normalize_text(dep), iban) for name, dep, iban in existing}

    added = 0
    with open(file_path, "a", encoding="utf-8") as f:
        for department, full_name, bank_name, iban in accounts:
            key = (normalize_text(full_name), normalize_text(department), iban)
            if key in existing_keys:
                continue
            f.write(f"{department}\n{full_name}\n{bank_name}\n{iban}\n\n")
            existing_keys.add(key)
            added += 1
    return added


def write_formatted_accounts_file(accounts: list[tuple[str, str, str]], file_path: str) -> None:
    lines = ["# Departman\tAd Soyad\tIBAN", ""]
    for full_name, department, iban in accounts:
        lines.append(f"{department}\t{full_name}\t{iban}")
    with open(file_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def load_accounts_from_formatted_file(file_path: str) -> list[tuple[str, str, str]]:
    if not os.path.exists(file_path):
        return []

    loaded: list[tuple[str, str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    with open(file_path, "r", encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            parts = [part.strip() for part in line.split("\t")]
            if len(parts) < 3:
                continue
            department, full_name, iban_raw = parts[0], parts[1], parts[2]
            iban = normalize_iban(iban_raw)
            if not is_iban_line(iban):
                continue
            key = (normalize_text(full_name), normalize_text(department), iban)
            if key in seen:
                continue
            seen.add(key)
            loaded.append((full_name, department, iban))
    return loaded


def load_accounts() -> list[tuple[str, str, str]]:
    # Ana kaynak ham dosya olsun; format dosyasini her seferinde tazele.
    raw_accounts = parse_accounts_from_raw(ACCOUNTS_RAW_FILE)
    if raw_accounts:
        write_formatted_accounts_file(raw_accounts, ACCOUNTS_FORMATTED_FILE)
        return raw_accounts

    # Ham kaynak yoksa/okunamazsa formatli dosyadan devam et.
    formatted_accounts = load_accounts_from_formatted_file(ACCOUNTS_FORMATTED_FILE)
    return formatted_accounts


def find_person_matches(content: str) -> list[tuple[str, str]]:
    normalized_content = normalize_text(content)
    content_words = set(normalized_content.split())
    content_iban = normalize_iban(content)
    found: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()

    accounts = load_accounts()
    all_persons: list[tuple[str, str, str]] = []

    for name, dep, iban in accounts:
        all_persons.append((name, dep, iban))

    for name, dep in PERSON_DEPARTMENT_LIST + load_person_list_from_file(PERSON_LIST_FILE):
        all_persons.append((name, dep, ""))

    for raw_name, department, iban in all_persons:
        name_key = normalize_text(raw_name)
        dep_key = normalize_text(department)
        if not name_key:
            continue

        iban_match = bool(iban) and iban in content_iban
        direct_match = name_key in normalized_content
        fuzzy_match = False

        if not direct_match and not iban_match:
            name_words = [w for w in name_key.split() if len(w) >= 3]
            if name_words:
                matched_words = sum(1 for w in name_words if w in content_words)
                ratio = matched_words / len(name_words)
                first_words = name_words[:2]
                first_words_ok = len(first_words) == 2 and all(w in content_words for w in first_words)

                # Uzun ticari isimlerde OCR kısaltmalarını yakalamak için daha toleranslı kural:
                # - en az 3 kelime tutmalı ve %40 oranı geçmeli, veya
                # - ilk iki kelime + toplam en az 3 kelime tutmalı.
                fuzzy_match = (matched_words >= 3 and ratio >= 0.4) or (first_words_ok and matched_words >= 3)

        if iban_match or direct_match or fuzzy_match:
            uniq_key = (name_key, dep_key)
            if uniq_key not in seen:
                seen.add(uniq_key)
                found.append((raw_name, department))
    return found


def build_match_reply(matches: list[tuple[str, str]]) -> str:
    lines = [f"{name} - {department} departmanina ait" for name, department in matches]
    return "\n".join(lines)


def tg_request(method: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    response = requests.post(f"{BOT_API_BASE}/{method}", json=payload or {}, timeout=60)
    response.raise_for_status()
    data = response.json()
    if not data.get("ok"):
        raise RuntimeError(f"Telegram API error ({method}): {data}")
    return data


def send_message(
    chat_id: int | str,
    text: str,
    reply_to_message_id: int | None = None,
    parse_mode: str | None = None,
) -> None:
    chunk_size = 3800
    chunks = [text[i : i + chunk_size] for i in range(0, len(text), chunk_size)] or [text]
    for idx, chunk in enumerate(chunks):
        payload: dict[str, Any] = {"chat_id": chat_id, "text": chunk}
        if idx == 0 and reply_to_message_id:
            payload["reply_to_message_id"] = reply_to_message_id
        if parse_mode:
            payload["parse_mode"] = parse_mode
        tg_request("sendMessage", payload)


def unmatched_department_message() -> str:
    return (
        "Departman eşleşmesi yapılamadı lütfen işlemi manuel olarak kontrol ediniz\n\n"
        "<code>Alıcı bize ait değildir</code>"
    )


def account_add_usage_message() -> str:
    return (
        "Hesap eklemek icin komut:\n"
        "/hesapekle\n\n"
        "Departman\n"
        "Ad Soyad\n"
        "Banka\n"
        "TR ile baslayan IBAN\n\n"
        "Bir mesajda birden fazla blok gonderebilirsin.\n\n"
        "Hesap silmek icin:\n"
        "/hesapsil TRxxxxxxxxxxxxxxxxxxxxxxxx\n\n"
        "Departmana gore silmek icin:\n"
        "/departmansil DepartmanAdi\n\n"
        "Hesap listelemek icin:\n"
        "/hesapliste\n"
        "/hesapliste DepartmanAdi"
    )


def delete_accounts_by_iban(file_path: str, iban_values: list[str]) -> int:
    if not os.path.exists(file_path):
        return 0

    target_ibans = {normalize_iban(v) for v in iban_values if is_iban_line(v)}
    if not target_ibans:
        return 0

    with open(file_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    removed_count = 0
    kept: list[str] = []
    i = 0
    while i < len(lines):
        if i + 3 < len(lines):
            department = lines[i].strip()
            full_name = lines[i + 1].strip()
            bank_name = lines[i + 2].strip()
            iban_line = lines[i + 3].strip()
            normalized_iban = normalize_iban(iban_line)
            if (
                department
                and full_name
                and bank_name
                and is_iban_line(normalized_iban)
                and normalized_iban in target_ibans
            ):
                removed_count += 1
                i += 4
                while i < len(lines) and not lines[i].strip():
                    i += 1
                continue

        kept.append(lines[i])
        i += 1

    if removed_count > 0:
        with open(file_path, "w", encoding="utf-8") as f:
            f.writelines(kept)

    return removed_count


def delete_accounts_by_department(file_path: str, department_name: str) -> int:
    if not os.path.exists(file_path):
        return 0

    dep_key = normalize_text(department_name)
    if not dep_key:
        return 0

    with open(file_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    removed_count = 0
    kept: list[str] = []
    i = 0
    while i < len(lines):
        if i + 3 < len(lines):
            department = lines[i].strip()
            full_name = lines[i + 1].strip()
            bank_name = lines[i + 2].strip()
            iban_line = lines[i + 3].strip()
            normalized_iban = normalize_iban(iban_line)
            if (
                department
                and full_name
                and bank_name
                and is_iban_line(normalized_iban)
                and normalize_text(department) == dep_key
            ):
                removed_count += 1
                i += 4
                while i < len(lines) and not lines[i].strip():
                    i += 1
                continue

        kept.append(lines[i])
        i += 1

    if removed_count > 0:
        with open(file_path, "w", encoding="utf-8") as f:
            f.writelines(kept)

    return removed_count


def list_accounts_message(department_filter: str = "") -> str:
    accounts = load_accounts()
    if not accounts:
        return "Kayitli hesap bulunamadi."

    filtered = accounts
    if department_filter.strip():
        dep_key = normalize_text(department_filter)
        filtered = [
            (name, dep, iban)
            for name, dep, iban in accounts
            if dep_key in normalize_text(dep)
        ]

    if not filtered:
        return "Filtreye uygun hesap bulunamadi."

    lines = [f"Toplam {len(filtered)} hesap bulundu."]
    for name, dep, iban in filtered:
        lines.append(f"{dep} | {name} | {iban}")
    return "\n".join(lines)


def load_forwarding_config(file_path: str) -> dict[str, Any]:
    if not os.path.exists(file_path):
        return {}
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {}


def merge_forwarding_config_from_env(base: dict[str, Any]) -> dict[str, Any]:
    cfg: dict[str, Any] = dict(base)
    raw_json = os.getenv("FORWARDING_CONFIG_JSON", "").strip()
    if raw_json:
        try:
            extra = json.loads(raw_json)
            if isinstance(extra, dict):
                cfg.update(extra)
        except Exception:
            pass

    enabled_raw = os.getenv("FORWARDING_ENABLED", "").strip().lower()
    if enabled_raw in ("1", "true", "yes", "on"):
        cfg["enabled"] = True
    elif enabled_raw in ("0", "false", "no", "off"):
        cfg["enabled"] = False

    if os.getenv("TELETHON_API_ID", "").strip():
        cfg["api_id"] = os.getenv("TELETHON_API_ID", "").strip()
    if os.getenv("TELETHON_API_HASH", "").strip():
        cfg["api_hash"] = os.getenv("TELETHON_API_HASH", "").strip()
    if os.getenv("TELETHON_SESSION_NAME", "").strip():
        cfg["session_name"] = os.getenv("TELETHON_SESSION_NAME", "").strip()
    if os.getenv("TELETHON_PHONE", "").strip():
        cfg["phone"] = os.getenv("TELETHON_PHONE", "").strip()
    auth_env = os.getenv("AUTHORIZED_CHAT_IDS", "").strip()
    if auth_env:
        cfg["authorized_chat_ids"] = auth_env

    # Web panelden yazilan aktif Telethon session yolu (env ile dosya adi degistirilebilir)
    active_marker = os.getenv("ACTIVE_TELETHON_SESSION_FILE", "active_telethon_session.txt").strip()
    if active_marker:
        try:
            active_path = Path(active_marker)
            if active_path.is_file():
                first_line = active_path.read_text(encoding="utf-8").strip().splitlines()[0].strip()
                if first_line:
                    cfg["session_name"] = first_line
        except Exception:
            pass

    return cfg


def get_effective_forwarding_config() -> dict[str, Any]:
    return merge_forwarding_config_from_env(load_forwarding_config(FORWARDING_CONFIG_FILE))


def parse_chat_id_list(raw_value: str) -> set[str]:
    values = re.split(r"[\s,;]+", str(raw_value or "").strip())
    return {value.strip() for value in values if value.strip()}


def configure_runtime_settings() -> None:
    global TELEGRAM_BOT_TOKEN, BOT_API_BASE, FILE_API_BASE, AUTHORIZED_CHAT_IDS, VISION_API_KEY, VISION_URL

    config = get_effective_forwarding_config()

    env_token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    file_token = str(config.get("telegram_bot_token", "")).strip()
    if env_token:
        TELEGRAM_BOT_TOKEN = env_token
    elif file_token:
        TELEGRAM_BOT_TOKEN = file_token

    BOT_API_BASE = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"
    FILE_API_BASE = f"https://api.telegram.org/file/bot{TELEGRAM_BOT_TOKEN}"

    env_ids = parse_chat_id_list(os.getenv("AUTHORIZED_CHAT_IDS", ""))
    file_ids = parse_chat_id_list(str(config.get("authorized_chat_ids", "")))
    AUTHORIZED_CHAT_IDS = env_ids or file_ids

    env_vision = os.getenv("VISION_API_KEY", "").strip()
    if env_vision:
        VISION_API_KEY = env_vision
    VISION_URL = f"https://vision.googleapis.com/v1/images:annotate?key={VISION_API_KEY}"


def build_match_line(name: str, department: str) -> str:
    return f"{name} - {department} departmanina ait"


def find_department_group_name(department: str, group_names: list[str]) -> str | None:
    dep_key = normalize_text(department)
    for group_name in group_names:
        normalized_group = normalize_text(group_name)
        if dep_key and dep_key in normalized_group and "dp" in normalized_group and "havale" in normalized_group:
            return group_name
    return None


def has_multiple_departments(matches: list[tuple[str, str]]) -> bool:
    distinct_departments = {normalize_text(department) for _, department in matches if normalize_text(department)}
    return len(distinct_departments) > 1


def is_forward_allowed_for_chat(chat_id: int | str | None) -> bool:
    if chat_id is None:
        return False
    allowed = FORWARD_ONLY_SOURCE_CHAT_ID.strip()
    if not allowed:
        return True
    return str(chat_id).strip() == allowed


def is_chat_authorized(chat_id: int | str | None) -> bool:
    if chat_id is None:
        return False
    if not AUTHORIZED_CHAT_IDS:
        return True
    return str(chat_id).strip() in AUTHORIZED_CHAT_IDS


async def _forward_matches_via_telethon_async(
    matches: list[tuple[str, str]],
    source_text: str,
    source_media_bytes: bytes | None,
    source_media_name: str | None,
    config: dict[str, Any],
) -> list[str]:
    if TelegramClient is None:
        return []

    api_id_raw = config.get("api_id")
    api_hash = str(config.get("api_hash", "")).strip()
    session_name = str(config.get("session_name", "forwarding_user")).strip() or "forwarding_user"
    if not api_id_raw or not api_hash:
        return []

    try:
        api_id = int(api_id_raw)
    except Exception:
        return []

    client = TelegramClient(session_name, api_id, api_hash)
    sent_groups: list[str] = []
    try:
        await client.connect()
        if not await client.is_user_authorized():
            return []

        dialogs = await client.get_dialogs()
        group_names = [d.name or "" for d in dialogs if getattr(d, "is_group", False) or getattr(d, "is_channel", False)]
        grouped_messages: dict[str, str] = {}

        for name, department in matches:
            target_group = find_department_group_name(department, group_names)
            if not target_group:
                continue
            grouped_messages.setdefault(target_group, source_text)

        for dialog in dialogs:
            dialog_name = dialog.name or ""
            if dialog_name not in grouped_messages:
                continue
            text = grouped_messages[dialog_name]
            if source_media_bytes:
                media = io.BytesIO(source_media_bytes)
                media.name = source_media_name or "dekont.jpg"
                await client.send_file(
                    dialog.entity,
                    media,
                    caption=text or None,
                )
            else:
                await client.send_message(dialog.entity, text)
            sent_groups.append(dialog_name)
    finally:
        await client.disconnect()

    return sent_groups


def auto_forward_matches(
    matches: list[tuple[str, str]],
    source_text: str,
    source_chat_id: int | str | None,
    source_media_bytes: bytes | None = None,
    source_media_name: str | None = None,
) -> list[str]:
    if not matches:
        return []
    if not is_forward_allowed_for_chat(source_chat_id):
        return []
    if has_multiple_departments(matches):
        return []
    if not source_text.strip() and source_media_bytes is None:
        return []

    config = get_effective_forwarding_config()
    if not config.get("enabled", False):
        return []

    try:
        import asyncio

        return asyncio.run(
            _forward_matches_via_telethon_async(
                matches,
                source_text.strip(),
                source_media_bytes,
                source_media_name,
                config,
            )
        )
    except Exception:
        return []


def get_file_bytes(file_id: str) -> bytes:
    file_info = tg_request("getFile", {"file_id": file_id})
    file_path = file_info["result"]["file_path"]
    file_url = f"{FILE_API_BASE}/{file_path}"
    file_response = requests.get(file_url, timeout=60)
    file_response.raise_for_status()
    return file_response.content


def extract_text_from_pdf_locally(pdf_bytes: bytes) -> str:
    if PdfReader is None:
        raise RuntimeError("pypdf kurulu degil. Lutfen `pip install pypdf` komutunu calistir.")
    reader = PdfReader(io.BytesIO(pdf_bytes))
    parts: list[str] = []
    for page in reader.pages:
        text = page.extract_text() or ""
        text = text.strip()
        if text:
            parts.append(text)

    merged = "\n".join(parts).strip()
    if not merged:
        raise RuntimeError("PDF metni lokalde çıkarılamadı.")
    return merged


def extract_text_with_vision(image_bytes: bytes) -> str:
    encoded = base64.b64encode(image_bytes).decode("utf-8")
    payload = {
        "requests": [
            {
                "image": {"content": encoded},
                "features": [{"type": "DOCUMENT_TEXT_DETECTION"}],
            }
        ]
    }
    response = requests.post(VISION_URL, json=payload, timeout=90)
    try:
        data = response.json()
    except Exception:
        data = {"raw_text": response.text}

    if response.status_code >= 400:
        raise RuntimeError(
            f"Vision HTTP {response.status_code}: {data}"
        )

    responses = data.get("responses", [])
    if not responses:
        raise RuntimeError(f"Vision responses boş döndü: {data}")

    first = responses[0]
    if "error" in first:
        raise RuntimeError(f"Vision API hatası: {first['error']}")

    text = first.get("fullTextAnnotation", {}).get("text", "").strip()
    if not text:
        annotations = first.get("textAnnotations", [])
        if annotations:
            text = annotations[0].get("description", "").strip()
    if not text:
        raise RuntimeError("Vision OCR metin üretemedi.")
    return text


def handle_update(update: dict[str, Any]) -> None:
    message = update.get("message") or update.get("edited_message")
    if not message:
        return

    chat_id = message.get("chat", {}).get("id")
    message_id = message.get("message_id")
    photos = message.get("photo", [])
    document = message.get("document") or {}
    document_mime = (document.get("mime_type") or "").lower()
    is_pdf_document = document_mime == "application/pdf"
    is_image_document = document_mime.startswith("image/")
    text_content = message.get("text", "") or message.get("caption", "") or ""

    if not chat_id:
        return
    if not is_chat_authorized(chat_id):
        return

    if not photos and not is_pdf_document and not is_image_document and not text_content:
        return

    if text_content and not photos and not is_pdf_document and not is_image_document:
        normalized_text = text_content.strip()
        command_match = re.match(
            r"^/(hesapekle|hesapsil|hesapliste|departmansil)(?:@\w+)?\b",
            normalized_text,
            flags=re.IGNORECASE,
        )
        if command_match:
            command_name = command_match.group(1).casefold()
            command_text = normalized_text[command_match.end() :].strip()
            if command_name == "departmansil":
                if not command_text:
                    send_message(chat_id, "Kullanim: /departmansil DepartmanAdi", message_id)
                    return
                removed_count = delete_accounts_by_department(ACCOUNTS_RAW_FILE, command_text)
                if removed_count > 0:
                    load_accounts()
                    send_message(chat_id, f"{command_text} departmanindan {removed_count} hesap silindi.", message_id)
                else:
                    send_message(chat_id, "Bu departmanda silinecek hesap bulunamadi.", message_id)
                return

            if command_name == "hesapsil":
                iban_tokens = [normalize_iban(token) for token in re.findall(r"TR[0-9A-Za-z\s]{10,}", command_text)]
                if not iban_tokens and command_text:
                    iban_tokens = [normalize_iban(command_text)]
                removed_count = delete_accounts_by_iban(ACCOUNTS_RAW_FILE, iban_tokens)
                if removed_count > 0:
                    # load_accounts cagrisi format dosyasini da gunceller.
                    load_accounts()
                    send_message(chat_id, f"{removed_count} hesap silindi.", message_id)
                else:
                    send_message(chat_id, "Silinecek hesap bulunamadi. Ornek: /hesapsil TR...", message_id)
                return

            if command_name == "hesapliste":
                send_message(chat_id, list_accounts_message(command_text), message_id)
                return

            parsed_accounts = parse_accounts_from_text(command_text)
            if not parsed_accounts:
                send_message(chat_id, account_add_usage_message(), message_id)
                return
            added_count = append_accounts_to_raw_file(parsed_accounts, ACCOUNTS_RAW_FILE)
            if added_count > 0:
                send_message(chat_id, f"{added_count} yeni hesap eklendi.", message_id)
            else:
                send_message(chat_id, "Bu mesajdaki hesaplar zaten kayitli.", message_id)
            return

        if normalized_text.lower() in {"/start", "/help"}:
            send_message(chat_id, account_add_usage_message(), message_id)
            return

        parsed_accounts: list[tuple[str, str, str, str]] = []
        added_count = 0

        text_matches = find_person_matches(text_content)
        reply_parts: list[str] = []
        if added_count > 0:
            reply_parts.append(f"{added_count} yeni hesap eklendi.")
        elif parsed_accounts:
            reply_parts.append("Bu mesajdaki hesaplar zaten kayitli.")

        if text_matches:
            match_reply_text = build_match_reply(text_matches)
            reply_parts.append(match_reply_text)
            final_reply_text = "\n\n".join(reply_parts)
            send_message(chat_id, final_reply_text, message_id)
            if has_multiple_departments(text_matches):
                print("Oto yonlendirme atlandi: birden fazla departman eslesmesi var.")
                return
            forwarded_groups = auto_forward_matches(text_matches, text_content, chat_id)
            if forwarded_groups:
                print(f"Oto yonlendirme tamamlandi. Gruplar: {', '.join(forwarded_groups)}")
            else:
                print("Oto yonlendirme yapilmadi (eslesen grup/yetki/ayar kontrol edin).")
        else:
            if reply_parts:
                send_message(chat_id, "\n\n".join(reply_parts), message_id)
            else:
                send_message(
                    chat_id,
                    unmatched_department_message(),
                    message_id,
                    parse_mode="HTML",
                )
        return

    try:
        extracted_text = ""
        source_media_bytes: bytes | None = None
        source_media_name: str | None = None
        if is_pdf_document:
            file_id = document.get("file_id")
            if not file_id:
                raise RuntimeError("PDF dosyası alınamadı.")
            pdf_bytes = get_file_bytes(file_id)
            source_media_bytes = pdf_bytes
            source_media_name = (document.get("file_name") or "dekont.pdf").strip() or "dekont.pdf"
            extracted_text = extract_text_from_pdf_locally(pdf_bytes)
        elif is_image_document:
            file_id = document.get("file_id")
            if not file_id:
                raise RuntimeError("Gorsel dosyasi alinamadi.")
            image_bytes = get_file_bytes(file_id)
            source_media_bytes = image_bytes
            original_name = (document.get("file_name") or "").strip()
            source_media_name = original_name or "dekont.jpg"
            extracted_text = extract_text_with_vision(image_bytes)
        else:
            # Telegram photo listesinde son eleman genelde en yüksek çözünürlük.
            file_id = photos[-1]["file_id"]
            image_bytes = get_file_bytes(file_id)
            source_media_bytes = image_bytes
            source_media_name = "dekont.jpg"
            extracted_text = extract_text_with_vision(image_bytes)

        combined_text = f"{text_content}\n{extracted_text}".strip()
        matches = find_person_matches(combined_text)
        if matches:
            match_reply_text = build_match_reply(matches)
            send_message(chat_id, match_reply_text, message_id)
            if has_multiple_departments(matches):
                print("Oto yonlendirme atlandi: birden fazla departman eslesmesi var.")
                return
            forwarded_groups = auto_forward_matches(
                matches,
                text_content.strip(),
                chat_id,
                source_media_bytes,
                source_media_name,
            )
            if forwarded_groups:
                print(f"Oto yonlendirme tamamlandi. Gruplar: {', '.join(forwarded_groups)}")
            else:
                print("Oto yonlendirme yapilmadi (eslesen grup/yetki/ayar kontrol edin).")
        else:
            send_message(
                chat_id,
                unmatched_department_message(),
                message_id,
                parse_mode="HTML",
            )

        if FORWARD_CHAT_ID:
            send_message(FORWARD_CHAT_ID, f"Kaynak chat: {chat_id}\n\n{extracted_text}")
    except Exception as exc:
        send_message(chat_id, f"OCR hatasi: {exc}", message_id)


def _log_telethon_forwarding_startup() -> None:
    """Railway logunda neden forward olmayabilecegini hizli goster."""
    cfg = get_effective_forwarding_config()
    enabled = bool(cfg.get("enabled", False))
    api_id = str(cfg.get("api_id", "")).strip()
    api_hash = str(cfg.get("api_hash", "")).strip()
    api_ok = bool(api_id and api_hash)
    sn = str(cfg.get("session_name", "forwarding_user")).strip() or "forwarding_user"
    session_file = Path(sn + ".session") if not sn.endswith(".session") else Path(sn)
    session_ok = session_file.is_file()
    print(
        f"Telethon oto yonlendirme: FORWARDING_ENABLED etkisi enabled={enabled}, "
        f"api={'tamam' if api_ok else 'EKSIK'}, session_dosyasi={'var' if session_ok else 'YOK'} ({session_file})"
    )
    if enabled and not session_ok:
        print(
            "IPUCU: Panelden Telethon ile giris yapin; session kalici disk (volume) yoksa redeploy sonrasi "
            "dosya silinir. Grup adlari normalize edilmis olarak hem departman hem 'dp' hem 'havale' icermeli."
        )


def run() -> None:
    configure_runtime_settings()
    _log_telethon_forwarding_startup()
    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError("Telegram bot token bulunamadi. GUI'den veya TELEGRAM_BOT_TOKEN env ile ayarlayin.")
    if not VISION_API_KEY:
        print("UYARI: VISION_API_KEY bos; foto OCR calismayabilir. Railway'de env olarak tanimlayin.")
    print("Bot baslatildi. Fotograflari dinliyorum...")
    offset: int | None = None

    while True:
        try:
            payload: dict[str, Any] = {"timeout": 50}
            if offset is not None:
                payload["offset"] = offset

            response = requests.post(
                f"{BOT_API_BASE}/getUpdates",
                json=payload,
                timeout=60,
            )
            response.raise_for_status()
            data = response.json()

            if not data.get("ok"):
                raise RuntimeError(f"getUpdates hatasi: {data}")

            for update in data.get("result", []):
                offset = update["update_id"] + 1
                handle_update(update)
        except Exception as exc:
            print(f"Hata: {exc}")
            time.sleep(3)


if __name__ == "__main__":
    run()
