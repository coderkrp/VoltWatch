import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import api_client


class ApiClientTests(unittest.TestCase):
    def test_get_api_headers_omits_api_key_when_unset(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            self.assertEqual(api_client.get_api_headers(), {})

    def test_get_api_headers_includes_api_key_when_set(self) -> None:
        with patch.dict("os.environ", {"BACKEND_API_KEY": "secret123"}, clear=True):
            self.assertEqual(
                api_client.get_api_headers(),
                {"X-API-Key": "secret123"},
            )

    def test_fetch_json_uses_base_url_and_headers(self) -> None:
        mock_response = Mock()
        mock_response.json.return_value = {"ok": True}

        with patch.dict(
            "os.environ",
            {
                "BACKEND_API_URL": "http://example.test/api/v1",
                "BACKEND_API_KEY": "secret123",
            },
            clear=True,
        ):
            with patch("api_client.requests.get", return_value=mock_response) as mock_get:
                payload = api_client.fetch_json("/health", params={"device_id": "dev-a"})

        self.assertEqual(payload, {"ok": True})
        mock_get.assert_called_once_with(
            "http://example.test/api/v1/health",
            params={"device_id": "dev-a"},
            headers={"X-API-Key": "secret123"},
            timeout=api_client.API_TIMEOUT_SECONDS,
        )
        mock_response.raise_for_status.assert_called_once_with()
