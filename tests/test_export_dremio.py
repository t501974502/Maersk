import os
import unittest
from unittest.mock import patch

from scripts.export_dremio import build_headers, normalize_authorization_value


class TestAuthorizationHeaders(unittest.TestCase):
    def test_normalize_authorization_strips_header_name(self) -> None:
        value = "Authorization: _dremioabc123"
        self.assertEqual(normalize_authorization_value(value), "_dremioabc123")

    def test_normalize_authorization_handles_case_and_whitespace(self) -> None:
        value = "  AUTHORIZATION:   Token abc123  "
        self.assertEqual(normalize_authorization_value(value), "Token abc123")

    def test_normalize_authorization_passthrough_without_prefix(self) -> None:
        value = "_dremioabc123"
        self.assertEqual(normalize_authorization_value(value), "_dremioabc123")

    def test_build_headers_accepts_authorization_prefix_value(self) -> None:
        env_vars = {
            "DREMIO_AUTH_HEADER": "Authorization: _dremioabc123",
            "DREMIO_TOKEN": "",
            "DREMIO_AUTH_SCHEME": "",
        }
        with patch.dict(os.environ, env_vars, clear=False):
            headers = build_headers()
        self.assertEqual(headers["Authorization"], "_dremioabc123")

    def test_build_headers_uses_token_fallback_when_header_missing(self) -> None:
        env_vars = {
            "DREMIO_AUTH_HEADER": "",
            "DREMIO_TOKEN": "abc123",
            "DREMIO_AUTH_SCHEME": "_dremio",
        }
        with patch.dict(os.environ, env_vars, clear=False):
            headers = build_headers()
        self.assertEqual(headers["Authorization"], "_dremioabc123")


if __name__ == "__main__":
    unittest.main()
