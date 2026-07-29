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
NODE_TRIGGER_TOGGLE = "34"   # LoRA Manager trigger-word toggle
NODE_PROMPT_CLEANUP = "47"   # RegexReplace between the prompt concat and CLIP
NODE_MODELNAME = "49"        # WidgetToString feeding Image Saver's modelname

SEED_MIN = 0
SEED_MAX = 2**32 - 1

DEFAULT_SEPARATE_VAE = "sdxl_vae.safetensors"

# Strips a leading/trailing comma and collapses the ",," LoRA Manager emits
# between trigger-word groups, so neither reaches the CLIP encoder.
PROMPT_CLEANUP_PATTERN = r"^\s*,+\s*|\s*,+\s*$|,\s*(?=,)"

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


def _model_has_segm(model_name: str) -> bool:
    """UltralyticsDetectorProvider only returns a real SEGM_DETECTOR on slot 1
    for "segm/" models — for "bbox/" ones it returns an empty NO_SEGM_DETECTOR
    marker. Since the detector model is a user-facing dropdown that lists both,
    whether to wire segm_detector has to follow the picked model, not a fixed
    per-group flag."""
    return model_name.startswith("segm/")


def _detector_node(model_name: str) -> dict:
    return {"class_type": "UltralyticsDetectorProvider", "inputs": {"model_name": model_name}}


# (toggle_key, main_node_id, pipe_node_id, detector_node_id, widgets, wildcard, detector_model)
_ADETAILER_GROUPS = [
    ("hand_adetailer", "25", "13", "8",
     [512, True, 4096, 456186304267652, "randomize", 14, 6, "euler_ancestral", "normal", 0.4, 16, True, True,
      0.5, 8, 3, "none", 4, 0.9, 0, 0.7, "False", 16, 0.2, 1, False, 64, False, False],
     "[CONCAT] hand, perfect hands", "bbox/hand_yolov8s.pt"),
    ("nsfw_adetailer", "26", "14", "9",
     [512, True, 4096, 265140531707862, "randomize", 14, 6, "euler_ancestral", "normal", 0.3, 16, True, True,
      0.44, 8, 3, "none", 4, 0.9, 0, 0.7, "False", 16, 0.2, 1, False, 64, False, False],
     "[LAB]\n[ALL] nsfw\n[NIPPLES] nsfw, nipples\n[PUSSY] nsfw, pussy\n[ANUS] nsfw, (anus)\n[PENIS] nsfw, penis\n[TESTICLES] nsfw, testicles",
     "bbox/ntd11_anime_nsfw_segm_v5-variant1.pt"),
    ("face_adetailer", "27", "15", "10",
     [512, True, 4096, 1026130104326123, "randomize", 14, 6, "euler_ancestral", "normal", 0.26, 16, True, True,
      0.4, 8, 3, "none", 4, 0.9, 0, 0.7, "False", 16, 0.2, 1, False, 64, False, False],
     "[CONCAT] {face|face,detailed face}", "bbox/face_yolov8m.pt"),
    ("eyes_adetailer", "28", "16", "11",
     [512, True, 4096, 652548091174336, "randomize", 14, 6, "euler_ancestral", "normal", 0.24, 16, True, True,
      0.38, 8, 4, "none", 4, 0.9, 0, 0.7, "False", 16, 0.2, 1, False, 64, False, False],
     "[CONCAT] {eyes|eyes,detailed eyes}", "bbox/Eyeful_v2-Individual.pt"),
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
    # Node ids follow the editor's group titles: 82 sits in "HiresFix Pre
    # Detailer" (runs straight off the VAE decode, before the detail passes),
    # 83 in "HiresFix Post Detailer" (runs after them).
    "hiresfix_pre": [
        ("82", {
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
        ("83", {
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
        "widgets": widgets, "wildcard": wildcard, "default_model": model,
    }
    for toggle_key, main_id, pipe_id, det_id, widgets, wildcard, model in _ADETAILER_GROUPS
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
        (meta["pipe_id"], _editdetailer_node(meta["wildcard"], meta["det_id"], _model_has_segm(model)), 0),
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
        # Same order the editor's links describe: 39 -> 82 -> 24 -> 25 -> 26 ->
        # 27 -> 28 -> 83 -> 71 -> 91 -> 94 -> 92 -> 93 -> 75.
        "stages": [
            ("hiresfix_pre", "image"), ("detailer", "image"),
            ("hand_adetailer", "image"), ("nsfw_adetailer", "image"),
            ("face_adetailer", "image"), ("eyes_adetailer", "image"),
            ("hiresfix_post", "image"), ("color_match", "image_target"), ("contrast", "images"),
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
                # deepcopy, not dict(): a shallow copy would hand the graph the
                # very "inputs" dict held by the FEATURE_NODES constant, so any
                # later edit to an injected node would poison every subsequent
                # build in the process.
                node_def = copy.deepcopy(node_def)
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
            "inputs": {"vae_name": toggles.get("seperate_vae_model") or DEFAULT_SEPARATE_VAE},
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


# Every node id the builder writes to by hand, and the class_type it expects to
# find there. Everything above was transcribed from the editor export once, so a
# later edit to Standard_V37.json that renumbers or retypes a node would silently
# produce subtly wrong images rather than an error — validate_template() is the
# tripwire for exactly that.
_EXPECTED_CLASS_TYPES = {
    NODE_WIDTH: "easy int",
    NODE_HEIGHT: "easy int",
    NODE_BATCH: "easy int",
    NODE_POSITIVE: "ImpactWildcardProcessor",
    NODE_NEGATIVE: "ImpactWildcardProcessor",
    NODE_LORA: "Lora Loader (LoraManager)",
    NODE_CHECKPOINT: "CheckpointLoaderSimple",
    NODE_SEED: "Seed (rgthree)",
    NODE_PARAMS: "Input Parameters (Image Saver)",
    NODE_SAVE: "Image Saver",
    NODE_CLIP_SKIP: "CLIPSetLastLayer",
    NODE_SAMLOADER: "SAMLoader",
    NODE_TO_DETAILER_PIPE: "ToDetailerPipe",
    NODE_VAE_SWITCH: "ImpactSwitch",
    NODE_TRIGGER_TOGGLE: "TriggerWord Toggle (LoraManager)",
    NODE_PROMPT_CLEANUP: "RegexReplace",
    NODE_BBOX_CROP: "PrimitiveFloat",
}


def validate_template() -> list[str]:
    """Cross-checks the hand-transcribed node map against both workflow exports.
    Returns a list of human-readable problems; empty means the map still holds."""
    api_graph = load_template()
    ui_types = {str(n["id"]): n.get("type") for n in load_ui_template().get("nodes", [])}
    problems = []

    for node_id, class_type in _EXPECTED_CLASS_TYPES.items():
        actual = api_graph.get(node_id, {}).get("class_type")
        if actual is None:
            problems.append(f"nodo {node_id} ({class_type}) ausente en Standard_V37.api.json")
        elif actual != class_type:
            problems.append(f"nodo {node_id}: se esperaba {class_type}, el template tiene {actual}")

    # Injected nodes only have to line up with the editor export — they're
    # bypassed there, so they never appear in the API-format one.
    injected = {node_id: node["class_type"]
                for nodes in FEATURE_NODES.values() for node_id, node, _ in nodes}
    for meta in _ADETAILER_META.values():
        injected[meta["det_id"]] = "UltralyticsDetectorProvider"
        injected[meta["pipe_id"]] = "EditDetailerPipe"
        injected[meta["main_id"]] = "FaceDetailerPipe"
    injected[NODE_VAE_LOADER] = "VAELoader"

    for node_id, class_type in injected.items():
        actual = ui_types.get(node_id)
        if actual is None:
            problems.append(f"nodo inyectable {node_id} ({class_type}) ausente en Standard_V37.json")
        elif actual != class_type:
            problems.append(f"nodo inyectable {node_id}: se esperaba {class_type}, el export tiene {actual}")

    for chain in FEATURE_CHAINS:
        for consumer_id, input_key in chain["consumers"]:
            if consumer_id not in api_graph:
                problems.append(f"consumidor {consumer_id} ausente en Standard_V37.api.json")
            elif input_key not in api_graph[consumer_id]["inputs"]:
                problems.append(f"consumidor {consumer_id} no tiene input '{input_key}'")

    known_toggles = set(FEATURE_NODES) | set(_ADETAILER_META)
    for chain in FEATURE_CHAINS:
        for toggle_key, _ in chain["stages"]:
            if toggle_key not in known_toggles:
                problems.append(f"toggle '{toggle_key}' referenciado en una cadena pero sin nodos definidos")

    expected_widgets = max(i for i, _ in _FACEDETAILER_WIDGET_MAP) + 1
    for toggle_key, meta in _ADETAILER_META.items():
        if len(meta["widgets"]) < expected_widgets:
            problems.append(
                f"{toggle_key}: {len(meta['widgets'])} widgets, el mapeo necesita al menos {expected_widgets}")

    return problems


def load_ui_template() -> dict:
    """The UI-format export (nodes/links/groups). It's what Image Saver embeds in
    the PNG as `workflow`, mirroring what the ComfyUI frontend normally sends
    alongside the API-format prompt — so dragging an output back into ComfyUI
    reopens the graph that produced it."""
    with open(config.UI_WORKFLOW, "r", encoding="utf-8") as f:
        return json.load(f)


# widgets_values index of each UI-format node the builder overrides, so the
# workflow embedded in the PNG describes the run that actually happened instead
# of the template's own defaults. Purely cosmetic for reproduction — a mismatch
# here must never break a generation, hence the fail-soft in build_ui_workflow.
_UI_WIDGET_SLOTS = {
    NODE_WIDTH: {0: "width"},
    NODE_HEIGHT: {0: "height"},
    NODE_BATCH: {0: "batch_size"},
    NODE_CHECKPOINT: {0: "checkpoint"},
    NODE_POSITIVE: {0: "positive_prompt", 1: "positive_prompt"},
    NODE_NEGATIVE: {0: "negative_prompt", 1: "negative_prompt"},
    NODE_SEED: {0: "seed"},
    NODE_PARAMS: {0: "seed", 2: "steps", 3: "cfg", 4: "sampler", 5: "scheduler"},
    NODE_SAVE: {1: "path"},
    NODE_LORA: {1: "lora_text", 2: "loras"},
}


def build_ui_workflow(template: dict, params: dict, seed: int) -> dict:
    try:
        return _build_ui_workflow(template, params, seed)
    except Exception:
        return template  # embedded-workflow fidelity is never worth a failed job


def _build_ui_workflow(template: dict, params: dict, seed: int) -> dict:
    values = {
        "width": int(params["width"]),
        "height": int(params["height"]),
        "batch_size": max(1, min(config.MAX_BATCH_SIZE, int(params["batch_size"]))),
        "checkpoint": params["checkpoint"],
        "positive_prompt": params["positive_prompt"].strip(),
        "negative_prompt": params["negative_prompt"].strip(),
        "seed": seed,
        "steps": int(params["steps"]),
        "cfg": float(params["cfg"]),
        "sampler": params["sampler"],
        "scheduler": params["scheduler"],
        "path": _save_path(params),
        "loras": _lora_widget_entries(params.get("loras") or []),
        "lora_text": _lora_tag_text(params.get("loras") or []),
    }
    workflow = copy.deepcopy(template)
    for node in workflow.get("nodes", []):
        slots = _UI_WIDGET_SLOTS.get(str(node.get("id")))
        if not slots:
            continue
        widgets = node.get("widgets_values")
        if not isinstance(widgets, list):
            continue
        for index, key in slots.items():
            if index < len(widgets):
                widgets[index] = values[key]
    return workflow


def _lora_tag_text(loras: list[dict]) -> str:
    if not loras:
        return ""
    tags = [f"<lora:{l['name']}:{l['strength']:.2f}>" for l in loras]
    return ", ".join(tags) + ","


def _lora_widget_entries(loras: list[dict]) -> list[dict]:
    """The shape Lora Loader (LoraManager) reads its stack from — it ignores the
    `text` widget entirely and loads whatever is listed here."""
    return [
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


def _save_path(params: dict) -> str:
    project = (params.get("project") or "").strip()
    return project if project and project != "(root)" else ""


def build_prompt_graph(params: dict, toggles: dict | None = None) -> tuple[dict, int]:
    """Takes UI-facing generation params and returns a ready-to-submit API-format graph."""
    graph = copy.deepcopy(load_template())
    toggles = toggles or {}

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
    graph[NODE_LORA]["inputs"]["loras"] = {"__value__": _lora_widget_entries(loras)}
    graph[NODE_LORA]["inputs"]["text"] = _lora_tag_text(loras)
    # Editor leftover: an autocomplete breadcrumb naming whichever LoRA the
    # template author last typed. The loader ignores it; don't ship it.
    graph[NODE_LORA]["inputs"].pop("__lm_autocomplete_meta_text", None)

    # The template was exported with the author's own trigger-word state baked
    # into this widget. LoRA Manager only ignores it while the live
    # `trigger_words` input is non-empty, so with no LoRAs selected that stale
    # group would be prepended to every positive prompt. Start from a blank one.
    graph[NODE_TRIGGER_TOGGLE]["inputs"].update({
        "allow_strength_adjustment": False,
        "toggle_trigger_words": {"__value__": []},
        "orinalMessage": "",
    })
    graph[NODE_PROMPT_CLEANUP]["inputs"]["regex_pattern"] = PROMPT_CLEANUP_PATTERN

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

    graph[NODE_SAVE]["inputs"]["path"] = _save_path(params)

    _apply_feature_toggles(graph, toggles)
    _apply_save_metadata(graph, params)

    return graph, seed


def _apply_save_metadata(graph: dict, params: dict) -> None:
    """Image Saver writes the A1111-style parameter block Civitai and friends
    read back. Several of its fields ship as literals in the template and would
    otherwise describe the export, not this run."""
    save = graph[NODE_SAVE]["inputs"]

    # modelname came from a WidgetToString reading extra_pnginfo.workflow — a
    # static export that always names the template's own checkpoint, so every
    # image was labelled (and, via %basemodelname, *named*) after it. The real
    # value is right here; drop the indirection and the node with it.
    graph.pop(NODE_MODELNAME, None)
    save["modelname"] = params["checkpoint"]

    save["denoise"] = float(graph[NODE_PARAMS]["inputs"]["denoise"])
    clip_skip = graph.get(NODE_CLIP_SKIP)
    save["clip_skip"] = abs(int(clip_skip["inputs"]["stop_at_clip_layer"])) if clip_skip else 1
