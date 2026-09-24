#!/usr/bin/env python3
"""Local LoRA/checkpoint cache with Civitai (or Salad-baked) provenance.

Weights live in art/model-cache/ (gitignored, under /art/). The on-disk
index.json stores source URLs, Civitai ids, hashes, and local filenames.
Salad Comfy still URL-loads on a new replica — this cache stops *this*
machine from re-pulling Civitai, and is the bake source for a custom image.

    python model_catalog.py seed
    python model_catalog.py fetch civitai:702491@866836
    python model_catalog.py fetch-missing
    python model_catalog.py list
    python model_catalog.py path civitai:702491@866836

Override cache root with ELDERMARK_MODEL_CACHE (tests).

The `salad_klein/` Docker-image tree this catalog bakes for sits beside this
module in the same checkout; point SALAD_STUDIO_HOME at a different root (the
same-named environment variable overrides the default).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

_INDEX_LOCK = threading.Lock()

# Eldermark art tree (the gitignored model cache lives under it); the
# ELDERMARK_ART environment variable overrides the default.
ELDERMARK_ART = Path(
    os.environ.get("ELDERMARK_ART", r"C:\Users\vkozy\repos\lifesim-design\art")
)
DEFAULT_CACHE = ELDERMARK_ART / "model-cache"
# Root of this checkout (its own salad_klein/ Docker-image tree lives under it).
# Override with the SALAD_STUDIO_HOME environment variable when it lives elsewhere.
SALAD_STUDIO_HOME = Path(
    os.environ.get("SALAD_STUDIO_HOME") or Path(__file__).resolve().parent
)
KLEIN_HF_IDS = (
    "hf:flux-2-klein-base-9b-fp8",
    "hf:flux-2-klein-9b-fp8",
    "hf:qwen_3_8b_fp8mixed",
    "hf:flux2-vae",
)
KLEIN_WEIGHTS_DIR = SALAD_STUDIO_HOME / "salad_klein" / "weights"
INDEX_NAME = "index.json"
SCHEMA = 1
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)
# Auto-fetch LoRAs under this size. UltraRealPhoto v2 is ~2 GB — metadata only.
AUTO_MAX_BYTES = 64 * 1024 * 1024
CIVITAI_REF = re.compile(
    r"(?:civitai:)?(?P<model>\d+)(?:@(?P<version>\d+))?",
    re.I,
)
CIVITAI_URL = re.compile(
    r"civitai\.com/models/(?P<model>\d+)",
    re.I,
)

# Provenance of every weight this session actually used or rejected.
# local_file is filled after a successful fetch; do_not_redownload means
# do not pull onto a Salad Flux replica (OOM / wrong family / Krea 2).
KNOWN: list[dict[str, Any]] = [
    {
        "id": "salad:flux1-dev-fp8",
        "name": "Flux.1-dev fp8 (Salad Comfy recipe)",
        "kind": "checkpoint",
        "base": "Flux.1 D",
        "use": ["faces", "bodies"],
        "status": "working-probe",
        "do_not_redownload": False,
        "source": {
            "host": "salad-recipe",
            "page": "https://docs.salad.com/container-engine/reference/recipes/comfyui",
            "filename": "flux1-dev-fp8.safetensors",
            "note": "Baked on ComfyUI API Flux.1 Dev. Not a Civitai file.",
        },
    },
    {
        "id": "hf:flux-2-klein-base-9b-fp8",
        "name": "FLUX.2 Klein 9B-Base fp8 unet",
        "kind": "checkpoint",
        "base": "Flux.2 Klein 9B",
        "use": ["events", "bodies", "faces"],
        "status": "on-klein-group",
        "do_not_redownload": False,
        "source": {
            "host": "huggingface",
            "page": "https://huggingface.co/black-forest-labs/FLUX.2-klein-base-9b-fp8",
            "download": "https://huggingface.co/black-forest-labs/FLUX.2-klein-base-9b-fp8/resolve/main/flux-2-klein-base-9b-fp8.safetensors",
            "filename": "flux-2-klein-base-9b-fp8.safetensors",
            "comfy_dir": "diffusion_models",
            "size_bytes": 8910000000,
            "note": "Gated BFL. Prefetch at Klein replica start; HF_TOKEN needed to fetch.",
        },
    },
    {
        "id": "hf:flux-2-klein-9b-fp8",
        "name": "FLUX.2 Klein 9B distilled fp8 unet",
        "kind": "checkpoint",
        "base": "Flux.2 Klein 9B",
        "use": ["events", "bodies", "faces"],
        "status": "on-klein-group",
        "do_not_redownload": False,
        "source": {
            "host": "huggingface",
            "page": "https://huggingface.co/black-forest-labs/FLUX.2-klein-9b-fp8",
            "download": "https://huggingface.co/black-forest-labs/FLUX.2-klein-9b-fp8/resolve/main/flux-2-klein-9b-fp8.safetensors",
            "filename": "flux-2-klein-9b-fp8.safetensors",
            "comfy_dir": "diffusion_models",
            "size_bytes": 8910000000,
            "note": "Gated BFL distilled Klein. Prefetch at replica start with base-9b.",
        },
    },
    {
        "id": "hf:qwen_3_8b_fp8mixed",
        "name": "Qwen 3 8B fp8mixed (Klein CLIP)",
        "kind": "checkpoint",
        "base": "Flux.2 Klein 9B",
        "use": ["events", "bodies", "faces"],
        "status": "on-klein-group",
        "do_not_redownload": False,
        "source": {
            "host": "huggingface",
            "page": "https://huggingface.co/Comfy-Org/flux2-klein-9B",
            "download": "https://huggingface.co/Comfy-Org/flux2-klein-9B/resolve/main/split_files/text_encoders/qwen_3_8b_fp8mixed.safetensors",
            "filename": "qwen_3_8b_fp8mixed.safetensors",
            "comfy_dir": "text_encoders",
            "size_bytes": 8070000000,
            "note": "Bake into salad_klein image.",
        },
    },
    {
        "id": "hf:flux2-vae",
        "name": "FLUX.2 VAE",
        "kind": "checkpoint",
        "base": "Flux.2 Klein 9B",
        "use": ["events", "bodies", "faces"],
        "status": "on-klein-group",
        "do_not_redownload": False,
        "source": {
            "host": "huggingface",
            "page": "https://huggingface.co/Comfy-Org/flux2-dev",
            "download": "https://huggingface.co/Comfy-Org/flux2-dev/resolve/main/split_files/vae/flux2-vae.safetensors",
            "filename": "flux2-vae.safetensors",
            "comfy_dir": "vae",
            "size_bytes": 320000000,
            "note": "Bake into salad_klein image.",
        },
    },
    {
        "id": "civitai:2416142@2786085",
        "name": "SNOFS Merged distilled v1.2 Klein fp8 unet",
        "kind": "checkpoint",
        "base": "Flux.2 Klein 9B",
        "use": ["bodies", "sex"],
        "status": "on-klein-group",
        "do_not_redownload": False,
        "source": {
            "host": "civitai",
            "page": "https://civitai.com/models/2416142?modelVersionId=2786085",
            "model_id": 2416142,
            "version_id": 2786085,
            "download": "https://civitai.com/api/download/models/2786085",
            "filename": "snofsSexNudesAndOther_distilledV12KleinFp8.safetensors",
            "sha256": "8F14F15040C2E041DE87058E29317663338BB6B77054D224C1BFCCFFCFEB1E35",
            "size_bytes": 9078612168,
            "note": (
                "The checkpoint with SNOFS built in — the author's own SNOFS merged onto "
                "distilled Klein 9B as an fp8 unet, which is why the two-body plates "
                "ride it: prompt_snofs_distilled_anatomy.json / _resms.json set node 70 "
                "to this very filename. On this route there is no separate SNOFS LoRA "
                "weight to set — the LoKr (civitai:1972981@2960556) belongs to the plain "
                "/ base Klein unet route, and stacked on this unet it measured safe but "
                "redundant. Same bytes as the HF mirror edwixx/Flux2Klein9B_SNOFS "
                "snofsSexNudesAndOtherFunStuff_distilledV12Fp8.safetensors, which is what "
                "prefetch.py pulls at replica start and renames to this filename."
            ),
        },
    },
    {
        "id": "civitai:796382@1026423",
        "name": "UltraRealPhoto Flux v2",
        "kind": "lora",
        "base": "Flux.1 D",
        "use": ["faces", "bodies"],
        "status": "working-probe",
        "do_not_redownload": False,
        "source": {
            "host": "civitai",
            "page": "https://civitai.com/models/796382?modelVersionId=1026423",
            "model_id": 796382,
            "version_id": 1026423,
            "file_id": 932239,
            "download": "https://civitai.com/api/download/models/1026423?fileId=932239",
            "filename": "UltraRealPhoto.safetensors",
            "sha256": "B1C4DDF95671E6B51817B4F3802865E544040C232C467E76B1CB0C251BD6B634",
            "size_bytes": 2144814080,
        },
    },
    {
        "id": "civitai:702491@866836",
        "name": "Inzaniak Light (non-anime Flux)",
        "kind": "lora",
        "base": "Flux.1 D",
        "use": ["events"],
        "status": "probe",
        "do_not_redownload": False,
        "source": {
            "host": "civitai",
            "page": "https://civitai.com/models/702491?modelVersionId=866836",
            "model_id": 702491,
            "version_id": 866836,
            "file_id": 775727,
            "download": "https://civitai.com/api/download/models/866836?fileId=775727",
            "filename": "Light_-_Flux.safetensors",
            "sha256": "B391A3851B7B6051704922BAB469F8F769F02563DA47EBD106AE8F6F08E881DD",
            "size_bytes": 19265864,
        },
    },
    {
        "id": "civitai:702491@829557",
        "name": "Inzaniak Weird (non-anime Flux)",
        "kind": "lora",
        "base": "Flux.1 D",
        "use": ["events"],
        "status": "listed",
        "do_not_redownload": False,
        "source": {
            "host": "civitai",
            "page": "https://civitai.com/models/702491?modelVersionId=829557",
            "model_id": 702491,
            "version_id": 829557,
            "file_id": 743572,
            "download": "https://civitai.com/api/download/models/829557?fileId=743572",
            "filename": "weird_flux.safetensors",
            "sha256": "236826D58C62BAB6E62AAD39055F4EBA8B20B16325A38EAD68845101A19B2055",
            "size_bytes": 19168768,
        },
    },
    {
        "id": "civitai:702491@787185",
        "name": "Inzaniak Sketchy (non-anime Flux)",
        "kind": "lora",
        "base": "Flux.1 D",
        "use": ["events"],
        "status": "listed",
        "do_not_redownload": False,
        "source": {
            "host": "civitai",
            "page": "https://civitai.com/models/702491?modelVersionId=787185",
            "model_id": 702491,
            "version_id": 787185,
            "file_id": 700564,
            "download": "https://civitai.com/api/download/models/787185?fileId=700564",
            "filename": "sketchy_flux.safetensors",
            "sha256": "CAB9FCC866AE773AA606D71199BEB3759C8097FA596F5203543B09FFA6BCDC06",
            "size_bytes": 19171056,
        },
    },
    {
        "id": "civitai:702491@785986",
        "name": "Inzaniak Twisted (non-anime Flux)",
        "kind": "lora",
        "base": "Flux.1 D",
        "use": ["events"],
        "status": "listed",
        "do_not_redownload": False,
        "source": {
            "host": "civitai",
            "page": "https://civitai.com/models/702491?modelVersionId=785986",
            "model_id": 702491,
            "version_id": 785986,
            "file_id": 699482,
            "download": "https://civitai.com/api/download/models/785986?fileId=699482",
            "filename": "twisted_flux.safetensors",
            "sha256": "A2F9A2AF46A3AC6D30C9FBF6CB609781B2A1B4E0E021A8B275F8129702F19EFA",
            "size_bytes": 19171128,
        },
    },
    {
        "id": "civitai:264290@720004",
        "name": "Watercolor Painting (Pony XL)",
        "kind": "lora",
        "base": "Pony",
        "use": ["events"],
        "status": "probe",
        "do_not_redownload": False,
        "source": {
            "host": "civitai",
            "page": "https://civitai.com/models/264290?modelVersionId=720004",
            "model_id": 264290,
            "version_id": 720004,
            "file_id": 634621,
            "download": "https://civitai.com/api/download/models/720004?fileId=634621",
            "filename": "Watercolor Painting Style LoRA_Pony XL v6.safetensors",
            "sha256": "50A1C0701F5E0CA266B9EAC8100F745C88C8C32B5F8381AC3E6075737C70C085",
            "size_bytes": 228454720,
        },
    },
    {
        "id": "civitai:257749@290640",
        "name": "Pony Diffusion V6 XL",
        "kind": "checkpoint",
        "base": "Pony",
        "use": ["sex", "events"],
        "status": "working-probe",
        "do_not_redownload": False,
        "source": {
            "host": "civitai",
            "page": "https://civitai.com/models/257749?modelVersionId=290640",
            "model_id": 257749,
            "version_id": 290640,
            "download": "https://civitai.com/api/download/models/290640",
            "filename": "ponyDiffusionV6XL_v6StartWithThisOne.safetensors",
        },
    },
    {
        "id": "civitai:573152@2155386",
        "name": "Lustify V7 GGWP",
        "kind": "checkpoint",
        "base": "SDXL",
        "use": ["sex"],
        "status": "probe",
        "do_not_redownload": False,
        "source": {
            "host": "civitai",
            "page": "https://civitai.com/models/573152?modelVersionId=2155386",
            "model_id": 573152,
            "version_id": 2155386,
            "download": "https://civitai.com/api/download/models/2155386",
            "note": "Civitai 401 without token.",
        },
    },
    {
        "id": "civitai:827184@2883731",
        "name": "WAI-illustrious-SDXL v17",
        "kind": "checkpoint",
        "base": "Illustrious",
        "use": ["sex"],
        "status": "probe",
        "do_not_redownload": False,
        "source": {
            "host": "civitai",
            "page": "https://civitai.com/models/827184?modelVersionId=2883731",
            "model_id": 827184,
            "version_id": 2883731,
            "download": "https://civitai.com/api/download/models/2883731",
        },
    },
    {
        "id": "civitai:1632416@2548590",
        "name": "PhotoStyle Sean Archer",
        "kind": "lora",
        "base": "Flux.1 D",
        "use": ["faces"],
        "status": "rejected",
        "do_not_redownload": False,
        "source": {
            "host": "civitai",
            "page": "https://civitai.com/models/1632416?modelVersionId=2548590",
            "model_id": 1632416,
            "version_id": 2548590,
            "download": "https://civitai.com/api/download/models/2548590",
            "note": "Male plates are women; not a DNA house.",
        },
    },
    {
        "id": "civitai:2433139@3302765",
        "name": "Golden Hour",
        "kind": "checkpoint",
        "base": "Illustrious",
        "use": ["bodies"],
        "status": "rejected",
        "do_not_redownload": True,
        "source": {
            "host": "civitai",
            "page": "https://civitai.com/models/2433139?modelVersionId=3302765",
            "model_id": 2433139,
            "version_id": 3302765,
            "download": "https://civitai.com/api/download/models/3302765",
            "note": "Failed front/crop/male. Do not use as body house.",
        },
    },
    {
        "id": "civitai:978314@1413133",
        "name": "UltraReal Fine-Tune fp8",
        "kind": "checkpoint",
        "base": "Flux.1 D",
        "use": ["faces"],
        "status": "rejected",
        "do_not_redownload": True,
        "source": {
            "host": "civitai",
            "page": "https://civitai.com/models/978314?modelVersionId=1413133",
            "model_id": 978314,
            "version_id": 1413133,
            "download": "https://civitai.com/api/download/models/1413133",
            "note": "Second ~12 GB Flux next to baked fp8 OOMs on 4090.",
        },
    },
    {
        "id": "civitai:618692@691639",
        "name": "Stock Flux.1-dev (Civitai)",
        "kind": "checkpoint",
        "base": "Flux.1 D",
        "use": ["faces"],
        "status": "rejected",
        "do_not_redownload": True,
        "source": {
            "host": "civitai",
            "page": "https://civitai.com/models/618692?modelVersionId=691639",
            "model_id": 618692,
            "version_id": 691639,
            "download": "https://civitai.com/api/download/models/691639",
            "note": "Same family as baked fp8. Do not re-download.",
        },
    },
    {
        "id": "civitai:2758431",
        "name": "KreaKult",
        "kind": "lora",
        "base": "Krea 2",
        "use": [],
        "status": "rejected",
        "do_not_redownload": True,
        "source": {
            "host": "civitai",
            "page": "https://civitai.com/models/2758431",
            "model_id": 2758431,
            "note": "Krea 2 LoRA; silent no-op on Flux-dev.",
        },
    },
    {
        "id": "civitai:2888019",
        "name": "FasciumKROMA",
        "kind": "checkpoint",
        "base": "Krea 2",
        "use": [],
        "status": "rejected",
        "do_not_redownload": True,
        "source": {
            "host": "civitai",
            "page": "https://civitai.com/models/2888019",
            "model_id": 2888019,
            "note": "Krea 2 ~12.5 GB. Do not load on Flux/SDXL recipe.",
        },
    },
    {
        "id": "civitai:2334190@2625692",
        "name": "Klein Detail Slider",
        "kind": "lora",
        "base": "Flux.2 Klein 9B",
        "use": ["faces", "bodies", "events"],
        "status": "listed",
        "do_not_redownload": False,
        "source": {
            "host": "civitai",
            "page": "https://civitai.com/models/2334190?modelVersionId=2625692",
            "model_id": 2334190,
            "version_id": 2625692,
            "download": "https://civitai.com/api/download/models/2625692",
            "filename": "klein_slider_detail.safetensors",
            "sha256": "083ECBD1438396452285838523594C4500868F6CAE3043B7C85E3FC464846CB6",
            "size_bytes": 20738144,
            "note": "Not on flux2-klein after_start; LoraLoader uses the Civitai URL.",
        },
    },
    {
        "id": "civitai:545264@2763568",
        "name": "Impressionism Klein9B",
        "kind": "lora",
        "base": "Flux.2 Klein 9B",
        "use": ["events"],
        "status": "listed",
        "do_not_redownload": False,
        "source": {
            "host": "civitai",
            "page": "https://civitai.com/models/545264?modelVersionId=2763568",
            "model_id": 545264,
            "version_id": 2763568,
            "download": "https://civitai.com/api/download/models/2763568",
            "filename": "impressionism_klein9b.safetensors",
            "sha256": "BD3C8B540E71C8D864FD01EC26C6B96E13E98A363923953811CCB905730D8E34",
            "size_bytes": 82866720,
            "note": "Trigger ArsMJStyle, Impressionism. Melts full-body paperdolls; events only.",
        },
    },
    {
        "id": "civitai:637213@2760271",
        "name": "Classic Oil Painting - CE V03a",
        "kind": "lora",
        "base": "Flux.2 Klein 9B",
        "use": ["faces"],
        "status": "listed",
        "do_not_redownload": False,
        "source": {
            "host": "civitai",
            "page": "https://civitai.com/models/637213?modelVersionId=2760271",
            "model_id": 637213,
            "version_id": 2760271,
            "download": "https://civitai.com/api/download/models/2760271",
            "filename": "ClassicOil03a_CE_FLUX2_Klein9b_AIT4k.safetensors",
            "sha256": "C11B19F6A17621A19A3B2A8063CAC7CACAAD2F7A48C2D0802CA1674382AB15A7",
            "size_bytes": 165704432,
            "note": "Ref image 123717470 @ strength 0.2. Not on Salad group yet.",
        },
    },
    {
        "id": "civitai:957327@2725918",
        "name": "Painterly - CE V01b",
        "kind": "lora",
        "base": "Flux.2 Klein 9B",
        "use": ["bodies", "events"],
        "status": "listed",
        "do_not_redownload": False,
        "source": {
            "host": "civitai",
            "page": "https://civitai.com/models/957327?modelVersionId=2725918",
            "model_id": 957327,
            "version_id": 2725918,
            "download": "https://civitai.com/api/download/models/2725918",
            "filename": "Painterly01b_CE_FLUX2_Klein9b_AIT6k.safetensors",
            "sha256": "61DC5A371725E90E33E591A9BABE12441C763855877045C2D5EA7AA38D0B6165",
            "size_bytes": 165704432,
            "note": "Ref image 122476755. Not on Salad group yet.",
        },
    },
    {
        "id": "civitai:660535@2748101",
        "name": "Vintage Drawing - CE V01a",
        "kind": "lora",
        "base": "Flux.2 Klein 9B",
        "use": ["bodies"],
        "status": "listed",
        "do_not_redownload": False,
        "source": {
            "host": "civitai",
            "page": "https://civitai.com/models/660535?modelVersionId=2748101",
            "model_id": 660535,
            "version_id": 2748101,
            "download": "https://civitai.com/api/download/models/2748101",
            "filename": "VintageDrawing01a_CE_FLUX2_Klein9b_AIT3k.safetensors",
            "sha256": "B022233E75EE2FFB62D3FF2B5CD6B3998D6DAB1BFBD8F31151D3BB4AFA833DA8",
            "size_bytes": 165704432,
            "note": "Ref image 123309022 pregnancy. Not on Salad group yet.",
        },
    },
    {
        "id": "civitai:1449678@2795018",
        "name": "Aged Art - CE V01a",
        "kind": "lora",
        "base": "Flux.2 Klein 9B",
        "use": ["events"],
        "status": "listed",
        "do_not_redownload": False,
        "source": {
            "host": "civitai",
            "page": "https://civitai.com/models/1449678?modelVersionId=2795018",
            "model_id": 1449678,
            "version_id": 2795018,
            "download": "https://civitai.com/api/download/models/2795018",
            "filename": "AgedArt01a_CE_FLUX2_Klein9b_AIT5k.safetensors",
            "sha256": "6452DCCDDFECA3175E1E8F6B53FC186E250A814ED4102DF0D68EB4ED665505F0",
            "size_bytes": 165704432,
            "note": "Ref image 125047656. Not on Salad group yet.",
        },
    },
    {
        "id": "civitai:754926@2767494",
        "name": "Medieval - CE V02",
        "kind": "lora",
        "base": "Flux.2 Klein 9B",
        "use": ["events"],
        "status": "listed",
        "do_not_redownload": False,
        "source": {
            "host": "civitai",
            "page": "https://civitai.com/models/754926?modelVersionId=2767494",
            "model_id": 754926,
            "version_id": 2767494,
            "download": "https://civitai.com/api/download/models/2767494",
            "filename": "Medieval02_CE_FLUX2_Klein9b_AIT4k.safetensors",
            "sha256": "BF680AF5526A87A7DA69469561C32997359DC3715B24CEEA4C8DA73AF8986258",
            "size_bytes": 165704432,
            "note": "Ref image 123970913. Not on Salad group yet.",
        },
    },
    {
        "id": "civitai:2745770@3088444",
        "name": "Artificeal v1.0",
        "kind": "lora",
        "base": "Flux.2 Klein 9B",
        "use": ["events"],
        "status": "listed",
        "do_not_redownload": False,
        "source": {
            "host": "civitai",
            "page": "https://civitai.com/models/2745770?modelVersionId=3088444",
            "model_id": 2745770,
            "version_id": 3088444,
            "download": "https://civitai.com/api/download/models/3088444",
            "filename": "Artificeal.safetensors",
            "sha256": "35F1B348A745FAD4D7012EAA51A10E014AC0A96629ADA6655EB5825404182F50",
            "size_bytes": 331380760,
            "note": "Trigger Artificeal style artwork. Ref image 135440425. Not on Salad group yet.",
        },
    },
    {
        "id": "civitai:2715533@3051077",
        "name": "YFG Grud F.2 Klein 9B 3K v1.0b",
        "kind": "lora",
        "base": "Flux.2 Klein 9B",
        "use": ["events"],
        "status": "listed",
        "do_not_redownload": False,
        "source": {
            "host": "civitai",
            "page": "https://civitai.com/models/2715533?modelVersionId=3051077",
            "model_id": 2715533,
            "version_id": 3051077,
            "download": "https://civitai.com/api/download/models/3051077",
            "filename": "YFG-Grud-F2K9_3k-v1.safetensors",
            "sha256": "B0D3F4D23F776C87269F868C82DDE5718FEFC877E73E991256F5CCD6BBB59F97",
            "size_bytes": 165704432,
            "note": "Trigger YFG-Grud style. Watercolor outlier, not the oil house. Ref 134526753.",
        },
    },
    {
        "id": "civitai:1972981@2960556",
        "name": "SNOFS LoKr Klein 9b v1.4",
        "kind": "lora",
        "base": "Flux.2 Klein 9B",
        "use": ["bodies", "sex"],
        "status": "listed",
        "do_not_redownload": False,
        "source": {
            "host": "civitai",
            "page": "https://civitai.com/models/1972981?modelVersionId=2960556",
            "model_id": 1972981,
            "version_id": 2960556,
            "download": "https://civitai.com/api/download/models/2960556",
            "filename": "klein_snofs_v1_4.safetensors",
            "sha256": "512C7F1D8DC7FA5DBC1FEE6049C2975EF3007300A5DE1712B3E1773CB95089F7",
            "size_bytes": 1090563760,
            "note": (
                "LoKr; Comfy LoraLoader reads the format. Trained on full natural-language "
                "sentences, not tags — the author's own vocabulary (missionary / doggystyle / "
                "cowgirl / spooning / prone position) is what it answers to. 0.3-0.7 on the "
                "two-body recipe: when limbs explode, lower SNOFS FIRST, before the anatomy "
                "fixer. The author's advice is to try SNOFS alone before stacking other "
                "general NSFW LoRAs on it. Runs on Klein 9B base as well as distilled. On "
                "this group the shipped plates ride the SNOFS distilled v1.2 UNET instead "
                "(civitai:2416142@2786085, the unet prompt_snofs_distilled_anatomy.json "
                "names) — 0.3 measured safe but redundant there; apply this LoKr on the "
                "plain / base Klein unet route."
            ),
        },
    },
    {
        "id": "civitai:2324991@2615554",
        "name": "Klein Anatomy / Quality Fixer v1.5",
        "kind": "lora",
        "base": "Flux.2 Klein 9B",
        "use": ["bodies", "sex"],
        "status": "listed",
        "do_not_redownload": False,
        "source": {
            "host": "civitai",
            "page": "https://civitai.com/models/2324991?modelVersionId=2615554",
            "model_id": 2324991,
            "version_id": 2615554,
            "download": "https://civitai.com/api/download/models/2615554",
            "filename": "klein_slider_anatomy.safetensors",
            "sha256": "2076AD1EA2DE379901A2786466FAC62ED2810E3D3738001A89F8BE587928943C",
            "size_bytes": 20738144,
            "note": (
                "The anatomy fixer: extra limbs, fused legs, general glitches. Author: 2.0 "
                "mostly keeps the seed and fixes minor glitches, 3.0 fixes more prominent "
                "artifacts; negative strengths act like an SD negative prompt. v1.5 is "
                "anatomy-only (v1.0 2615475 also moves quality)."
            ),
        },
    },
    {
        "id": "civitai:2335408@2627022",
        "name": "Back Pose Enhancer 1A [Klein 9B]",
        "kind": "lora",
        "base": "Flux.2 Klein 9B",
        "use": ["bodies", "sex"],
        "status": "listed",
        "do_not_redownload": False,
        "source": {
            "host": "civitai",
            "page": "https://civitai.com/models/2335408?modelVersionId=2627022",
            "model_id": 2335408,
            "version_id": 2627022,
            "download": "https://civitai.com/api/download/models/2627022",
            "filename": "1A_Back_Pose_Enhancer.safetensors",
            "sha256": "016E0D4FE9409338A29D07DBA0BF00A9BBB4F4AA4753B7F54882372DF107CAE3",
            "size_bytes": 174099976,
            "note": (
                "Sitting / back-facing two-body poses — the cowgirl weak spot. 1A is general "
                "use and the author's default; 1C (2627093) is the other cut, and the MLX "
                "builds are for Mac. Adds at ~1.0, and only when someone is sitting with "
                "their back to the camera."
            ),
        },
    },
    {
        "id": "civitai:2333479@2624854",
        "name": "General Penis LoRA [Klein 9B] v1.0",
        "kind": "lora",
        "base": "Flux.2 Klein 9B",
        "use": ["bodies", "sex"],
        "status": "listed",
        "do_not_redownload": False,
        "source": {
            "host": "civitai",
            "page": "https://civitai.com/models/2333479?modelVersionId=2624854",
            "model_id": 2333479,
            "version_id": 2624854,
            "download": "https://civitai.com/api/download/models/2624854",
            "filename": "Klein9BGeneralPenis-v1-0.safetensors",
            "sha256": "0D0D6AEDEA51539AC566F9BD7C5C514E7C9FB07C8FA77D00358B90461A97760C",
            "size_bytes": 165704424,
            "note": (
                "Male genital / body accuracy. Trained words: penis, erect, flaccid, "
                "foreskin, hung, uncircumcised — name the type in the prompt rather than "
                "leaving it to the model. v1.5BETA (2790299) has more variation but the "
                "author flags distortion; v1.0 is the stable cut. ~0.6-1.0."
            ),
        },
    },
    {
        "id": "civitai:2482439@2790993",
        "name": "Klein Fixes (NSFW) v1.0",
        "kind": "lora",
        "base": "Flux.2 Klein 9B",
        "use": ["bodies", "sex"],
        "status": "listed",
        "do_not_redownload": False,
        "source": {
            "host": "civitai",
            "page": "https://civitai.com/models/2482439?modelVersionId=2790993",
            "model_id": 2482439,
            "version_id": 2790993,
            "download": "https://civitai.com/api/download/models/2790993",
            "filename": "FLUX_NSFW_Fix.safetensors",
            "sha256": "68C4266C269BB57385C08CAB9FE47B44120F8AA99B0BFD2AC13BD3ECB1DF855C",
            "size_bytes": 331379136,
            "note": (
                "The house tail LoRA (1.0) on the two-body plates. Trained words name "
                "what it fixes: breast size/shape descriptions, vulva, anus, pubic "
                "hair. Sits last in the chain so the CLIP encodes land on it."
            ),
        },
    },
]


def cache_root() -> Path:
    override = os.environ.get("ELDERMARK_MODEL_CACHE")
    return Path(override) if override else DEFAULT_CACHE


def index_path() -> Path:
    return cache_root() / INDEX_NAME


def civitai_token() -> str:
    p = Path.home() / ".config" / "civitai" / "token"
    return p.read_text(encoding="utf-8").strip() if p.is_file() else ""


def hf_token() -> str:
    p = Path.home() / ".config" / "huggingface" / "token"
    return p.read_text(encoding="utf-8").strip() if p.is_file() else ""


def empty_index() -> dict[str, Any]:
    return {"schema": SCHEMA, "items": []}


def load_index() -> dict[str, Any]:
    path = index_path()
    if not path.is_file():
        return empty_index()
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or "items" not in data:
        raise SystemExit(f"bad index: {path}")
    return data


def save_index(data: dict[str, Any]) -> None:
    root = cache_root()
    root.mkdir(parents=True, exist_ok=True)
    (root / "loras").mkdir(exist_ok=True)
    (root / "checkpoints").mkdir(exist_ok=True)
    (root / "hf").mkdir(exist_ok=True)
    tmp = index_path().with_suffix(".json.tmp")
    payload = json.dumps(data, indent=2, sort_keys=False) + "\n"
    with _INDEX_LOCK:
        tmp.write_text(payload, encoding="utf-8")
        tmp.replace(index_path())


def find_item(data: dict[str, Any], item_id: str) -> dict[str, Any] | None:
    for it in data["items"]:
        if it.get("id") == item_id:
            return it
    return None


def upsert(data: dict[str, Any], item: dict[str, Any]) -> dict[str, Any]:
    existing = find_item(data, item["id"])
    if existing is None:
        data["items"].append(item)
        return item
    for key in ("name", "kind", "base", "use", "status", "do_not_redownload", "source"):
        if key in item:
            existing[key] = item[key]
    return existing


def parse_ref(ref: str) -> tuple[int, int | None]:
    raw = ref.strip()
    qver = None
    parsed = urllib.parse.urlparse(raw)
    if parsed.query:
        qs = urllib.parse.parse_qs(parsed.query)
        if qs.get("modelVersionId"):
            qver = int(qs["modelVersionId"][0])
    m = CIVITAI_URL.search(raw)
    if m:
        return int(m.group("model")), qver
    m = CIVITAI_REF.fullmatch(raw.replace(" ", ""))
    if not m:
        raise SystemExit(f"unrecognized ref: {ref!r} (want 702491@866836 or a civitai URL)")
    ver = int(m.group("version")) if m.group("version") else qver
    return int(m.group("model")), ver


def _http_get(url: str, token: str = "", timeout: int = 60) -> tuple[int, bytes, str]:
    headers = {"User-Agent": UA, "accept": "*/*"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read(), r.geturl()
    except urllib.error.HTTPError as e:
        return e.code, e.read(), url


def civitai_version(model_id: int, version_id: int | None, token: str) -> dict[str, Any]:
    if version_id:
        url = f"https://civitai.com/api/v1/model-versions/{version_id}"
        code, body, _ = _http_get(url, token)
        if code != 200:
            raise SystemExit(f"Civitai version {version_id} HTTP {code}: {body[:200]!r}")
        data = json.loads(body.decode("utf-8"))
        if int(data.get("modelId") or 0) not in (0, model_id) and data.get("modelId") != model_id:
            # Some payloads omit modelId; still accept if id matches.
            if data.get("id") != version_id:
                raise SystemExit(f"version {version_id} belongs to model {data.get('modelId')}, not {model_id}")
        return data
    url = f"https://civitai.com/api/v1/models/{model_id}"
    code, body, _ = _http_get(url, token)
    if code != 200:
        raise SystemExit(f"Civitai model {model_id} HTTP {code}: {body[:200]!r}")
    model = json.loads(body.decode("utf-8"))
    versions = model.get("modelVersions") or []
    if not versions:
        raise SystemExit(f"Civitai model {model_id} has no versions")
    return versions[0]


def primary_file(version: dict[str, Any]) -> dict[str, Any]:
    files = version.get("files") or []
    for f in files:
        if f.get("primary"):
            return f
    if not files:
        raise SystemExit("Civitai version has no files")
    return files[0]


def item_from_version(
    model_id: int,
    version: dict[str, Any],
    *,
    kind: str | None = None,
    use: list[str] | None = None,
    status: str = "probe",
) -> dict[str, Any]:
    ver_id = int(version["id"])
    mid = int(version.get("modelId") or model_id)
    f = primary_file(version)
    hashes = f.get("hashes") or {}
    size_kb = f.get("sizeKB") or 0
    filename = f.get("name") or f"model-{ver_id}.safetensors"
    model_meta = version.get("model") or {}
    name = f"{model_meta.get('name') or 'civitai'} / {version.get('name') or ver_id}"
    inferred_kind = kind or (
        "lora" if (model_meta.get("type") or "").upper() == "LORA" else "checkpoint"
    )
    return {
        "id": f"civitai:{mid}@{ver_id}",
        "name": name,
        "kind": inferred_kind,
        "base": version.get("baseModel") or "",
        "use": use or [],
        "status": status,
        "do_not_redownload": False,
        "source": {
            "host": "civitai",
            "page": f"https://civitai.com/models/{mid}?modelVersionId={ver_id}",
            "model_id": mid,
            "version_id": ver_id,
            "file_id": f.get("id"),
            "download": f.get("downloadUrl")
            or f"https://civitai.com/api/download/models/{ver_id}",
            "filename": filename,
            "sha256": hashes.get("SHA256"),
            "size_bytes": int(float(size_kb) * 1024) if size_kb else None,
            "trained_words": version.get("trainedWords") or [],
        },
    }


def local_relpath(item: dict[str, Any]) -> str:
    src = item.get("source") or {}
    fname = src.get("filename") or (item["id"].replace(":", "-").replace("@", "-") + ".safetensors")
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", fname)
    if src.get("host") == "huggingface":
        return f"hf/{safe}"
    folder = "loras" if item.get("kind") == "lora" else "checkpoints"
    stem = item["id"].replace(":", "-").replace("@", "-")
    return f"{folder}/{stem}-{safe}"


def local_path(item: dict[str, Any]) -> Path | None:
    rel = item.get("local_file")
    if not rel:
        return None
    return cache_root() / rel


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest().upper()


def download_to(url: str, dest: Path, token: str, expected_sha: str | None) -> int:
    dest.parent.mkdir(parents=True, exist_ok=True)
    headers = {"User-Agent": UA, "accept": "*/*"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
        if "civitai.com" in url.lower() and "token=" not in url:
            sep = "&" if "?" in url else "?"
            url = f"{url}{sep}token={urllib.parse.quote(token)}"
    req = urllib.request.Request(url, headers=headers)
    tmp = dest.with_suffix(dest.suffix + ".part")
    n = 0
    try:
        with urllib.request.urlopen(req, timeout=600) as r, tmp.open("wb") as out:
            while True:
                chunk = r.read(1024 * 1024)
                if not chunk:
                    break
                out.write(chunk)
                n += len(chunk)
        if expected_sha:
            got = sha256_file(tmp)
            if got != expected_sha.upper():
                tmp.unlink(missing_ok=True)
                raise SystemExit(f"sha256 mismatch for {dest.name}: got {got} want {expected_sha}")
        tmp.replace(dest)
    except urllib.error.HTTPError as e:
        tmp.unlink(missing_ok=True)
        body = e.read()[:300]
        raise SystemExit(f"download HTTP {e.code}: {body!r}") from e
    return n


def seed(data: dict[str, Any]) -> int:
    n = 0
    for item in KNOWN:
        before = find_item(data, item["id"])
        merged = upsert(data, json.loads(json.dumps(item)))
        if before is None:
            n += 1
        elif before.get("local_file"):
            merged["local_file"] = before["local_file"]
            if before.get("sha256_ok") is not None:
                merged["sha256_ok"] = before["sha256_ok"]
    save_index(data)
    return n


def should_autodownload(item: dict[str, Any], force: bool) -> bool:
    if force:
        return True
    if item.get("do_not_redownload"):
        return False
    # LoRAs are referenced by URL and loaded from it when the Comfy graph runs,
    # so there is no reason to mirror them onto this machine. Deliberate local
    # copies still go through --force. (2026-09-22)
    if item.get("kind") == "lora":
        return False
    if item.get("source", {}).get("host") != "civitai":
        return False
    size = (item.get("source") or {}).get("size_bytes")
    if size is None:
        return False
    return int(size) <= AUTO_MAX_BYTES


def fetch_item(data: dict[str, Any], item: dict[str, Any], token: str, force: bool) -> str:
    src = item.get("source") or {}
    host = str(src.get("host") or "")
    if host not in ("civitai", "huggingface"):
        return f"skip {item['id']} (not a Civitai/HF file)"
    if item.get("do_not_redownload") and not force:
        return f"skip {item['id']} (do_not_redownload)"
    dest_rel = local_relpath(item)
    dest = cache_root() / dest_rel
    if dest.is_file():
        expected = src.get("sha256")
        if expected:
            got = sha256_file(dest)
            item["local_file"] = dest_rel
            item["sha256_ok"] = got == expected.upper()
            save_index(data)
            if not item["sha256_ok"]:
                return f"hash-fail {item['id']} {dest}"
        else:
            item["local_file"] = dest_rel
            save_index(data)
        return f"have {item['id']} {dest} ({dest.stat().st_size} bytes)"
    if not should_autodownload(item, force):
        size = src.get("size_bytes")
        return f"skip {item['id']} size={size} (pass --force to download)"
    url = src.get("download")
    if not url:
        return f"skip {item['id']} (no download URL)"
    print(f"[fetch] {item['id']} -> {dest}", flush=True)
    n = download_to(url, dest, token, src.get("sha256"))
    item["local_file"] = dest_rel
    item["sha256_ok"] = True if src.get("sha256") else None
    save_index(data)
    return f"ok {item['id']} {n} bytes"


def salad_loader_name(item: dict[str, Any], token: str = "") -> str:
    """Name Salad LoraLoader / CheckpointLoaderSimple should use.

    Salad cannot see art/model-cache/. Keep the Civitai URL; the local
    file is for this machine and for baking a custom image later.
    """
    src = item.get("source") or {}
    if src.get("host") == "salad-recipe":
        return src.get("filename") or "flux1-dev-fp8.safetensors"
    url = src.get("download") or ""
    if token and url.startswith("https://civitai.com/") and "token=" not in url:
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}token={token}"
    return url


def cmd_seed(_: argparse.Namespace) -> int:
    data = load_index()
    n = seed(data)
    print(f"[seed] {index_path()} items={len(data['items'])} new={n}")
    return 0


def cmd_list(_: argparse.Namespace) -> int:
    data = load_index()
    if not data["items"]:
        print("(empty — run seed)")
        return 0
    for it in data["items"]:
        local = it.get("local_file") or "-"
        size = (it.get("source") or {}).get("size_bytes")
        flag = "NO-REDOWNLOAD" if it.get("do_not_redownload") else it.get("status")
        print(f"{it['id']:28} {it.get('kind','?'):11} {flag:16} {local} size={size}")
    return 0


def cmd_path(args: argparse.Namespace) -> int:
    data = load_index()
    it = find_item(data, args.id) or find_item(data, args.id if args.id.startswith("civitai:") else f"civitai:{args.id}")
    if it is None:
        model, ver = parse_ref(args.id)
        want = f"civitai:{model}@{ver}" if ver else None
        it = find_item(data, want) if want else None
        if it is None:
            for cand in data["items"]:
                if cand["id"].startswith(f"civitai:{model}@"):
                    it = cand
                    break
    if it is None:
        print(f"missing {args.id}", file=sys.stderr)
        return 2
    p = local_path(it)
    if p is None or not p.is_file():
        print(f"not downloaded: {it['id']}", file=sys.stderr)
        return 2
    print(p)
    return 0


def cmd_fetch(args: argparse.Namespace) -> int:
    token = civitai_token()
    data = load_index()
    seed(data)
    model_id, version_id = parse_ref(args.ref)
    existing = None
    if version_id:
        existing = find_item(data, f"civitai:{model_id}@{version_id}")
    if existing is None:
        for it in data["items"]:
            src = it.get("source") or {}
            if src.get("model_id") == model_id and (
                version_id is None or src.get("version_id") == version_id
            ):
                existing = it
                break
    if existing is None:
        version = civitai_version(model_id, version_id, token)
        existing = upsert(
            data,
            item_from_version(
                model_id,
                version,
                kind=args.kind,
                use=[u for u in (args.use or "").split(",") if u],
                status=args.status,
            ),
        )
        save_index(data)
    print(fetch_item(data, existing, token, args.force))
    return 0


def token_for_item(item: dict[str, Any]) -> str:
    host = str((item.get("source") or {}).get("host") or "")
    if host == "huggingface":
        return hf_token()
    return civitai_token()


def stage_klein_weights(data: dict[str, Any] | None = None) -> list[str]:
    """Hardlink (or copy) cached Klein HF files into salad_klein/weights/."""
    data = data if data is not None else load_index()
    KLEIN_WEIGHTS_DIR.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    for kid in KLEIN_HF_IDS:
        it = find_item(data, kid)
        if it is None:
            lines.append(f"missing {kid}")
            continue
        src = local_path(it)
        fname = str((it.get("source") or {}).get("filename") or "")
        dest = KLEIN_WEIGHTS_DIR / fname
        if src is None:
            lines.append(f"not-downloaded {kid}")
            continue
        sk = SALAD_STUDIO_HOME / "salad_klein"
        if str(sk) not in sys.path:
            sys.path.insert(0, str(sk))
        from weights_zip import is_zip_file, unzip_safetensors

        sidecar = Path(str(src) + ".zip")
        if is_zip_file(src) or src.suffix == ".zip":
            unzip_safetensors(src, dest)
            lines.append(f"unzipped {dest}")
            continue
        if not src.is_file() and sidecar.is_file():
            unzip_safetensors(sidecar, dest)
            lines.append(f"unzipped {dest}")
            continue
        if not src.is_file():
            lines.append(f"not-downloaded {kid}")
            continue
        if dest.is_file() and dest.stat().st_size == src.stat().st_size:
            lines.append(f"staged {dest}")
            continue
        dest.unlink(missing_ok=True)
        try:
            os.link(src, dest)
            lines.append(f"linked {dest}")
        except OSError:
            import shutil

            shutil.copy2(src, dest)
            lines.append(f"copied {dest}")
    return lines


def cmd_fetch_klein(args: argparse.Namespace) -> int:
    """Download the three Klein HF weights in parallel, optionally stage for Docker."""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    data = load_index()
    seed(data)
    items = []
    for kid in KLEIN_HF_IDS:
        it = find_item(data, kid)
        if it is None:
            print(f"missing {kid}", file=sys.stderr)
            return 2
        items.append(it)

    def _one(it: dict[str, Any]) -> str:
        return fetch_item(data, it, token_for_item(it), force=True)

    rc = 0
    with ThreadPoolExecutor(max_workers=3) as pool:
        futs = {pool.submit(_one, it): it["id"] for it in items}
        for fut in as_completed(futs):
            line = fut.result()
            print(line, flush=True)
            if line.startswith("hash-fail") or line.startswith("skip"):
                rc = 2
    save_index(data)
    if getattr(args, "stage", False):
        for line in stage_klein_weights(data):
            print(line, flush=True)
            if line.startswith("missing") or line.startswith("not-downloaded"):
                rc = 2
    return rc


def cmd_fetch_missing(args: argparse.Namespace) -> int:
    token = civitai_token()
    data = load_index()
    seed(data)
    rc = 0
    for it in data["items"]:
        line = fetch_item(data, it, token, args.force)
        print(line)
        if line.startswith("hash-fail"):
            rc = 2
    return rc


def cmd_verify(_: argparse.Namespace) -> int:
    data = load_index()
    rc = 0
    for it in data["items"]:
        p = local_path(it)
        expected = (it.get("source") or {}).get("sha256")
        if p is None or not p.is_file():
            continue
        if not expected:
            print(f"no-hash {it['id']} {p.stat().st_size}")
            continue
        got = sha256_file(p)
        ok = got == expected.upper()
        it["sha256_ok"] = ok
        print(("ok" if ok else "FAIL"), it["id"], p.name)
        if not ok:
            rc = 2
    save_index(data)
    return rc


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("seed", help="write known sources into the gitignored index")
    sub.add_parser("list", help="list catalog entries")
    p = sub.add_parser("path", help="print local file for an id")
    p.add_argument("id")
    p = sub.add_parser("fetch", help="register + download one Civitai ref")
    p.add_argument("ref")
    p.add_argument("--kind", choices=("lora", "checkpoint"))
    p.add_argument("--use", default="")
    p.add_argument("--status", default="probe")
    p.add_argument("--force", action="store_true")
    p = sub.add_parser("fetch-missing", help="download small Civitai files not yet local")
    p.add_argument("--force", action="store_true")
    p = sub.add_parser(
        "fetch-klein",
        help="download Klein unet/CLIP/VAE in parallel into art/model-cache",
    )
    p.add_argument(
        "--stage",
        action="store_true",
        help="hardlink/copy into $SALAD_STUDIO_HOME/salad_klein/weights/ for docker build",
    )
    sub.add_parser("verify", help="re-hash downloaded files against source sha256")

    args = ap.parse_args()
    if args.cmd == "seed":
        return cmd_seed(args)
    if args.cmd == "list":
        return cmd_list(args)
    if args.cmd == "path":
        return cmd_path(args)
    if args.cmd == "fetch":
        return cmd_fetch(args)
    if args.cmd == "fetch-missing":
        return cmd_fetch_missing(args)
    if args.cmd == "fetch-klein":
        return cmd_fetch_klein(args)
    if args.cmd == "verify":
        return cmd_verify(args)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
