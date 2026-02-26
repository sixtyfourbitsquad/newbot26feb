"""Application configuration loaded from environment."""
import os
from dotenv import load_dotenv

load_dotenv()


def _get_env(key: str, default: str | None = None) -> str:
    value = os.getenv(key, default)
    if value is None or value == "":
        raise ValueError(f"Missing required env variable: {key}")
    return value


def _get_env_int(key: str, default: int | None = None) -> int:
    raw = os.getenv(key)
    if raw is None or raw == "":
        if default is not None:
            return default
        raise ValueError(f"Missing required env variable: {key}")
    return int(raw)


BOT_TOKEN: str = _get_env("BOT_TOKEN")
ADMIN_GROUP_ID: int = _get_env_int("ADMIN_GROUP_ID")

def _parse_admin_user_ids() -> frozenset[int]:
    raw = os.getenv("ADMIN_USER_IDS", "").strip()
    if not raw:
        return frozenset()
    return frozenset(int(x.strip()) for x in raw.split(",") if x.strip().isdigit())


ADMIN_USER_IDS: frozenset[int] = _parse_admin_user_ids()

DB_HOST: str = os.getenv("DB_HOST", "localhost")
DB_NAME: str = os.getenv("DB_NAME", "bot1_db")
DB_USER: str = os.getenv("DB_USER", "botuser")
DB_PASS: str = os.getenv("DB_PASS", "strongpassword123")
DB_PORT: int = _get_env_int("DB_PORT", 5432)

DEFAULT_WELCOME_TEXT: str = (
    "Welcome! Send a message and our team will reply here."
)

# Broadcast rate: messages per second
BROADCAST_BATCH_SIZE: int = 25
BROADCAST_MESSAGES_PER_SECOND: int = 25
