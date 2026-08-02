import base64
import io
import shutil
import uuid
import zipfile

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from .. import comfy_client, config
from . import db as rig_db
from . import workflow_builder as rig_wf
from .schemas import (
    ApproveBaseRequest,
    GenerateBaseRequest,
    GenerateLayerRequest,
    LayerPatchRequest,
    MaskUploadRequest,
    NewCharacterProjectRequest,
    NewLayerRequest,
)

router = APIRouter(prefix="/api/character-rig", tags=["character-rig"])


def _input_filename(project_id: str, suffix: str) -> str:
    return f"rigprep_{project_id}_{suffix}.png"


def _write_bytes_to_input(data: bytes, filename: str) -> None:
    config.COMFY_INPUT_DIR.mkdir(parents=True, exist_ok=True)
    (config.COMFY_INPUT_DIR / filename).write_bytes(data)


def _copy_output_to_input(output_relative_path: str, input_filename: str) -> None:
    src = config.COMFY_OUTPUT_DIR / output_relative_path
    _write_bytes_to_input(src.read_bytes(), input_filename)


def _decode_mask_base64(data_url: str) -> bytes:
    # accepts either a raw base64 string or a "data:image/png;base64,...." URL
    if "," in data_url and data_url.strip().startswith("data:"):
        data_url = data_url.split(",", 1)[1]
    return base64.b64decode(data_url)


async def _extract_node_image(prompt_id: str, node_id: str | None) -> str | None:
    """node_id=None scans every output node for the first one with images —
    needed because the two layer-extraction graphs (simple crop vs
    occlusion fill) name their save node differently ("5" vs "save"), and
    each graph only ever has one image-producing node anyway."""
    history = await comfy_client.get_history(prompt_id)
    entry = history.get(prompt_id)
    if not entry or not entry.get("status", {}).get("completed"):
        return None
    outputs = entry.get("outputs", {})
    if node_id is not None:
        images = outputs.get(node_id, {}).get("images", [])
    else:
        images = next((o["images"] for o in outputs.values() if o.get("images")), [])
    if not images:
        return None
    img = images[0]
    subfolder = img.get("subfolder", "")
    filename = img["filename"]
    return f"{subfolder}/{filename}" if subfolder else filename


# ---------- projects ----------

@router.post("/projects")
def create_project(req: NewCharacterProjectRequest):
    project_id = str(uuid.uuid4())
    rig_db.create_project({
        "id": project_id, "name": req.name, "art_style": req.art_style,
        "description": req.description, "pose": req.pose, "palette_hex": req.palette_hex,
        "checkpoint": req.checkpoint, "seed": req.seed,
    })
    return rig_db.get_project(project_id)


@router.get("/projects")
def list_projects():
    return rig_db.list_projects()


@router.get("/projects/{project_id}")
def get_project(project_id: str):
    project = rig_db.get_project(project_id)
    if not project:
        raise HTTPException(404, "Proyecto no encontrado")
    project["base_iterations"] = rig_db.list_base_iterations(project_id)
    project["layers"] = rig_db.list_layers(project_id)
    return project


# ---------- base image (Fase 1) ----------

@router.post("/projects/{project_id}/generate-base")
async def generate_base(project_id: str, req: GenerateBaseRequest):
    project = rig_db.get_project(project_id)
    if not project:
        raise HTTPException(404, "Proyecto no encontrado")

    seed = req.seed if req.seed >= 0 else uuid.uuid4().int % (2**32)
    iteration_id = str(uuid.uuid4())
    output_prefix = f"character_rig/{project_id}/base/{iteration_id}"
    graph = rig_wf.build_character_base_graph(
        {
            "checkpoint": req.checkpoint, "positive_prompt": req.positive_prompt,
            "negative_prompt": req.negative_prompt, "seed": seed,
            "width": req.width, "height": req.height,
        },
        output_prefix,
    )
    client_id = str(uuid.uuid4())
    try:
        result = await comfy_client.queue_prompt(graph, client_id)
    except Exception as exc:
        raise HTTPException(502, f"ComfyUI rechazó el job: {exc}")

    prompt_id = result.get("prompt_id")
    if not prompt_id:
        raise HTTPException(502, f"Respuesta inesperada de ComfyUI: {result}")

    rig_db.insert_base_iteration(
        {"id": iteration_id, "project_id": project_id, "prompt_id": prompt_id, "seed": seed, "status": "queued"}
    )
    return {"iteration_id": iteration_id, "prompt_id": prompt_id, "seed": seed}


@router.get("/projects/{project_id}/base-iterations/{iteration_id}/status")
async def base_iteration_status(project_id: str, iteration_id: str):
    iteration = rig_db.get_base_iteration(iteration_id)
    if not iteration:
        raise HTTPException(404, "Iteración no encontrada")
    if iteration["status"] == "done":
        return iteration

    image_path = await _extract_node_image(iteration["prompt_id"], "7")
    if image_path is None:
        history = await comfy_client.get_history(iteration["prompt_id"])
        entry = history.get(iteration["prompt_id"])
        if entry and entry.get("status", {}).get("status_str") == "error":
            rig_db.update_base_iteration(iteration_id, "error")
        return rig_db.get_base_iteration(iteration_id)

    rig_db.update_base_iteration(iteration_id, "done", image_path)
    return rig_db.get_base_iteration(iteration_id)


@router.post("/projects/{project_id}/approve-base")
async def approve_base(project_id: str, req: ApproveBaseRequest):
    project = rig_db.get_project(project_id)
    if not project:
        raise HTTPException(404, "Proyecto no encontrado")

    _copy_output_to_input(req.iteration_image_path, _input_filename(project_id, "base"))
    rig_db.approve_base(
        project_id, req.iteration_image_path, project["seed"] or 0,
        {"checkpoint": project["checkpoint"]},
    )

    seg_output_prefix = f"character_rig/{project_id}/masks"
    graph = rig_wf.build_human_parts_segment_graph(
        _input_filename(project_id, "base"), seg_output_prefix
    )
    client_id = str(uuid.uuid4())
    try:
        result = await comfy_client.queue_prompt(graph, client_id)
    except Exception as exc:
        raise HTTPException(502, f"ComfyUI rechazó la segmentación: {exc}")
    seg_prompt_id = result.get("prompt_id")
    if not seg_prompt_id:
        raise HTTPException(502, f"Respuesta inesperada de ComfyUI: {result}")

    # Idempotent: approving again (retry after a ComfyUI-side error, e.g. a
    # missing model file) must re-run segmentation on the *same* 12 layer
    # rows, not create a second set of them.
    existing_by_part = {l["part_key"]: l for l in rig_db.list_layers(project_id)}
    for i, part_key in enumerate(rig_wf.PART_KEYS):
        existing = existing_by_part.get(part_key)
        layer_id = existing["id"] if existing else str(uuid.uuid4())
        if not existing:
            rig_db.create_layer({
                "id": layer_id, "project_id": project_id, "part_key": part_key,
                "display_name": rig_wf.PART_DISPLAY_NAMES[part_key], "order_index": i,
                "status": "pendiente",
            })
        else:
            rig_db.reset_layer_for_resegment(layer_id)
        rig_db.update_layer_job(layer_id, seg_prompt_id, "running")

    return {"project": rig_db.get_project(project_id), "segmentation_prompt_id": seg_prompt_id}


@router.get("/projects/{project_id}/segmentation-status")
async def segmentation_status(project_id: str, prompt_id: str):
    layers = rig_db.list_layers(project_id)
    pending = [l for l in layers if l["prompt_id"] == prompt_id and l["status"] == "pendiente"]
    if not pending:
        return {"done": True, "layers": layers}

    history = await comfy_client.get_history(prompt_id)
    entry = history.get(prompt_id)
    if not entry or not entry.get("status", {}).get("completed"):
        if entry and entry.get("status", {}).get("status_str") == "error":
            for layer in pending:
                rig_db.update_layer_job(layer["id"], prompt_id, "error")
            return {"done": True, "layers": rig_db.list_layers(project_id)}
        return {"done": False, "layers": layers}

    for layer in pending:
        node_id = f"save_{layer['part_key']}"
        node_out = entry.get("outputs", {}).get(node_id, {})
        images = node_out.get("images", [])
        if not images:
            continue
        img = images[0]
        subfolder = img.get("subfolder", "")
        rel_path = f"{subfolder}/{img['filename']}" if subfolder else img["filename"]
        rig_db.set_layer_proposed_mask(layer["id"], rel_path)
        _copy_output_to_input(rel_path, _input_filename(project_id, layer["part_key"]))

    return {"done": True, "layers": rig_db.list_layers(project_id)}


# ---------- layers (Fase 2 / 3) ----------

@router.post("/projects/{project_id}/layers")
def add_custom_layer(project_id: str, req: NewLayerRequest):
    project = rig_db.get_project(project_id)
    if not project:
        raise HTTPException(404, "Proyecto no encontrado")
    existing = rig_db.list_layers(project_id)
    layer_id = str(uuid.uuid4())
    rig_db.create_layer({
        "id": layer_id, "project_id": project_id, "part_key": req.part_key,
        "display_name": req.display_name, "order_index": len(existing), "status": "pendiente",
    })
    return rig_db.get_layer(layer_id)


@router.put("/projects/{project_id}/layers/{layer_id}/mask")
def upload_layer_mask(project_id: str, layer_id: str, req: MaskUploadRequest):
    layer = rig_db.get_layer(layer_id)
    if not layer or layer["project_id"] != project_id:
        raise HTTPException(404, "Capa no encontrada")

    mask_bytes = _decode_mask_base64(req.mask_png_base64)
    _write_bytes_to_input(mask_bytes, _input_filename(project_id, layer["part_key"]))

    preview_dir = config.COMFY_OUTPUT_DIR / "character_rig" / project_id / "masks"
    preview_dir.mkdir(parents=True, exist_ok=True)
    preview_name = f"{layer['part_key']}_corrected.png"
    (preview_dir / preview_name).write_bytes(mask_bytes)
    rig_db.update_layer_mask(layer_id, f"character_rig/{project_id}/masks/{preview_name}")
    return rig_db.get_layer(layer_id)


@router.post("/projects/{project_id}/layers/{layer_id}/generate")
async def generate_layer(project_id: str, layer_id: str, req: GenerateLayerRequest):
    project = rig_db.get_project(project_id)
    layer = rig_db.get_layer(layer_id)
    if not project or not layer or layer["project_id"] != project_id:
        raise HTTPException(404, "Proyecto o capa no encontrada")
    if not layer["mask_path"]:
        raise HTTPException(400, "Esta capa todavía no tiene máscara")

    output_prefix = f"character_rig/{project_id}/layers/{layer['part_key']}"
    graph = rig_wf.build_part_extract_graph(
        _input_filename(project_id, "base"),
        _input_filename(project_id, layer["part_key"]),
        output_prefix,
    )
    client_id = str(uuid.uuid4())
    try:
        result = await comfy_client.queue_prompt(graph, client_id)
    except Exception as exc:
        raise HTTPException(502, f"ComfyUI rechazó el job: {exc}")
    prompt_id = result.get("prompt_id")
    if not prompt_id:
        raise HTTPException(502, f"Respuesta inesperada de ComfyUI: {result}")

    rig_db.update_layer_job(layer_id, prompt_id, "running")
    return rig_db.get_layer(layer_id)


@router.post("/projects/{project_id}/layers/{layer_id}/generate-occluded")
async def generate_layer_occluded(project_id: str, layer_id: str):
    """Fase 3b: like /generate, but fills the region of this part hidden
    behind higher-stacked parts instead of leaving it transparent — see
    plan §1. Which parts are "higher" comes straight from order_index, so
    this is only meaningful once layers have been reordered to reflect real
    stacking (front-to-back), not just the creation order."""
    project = rig_db.get_project(project_id)
    layer = rig_db.get_layer(layer_id)
    if not project or not layer or layer["project_id"] != project_id:
        raise HTTPException(404, "Proyecto o capa no encontrada")
    if not layer["mask_path"]:
        raise HTTPException(400, "Esta capa todavía no tiene máscara")

    occluders = [
        l for l in rig_db.list_layers(project_id)
        if l["id"] != layer_id and l["mask_path"] and l["order_index"] > layer["order_index"]
    ]
    if not occluders:
        raise HTTPException(
            400,
            "Ninguna capa está por encima de esta en el orden — no hay nada que ocluya. "
            "Reordená las capas o usá 'Generar capa' (recorte simple) en su lugar.",
        )

    output_prefix = f"character_rig/{project_id}/layers/{layer['part_key']}"
    positive_prompt = ", ".join(
        p for p in [project["description"], project["art_style"], project["pose"]] if p
    )
    graph = rig_wf.build_part_extract_occluded_graph(
        _input_filename(project_id, "base"),
        _input_filename(project_id, layer["part_key"]),
        [_input_filename(project_id, o["part_key"]) for o in occluders],
        project["checkpoint"],
        positive_prompt,
        output_prefix,
        seed=(project["seed"] or 0),
    )
    client_id = str(uuid.uuid4())
    try:
        result = await comfy_client.queue_prompt(graph, client_id)
    except Exception as exc:
        raise HTTPException(502, f"ComfyUI rechazó el job: {exc}")
    prompt_id = result.get("prompt_id")
    if not prompt_id:
        raise HTTPException(502, f"Respuesta inesperada de ComfyUI: {result}")

    rig_db.update_layer_job(layer_id, prompt_id, "running")
    return rig_db.get_layer(layer_id)


@router.get("/projects/{project_id}/layers/{layer_id}/status")
async def layer_status(project_id: str, layer_id: str):
    layer = rig_db.get_layer(layer_id)
    if not layer or layer["project_id"] != project_id:
        raise HTTPException(404, "Capa no encontrada")
    if layer["job_status"] == "done" or not layer["prompt_id"]:
        return layer

    image_path = await _extract_node_image(layer["prompt_id"], None)
    if image_path is None:
        history = await comfy_client.get_history(layer["prompt_id"])
        entry = history.get(layer["prompt_id"])
        if entry and entry.get("status", {}).get("status_str") == "error":
            rig_db.update_layer_result(layer_id, "error")
        return rig_db.get_layer(layer_id)

    rig_db.update_layer_result(layer_id, "done", image_path)
    return rig_db.get_layer(layer_id)


@router.patch("/projects/{project_id}/layers/{layer_id}")
def patch_layer(project_id: str, layer_id: str, req: LayerPatchRequest):
    layer = rig_db.get_layer(layer_id)
    if not layer or layer["project_id"] != project_id:
        raise HTTPException(404, "Capa no encontrada")
    rig_db.patch_layer(layer_id, req.display_name, req.order_index)
    return rig_db.get_layer(layer_id)


@router.delete("/projects/{project_id}/layers/{layer_id}")
def delete_layer(project_id: str, layer_id: str):
    layer = rig_db.get_layer(layer_id)
    if not layer or layer["project_id"] != project_id:
        raise HTTPException(404, "Capa no encontrada")
    rig_db.delete_layer(layer_id)
    return {"deleted": True}


# ---------- export (Fase 4) ----------

def _safe_filename(name: str) -> str:
    cleaned = "".join(c for c in name if c.isalnum() or c in "-_")
    return cleaned or "character"


@router.get("/projects/{project_id}/export")
def export_project(project_id: str):
    """Zips every generated layer (order_index zero-padded into the filename
    so a plain file browser sorts them back-to-front correctly) plus the
    approved base image for reference and a manifest.txt. Deliberately just
    a folder-of-PNGs export, not a multi-layer PSD — no new dependency
    (psd-tools) was added for this; drag the PNGs into Live2D/Spine by hand
    in that order. See plan §13/§10 if a one-click PSD import is wanted later."""
    project = rig_db.get_project(project_id)
    if not project:
        raise HTTPException(404, "Proyecto no encontrado")

    layers = [l for l in rig_db.list_layers(project_id) if l["image_path"]]
    if not layers:
        raise HTTPException(400, "Todavía no hay ninguna capa generada para exportar")
    layers.sort(key=lambda l: l["order_index"])

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        if project["base_image_path"]:
            base_path = config.COMFY_OUTPUT_DIR / project["base_image_path"]
            if base_path.exists():
                zf.write(base_path, "00_reference_base.png")

        manifest = [
            f"Character Rig Prep — export de '{project['name']}'",
            "",
            "Orden de atrás/abajo hacia adelante/arriba (mismo canvas, ya alineadas):",
            "",
        ]
        for layer in layers:
            src = config.COMFY_OUTPUT_DIR / layer["image_path"]
            if not src.exists():
                continue
            filename = f"{layer['order_index']:02d}_{layer['part_key']}.png"
            zf.write(src, filename)
            manifest.append(f"  {filename}  —  {layer['display_name']}")
        zf.writestr("manifest.txt", "\n".join(manifest))

    buf.seek(0)
    filename = f"{_safe_filename(project['name'])}_layers.zip"
    return StreamingResponse(
        buf, media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
