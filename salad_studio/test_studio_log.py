"""Logs tab helpers: HTTP 521 must not present Cloudflare's docs URL as the request."""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOOLS = HERE.parent
for p in (str(TOOLS), str(HERE)):
    if p not in sys.path:
        sys.path.insert(0, p)

from salad_studio import studio_log  # noqa: E402


class ExplainHttp(unittest.TestCase):
    def test_521_shows_request_url_not_cloudflare_docs(self) -> None:
        body = (
            '{"type":"https://developers.cloudflare.com/support/troubleshooting/'
            'http-status-codes/cloudflare-5xx-errors/error-521/","title":'
            '"Error 521: Web server is down","status":521,"detail":"Cloudflare attempt"}'
        )
        req = "https://persimmon.example.salad.cloud/prompt"
        msg = studio_log.explain_http(521, body, req)
        self.assertIn(req, msg)
        self.assertIn("HTTP 521", msg)
        self.assertIn("origin", msg.lower())
        self.assertNotIn("developers.cloudflare.com", msg)
        self.assertTrue(msg.startswith("POST "))

    def test_522_truncated_json_does_not_look_like_bad_url(self) -> None:
        body = (
            '{"type":"https://developers.cloudflare.com/support/troubleshooting/'
            'http-status-codes/cloudflare-5xx-errors/error-522/","title":'
            '"Error 522: Connection timed out","status":522,"detail":"Cloudflare '
            'could not establish a TCP connection to the origin server. The TCP '
            'handshake timed out, which may indicate the origin is overloaded, '
            'firewalling Cloudflare, or unreachable at the network level.","instance"'
        )
        req = "https://persimmon-caraway-2tyczg3bbqh90fnp.salad.cloud/prompt"
        msg = studio_log.explain_http(522, body, req)
        self.assertTrue(msg.startswith("POST " + req))
        self.assertIn("HTTP 522", msg)
        self.assertIn("TCP", msg)
        self.assertNotIn("developers.cloudflare.com", msg)
        self.assertNotIn('"type"', msg)

    def test_500_includes_comfy_node_errors(self) -> None:
        body = json.dumps(
            {
                "error": {
                    "type": "prompt_outputs_failed_validation",
                    "message": "Prompt outputs failed validation",
                    "details": "",
                },
                "node_errors": {
                    "182": {
                        "errors": [
                            {
                                "details": "unet_name: 'flux-2-klein-9b-fp8.safetensors' not in list"
                            }
                        ]
                    }
                },
            }
        )
        msg = studio_log.explain_http(
            500, body, "https://beet-ginger.example.salad.cloud/prompt"
        )
        self.assertIn("HTTP 500", msg)
        self.assertIn("flux-2-klein-9b-fp8", msg)
        self.assertIn("prompt_outputs_failed_validation", msg)

    def test_redact_token_query(self) -> None:
        raw = "https://civitai.com/api/download/models/1?token=supersecret"
        self.assertIn("token=…", studio_log.redact(raw, ["supersecret"]))
        self.assertNotIn("supersecret", studio_log.strip_url_secrets(raw))

    def test_prompt_url_joins_once(self) -> None:
        self.assertEqual(
            studio_log.prompt_url("https://host.salad.cloud/"),
            "https://host.salad.cloud/prompt",
        )
        self.assertEqual(
            studio_log.prompt_url("https://host.salad.cloud"),
            "https://host.salad.cloud/prompt",
        )


class SourceLogsTab(unittest.TestCase):
    def test_app_has_logs_tab(self) -> None:
        src = (HERE / "app.py").read_text(encoding="utf-8")
        self.assertIn('text="Logs"', src)
        self.assertIn("_build_logs_tab", src)
        self.assertIn("on_log=self.log", src)
        self.assertIn("explain_http", (HERE / "generator.py").read_text(encoding="utf-8"))
        self.assertIn("wait_gateway_ready", (HERE / "generator.py").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
