import os
import unittest
from unittest.mock import patch

from scripts.export_dremio import build_headers


class BuildHeadersTests(unittest.TestCase):
    def test_uses_auth_header_value_as_is(self) -> None:
        with patch.dict(os.environ, {"DREMIO_AUTH_HEADER": "sample-auth-token"}, clear=True):
            headers = build_headers()
        self.assertEqual(headers["Authorization"], "sample-auth-token")

    def test_strips_authorization_prefix_from_auth_header(self) -> None:
        with patch.dict(os.environ, {"DREMIO_AUTH_HEADER": "Authorization: sample-auth-token"}, clear=True):
            headers = build_headers()
        self.assertEqual(headers["Authorization"], "sample-auth-token")

    def test_preserves_other_colon_delimited_values(self) -> None:
        with patch.dict(os.environ, {"DREMIO_AUTH_HEADER": "custom:sample-auth-token"}, clear=True):
            headers = build_headers()
        self.assertEqual(headers["Authorization"], "custom:sample-auth-token")


if __name__ == "__main__":
    unittest.main()
