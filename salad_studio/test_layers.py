"""The five non-UI layers run in a process where tkinter is never imported.

A subprocess drives one real call per layer -- import, persistence, logging,
Salad communication, AI communication -- and then asserts that ``tkinter`` is
not in ``sys.modules``. The UI layer is the one that is allowed to import it, so
a regression here means widget code crept back into a layer.
"""
from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOOLS = HERE.parent

PROBE = r'''
import sys, tempfile
from pathlib import Path

root = Path.cwd()
for p in (root, root / "salad_studio"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

tmp = Path(tempfile.mkdtemp())

import ai_helper, comfy_import, profiles, prompt_history, request_json
import salad_queue, studio_log, studio_meta, tokens

# --- import layer: build the Comfy graph the replica will run -------------
body = request_json.build_request(
    prompt_text="a watercolor portrait of an adult",
    graph="klein",
    width=64,
    height=64,
    steps=4,
    seed=1,
    selected_ids=[],
)
assert isinstance(body.get("prompt"), dict) and body["prompt"], "no graph built"
nodes = comfy_import.comfy_node_count(body)
print(f"import: built {len(body['prompt'])} nodes, comfy_node_count={nodes}")

# --- persistence layer: a token and a prompt round trip -------------------
tokens.LOCAL_PATH = tmp / "studio-tokens.json"
tokens.write_token("salad", "probe-key")
assert tokens.read_token("salad") == "probe-key", "token did not round trip"
prompt_history.HISTORY_PATH = tmp / "studio-prompt-history.json"
prompt_history.THUMBS_DIR = tmp / "thumbs"
assert prompt_history.add_prompt("probe prompt"), "prompt was not stored"
rows = prompt_history.list_prompts()
assert rows and rows[0]["text"] == "probe prompt", rows
print(f"persistence: token round trip ok, {len(rows)} prompt entry(ies)")

# --- logging layer: a formatted line and an explained HTTP failure --------
line = studio_log.format_line("ok", "probe")
assert "PROBE" in line.upper(), line
explained = studio_log.explain_http(503, b"", "https://example.salad.test/prompt")
assert "HTTP 503" in explained, explained
print(f"logging: {line.strip()} | {explained[:60]}")

# --- Salad communication layer: route a graph, queue a request -----------
doc = studio_meta.load()
family = studio_meta.family_for_unet(profiles.SNOFS_UNET, doc)
group = studio_meta.group_for_family(family, doc)
assert family == "snofs" and group, (family, group)
line_q = salad_queue.SaladQueue(sleep=lambda _s: None, now=lambda: 0.0)
job = line_q.deliver(
    {"url": "https://example.salad.test/prompt"},
    lambda _job: salad_queue.Attempt(status=200, accepted=True, result="plate"),
)
assert job.state == salad_queue.ACCEPTED, job.state
print(f"salad: {profiles.SNOFS_UNET} -> {family}/{group}, queued job {job.state}")

# --- AI communication layer: build the request, parse a reply ------------
payload = ai_helper.build_payload(editor_positive="a plate")
system = payload["messages"][0]["content"]
positive, negative = ai_helper.parse_reply('{"positive": "P", "negative": "N"}')
assert system.strip(), "the instruction is empty"
assert (positive, negative) == ("P", "N"), (positive, negative)
print(f"ai: instruction {len(system)} chars, parsed ({positive}, {negative})")

# --- the point of the probe ---------------------------------------------
imported = sorted(name for name in sys.modules if name.split(".")[0] == "tkinter")
assert not imported, f"a non-UI layer imported tkinter: {imported}"
print("layers: tkinter never imported")
'''


class LayerSeparability(unittest.TestCase):
    def test_every_layer_runs_without_tkinter(self) -> None:
        proc = subprocess.run(
            [sys.executable, "-c", PROBE],
            cwd=str(TOOLS),
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
        output = proc.stdout.strip()
        print(output)
        self.assertEqual(proc.returncode, 0, f"probe failed:\n{proc.stdout}\n{proc.stderr}")
        lines = [line for line in output.splitlines() if line.strip()]
        for prefix in ("import:", "persistence:", "logging:", "salad:", "ai:"):
            self.assertTrue(
                any(line.startswith(prefix) for line in lines),
                f"no result line for {prefix}\n{output}",
            )
        self.assertIn("layers: tkinter never imported", output)

    def test_the_ui_module_is_the_one_that_imports_tkinter(self) -> None:
        """The other half of the split: the window still lives in app.py."""
        source = (HERE / "app.py").read_text(encoding="utf-8")
        self.assertIn("import tkinter as tk", source)
        for module in (
            "ai_helper.py",
            "comfy_import.py",
            "generator.py",
            "profiles.py",
            "prompt_history.py",
            "request_json.py",
            "salad_queue.py",
            "salad_status.py",
            "studio_log.py",
            "studio_meta.py",
            "tokens.py",
        ):
            text = (HERE / module).read_text(encoding="utf-8")
            self.assertNotIn(
                "import tkinter",
                text,
                f"{module} must stay importable without the UI layer",
            )


if __name__ == "__main__":
    unittest.main()
