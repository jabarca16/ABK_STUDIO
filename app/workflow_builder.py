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

SEED_MIN = 0
SEED_MAX = 2**32 - 1


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


def build_prompt_graph(params: dict) -> dict:
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

    return graph, seed
