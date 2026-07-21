import os
import unittest
from unittest.mock import patch

from scripts.export_dremio import build_headers, normalize_authorization_value


class NormalizeAuthorizationValueTests(unittest.TestCase):
    def test_strips_authorization_prefix_and_quotes(self) -> None:
        self.assertEqual(
            normalize_authorization_value(' "Authorization: ******" '),
            "******",
        )

    def test_strips_authorization_equals_prefix(self) -> None:
        self.assertEqual(
            normalize_authorization_value("Authorization=_dremiotoken-value"),
            "_dremiotoken-value",
        )


class BuildHeadersTests(unittest.TestCase):
    @patch.dict(os.environ, {"DREMIO_AUTH_HEADER": "Authorization: ******"}, clear=True)
    def test_uses_normalized_auth_header_secret(self) -> None:
        self.assertEqual(
            build_headers(),
            {"Content-Type": "application/json", "Authorization": "******"},
        )


if __name__ == "__main__":
    unittest.main()
