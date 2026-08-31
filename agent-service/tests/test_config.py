from __future__ import annotations

import unittest

from app.config import Settings


class McpSettingsTest(unittest.TestCase):
    def test_rest_is_default_and_does_not_require_mcp_endpoint(self):
        settings = Settings(award_detail_mcp_url="")

        self.assertEqual("rest", settings.award_detail_transport)

    def test_rejects_unknown_transport(self):
        with self.assertRaisesRegex(ValueError, "仅支持 rest 或 mcp"):
            Settings(award_detail_transport="unknown")

    def test_rejects_non_loopback_mcp_url(self):
        with self.assertRaisesRegex(ValueError, "回环地址"):
            Settings(
                award_detail_transport="mcp",
                award_detail_mcp_url="https://example.com/mcp",
            )

    def test_rejects_wrong_mcp_path_and_credentials(self):
        with self.assertRaisesRegex(ValueError, "路径必须是 /mcp"):
            Settings(
                award_detail_transport="mcp",
                award_detail_mcp_url="http://127.0.0.1:8088/api",
            )
        with self.assertRaisesRegex(ValueError, "不允许包含凭据"):
            Settings(
                award_detail_transport="mcp",
                award_detail_mcp_url="http://user:secret@127.0.0.1:8088/mcp",
            )

    def test_rejects_non_positive_mcp_timeouts(self):
        with self.assertRaisesRegex(ValueError, "必须大于 0"):
            Settings(award_detail_mcp_call_timeout_seconds=0)


if __name__ == "__main__":
    unittest.main()
