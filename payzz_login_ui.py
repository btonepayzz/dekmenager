import getpass
import json
import os
import re
import time
import unicodedata
from pathlib import Path

from selenium import webdriver
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.chrome.service import Service
from selenium.webdriver import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait


LOGIN_URL = "https://zero.onepayzz.com/login"
BASE_URL = "https://zero.onepayzz.com/"
DEPOSITS_URL = "https://zero.onepayzz.com/deposits"
SESSION_FILE = Path("payzz_session.json")

XPATH_LOGIN_FRAME = "/html/body/div[1]/div/div"
XPATH_USERNAME = "//*[@id='username']"
XPATH_PASSWORD = "//*[@id='password']"
XPATH_SUBMIT = "/html/body/div[1]/div/div/form/div[3]/button"
XPATH_TWO_FA_CODE = "//input[@type='text' or @name='token' or contains(@placeholder, 'kod') or contains(@placeholder, 'OTP')]"
XPATH_DEPOSITS_FORM = "/html/body/div[1]/div/div[2]/main/div/div/div[2]/div/div[2]/form"
XPATH_DEPOSITS_SEARCH_INPUT = "/html/body/div[1]/div/div[2]/main/div/div/div[2]/div/div[2]/form/div/div[5]/div/input"
XPATH_DEPOSITS_NAME_CELL = "/html/body/div[1]/div/div[2]/main/div/div/div[3]/div[2]/div[1]/table/tbody/tr[1]/td[3]/p[1]"
XPATH_DEPOSITS_STATUS_CELL = "/html/body/div[1]/div/div[2]/main/div/div/div[3]/div[2]/div[1]/table/tbody/tr[1]/td[6]/div/div/span"
TARGET_NAME = "YUNUS GÜLPAY"
DEPOSITS_INITIAL_WAIT_SECONDS = 2.5


def dump_session(driver: webdriver.Chrome, output_file: Path) -> None:
    data = {
        "saved_at": int(time.time()),
        "current_url": driver.current_url,
        "cookies": driver.get_cookies(),
        "local_storage": driver.execute_script(
            """
            const out = {};
            for (let i = 0; i < window.localStorage.length; i++) {
                const key = window.localStorage.key(i);
                out[key] = window.localStorage.getItem(key);
            }
            return out;
            """
        ),
        "session_storage": driver.execute_script(
            """
            const out = {};
            for (let i = 0; i < window.sessionStorage.length; i++) {
                const key = window.sessionStorage.key(i);
                out[key] = window.sessionStorage.getItem(key);
            }
            return out;
            """
        ),
    }
    output_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def load_session(input_file: Path) -> dict:
    if not input_file.exists():
        return {}
    try:
        raw = json.loads(input_file.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            return raw
    except Exception:
        pass
    return {}


def apply_session(driver: webdriver.Chrome, session_data: dict) -> None:
    cookies = session_data.get("cookies", [])
    local_storage = session_data.get("local_storage", {})
    session_storage = session_data.get("session_storage", {})

    driver.get(BASE_URL)

    if isinstance(cookies, list):
        for cookie in cookies:
            if not isinstance(cookie, dict):
                continue
            cookie_copy = dict(cookie)
            cookie_copy.pop("sameSite", None)
            try:
                driver.add_cookie(cookie_copy)
            except Exception:
                continue

    if isinstance(local_storage, dict):
        for key, value in local_storage.items():
            driver.execute_script("window.localStorage.setItem(arguments[0], arguments[1]);", str(key), str(value))

    if isinstance(session_storage, dict):
        for key, value in session_storage.items():
            driver.execute_script("window.sessionStorage.setItem(arguments[0], arguments[1]);", str(key), str(value))


def is_login_page(driver: webdriver.Chrome) -> bool:
    current = (driver.current_url or "").lower()
    if "/login" in current:
        return True
    return bool(driver.find_elements(By.XPATH, XPATH_USERNAME)) and bool(driver.find_elements(By.XPATH, XPATH_PASSWORD))


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


def run_deposits_step(driver: webdriver.Chrome, wait: WebDriverWait, target_name: str = TARGET_NAME) -> bool:
    driver.get(DEPOSITS_URL)
    form_element = wait.until(EC.presence_of_element_located((By.XPATH, XPATH_DEPOSITS_FORM)))
    time.sleep(DEPOSITS_INITIAL_WAIT_SECONDS)
    wait.until(EC.element_to_be_clickable((By.XPATH, XPATH_DEPOSITS_FORM))).click()

    search_input = wait.until(EC.element_to_be_clickable((By.XPATH, XPATH_DEPOSITS_SEARCH_INPUT)))
    try:
        search_input.click()
        search_input.send_keys(Keys.CONTROL, "a")
        search_input.send_keys(Keys.BACKSPACE)
        search_input.send_keys(target_name)
        search_input.send_keys(Keys.ENTER)
        print(f"Arama yapildi: {target_name}")
    except Exception:
        ActionChains(driver).click(search_input).send_keys(target_name).send_keys(Keys.ENTER).perform()
        print(f"Arama fallback ile yapildi: {target_name}")

    time.sleep(1.5)

    name_element = wait.until(EC.presence_of_element_located((By.XPATH, XPATH_DEPOSITS_NAME_CELL)))
    status_element = wait.until(EC.presence_of_element_located((By.XPATH, XPATH_DEPOSITS_STATUS_CELL)))
    page_name = (name_element.text or "").strip()
    page_status = (status_element.text or "").strip()
    target_norm = normalize_text(target_name)
    page_norm = normalize_text(page_name)

    matched = bool(page_norm) and (target_norm in page_norm or page_norm in target_norm)
    if matched:
        print(f"Isim bulundu: {page_name} | Durum: {page_status or '-'}")
    else:
        print(f"Isim bulunamadi. Beklenen: {target_name} | Gelen: {page_name} | Durum: {page_status or '-'}")
    return matched


def interactive_search_loop(driver: webdriver.Chrome, wait: WebDriverWait) -> None:
    print("Yeni arama modu acik. Cikmak icin bos birakip Enter'a bas veya q yaz.")
    while True:
        next_name = input("Yeni aranacak isim: ").strip()
        if not next_name or next_name.lower() in {"q", "quit", "exit"}:
            break
        try:
            run_deposits_step(driver, wait, next_name)
        except Exception as exc:
            print(f"Arama sirasinda hata: {exc}")


def try_resume_with_saved_session(driver: webdriver.Chrome, wait: WebDriverWait) -> bool:
    session_data = load_session(SESSION_FILE)
    if not session_data:
        return False

    print("Kayitli session bulundu, tekrar kullanim deneniyor...")
    try:
        apply_session(driver, session_data)
        target_url = str(session_data.get("current_url", "")).strip() or BASE_URL
        driver.get(target_url)
        driver.refresh()
        try:
            wait.until(lambda d: not is_login_page(d))
        except TimeoutException:
            return False
        print("Kayitli session gecerli, yeniden giris gerekmedi.")
        return True
    except Exception:
        print("Kayitli session gecersiz/bitmis, sifre ile giris istenecek.")
        return False


def run_login() -> None:
    options = webdriver.ChromeOptions()
    options.add_argument("--start-maximized")
    options.add_argument("--log-level=3")
    options.add_argument("--disable-logging")
    options.add_argument("--disable-background-networking")
    options.add_argument("--disable-component-update")
    options.add_experimental_option("excludeSwitches", ["enable-logging"])
    service = Service(log_output=os.devnull)
    driver = webdriver.Chrome(options=options, service=service)
    wait = WebDriverWait(driver, 20)
    should_close_driver = True

    try:
        if try_resume_with_saved_session(driver, wait):
            run_deposits_step(driver, wait)
            interactive_search_loop(driver, wait)
            print("Tarayici acik birakildi. Manuel olarak kapatabilirsin.")
            print("Script beklemede kalacak; kapattiktan sonra terminalde Enter'a bas.")
            input("Devam etmek icin Enter...")
            should_close_driver = False
            return

        username = input("PayZZ kullanici adi: ").strip()
        password = getpass.getpass("PayZZ sifre: ").strip()
        if not username or not password:
            raise RuntimeError("Kullanici adi ve sifre zorunlu.")

        driver.get(LOGIN_URL)
        wait.until(EC.presence_of_element_located((By.XPATH, XPATH_LOGIN_FRAME)))
        wait.until(EC.presence_of_element_located((By.XPATH, XPATH_USERNAME))).send_keys(username)
        wait.until(EC.presence_of_element_located((By.XPATH, XPATH_PASSWORD))).send_keys(password)
        wait.until(EC.element_to_be_clickable((By.XPATH, XPATH_SUBMIT))).click()

        # 2FA adimi tamamen manuel: kodu kullanici girer.
        try:
            wait.until(EC.presence_of_element_located((By.XPATH, XPATH_TWO_FA_CODE)))
            print("2FA ekrani acildi.")
        except TimeoutException:
            print("2FA input'u otomatik bulunamadi ama manuel devam edebilirsin.")
        print("Lutfen 2FA kodunu tarayicida MANUEL gir ve dogrulamayi tamamla.")
        input("2FA islemi bittiginde Enter'a bas...")

        try:
            wait.until(lambda d: "/login" not in d.current_url)
        except TimeoutException:
            print("Hala login sayfasindasin. Yine de mevcut session verisi kaydedilecek.")

        run_deposits_step(driver, wait)
        interactive_search_loop(driver, wait)
        dump_session(driver, SESSION_FILE)
        print(f"Session kaydedildi: {SESSION_FILE.resolve()}")
    finally:
        if should_close_driver:
            driver.quit()


if __name__ == "__main__":
    run_login()
