import asyncio
import json
import os
import tkinter as tk
from tkinter import messagebox, simpledialog

try:
    from telethon import TelegramClient  # type: ignore[reportMissingImports]
    from telethon.errors import SessionPasswordNeededError  # type: ignore[reportMissingImports]
except Exception:
    TelegramClient = None
    SessionPasswordNeededError = Exception


CONFIG_FILE = "forwarding_config.json"


def load_config() -> dict:
    if not os.path.exists(CONFIG_FILE):
        return {}
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {}


def save_config(data: dict) -> None:
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


class ForwardingApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Havale Oto Yonlendirme Ayarlari")
        self.root.geometry("700x420")

        self.config = load_config()

        tk.Label(root, text="Telegram Bot Token").grid(row=0, column=0, sticky="w", padx=10, pady=8)
        self.bot_token_entry = tk.Entry(root, width=58, show="*")
        self.bot_token_entry.grid(row=0, column=1, padx=10, pady=8)

        tk.Label(root, text="Yetkili Sohbet ID'leri").grid(row=1, column=0, sticky="w", padx=10, pady=8)
        self.authorized_ids_entry = tk.Entry(root, width=58)
        self.authorized_ids_entry.grid(row=1, column=1, padx=10, pady=8)

        tk.Label(root, text="API ID").grid(row=2, column=0, sticky="w", padx=10, pady=8)
        self.api_id_entry = tk.Entry(root, width=42)
        self.api_id_entry.grid(row=2, column=1, padx=10, pady=8, sticky="w")

        tk.Label(root, text="API Hash").grid(row=3, column=0, sticky="w", padx=10, pady=8)
        self.api_hash_entry = tk.Entry(root, width=42)
        self.api_hash_entry.grid(row=3, column=1, padx=10, pady=8, sticky="w")

        tk.Label(root, text="Telefon (+90...)").grid(row=4, column=0, sticky="w", padx=10, pady=8)
        self.phone_entry = tk.Entry(root, width=42)
        self.phone_entry.grid(row=4, column=1, padx=10, pady=8, sticky="w")

        tk.Label(root, text="Session Adi").grid(row=5, column=0, sticky="w", padx=10, pady=8)
        self.session_entry = tk.Entry(root, width=42)
        self.session_entry.grid(row=5, column=1, padx=10, pady=8, sticky="w")

        self.enabled_var = tk.BooleanVar(value=bool(self.config.get("enabled", False)))
        tk.Checkbutton(root, text="Oto yonlendirme aktif", variable=self.enabled_var).grid(
            row=6, column=1, sticky="w", padx=10, pady=8
        )

        tk.Label(
            root,
            text="Sohbet ID'lerini virgul veya bosluk ile ayirabilirsin. Bos birakirsan bot herkese acik olur.",
            fg="#666666",
            wraplength=650,
            justify="left",
        ).grid(row=7, column=0, columnspan=2, sticky="w", padx=10, pady=6)

        tk.Button(root, text="Kaydet", command=self.on_save, width=18).grid(row=8, column=0, padx=10, pady=12)
        tk.Button(root, text="Telethon Giris Yap", command=self.on_login, width=18).grid(row=8, column=1, padx=10, pady=12, sticky="w")

        self._fill_form()

    def _fill_form(self) -> None:
        self.bot_token_entry.insert(0, str(self.config.get("telegram_bot_token", "")))
        self.authorized_ids_entry.insert(0, str(self.config.get("authorized_chat_ids", "")))
        self.api_id_entry.insert(0, str(self.config.get("api_id", "")))
        self.api_hash_entry.insert(0, str(self.config.get("api_hash", "")))
        self.phone_entry.insert(0, str(self.config.get("phone", "")))
        self.session_entry.insert(0, str(self.config.get("session_name", "forwarding_user")))

    def _collect(self) -> dict:
        return {
            "telegram_bot_token": self.bot_token_entry.get().strip(),
            "authorized_chat_ids": self.authorized_ids_entry.get().strip(),
            "api_id": self.api_id_entry.get().strip(),
            "api_hash": self.api_hash_entry.get().strip(),
            "phone": self.phone_entry.get().strip(),
            "session_name": self.session_entry.get().strip() or "forwarding_user",
            "enabled": bool(self.enabled_var.get()),
        }

    def on_save(self) -> None:
        data = self._collect()
        save_config(data)
        messagebox.showinfo("Basarili", "Ayarlar kaydedildi.")

    async def _login_async(self, data: dict) -> None:
        if TelegramClient is None:
            raise RuntimeError("Telethon kurulu degil. `pip install telethon` calistir.")

        api_id_raw = data.get("api_id")
        api_hash = data.get("api_hash", "")
        phone = data.get("phone", "")
        session_name = data.get("session_name", "forwarding_user")

        if not api_id_raw or not api_hash or not phone:
            raise RuntimeError("API ID, API Hash ve telefon zorunlu.")

        api_id = int(api_id_raw)
        client = TelegramClient(session_name, api_id, api_hash)
        await client.connect()
        try:
            if await client.is_user_authorized():
                return

            await client.send_code_request(phone)
            code = simpledialog.askstring("Dogrulama Kodu", "Telegram'dan gelen kodu gir:")
            if not code:
                raise RuntimeError("Kod girilmedi.")
            try:
                await client.sign_in(phone=phone, code=code.strip())
            except SessionPasswordNeededError:
                password = simpledialog.askstring("2FA", "Iki adimli dogrulama sifresi:", show="*")
                if not password:
                    raise RuntimeError("2FA sifresi girilmedi.")
                await client.sign_in(password=password)
        finally:
            await client.disconnect()

    def on_login(self) -> None:
        data = self._collect()
        save_config(data)
        try:
            asyncio.run(self._login_async(data))
            messagebox.showinfo("Basarili", "Telethon girisi tamamlandi. Artik oto yonlendirme kullanilabilir.")
        except Exception as exc:
            messagebox.showerror("Hata", str(exc))


def run_setup_gui() -> None:
    root = tk.Tk()
    ForwardingApp(root)
    root.mainloop()


def main() -> None:
    run_setup_gui()


if __name__ == "__main__":
    main()
