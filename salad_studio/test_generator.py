#!/usr/bin/env python3
"""Offline tests for salad_studio.generator — never hits the network."""
from __future__ import annotations

import base64
import io
import json
import os
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
TOOLS = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(TOOLS))

import generator  # noqa: E402

# 2x2 JPEG (SOF0 height/width = 2).
_JPEG_2X2 = (
    b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    b"\xff\xdb\x00C\x00"
    b"\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\t\t\x08\n\x0c\x14\r\x0c\x0b"
    b"\x0b\x0c\x19\x12\x13\x0f\x14\x1d\x1a\x1f\x1e\x1d\x1a\x1c\x1c $.' \","
    b"#\x1c\x1c(7),01444\x1f'9=82<.342"
    b"\xff\xc0\x00\x0b\x08\x00\x02\x00\x02\x01\x01\x11\x00"
    b"\xff\xc4\x00\x1f\x00\x00\x01\x05\x01\x01\x01\x01\x01\x01\x00\x00\x00"
    b"\x00\x00\x00\x00\x00\x01\x02\x03\x04\x05\x06\x07\x08\t\n\x0b"
    b"\xff\xda\x00\x08\x01\x01\x00\x00?\x00\x7f?\xff\xd9"
)
_JPEG_B64 = base64.b64encode(_JPEG_2X2).decode("ascii")
_OK = (200, json.dumps({"images": [_JPEG_B64]}).encode())


def _gen_kwargs(out_dir: Path, graph: str = "klein") -> dict:
    return {
        "gateway": "https://example.salad.test/",
        "key": "test-key",
        "prompt_text": "a watercolor adult portrait",
        "graph": graph,
        "width": 64,
        "height": 64,
        "steps": 4,
        "use_loras": False,
        "out_dir": out_dir,
        "seed": 1,
    }


class Generate(unittest.TestCase):
    def test_generate_writes_jpg(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out_dir = Path(td)
            with patch.object(generator.salad_gen, "_req", return_value=_OK) as req:
                path = generator.generate(**_gen_kwargs(out_dir))
            urls = [c.args[0] for c in req.call_args_list]
            self.assertIn("https://example.salad.test/ready", urls)
            self.assertEqual(urls[-1], "https://example.salad.test/prompt")
            args, kwargs = req.call_args
            self.assertEqual(kwargs.get("timeout") or args[3], 180)
            self.assertTrue(path.is_file())
            self.assertTrue(path.name.startswith("studio_"))
            self.assertEqual(path.suffix, ".jpg")
            self.assertGreater(path.stat().st_size, 0)
            self.assertEqual(path.read_bytes(), _JPEG_2X2)

    def test_generate_flux1_writes_jpg(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out_dir = Path(td)
            with patch.object(generator.salad_gen, "_req", return_value=_OK):
                path = generator.generate(**_gen_kwargs(out_dir, graph="flux1"))
            self.assertTrue(path.is_file())
            self.assertEqual(path.suffix, ".jpg")

    def test_read_key(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            key_path = Path(td) / "key"
            key_path.write_text(" secret-key \n", encoding="utf-8")
            self.assertEqual(generator.read_key(str(key_path)), "secret-key")


class History(unittest.TestCase):
    def test_list_history_mtime_desc(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out_dir = Path(td)
            older = out_dir / "studio_100.jpg"
            newer = out_dir / "studio_200.jpg"
            other = out_dir / "other.jpg"
            older.write_bytes(b"old")
            newer.write_bytes(b"new")
            other.write_bytes(b"nope")
            os.utime(older, (1_000, 1_000))
            os.utime(newer, (2_000, 2_000))
            self.assertEqual(generator.list_history(out_dir), [newer, older])
            n = generator.clear_history(out_dir)
            self.assertEqual(n, 2)
            self.assertFalse(newer.exists())
            self.assertFalse(older.exists())
            self.assertTrue(other.exists())
            self.assertEqual(generator.list_history(out_dir), [])

    def test_generate_appears_in_history(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out_dir = Path(td)
            with patch.object(generator.salad_gen, "_req", return_value=_OK):
                path = generator.generate(**_gen_kwargs(out_dir))
            hist = generator.list_history(out_dir)
            self.assertEqual(hist, [path])


    def test_generate_use_loras_posts_klein_chain(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out_dir = Path(td)
            extras = Path(td) / "extras.json"
            extras.write_text("{}", encoding="utf-8")
            kwargs = _gen_kwargs(out_dir)
            kwargs["use_loras"] = True
            kwargs["extras_path"] = extras
            with patch(
                "salad_studio.tokens.read_token", return_value="civitai-test-token"
            ), patch.object(
                generator, "_probe_url", return_value=(200, "HEAD")
            ), patch.object(generator.salad_gen, "_req", return_value=_OK) as req:
                generator.generate(**kwargs)
            posted = json.loads(req.call_args.kwargs.get("data") or req.call_args.args[2])
            names = [
                n["inputs"]["lora_name"]
                for n in posted["prompt"].values()
                if n.get("class_type") == "LoraLoader"
            ]
            self.assertEqual(
                names,
                [
                    "https://civitai.com/api/download/models/2625692?token=civitai-test-token",
                    "https://civitai.com/api/download/models/2763568?token=civitai-test-token",
                ],
            )


class PromptEditorPayload(unittest.TestCase):
    def test_generate_from_payload_posts_editor_json(self) -> None:
        editor = {
            "prompt": {
                "9": {
                    "class_type": "SaveImage",
                    "inputs": {"filename_prefix": "edited", "images": ["65", 0]},
                },
                "80": {
                    "class_type": "LoraLoader",
                    "inputs": {
                        "lora_name": "https://civitai.com/api/download/models/2760271",
                        "strength_model": 0.2,
                        "strength_clip": 0.2,
                        "model": ["70", 0],
                        "clip": ["71", 0],
                    },
                },
            },
            "convert_output": {"format": "jpeg"},
        }
        with tempfile.TemporaryDirectory() as td:
            out_dir = Path(td)
            with patch(
                "salad_studio.tokens.read_token", return_value="civitai-test-token"
            ), patch.object(
                generator, "_probe_url", return_value=(200, "HEAD")
            ), patch.object(generator.salad_gen, "_req", return_value=_OK) as req:
                path = generator.generate_from_payload(
                    gateway="https://example.salad.test/",
                    key="test-key",
                    payload=editor,
                    out_dir=out_dir,
                )
            urls = [c.args[0] for c in req.call_args_list]
            self.assertEqual(urls[0], "https://example.salad.test/ready")
            self.assertEqual(urls[-1], "https://example.salad.test/prompt")
            args, kwargs = req.call_args
            posted = json.loads(kwargs.get("data") or args[2])
            self.assertIn(
                "token=civitai-test-token",
                posted["prompt"]["80"]["inputs"]["lora_name"],
            )
            self.assertEqual(
                editor["prompt"]["80"]["inputs"]["lora_name"],
                "https://civitai.com/api/download/models/2760271",
            )
            self.assertTrue(path.is_file())

    def test_generate_from_payload_requires_civitai_token(self) -> None:
        editor = {
            "prompt": {
                "80": {
                    "class_type": "LoraLoader",
                    "inputs": {
                        "lora_name": "https://civitai.com/api/download/models/2795018"
                    },
                }
            }
        }
        with tempfile.TemporaryDirectory() as td:
            with patch("salad_studio.tokens.read_token", return_value=""):
                with self.assertRaises(RuntimeError) as ctx:
                    generator.generate_from_payload(
                        gateway="https://example.salad.test/",
                        key="test-key",
                        payload=editor,
                        out_dir=Path(td),
                    )
            self.assertIn("Civitai", str(ctx.exception))

    def test_http_error_names_request_url_not_cloudflare_docs(self) -> None:
        editor = {"prompt": {"1": {"class_type": "SaveImage"}}}
        cf = (
            b'{"type":"https://developers.cloudflare.com/support/troubleshooting/'
            b'http-status-codes/cloudflare-5xx-errors/error-521/","title":'
            b'"Error 521: Web server is down","status":400}'
        )
        with tempfile.TemporaryDirectory() as td:
            with patch.object(generator.salad_gen, "_req", return_value=(400, cf)):
                with self.assertRaises(RuntimeError) as ctx:
                    generator.generate_from_payload(
                        gateway="https://example.salad.test/",
                        key="test-key",
                        payload=editor,
                        out_dir=Path(td),
                    )
        msg = str(ctx.exception)
        self.assertIn("POST https://example.salad.test/prompt", msg)
        self.assertIn("HTTP 400", msg)
        self.assertNotIn("developers.cloudflare.com", msg)

    def test_prompt_id_polls_history(self) -> None:
        editor = {
            "prompt": {"9": {"class_type": "SaveImage"}},
            "convert_output": {"format": "jpeg"},
        }
        queued = json.dumps({"prompt_id": "abc-1", "number": 1, "node_errors": {}}).encode()

        def _req(url, key, data=None, timeout=30):
            if url.endswith("/ready"):
                return 200, b"ok"
            if url.endswith("/prompt"):
                return 200, queued
            return 404, b""

        with tempfile.TemporaryDirectory() as td:
            with patch.object(generator.salad_gen, "_req", side_effect=_req), patch.object(
                generator, "wait_history_image", return_value="QQ=="
            ) as hist:
                path = generator.generate_from_payload(
                    gateway="https://example.salad.test/",
                    key="test-key",
                    payload=editor,
                    out_dir=Path(td),
                )
            hist.assert_called_once()
            self.assertTrue(path.is_file())
            self.assertGreater(path.stat().st_size, 0)

    def test_preprobe_ready_then_prompt(self) -> None:
        editor = {"prompt": {"1": {"class_type": "SaveImage"}}}
        calls: list[str] = []

        def _req(url, key, data=None, timeout=30):
            calls.append(url)
            if url.endswith("/ready"):
                return 522, b'{"title":"Error 522: Connection timed out","status":522}'
            return _OK

        n_ready = {"n": 0}

        def _req2(url, key, data=None, timeout=30):
            if url.endswith("/ready"):
                n_ready["n"] += 1
                if n_ready["n"] < 2:
                    return 522, b'{"title":"Error 522: Connection timed out","status":522}'
                return 200, b"{}"
            return _OK

        with tempfile.TemporaryDirectory() as td:
            with patch.object(generator, "_READY_SLEEP_S", 0), patch.object(
                generator.salad_gen, "time"
            ) as tmod, patch.object(generator.salad_gen, "_req", side_effect=_req2):
                tmod.sleep = lambda _s: None
                generator.generate_from_payload(
                    gateway="https://example.salad.test/",
                    key="test-key",
                    payload=editor,
                    out_dir=Path(td),
                )
        self.assertGreaterEqual(n_ready["n"], 2)

    def test_generate_payload_kwarg_posts_editor_json(self) -> None:
        editor = {"prompt": {"1": {"class_type": "SaveImage"}}, "note": "from-editor"}
        with tempfile.TemporaryDirectory() as td:
            out_dir = Path(td)
            kwargs = _gen_kwargs(out_dir)
            kwargs["payload"] = json.dumps(editor)
            with patch.object(generator.salad_gen, "_req", return_value=_OK) as req:
                generator.generate(**kwargs)
            posted = json.loads(req.call_args.kwargs.get("data") or req.call_args.args[2])
            self.assertEqual(posted["note"], "from-editor")
            self.assertEqual(posted["prompt"], editor["prompt"])

    def test_parse_request_json_requires_prompt(self) -> None:
        with self.assertRaises(ValueError):
            generator.parse_request_json("{}")
        with self.assertRaises(json.JSONDecodeError):
            generator.parse_request_json("not-json")
        self.assertEqual(
            generator.parse_request_json('{"prompt": {}}')["prompt"],
            {},
        )


class CheckLoraUrls(unittest.TestCase):
    """A LoRA is loaded by the replica *from its URL* when the Comfy graph runs.
    Nothing is downloaded here — the check only catches a wrong or expired URL
    while it is cheap, instead of letting it surface later as an HTTP 524."""

    URL = "https://civitai.com/api/download/models/2615554?token=test-token"

    def _prompt(self, url: str | None = None) -> dict:
        return {
            "80": {
                "class_type": "LoraLoader",
                "inputs": {"lora_name": url or self.URL, "strength_model": 2.0},
            }
        }

    def _opener(self, code: int, calls: list):
        class _Resp:
            status = code

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        def _open(req, timeout=0):
            calls.append((req.full_url, req.get_method()))
            if code >= 400:
                raise urllib.error.HTTPError(req.full_url, code, "err", {}, io.BytesIO(b""))
            return _Resp()

        return _open

    def test_no_loras_makes_no_request(self) -> None:
        calls: list = []
        out = generator.check_lora_urls(
            {"9": {"class_type": "SaveImage", "inputs": {}}},
            opener=self._opener(200, calls),
        )
        self.assertEqual(out, [])
        self.assertEqual(calls, [])

    def test_a_valid_url_passes(self) -> None:
        calls: list = []
        out = generator.check_lora_urls(self._prompt(), opener=self._opener(200, calls))
        self.assertEqual(out, [])
        self.assertEqual([method for _, method in calls], ["HEAD"])
        self.assertIn("civitai.com", calls[0][0])  # it really probed the URL

    def test_a_head_refusal_falls_back_to_a_ranged_get(self) -> None:
        methods: list = []
        codes = iter([405, 200])

        def _open(req, timeout=0):
            methods.append(req.get_method())
            code = next(codes)
            if code >= 400:
                raise urllib.error.HTTPError(req.full_url, code, "err", {}, io.BytesIO(b""))
            return type(
                "R",
                (),
                {
                    "status": code,
                    "__enter__": lambda s: s,
                    "__exit__": lambda s, *a: False,
                },
            )()

        out = generator.check_lora_urls(self._prompt(), opener=_open)
        self.assertEqual(out, [])
        self.assertEqual(methods, ["HEAD", "GET"])

    def test_a_ranged_get_206_counts_as_resolved(self) -> None:
        """206 is the ranged GET's normal answer when the CDN honours `Range`.

        Civitai's does — HEAD is refused with 403 and the GET returns
        ``206 Partial Content``. Testing only for 200 therefore reported every
        live LoRA as "unconfirmed" and warned on every tokenised URL.
        """
        methods: list = []
        codes = iter([403, 206])

        def _open(req, timeout=0):
            methods.append(req.get_method())
            code = next(codes)
            if code >= 400:
                raise urllib.error.HTTPError(req.full_url, code, "err", {}, io.BytesIO(b""))
            return type(
                "R",
                (),
                {
                    "status": code,
                    "__enter__": lambda s: s,
                    "__exit__": lambda s, *a: False,
                },
            )()

        logs: list = []
        out = generator.check_lora_urls(
            self._prompt(), opener=_open, on_log=lambda lvl, msg: logs.append(f"{lvl}:{msg}")
        )
        self.assertEqual(methods, ["HEAD", "GET"])
        self.assertEqual(out, [], "a 206 means the URL resolves")
        self.assertTrue(any(m.startswith("ok:") for m in logs), logs)
        self.assertFalse(any("unconfirmed" in m for m in logs), logs)

    def test_a_gone_url_names_the_lora_and_fails(self) -> None:
        with self.assertRaises(RuntimeError) as raised:
            generator.check_lora_urls(self._prompt(), opener=self._opener(404, []))
        # The message must identify the LoRA without leaking the ?token= URL.
        self.assertIn("civitai:2615554", str(raised.exception))
        self.assertNotIn("token=", str(raised.exception))

    def test_an_inconclusive_answer_does_not_block_the_render(self) -> None:
        out = generator.check_lora_urls(self._prompt(), opener=self._opener(503, []))
        self.assertEqual(out, [self.URL])  # reported, never raised

    def test_a_transport_error_does_not_block_the_render(self) -> None:
        def _boom(req, timeout=0):
            raise urllib.error.URLError("no route to host")

        out = generator.check_lora_urls(self._prompt(), opener=_boom)
        self.assertEqual(out, [self.URL])

    def test_the_render_post_keeps_the_civitai_urls(self) -> None:
        """The load-bearing one: LoRAs must still be passed as URLs, because the
        replica loads them from the URL and cannot resolve a bare filename."""
        payload = json.loads(
            (TOOLS / "salad_klein" / "prompt_snofs_detail_impressionism.json").read_text(
                encoding="utf-8"
            )
        )
        # Production shape: the check runs after the Civitai token is appended.
        for node in payload["prompt"].values():
            if isinstance(node, dict) and node.get("class_type") == "LoraLoader":
                node["inputs"]["lora_name"] += "?token=test-token"

        seen: dict = {}

        def _req(url, key, data=None, timeout=30):
            if url.endswith("/prompt"):
                seen["body"] = json.loads(data)
                return (200, json.dumps({"images": [_JPEG_B64]}).encode())
            return (200, b"{}")

        with tempfile.TemporaryDirectory() as td:
            with patch.object(
                generator, "_probe_url", return_value=(200, "HEAD")
            ), patch.object(generator.salad_gen, "_req", side_effect=_req):
                generator.generate_from_payload(
                    gateway="https://example.salad.test/",
                    key="test-key",
                    payload=payload,
                    out_dir=Path(td),
                )
        names = [
            n["inputs"]["lora_name"]
            for n in seen["body"]["prompt"].values()
            if isinstance(n, dict) and n.get("class_type") == "LoraLoader"
        ]
        self.assertTrue(names, "the render POST lost every LoraLoader")
        for name in names:
            self.assertIn("civitai.com/api/download/models/", name)
            self.assertNotIn(".safetensors", name)


if __name__ == "__main__":
    unittest.main()
