import os

import requests

API_TIMEOUT_SECONDS = 5


def get_api_base_url() -> str:
    return os.getenv("BACKEND_API_URL", "http://localhost:8000/api/v1")


def get_api_headers() -> dict[str, str]:
    api_key = os.getenv("BACKEND_API_KEY")
    if not api_key:
        return {}
    return {"X-API-Key": api_key}


def fetch_json(path: str, params=None):
    url = f"{get_api_base_url()}{path}"
    response = requests.get(
        url,
        params=params,
        headers=get_api_headers(),
        timeout=API_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    return response.json()
