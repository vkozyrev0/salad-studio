"""The seven non-UI layers run in a process where tkinter is never imported.

A subprocess drives one real call per layer -- import, persistence, logging,
Salad communication, Vast.ai communication, image deployment, AI communication
-- and then asserts that ``tkinter`` is not in ``sys.modules``. The UI layer is
the one that is allowed to import it, so a regression here means widget code
crept back into a layer.
"""
from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOOLS = HERE.parent
PKG = TOOLS / "salad_studio"

PROBE = r'''
import sys, tempfile
from pathlib import Path

root = Path.cwd()
for p in (root, root / "salad_studio"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

tmp = Path(tempfile.mkdtemp())

import ai_helper, comfy_import, image_deploy, profiles, prompt_history, request_json
import salad_queue, studio_log, studio_meta, tokens, vast

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
seed = profiles.seed_checkpoints("klein5090", doc)
assert family == "snofs" and seed == [profiles.SNOFS_UNET], (family, seed)
line_q = salad_queue.SaladQueue(sleep=lambda _s: None, now=lambda: 0.0)
job = line_q.deliver(
    {"url": "https://example.salad.test/prompt"},
    lambda _job: salad_queue.Attempt(status=200, accepted=True, result="plate"),
    line="klein5090",
)
assert job.state == salad_queue.ACCEPTED, job.state
print(
    f"salad: {profiles.SNOFS_UNET} -> {family}, "
    f"profile klein5090 serves {len(seed)} checkpoint(s), queued job {job.state}"
)

# --- Vast.ai communication layer: list an account, keep two instances -----
vast.INSTANCES_PATH = tmp / "studio-vast.json"
sent = []


def fake_send(request, timeout):
    sent.append(request)
    return 200, b'{"instances": [{"id": 1, "label": "probe", "public_ipaddr": "203.0.113.9", ' \
                b'"ports": {"8188/tcp": [{"HostPort": 31234}]}}]}'


listed = vast.fetch_instances("probe-vast-key", sender=fake_send)
assert listed["status"] == 200 and len(listed["instances"]) == 1, listed
assert sent[0].full_url == vast.INSTANCES_URL, sent[0].full_url
assert dict(sent[0].headers)["Authorization"] == "Bearer probe-vast-key"
doc, refusal = vast.add_instance(vast.empty_doc(), "203.0.113.9:31234", label="probe")
assert refusal == "", refusal
doc, refusal = vast.add_instance(doc, "198.51.100.7:40111")
assert refusal == "", refusal
vast.save_doc(doc)
kept = vast.load_doc()["instances"]
assert [row["endpoint"] for row in kept] == ["http://203.0.113.9:31234", "http://198.51.100.7:40111"], kept
print(f"vast: listed {len(listed['instances'])} instance(s), {len(kept)} kept across a reload")

# --- image deployment layer: the tag, its env, and the commands ------------
image_deploy.SETTINGS_PATH = tmp / "studio-images.json"
doc_meta = studio_meta.load()
entry = image_deploy.entry_by_ref(image_deploy.entries(doc_meta, None), "klein")
assert entry is not None and entry["tag"].endswith("prefetch6-klein"), entry
rows = image_deploy.env_rows(entry, None, {"huggingface": "probe-hf-token"})
assert [r["name"] for r in rows] == ["HF_TOKEN", "CIVITAI_API_TOKEN", "STARTUP_CHECK_MAX_TRIES"], rows
assert rows[0]["value"] == "probe-hf-token"
settings, refusal = image_deploy.add_env(image_deploy.empty_settings(), "klein", "PROBE_FLAG", "1")
assert refusal == "", refusal
image_deploy.save_settings(settings)
kept_env = image_deploy.extra_env(image_deploy.load_settings(), "klein")
assert [r["name"] for r in kept_env] == ["PROBE_FLAG"], kept_env
script = image_deploy.deploy_script(entry, rows)
assert "docker build" in script and "vastai create" in script
assert "probe-hf-token" not in script, "the shown commands must not carry the token"
print(
    f"images: {entry['tag'].rsplit(':', 1)[-1]} {len(rows)} env entries, "
    f"{len(kept_env)} extra kept across a reload"
)

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
        for prefix in ("import:", "persistence:", "logging:", "salad:", "vast:", "images:", "ai:"):
            self.assertTrue(
                any(line.startswith(prefix) for line in lines),
                f"no result line for {prefix}\n{output}",
            )
        self.assertIn("layers: tkinter never imported", output)

    def test_the_ui_module_is_the_one_that_imports_tkinter(self) -> None:
        """The other half of the split: the window still lives in app.py."""
        source = (PKG / "app.py").read_text(encoding="utf-8")
        self.assertIn("import tkinter as tk", source)
        for module in (
            "ai_helper.py",
            "comfy_import.py",
            "generator.py",
            "image_deploy.py",
            "profiles.py",
            "prompt_history.py",
            "request_json.py",
            "salad_queue.py",
            "salad_status.py",
            "studio_log.py",
            "studio_meta.py",
            "tokens.py",
            "vast.py",
        ):
            text = (PKG / module).read_text(encoding="utf-8")
            self.assertNotIn(
                "import tkinter",
                text,
                f"{module} must stay importable without the UI layer",
            )


if __name__ == "__main__":
    unittest.main()
