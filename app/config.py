import os
import secrets
from pathlib import Path


def _load_or_create_secret_key():
    env_key = os.environ.get("SECRET_KEY")
    if env_key:
        return env_key
    key_file = Path(__file__).resolve().parent.parent / "data" / "secret_key.txt"
    key_file.parent.mkdir(parents=True, exist_ok=True)
    if key_file.exists():
        return key_file.read_text().strip()
    key = secrets.token_hex(32)
    key_file.write_text(key)
    return key


class Config:
    BASE_DIR = Path(__file__).resolve().parent.parent
    DATA_DIR = BASE_DIR / "data"
    DB_PATH = DATA_DIR / "finance.db"
    SECRET_KEY = _load_or_create_secret_key()
    DEMO_READ_ONLY_USERNAME = os.environ.get("DEMO_READ_ONLY_USERNAME", "demo")
    DEMO_PUBLIC_LOGIN_ENABLED = os.environ.get("DEMO_PUBLIC_LOGIN_ENABLED", "0") == "1"
