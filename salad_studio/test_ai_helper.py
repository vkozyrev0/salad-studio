"""Prompt Assist: the DeepSeek request contract and reply parsing.

The HTTP transport is faked at the boundary, the shipped code builds the
request, so the URL, the auth header and the body are all the real ones.
"""
from __future__ import annotations

import base64
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
TOOLS = HERE.parent
for p in (str(TOOLS), str(HERE)):
    if p not in sys.path:
        sys.path.insert(0, p)

from salad_studio import ai_helper as ai  # noqa: E402
from salad_studio import tokens as tok  # noqa: E402

STORED_KEY = "ds-test-key-abcdef123456"

REQUEST_JSON = json.dumps(
    {
        "prompt": {
            "74": {
                "class_type": "CLIPTextEncode",
                "inputs": {"text": "MARKER_EDITOR_POSITIVE", "clip": ["71", 0]},
            },
            "70": {
                "class_type": "UNETLoader",
                "inputs": {"unet_name": "flux-2-klein-base-9b-fp8.safetensors"},
            },
        },
        "convert_output": {"format": "jpeg"},
    }
)

INPUTS = {
    "editor_positive": "MARKER_EDITOR_POSITIVE",
    "editor_negative": "MARKER_EDITOR_NEGATIVE",
    "adjusted_positive": "MARKER_ADJUSTED_POSITIVE",
    "adjusted_negative": "MARKER_ADJUSTED_NEGATIVE",
    "request_json": REQUEST_JSON,
    "findings": "lora #80 -> Klein Detail Slider family=Flux.2 Klein source=catalog",
}


class CapturingSend:
    """Stands in for the HTTP call and records the real request object."""

    def __init__(self, status: int = 200, body: bytes | None = None) -> None:
        self.status = status
        self.body = body if body is not None else _reply_body('{"positive": "P", "negative": "N"}')
        self.requests: list = []

    def __call__(self, request, timeout):
        self.requests.append(request)
        return self.status, self.body


def _reply_body(content: str) -> bytes:
    return json.dumps(
        {
            "id": "x",
            "object": "chat.completion",
            "model": ai.MODEL,
            "choices": [
                {"index": 0, "message": {"role": "assistant", "content": content}}
            ],
        }
    ).encode()


class DeepSeekContract(unittest.TestCase):
    def setUp(self) -> None:
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self._old_local = tok.LOCAL_PATH
        self._old_home = tok.CONFIG_HOME
        tok.LOCAL_PATH = Path(self._td.name) / "studio-tokens.json"
        tok.CONFIG_HOME = Path(self._td.name) / "defaults"
        self.addCleanup(lambda: setattr(tok, "LOCAL_PATH", self._old_local))
        self.addCleanup(lambda: setattr(tok, "CONFIG_HOME", self._old_home))

    def test_request_targets_deepseek_with_the_stored_key_and_all_five_inputs(self) -> None:
        tok.write_token("deepseek", STORED_KEY)
        send = CapturingSend()
        out = ai.help_with_prompts(tok.read_token("deepseek"), send=send, **INPUTS)

        self.assertEqual(len(send.requests), 1)
        request = send.requests[0]
        self.assertEqual(request.full_url, "https://api.deepseek.com/chat/completions")
        self.assertEqual(request.get_method(), "POST")
        # The key the token store returns for DeepSeek is what gets sent.
        self.assertEqual(request.get_header("Authorization"), f"Bearer {STORED_KEY}")

        body = json.loads(request.data.decode("utf-8"))
        self.assertEqual(body["model"], ai.MODEL)
        self.assertFalse(body["stream"])
        self.assertGreaterEqual(int(body["max_tokens"]), 1000)
        self.assertEqual(body["messages"][0]["role"], "system")
        self.assertEqual(body["messages"][1]["role"], "user")
        context = body["messages"][1]["content"]
        # All five context inputs, by content.
        for label, needle in (
            ("editor positive", "MARKER_EDITOR_POSITIVE"),
            ("editor negative", "MARKER_EDITOR_NEGATIVE"),
            ("adjusted positive", "MARKER_ADJUSTED_POSITIVE"),
            ("adjusted negative", "MARKER_ADJUSTED_NEGATIVE"),
            ("request JSON", "flux-2-klein-base-9b-fp8.safetensors"),
        ):
            with self.subTest(input=label):
                self.assertIn(needle, context)
        self.assertIn("Klein Detail Slider", context)

        # The reply's prompts come back for the two adjusted boxes.
        self.assertEqual(out["positive"], "P")
        self.assertEqual(out["negative"], "N")
        self.assertIn("P", out["raw"])

    def test_malformed_reply_surfaces_the_raw_text(self) -> None:
        raw = "I am not able to help with that request."
        send = CapturingSend(body=_reply_body(raw))
        with self.assertRaises(ai.ReplyError) as ctx:
            ai.help_with_prompts(STORED_KEY, send=send, **INPUTS)
        self.assertIn("not able to help", ctx.exception.raw)

    def test_empty_content_is_an_error_not_a_silent_blank(self) -> None:
        send = CapturingSend(body=_reply_body(""))
        with self.assertRaises(ai.AiError) as ctx:
            ai.help_with_prompts(STORED_KEY, send=send, **INPUTS)
        self.assertIn("no message content", str(ctx.exception))

    def test_http_error_reports_the_status_and_provider_message(self) -> None:
        body = json.dumps({"error": {"message": "Authentication Fails"}}).encode()
        send = CapturingSend(status=401, body=body)
        with self.assertRaises(ai.AiError) as ctx:
            ai.help_with_prompts(STORED_KEY, send=send, **INPUTS)
        self.assertIn("401", str(ctx.exception))
        self.assertIn("Authentication Fails", str(ctx.exception))

    def test_missing_key_is_reported_before_any_call(self) -> None:
        send = CapturingSend()
        with self.assertRaises(ai.AiError) as ctx:
            ai.help_with_prompts("", send=send, **INPUTS)
        self.assertIn("empty", str(ctx.exception))
        self.assertEqual(send.requests, [])

    def test_transport_failure_becomes_an_ai_error(self) -> None:
        def boom(request, timeout):
            raise ai.AiError("DeepSeek call failed: URLError: no route")

        with self.assertRaises(ai.AiError):
            ai.help_with_prompts(STORED_KEY, send=boom, **INPUTS)


class IssueAndImage(unittest.TestCase):
    """The reported image issue and the optional attached plate."""

    def setUp(self) -> None:
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.tmp = Path(self._td.name)

    def _jpeg(self, name: str = "plate.jpg", size: tuple[int, int] = (64, 64)) -> Path:
        try:
            from PIL import Image
        except ImportError as e:  # pragma: no cover - Pillow ships with the app
            raise unittest.SkipTest(f"Pillow unavailable: {e}") from e
        path = self.tmp / name
        Image.new("RGB", size, (120, 90, 60)).save(path, "JPEG", quality=90)
        return path

    def test_issue_leads_the_context_and_is_marked_top_priority(self) -> None:
        payload = ai.build_payload(
            editor_positive="EDITOR POS",
            issue="the head is missing",
            **{"findings": "(none)"},
        )
        context = payload["messages"][1]["content"]
        self.assertIsInstance(context, str)
        self.assertIn("the head is missing", context)
        head = context.split("=== POSITIVE PROMPT")[0]
        self.assertIn("HIGHEST PRIORITY", head)
        self.assertIn("(none reported)", ai.build_payload()["messages"][1]["content"])

    def test_system_prompt_orders_the_issue_first(self) -> None:
        system = ai.build_payload()["messages"][0]["content"]
        self.assertIn("HIGHEST PRIORITY", system)
        self.assertIn("issue", system.lower())
        self.assertIn("image", system.lower())

    def test_system_prompt_carries_the_house_klein_anatomy_rules(self) -> None:
        """The standing instruction, not just the per-press context.

        The rules live in the metadata document (origin:
        docs/workflow/19-two-body-prompt-playbook.md); a rewrite that loses them
        goes back to prompts that omit the act. test_studio_meta.py drives the
        document side of the same contract.
        """
        system = ai.build_payload()["messages"][0]["content"]
        for rule in (
            "Klein anatomy rules",
            "missionary",
            "clinical anatomical words",
            "style-only",
            "REPLACE_THIS_PROMPT",
            "count limbs",
        ):
            self.assertIn(rule, system)

    def test_no_image_keeps_the_plain_text_content(self) -> None:
        payload = ai.build_payload(editor_positive="X")
        self.assertIsInstance(payload["messages"][1]["content"], str)

    def test_image_is_attached_as_an_openai_content_part(self) -> None:
        payload = ai.build_payload(
            editor_positive="X", issue="a missing arm", image_data_url="data:image/jpeg;base64,AAAA"
        )
        content = payload["messages"][1]["content"]
        self.assertIsInstance(content, list)
        self.assertEqual([part["type"] for part in content], ["text", "image_url"])
        self.assertIn("a missing arm", content[0]["text"])
        self.assertEqual(content[1]["image_url"]["url"], "data:image/jpeg;base64,AAAA")
        self.assertIn("inspect it", content[0]["text"])

    def test_help_with_prompts_attaches_a_real_file(self) -> None:
        path = self._jpeg("real.jpg", (200, 120))
        send = CapturingSend()
        out = ai.help_with_prompts(
            STORED_KEY, send=send, issue="her arm is missing", image_path=path, **INPUTS
        )
        body = json.loads(send.requests[0].data.decode())
        content = body["messages"][1]["content"]
        self.assertIsInstance(content, list)
        url = content[1]["image_url"]["url"]
        self.assertTrue(url.startswith("data:image/jpeg;base64,"))
        decoded = base64.b64decode(url.split(",", 1)[1])
        self.assertTrue(decoded.startswith(b"\xff\xd8"), "the part must be a JPEG")
        self.assertIn("her arm is missing", content[0]["text"])
        self.assertEqual(out["image"], str(path))

    def test_help_without_an_image_sends_text_only(self) -> None:
        send = CapturingSend()
        out = ai.help_with_prompts(STORED_KEY, send=send, **INPUTS)
        body = json.loads(send.requests[0].data.decode())
        self.assertIsInstance(body["messages"][1]["content"], str)
        self.assertEqual(out["image"], "")

    def test_image_data_url_downscales_a_large_plate(self) -> None:
        big = self._jpeg("big.jpg", (2400, 1600))
        url = ai.image_data_url(big, max_side=512)
        raw = base64.b64decode(url.split(",", 1)[1])
        self.assertLess(len(raw), big.stat().st_size)
        from PIL import Image

        with Image.open(io.BytesIO(raw)) as im:
            self.assertLessEqual(max(im.size), 512)

    def test_image_data_url_reports_a_missing_file(self) -> None:
        with self.assertRaises(ai.AiError) as ctx:
            ai.image_data_url(self.tmp / "nope.jpg")
        self.assertIn("not found", str(ctx.exception))


class LocalSend:
    """Fake LM Studio server: native + OpenAI-compatible list, and chat."""

    def __init__(
        self,
        *,
        models: tuple[str, ...] = ("local-qwen-vl",),
        native_rows: tuple[dict, ...] = (),
        native_status: int = 404,
        reply: str | None = None,
        status: int = 200,
        models_status: int = 200,
        offline: bool = False,
    ) -> None:
        self.models = models
        self.native_rows = list(native_rows)
        self.native_status = native_status
        self.reply = reply if reply is not None else '{"positive": "LP", "negative": "LN"}'
        self.status = status
        self.models_status = models_status
        self.offline = offline
        self.requests: list = []

    def __call__(self, request, timeout):
        self.requests.append(request)
        if self.offline:
            raise ai.AiError("model call failed: URLError: connection refused")
        if request.full_url.endswith("/api/v1/models"):
            if self.native_status != 200:
                return self.native_status, b"{}"
            return 200, json.dumps({"models": self.native_rows}).encode()
        if request.full_url.endswith("/models"):
            if self.models_status != 200:
                return self.models_status, b"{}"
            return 200, json.dumps(
                {"data": [{"id": name, "object": "model"} for name in self.models]}
            ).encode()
        return self.status, json.dumps(
            {"choices": [{"message": {"role": "assistant", "content": self.reply}}]}
        ).encode()

    def chat_request(self):
        return next(r for r in self.requests if r.full_url.endswith("/chat/completions"))

    def models_request(self):
        return next(
            (r for r in self.requests if r.full_url.endswith("/models")
             and not r.full_url.endswith("/api/v1/models")),
            None,
        )

    def native_request(self):
        return next((r for r in self.requests if r.full_url.endswith("/api/v1/models")), None)


class LocalModelChoice(unittest.TestCase):
    """Picking the model: a local server lists embeddings and unloaded models."""

    REAL_SHAPE = (
        {"key": "qwen3.8-27b-obliterated", "type": "llm",
         "loaded_instances": [{"id": "qwen3.8-27b-obliterated"}],
         "capabilities": {"vision": True}},
        {"key": "gemma-4-12b-obliterated", "type": "llm", "loaded_instances": [],
         "capabilities": {"vision": False}},
        {"key": "text-embedding-nomic", "type": "embedding", "loaded_instances": [],
         "capabilities": {}},
    )

    def test_native_rows_read_type_loaded_and_vision(self) -> None:
        rows = ai.native_model_rows(json.dumps({"models": list(self.REAL_SHAPE)}))
        self.assertEqual([r["id"] for r in rows], [
            "qwen3.8-27b-obliterated", "gemma-4-12b-obliterated", "text-embedding-nomic",
        ])
        self.assertIs(rows[0]["loaded"], True)
        self.assertIs(rows[0]["vision"], True)
        self.assertIs(rows[1]["loaded"], False)
        self.assertEqual(rows[2]["type"], "embedding")

    def test_the_loaded_chat_model_wins(self) -> None:
        rows = ai.native_model_rows(json.dumps({"models": list(self.REAL_SHAPE)}))
        self.assertEqual(ai.choose_local_model(rows)["id"], "qwen3.8-27b-obliterated")

    def test_an_embedding_model_is_never_chosen(self) -> None:
        rows = ai.native_model_rows(
            json.dumps({"models": [
                {"key": "text-embedding-nomic", "type": "embedding", "loaded_instances": []},
                {"key": "some-llm", "type": "llm", "loaded_instances": []},
            ]})
        )
        self.assertEqual(ai.choose_local_model(rows)["id"], "some-llm")

    def test_an_unloaded_chat_model_beats_nothing(self) -> None:
        rows = ai.native_model_rows(
            json.dumps({"models": [
                {"key": "only-llm", "type": "llm", "loaded_instances": []},
                {"key": "emb", "type": "embedding", "loaded_instances": []},
            ]})
        )
        self.assertEqual(ai.choose_local_model(rows)["id"], "only-llm")

    def test_choose_handles_no_rows(self) -> None:
        self.assertEqual(ai.choose_local_model([]), {})

    def test_native_metadata_drives_the_choice_and_the_vision_flag(self) -> None:
        send = LocalSend(
            models=("text-embedding-nomic", "qwen3.8-27b-obliterated"),
            native_rows=self.REAL_SHAPE,
            native_status=200,
        )
        out = ai.help_with_prompts_local(url="localhost:1234", send=send, **INPUTS)
        self.assertEqual(out["model"], "qwen3.8-27b-obliterated")
        self.assertIs(out["vision"], True)
        self.assertEqual(json.loads(send.chat_request().data.decode())["model"],
                         "qwen3.8-27b-obliterated")

    def test_falls_back_to_the_openai_list_when_native_is_missing(self) -> None:
        send = LocalSend(models=("only-openai-model",), native_status=404)
        out = ai.help_with_prompts_local(url="localhost:1234", send=send, **INPUTS)
        self.assertEqual(out["model"], "only-openai-model")
        self.assertIsNone(out["vision"], "vision is unknown without native metadata")
        self.assertIsNotNone(send.native_request(), "native is tried first")

    def test_native_url_derives_from_the_openai_base(self) -> None:
        self.assertEqual(
            ai.native_models_url("http://localhost:1234/v1"),
            "http://localhost:1234/api/v1/models",
        )
        self.assertEqual(
            ai.native_models_url(ai.local_base("http://localhost:1234/api/v1")),
            "http://localhost:1234/api/v1/models",
        )


class LocalBackend(unittest.TestCase):
    """The second Help button: an OpenAI-compatible local server (LM Studio)."""

    def test_url_normalisation(self) -> None:
        cases = {
            "": ai.LOCAL_BASE_URL,
            "localhost:1234/v1": "http://localhost:1234/v1",
            "http://localhost:1234": "http://localhost:1234/v1",
            "http://localhost:1234/v1/": "http://localhost:1234/v1",
            "http://127.0.0.1:1234/v1/chat/completions": "http://127.0.0.1:1234/v1",
            "https://box.local:8080/v1": "https://box.local:8080/v1",
            "  192.168.1.9:1234  ": "http://192.168.1.9:1234/v1",
            # LM Studio's native REST base maps onto the OpenAI-compatible one.
            "http://localhost:1234/api/v1": "http://localhost:1234/v1",
            "http://localhost:1234/api/v1/models": "http://localhost:1234/v1",
            "http://localhost:1234/api/v1/chat": "http://localhost:1234/v1",
            # Other documented inference URLs reduce to their base too.
            "http://localhost:1234/v1/responses": "http://localhost:1234/v1",
            "http://localhost:1234/v1/messages": "http://localhost:1234/v1",
        }
        for raw, want in cases.items():
            with self.subTest(url=raw):
                self.assertEqual(ai.local_base(raw), want)

    def test_endpoints_are_the_openai_compatible_ones(self) -> None:
        base = ai.local_base("http://localhost:1234")
        self.assertEqual(ai.local_models_url(base), "http://localhost:1234/v1/models")
        self.assertEqual(
            ai.local_chat_url(base), "http://localhost:1234/v1/chat/completions"
        )

    def test_request_targets_the_local_chat_endpoint_without_a_key(self) -> None:
        send = LocalSend()
        ai.help_with_prompts_local(url="localhost:1234", send=send, **INPUTS)
        request = send.chat_request()
        self.assertEqual(request.full_url, "http://localhost:1234/v1/chat/completions")
        self.assertEqual(request.get_method(), "POST")
        self.assertFalse(
            any(key.lower() == "authorization" for key in request.headers),
            "a local server needs no Authorization header",
        )

    def test_model_id_is_discovered_from_the_local_server(self) -> None:
        send = LocalSend(models=("qwen2.5-vl-7b-instruct",))
        out = ai.help_with_prompts_local(url="http://localhost:1234/v1", send=send, **INPUTS)
        self.assertEqual(send.models_request().full_url, "http://localhost:1234/v1/models")
        body = json.loads(send.chat_request().data.decode())
        self.assertEqual(body["model"], "qwen2.5-vl-7b-instruct")
        self.assertEqual(out["model"], "qwen2.5-vl-7b-instruct")
        self.assertEqual(out["base"], "http://localhost:1234/v1")
        # The order matters: discover first, then chat.
        self.assertTrue(
            send.requests.index(send.models_request()) < send.requests.index(send.chat_request())
        )

    def test_an_explicit_model_skips_discovery(self) -> None:
        send = LocalSend(models=("ignored",))
        ai.help_with_prompts_local(url="localhost:1234", model="chosen", send=send, **INPUTS)
        self.assertIsNone(send.models_request())
        self.assertEqual(json.loads(send.chat_request().data.decode())["model"], "chosen")

    def test_same_context_and_reply_contract_as_deepseek(self) -> None:
        send = LocalSend()
        out = ai.help_with_prompts_local(url="localhost:1234", send=send, **INPUTS)
        body = json.loads(send.chat_request().data.decode())
        # Same system prompt and the same user context as the DeepSeek payload.
        deepseek = ai.build_payload(**INPUTS)
        self.assertEqual(body["messages"][0]["content"], deepseek["messages"][0]["content"])
        context = body["messages"][1]["content"]
        for needle in (
            "MARKER_EDITOR_POSITIVE",
            "MARKER_EDITOR_NEGATIVE",
            "MARKER_ADJUSTED_POSITIVE",
            "MARKER_ADJUSTED_NEGATIVE",
            "flux-2-klein-base-9b-fp8.safetensors",
            "Klein Detail Slider",
        ):
            with self.subTest(needle=needle):
                self.assertIn(needle, context)
        self.assertFalse(body["stream"])
        self.assertEqual(out["positive"], "LP")
        self.assertEqual(out["negative"], "LN")

    def test_the_issue_leads_the_local_context_too(self) -> None:
        send = LocalSend()
        ai.help_with_prompts_local(
            url="localhost:1234", send=send, issue="the head is missing", **INPUTS
        )
        context = json.loads(send.chat_request().data.decode())["messages"][1]["content"]
        head = context.split("=== POSITIVE PROMPT")[0]
        self.assertIn("the head is missing", head)
        self.assertIn("HIGHEST PRIORITY", head)

    def test_an_image_rides_along_for_the_local_model(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            try:
                from PIL import Image
            except ImportError as e:  # pragma: no cover
                raise unittest.SkipTest(f"Pillow unavailable: {e}") from e
            plate = Path(td) / "plate.jpg"
            Image.new("RGB", (80, 60), (10, 90, 40)).save(plate, "JPEG")
            send = LocalSend()
            ai.help_with_prompts_local(
                url="localhost:1234", send=send, image_path=plate, **INPUTS
            )
        content = json.loads(send.chat_request().data.decode())["messages"][1]["content"]
        self.assertIsInstance(content, list)
        self.assertEqual([part["type"] for part in content], ["text", "image_url"])
        self.assertTrue(content[1]["image_url"]["url"].startswith("data:image/jpeg;base64,"))

    def test_server_not_running_gives_an_actionable_message(self) -> None:
        send = LocalSend(offline=True)
        with self.assertRaises(ai.AiError) as ctx:
            ai.help_with_prompts_local(url="http://localhost:1234/v1", send=send, **INPUTS)
        message = str(ctx.exception)
        self.assertIn("LM Studio", message)
        self.assertIn("Start Server", message)
        self.assertIn("http://localhost:1234/v1", message)

    def test_no_model_loaded_is_reported_with_the_url(self) -> None:
        send = LocalSend(models=())
        with self.assertRaises(ai.AiError) as ctx:
            ai.help_with_prompts_local(url="http://localhost:9999/v1", send=send, **INPUTS)
        self.assertIn("http://localhost:9999/v1", str(ctx.exception))
        self.assertIn("LM Studio", str(ctx.exception))

    def test_local_http_error_is_surfaced(self) -> None:
        send = LocalSend(status=404)
        with self.assertRaises(ai.AiError) as ctx:
            ai.help_with_prompts_local(url="localhost:1234", send=send, **INPUTS)
        message = str(ctx.exception)
        self.assertIn("404", message)
        self.assertIn("is a model loaded", message)

    def test_empty_local_reply_is_an_error_not_a_blank(self) -> None:
        send = LocalSend(reply="")
        with self.assertRaises(ai.AiError) as ctx:
            ai.help_with_prompts_local(url="localhost:1234", send=send, **INPUTS)
        self.assertIn("no message content", str(ctx.exception))

    def test_fetch_local_models_tolerates_a_broken_server(self) -> None:
        self.assertEqual(ai.fetch_local_models("http://x/v1", send=LocalSend(offline=True)), [])
        self.assertEqual(ai.fetch_local_models("http://x/v1", send=LocalSend(models_status=500)), [])
        self.assertEqual(
            ai.fetch_local_models("http://x/v1", send=LocalSend(models=("a", "b"))), ["a", "b"]
        )


class ReplyParsing(unittest.TestCase):
    def test_plain_json_object(self) -> None:
        self.assertEqual(
            ai.parse_reply('{"positive": "a", "negative": "b"}'), ("a", "b")
        )

    def test_fenced_json(self) -> None:
        self.assertEqual(
            ai.parse_reply('Sure!\n```json\n{"positive": "a", "negative": "b"}\n```\n'),
            ("a", "b"),
        )

    def test_json_with_surrounding_prose(self) -> None:
        self.assertEqual(
            ai.parse_reply('Here you go: {"positive": "a", "negative": "b"}, enjoy'),
            ("a", "b"),
        )

    def test_nested_wrapper_and_key_aliases(self) -> None:
        self.assertEqual(
            ai.parse_reply('{"prompts": {"positive_prompt": "a", "negative_prompt": "b"}}'),
            ("a", "b"),
        )

    def test_labelled_sections(self) -> None:
        text = "Positive prompt: a cream paper stallion\nNegative: blurry, watermark\n"
        self.assertEqual(ai.parse_reply(text), ("a cream paper stallion", "blurry, watermark"))

    def test_empty_negative_is_allowed(self) -> None:
        self.assertEqual(ai.parse_reply('{"positive": "a", "negative": ""}'), ("a", ""))

    def test_blank_pair_is_rejected(self) -> None:
        with self.assertRaises(ai.ReplyError):
            ai.parse_reply('{"positive": "", "negative": ""}')

    def test_garbage_is_rejected_with_the_raw_text_kept(self) -> None:
        with self.assertRaises(ai.ReplyError) as ctx:
            ai.parse_reply("no prompts here at all")
        self.assertEqual(ctx.exception.raw, "no prompts here at all")

    def test_empty_reply_is_rejected(self) -> None:
        with self.assertRaises(ai.ReplyError):
            ai.parse_reply("   ")

    def test_content_of_reads_the_chat_completions_shape(self) -> None:
        self.assertEqual(ai.content_of(_reply_body("hello")), "hello")
        self.assertEqual(ai.content_of(b"not json"), "")
        self.assertEqual(ai.content_of(json.dumps({"choices": []}).encode()), "")

    def test_parse_reply_full_reads_the_issue_field(self) -> None:
        out = ai.parse_reply_full(
            '{"issue": "the head is missing", "positive": "a", "negative": "b"}'
        )
        self.assertEqual(out["positive"], "a")
        self.assertEqual(out["negative"], "b")
        self.assertEqual(out["issue"], "the head is missing")

    def test_issue_is_optional_in_the_reply(self) -> None:
        out = ai.parse_reply_full('{"positive": "a", "negative": "b"}')
        self.assertEqual(out["issue"], "")
        self.assertEqual(ai.parse_reply('{"positive": "a", "negative": "b"}'), ("a", "b"))

    def test_issue_key_aliases(self) -> None:
        for key in ("problem", "image_issue", "defect"):
            with self.subTest(key=key):
                out = ai.parse_reply_full(
                    json.dumps({key: "a missing arm", "positive": "a", "negative": "b"})
                )
                self.assertEqual(out["issue"], "a missing arm")


def _reply_body_full(content: str, *, finish: str = "stop", reasoning: str = "") -> bytes:
    """A chat-completions body that carries a stop reason and a trace."""
    return json.dumps(
        {
            "id": "x",
            "object": "chat.completion",
            "model": ai.MODEL,
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": content,
                        "reasoning_content": reasoning,
                    },
                    "finish_reason": finish,
                }
            ],
        }
    ).encode()


def _sse_frame(delta: dict, **choice: object) -> str:
    return "data: " + json.dumps({"choices": [{"delta": delta, **choice}]})


class ScriptedSend:
    """One body per call, so a continued reply can be served in pieces."""

    def __init__(self, *bodies: bytes, status: int = 200) -> None:
        self.bodies = list(bodies)
        self.status = status
        self.requests: list = []

    def __call__(self, request, timeout):
        self.requests.append(request)
        index = min(len(self.requests) - 1, len(self.bodies) - 1)
        return self.status, self.bodies[index]

    def payload(self, index: int) -> dict:
        return json.loads(self.requests[index].data.decode("utf-8"))


class AReasoningModelsReplyIsNotItsFragment(unittest.TestCase):
    """The reported bug: a piece of the reply was taken for the whole reply.

    A model that reasons first quotes things that parse as JSON, the schema in
    this module's own system prompt, a first draft, and that quoted piece used
    to be handed back as the answer.
    """

    def test_the_echoed_schema_is_not_an_answer(self) -> None:
        reply = (
            'The schema is {"issue": "what is wrong", "positive": "...", '
            '"negative": "..."}\n\nHere is my answer:\n'
            '{"issue": "head missing", "positive": "REAL POSITIVE", '
            '"negative": "REAL NEGATIVE"}'
        )
        out = ai.parse_reply_full(reply)
        self.assertEqual(out["positive"], "REAL POSITIVE")
        self.assertEqual(out["negative"], "REAL NEGATIVE")

    def test_a_draft_in_the_trace_does_not_beat_the_answer(self) -> None:
        reply = (
            'Let me draft: {"prompt": "rough draft of a stallion", "steps": 20}\n'
            'Final:\n{"issue": "head missing", "positive": "FINAL POSITIVE", '
            '"negative": "FINAL NEGATIVE"}'
        )
        self.assertEqual(
            ai.parse_reply(reply), ("FINAL POSITIVE", "FINAL NEGATIVE")
        )

    def test_placeholder_prompts_alone_are_rejected(self) -> None:
        with self.assertRaises(ai.ReplyError):
            ai.parse_reply('{"positive": "...", "negative": "…"}')

    def test_braces_inside_a_prompt_do_not_split_the_object(self) -> None:
        reply = 'Here you go: {"positive": "a {brace} b", "negative": "n"} enjoy'
        self.assertEqual(ai.parse_reply(reply), ("a {brace} b", "n"))

    def test_an_object_restarted_after_a_cut_is_recovered(self) -> None:
        # What a continued reply really comes back as: the model re-writes the
        # object from the top instead of resuming the cut string, so an
        # unterminated head sits in front of the complete answer. Observed live
        # against LM Studio's Ministral with max_tokens cut to 1000.
        stitched = (
            '{"issue": "head missing", "positive": "a prompt the limit cut'
            '{"issue": "head missing", "positive": "REAL POSITIVE", '
            '"negative": "REAL NEGATIVE"}'
        )
        out = ai.parse_reply_full(stitched)
        self.assertEqual(out["positive"], "REAL POSITIVE")
        self.assertEqual(out["negative"], "REAL NEGATIVE")


class ACutOffReplyIsContinued(unittest.TestCase):
    """``finish_reason: "length"`` is the front of an answer, not the answer."""

    def test_a_cut_reply_is_continued_until_the_answer_is_complete(self) -> None:
        send = ScriptedSend(
            _reply_body_full(
                '{"issue": "head missing", "positive": "a long prompt the limit cut',
                finish="length",
            ),
            _reply_body_full('", "negative": "missing head"}'),
        )
        out = ai.help_with_prompts(STORED_KEY, send=send, **INPUTS)

        self.assertEqual(out["positive"], "a long prompt the limit cut")
        self.assertEqual(out["negative"], "missing head")
        self.assertEqual(out["issue"], "head missing")
        self.assertEqual(out["continued"], 1)
        self.assertEqual(len(send.requests), 2)
        # The follow-up carries the half-written answer and asks for the rest.
        follow = send.payload(1)
        self.assertEqual(follow["messages"][-2]["role"], "assistant")
        self.assertIn("the limit cut", follow["messages"][-2]["content"])
        self.assertEqual(follow["messages"][-1]["content"], ai.CONTINUE_PROMPT)
        self.assertFalse(follow["stream"])

    def test_a_still_cut_reply_is_reported_rather_than_accepted(self) -> None:
        send = ScriptedSend(_reply_body_full('{"positive": "a', finish="length"))
        with self.assertRaises(ai.AiError) as ctx:
            ai.help_with_prompts(STORED_KEY, send=send, **INPUTS)
        self.assertIn("output-token limit", str(ctx.exception))
        self.assertEqual(len(send.requests), 1 + ai.CONTINUE_ATTEMPTS)

    def test_a_trace_that_ate_the_budget_demands_the_answer(self) -> None:
        send = ScriptedSend(
            _reply_body_full("", finish="length", reasoning="a very long trace"),
            _reply_body_full('{"positive": "P", "negative": "N"}'),
        )
        out = ai.help_with_prompts(STORED_KEY, send=send, **INPUTS)

        self.assertEqual(out["positive"], "P")
        self.assertEqual(out["continued"], 1)
        follow = send.payload(1)
        self.assertEqual(follow["messages"][-1]["content"], ai.ANSWER_NOW_PROMPT)
        self.assertTrue(
            all(m.get("role") != "assistant" for m in follow["messages"]),
            "an empty half-answer must not be sent back as an assistant turn",
        )

    def test_a_trace_with_no_answer_is_explained(self) -> None:
        send = ScriptedSend(_reply_body_full("", reasoning="trace only, no answer"))
        with self.assertRaises(ai.AiError) as ctx:
            ai.help_with_prompts(STORED_KEY, send=send, **INPUTS)
        self.assertIn("reasoning", str(ctx.exception))

    def test_the_local_call_continues_the_same_way(self) -> None:
        send = ScriptedSend(
            _reply_body_full('{"positive": "LO', finish="length"),
            _reply_body_full('CAL", "negative": "N"}'),
        )
        out = ai.help_with_prompts_local(
            url="localhost:1234", model="chosen", send=send, **INPUTS
        )
        self.assertEqual(out["positive"], "LOCAL")
        self.assertEqual(out["continued"], 1)
        self.assertEqual(len(send.requests), 2)


class AStreamedBodyIsAssembled(unittest.TestCase):
    """``stream: false`` is sent, but a server may stream anyway."""

    @staticmethod
    def _stream(*, sentinel: bool = True, finish: str = "stop") -> bytes:
        frames = [
            _sse_frame({"role": "assistant", "content": '{"positive": "P", '}),
            _sse_frame({"content": '"negative": "N"}'}),
            _sse_frame({}, finish_reason=finish),
        ]
        if sentinel:
            frames.append("data: [DONE]")
        return ("\n\n".join(frames) + "\n\n").encode()

    def test_the_frames_add_up_to_the_whole_reply(self) -> None:
        body = self._stream()
        self.assertEqual(ai.content_of(body), '{"positive": "P", "negative": "N"}')

        send = ScriptedSend(body)
        out = ai.help_with_prompts(STORED_KEY, send=send, **INPUTS)
        self.assertEqual((out["positive"], out["negative"]), ("P", "N"))
        self.assertEqual(out["continued"], 0)

    def test_a_stream_that_never_finished_is_continued(self) -> None:
        send = ScriptedSend(
            self._stream(sentinel=False, finish="length"),
            self._stream(),
        )
        out = ai.help_with_prompts(STORED_KEY, send=send, **INPUTS)
        self.assertEqual(out["continued"], 1)
        self.assertEqual(out["negative"], "N")

    def test_the_streamed_text_is_what_the_raw_pane_shows(self) -> None:
        send = ScriptedSend(self._stream())
        out = ai.help_with_prompts(STORED_KEY, send=send, **INPUTS)
        self.assertIn('"negative": "N"', out["raw"])


class AShortBodyIsNotTheWholeReply(unittest.TestCase):
    """A body that stops early must fail loudly, never parse as an answer."""

    class _Resp:
        status = 200

        def __init__(self, data: bytes, declared: int | None) -> None:
            self._data = data
            self.headers = (
                {} if declared is None else {"Content-Length": str(declared)}
            )

        def read(self, size: int = -1) -> bytes:
            out, self._data = self._data[:size], self._data[size:]
            return out

        def __enter__(self):
            return self

        def __exit__(self, *exc) -> bool:
            return False

    def _send(self, data: bytes, declared: int | None) -> None:
        request = ai.request_for(STORED_KEY, ai.build_payload(editor_positive="x"))
        with mock.patch.object(
            ai.urllib.request, "urlopen", return_value=self._Resp(data, declared)
        ):
            return ai._http_send(request, 5)

    def test_a_short_body_is_not_taken_for_the_whole_reply(self) -> None:
        with self.assertRaises(ai.AiError) as ctx:
            self._send(b'{"choices": [', 900)
        self.assertIn("cut off in transit", str(ctx.exception))

    def test_a_complete_body_reads_whole(self) -> None:
        body = _reply_body_full("hello")
        status, got = self._send(body, len(body))
        self.assertEqual(status, 200)
        self.assertEqual(got, body)


if __name__ == "__main__":
    unittest.main()
