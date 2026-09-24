"""Salad Studio LoRA library: known catalog rows plus user extras.

User extras live in ``~/.config/salad/studio-loras.json`` (override with a
path argument in tests — never write the real file from tests).
"""
from __future__ import annotations

import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, unquote, urlparse, urlunparse

_TOOLS = Path(__file__).resolve().parent.parent
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

import model_catalog as mc  # noqa: E402

EXTRAS_PATH = Path.home() / ".config" / "salad" / "studio-loras.json"
DEFAULT_KLEIN_LORA_IDS = (
    "civitai:2334190@2625692",
    "civitai:545264@2763568",
)
# Studio graph → catalog ``base`` string. Empty/unknown family matches neither.
GRAPH_BASE = {
    "klein": "Flux.2 Klein 9B",
    "flux1": "Flux.1 D",
}
FAMILY_LABELS = {
    "Flux.2 Klein 9B": "Flux.2 Klein",
    "Flux.1 D": "Flux.1 Dev",
}
# UI graph control: same strings Config LoRA checkboxes show. Wire ids stay klein/flux1.
GRAPH_LABELS = {
    "klein": "Flux.2 Klein",
    "flux1": "Flux.1 Dev",
}
GRAPH_CHOICES = tuple(GRAPH_LABELS[g] for g in ("klein", "flux1"))
FAMILY_CHOICES = (
    "Flux.2 Klein",
    "Flux.1 Dev",
    "Pony",
    "SDXL",
    "Krea 2",
    "Illustrious",
    "unknown",
)
_FAMILY_ALIASES = {
    "": "",
    "unknown": "",
    "(unknown)": "",
    "flux.2 klein 9b": "Flux.2 Klein 9B",
    "flux.2 klein": "Flux.2 Klein 9B",
    "flux2 klein": "Flux.2 Klein 9B",
    "klein": "Flux.2 Klein 9B",
    "flux.1 d": "Flux.1 D",
    "flux.1 dev": "Flux.1 D",
    "flux1": "Flux.1 D",
    "flux.1": "Flux.1 D",
    "pony": "Pony",
    "sdxl": "SDXL",
    "krea 2": "Krea 2",
    "krea": "Krea 2",
    "illustrious": "Illustrious",
}
_STRENGTH = {
    "civitai:545264@2763568": (0.8, 0.8),
    "civitai:637213@2760271": (0.2, 0.2),
    "civitai:1449678@2795018": (0.5, 0.5),
}
_HF_FILE = re.compile(r"/([^/?#]+\.safetensors)(?:\?|#|$)", re.I)
_DL_VER = re.compile(r"civitai\.com/api/download/models/(\d+)", re.I)


def _resolve_extras(path: Path | None) -> Path:
    return path if path is not None else EXTRAS_PATH


def _load_extras(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    raw = path.read_text(encoding="utf-8")
    if not raw.strip():
        return []
    data = json.loads(raw)
    if isinstance(data, dict):
        items = data.get("items") or []
    elif isinstance(data, list):
        items = data
    else:
        items = []
    return [it for it in items if isinstance(it, dict) and it.get("id")]


def _save_extras(path: Path, items: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"items": items}
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def replica_weight_names() -> set[str]:
    """Filenames Salad Klein prefetch already has (unet / CLIP / VAE)."""
    names: set[str] = set()
    for it in mc.KNOWN:
        if str(it.get("status") or "") != "on-klein-group":
            continue
        fn = str((it.get("source") or {}).get("filename") or "")
        if fn:
            names.add(fn)
            names.add(Path(fn).name)
    return names


def _is_replica_item(item: dict[str, Any]) -> bool:
    if str(item.get("status") or "") == "on-klein-group":
        return True
    fn = str((item.get("source") or {}).get("filename") or "")
    return bool(fn and Path(fn).name in replica_weight_names())


def _known_loras() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in mc.KNOWN:
        if item.get("kind") != "lora":
            continue
        out.append(dict(item))
    return out


def _version_id_of(item: dict[str, Any]) -> int:
    src = item.get("source") or {}
    vid = _id_num(src.get("version_id"))
    if vid:
        return vid
    vid = _id_num(civitai_version_from_url(str(src.get("download") or "")))
    if vid:
        return vid
    parsed = _CIVITAI_ID.match(str(item.get("id") or ""))
    if parsed:
        return int(parsed.group(2))
    return 0


def _lora_dup_keys(item: dict[str, Any]) -> list[str]:
    """Identity keys used to collapse the same LoRA stored under different ids."""
    keys: list[str] = []
    vid = _version_id_of(item)
    if vid:
        keys.append(f"ver:{vid}")
    fn = _stem_key(str((item.get("source") or {}).get("filename") or ""))
    if fn:
        keys.append(f"fn:{fn}")
    name = _stem_key(str(item.get("name") or ""))
    fam = family_of(item)
    if name:
        keys.append(f"name:{name}|{fam}")
    lid = str(item.get("id") or "")
    if lid:
        keys.append(f"id:{lid}")
    return keys


def _prefer_lora(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    query = str(a.get("name") or b.get("name") or "")
    a_hit = civitai_hit_from_item(a) or {}
    b_hit = civitai_hit_from_item(b) or {}
    a_ok = is_tag_or_suffix(query, a_hit) if query else False
    b_ok = is_tag_or_suffix(query, b_hit) if query else False
    if a_ok != b_ok:
        return a if a_ok else b
    if bool(a.get("verified")) != bool(b.get("verified")):
        return a if a.get("verified") else b
    va, vb = _version_id_of(a), _version_id_of(b)
    if va != vb:
        # Same display name, both match the tag: newer suffix (Klein V3) wins.
        # Exact-filename already won above for Goddess v2 vs mid-name v3.
        if a_ok and b_ok:
            return b if vb > va else a
        return a if va > vb else b
    a_user = str(a.get("status") or "") == "user"
    b_user = str(b.get("status") or "") == "user"
    if a_user != b_user:
        return a if a_user else b
    return b


def _collapse_loras(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One row per Civitai version / filename / visible name."""
    order: list[str] = []
    chosen: dict[str, dict[str, Any]] = {}
    index: dict[str, str] = {}

    def _primary(item: dict[str, Any]) -> str:
        lid = str(item.get("id") or "")
        return lid or f"row:{id(item)}"

    for item in rows:
        row = dict(item)
        pid = _primary(row)
        keys = _lora_dup_keys(row)
        existing_pid = next((index[k] for k in keys if k in index), "")
        if existing_pid and existing_pid in chosen:
            winner = _prefer_lora(chosen[existing_pid], row)
            win_id = _primary(winner)
            if win_id != existing_pid:
                order = [win_id if x == existing_pid else x for x in order]
                chosen.pop(existing_pid, None)
            chosen[win_id] = winner
            for k in _lora_dup_keys(winner):
                index[k] = win_id
            continue
        chosen[pid] = row
        order.append(pid)
        for k in keys:
            index[k] = pid
    return [chosen[pid] for pid in order if pid in chosen]


def list_loras(extras_path: Path | None = None) -> list[dict[str, Any]]:
    """KNOWN LoRAs first, then extras (extras replace the same id)."""
    by_id: dict[str, dict[str, Any]] = {}
    for item in _known_loras():
        row = dict(item)
        row.setdefault("verified", _is_replica_item(row))
        by_id[str(item["id"])] = row
    for item in _load_extras(_resolve_extras(extras_path)):
        row = dict(item)
        row.setdefault("verified", False)
        by_id[str(item["id"])] = row
    return _collapse_loras(list(by_id.values()))


def find_lora(lora_id: str, extras_path: Path | None = None) -> dict[str, Any] | None:
    for item in list_loras(extras_path):
        if item.get("id") == lora_id:
            return item
    return None


def _url_without_token(url: str) -> str:
    parts = urlparse(url)
    q = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k != "token"]
    return urlunparse(parts._replace(query="&".join(f"{k}={v}" for k, v in q) if q else ""))


def strip_civitai_token(url: str) -> str:
    return _url_without_token(url)


def civitai_version_from_url(url: str) -> str:
    m = re.search(r"/download/models/(\d+)", url)
    return m.group(1) if m else ""


def find_by_loader_name(
    name: str, extras_path: Path | None = None
) -> dict[str, Any] | None:
    """Match a LoraLoader ``lora_name`` (filename or Civitai URL) to a catalog/extra row."""
    raw = (name or "").strip()
    if not raw:
        return None
    clean = _url_without_token(raw)
    ver = civitai_version_from_url(clean)
    fname = Path(urlparse(clean).path).name
    q = raw.lower().removesuffix(".safetensors")
    matches: list[dict[str, Any]] = []
    for item in list_loras(extras_path):
        src = item.get("source") or {}
        dl = str(src.get("download") or "")
        stem = Path(str(src.get("filename") or "")).stem.lower()
        item_id = str(item.get("id") or "")
        if (
            comfy_lora_name(item) in (raw, clean)
            or (dl and _url_without_token(dl) == clean)
            or (fname and str(src.get("filename") or "") == fname)
            or (stem and stem == q)
            or (ver and str(src.get("version_id") or "") == ver)
            or (ver and item_id.endswith(f"@{ver}"))
        ):
            matches.append(item)
    if not matches:
        return None
    best = matches[0]
    best_hit = civitai_hit_from_item(best)
    for item in matches[1:]:
        hit = civitai_hit_from_item(item)
        if prefer_civitai_hit(raw, best_hit, hit) is hit:
            best = item
            best_hit = hit
    return best


def _norm_lora_query(raw: str) -> str:
    return re.sub(r"[_\-]+", " ", (raw or "").strip().lower()).removesuffix(".safetensors")


def score_civitai_hit(query: str, model_name: str, filenames: list[str]) -> int:
    """0–100. Exact filename stem wins. Short titles must not match long tags
    (``Cass`` must not beat ``cass_aruhshuraanima_preview3_1-step00004500``)."""
    q = _norm_lora_query(query)
    q_raw = (query or "").strip().lower().removesuffix(".safetensors")
    if not q and not q_raw:
        return 0
    q_tokens = [t for t in re.split(r"[\s_\-]+", q_raw) if len(t) > 2]
    for fn in filenames:
        stem = Path(str(fn)).stem.lower()
        stem_n = _norm_lora_query(stem)
        if stem == q_raw or stem_n == q:
            return 100
        if q_raw and q_raw in stem:
            return 90
        if q_tokens and all(t in stem for t in q_tokens):
            return 95
    title = _norm_lora_query(model_name)
    if title == q:
        return 85
    if q and len(q) >= 8 and q in title:
        return 70
    # Title as a substring of the tag only if the title is distinctive.
    if title and len(title) >= 12 and title in q:
        return 65
    return 0


def _query_variants(raw: str) -> list[str]:
    """Civitai's search often misses the exact ``<lora:file>`` token; try aliases."""
    q = (raw or "").strip()
    if not q:
        return []
    fname = Path(q.replace("\\", "/")).name
    stem = Path(fname).stem
    out: list[str] = []
    for v in (
        q,
        fname,
        stem,
        q.replace("_", " "),
        q.replace("-", " "),
        re.sub(r"[_\-]+", " ", q),
        re.sub(r"[_\-]+", " ", stem),
    ):
        v = v.strip()
        if v and v not in out:
            out.append(v)
    parts = [p for p in re.split(r"[_\-]+", q) if p]
    if len(parts) >= 2:
        tail = "-".join(parts[-2:])
        if tail not in out:
            out.append(tail)
    # Drop trainer step suffixes so Civitai search finds the model page.
    stripped = re.sub(r"(?i)[_\-]?\d*[-_]?step\d+$", "", q).strip(" _-")
    if stripped and stripped not in out:
        out.append(stripped)
    if len(parts) >= 3:
        head = "_".join(parts[:3])
        if head not in out:
            out.append(head)
    camel = re.sub(r"([a-z])([A-Z])", r"\1 \2", stem)
    camel = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", camel)
    camel = re.sub(r"[_\-]+", " ", camel).strip()
    if camel and camel not in out:
        out.append(camel)
    words = [w for w in camel.split() if w]
    if len(words) >= 2:
        pair = " ".join(words[:2])
        if pair not in out:
            out.append(pair)
    # CreativeEdge dumps: Geometric01_CE_FLUX2_Klein9b_AIT5k → Geometric / Geometric CE
    ce = re.split(r"(?i)_CE_", stem, maxsplit=1)
    if len(ce) == 2 and ce[0]:
        head = ce[0]
        bare = re.sub(r"(?i)\d+[a-z]?$", "", head).strip("_-")
        camel_bare = re.sub(r"([a-z])([A-Z])", r"\1 \2", bare)
        camel_bare = re.sub(r"([A-Za-z])(\d)", r"\1 \2", camel_bare).strip()
        words = [w for w in camel_bare.split() if w and not w.isdigit()]
        phrase = " ".join(words)
        for v in (
            head,
            f"{head} CE",
            bare,
            f"{bare} CE",
            camel_bare,
            phrase,
            f"{phrase} CE" if phrase else "",
        ):
            v = v.strip()
            if v and len(v) >= 3 and v not in out:
                out.append(v)
    return out[:18]


def _filename_for_query(query: str, fnames: list[str]) -> str:
    best_fn = ""
    best_sc = -1
    for fn in fnames:
        sc = score_civitai_hit(query, "", [fn])
        if sc > best_sc:
            best_sc = sc
            best_fn = fn
    return best_fn or (fnames[0] if fnames else f"{query}.safetensors")


_CIVITAI_ID = re.compile(r"(?i)^civitai:(\d+)@(\d+)$")


def _id_num(val: Any) -> int:
    try:
        return int(val)
    except (TypeError, ValueError):
        return 0


def _hit_ids(hit: dict[str, Any]) -> tuple[int, int]:
    return _id_num(hit.get("model_id")), _id_num(hit.get("version_id"))


def _hit_score(query: str, hit: dict[str, Any]) -> int:
    fn = str(hit.get("filename") or "")
    return score_civitai_hit(query, str(hit.get("name") or ""), [fn] if fn else [])


def _stem_key(name: str) -> str:
    return _norm_lora_query(Path(str(name or "")).name)


def _is_prefix_stem(prefix: str, full: str) -> bool:
    if not prefix or not full or full == prefix or not full.startswith(prefix):
        return False
    rest = full[len(prefix) :]
    return rest[:1] in ("", " ")


def is_tag_or_suffix(query: str, hit: dict[str, Any] | None) -> bool:
    """Exact prompt-tag filename, or that tag as a prefix plus a version suffix.

    ``Flux.2 Klein 9B Anime V3 Refined`` is a suffix of ``Flux.2 Klein 9B anime``.
    ``Ah! My Goddess_v3_illustriousXL`` is not (``v3`` sits in the middle).
    """
    if not hit:
        return False
    q = _stem_key(query)
    fn = _stem_key(str(hit.get("filename") or ""))
    if not q or not fn:
        return False
    return fn == q or _is_prefix_stem(q, fn)


def _is_filename_successor(query: str, a: dict[str, Any], b: dict[str, Any]) -> bool:
    """True when one file is the tag and the other is the tag plus a version suffix."""
    return is_tag_or_suffix(query, a) and is_tag_or_suffix(query, b)


def civitai_hit_from_item(item: dict[str, Any] | None) -> dict[str, Any] | None:
    """Normalize a catalog/extras row to the Civitai search-hit shape."""
    if not item:
        return None
    src = item.get("source") or {}
    mid, vid = _id_num(src.get("model_id")), _id_num(src.get("version_id"))
    parsed = _CIVITAI_ID.match(str(item.get("id") or ""))
    if parsed:
        if not mid:
            mid = int(parsed.group(1))
        if not vid:
            vid = int(parsed.group(2))
    if not vid:
        vid = _id_num(civitai_version_from_url(str(src.get("download") or "")))
    return {
        "page": str(src.get("page") or ""),
        "download": str(src.get("download") or ""),
        "filename": str(src.get("filename") or ""),
        "name": str(item.get("name") or ""),
        "model_id": mid or None,
        "version_id": vid or None,
        "version_name": str(src.get("version_name") or ""),
    }


def prefer_civitai_hit(
    query: str,
    a: dict[str, Any] | None,
    b: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Prefer a later same-model version whose filename is the tag plus a suffix.

    Exact filename still wins across different models (Cass vs Aruhshura). On the
    same model — or when V3's filename is ``<tag> V3 Refined`` vs V1 ``<tag>`` —
    the higher Civitai version id wins among strong filename matches.
    """
    if not a:
        return b
    if not b:
        return a
    sa, sb = _hit_score(query, a), _hit_score(query, b)
    ma, va = _hit_ids(a)
    mb, vb = _hit_ids(b)
    same = bool(ma and mb and ma == mb) or _is_filename_successor(query, a, b)
    if same:
        a_ok, b_ok = is_tag_or_suffix(query, a), is_tag_or_suffix(query, b)
        if a_ok and b_ok:
            if vb != va:
                return b if vb > va else a
            return b if sb > sa else a
        if b_ok and not a_ok:
            return b
        if a_ok and not b_ok:
            return a
    if sb > sa:
        return b
    return a


def looks_unversioned_filename(query: str, item: dict[str, Any] | None) -> bool:
    """True when extras filename is exactly the prompt tag (a V3 suffix may exist)."""
    if not item:
        return False
    fname = str((item.get("source") or {}).get("filename") or "")
    q = _stem_key(query)
    return bool(q and _stem_key(fname) == q)


def best_civitai_hit(query: str, items: list[Any]) -> dict[str, Any] | None:
    """Pick the version whose file name matches the prompt tag.

    Across models, exact filename wins. On one model, a later version whose
    filename is the tag plus a suffix (Klein-anime V3 vs V1) beats an older
    exact-filename dump. A newer file that dropped the matching name does not.
    """
    raw = (query or "").strip()
    best: dict[str, Any] | None = None
    for it in items or []:
        if not isinstance(it, dict):
            continue
        model_id = it.get("id")
        title = str(it.get("name") or "")
        strong: list[tuple[int, dict[str, Any]]] = []
        weak: dict[str, Any] | None = None
        weak_sc = -1
        for ver in it.get("modelVersions") or []:
            if not isinstance(ver, dict):
                continue
            files = ver.get("files") or []
            fnames = [str(f.get("name") or "") for f in files if isinstance(f, dict)]
            if not fnames:
                continue
            score = score_civitai_hit(raw, title, fnames)
            if score < 60:
                continue
            ver_id = ver.get("id")
            fname = _filename_for_query(raw, fnames)
            dl = ""
            for f in files:
                if str(f.get("name") or "") != fname:
                    continue
                cand = str(f.get("downloadUrl") or "")
                if cand.startswith("http"):
                    dl = cand
                    break
            if not dl and ver_id:
                dl = f"https://civitai.com/api/download/models/{ver_id}"
            hit = {
                "page": f"https://civitai.com/models/{model_id}?modelVersionId={ver_id}",
                "download": dl,
                "filename": fname,
                "name": title or raw,
                "model_id": model_id,
                "version_id": ver_id,
                "version_name": str(ver.get("name") or ""),
                "verified": True,
            }
            if is_tag_or_suffix(raw, hit):
                strong.append((_id_num(ver_id), hit))
            elif score > weak_sc:
                weak_sc = score
                weak = hit
        if strong:
            pick = max(strong, key=lambda t: t[0])[1]
        else:
            pick = weak
        if pick:
            best = prefer_civitai_hit(raw, best, pick)
    return best


def _civitai_model_search(query: str, timeout: int) -> list[Any]:
    params = urllib.parse.urlencode({"limit": 20, "types": "LORA", "query": query})
    url = f"https://civitai.com/api/v1/models?{params}"
    req = urllib.request.Request(
        url, headers={"User-Agent": mc.UA, "accept": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError, ValueError):
        return []
    items = data.get("items") if isinstance(data, dict) else None
    return items if isinstance(items, list) else []


def fetch_civitai_model(model_id: int, timeout: int = 20) -> dict[str, Any] | None:
    """GET ``/api/v1/models/{id}`` with every version (search often omits Klein files)."""
    try:
        mid = int(model_id)
    except (TypeError, ValueError):
        return None
    if mid <= 0:
        return None
    try:
        data = _civitai_json(
            f"https://civitai.com/api/v1/models/{mid}", timeout=timeout
        )
    except (
        urllib.error.URLError,
        TimeoutError,
        json.JSONDecodeError,
        OSError,
        ValueError,
    ):
        return None
    return data if isinstance(data, dict) else None


def _model_file_stems(item: dict[str, Any]) -> list[str]:
    stems: list[str] = []
    for ver in item.get("modelVersions") or []:
        if not isinstance(ver, dict):
            continue
        for f in ver.get("files") or []:
            if isinstance(f, dict) and f.get("name"):
                stems.append(Path(str(f["name"])).stem.lower())
    return stems


def _ce_head(stem: str) -> str:
    parts = re.split(r"(?i)_ce_", Path(str(stem).replace("\\", "/")).stem, maxsplit=1)
    return parts[0].lower() if len(parts) == 2 else ""


def _hydrate_model_versions(query: str, item: dict[str, Any]) -> dict[str, Any]:
    """Search lists the latest dump (ZIMG); the Klein file is another version."""
    qstem = Path(str(query).replace("\\", "/")).stem.lower().removesuffix(".safetensors")
    stems = _model_file_stems(item)
    if any(s == qstem for s in stems):
        return item
    head = _ce_head(qstem)
    if not head or not any(_ce_head(s) == head for s in stems):
        return item
    full = fetch_civitai_model(int(item.get("id") or 0))
    return full if isinstance(full, dict) and full.get("modelVersions") else item


def civitai_search_lora(query: str, timeout: int = 20) -> dict[str, Any] | None:
    """Look up a prompt ``<lora:Name:w>`` tag on Civitai. No extras write."""
    raw = (query or "").strip()
    if not raw:
        return None
    best: dict[str, Any] | None = None
    for q in _query_variants(raw):
        items = [
            _hydrate_model_versions(raw, it)
            for it in _civitai_model_search(q, timeout)
            if isinstance(it, dict)
        ]
        hit = best_civitai_hit(raw, items)
        if not hit:
            continue
        best = prefer_civitai_hit(raw, best, hit)
        if is_tag_or_suffix(raw, best):
            return best
    return best


def normalize_family(base: str | None) -> str:
    """Canonical catalog ``base`` string, or empty if unknown/unset."""
    raw = str(base or "").strip()
    if not raw:
        return ""
    aliased = _FAMILY_ALIASES.get(raw.lower())
    if aliased is not None:
        return aliased
    low = raw.lower()
    if "klein" in low:
        return "Flux.2 Klein 9B"
    if "flux.1" in low or low.startswith("flux1"):
        return "Flux.1 D"
    return raw


def family_of(item: dict[str, Any]) -> str:
    return normalize_family(item.get("base"))


def family_label(item: dict[str, Any] | str | None) -> str:
    """Visible compatible-model text (Flux.1 Dev / Flux.2 Klein / catalog family)."""
    if isinstance(item, dict):
        fam = family_of(item)
    else:
        fam = normalize_family(item)
    if not fam:
        return "unknown"
    return FAMILY_LABELS.get(fam, fam)


def graph_label(graph: str | None) -> str:
    """Family name shown on the Config graph control (matches checkbox tags)."""
    return GRAPH_LABELS.get(graph_id(graph), GRAPH_LABELS["klein"])


def graph_id(graph: str | None) -> str:
    """Map a UI family label or a stored id to ``klein`` / ``flux1``."""
    raw = str(graph or "").strip()
    if not raw:
        return "klein"
    if raw in GRAPH_BASE:
        return raw
    for gid, lab in GRAPH_LABELS.items():
        if raw == lab or raw.lower() == lab.lower():
            return gid
    fam = normalize_family(raw)
    for gid, base in GRAPH_BASE.items():
        if fam == base:
            return gid
    return "klein"


def compatible_with_graph(item: dict[str, Any], graph: str) -> bool:
    """True only when the LoRA's family matches the studio graph."""
    want = GRAPH_BASE.get(graph_id(graph))
    fam = family_of(item)
    if not want or not fam:
        return False
    return fam == want


def ensure_civitai_version_name(
    item: dict[str, Any],
    *,
    extras_path: Path | None = None,
    live: bool = True,
) -> dict[str, Any]:
    """Fill ``source.version_name`` from Civitai when we have a version id but no title."""
    item = dict(item)
    src = dict(item.get("source") or {})
    item["source"] = src
    if str(src.get("version_name") or "").strip():
        return item
    vid = _id_num(src.get("version_id")) or _id_num(
        civitai_version_from_url(str(src.get("download") or ""))
    )
    if not vid or not live:
        return item
    data = fetch_civitai_version(vid)
    if not isinstance(data, dict):
        return item
    name = str(data.get("name") or "").strip()
    if not name:
        return item
    src["version_name"] = name
    src["version_id"] = vid
    item["source"] = src
    write_extra(item, extras_path)
    return item


def version_label(item: dict[str, Any] | None) -> str:
    """Civitai version title (``v3.0``, ``Anime V3 Refined``) when known."""
    if not item:
        return ""
    src = item.get("source") or {}
    return str(src.get("version_name") or item.get("version_name") or "").strip()


_V_NUM = re.compile(r"(?i)(?:^|[\s_\-.(])v(?:ersion)?[\s._-]*(\d+(?:\.\d+)?)")
_P_NUM = re.compile(r"(?i)(?:^|[\s_\-.(])(?:preview|p)[\s._-]*(\d+)\b")


def variation_label(
    item: dict[str, Any] | None = None,
    *,
    version_name: str = "",
    filename: str = "",
) -> str:
    """Short variation token for JSON ``_meta.variation``: ``V1``, ``V3``, ``v2.0``, ``P3``."""
    if item:
        src = item.get("source") or {}
        version_name = version_name or version_label(item)
        filename = filename or str(src.get("filename") or "")
    for text in (version_name, filename):
        blob = str(text or "").strip()
        if not blob:
            continue
        m = _V_NUM.search(" " + blob)
        if m:
            n = m.group(1)
            return f"v{n}" if "." in n else f"V{n}"
        m = _P_NUM.search(" " + blob)
        if m:
            return f"P{m.group(1)}"
    return ""


def config_label(item: dict[str, Any]) -> str:
    name = str(item.get("name") or item.get("id") or "lora")
    fam = family_label(item)
    ver = version_label(item)
    if ver:
        return f"{name}  [{fam}]  {ver}"
    return f"{name}  [{fam}]"


def strengths_for(item: dict[str, Any]) -> tuple[float, float]:
    src = item.get("source") or {}
    if "strength_model" in item or "strength_clip" in item:
        return (
            float(item.get("strength_model", 1)),
            float(item.get("strength_clip", item.get("strength_model", 1))),
        )
    if "strength_model" in src:
        return (
            float(src.get("strength_model", 1)),
            float(src.get("strength_clip", src.get("strength_model", 1))),
        )
    pair = _STRENGTH.get(str(item.get("id")))
    if pair:
        return pair
    blob = str(src.get("download") or item.get("id") or "")
    if "2795018" in blob or "1449678" in blob:
        return (0.5, 0.5)
    return (1.0, 1.0)


def comfy_lora_name(item: dict[str, Any]) -> str:
    """Name Salad LoraLoader should load: replica filename, else a *verified* URL."""
    src = item.get("source") or {}
    filename = str(src.get("filename") or "")
    download = str(src.get("download") or "")
    if _is_replica_item(item) and filename:
        return filename
    http = download.startswith("http://") or download.startswith("https://")
    if http and item.get("verified") is True:
        return download
    if http and _is_known_id(item.get("id")):
        return download
    if filename:
        return filename
    return str(item.get("id") or "")


def _is_known_id(lora_id: Any) -> bool:
    lid = str(lora_id or "")
    return any(str(it.get("id") or "") == lid for it in mc.KNOWN)


def spec_for(item: dict[str, Any]) -> dict[str, Any]:
    sm, sc = strengths_for(item)
    src = item.get("source") or {}
    return {
        "id": item.get("id"),
        "lora_name": comfy_lora_name(item),
        "filename": str(src.get("filename") or ""),
        "tag": str(item.get("name") or ""),
        "version_name": version_label(item),
        "variation": variation_label(item),
        "verified": bool(item.get("verified")),
        "strength_model": sm,
        "strength_clip": sc,
        "base": str(item.get("base") or ""),
    }


def specs_for_ids(
    ids: list[str] | tuple[str, ...],
    extras_path: Path | None = None,
    graph: str | None = None,
) -> list[dict[str, Any]]:
    """Resolve selected ids to LoraLoader specs; drop families that do not match ``graph``."""
    out: list[dict[str, Any]] = []
    for lora_id in ids:
        item = find_lora(str(lora_id), extras_path)
        if item is None:
            continue
        if graph is not None and not compatible_with_graph(item, graph):
            continue
        out.append(spec_for(item))
    return out


def _filename_from_url(url: str) -> str:
    m = _HF_FILE.search(url)
    if m:
        return unquote(m.group(1))
    path = urlparse(url).path
    name = Path(unquote(path)).name
    if name.endswith(".safetensors"):
        return name
    return name or "lora.safetensors"


def fetch_civitai_version(
    version_id: int, timeout: int = 15
) -> dict[str, Any] | None:
    """GET Civitai ``/api/v1/model-versions/{id}``. None if missing/invalid."""
    vid = _id_num(version_id)
    if not vid:
        return None
    url = f"https://civitai.com/api/v1/model-versions/{vid}"
    req = urllib.request.Request(
        url, headers={"User-Agent": mc.UA, "accept": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (
        urllib.error.URLError,
        TimeoutError,
        json.JSONDecodeError,
        OSError,
        ValueError,
    ):
        return None
    if not isinstance(data, dict) or _id_num(data.get("id")) != vid:
        return None
    files = data.get("files") or []
    if not isinstance(files, list) or not files:
        return None
    return data


_IMAGE_ID = re.compile(r"(?i)civitai\.com/images/(\d+)")


def civitai_image_id(text: str) -> str | None:
    m = _IMAGE_ID.search(text or "")
    return m.group(1) if m else None


def _civitai_headers(*, accept: str = "application/json") -> dict[str, str]:
    headers = {"User-Agent": mc.UA, "accept": accept}
    try:
        from tokens import read_token

        tok = str(read_token("civitai") or "").strip()
    except Exception:
        tok = ""
    if tok:
        headers["Authorization"] = f"Bearer {tok}"
    return headers


def _civitai_json(url: str, timeout: int = 20) -> Any:
    req = urllib.request.Request(url, headers=_civitai_headers())
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _image_has_resources(item: dict[str, Any]) -> bool:
    ids = item.get("modelVersionIds")
    if isinstance(ids, list) and ids:
        return True
    gen = unwrap_image_generation(item)
    rows = gen.get("resources")
    return isinstance(rows, list) and any(isinstance(r, dict) for r in rows)


def _as_resource_row(raw: dict[str, Any]) -> dict[str, Any] | None:
    mtype = str(raw.get("modelType") or raw.get("type") or "").strip()
    low = mtype.lower()
    name = str(raw.get("modelName") or raw.get("name") or "").strip()
    vid = raw.get("modelVersionId") or raw.get("versionId")
    try:
        vid_i = int(vid) if vid is not None else None
    except (TypeError, ValueError):
        vid_i = None
    if not name and not vid_i:
        return None
    if "lora" in low:
        kind = "lora"
    elif "checkpoint" in low:
        kind = "checkpoint"
    else:
        kind = low or "unknown"
    weight = raw.get("strength")
    if weight is None:
        weight = raw.get("weight")
    try:
        weight_f = float(weight) if weight is not None else None
    except (TypeError, ValueError):
        weight_f = None
    row: dict[str, Any] = {"name": name, "type": kind}
    if vid_i is not None:
        row["modelVersionId"] = vid_i
    if weight_f is not None:
        row["weight"] = weight_f
    vn = str(raw.get("versionName") or raw.get("version_name") or "").strip()
    if vn:
        row["versionName"] = vn
    base = str(raw.get("baseModel") or raw.get("base") or "").strip()
    if base:
        row["baseModel"] = base
    return row


def merge_image_resources(
    item: dict[str, Any], resources: list[Any]
) -> dict[str, Any]:
    """Copy Resources-used onto a v1 images item (Draw Things leaves ids empty)."""
    rows: list[dict[str, Any]] = []
    for raw in resources:
        if isinstance(raw, dict):
            row = _as_resource_row(raw)
            if row:
                rows.append(row)
    if not rows:
        return item
    ids: list[int] = []
    for row in rows:
        vid = row.get("modelVersionId")
        if isinstance(vid, int) and vid not in ids:
            ids.append(vid)
    if ids and not (isinstance(item.get("modelVersionIds"), list) and item["modelVersionIds"]):
        item["modelVersionIds"] = ids
    meta = item.get("meta") if isinstance(item.get("meta"), dict) else {}
    inner = meta.get("meta") if isinstance(meta.get("meta"), dict) else {}
    if not isinstance(inner, dict):
        inner = {}
    if not inner.get("resources"):
        inner["resources"] = rows
    if not inner.get("Model"):
        for row in rows:
            if row.get("type") == "checkpoint" and row.get("name"):
                inner["Model"] = row["name"]
                break
    if inner.get("width") in (None, "") and item.get("width"):
        inner["width"] = item["width"]
    if inner.get("height") in (None, "") and item.get("height"):
        inner["height"] = item["height"]
    meta["meta"] = inner
    item["meta"] = meta
    return item


def fetch_civitai_generation_data(
    image_id: str, timeout: int = 20
) -> list[dict[str, Any]] | None:
    """tRPC ``image.getGenerationData`` — Resources-used for External Generator posts."""
    iid = str(image_id or "").strip()
    if not iid.isdigit():
        return None
    payload = json.dumps({"json": {"id": int(iid)}}, separators=(",", ":"))
    url = (
        "https://civitai.com/api/trpc/image.getGenerationData?input="
        + urllib.parse.quote(payload, safe="")
    )
    try:
        data = _civitai_json(url, timeout=timeout)
    except (
        urllib.error.URLError,
        TimeoutError,
        json.JSONDecodeError,
        OSError,
        ValueError,
    ):
        return None
    node = data
    for key in ("result", "data", "json"):
        if isinstance(node, dict) and key in node:
            node = node[key]
    if not isinstance(node, dict):
        return None
    rows = node.get("resources")
    resources = [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []
    tools = [t for t in (node.get("tools") or []) if isinstance(t, dict)]
    if not resources and not tools:
        return None
    return {
        "resources": resources,
        "tools": tools,
        "onSite": node.get("onSite"),
        "process": node.get("process"),
    }


_PAGE_VERSION = re.compile(
    r"/models/(\d+)/[^\"'?\s#]*\?modelVersionId=(\d+)", re.I
)


def fetch_civitai_page_resources(
    image_id: str, timeout: int = 20
) -> list[dict[str, Any]] | None:
    """Public image HTML Resources-used when tRPC is unauthorized."""
    iid = str(image_id or "").strip()
    if not iid.isdigit():
        return None
    url = f"https://civitai.com/images/{iid}"
    req = urllib.request.Request(
        url, headers=_civitai_headers(accept="text/html")
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            html = resp.read().decode("utf-8", errors="replace")
    except (
        urllib.error.URLError,
        TimeoutError,
        OSError,
        ValueError,
    ):
        return None
    found: list[dict[str, Any]] = []
    seen: set[int] = set()
    for match in _PAGE_VERSION.finditer(html):
        mid, vid = int(match.group(1)), int(match.group(2))
        if vid in seen:
            continue
        seen.add(vid)
        data = fetch_civitai_version(vid)
        model = (data or {}).get("model") if isinstance(data, dict) else {}
        if not isinstance(model, dict):
            model = {}
        found.append(
            {
                "modelId": mid,
                "modelVersionId": vid,
                "modelName": str(model.get("name") or ""),
                "modelType": str(model.get("type") or ""),
                "versionName": str((data or {}).get("name") or ""),
            }
        )
    return found or None


def fetch_civitai_image(image_id: str, timeout: int = 20) -> dict[str, Any] | None:
    """GET ``/api/v1/images?imageId=&withMeta=true``. Nested ``meta.meta`` holds gen data.

    Draw Things / External Generator posts often have empty ``modelVersionIds``.
    Fill Resources-used from tRPC generation data, then the public image page.
    """
    iid = str(image_id or "").strip()
    if not iid.isdigit():
        return None
    url = f"https://civitai.com/api/v1/images?imageId={iid}&withMeta=true"
    try:
        data = _civitai_json(url, timeout=timeout)
    except (
        urllib.error.URLError,
        TimeoutError,
        json.JSONDecodeError,
        OSError,
        ValueError,
    ):
        return None
    items = data.get("items") if isinstance(data, dict) else None
    if not isinstance(items, list) or not items or not isinstance(items[0], dict):
        return None
    item = items[0]
    extra: Any = None
    if not _image_has_resources(item):
        extra = fetch_civitai_generation_data(iid, timeout=timeout)
        if not extra:
            extra = fetch_civitai_page_resources(iid, timeout=timeout)
    merge_generation_payload(item, extra)
    return item


def merge_generation_payload(item: dict[str, Any], extra: Any) -> dict[str, Any]:
    """Apply tRPC/page Resources-used and Tools (Draw Things vs Comfy)."""
    if extra is None:
        return item
    if isinstance(extra, list):
        extra = {"resources": extra}
    if not isinstance(extra, dict):
        return item
    rows = extra.get("resources")
    if isinstance(rows, list) and rows:
        merge_image_resources(item, rows)
    tools = extra.get("tools")
    names: list[str] = []
    if isinstance(tools, list):
        for row in tools:
            if isinstance(row, dict) and row.get("name"):
                names.append(str(row["name"]).strip())
            elif isinstance(row, str) and row.strip():
                names.append(row.strip())
    if names:
        meta = item.get("meta") if isinstance(item.get("meta"), dict) else {}
        inner = meta.get("meta") if isinstance(meta.get("meta"), dict) else {}
        if not isinstance(inner, dict):
            inner = {}
        inner["tools"] = names
        if extra.get("onSite") is False:
            inner["onSite"] = False
        meta["meta"] = inner
        item["meta"] = meta
    return item


def fetch_civitai_version_by_hash(file_hash: str, timeout: int = 15) -> dict[str, Any] | None:
    """GET ``/api/v1/model-versions/by-hash/{hash}`` (AutoV2 etc.)."""
    h = str(file_hash or "").strip()
    if len(h) < 8:
        return None
    url = f"https://civitai.com/api/v1/model-versions/by-hash/{urllib.parse.quote(h)}"
    req = urllib.request.Request(
        url, headers={"User-Agent": mc.UA, "accept": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (
        urllib.error.URLError,
        TimeoutError,
        json.JSONDecodeError,
        OSError,
        ValueError,
    ):
        return None
    if not isinstance(data, dict) or not data.get("id"):
        return None
    return data


def unwrap_image_generation(item: dict[str, Any] | None) -> dict[str, Any]:
    """Civitai nests generation params at ``meta.meta`` when ``withMeta=true``."""
    if not isinstance(item, dict):
        return {}
    meta = item.get("meta")
    if not isinstance(meta, dict):
        return {}
    inner = meta.get("meta")
    if isinstance(inner, dict) and (
        inner.get("prompt")
        or inner.get("resources")
        or inner.get("comfy")
        or inner.get("sampler")
        or inner.get("Model")
        or inner.get("hashes")
        or inner.get("seed") is not None
    ):
        return inner
    if meta.get("prompt") or meta.get("resources") or meta.get("hashes") or meta.get("comfy"):
        return meta
    return {}


def generation_resource_rows(gen: dict[str, Any] | None) -> list[dict[str, Any]]:
    """``resources`` plus nameless ``civitaiResources`` version ids."""
    if not isinstance(gen, dict):
        return []
    out: list[dict[str, Any]] = []
    for key in ("resources", "civitaiResources"):
        rows = gen.get(key)
        if not isinstance(rows, list):
            continue
        out.extend(row for row in rows if isinstance(row, dict))
    return out


def lora_hints_from_generation(gen: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    """Map LoRA names to Civitai version ids.

    Prompt hashes pin the exact file (Klein-anime V1 vs V3). Resources-used
    (tRPC / page scrape) fill Draw Things posts that have no ``hashes``.
    """
    if not isinstance(gen, dict):
        return {}
    hints: dict[str, dict[str, Any]] = {}
    for row in generation_resource_rows(gen):
        if not isinstance(row, dict):
            continue
        kind = str(row.get("type") or row.get("modelType") or "").lower()
        if "lora" not in kind:
            continue
        vid = row.get("modelVersionId") or row.get("versionId")
        try:
            vid_i = int(vid) if vid is not None else None
        except (TypeError, ValueError):
            vid_i = None
        tag = str(row.get("name") or row.get("modelName") or "").strip()
        if not tag and vid_i is not None:
            tag = str(vid_i)
        if not tag or not vid_i:
            continue
        hints[tag] = {
            "version_id": vid_i,
            "version_name": str(row.get("versionName") or row.get("version_name") or ""),
            "filename": str(row.get("filename") or ""),
            "model_name": tag,
            "base": str(row.get("baseModel") or row.get("base") or ""),
        }
    hashes = gen.get("hashes")
    if not isinstance(hashes, dict):
        return hints
    for key, raw_hash in hashes.items():
        k = str(key or "")
        if not k.lower().startswith("lora:"):
            continue
        tag = k.split(":", 1)[1].strip()
        hv = str(raw_hash or "").strip()
        if not tag or not hv:
            continue
        data = fetch_civitai_version_by_hash(hv)
        if not data:
            continue
        files = [f for f in (data.get("files") or []) if isinstance(f, dict)]
        fname = ""
        for f in files:
            if f.get("primary"):
                fname = str(f.get("name") or "")
                break
        if not fname and files:
            fname = str(files[0].get("name") or "")
        hints[tag] = {
            "version_id": data.get("id"),
            "version_name": str(data.get("name") or ""),
            "filename": fname,
            "hash": hv,
            "model_name": str((data.get("model") or {}).get("name") or ""),
        }
    return hints


def verify_http_url(url: str, timeout: int = 15) -> bool:
    """True when the URL exists (200/3xx) or is gated (401/403)."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return False
    req = urllib.request.Request(
        url, method="HEAD", headers={"User-Agent": mc.UA, "accept": "*/*"}
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return int(getattr(resp, "status", 200) or 200) < 400
    except urllib.error.HTTPError as e:
        return int(e.code) in (401, 403)
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return False


def _pick_version_file(
    data: dict[str, Any], filename: str | None
) -> dict[str, Any] | None:
    files = [f for f in (data.get("files") or []) if isinstance(f, dict)]
    if not files:
        return None
    want = (filename or "").strip()
    if want:
        for f in files:
            if str(f.get("name") or "") == want:
                return f
        scored = [
            (score_civitai_hit(want, "", [str(f.get("name") or "")]), f) for f in files
        ]
        scored.sort(key=lambda t: t[0], reverse=True)
        if scored[0][0] >= 90:
            return scored[0][1]
        return None
    for f in files:
        if f.get("primary"):
            return f
    return files[0]


def apply_civitai_version(
    item: dict[str, Any],
    data: dict[str, Any],
    *,
    filename: str | None = None,
) -> dict[str, Any]:
    """Fill download/filename from a live model-versions payload. Sets verified."""
    item = dict(item)
    src = dict(item.get("source") or {})
    want = filename or str(src.get("filename") or "") or None
    chosen = _pick_version_file(data, want) or _pick_version_file(data, None)
    vid = _id_num(data.get("id"))
    api_mid = _id_num(data.get("modelId"))
    src_mid = _id_num(src.get("model_id"))
    if api_mid and api_mid != vid:
        mid = api_mid
    else:
        mid = src_mid or api_mid
    if chosen is None or not vid:
        item["verified"] = False
        item["source"] = src
        return item
    dl = str(chosen.get("downloadUrl") or "").strip()
    if not dl.startswith("http"):
        dl = f"https://civitai.com/api/download/models/{vid}"
    fname = want if want and str(want).lower().endswith(".safetensors") else str(
        chosen.get("name") or src.get("filename") or ""
    )
    src.update(
        {
            "host": "civitai",
            "model_id": mid or src.get("model_id"),
            "version_id": vid,
            "version_name": str(data.get("name") or src.get("version_name") or "").strip(),
            "download": dl,
            "filename": fname,
            "page": (
                f"https://civitai.com/models/{mid}?modelVersionId={vid}"
                if mid
                else str(src.get("page") or "")
            ),
        }
    )
    item["source"] = src
    item["verified"] = True
    if mid and vid:
        item["id"] = f"civitai:{mid}@{vid}"
    return item


def verify_item(
    item: dict[str, Any], *, live: bool = True, timeout: int = 15
) -> dict[str, Any]:
    """Confirm a LoRA/safetensor ref against Civitai, HTTP, replica disk, or a local file."""
    item = dict(item)
    src = dict(item.get("source") or {})
    item["source"] = src
    download = str(src.get("download") or "")
    filename = str(src.get("filename") or "")
    host = str(src.get("host") or "")
    if _is_replica_item(item):
        item["verified"] = True
        return item
    if filename and Path(filename).name in replica_weight_names() and not download.startswith("http"):
        item["verified"] = True
        return item
    if host == "local" or (
        filename.lower().endswith(".safetensors")
        and not download.startswith("http://")
        and not download.startswith("https://")
    ):
        path = Path(download) if download and not download.startswith("http") else Path(filename)
        item["verified"] = path.is_file() and path.suffix.lower() == ".safetensors"
        return item
    if not live:
        item["verified"] = bool(item.get("verified"))
        return item
    vid = _id_num(src.get("version_id")) or _id_num(civitai_version_from_url(download))
    if host == "civitai" or vid:
        data = fetch_civitai_version(vid, timeout=timeout) if vid else None
        if not data:
            item["verified"] = False
            return item
        want = filename if filename.lower().endswith(".safetensors") else None
        return apply_civitai_version(item, data, filename=want)
    if download.startswith("http://") or download.startswith("https://"):
        item["verified"] = verify_http_url(download, timeout=timeout)
        return item
    item["verified"] = False
    return item


def verify_safetensor_ref(name: str, *, extras_path: Path | None = None) -> bool:
    """True for a replica filename, a verified extras/catalog row, or a live URL."""
    raw = (name or "").strip()
    if not raw:
        return False
    fname = Path(urlparse(_url_without_token(raw)).path).name or raw
    if fname in replica_weight_names():
        return True
    item = find_by_loader_name(raw, extras_path)
    if item is None and not raw.lower().endswith(".safetensors"):
        item = find_by_loader_name(raw + ".safetensors", extras_path)
    if item is not None:
        if item.get("verified") is True or _is_replica_item(item) or _is_known_id(item.get("id")):
            return True
        checked = verify_item(item, live=True)
        return checked.get("verified") is True
    if raw.startswith("http://") or raw.startswith("https://"):
        vid = _id_num(civitai_version_from_url(raw))
        if vid:
            return fetch_civitai_version(vid) is not None
        return verify_http_url(raw)
    path = Path(raw)
    return path.is_file() and path.suffix.lower() == ".safetensors"


def unverified_payload_refs(
    payload: dict[str, Any], extras_path: Path | None = None
) -> list[str]:
    """LoRA / UNET / CLIP / VAE names in a /prompt body that are not verified."""
    prompt = payload.get("prompt") if isinstance(payload, dict) else None
    if not isinstance(prompt, dict):
        return []
    keys = ("lora_name", "unet_name", "clip_name", "vae_name", "ckpt_name")
    seen: list[str] = []
    for node in prompt.values():
        if not isinstance(node, dict):
            continue
        inputs = node.get("inputs") if isinstance(node.get("inputs"), dict) else {}
        for key in keys:
            raw = str(inputs.get(key) or "").strip()
            if not raw or raw in seen:
                continue
            if verify_safetensor_ref(raw, extras_path=extras_path):
                continue
            seen.append(raw)
    return seen


def _item_from_civitai_ref(ref: str, *, name: str | None, filename: str | None) -> dict[str, Any]:
    model_id, version_id = mc.parse_ref(ref)
    ver = version_id or model_id
    item_id = f"civitai:{model_id}@{ver}"
    existing = None
    for known in mc.KNOWN:
        if known.get("id") == item_id:
            existing = dict(known)
            break
        src = known.get("source") or {}
        if src.get("version_id") == ver:
            existing = dict(known)
            break
    if existing is not None:
        if name:
            existing["name"] = name
        if filename:
            src = dict(existing.get("source") or {})
            src["filename"] = filename
            existing["source"] = src
        existing.setdefault("verified", _is_replica_item(existing))
        return existing
    fname = filename or f"civitai-{ver}.safetensors"
    download = f"https://civitai.com/api/download/models/{ver}"
    return {
        "id": item_id,
        "name": name or item_id,
        "kind": "lora",
        "base": "",
        "use": [],
        "status": "user",
        "verified": False,
        "source": {
            "host": "civitai",
            "page": f"https://civitai.com/models/{model_id}?modelVersionId={ver}",
            "model_id": model_id,
            "version_id": ver,
            "download": download,
            "filename": fname,
        },
    }


def _item_from_url(url: str, *, name: str | None, filename: str | None) -> dict[str, Any]:
    parsed = urlparse(url)
    host = (parsed.netloc or "").lower()
    fname = filename or _filename_from_url(url)
    if "civitai.com" in host:
        dl = _DL_VER.search(url)
        if dl:
            ver = int(dl.group(1))
            try:
                return _item_from_civitai_ref(f"{ver}@{ver}", name=name, filename=fname)
            except SystemExit:
                pass
        try:
            return _item_from_civitai_ref(url, name=name, filename=fname)
        except SystemExit:
            pass
    if "huggingface.co" in host or "hf.co" in host:
        item_id = f"hf:{fname}"
        return {
            "id": item_id,
            "name": name or fname,
            "kind": "lora",
            "base": "",
            "use": [],
            "status": "user",
            "verified": False,
            "source": {
                "host": "huggingface",
                "page": url,
                "download": url,
                "filename": fname,
            },
        }
    item_id = f"url:{fname}"
    return {
        "id": item_id,
        "name": name or fname,
        "kind": "lora",
        "base": "",
        "use": [],
        "status": "user",
        "verified": False,
        "source": {
            "host": "url",
            "page": url,
            "download": url,
            "filename": fname,
        },
    }


def _item_from_local(path: Path, *, name: str | None, filename: str | None) -> dict[str, Any]:
    fname = filename or path.name
    item_id = f"local:{fname}"
    return {
        "id": item_id,
        "name": name or path.stem,
        "kind": "lora",
        "base": "",
        "use": [],
        "status": "user",
        "verified": path.is_file() and path.suffix.lower() == ".safetensors",
        "source": {
            "host": "local",
            "page": str(path),
            "download": str(path),
            "filename": fname,
        },
    }


def add_lora(
    ref: str,
    *,
    extras_path: Path | None = None,
    name: str | None = None,
    filename: str | None = None,
    strength_model: float | None = None,
    strength_clip: float | None = None,
    base: str | None = None,
    verified: bool | None = None,
    verify: bool = True,
    version_name: str | None = None,
) -> dict[str, Any]:
    """Add a LoRA from civitai / huggingface / local path / download URL.

    URLs are not trusted until ``verified`` is set (live Civitai/HTTP check
    unless the caller already confirmed the ref, e.g. a search hit).
    """
    raw = (ref or "").strip()
    if not raw:
        raise ValueError("empty LoRA ref")
    path = Path(raw)
    low = raw.lower().split("?", 1)[0]
    looks_file = (
        path.is_file()
        or (
            low.endswith(".safetensors")
            and not raw.startswith("http://")
            and not raw.startswith("https://")
        )
    )
    if looks_file:
        item = _item_from_local(path, name=name, filename=filename or path.name)
    elif raw.startswith("http://") or raw.startswith("https://"):
        item = _item_from_url(raw, name=name, filename=filename)
    else:
        try:
            item = _item_from_civitai_ref(raw, name=name, filename=filename)
        except SystemExit as e:
            raise ValueError(str(e)) from None
    if strength_model is not None:
        item["strength_model"] = float(strength_model)
    if strength_clip is not None:
        item["strength_clip"] = float(strength_clip)
    if base is not None:
        item["base"] = normalize_family(base)
    if version_name:
        src = dict(item.get("source") or {})
        src["version_name"] = str(version_name).strip()
        item["source"] = src
    if verified is True:
        item["verified"] = True
    elif verify:
        item = verify_item(item, live=True)
    else:
        item["verified"] = bool(item.get("verified"))
    if not str((item.get("source") or {}).get("version_name") or "").strip() and (
        verify or verified is True
    ):
        # ensure_civitai_version_name returns early (no write) for non-Civitai
        # refs, so persist the row ourselves on both branches.
        item = ensure_civitai_version_name(item, extras_path=extras_path, live=True)
    return write_extra(item, extras_path)


def write_extra(item: dict[str, Any], extras_path: Path | None = None) -> dict[str, Any]:
    """Persist an extras/catalog overlay row (including ``verified``)."""
    dest = _resolve_extras(extras_path)
    extras = [it for it in _load_extras(dest) if it.get("id") != item.get("id")]
    extras.append(item)
    extras = _collapse_loras(extras)
    _save_extras(dest, extras)
    return item


def verify_lora(lora_id: str, extras_path: Path | None = None) -> dict[str, Any]:
    """Live-check one catalog/extra row and save the verified flag."""
    item = find_lora(lora_id, extras_path)
    if item is None:
        raise ValueError(f"unknown LoRA {lora_id}")
    checked = verify_item(item, live=True)
    return write_extra(checked, extras_path)


def verify_unverified_loras(
    extras_path: Path | None = None,
) -> tuple[int, int, list[str]]:
    """Verify every row that is not already verified. Returns (ok, fail, failed ids)."""
    ok = 0
    fail = 0
    failed: list[str] = []
    for item in list_loras(extras_path):
        lid = str(item.get("id") or "")
        if item.get("verified") is True or _is_replica_item(item):
            continue
        if not lid:
            continue
        checked = verify_item(item, live=True)
        write_extra(checked, extras_path)
        if checked.get("verified") is True:
            ok += 1
        else:
            fail += 1
            failed.append(lid)
    return ok, fail, failed


def edit_lora(
    lora_id: str,
    *,
    extras_path: Path | None = None,
    name: str | None = None,
    filename: str | None = None,
    strength_model: float | None = None,
    strength_clip: float | None = None,
    base: str | None = None,
) -> dict[str, Any]:
    """Overlay an extra (or annotate a catalog row) and persist it."""
    item = find_lora(lora_id, extras_path)
    if item is None:
        raise ValueError(f"unknown LoRA {lora_id}")
    item = dict(item)
    src = dict(item.get("source") or {})
    item["source"] = src
    if name is not None:
        item["name"] = str(name)
    if filename is not None:
        src["filename"] = str(filename)
    if strength_model is not None:
        item["strength_model"] = float(strength_model)
    if strength_clip is not None:
        item["strength_clip"] = float(strength_clip)
    if base is not None:
        item["base"] = normalize_family(base)
    dest = _resolve_extras(extras_path)
    extras = _load_extras(dest)
    extras = [it for it in extras if it.get("id") != lora_id]
    extras.append(item)
    _save_extras(dest, extras)
    return item


def remove_lora(lora_id: str, extras_path: Path | None = None) -> bool:
    """Remove a user extra. Known catalog rows cannot be deleted."""
    dest = _resolve_extras(extras_path)
    extras = _load_extras(dest)
    kept = [it for it in extras if it.get("id") != lora_id]
    if len(kept) == len(extras):
        return False
    _save_extras(dest, kept)
    return True
