import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import export_dremio


class BuildHeadersTests(unittest.TestCase):
    def test_build_headers_strips_authorization_prefix(self) -> None:
        with patch.dict(
            os.environ,
            {"DREMIO_AUTH_HEADER": "Authorization: demo-auth-value"},
            clear=False,
        ):
            headers = export_dremio.build_headers()

        self.assertEqual(headers["Authorization"], "demo-auth-value")

    def test_build_headers_strips_prefix_once_and_keeps_colons(self) -> None:
        with patch.dict(
            os.environ,
            {"DREMIO_AUTH_HEADER": "Authorization: demo:with:colons"},
            clear=False,
        ):
            headers = export_dremio.build_headers()

        self.assertEqual(headers["Authorization"], "demo:with:colons")

    def test_build_headers_keeps_raw_auth_value(self) -> None:
        with patch.dict(
            os.environ,
            {"DREMIO_AUTH_HEADER": "_dremiotoken-123"},
            clear=False,
        ):
            headers = export_dremio.build_headers()

        self.assertEqual(headers["Authorization"], "_dremiotoken-123")


if __name__ == "__main__":
    unittest.main()
