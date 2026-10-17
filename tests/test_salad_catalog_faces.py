"""A 504/524 from the gateway is reported, not re-POSTed, by the hand-run scripts.

``504`` and ``524`` are terminal: Cloudflare returns them after giving up on a
job the container may still be running, so the next POST to ``/prompt`` submits
a duplicate render (``salad_studio/salad_queue.py:88-91``, ``docs/workflow/21``).
``salad_catalog_faces`` and the three probes import Eldermark-only modules
(``paperdoll_mask``, ``regen_faces``) at top level, so the retry logic is reached
by exec'ing the single shipped function into a namespace instead of importing the
module. Every check drives the shipped form and a rebuild of the pre-fix form
through the same stubbed transport, and the pre-fix form must fail the check.
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import sys
import threading
import traceback
import types
import unittest
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
TOOLS = HERE.parent
for _p in (TOOLS, TOOLS / "salad_studio"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import salad_gen  # noqa: E402  (stdlib-only root script; its transport is stubbed)

CATALOG = TOOLS / "salad_catalog_faces.py"
PROBE_AGES = TOOLS / "salad_probe_ages.py"
PROBE_KLEIN = TOOLS / "salad_probe_klein.py"
PROBE_SDXL = TOOLS / "salad_probe_sdxl.py"

# The fix, per site: the shipped text and the pre-fix text it replaced. The
# pattern matches one line (or, for ``post``, the whole added block), so a
# reworded comment does not break the rebuild but a reverted fix does.
_FIXES: dict[str, tuple[str, str]] = {
    CATALOG.name: (
        r"    if code in \(502, 503, 429\):\n",
        "    if code in (502, 503, 504, 429) or code >= 500:\n",
    ),
    PROBE_AGES.name: (
        r"        if code in \(502, 503\):\n",
        "        if code in (502, 503, 504, 524):\n",
    ),
    PROBE_KLEIN.name: (
        r"        if code in \(502, 503\):\n",
        "        if code in (502, 503, 504, 524):\n",
    ),
    PROBE_SDXL.name: (
        (
            r"        if code not in \(502, 503\):\n"
            r"(?:            .*\n|\n)*?"
            r"            return 3\n"
        ),
        "",
    ),
}


def _function_source(text: str, name: str) -> str:
    """The shipped source of one top-level function, comments included."""
    for node in ast.parse(text).body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            segment = ast.get_source_segment(text, node)
            assert segment is not None, f"no source segment for {name}()"
            return segment
    raise AssertionError(f"the shipped text no longer defines {name}()")


def _load(path: Path, names: tuple[str, ...], extra: dict, *, pre_fix: bool) -> dict:
    """Exec the named shipped functions into their own globals and hand them back."""
    text = path.read_text(encoding="utf-8")
    if pre_fix:
        pattern, was = _FIXES[path.name]
        text, hits = re.subn(pattern, lambda _m: was, text, count=1)
        assert hits == 1, f"{path.name} no longer carries the fix this test guards"
    namespace = dict(extra)
    for name in names:
        code = compile(_function_source(text, name), f"<{path.name}:{name}>", "exec")
        exec(code, namespace)  # noqa: S102 - the module cannot be imported here
    return namespace


class _NoSleep:
    """A ``time`` whose sleep returns at once and whose clock stands still."""

    def sleep(self, _seconds: float) -> None:
        return None

    def time(self) -> float:
        return 0.0


class _Transport:
    """``salad_gen._req`` with one fixed answer and a count of the POSTs."""

    def __init__(self, code: int) -> None:
        self.code = code
        self.posts: list[str] = []

    def __call__(self, url: str, key: str, data: bytes | None = None, timeout: int = 30):
        if url.endswith("/prompt"):
            self.posts.append(url)
        return self.code, b'{"error": "the gateway gave up on the job"}'


def _catalog(*, pre_fix: bool) -> tuple[dict, dict]:
    """``gen_one`` and ``main`` with the transport, the clock and the catalog stubbed."""
    prog: dict = {
        "version": 1,
        "created_at": "t",
        "updated_at": "t",
        "backend": "salad-flux-dev",
        "totals": {"done": 0, "failed": 0},
        "cells": {},
    }
    extra = {
        "argparse": argparse,
        "sys": sys,
        "time": _NoSleep(),
        "traceback": traceback,
        "ThreadPoolExecutor": ThreadPoolExecutor,
        "wait": wait,
        "FIRST_COMPLETED": FIRST_COMPLETED,
        "Path": Path,
        "salad_gen": salad_gen,
        "log": lambda *a, **k: None,
        "ISO": lambda: "t",
        "cell_key": lambda entry: "cell.jpg",
        "compose": lambda params: "a prompt",
        "negatives": lambda sex: "a negative",
        "install_knockout_plate": lambda *a, **k: None,
        "load_policy": dict,
        "catalog_dir": lambda policy: Path("catalog"),
        "load_index": lambda cat: [
            {"params": {"sex": "female", "ageStage": "adults"}}
        ],
        "load_progress": lambda: prog,
        "save_progress": lambda p: None,
        "queue": lambda entries, policy, p: list(entries),
        "wait_ready": lambda **k: None,
        "PAUSE": Path("salad_PAUSE.txt-does-not-exist"),
        "_LOCK": threading.Lock(),
    }
    return _load(CATALOG, ("gen_one", "main"), extra, pre_fix=pre_fix), prog


def _drive_catalog(*, pre_fix: bool, code: int) -> tuple[int, int, str]:
    """Run ``main`` for one cell; report its exit code, POST count and cell status."""
    namespace, prog = _catalog(pre_fix=pre_fix)
    transport = _Transport(code)
    argv = [
        "salad_catalog_faces.py",
        "--generate",
        "--ignore-pause",
        "--limit",
        "1",
        "--queue-depth",
        "1",
    ]
    with mock.patch.object(salad_gen, "_req", transport), mock.patch.object(
        sys, "argv", argv
    ):
        rc = namespace["main"]()
    cell = (prog.get("cells") or {}).get("cell.jpg") or {}
    return rc, len(transport.posts), str(cell.get("status"))


def _drive_ages(*, pre_fix: bool, code: int) -> tuple[str, int]:
    """One ``salad_probe_ages.one`` call; report its line and the POST count."""
    extra = {
        "Path": Path,
        "salad_gen": salad_gen,
        "ART": Path("never-written"),
        "cat": types.SimpleNamespace(
            compose=lambda params: "a prompt", negatives=lambda sex: "n"
        ),
        "_payload_bytes": lambda *a, **k: b"{}",
    }
    one = _load(PROBE_AGES, ("one",), extra, pre_fix=pre_fix)["one"]
    transport = _Transport(code)
    with mock.patch.object(salad_gen, "_req", transport), mock.patch.object(
        salad_gen, "time", _NoSleep()
    ):
        line = one(
            "a-fake-key",
            "https://gateway.example",
            "female",
            "adults",
            "salad_probe",
            "flux1-dev-fp8.safetensors",
            "",
        )
    return line, len(transport.posts)


def _drive_klein(*, pre_fix: bool, code: int) -> tuple[str, int]:
    """One ``salad_probe_klein.one`` call; report its line and the POST count."""
    extra = {
        "Path": Path,
        "salad_gen": salad_gen,
        "klein_payload": lambda *a, **k: {"prompt": {}},
    }
    one = _load(PROBE_KLEIN, ("one",), extra, pre_fix=pre_fix)["one"]
    transport = _Transport(code)
    with mock.patch.object(salad_gen, "_req", transport), mock.patch.object(
        salad_gen, "time", _NoSleep()
    ):
        line = one(
            "https://gateway.example",
            "a-fake-key",
            "a prompt",
            Path("never-written.jpg"),
            width=1024,
            height=1024,
            use_loras=False,
        )
    return line, len(transport.posts)


def _drive_sdxl(*, pre_fix: bool, code: int) -> tuple[int, int]:
    """One ``salad_probe_sdxl.post`` call; report its exit code and the POST count."""
    extra = {
        "json": json,
        "time": _NoSleep(),
        "ART": Path("never-written"),
        "salad_gen": salad_gen,
    }
    post = _load(PROBE_SDXL, ("post",), extra, pre_fix=pre_fix)["post"]
    transport = _Transport(code)
    with mock.patch.object(salad_gen, "_req", transport):
        rc = post(
            "https://gateway.example",
            "a-fake-key",
            {"1": {"class_type": "KSampler"}},
            "",
            "salad_probe_sdxl_probe.jpg",
        )
    return rc, len(transport.posts)


class CatalogFacesReportsATimeoutInsteadOfRePosting(unittest.TestCase):
    """C1: a cell the gateway timed out on costs one POST, not 24."""

    def _one_post(self, *, pre_fix: bool, code: int) -> None:
        rc, posts, status = _drive_catalog(pre_fix=pre_fix, code=code)
        self.assertEqual(
            posts,
            1,
            f"HTTP {code} must be reported, not re-submitted: {posts} POSTs for one cell",
        )
        self.assertEqual(status, "failed", f"HTTP {code} is terminal for the cell")
        self.assertEqual(rc, 1, "a run with a failed cell reports it in the exit code")

    def test_a_504_costs_one_post_and_fails_the_cell(self) -> None:
        self._one_post(pre_fix=False, code=504)
        with self.assertRaises(AssertionError, msg="the pre-fix form re-POSTs the cell"):
            self._one_post(pre_fix=True, code=504)

    def test_a_524_costs_one_post_and_fails_the_cell(self) -> None:
        self._one_post(pre_fix=False, code=524)
        with self.assertRaises(AssertionError, msg="the pre-fix form re-POSTs the cell"):
            self._one_post(pre_fix=True, code=524)

    def test_another_5xx_is_terminal_too(self) -> None:
        for code in (500, 501, 505):
            with self.subTest(code=code):
                self._one_post(pre_fix=False, code=code)
        with self.assertRaises(AssertionError, msg="the pre-fix form re-POSTs any 5xx"):
            self._one_post(pre_fix=True, code=500)

    def test_the_retryable_codes_still_re_submit_the_cell(self) -> None:
        for code in (502, 503, 429):
            with self.subTest(code=code):
                _rc, posts, status = _drive_catalog(pre_fix=False, code=code)
                self.assertGreater(posts, 1, f"HTTP {code} is a dead replica: still retried")
                self.assertEqual(status, "failed", "the retry cap still ends the cell")


class TheProbesReportATimeoutInsteadOfRePosting(unittest.TestCase):
    """C2: one ``one()``/``post()`` call must answer a 504/524 with one POST."""

    def _ages_one_post(self, *, pre_fix: bool, code: int) -> None:
        line, posts = _drive_ages(pre_fix=pre_fix, code=code)
        self.assertEqual(posts, 1, f"HTTP {code} must be reported: {posts} POSTs")
        self.assertIn(f"HTTP {code}", line, "the gateway code is still named")

    def test_salad_probe_ages_reports_a_504_after_one_post(self) -> None:
        self._ages_one_post(pre_fix=False, code=504)
        with self.assertRaises(AssertionError, msg="the pre-fix form re-POSTs"):
            self._ages_one_post(pre_fix=True, code=504)

    def _klein_one_post(self, *, pre_fix: bool, code: int) -> None:
        line, posts = _drive_klein(pre_fix=pre_fix, code=code)
        self.assertEqual(posts, 1, f"HTTP {code} must be reported: {posts} POSTs")
        self.assertIn(f"HTTP {code}", line, "the gateway code is still named")

    def test_salad_probe_klein_reports_a_524_after_one_post(self) -> None:
        self._klein_one_post(pre_fix=False, code=524)
        with self.assertRaises(AssertionError, msg="the pre-fix form re-POSTs"):
            self._klein_one_post(pre_fix=True, code=524)

    def _sdxl_one_post(self, *, pre_fix: bool, code: int) -> None:
        rc, posts = _drive_sdxl(pre_fix=pre_fix, code=code)
        self.assertEqual(posts, 1, f"HTTP {code} must be reported: {posts} POSTs")
        self.assertNotEqual(rc, 0, "a plate that never landed is not a success")

    def test_salad_probe_sdxl_reports_a_504_after_one_post(self) -> None:
        self._sdxl_one_post(pre_fix=False, code=504)
        with self.assertRaises(AssertionError, msg="the pre-fix form re-POSTs"):
            self._sdxl_one_post(pre_fix=True, code=504)

    def test_salad_probe_sdxl_still_re_submits_a_502(self) -> None:
        rc, posts = _drive_sdxl(pre_fix=False, code=502)
        self.assertEqual(posts, 9, "a dead replica is still retried, nine tries as shipped")
        self.assertNotEqual(rc, 0, "nine dead replicas are still a failure")


class ProgressFileSurvivesACrash(unittest.TestCase):
    """A partial progress file must not stop every later run."""

    def _namespace(self, tmp: Path, *, pre_fix: bool = False) -> dict:
        import os
        import tempfile

        extra = {
            "json": json,
            "os": os,
            "tempfile": tempfile,
            "time": _NoSleep(),
            "PROGRESS": tmp / "salad_progress.json",
            "ISO": lambda: "t",
            "log": lambda _message: None,
        }
        return _load(
            CATALOG,
            ("_empty_progress", "load_progress", "save_progress"),
            extra,
            pre_fix=pre_fix,
        )

    def test_a_partial_progress_file_is_moved_aside(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            ns = self._namespace(Path(td))
            ns["PROGRESS"].write_text("{not json", encoding="utf-8")
            prog = ns["load_progress"]()
            self.assertEqual(prog["cells"], {})
            self.assertFalse(ns["PROGRESS"].exists(), "the bad file is out of the way")
            self.assertTrue(
                list(Path(td).glob("salad_progress.json.corrupt-*")),
                "and kept for inspection",
            )

    def test_save_publishes_one_whole_file(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            ns = self._namespace(Path(td))
            prog = ns["_empty_progress"]()
            prog["cells"] = {"a.jpg": {"status": "done"}}
            ns["save_progress"](prog)
            self.assertEqual(ns["load_progress"]()["totals"]["done"], 1)
            self.assertEqual(
                [p.name for p in Path(td).glob("*.tmp")],
                [],
                "no temp file is left behind",
            )


if __name__ == "__main__":
    unittest.main()
