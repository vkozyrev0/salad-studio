#!/usr/bin/env python3
"""Offline tests for salad_studio.generator, never hits the network."""
from __future__ import annotations

import base64
import inspect
import io
import json
import os
import sys
import tempfile
import textwrap
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
TOOLS = HERE.parent
PKG = TOOLS / "salad_studio"
sys.path.insert(0, str(PKG))
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


def _old_form(func, edits: list[tuple[str, str]]):
    """The shipped function with a pass's fix undone: the old form, rebuilt.

    ``edits`` are (shipped text, the text it replaced) pairs, applied to the
    source ``inspect.getsource`` returns. The old behaviour is therefore rebuilt
    from the shipped file rather than copied into a literal that could drift
    away from it, and a test can drive both to show what the fix changed.
    """
    source = textwrap.dedent(inspect.getsource(func))
    for new, old in edits:
        assert new in source, f"{func.__name__} no longer holds {new!r}"
        source = source.replace(new, old, 1)
    namespace: dict = {}
    exec(compile(source, f"<old {func.__name__}>", "exec"), func.__globals__, namespace)
    return namespace[func.__name__]


# `wait_gateway_ready`'s last attempt used to raise the short in-loop message, so
# the trailing block naming `_READY_TRIES` and the minutes never ran.
_READY_EDITS = [
    (
        (
            "            # Last attempt, replica still booting: fall out so the tail names\n"
            "            # the probe count and the budget it spent.\n"
            '            _log("error", msg)\n'
            "            break\n"
        ),
        (
            '            _log("error", msg)\n'
            '            raise RuntimeError(msg + f"  (pre-probe /ready failed for {who})")\n'
        ),
    ),
    (
        (
            "        # Last attempt on a retry code: fall out for the tail below.\n"
            '        _log("error", msg)\n'
            "        break\n"
        ),
        (
            '        _log("error", msg)\n'
            '        raise RuntimeError(msg + f"  (pre-probe /ready failed for {who})")\n'
        ),
    ),
]

# `ready_budget_s` summed the whole interval table, one interval more than the
# loop can spend: the loop sleeps before every probe but the last, so the last
# interval in the table is never spent.
_BUDGET_EDITS = [
    (
        "    return sum(ready_sleep_s(attempt) for attempt in range(_READY_TRIES - 1))",
        "    return sum(ready_sleep_s(attempt) for attempt in range(_READY_TRIES))",
    ),
]

# `_probe_url`'s ranged GET returned on every path, so `return 0, "no probe
# worked"` never ran.
_PROBE_URL_EDITS = [
    (
        (
            "            # A HEAD transport failure is inconclusive on its own, so the ranged\n"
            "            # GET below still runs. The GET is the last method: with neither\n"
            "            # answering, fall out for the summary rather than this pass's own\n"
            "            # reason, which names only one of the two.\n"
            '            if method == "GET":\n'
            "                break\n"
            "            continue\n"
        ),
        '            return 0, type(exc).__name__\n',
    ),
]


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
            for path in (newer, older):
                path.unlink()
            self.assertTrue(other.exists(), "a plate this app did not write stays")
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

    def test_a_timed_out_post_is_not_sent_again(self) -> None:
        """A POST timeout may be a render in flight, so the queue must not retry.

        ``salad_gen._req`` lets a transport error escape; the queue maps a
        raised attempt to status 0 and retries it as busy, which used to submit
        the same plate up to six times.
        """
        import salad_queue

        editor = {"prompt": {"9": {"class_type": "SaveImage"}}}
        posts: list[str] = []

        def _req(url, key, data=None, timeout=30):
            if url.endswith("/ready"):
                return 200, b"ok"
            posts.append(url)
            raise TimeoutError("timed out")

        line = salad_queue.SaladQueue(
            sleep=lambda _s: None, now=lambda: 0.0, max_attempts=4
        )
        with tempfile.TemporaryDirectory() as td:
            with patch.object(generator.salad_gen, "_req", side_effect=_req):
                with self.assertRaises(RuntimeError) as caught:
                    generator.generate_from_payload(
                        gateway="https://example.salad.test/",
                        key="test-key",
                        payload=editor,
                        out_dir=Path(td),
                        queue=line,
                    )
        self.assertEqual(posts, ["https://example.salad.test/prompt"])
        self.assertEqual(line.jobs()[0].state, salad_queue.FAILED)
        self.assertIn("not re-sent", str(caught.exception))

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

    def test_the_readiness_wait_widens_after_its_first_probes(self) -> None:
        """A long boot is asked about less and less often, over a longer budget.

        A spawn has been seen to run past an hour, so the wait covers about ninety
        minutes; while the container has no ready replica every answer is the same
        503 page, so the first probes are close together and the rest are spaced
        out, which keeps the request count far below a flat 10 s wait.
        """
        sleeps = [
            generator.ready_sleep_s(i) for i in range(generator._READY_TRIES - 1)
        ]
        self.assertEqual(sleeps[0], generator._READY_SLEEP_S)
        self.assertEqual(
            sleeps[generator._READY_SLEEP_AFTER - 1], generator._READY_SLEEP_S
        )
        self.assertEqual(
            sleeps[generator._READY_SLEEP_AFTER], generator._READY_SLEEP_MID_S
        )
        self.assertEqual(
            sleeps[generator._READY_SLEEP_MID_AFTER - 1], generator._READY_SLEEP_MID_S
        )
        self.assertEqual(
            sleeps[generator._READY_SLEEP_MID_AFTER], generator._READY_SLEEP_MAX_S
        )
        self.assertEqual(sleeps[-1], generator._READY_SLEEP_MAX_S)
        self.assertEqual(
            generator.ready_budget_s(),
            sum(sleeps),
            "the budget is the intervals the loop spends",
        )
        self.assertGreaterEqual(
            generator.ready_budget_s(), 60 * 60, "an hour-long spawn must still be waited for"
        )
        self.assertLessEqual(
            generator.ready_budget_s(), 2 * 60 * 60, "and the wait stays bounded"
        )
        flat = generator.ready_budget_s() / generator._READY_SLEEP_S
        self.assertLess(
            generator._READY_TRIES,
            flat / 2,
            "the wider budget must not mean a request every 10 s for ninety minutes",
        )

    def test_the_wait_uses_the_widening_interval(self) -> None:
        """The shipped loop sleeps what ready_sleep_s says, not a fixed 10 s."""
        editor = {"prompt": {"1": {"class_type": "SaveImage"}}}
        slept: list[float] = []

        def _req(url, key, data=None, timeout=30):
            if url.endswith("/ready"):
                return 503, b'{"title": "replica unavailable"}'
            return _OK

        with tempfile.TemporaryDirectory() as td, patch.object(
            generator, "_READY_TRIES", 60
        ), patch.object(generator.salad_gen, "_req", side_effect=_req), patch.object(
            generator.salad_gen.time, "sleep", lambda s: slept.append(s)
        ):
            with self.assertRaises(RuntimeError):
                generator.generate_from_payload(
                    gateway="https://example.salad.test/",
                    key="test-key",
                    payload=editor,
                    out_dir=Path(td),
                )
        self.assertEqual(
            slept,
            [generator.ready_sleep_s(i) for i in range(59)],
            "the wait must widen exactly as ready_sleep_s says",
        )
        self.assertIn(generator._READY_SLEEP_MID_S, slept)
        self.assertIn(generator._READY_SLEEP_MAX_S, slept)

    def test_the_budget_is_the_sleeps_the_wait_spends(self) -> None:
        """C3: the failure message's budget is what the loop actually spends.

        The loop sleeps before every probe but the last, so the last interval in
        the table is never spent. The old form, which summed the whole table, is
        rebuilt from the shipped source and driven alongside the fixed one.
        """
        editor = {"prompt": {"1": {"class_type": "SaveImage"}}}
        slept: list[float] = []

        def _req(url, key, data=None, timeout=30):
            return 503, b'{"title": "replica unavailable"}'

        with tempfile.TemporaryDirectory() as td, patch.object(
            generator.salad_gen, "_req", side_effect=_req
        ), patch.object(generator.salad_gen.time, "sleep", lambda s: slept.append(s)):
            with self.assertRaises(RuntimeError):
                generator.generate_from_payload(
                    gateway="https://example.salad.test/",
                    key="test-key",
                    payload=editor,
                    out_dir=Path(td),
                )
        self.assertEqual(
            slept,
            [generator.ready_sleep_s(i) for i in range(generator._READY_TRIES - 1)],
            "the loop sleeps before every probe but the last",
        )
        self.assertEqual(
            generator.ready_budget_s(),
            sum(slept),
            "the budget a failure message names is the one the loop actually spends",
        )
        old = _old_form(generator.ready_budget_s, _BUDGET_EDITS)
        self.assertEqual(
            old() - generator.ready_budget_s(),
            generator.ready_sleep_s(generator._READY_TRIES - 1),
            "the old form names exactly one interval the loop never spends",
        )

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
    Nothing is downloaded here, the check only catches a wrong or expired URL
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

        Civitai's does, HEAD is refused with 403 and the GET returns
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

    def test_a_head_transport_failure_still_tries_the_get(self) -> None:
        """A HEAD that raises is inconclusive; the ranged GET decides."""

        class _Resp:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *_exc):
                return False

        seen: list[str] = []

        def _open(req, timeout=0):
            seen.append(req.get_method())
            if req.get_method() == "HEAD":
                raise urllib.error.URLError("no route to host")
            return _Resp()

        self.assertEqual(generator._probe_url(self.URL, _open), (200, "GET"))
        self.assertEqual(seen, ["HEAD", "GET"], "the GET must still run")

    def test_a_url_neither_method_answers_reports_the_summary(self) -> None:
        """The trailing ``no probe worked`` was unreachable.

        The ranged GET returned on every path, so a URL whose HEAD is refused
        and whose GET never answers reported the GET pass's own transport error
        rather than the summary. The last method falls out of the loop now.
        """
        seen: list[str] = []

        def _open(req, timeout=0):
            seen.append(req.get_method())
            if req.get_method() == "HEAD":
                raise urllib.error.HTTPError(
                    req.full_url, 403, "err", {}, io.BytesIO(b"")
                )
            raise urllib.error.URLError("no route to host")

        old = _old_form(generator._probe_url, _PROBE_URL_EDITS)
        self.assertEqual(old(self.URL, _open), (0, "URLError"), "the old form")
        seen.clear()
        self.assertEqual(generator._probe_url(self.URL, _open), (0, "no probe worked"))
        self.assertEqual(seen, ["HEAD", "GET"], "both methods are still tried")

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


class HistoryPoll(unittest.TestCase):
    """C4: an entry that is present but not completed is a render still running."""

    def _answer(self, payload: dict) -> tuple[int, bytes]:
        return 200, json.dumps({"pid": payload}).encode()

    def test_an_in_flight_entry_keeps_the_poll_waiting(self) -> None:
        answers = [
            self._answer({"status": {"status_str": "executing", "completed": False}}),
            self._answer({"status": {"status_str": "executing", "completed": False}}),
            self._answer({"images": ["QUJD"]}),
        ]
        calls: list[int] = []

        def fetch(_url):
            calls.append(1)
            return answers[min(len(calls) - 1, len(answers) - 1)]

        got = generator.poll_history_image(
            fetch, "https://gw.example/history/pid", "pid", tries=5, sleep_s=0
        )
        self.assertEqual(got, "QUJD", "the poll must reach the answer that has the plate")
        self.assertEqual(len(calls), 3, "and must not stop at the first in-flight entry")

    def test_an_entry_with_no_status_keeps_the_poll_waiting(self) -> None:
        answers = [self._answer({}), self._answer({"images": ["QUJD"]})]
        calls: list[int] = []

        def fetch(_url):
            calls.append(1)
            return answers[min(len(calls) - 1, len(answers) - 1)]

        self.assertEqual(
            generator.poll_history_image(
                fetch, "https://gw.example/history/pid", "pid", tries=4, sleep_s=0
            ),
            "QUJD",
        )

    def test_an_error_status_is_terminal(self) -> None:
        calls: list[int] = []

        def fetch(_url):
            calls.append(1)
            return self._answer({"status": {"status_str": "error", "completed": True}})

        self.assertIsNone(
            generator.poll_history_image(
                fetch, "https://gw.example/history/pid", "pid", tries=3, sleep_s=0
            ),
            "an error status is the one answer that ends the wait",
        )
        self.assertEqual(len(calls), 1, "and it does not ask again")


class WaitReady(unittest.TestCase):
    """C11: the readiness wait must report its own failure."""

    def test_a_zero_budget_reports_not_ready_instead_of_raising(self) -> None:
        import salad_gen

        with patch.object(salad_gen, "_req") as req:
            with self.assertRaises(SystemExit) as caught:
                salad_gen.wait_ready("https://gw.example", "k", timeout_s=0)
        self.assertIn("not ready after 0s", str(caught.exception))
        self.assertFalse(req.called, "a zero budget asks the gateway nothing")

    def test_the_last_probe_names_the_probe_count_and_the_budget(self) -> None:
        """The trailing block naming `_READY_TRIES` and the minutes never ran.

        Every final-iteration path returned or raised, so the short in-loop
        message was all an operator saw: it could not tell "the replica never
        came up" from "the gateway refused". The last attempt falls out of the
        loop now, and the old form is rebuilt to show the difference.
        """
        import salad_gen

        editor = {"prompt": {"1": {"class_type": "SaveImage"}}}
        body = b'{"title":"Error 522: Connection timed out","status":522}'

        def _req(url, key, data=None, timeout=30):
            return 522, body

        old = _old_form(generator.wait_gateway_ready, _READY_EDITS)
        messages: list[str] = []
        for func in (old, generator.wait_gateway_ready):
            with tempfile.TemporaryDirectory() as td, patch.object(
                salad_gen, "_req", side_effect=_req
            ), patch.object(salad_gen, "time") as tmod, patch.object(
                generator, "wait_gateway_ready", func
            ), self.assertRaises(RuntimeError) as caught:
                tmod.sleep = lambda _s: None
                generator.generate_from_payload(
                    gateway="https://example.salad.test/",
                    key="test-key",
                    payload=editor,
                    out_dir=Path(td),
                )
            messages.append(str(caught.exception))

        old_message, new_message = messages
        self.assertIn("pre-probe /ready failed", old_message)
        self.assertNotIn(f"after {generator._READY_TRIES} probes", old_message)
        self.assertIn(
            f"after {generator._READY_TRIES} probes over "
            f"~{generator.ready_budget_s() // 60} minutes",
            new_message,
        )
        self.assertIn("last status HTTP 522", new_message)


class VastQueuedRender(unittest.TestCase):
    """generate_from_vast goes through the queue the way the Salad path does."""

    PAYLOAD = {"prompt": {"9": {"class_type": "SaveImage"}}}

    def setUp(self) -> None:
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.out = Path(self._td.name)

    def _queue(self, **kwargs):
        import salad_queue

        return salad_queue.SaladQueue(
            sleep=lambda _s: None, now=lambda: 0.0, **kwargs
        )

    def test_generate_from_vast_creates_a_job_on_its_line_and_accepts_on_200(self) -> None:
        import salad_queue

        send = _SeqSender([(200, json.dumps({"images": [_JPEG_B64]}).encode())])
        line = self._queue()
        path = generator.generate_from_vast(
            endpoint="203.0.113.9:31234",
            payload=self.PAYLOAD,
            out_dir=self.out,
            sender=send,
            queue=line,
            line="studio",
            checksum="abc123",
        )
        jobs = line.jobs()
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].line, "studio")
        self.assertEqual(jobs[0].state, salad_queue.ACCEPTED)
        self.assertTrue(jobs[0].accepted)
        self.assertEqual(jobs[0].checksum, "abc123")
        self.assertEqual(line.containers(), {}, "a vast request is not a Salad container")
        self.assertTrue(path.is_file())
        self.assertEqual(len(send.requests), 1)

    def test_a_503_is_retried_as_busy(self) -> None:
        import salad_queue

        send = _SeqSender(
            [
                (503, b'{"title": "replica unavailable"}'),
                (503, b'{"title": "replica unavailable"}'),
                (200, json.dumps({"images": [_JPEG_B64]}).encode()),
            ]
        )
        line = self._queue(max_attempts=3)
        path = generator.generate_from_vast(
            endpoint="203.0.113.9:31234",
            payload=self.PAYLOAD,
            out_dir=self.out,
            sender=send,
            queue=line,
            line="studio",
        )
        job = line.jobs()[0]
        self.assertEqual(job.state, salad_queue.ACCEPTED)
        self.assertEqual(job.attempts, 3)
        self.assertTrue(path.is_file())

    def test_the_sender_seam_sees_exactly_one_post_per_real_attempt(self) -> None:
        send = _SeqSender(
            [
                (503, b"busy"),
                (200, json.dumps({"images": [_JPEG_B64]}).encode()),
            ]
        )
        line = self._queue(max_attempts=4)
        generator.generate_from_vast(
            endpoint="203.0.113.9:31234",
            payload=self.PAYLOAD,
            out_dir=self.out,
            sender=send,
            queue=line,
            line="studio",
        )
        posts = [r for r in send.requests if r.get_method() == "POST"]
        self.assertEqual(len(posts), line.jobs()[0].attempts)
        self.assertEqual(len(posts), 2)

    def test_an_unanswered_post_is_not_sent_again(self) -> None:
        """A POST the instance never answers may still be rendering.

        The vast transport reports a transport failure as status 0, which the
        queue used to read as busy and retry, duplicating the plate.
        """
        import salad_queue

        class _Silent:
            def __init__(self) -> None:
                self.requests: list = []

            def __call__(self, request, timeout):
                self.requests.append(request)
                return 0, b""

        send = _Silent()
        line = self._queue(max_attempts=4)
        with self.assertRaises(RuntimeError) as caught:
            generator.generate_from_vast(
                endpoint="203.0.113.9:31234",
                payload=self.PAYLOAD,
                out_dir=self.out,
                sender=send,
                queue=line,
                line="studio",
            )
        self.assertEqual(len(send.requests), 1)
        self.assertEqual(line.jobs()[0].state, salad_queue.FAILED)
        self.assertIn("no answer", str(caught.exception))


class _SeqSender:
    """A transport that answers a canned sequence and records each request."""

    def __init__(self, answers: list[tuple[int, bytes]]) -> None:
        self.answers = list(answers)
        self.requests: list = []

    def __call__(self, request, timeout):
        self.requests.append(request)
        if self.answers:
            return self.answers.pop(0)
        return 200, b"{}"


if __name__ == "__main__":
    unittest.main()
