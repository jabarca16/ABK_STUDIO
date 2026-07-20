import copy
import json
import random

from . import config

# Node IDs inside Workflow/Standard_V37.json — mapped by inspecting the export.
NODE_WIDTH = "1"
NODE_POSITIVE = "3"
NODE_NEGATIVE = "4"
NODE_LORA = "5"
NODE_HEIGHT = "12"
NODE_CHECKPOINT = "30"
NODE_BBOX_CROP = "31"
NODE_SEED = "32"
NODE_PARAMS = "18"       # steps / cfg / sampler / scheduler / denoise
NODE_BATCH = "29"
NODE_SAVE = "54"         # path (project subfolder) + filename pattern

NODE_CLIP_SKIP = "55"
NODE_SAMLOADER = "7"
NODE_TO_DETAILER_PIPE = "6"
NODE_VAE_LOADER = "56"
NODE_VAE_SWITCH = "40"

SEED_MIN = 0
SEED_MAX = 2**32 - 1

# ---------------------------------------------------------------------------
# Feature toggles — mirrors the two "Fast Groups Bypasser (rgthree)" nodes in
# Standard_V37.json. ComfyUI's execution engine has no concept of node
# mode/bypass (that's purely how the graph editor exports the API-format
# prompt), so re-wiring bypassed groups on the fly has to be replicated here:
# inject the group's node(s) and point whichever downstream node used to read
# straight past them at the new node's output instead.
#
# Node ids/inputs below were extracted once from Standard_V37.json (linked
# inputs use "__REF__" as a placeholder to be filled with the live upstream
# reference at build time).
# --- ADetailer group builders -----------------------------------------
# The 4 body-part detailer groups (Hand/NSFW/Face/Eyes) each need 3 nodes:
# UltralyticsDetectorProvider (bbox/segm detector) -> EditDetailerPipe (wraps
# the shared base pipe from node 6 with this group's detector + prompt) ->
# FaceDetailerPipe (does the actual detect+inpaint pass). The widget layout
# below was extracted from node id 27 (Face ADetailer, the one group already
# live in Standard_V37.api.json today) and matches the fixed field order
# FaceDetailerPipe uses across all 4 groups — only the values differ.
_FACEDETAILER_WIDGET_MAP = [
    (0, "guide_size"), (1, "guide_size_for"), (5, "steps"), (9, "denoise"), (10, "feather"),
    (11, "noise_mask"), (12, "force_inpaint"), (13, "bbox_threshold"), (14, "bbox_dilation"),
    (16, "sam_detection_hint"), (17, "sam_dilation"), (18, "sam_threshold"), (19, "sam_bbox_expansion"),
    (20, "sam_mask_hint_threshold"), (21, "sam_mask_hint_use_negative"), (22, "drop_size"),
    (23, "refiner_ratio"), (24, "cycle"), (25, "inpaint_model"), (26, "noise_mask_feather"),
]


def _facedetailer_node(widgets: list, pipe_id: str) -> dict:
    inputs = {name: widgets[i] for i, name in _FACEDETAILER_WIDGET_MAP}
    inputs.update({
        "max_size": ["19", 0], "seed": ["32", 0], "cfg": ["18", 2],
        "sampler_name": ["36", 0], "scheduler": ["35", 0], "bbox_crop_factor": ["31", 0],
        "tiled_encode": ["23", 0], "tiled_decode": ["23", 0],
        "image": "__REF__", "detailer_pipe": [pipe_id, 0],
    })
    return {"class_type": "FaceDetailerPipe", "inputs": inputs}


def _editdetailer_node(wildcard: str, detector_id: str, has_segm: bool) -> dict:
    inputs = {
        "wildcard": wildcard,
        "Select to add LoRA": "Select the LoRA to add to the text",
        "Select to add Wildcard": "Select the Wildcard to add to the text",
        "detailer_pipe": [NODE_TO_DETAILER_PIPE, 0],
        "bbox_detector": [detector_id, 0],
    }
    if has_segm:
        inputs["segm_detector"] = [detector_id, 1]
    return {"class_type": "EditDetailerPipe", "inputs": inputs}


def _detector_node(model_name: str) -> dict:
    return {"class_type": "UltralyticsDetectorProvider", "inputs": {"model_name": model_name}}


# (toggle_key, main_node_id, pipe_node_id, detector_node_id, widgets, wildcard, detector_model, has_segm)
_ADETAILER_GROUPS = [
    ("hand_adetailer", "25", "13", "8",
     [512, True, 4096, 456186304267652, "randomize", 14, 6, "euler_ancestral", "normal", 0.4, 16, True, True,
      0.5, 8, 3, "none", 4, 0.9, 0, 0.7, "False", 16, 0.2, 1, False, 64, False, False],
     "[CONCAT] hand, perfect hands", "bbox/hand_yolov8s.pt", False),
    ("nsfw_adetailer", "26", "14", "9",
     [512, True, 4096, 265140531707862, "randomize", 14, 6, "euler_ancestral", "normal", 0.3, 16, True, True,
      0.44, 8, 3, "none", 4, 0.9, 0, 0.7, "False", 16, 0.2, 1, False, 64, False, False],
     "[LAB]\n[ALL] nsfw\n[NIPPLES] nsfw, nipples\n[PUSSY] nsfw, pussy\n[ANUS] nsfw, (anus)\n[PENIS] nsfw, penis\n[TESTICLES] nsfw, testicles",
     "bbox/ntd11_anime_nsfw_segm_v5-variant1.pt", True),
    ("face_adetailer", "27", "15", "10",
     [512, True, 4096, 1026130104326123, "randomize", 14, 6, "euler_ancestral", "normal", 0.26, 16, True, True,
      0.4, 8, 3, "none", 4, 0.9, 0, 0.7, "False", 16, 0.2, 1, False, 64, False, False],
     "[CONCAT] {face|face,detailed face}", "bbox/face_yolov8m.pt", False),
    ("eyes_adetailer", "28", "16", "11",
     [512, True, 4096, 652548091174336, "randomize", 14, 6, "euler_ancestral", "normal", 0.24, 16, True, True,
      0.38, 8, 4, "none", 4, 0.9, 0, 0.7, "False", 16, 0.2, 1, False, 64, False, False],
     "[CONCAT] {eyes|eyes,detailed eyes}", "bbox/Eyeful_v2-Individual.pt", False),
]

FEATURE_NODES = {
    "color_match": [
        ("71", {
            "class_type": "ColorMatchV2",
            "inputs": {
                "method": "mkl", "strength": 1, "multithread": True,
                "image_target": "__REF__", "image_ref": ["39", 0],
            },
        }, 0),
    ],
    "hiresfix_pre": [
        ("83", {
            "class_type": "easy hiresFix",
            "inputs": {
                "model_name": "4x_foolhardy_Remacri.pth", "rescale_after_model": True,
                "rescale_method": "lanczos", "rescale": "by percentage", "percent": 50,
                "width": 1024, "height": 1024, "longer_side": 1024, "crop": "disabled",
                "image_output": "Hide", "link_id": 0, "save_prefix": "ComfyUI",
                "image": "__REF__", "vae": ["40", 0],
            },
        }, 1),  # easy hiresFix outputs: [0]=pipe, [1]=image, [2]=latent
    ],
    "hiresfix_post": [
        ("82", {
            "class_type": "easy hiresFix",
            "inputs": {
                "model_name": "4x_foolhardy_Remacri.pth", "rescale_after_model": True,
                "rescale_method": "lanczos", "rescale": "by percentage", "percent": 50,
                "width": 1024, "height": 1024, "longer_side": 1024, "crop": "disabled",
                "image_output": "Hide", "link_id": 0, "save_prefix": "ComfyUI",
                "image": "__REF__", "vae": ["40", 0],
            },
        }, 1),
    ],
    "detailer": [
        ("21", {"class_type": "SolidMask", "inputs": {"value": 1, "width": ["1", 0], "height": ["12", 0]}}, 0),
        ("22", {
            "class_type": "MaskToSEGS",
            "inputs": {"mask": ["21", 0], "combined": False, "crop_factor": 1, "bbox_fill": False,
                       "drop_size": 10, "contour_fill": False},
        }, 0),
        ("24", {
            "class_type": "DetailerForEach",
            "inputs": {
                "image": "__REF__", "segs": ["22", 0], "model": ["41", 0], "clip": ["5", 1], "vae": ["40", 0],
                "guide_size": 512, "guide_size_for": True, "max_size": ["19", 0], "seed": ["32", 0], "steps": 18,
                "cfg": ["18", 2], "sampler_name": "euler_ancestral", "scheduler": "normal",
                "positive": ["43", 0], "negative": ["44", 0], "denoise": 0.25, "feather": 6,
                "noise_mask": True, "force_inpaint": True, "wildcard": "", "cycle": 1,
                "inpaint_model": False, "noise_mask_feather": 64,
                "tiled_encode": ["23", 0], "tiled_decode": ["23", 0],
            },
        }, 0),
    ],
    "epsilon_scaling": [
        ("60", {
            "class_type": "Epsilon Scaling",
            "inputs": {"scaling_factor": 1.005, "model": "__REF__"},
        }, 0),
    ],
    "cfg_zero_star": [
        ("69", {"class_type": "CFGZeroStar", "inputs": {"model": "__REF__"}}, 0),
    ],
    "vpred_model": [
        ("61", {
            "class_type": "ModelSamplingDiscrete",
            "inputs": {"sampling": "v_prediction", "zsnr": True, "model": "__REF__"},
        }, 0),
        ("68", {"class_type": "Mahiro", "inputs": {"model": "__REF__"}}, 0),
    ],
    "contrast": [
        ("91", {"class_type": "AdjustContrast", "inputs": {"factor": 1.1, "images": "__REF__"}}, 0),
    ],
    "image_morphology": [
        ("94", {
            "class_type": "Morphology",
            "inputs": {"operation": "erode", "kernel_size": 3, "image": "__REF__"},
        }, 0),
    ],
    "image_quantize": [
        ("92", {
            "class_type": "ImageQuantize",
            "inputs": {"colors": 256, "dither": "none", "image": "__REF__"},
        }, 0),
    ],
    "image_sharpen": [
        ("93", {
            "class_type": "ImageSharpen",
            "inputs": {"sharpen_radius": 1, "sigma": 0.5, "alpha": 0.5, "image": "__REF__"},
        }, 0),
    ],
}

# ADetailer groups aren't pre-baked into FEATURE_NODES like the rest — their
# detector model_name is user-selectable (a settings dropdown, since which
# .pt files are actually installed varies per machine), so their 3 nodes get
# built on demand in _apply_feature_toggles using whatever model the current
# settings picked.
_ADETAILER_META = {
    toggle_key: {
        "main_id": main_id, "pipe_id": pipe_id, "det_id": det_id,
        "widgets": widgets, "wildcard": wildcard, "default_model": model, "has_segm": has_segm,
    }
    for toggle_key, main_id, pipe_id, det_id, widgets, wildcard, model, has_segm in _ADETAILER_GROUPS
}

DETECTOR_MODEL_SETTING_KEYS = {key: f"{key}_model" for key in _ADETAILER_META}
DETECTOR_MODEL_DEFAULTS = {
    f"{key}_model": meta["default_model"] for key, meta in _ADETAILER_META.items()
}


def _build_adetailer_nodes(toggle_key: str, toggles: dict) -> list:
    meta = _ADETAILER_META[toggle_key]
    model = toggles.get(DETECTOR_MODEL_SETTING_KEYS[toggle_key]) or meta["default_model"]
    return [
        (meta["det_id"], _detector_node(model), 0),
        (meta["pipe_id"], _editdetailer_node(meta["wildcard"], meta["det_id"], meta["has_segm"]), 0),
        (meta["main_id"], _facedetailer_node(meta["widgets"], meta["pipe_id"]), 0),
    ]

# Serial chains: each stage feeds the next via the given input key. The final
# enabled stage's output (or the chain's own source if none are enabled) is
# written into `final_consumer`'s `final_input_key`.
FEATURE_CHAINS = [
    {
        "source": ["5", 0],  # Lora Loader MODEL output
        "stages": [("epsilon_scaling", "model"), ("cfg_zero_star", "model"), ("vpred_model", "model")],
        "consumers": [("41", "model"), ("46", "model")],
    },
    {
        "source": ["39", 0],  # VAEDecode output image
        "stages": [
            ("hiresfix_post", "image"), ("detailer", "image"),
            ("hand_adetailer", "image"), ("nsfw_adetailer", "image"),
            ("face_adetailer", "image"), ("eyes_adetailer", "image"),
            ("hiresfix_pre", "image"), ("color_match", "image_target"), ("contrast", "images"),
            ("image_morphology", "image"), ("image_quantize", "image"), ("image_sharpen", "image"),
        ],
        "consumers": [("75", "input1")],
    },
]

# Every node id any toggle can inject — reset to a clean slate before each
# build so groups baked into the base template by default (Face ADetailer,
# CLIP Skip, Use SAMLoader) behave identically to freshly-injected ones.
_ALL_CHAIN_NODE_IDS = [node_id for nodes in FEATURE_NODES.values() for node_id, _, _ in nodes] + [
    node_id for meta in _ADETAILER_META.values() for node_id in (meta["det_id"], meta["pipe_id"], meta["main_id"])
]

# Debug-only "Image Comparer (rgthree)" nodes that sit next to each ADetailer
# group in the editor — they have no downstream consumers (pure UI preview),
# but Face ADetailer's (64) is baked into the base template by default, so it
# must be stripped too or it dangles once node 27 gets reset/re-injected.
_DEBUG_COMPARER_NODE_IDS = ["58", "62", "63", "64", "65"]


def _inject_ref(inputs: dict, ref) -> dict:
    return {k: (ref if v == "__REF__" else v) for k, v in inputs.items()}


def _apply_feature_toggles(graph: dict, toggles: dict) -> None:
    # CLIP Skip and Use SAMLoader are active by default in the template —
    # disabling them means removing the node and rerouting its consumer.
    if not toggles.get("clip_skip", True):
        graph.pop(NODE_CLIP_SKIP, None)
        graph[NODE_LORA]["inputs"]["clip"] = ["30", 1]

    if not toggles.get("use_samloader", True):
        graph.pop(NODE_SAMLOADER, None)
        graph[NODE_TO_DETAILER_PIPE]["inputs"].pop("sam_model_opt", None)

    for node_id in _ALL_CHAIN_NODE_IDS:
        graph.pop(node_id, None)
    for node_id in _DEBUG_COMPARER_NODE_IDS:
        graph.pop(node_id, None)

    for chain in FEATURE_CHAINS:
        ref = chain["source"]
        for toggle_key, input_key in chain["stages"]:
            if not toggles.get(toggle_key):
                continue
            stage_nodes = _build_adetailer_nodes(toggle_key, toggles) if toggle_key in _ADETAILER_META \
                else FEATURE_NODES[toggle_key]
            for node_id, node_def, output_slot in stage_nodes:
                node_def = dict(node_def)
                has_ref = "__REF__" in node_def["inputs"].values()
                if has_ref:
                    node_def["inputs"] = _inject_ref(node_def["inputs"], ref)
                graph[node_id] = node_def
                # Helper nodes with no __REF__ (detectors, edit-pipes, mask
                # builders) don't represent the stage's image/model output —
                # only advance the threaded ref past nodes that consumed it.
                if has_ref:
                    ref = [node_id, output_slot]
        for consumer_id, input_key in chain["consumers"]:
            graph[consumer_id]["inputs"][input_key] = ref
            # node 75's template ships a redundant "input2" fallback (unused —
            # select is always 1) that can dangle once its default source
            # (Face ADetailer, node 27) gets toggled off. Drop it; ComfyUI
            # validates connected refs even on branches select won't pick.
            graph[consumer_id]["inputs"].pop("input2", None)

    # Seperate VAE isn't a reroute — an ImpactSwitch already selects between
    # the checkpoint's own VAE (select=1) and a standalone VAELoader (select=2).
    if toggles.get("seperate_vae"):
        graph[NODE_VAE_LOADER] = {
            "class_type": "VAELoader",
            "inputs": {"vae_name": "sdxl_vae.safetensors"},
        }
        graph[NODE_VAE_SWITCH]["inputs"]["select"] = 2
        graph[NODE_VAE_SWITCH]["inputs"]["input2"] = [NODE_VAE_LOADER, 0]
    else:
        graph.pop(NODE_VAE_LOADER, None)
        graph[NODE_VAE_SWITCH]["inputs"]["select"] = 1
        graph[NODE_VAE_SWITCH]["inputs"].pop("input2", None)


def load_template() -> dict:
    with open(config.DEFAULT_WORKFLOW, "r", encoding="utf-8") as f:
        return json.load(f)


def load_ui_template() -> dict:
    """The UI-format export (nodes/links/groups) — some custom nodes (e.g. KJNodes'
    WidgetToString) read extra_pnginfo.workflow at execution time, mirroring what the
    ComfyUI frontend normally sends alongside the API-format prompt."""
    ui_path = config.WORKFLOW_DIR / "Standard_V37.json"
    with open(ui_path, "r", encoding="utf-8") as f:
        return json.load(f)


def _lora_tag_text(loras: list[dict]) -> str:
    if not loras:
        return ""
    tags = [f"<lora:{l['name']}:{l['strength']:.2f}>" for l in loras]
    return ", ".join(tags) + ","


def build_prompt_graph(params: dict, toggles: dict | None = None) -> dict:
    """Takes UI-facing generation params and returns a ready-to-submit API-format graph."""
    graph = copy.deepcopy(load_template())

    graph[NODE_WIDTH]["inputs"]["value"] = int(params["width"])
    graph[NODE_HEIGHT]["inputs"]["value"] = int(params["height"])
    graph[NODE_BATCH]["inputs"]["value"] = max(1, min(config.MAX_BATCH_SIZE, int(params["batch_size"])))

    positive_text = params["positive_prompt"].strip()
    graph[NODE_POSITIVE]["inputs"]["wildcard_text"] = positive_text
    graph[NODE_POSITIVE]["inputs"]["populated_text"] = positive_text

    negative_text = params["negative_prompt"].strip()
    graph[NODE_NEGATIVE]["inputs"]["wildcard_text"] = negative_text
    graph[NODE_NEGATIVE]["inputs"]["populated_text"] = negative_text

    loras = params.get("loras") or []
    graph[NODE_LORA]["inputs"]["loras"] = {
        "__value__": [
            {
                "name": l["name"],
                "strength": l["strength"],
                "active": True,
                "expanded": False,
                "clipStrength": l["strength"],
                "locked": False,
            }
            for l in loras
        ]
    }
    graph[NODE_LORA]["inputs"]["text"] = _lora_tag_text(loras)

    seed = int(params["seed"])
    if seed < 0:
        seed = random.randint(SEED_MIN, SEED_MAX)
    graph[NODE_SEED]["inputs"]["seed"] = seed

    graph[NODE_CHECKPOINT]["inputs"]["ckpt_name"] = params["checkpoint"]

    p = graph[NODE_PARAMS]["inputs"]
    p["steps"] = int(params["steps"])
    p["cfg"] = float(params["cfg"])
    p["sampler"] = params["sampler"]
    p["scheduler"] = params["scheduler"]

    project = (params.get("project") or "").strip()
    if project and project != "(root)":
        graph[NODE_SAVE]["inputs"]["path"] = project
    else:
        graph[NODE_SAVE]["inputs"]["path"] = ""

    _apply_feature_toggles(graph, toggles or {})

    return graph, seed
