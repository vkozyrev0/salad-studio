"""``salad_probe_ages``'s exit code: a run with a failed plate is not a success.

The module imports Eldermark-only helpers at top level (``salad_catalog_faces``
needs ``paperdoll_mask`` and ``regen_faces``, which live outside this repo), so
those two are stubbed before the import, the way a root-script test reaches a
script whose dependencies are not installed. ``main`` is then driven with the
per-job plate function stubbed, so no gateway and no image is touched.
"""
from __future__ import annotations

import importlib
import io
import sys
import types
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
TOOLS = HERE.parent
for _p in (TOOLS / "salad_studio", TOOLS):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def _stub_module(name: str, attrs: tuple[str, ...]) -> types.ModuleType:
    module = types.ModuleType(name)
    for attr in attrs:
        setattr(module, attr, lambda *a, **k: None)
    return module


# The Eldermark tree ``salad_catalog_faces`` reaches for is not part of this repo.
_ELDERMARK_ONLY = {
    "paperdoll_mask": ("install_knockout_plate",),
    "regen_faces": ("cell_key", "load_index", "load_policy", "catalog_dir", "stage_rank"),
}


def _import_probe():
    """Import the probe, stubbing the Eldermark-only modules it needs.

    The stubs are dropped again once the import is done, so they cannot make a
    real missing module look present to the rest of the process.
    """
    stubbed = []
    for name, attrs in _ELDERMARK_ONLY.items():
        try:
            __import__(name)
        except ImportError:
            sys.modules[name] = _stub_module(name, attrs)
            stubbed.append(name)
    try:
        return importlib.import_module("salad_probe_ages"), None
    except ImportError as err:  # pragma: no cover - a broken tree, not this test
        return None, err
    finally:
        for name in stubbed:
            sys.modules.pop(name, None)


probe, _PROBE_IMPORT_ERROR = _import_probe()


@unittest.skipIf(probe is None, f"salad_probe_ages unavailable: {_PROBE_IMPORT_ERROR}")
class TheProbeExitCode(unittest.TestCase):
    """One job, one plate: the stub decides whether it failed."""

    def _run(self, plate) -> tuple[int, str]:
        """Drive ``main`` for one plate; report its return and what it printed."""
        argv = ["salad_probe_ages.py", "--sex", "female", "--stage", "adults"]
        out = io.StringIO()
        with mock.patch.object(sys, "argv", argv), mock.patch.object(
            probe.salad_gen, "_read", return_value="a-fake-key"
        ), mock.patch.object(
            probe.salad_gen, "wait_ready", return_value=None
        ), mock.patch.object(
            probe, "_civitai_token", return_value=""
        ), mock.patch.object(
            probe, "one", side_effect=plate
        ), redirect_stdout(out):
            return probe.main(), out.getvalue()

    def test_a_run_where_the_plate_failed_is_not_a_success(self) -> None:
        code, printed = self._run(lambda *a, **k: "fail salad_probe_female_adults.jpg HTTP 500")
        self.assertIn("fail salad_probe_female_adults.jpg", printed, "the line is still reported")
        self.assertNotEqual(code, 0, "a failed plate must not exit 0")

    def test_a_run_where_every_plate_landed_exits_zero(self) -> None:
        code, printed = self._run(lambda *a, **k: "ok salad_probe_female_adults.jpg 12345")
        self.assertIn("ok salad_probe_female_adults.jpg", printed)
        self.assertEqual(code, 0, "a clean run is a success")

    def test_one_failure_among_successes_still_exits_non_zero(self) -> None:
        def plate(*args, **_k) -> str:
            # main submits (key, base, sex, stage, prefix, ckpt, token, lora, strength).
            sex, stage = args[2], args[3]
            word = "ok" if sex == "female" else "fail"
            return f"{word} salad_probe_{sex}_{stage}.jpg"

        argv = ["salad_probe_ages.py", "--stage", "adults"]
        out = io.StringIO()
        with mock.patch.object(sys, "argv", argv), mock.patch.object(
            probe.salad_gen, "_read", return_value="a-fake-key"
        ), mock.patch.object(
            probe.salad_gen, "wait_ready", return_value=None
        ), mock.patch.object(
            probe, "_civitai_token", return_value=""
        ), mock.patch.object(
            probe, "one", side_effect=plate
        ), redirect_stdout(out):
            code = probe.main()
        self.assertIn("ok salad_probe_female_adults.jpg", out.getvalue())
        self.assertIn("fail salad_probe_male_adults.jpg", out.getvalue())
        self.assertNotEqual(code, 0, "the contract counts every result, not the last one")


if __name__ == "__main__":
    unittest.main()
