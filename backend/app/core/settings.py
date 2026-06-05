import os
from pathlib import Path


def _get_float_env(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        return default


def _get_int_env(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _get_bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


BACKEND_DIR = Path(__file__).resolve().parents[2]
DEFAULT_DB_PATH = BACKEND_DIR / "data_logger.db"
DEFAULT_DATABASE_URL = f"sqlite:///{DEFAULT_DB_PATH.as_posix()}"

DATABASE_URL = os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL)
SESSION_TIMEOUT_SECONDS = _get_int_env("SESSION_TIMEOUT_SECONDS", 60)
API_KEY = os.getenv("API_KEY")
REQUIRE_API_KEY = _get_bool_env("REQUIRE_API_KEY", False)

# Optional soft validation thresholds; only warn when crossed.
MAX_ABS_VOLTAGE = _get_float_env("MAX_ABS_VOLTAGE", 1000.0)
MAX_ABS_CURRENT = _get_float_env("MAX_ABS_CURRENT", 100000.0)
