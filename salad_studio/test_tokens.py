"""Token files for Salad Studio. Isolated local JSON + temp default ~/.config."""
from __future__ import annotations

import json
import os
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

from salad_studio import tokens as tok  # noqa: E402

GITIGNORE = HERE.parent / ".gitignore"


def _walk(widget):
    yield widget
    for child in widget.winfo_children():
        yield from _walk(child)


def _labelframe_texts(root) -> list[str]:
    from tkinter import ttk

    return [str(w.cget("text")) for w in _walk(root) if isinstance(w, ttk.LabelFrame)]


def _label_texts(root) -> list[str]:
    from tkinter import ttk

    return [str(w.cget("text")) for w in _walk(root) if isinstance(w, ttk.Label)]


def _header(request, name: str) -> str | None:
    """Header lookup that does not depend on urllib's ``capitalize()`` casing."""
    for key, value in request.headers.items():
        if key.lower() == name.lower():
            return str(value)
    return None


class _FakeSend:
    """Records the real request and answers with a canned status."""

    def __init__(self, status: int = 200, boom: bool = False) -> None:
        self.status = status
        self.boom = boom
        self.requests: list = []

    def __call__(self, request, timeout):
        self.requests.append(request)
        if self.boom:
            raise OSError("network down")
        return self.status, b"{}"


class KeyValidity(unittest.TestCase):
    def setUp(self) -> None:
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        root = Path(self._td.name)
        self._old_home = tok.CONFIG_HOME
        self._old_local = tok.LOCAL_PATH
        tok.CONFIG_HOME = root / "defaults"
        tok.LOCAL_PATH = root / "studio-tokens.json"
        self.addCleanup(lambda: setattr(tok, "CONFIG_HOME", self._old_home))
        self.addCleanup(lambda: setattr(tok, "LOCAL_PATH", self._old_local))

    def test_fal_is_gone_and_every_remaining_kind_can_be_checked(self) -> None:
        kinds = [kind for kind, _l, _r in tok.TOKEN_SPECS]
        self.assertEqual(kinds, ["salad", "huggingface", "civitai", "deepseek"])
        self.assertNotIn("fal", kinds)
        with self.assertRaises(KeyError):
            tok.default_path("fal")
        self.assertEqual(sorted(tok.PROBE_SPECS), sorted(kinds))

    def test_salad_probe_url_agrees_with_salad_status(self) -> None:
        from salad_studio import salad_status

        expected = (
            f"{salad_status.API}/organizations/{salad_status.ORG}"
            f"/projects/{salad_status.PROJECT}/containers"
        )
        self.assertEqual(tok.PROBE_SPECS["salad"][0], expected)

    def test_probe_request_carries_the_key_in_the_right_header(self) -> None:
        for kind, (_url, header) in tok.PROBE_SPECS.items():
            with self.subTest(kind=kind):
                request = tok.probe_request(kind, "abc123")
                self.assertEqual(request.get_method(), "GET")
                if header == "Authorization":
                    self.assertEqual(_header(request, header), "Bearer abc123")
                else:
                    self.assertEqual(_header(request, header), "abc123")

    def test_accepted_key_is_valid_for_every_kind(self) -> None:
        for kind in tok.PROBE_SPECS:
            with self.subTest(kind=kind):
                send = _FakeSend(200)
                result = tok.probe_token(kind, send=send, key="abc123")
                self.assertEqual(result["state"], tok.VALID)
                self.assertEqual(len(send.requests), 1)

    def test_rejected_key_is_invalid_for_every_kind(self) -> None:
        for kind in tok.PROBE_SPECS:
            for status in (401, 403):
                with self.subTest(kind=kind, status=status):
                    result = tok.probe_token(kind, send=_FakeSend(status), key="abc123")
                    self.assertEqual(result["state"], tok.INVALID)
                    self.assertIn(str(status), result["detail"])

    def test_transport_failure_is_unknown_never_valid(self) -> None:
        result = tok.probe_token("civitai", send=_FakeSend(boom=True), key="abc123")
        self.assertEqual(result["state"], tok.UNKNOWN)
        self.assertNotEqual(result["state"], tok.VALID)
        self.assertIn("OSError", result["detail"])

    def test_unexpected_status_is_unknown(self) -> None:
        result = tok.probe_token("salad", send=_FakeSend(500), key="abc123")
        self.assertEqual(result["state"], tok.UNKNOWN)
        self.assertIn("500", result["detail"])

    def test_missing_key_is_unknown_and_never_calls_out(self) -> None:
        for kind in tok.PROBE_SPECS:
            with self.subTest(kind=kind):
                send = _FakeSend(200)
                result = tok.probe_token(kind, send=send, key="")
                self.assertEqual(result["state"], tok.UNKNOWN)
                self.assertEqual(send.requests, [])
                self.assertIn("no key", result["detail"])

    def test_stored_key_is_what_gets_probed(self) -> None:
        # salad has no environment fallback, so the store is the only source.
        tok.write_token("salad", "salad-stored-key")
        send = _FakeSend(200)
        tok.probe_token("salad", send=send)
        self.assertEqual(
            _header(send.requests[0], "Salad-Api-Key"), "salad-stored-key"
        )

    def test_environment_key_is_probed_when_no_file_has_one(self) -> None:
        with mock.patch.dict(os.environ, {"DEEPSEEK_API_KEY": "ds-env-only"}):
            send = _FakeSend(200)
            tok.probe_token("deepseek", send=send)
        self.assertEqual(
            _header(send.requests[0], "Authorization"), "Bearer ds-env-only"
        )

    def test_probe_all_covers_every_probe_spec(self) -> None:
        for kind, _l, _r in tok.TOKEN_SPECS:
            tok.write_token(kind, f"{kind}-key")
        results = tok.probe_all(send=_FakeSend(200), timeout=1)
        self.assertEqual(sorted(results), sorted(tok.PROBE_SPECS))
        self.assertTrue(all(r["state"] == tok.VALID for r in results.values()))

    def test_probe_all_reports_an_empty_slot_as_unknown(self) -> None:
        results = tok.probe_all(send=_FakeSend(200), timeout=1)
        self.assertEqual(sorted(results), sorted(tok.PROBE_SPECS))
        for kind, result in results.items():
            with self.subTest(kind=kind):
                self.assertIn(result["state"], (tok.UNKNOWN, tok.VALID))

    def test_state_color_maps_each_state_to_its_own_palette_key(self) -> None:
        keys = {
            tok.state_color(tok.VALID),
            tok.state_color(tok.INVALID),
            tok.state_color(tok.UNKNOWN),
        }
        self.assertEqual(keys, {"valid", "invalid", "unknown"})
        self.assertEqual(tok.state_color("checking"), "unknown")
        from salad_studio.theme import PALETTE

        for key in keys:
            self.assertIn(key, PALETTE)


class TokenFiles(unittest.TestCase):
    def setUp(self) -> None:
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        root = Path(self._td.name)
        self._old_home = tok.CONFIG_HOME
        self._old_local = tok.LOCAL_PATH
        tok.CONFIG_HOME = root / "defaults"
        tok.LOCAL_PATH = root / "studio-tokens.json"
        self.addCleanup(lambda: setattr(tok, "CONFIG_HOME", self._old_home))
        self.addCleanup(lambda: setattr(tok, "LOCAL_PATH", self._old_local))

    def test_local_path_is_gitignored(self) -> None:
        text = GITIGNORE.read_text(encoding="utf-8")
        self.assertIn("salad_studio/studio-tokens.json", text)

    def test_paths_stay_under_temp(self) -> None:
        self.assertEqual(tok.token_path("salad"), tok.LOCAL_PATH)
        self.assertTrue(str(tok.default_path("salad")).startswith(str(tok.CONFIG_HOME)))
        self.assertNotEqual(tok.LOCAL_PATH, HERE / "studio-tokens.json")

    def test_read_missing_is_empty(self) -> None:
        self.assertEqual(tok.read_token("salad"), "")
        self.assertEqual(tok.masked(""), "(missing)")

    def test_write_stays_in_local_json_not_defaults(self) -> None:
        tok.write_token("salad", " salad-secret-value \n")
        tok.write_token("huggingface", "hf_abcdefghijklmnop")
        tok.write_token("civitai", "civitai-token-32chars-xxxxxx")
        self.assertEqual(tok.read_token("salad"), "salad-secret-value")
        self.assertEqual(tok.read_token("huggingface"), "hf_abcdefghijklmnop")
        self.assertEqual(tok.read_token("civitai"), "civitai-token-32chars-xxxxxx")
        self.assertEqual(tok.masked(tok.read_token("salad")), "set (…alue)")
        self.assertTrue(tok.LOCAL_PATH.is_file())
        self.assertFalse(tok.default_path("salad").exists())
        doc = json.loads(tok.LOCAL_PATH.read_text(encoding="utf-8"))
        self.assertEqual(doc["salad"], "salad-secret-value")

    def test_empty_local_seeds_from_default_storage(self) -> None:
        salad_def = tok.default_path("salad")
        salad_def.parent.mkdir(parents=True)
        salad_def.write_text("from-default-salad\n", encoding="utf-8")
        hf_def = tok.default_path("huggingface")
        hf_def.parent.mkdir(parents=True)
        hf_def.write_text("from-default-hf\n", encoding="utf-8")
        copied = tok.seed_from_defaults()
        self.assertIn("salad", copied)
        self.assertIn("huggingface", copied)
        self.assertEqual(tok.read_token("salad"), "from-default-salad")
        self.assertEqual(tok.read_token("huggingface"), "from-default-hf")
        doc = json.loads(tok.LOCAL_PATH.read_text(encoding="utf-8"))
        self.assertEqual(doc["salad"], "from-default-salad")

    def test_local_value_wins_over_default(self) -> None:
        tok.write_token("salad", "local-wins")
        salad_def = tok.default_path("salad")
        salad_def.parent.mkdir(parents=True)
        salad_def.write_text("default-ignored\n", encoding="utf-8")
        self.assertEqual(tok.seed_from_defaults(), [])
        self.assertEqual(tok.read_token("salad"), "local-wins")

    def test_resolve_salad_key_uses_local_then_path(self) -> None:
        with self.assertRaises(FileNotFoundError):
            tok.resolve_salad_key()
        other = Path(self._td.name) / "override.key"
        other.write_text("override-key\n", encoding="utf-8")
        self.assertEqual(tok.resolve_salad_key(str(other)), "override-key")
        tok.write_token("salad", "slot-key")
        self.assertEqual(tok.resolve_salad_key(), "slot-key")
        self.assertEqual(tok.resolve_salad_key(str(other)), "slot-key")

    def test_deepseek_slot_is_offered_with_a_default_file(self) -> None:
        kinds = [kind for kind, _label, _rel in tok.TOKEN_SPECS]
        self.assertIn("deepseek", kinds)
        self.assertEqual(tok.token_label("deepseek"), "DeepSeek")
        self.assertEqual(tok.default_path("deepseek"), tok.CONFIG_HOME / "deepseek" / "key")
        self.assertEqual(tok.token_path("deepseek"), tok.LOCAL_PATH)

    def test_deepseek_reads_the_environment_when_no_file_has_it(self) -> None:
        with mock.patch.dict(os.environ, {"DEEPSEEK_API_KEY": "  ds-env-key  "}):
            self.assertEqual(tok.read_env_token("deepseek"), "ds-env-key")
            self.assertEqual(tok.read_token("deepseek"), "ds-env-key")
            # The environment value is never copied into the store.
            self.assertFalse(tok.LOCAL_PATH.is_file())
            self.assertEqual(tok.seed_from_defaults(), [])
            self.assertFalse(tok.LOCAL_PATH.is_file())

    def test_deepseek_file_and_local_value_win_over_the_environment(self) -> None:
        with mock.patch.dict(os.environ, {"DEEPSEEK_API_KEY": "ds-env-key"}):
            ds_def = tok.default_path("deepseek")
            ds_def.parent.mkdir(parents=True)
            ds_def.write_text("from-default-deepseek\n", encoding="utf-8")
            self.assertEqual(tok.read_token("deepseek"), "from-default-deepseek")
            tok.write_token("deepseek", "ds-local-key")
            self.assertEqual(tok.read_token("deepseek"), "ds-local-key")
            doc = json.loads(tok.LOCAL_PATH.read_text(encoding="utf-8"))
            self.assertEqual(doc["deepseek"], "ds-local-key")

    def test_deepseek_default_label_names_the_environment_variable(self) -> None:
        self.assertIn("deepseek", tok.default_label("deepseek"))
        self.assertIn("DEEPSEEK_API_KEY", tok.default_label("deepseek"))
        # Kinds without an env fallback keep the plain path label.
        self.assertEqual(tok.default_label("salad"), str(tok.default_path("salad")))
        self.assertEqual(tok.env_var("salad"), "")
        self.assertEqual(tok.read_env_token("salad"), "")

    def test_every_kind_has_a_slot_in_the_saved_store(self) -> None:
        tok.write_token("deepseek", "ds-only")
        doc = json.loads(tok.LOCAL_PATH.read_text(encoding="utf-8"))
        self.assertEqual(
            sorted(doc), sorted(kind for kind, _l, _r in tok.TOKEN_SPECS)
        )
        self.assertIn("deepseek", doc)


try:
    import tkinter as tk
except ImportError as _tk_err:
    tk = None  # type: ignore[assignment]
    _TK_IMPORT_ERROR = _tk_err
else:
    _TK_IMPORT_ERROR = None


@unittest.skipIf(tk is None, f"tkinter unavailable: {_TK_IMPORT_ERROR}")
class LiveTokensTab(unittest.TestCase):
    def test_tokens_tab_loads_saved_salad_key_and_generate_reads_it(self) -> None:
        try:
            probe = tk.Tk()
            probe.withdraw()
            probe.destroy()
        except tk.TclError as e:
            raise unittest.SkipTest(f"Tk cannot initialize: {e}") from e

        from salad_studio.app import SaladStudio
        from salad_studio import lora_store, profiles

        old_home = tok.CONFIG_HOME
        old_local = tok.LOCAL_PATH
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            tok.CONFIG_HOME = tmp / "defaults"
            tok.LOCAL_PATH = tmp / "studio-tokens.json"
            try:
                tok.write_token("salad", "salad-live-key-xyz9")
                tok.write_token("huggingface", "hf_live_token_abcd")
                profiles.PROFILES_PATH = tmp / "studio-profiles.json"
                lora_store.EXTRAS_PATH = tmp / "studio-loras.json"
                app = SaladStudio(show=False)
                app.withdraw()
                try:
                    app.update_idletasks()
                    from salad_studio import app as app_mod

                    tabs = [app.nb.tab(t, "text") for t in app.nb.tabs()]
                    self.assertEqual(tabs, list(app_mod.TAB_ORDER))
                    self.assertEqual(
                        app._token_entry["salad"].get(), "salad-live-key-xyz9"
                    )
                    self.assertEqual(
                        app._token_entry["huggingface"].get(), "hf_live_token_abcd"
                    )
                    # Every spec gets a box; the DeepSeek one names its env fallback.
                    for kind, _label, _rel in tok.TOKEN_SPECS:
                        self.assertIn(kind, app._token_entry)
                        self.assertIn(kind, app._token_widgets)
                    boxes = _labelframe_texts(app._tokens)
                    self.assertIn("DeepSeek", boxes)
                    self.assertIn("Salad API", boxes)
                    labels = _label_texts(app._tokens)
                    self.assertTrue(
                        any("DEEPSEEK_API_KEY" in text for text in labels),
                        "the DeepSeek box should name its environment fallback",
                    )
                    self.assertTrue(
                        any("deepseek" in text for text in labels),
                        "the DeepSeek box should show its default file path",
                    )
                    self.assertEqual(str(app._token_widgets["salad"].cget("show")), "*")
                    app._token_show["salad"].set(True)
                    app._toggle_token_visible("salad")
                    self.assertEqual(str(app._token_widgets["salad"].cget("show")), "")
                    app._token_show["salad"].set(False)
                    app._toggle_token_visible("salad")
                    self.assertEqual(str(app._token_widgets["salad"].cget("show")), "*")
                    self.assertEqual(app._salad_api_key(), "salad-live-key-xyz9")
                    app._token_entry["salad"].set("salad-replaced-key-Q")
                    app._save_token("salad")
                    self.assertEqual(tok.read_token("salad"), "salad-replaced-key-Q")
                    self.assertEqual(app._salad_api_key(), "salad-replaced-key-Q")
                    self.assertEqual(app._token_entry["salad"].get(), "salad-replaced-key-Q")
                    self.assertTrue(tok.LOCAL_PATH.is_file())
                    self.assertFalse(tok.default_path("salad").exists())
                finally:
                    app.destroy()
            finally:
                tok.CONFIG_HOME = old_home
                tok.LOCAL_PATH = old_local


if __name__ == "__main__":
    unittest.main()
