"""Tests for the headless Civitai-verify driver (no live Salad/Civitai required)."""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
TOOLS = HERE.parent
for p in (str(TOOLS), str(HERE)):
    if p not in sys.path:
        sys.path.insert(0, p)

from salad_studio import civitai_verify as cv  # noqa: E402
from salad_studio import generator  # noqa: E402
from salad_studio.test_generator import _JPEG_2X2, _OK  # noqa: E402

SAMPLE = "https://civitai.com/images/123566519"


def _write_jpeg(_iid: str, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(_JPEG_2X2)
    return dest


def _snap(word: str, name: str, ready_ok: bool = False) -> dict:
    running = word.split()[0] == "Ready"
    return {
        "word": word,
        "block": None if running else f"Replica is {word}",
        "detail": name,
        "ready_ok": ready_ok or running,
        "group": {"name": name, "display_name": name, "status": "running"},
        "instances": [
            {
                "state": "running" if running else "downloading",
                "ready": running,
                "id": name + "-1",
            }
        ],
    }


def _journal(td: str | Path) -> cv.Journal:
    return cv.Journal(Path(td) / "journal")


def _steps(journal: cv.Journal) -> list[str]:
    return [str(e.get("step")) for e in journal.events()]


def _by_step(journal: cv.Journal, step: str) -> list[dict]:
    return [e for e in journal.events() if e.get("step") == step]


def _rows(events: list[dict], step: str) -> list[dict]:
    return [e for e in events if e.get("step") == step]


class Diagnose(unittest.TestCase):
    def test_extracts_text_multiline_from_salad_500(self) -> None:
        err = (
            "POST https://example.salad.cloud/prompt, HTTP 500, "
            'Failed to queue prompt: {"error": {"type": "missing_node_type", '
            "\"message\": \"Node 'Text Multiline' not found. The custom node "
            'may not be installed.", "details": "Node ID \'#106\'", '
            '"extra_info": {"node_id": "106", "class_type": "Text Multiline", '
            '"node_title": "Text Multiline"}}, "node_errors": {}}'
        )
        issues = cv.diagnose_failure(err)
        kinds = [i.get("kind") for i in issues]
        self.assertIn("missing_node_type", kinds)
        types = [i.get("class_type") for i in issues if i.get("kind") == "missing_node_type"]
        self.assertIn("Text Multiline", types)
        self.assertNotIn("error", types)


class FingerprintLoop(unittest.TestCase):
    def test_restore_prior_hash_sets_loop_and_refuses_third_edit(self) -> None:
        fp_a = cv.fingerprint_sources([("comfy_import.py", "alpha-source")])
        fp_b = cv.fingerprint_sources([("comfy_import.py", "beta-source")])
        fp_c = cv.fingerprint_sources([("comfy_import.py", "gamma-source")])
        self.assertNotEqual(fp_a, fp_b)
        self.assertNotEqual(fp_a, fp_c)
        self.assertNotEqual(fp_b, fp_c)

        first = cv.consider_import_code_change([], fp_a)
        self.assertFalse(first["loop"])
        self.assertTrue(first["accepted"])

        second = cv.consider_import_code_change(first["seen"], fp_b)
        self.assertFalse(second["loop"])
        self.assertTrue(second["accepted"])

        ping = cv.consider_import_code_change(second["seen"], fp_a)
        self.assertTrue(ping["loop"])
        self.assertFalse(ping["accepted"])
        self.assertEqual(ping["fingerprint"], fp_a)

        distinct = cv.consider_import_code_change(second["seen"], fp_c)
        self.assertFalse(distinct["loop"])
        self.assertTrue(distinct["accepted"])

    def test_journal_refuses_restored_fingerprint(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            journal = _journal(td)
            a = cv.fingerprint_sources([("comfy_import.py", "one")])
            b = cv.fingerprint_sources([("comfy_import.py", "two")])
            self.assertTrue(cv.record_import_code_change(journal, a, "first"))
            self.assertTrue(cv.record_import_code_change(journal, b, "second"))
            self.assertFalse(cv.record_import_code_change(journal, a, "restore first"))
            self.assertTrue(journal.has_loop())
            loop_rows = _by_step(journal, "loop")
            self.assertEqual(len(loop_rows), 1)
            self.assertTrue(loop_rows[0].get("refuse"))
            self.assertEqual(loop_rows[0].get("fingerprint"), a)
            self.assertIn("infinite loop", loop_rows[0].get("message", "").lower())


class ListGroups(unittest.TestCase):
    def test_lists_both_gateways_with_ready_or_block_word(self) -> None:
        def snap(gateway: str, key: str) -> dict:
            if "beet-ginger" in gateway or "5090" in gateway:
                return _snap("Ready", "flux2-klein-5090", ready_ok=True)
            return _snap("Downloading 40%", "flux2-klein2")

        rows = cv.list_studio_groups(
            "test-key",
            snapshot_fn=snap,
            targets=[
                ("klein", "https://apple-gadogado.example/"),
                ("klein5090", "https://beet-ginger.example/"),
            ],
        )
        self.assertEqual([r["profile_id"] for r in rows], ["klein", "klein5090"])
        words = {r["profile_id"]: r["word"] for r in rows}
        self.assertTrue(words["klein"])
        self.assertIn(words["klein"].split()[0], {"Downloading", "Down", "Starting", "Ready"})
        self.assertEqual(words["klein5090"], "Ready")
        self.assertTrue(rows[0]["block"])
        self.assertFalse(rows[0]["ready"])
        self.assertTrue(rows[1]["ready"])
        picked = cv.pick_studio_group(rows)
        self.assertIsNotNone(picked)
        assert picked is not None
        self.assertEqual(picked["profile_id"], "klein5090")
        self.assertEqual(picked["word"], "Ready")


class ConvertInspect(unittest.TestCase):
    def test_fixture_paste_uses_real_convert_and_yields_prompt_graph(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            extras = Path(td) / "extras.json"
            extras.write_text("{}", encoding="utf-8")
            body = cv.convert_to_request(
                cv.default_fixture_pastes(), extras_path=extras
            )
        self.assertIsInstance(body, dict)
        self.assertIn("prompt", body)
        prompt = body["prompt"]
        self.assertIsInstance(prompt, dict)
        self.assertTrue(
            any(
                isinstance(n, dict) and n.get("class_type") for n in prompt.values()
            )
        )
        insp = cv.inspect_converted(body, cv.default_fixture_pastes())
        self.assertTrue(insp["has_graph"])
        self.assertFalse(insp["blocking"])
        self.assertTrue(insp["runnable"])

    def test_convert_error_is_journaled_and_halts_without_post(self) -> None:
        posted = {"n": 0}

        def boom(**kwargs):
            raise ValueError("paste exploded")

        def gen(**kwargs):
            posted["n"] += 1
            raise AssertionError("POST must not run after convert failure")

        with tempfile.TemporaryDirectory() as td:
            journal = _journal(td)
            src = Path(td) / "src"
            src.mkdir()
            (src / "comfy_import.py").write_text("x=1\n", encoding="utf-8")
            (src / "request_json.py").write_text("y=2\n", encoding="utf-8")
            result = cv.run_verify(
                [SAMPLE],
                journal,
                snapshot_fn=lambda gw, key: _snap("Ready", "g", True),
                fetch_fn=lambda image_id: cv.default_fixture_pastes(),
                import_fn=boom,
                generate_fn=gen,
                resolve_key_fn=lambda: "test-key",
                extras_path=Path(td) / "extras.json",
                source_root=src,
                targets=[
                    ("klein", "https://klein.example/"),
                    ("klein5090", "https://k5090.example/"),
                ],
            )
            self.assertFalse(result["ok"])
            self.assertEqual(posted["n"], 0)
            convert_rows = _by_step(journal, "convert")
            self.assertTrue(convert_rows)
            self.assertFalse(convert_rows[0]["ok"])
            self.assertIn("exploded", convert_rows[0]["error"])
            self.assertIn("container-list", _steps(journal))
            post_ok = [e for e in _by_step(journal, "post") if e.get("ok")]
            self.assertEqual(post_ok, [])

    def test_inspect_blocking_is_journaled_and_halts_without_post(self) -> None:
        posted = {"n": 0}

        def gen(**kwargs):
            posted["n"] += 1
            raise AssertionError("POST must not run after inspect failure")

        with tempfile.TemporaryDirectory() as td:
            extras = Path(td) / "extras.json"
            extras.write_text("{}", encoding="utf-8")
            journal = _journal(td)
            src = Path(td) / "src"
            src.mkdir()
            (src / "comfy_import.py").write_text("x=1\n", encoding="utf-8")
            (src / "request_json.py").write_text("y=2\n", encoding="utf-8")
            result = cv.run_verify(
                [SAMPLE],
                journal,
                snapshot_fn=lambda gw, key: _snap("Ready", "g", True),
                fetch_fn=lambda image_id: cv.default_fixture_pastes(),
                inspect_fn=lambda meta, wf: (["Could not parse workflow JSON: no"], []),
                generate_fn=gen,
                resolve_key_fn=lambda: "test-key",
                extras_path=extras,
                source_root=src,
                targets=[
                    ("klein", "https://klein.example/"),
                    ("klein5090", "https://k5090.example/"),
                ],
            )
            self.assertFalse(result["ok"])
            self.assertEqual(posted["n"], 0)
            inspect_rows = _by_step(journal, "inspect")
            self.assertTrue(inspect_rows)
            self.assertFalse(inspect_rows[0]["ok"])
            self.assertTrue(inspect_rows[0]["blocking"])


class PostPath(unittest.TestCase):
    def test_ready_group_posts_to_that_gateway_prompt(self) -> None:
        def snap(gateway: str, key: str) -> dict:
            if "k5090" in gateway:
                return _snap("Ready", "flux2-klein-5090", ready_ok=True)
            return _snap("Down", "flux2-klein2")

        with tempfile.TemporaryDirectory() as td:
            extras = Path(td) / "extras.json"
            extras.write_text("{}", encoding="utf-8")
            journal = _journal(td)
            src = Path(td) / "src"
            src.mkdir()
            (src / "comfy_import.py").write_text("x=1\n", encoding="utf-8")
            (src / "request_json.py").write_text("y=2\n", encoding="utf-8")
            with patch.object(generator.salad_gen, "_req", return_value=_OK) as req:
                result = cv.run_verify(
                    [SAMPLE],
                    journal,
                    snapshot_fn=snap,
                    fetch_fn=lambda image_id: cv.default_fixture_pastes(),
                    generate_fn=generator.generate_from_payload,
                    resolve_key_fn=lambda: "test-key",
                    extras_path=extras,
                    out_dir=Path(td) / "out",
                    source_root=src,
                    describe_fn=lambda p: "a woman standing in a forest clearing",
                    fetch_site_fn=_write_jpeg,
                    targets=[
                        ("klein", "https://klein.example/"),
                        ("klein5090", "https://k5090.example/"),
                    ],
                )
            urls = [c.args[0] for c in req.call_args_list]
            self.assertTrue(result["ok"], result)
            self.assertIn("https://k5090.example/prompt", urls)
            self.assertTrue(any(u.endswith("/prompt") for u in urls))
            post_rows = _by_step(journal, "post")
            self.assertTrue(post_rows)
            self.assertTrue(post_rows[0]["ok"])
            self.assertEqual(post_rows[0]["gateway"], "https://k5090.example/")
            picked = result["picked"]
            self.assertEqual(picked["profile_id"], "klein5090")

    def test_node_errors_and_logs_are_journaled(self) -> None:
        queued = json.dumps(
            {
                "prompt_id": "abc-1",
                "node_errors": {
                    "9": {
                        "type": "missing_node_type",
                        "message": "LanPaint_KSampler",
                    }
                },
            }
        ).encode()

        def _req(url, key, data=None, timeout=30):
            if str(url).endswith("/ready"):
                return 200, b"ok"
            if str(url).endswith("/prompt"):
                return 200, queued
            return 404, b""

        def snap(gateway: str, key: str) -> dict:
            return _snap("Ready", "flux2-klein-5090", ready_ok=True)

        with tempfile.TemporaryDirectory() as td:
            extras = Path(td) / "extras.json"
            extras.write_text("{}", encoding="utf-8")
            journal = _journal(td)
            src = Path(td) / "src"
            src.mkdir()
            (src / "comfy_import.py").write_text("x=1\n", encoding="utf-8")
            (src / "request_json.py").write_text("y=2\n", encoding="utf-8")
            with patch.object(generator.salad_gen, "_req", side_effect=_req):
                result = cv.run_verify(
                    [SAMPLE],
                    journal,
                    snapshot_fn=snap,
                    fetch_fn=lambda image_id: cv.default_fixture_pastes(),
                    generate_fn=generator.generate_from_payload,
                    log_fn=lambda *a, **k: [
                        "Comfy missing_node_type LanPaint_KSampler crashed"
                    ],
                    resolve_key_fn=lambda: "test-key",
                    extras_path=extras,
                    out_dir=Path(td) / "out",
                    source_root=src,
                    targets=[
                        ("klein", "https://klein.example/"),
                        ("klein5090", "https://k5090.example/"),
                    ],
                )
            self.assertFalse(result["ok"])
            post_rows = _by_step(journal, "post")
            self.assertTrue(post_rows)
            self.assertFalse(post_rows[0]["ok"])
            err = str(post_rows[0].get("error") or "")
            self.assertIn("node_errors", err)
            self.assertTrue(post_rows[0].get("logs"))
            self.assertTrue(
                any("LanPaint" in str(x) for x in post_rows[0]["logs"])
                or "LanPaint" in err
            )


class EditImport(unittest.TestCase):
    def test_missing_node_fix_writes_conversion_source_and_records_fingerprint(self) -> None:
        fake = (
            'SALAD_MISSING_TYPES = {\n    "Note",\n}\n'
            "def prompt_for_salad_replica(prompt):\n"
            "    if cls in SALAD_MISSING_TYPES:\n"
            "        pass\n"
        )
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "src"
            root.mkdir()
            (root / "comfy_import.py").write_text(fake, encoding="utf-8")
            (root / "request_json.py").write_text("ok\n", encoding="utf-8")
            journal = _journal(td)
            cv.sync_source_fingerprint(journal, root)
            issues = [
                {
                    "kind": "missing_node_type",
                    "class_type": "LanPaint_KSampler",
                }
            ]
            ok = cv.apply_known_import_fix(issues, source_root=root, journal=journal)
            self.assertTrue(ok)
            text = (root / "comfy_import.py").read_text(encoding="utf-8")
            self.assertIn('"LanPaint_KSampler"', text)
            fps = journal.fingerprints()
            self.assertGreaterEqual(len(fps), 2)
            self.assertNotEqual(fps[0], fps[-1])

            # Restoring the original source is a loop.
            (root / "comfy_import.py").write_text(fake, encoding="utf-8")
            restored = cv.sync_source_fingerprint(journal, root)
            self.assertFalse(restored)
            self.assertTrue(journal.has_loop())

    def test_already_listed_type_is_no_mechanical_fix_not_a_loop(self) -> None:
        fake = (
            'SALAD_MISSING_TYPES = {\n    "LanPaint_KSampler",\n}\n'
            "def prompt_for_salad_replica(prompt):\n"
            "    if cls in SALAD_MISSING_TYPES:\n"
            "        pass\n"
        )
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "src"
            root.mkdir()
            (root / "comfy_import.py").write_text(fake, encoding="utf-8")
            (root / "request_json.py").write_text("ok\n", encoding="utf-8")
            journal = _journal(td)
            self.assertTrue(cv.sync_source_fingerprint(journal, root))
            ok = cv.apply_known_import_fix(
                [{"kind": "missing_node_type", "class_type": "LanPaint_KSampler"}],
                source_root=root,
                journal=journal,
            )
            self.assertFalse(ok)
            self.assertFalse(journal.has_loop())
            self.assertEqual(
                (root / "comfy_import.py").read_text(encoding="utf-8"), fake
            )
            skips = _by_step(journal, "import-code-change")
            self.assertTrue(
                any(
                    "no mechanical" in str(row.get("skipped") or "")
                    for row in skips
                )
            )


class EditImportOptIn(unittest.TestCase):
    """The fix path edits conversion sources only when the caller opts in."""

    MISSING = "ZzOptInMissingNode"

    @staticmethod
    def _copy_sources(td: str) -> Path:
        src = Path(td) / "src"
        src.mkdir()
        shutil.copy2(HERE / "comfy_import.py", src / "comfy_import.py")
        shutil.copy2(HERE / "request_json.py", src / "request_json.py")
        return src

    def _boom(self, **_kwargs):
        raise RuntimeError(
            "POST https://klein.example/prompt, HTTP 500, Failed to queue "
            'prompt: {"error": {"type": "missing_node_type", "message": '
            f"\"Node '{self.MISSING}' not found.\", \"extra_info\": "
            f'{{"class_type": "{self.MISSING}"}}}}'
        )

    def _run(
        self, td: str, src: Path, *, edit_import: bool | None
    ) -> tuple[dict, cv.Journal]:
        """edit_import=None drives the shipped default (no opt-in kwarg)."""
        extras = Path(td) / "extras.json"
        extras.write_text("{}", encoding="utf-8")
        journal = _journal(td)
        opt_in = {} if edit_import is None else {"edit_import": edit_import}
        result = cv.run_verify(
            [SAMPLE],
            journal,
            snapshot_fn=lambda gw, key: _snap("Ready", "g", True),
            fetch_fn=lambda image_id: cv.default_fixture_pastes(),
            generate_fn=self._boom,
            log_fn=lambda *a, **k: [],
            resolve_key_fn=lambda: "test-key",
            extras_path=extras,
            out_dir=Path(td) / "out",
            source_root=src,
            max_attempts=2,
            targets=[("klein", "https://klein.example/")],
            **opt_in,
        )
        return result, journal

    def _with_sources(self, td: str, *, edit_import: bool | None):
        """Run the fix path against a throwaway copy, restoring module bindings.

        Journal rows and file texts are captured before the temp dir goes away.
        """
        saved_modules = {
            name: sys.modules.get(name)
            for name in ("comfy_import", "salad_studio.comfy_import")
        }
        saved_ci = cv.ci
        src = self._copy_sources(td)
        names = ("comfy_import.py", "request_json.py")
        before = {name: (src / name).read_bytes() for name in names}
        try:
            result, journal = self._run(td, src, edit_import=edit_import)
            after = {name: (src / name).read_bytes() for name in names}
            events = journal.events()
            texts = {name: (src / name).read_text(encoding="utf-8") for name in names}
        finally:
            for name, mod in saved_modules.items():
                if mod is not None:
                    sys.modules[name] = mod
            pkg = sys.modules.get("salad_studio")
            live_pkg_mod = saved_modules["salad_studio.comfy_import"]
            if pkg is not None and live_pkg_mod is not None:
                pkg.comfy_import = live_pkg_mod
            cv.ci = saved_ci
        return result, events, before, after, texts

    def test_not_opted_in_leaves_the_conversion_copy_byte_identical(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            result, events, before, after, _texts = self._with_sources(
                td, edit_import=None
            )
        self.assertFalse(result["ok"])
        self.assertEqual(after, before)
        skips = _rows(events, "import-code-change")
        self.assertTrue(skips)
        self.assertTrue(
            any("edit_import is off" in str(row.get("skipped") or "") for row in skips)
        )
        diagnoses = _rows(events, "diagnose")
        self.assertTrue(
            any(
                str(i.get("class_type")) == self.MISSING
                for row in diagnoses
                for i in row.get("issues") or []
            )
        )

    def test_opted_in_edits_the_conversion_copy(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            _result, _events, before, after, texts = self._with_sources(
                td, edit_import=True
            )
        self.assertNotEqual(after["comfy_import.py"], before["comfy_import.py"])
        self.assertEqual(after["request_json.py"], before["request_json.py"])
        self.assertIn(self.MISSING, texts["comfy_import.py"])
        compile(texts["comfy_import.py"], "comfy_import.py", "exec")


class AutoFixRetry(unittest.TestCase):
    def test_missing_node_type_post_edits_source_and_retries(self) -> None:
        missing = "ZzVerifyMissingNode"
        posted: list[dict] = []

        def import_with_missing(**kwargs):
            body = cv.convert_to_request(
                cv.default_fixture_pastes(), extras_path=kwargs.get("extras_path")
            )
            prompt = body.setdefault("prompt", {})
            prompt["999"] = {"class_type": missing, "inputs": {}}
            return body

        def _req(url, key, data=None, timeout=30):
            if str(url).endswith("/ready"):
                return 200, b"ok"
            if str(url).endswith("/prompt"):
                raw = data.decode() if isinstance(data, (bytes, bytearray)) else data
                obj = json.loads(raw)
                posted.append(obj)
                types = [
                    str(n.get("class_type") or "")
                    for n in (obj.get("prompt") or {}).values()
                    if isinstance(n, dict)
                ]
                if missing in types:
                    err = {
                        "prompt_id": "abc-1",
                        "node_errors": {
                            "999": {
                                "type": "missing_node_type",
                                "message": f"Node '{missing}' not found.",
                                "extra_info": {"class_type": missing},
                            }
                        },
                    }
                    return 200, json.dumps(err).encode()
                return _OK
            return 404, b""

        orig_bare = sys.modules.get("comfy_import")
        orig_pkg = sys.modules.get("salad_studio.comfy_import")
        orig_ci = cv.ci
        with tempfile.TemporaryDirectory() as td:
            extras = Path(td) / "extras.json"
            extras.write_text("{}", encoding="utf-8")
            journal = _journal(td)
            src = Path(td) / "src"
            src.mkdir()
            shutil.copy2(HERE / "comfy_import.py", src / "comfy_import.py")
            shutil.copy2(HERE / "request_json.py", src / "request_json.py")
            try:
                with patch.object(generator.salad_gen, "_req", side_effect=_req):
                    result = cv.run_verify(
                        [SAMPLE],
                        journal,
                        snapshot_fn=lambda gw, key: _snap("Ready", "g", True),
                        fetch_fn=lambda image_id: cv.default_fixture_pastes(),
                        import_fn=import_with_missing,
                        generate_fn=generator.generate_from_payload,
                        resolve_key_fn=lambda: "test-key",
                        extras_path=extras,
                        out_dir=Path(td) / "out",
                        source_root=src,
                        edit_import=True,
                        describe_fn=lambda p: "a woman standing in a forest clearing",
                        fetch_site_fn=_write_jpeg,
                        targets=[
                            ("klein", "https://klein.example/"),
                            ("klein5090", "https://k5090.example/"),
                        ],
                    )
            finally:
                if orig_bare is not None:
                    sys.modules["comfy_import"] = orig_bare
                if orig_pkg is not None:
                    sys.modules["salad_studio.comfy_import"] = orig_pkg
                    pkg = sys.modules.get("salad_studio")
                    if pkg is not None:
                        pkg.comfy_import = orig_pkg
                cv.ci = orig_ci
            self.assertTrue(result["ok"], result)
            self.assertGreaterEqual(len(posted), 2)
            first_types = [
                str(n.get("class_type") or "")
                for n in (posted[0].get("prompt") or {}).values()
                if isinstance(n, dict)
            ]
            retry_types = [
                str(n.get("class_type") or "")
                for n in (posted[-1].get("prompt") or {}).values()
                if isinstance(n, dict)
            ]
            self.assertIn(missing, first_types)
            self.assertNotIn(missing, retry_types)
            text = (src / "comfy_import.py").read_text(encoding="utf-8")
            self.assertIn(missing, text)
            posts = _by_step(journal, "post")
            self.assertGreaterEqual(len(posts), 2)
            self.assertFalse(posts[0]["ok"])
            self.assertTrue(posts[-1]["ok"])
            self.assertFalse(journal.has_loop())


class AuditClipLoraAblate(unittest.TestCase):
    def test_clip_matches_generation_data(self) -> None:
        body = {
            "prompt": {
                "74": {
                    "class_type": "CLIPTextEncode",
                    "inputs": {"text": "hello forest", "clip": ["71", 0]},
                },
                "67": {
                    "class_type": "CLIPTextEncode",
                    "inputs": {"text": "bad", "clip": ["71", 0]},
                },
                "121": {
                    "class_type": "CFGGuider",
                    "inputs": {
                        "positive": ["74", 0],
                        "negative": ["67", 0],
                    },
                },
            }
        }
        meta = "hello forest\nNegative prompt: bad\nSteps: 4, Sampler: Euler, Seed: 1\n"
        rep = cv.audit_clip(body, meta)
        self.assertTrue(rep["ok"])
        self.assertTrue(rep["positive_match"])
        self.assertTrue(rep["negative_match"])

    def test_clip_mismatch_is_journaled(self) -> None:
        body = {
            "prompt": {
                "74": {
                    "class_type": "CLIPTextEncode",
                    "inputs": {"text": "", "clip": ["71", 0]},
                },
                "121": {
                    "class_type": "CFGGuider",
                    "inputs": {"positive": ["74", 0], "negative": ["67", 0]},
                },
            }
        }
        rep = cv.audit_clip(body, "a woman in a forest\nNegative prompt: blurry\nSteps: 4\n")
        self.assertFalse(rep["ok"])
        self.assertTrue(any("positive CLIP" in x for x in rep["issues"]))

    def test_lora_local_filename_not_in_extras(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            extras = Path(td) / "extras.json"
            extras.write_text('{"items": []}', encoding="utf-8")
            body = {
                "prompt": {
                    "80": {
                        "class_type": "LoraLoader",
                        "inputs": {
                            "lora_name": "SteamPunk01_CE.safetensors",
                            "model": ["119", 0],
                        },
                    }
                }
            }
            rep = cv.audit_loras(body, extras)
            self.assertFalse(rep["ok"])
            self.assertTrue(any("not in Studio extras" in x for x in rep["issues"]))

    def test_lora_wrong_family_flagged(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            extras = Path(td) / "extras.json"
            extras.write_text(
                json.dumps(
                    {
                        "items": [
                            {
                                "id": "civitai:1@1",
                                "base": "SDXL",
                                "source": {
                                    "filename": "sdxl-style.safetensors",
                                    "download": "https://civitai.com/api/download/models/1",
                                },
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            body = {
                "prompt": {
                    "80": {
                        "class_type": "LoraLoader",
                        "inputs": {
                            "lora_name": "sdxl-style.safetensors",
                            "model": ["119", 0],
                        },
                    }
                }
            }
            rep = cv.audit_loras(body, extras)
            self.assertFalse(rep["ok"])
            self.assertTrue(any("not Flux.2 Klein" in x for x in rep["issues"]))

    def test_ablate_drops_lora_and_restores_original(self) -> None:
        body = {
            "prompt": {
                "80": {
                    "class_type": "LoraLoader",
                    "inputs": {
                        "lora_name": "https://civitai.com/api/download/models/1",
                        "model": ["119", 0],
                        "clip": ["71", 0],
                    },
                },
                "119": {
                    "class_type": "UNETLoader",
                    "inputs": {"unet_name": "flux-2-klein-9b-fp8.safetensors"},
                },
                "9": {
                    "class_type": "SaveImage",
                    "inputs": {"filename_prefix": "k", "images": ["8", 0]},
                },
            }
        }
        cands = cv.ablate_candidates(body)
        self.assertEqual(cands[0][0], "80")
        ids = [nid for nid, _cls in cands]
        self.assertIn("119", ids)
        self.assertNotIn("9", ids)
        dropped = cv.prompt_without_node(body, "80")
        self.assertNotIn("80", dropped["prompt"])
        self.assertIn("80", body["prompt"])
        self.assertIn("119", dropped["prompt"])
        dropped_unet = cv.prompt_without_node(body, "119")
        self.assertNotIn("119", dropped_unet["prompt"])
        self.assertIn("80", dropped_unet["prompt"])

    def test_apply_clip_texts_opt_in(self) -> None:
        body = {
            "prompt": {
                "74": {
                    "class_type": "CLIPTextEncode",
                    "inputs": {"text": "", "clip": ["71", 0]},
                },
                "67": {
                    "class_type": "CLIPTextEncode",
                    "inputs": {"text": "", "clip": ["71", 0]},
                },
                "121": {
                    "class_type": "CFGGuider",
                    "inputs": {
                        "positive": ["74", 0],
                        "negative": ["67", 0],
                    },
                },
            }
        }
        changed = cv.apply_clip_texts(
            body,
            positive="a woman asleep among crystals",
            negative="blurry",
        )
        self.assertTrue(changed["positive"])
        self.assertTrue(changed["negative"])
        pos, neg = cv.extract_clip_pair(body)
        self.assertEqual(pos, "a woman asleep among crystals")
        self.assertEqual(neg, "blurry")


class CompareImages(unittest.TestCase):
    def _pair(self, td: str | Path) -> tuple[Path, Path]:
        site = Path(td) / "site.jpg"
        gen = Path(td) / "gen.jpg"
        site.write_bytes(_JPEG_2X2)
        gen.write_bytes(_JPEG_2X2)
        return site, gen

    def test_shared_subject_is_similar(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            site, gen = self._pair(td)
            journal = _journal(td)

            def describe_fn(p: Path) -> str:
                if p.resolve() == gen.resolve() or p.name.startswith("gen"):
                    return "a woman stands in a forest clearing in warm sunlight"
                return "a woman standing in a sunlit forest clearing"

            event = cv.compare_generated_to_site(
                journal,
                url=SAMPLE,
                generated_path=gen,
                describe_fn=describe_fn,
                fetch_site_fn=_write_jpeg,
            )
            self.assertTrue(event.get("ok"))
            self.assertTrue(event.get("similar"))
            self.assertFalse(event.get("significantly_different"))
            row = _by_step(journal, "compare")[0]
            self.assertIn("woman", row["site_description"])
            self.assertIn("woman", row["generated_description"])
            self.assertFalse(_by_step(journal, "backtrack"))

    def test_crowded_path_vs_solitary_figure_is_significant(self) -> None:
        site_text = (
            "A single full-page watercolor. Several small figures walk a stone "
            "path under an autumn canopy; a girl in a yellow jumper reaches for a leaf."
        )
        gen_text = (
            "A single full-page watercolor. One girl with a satchel stands solitary "
            "beside a large oak at sunset on a forest path."
        )
        self.assertFalse(cv.descriptions_are_similar(site_text, gen_text))

    def test_single_plate_vs_three_panel_is_significant(self) -> None:
        site_text = (
            "A tall watercolor of an autumn forest canopy in red, orange, and gold. "
            "Several small figures walk a stone path covered in fallen leaves; "
            "a girl in a yellow jumper reaches up for a falling leaf."
        )
        gen_text = (
            "A three-panel watercolor comic of one girl with short dark hair, "
            "coat, skirt, and satchel. She stands beside a large oak at sunset, "
            "then the tree fills the middle panel, then she walks into sunbeams "
            "on a forest path."
        )
        self.assertFalse(cv.descriptions_are_similar(site_text, gen_text))
        with tempfile.TemporaryDirectory() as td:
            journal = _journal(td)
            event = cv.complete_compare_with_texts(
                journal,
                url="https://civitai.com/images/130704876",
                site_description=site_text,
                generated_description=gen_text,
            )
            self.assertTrue(event.get("significantly_different"))
            self.assertFalse(event.get("similar"))
            self.assertTrue(_by_step(journal, "backtrack"))

    def test_different_subject_is_significant_and_journaled(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            site, gen = self._pair(td)
            journal = _journal(td)
            site_text = "a woman standing in a sunlit forest clearing"
            gen_text = "empty gray noise field with no figure"

            def describe_fn(p: Path) -> str:
                if p.resolve() == gen.resolve():
                    return gen_text
                return site_text

            event = cv.compare_generated_to_site(
                journal,
                url=SAMPLE,
                generated_path=gen,
                describe_fn=describe_fn,
                fetch_site_fn=_write_jpeg,
            )
            self.assertTrue(event.get("ok"))
            self.assertTrue(event.get("significantly_different"))
            self.assertFalse(event.get("similar"))
            row = _by_step(journal, "compare")[0]
            self.assertEqual(row["site_description"], site_text)
            self.assertEqual(row["generated_description"], gen_text)

    def test_skip_without_generated_jpeg(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            journal = _journal(td)
            event = cv.compare_generated_to_site(
                journal,
                url=SAMPLE,
                generated_path=None,
            )
            self.assertEqual(event.get("skipped"), "no POST JPEG")
            self.assertFalse(event.get("ok"))

    def test_skip_when_describe_raises(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            site, gen = self._pair(td)
            journal = _journal(td)

            def boom(_p: Path) -> str:
                raise RuntimeError("vision down")

            event = cv.compare_generated_to_site(
                journal,
                url=SAMPLE,
                generated_path=gen,
                body={
                    "prompt": {
                        "67": {
                            "class_type": "CLIPTextEncode",
                            "inputs": {"text": "", "clip": ["71", 0]},
                        }
                    }
                },
                describe_fn=boom,
                fetch_site_fn=_write_jpeg,
            )
            self.assertEqual(event.get("skipped"), "pending_local_describe")
            self.assertTrue(event.get("pending_local_describe"))
            self.assertTrue(event.get("site_image"))
            self.assertTrue(event.get("generated"))
            self.assertIn("vision down", str(event.get("error") or ""))
            bt = _by_step(journal, "backtrack")
            self.assertTrue(bt)
            self.assertTrue(
                any("CLIP" in str(x) for x in bt[0].get("json_request") or [])
            )
            self.assertTrue(bt[0].get("import_conversion"))

    def test_record_local_descriptions_marks_different_and_backtracks(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            journal = _journal(td)
            (journal.dir / "last_prompt.json").write_text(
                json.dumps(
                    {
                        "prompt": {
                            "67": {
                                "class_type": "CLIPTextEncode",
                                "inputs": {"text": "", "clip": ["71", 0]},
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            event = cv.complete_compare_with_texts(
                journal,
                url=SAMPLE,
                site_description="a woman standing in a sunlit forest clearing",
                generated_description="empty gray noise field with no figure",
            )
            self.assertTrue(event.get("ok"))
            self.assertTrue(event.get("local_describe"))
            self.assertTrue(event.get("significantly_different"))
            bt = _by_step(journal, "backtrack")
            self.assertTrue(bt)
            self.assertTrue(
                any("CLIP" in str(x) for x in bt[0].get("json_request") or [])
            )
            rc = cv.main(
                [
                    "--journal",
                    str(journal.dir),
                    "--record-compare",
                    "--site-description",
                    "a woman standing in a sunlit forest clearing",
                    "--generated-description",
                    "a woman stands in a forest clearing in warm sunlight",
                ]
            )
            self.assertEqual(rc, 0)
            compares = _by_step(journal, "compare")
            self.assertTrue(any(c.get("local_describe") and c.get("similar") for c in compares))

    def test_different_empty_clip_backtracks_json_then_import(self) -> None:
        body = {
            "prompt": {
                "67": {
                    "class_type": "CLIPTextEncode",
                    "inputs": {"text": "", "clip": ["71", 0]},
                },
                "9": {
                    "class_type": "SaveImage",
                    "inputs": {"filename_prefix": "x", "images": ["8", 0]},
                },
            }
        }
        inspect = {
            "notes": [
                "LoadImage #76 TiledMultiDiff.png is a local file; Generate omits it."
            ],
            "replica_issues": [
                "LoadImage #76 TiledMultiDiff.png is a local file; Generate omits it."
            ],
        }
        with tempfile.TemporaryDirectory() as td:
            site, gen = self._pair(td)
            journal = _journal(td)

            def describe_fn(p: Path) -> str:
                if p.resolve() == gen.resolve():
                    return "empty gray noise field with no figure"
                return "a woman standing in a sunlit forest clearing"

            cv.compare_generated_to_site(
                journal,
                url=SAMPLE,
                generated_path=gen,
                body=body,
                inspect=inspect,
                describe_fn=describe_fn,
                fetch_site_fn=_write_jpeg,
            )
            bt = _by_step(journal, "backtrack")
            self.assertTrue(bt)
            json_find = " ".join(bt[0]["json_request"])
            imp_find = " ".join(bt[0]["import_conversion"])
            self.assertIn("CLIP", json_find)
            self.assertIn("LoadImage", json_find)
            self.assertTrue(imp_find)
            self.assertIn("import", imp_find.lower() + " convert " + imp_find.lower())


class CliMain(unittest.TestCase):
    def test_import_edits_are_opt_in(self) -> None:
        parser = cv.build_arg_parser()
        bare = parser.parse_args([SAMPLE, "--journal", "j"])
        self.assertFalse(bare.edit_import)
        on = parser.parse_args([SAMPLE, "--journal", "j", "--edit-import"])
        self.assertTrue(on.edit_import)
        off = parser.parse_args([SAMPLE, "--journal", "j", "--no-edit-import"])
        self.assertFalse(off.edit_import)
        both = parser.parse_args(
            [SAMPLE, "--journal", "j", "--edit-import", "--no-edit-import"]
        )
        self.assertFalse(both.edit_import)

    def test_main_writes_journal_with_required_steps(self) -> None:
        def snap(gateway: str, key: str) -> dict:
            return _snap("Downloading 10%", "flux2-klein2")

        with tempfile.TemporaryDirectory() as td:
            extras = Path(td) / "extras.json"
            extras.write_text("{}", encoding="utf-8")
            fixture = Path(td) / "fixture.json"
            fixture.write_text(
                json.dumps(
                    {
                        "metadata": cv.DEFAULT_FIXTURE_META,
                        "workflow": "",
                        "image_id": "fixture",
                    }
                ),
                encoding="utf-8",
            )
            journal_dir = Path(td) / "j"
            src = Path(td) / "src"
            src.mkdir()
            (src / "comfy_import.py").write_text("x=1\n", encoding="utf-8")
            (src / "request_json.py").write_text("y=2\n", encoding="utf-8")
            argv = [
                SAMPLE,
                "--journal",
                str(journal_dir),
                "--no-post",
                "--fixture",
                str(fixture),
                "--extras",
                str(extras),
                "--source-root",
                str(src),
                "--out",
                str(Path(td) / "out"),
            ]
            with patch.object(cv, "studio_gateway_targets", return_value=[
                ("klein", "https://klein.example/"),
                ("klein5090", "https://k5090.example/"),
            ]), patch.object(
                cv.salad_status, "snapshot_gateway", side_effect=snap
            ), patch.object(
                cv.tokens, "resolve_salad_key", return_value="test-key"
            ), patch.object(
                cv.ci, "fetch_civitai_image_pastes", side_effect=RuntimeError("offline")
            ):
                rc = cv.main(argv)
            journal = cv.Journal(journal_dir)
            steps = set(_steps(journal))
            self.assertEqual(rc, 0)
            self.assertIn("container-list", steps)
            self.assertTrue({"fetch", "convert"} & steps)
            self.assertTrue(_by_step(journal, "convert"))
            post = _by_step(journal, "post")
            self.assertTrue(post)
            self.assertTrue(post[0].get("skipped"))
            listed = _by_step(journal, "container-list")[0]
            ids = [g["profile_id"] for g in listed["groups"]]
            self.assertEqual(ids, ["klein", "klein5090"])


if __name__ == "__main__":
    unittest.main()
