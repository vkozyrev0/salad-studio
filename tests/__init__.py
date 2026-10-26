"""The suite. The first import of ``tests`` binds the store names before any test module loads."""
import sys as _sys
from pathlib import Path as _Path

_ROOT = _Path(__file__).resolve().parent.parent
for _p in (_ROOT, _ROOT / "salad_studio"):
    if str(_p) not in _sys.path:
        _sys.path.insert(0, str(_p))

# Each store, once. The import system would otherwise load a test module's
# ``import profiles`` and a controller's ``salad_studio.profiles`` as two
# modules with two path constants, so a test that repoints one leaves the other
# on the person's real file.
for _name in ("atomic", "generator", "graph_model", "hostings", "image_deploy",
              "lora_store", "profiles", "prompt_catalog", "prompt_history",
              "ref_check", "request_json", "salad_queue", "salad_status",
              "studio_log", "studio_meta", "tokens", "vast"):
    _module = _sys.modules.get(_name)
    if _module is None:
        __import__(f"salad_studio.{_name}")
        _module = _sys.modules[f"salad_studio.{_name}"]
    _sys.modules[_name] = _module
    _sys.modules[f"salad_studio.{_name}"] = _module
    setattr(_sys.modules["salad_studio"], _name, _module)
