import json
from urllib.parse import quote

from . import comfy_client


async def get_checkpoints() -> list[str]:
    info = await comfy_client.get_object_info("CheckpointLoaderSimple")
    return info["CheckpointLoaderSimple"]["input"]["required"]["ckpt_name"][0]


async def get_samplers_schedulers() -> dict:
    info = await comfy_client.get_object_info("KSampler")
    required = info["KSampler"]["input"]["required"]
    return {
        "samplers": required["sampler_name"][0],
        "schedulers": required["scheduler"][0],
    }


def _suggested_strength(usage_tips: str) -> float:
    try:
        data = json.loads(usage_tips) if usage_tips else {}
        return float(data.get("strength", 0.8))
    except (json.JSONDecodeError, TypeError, ValueError):
        return 0.8


def _preview_fields(item: dict) -> dict:
    preview_url = item.get("preview_url") or ""
    return {
        "preview_url": f"/api/library/preview?src={quote(preview_url, safe='')}" if preview_url else "",
        "preview_type": "video" if preview_url.lower().endswith((".mp4", ".webm")) else "image",
    }


async def get_loras(favorites: set[str] | None = None) -> list[dict]:
    favorites = favorites or set()
    raw_items = await comfy_client.get_lora_manager_list()
    loras = []
    for item in raw_items:
        civitai = item.get("civitai") or {}
        loras.append(
            {
                "name": item["file_name"],
                "display_name": item.get("model_name") or item["file_name"],
                "base_model": item.get("base_model") or "",
                "folder": item.get("folder") or "",
                "triggers": civitai.get("trainedWords") or [],
                "tags": item.get("tags") or [],
                **_preview_fields(item),
                "suggested_strength": _suggested_strength(item.get("usage_tips", "")),
                "favorite": item["file_name"] in favorites,
            }
        )
    return loras


async def get_checkpoint_library() -> list[dict]:
    valid_names = await get_checkpoints()
    by_basename = {}
    for name in valid_names:
        base = name.replace("\\", "/").rsplit("/", 1)[-1]
        by_basename[base.rsplit(".", 1)[0].lower()] = name

    raw_items = await comfy_client.get_model_manager_list("checkpoints")
    checkpoints = []
    for item in raw_items:
        if item.get("sub_type") != "checkpoint":
            continue
        ckpt_name = by_basename.get(item["file_name"].lower())
        if not ckpt_name:
            continue
        checkpoints.append(
            {
                "ckpt_name": ckpt_name,
                "display_name": item.get("model_name") or item["file_name"],
                "base_model": item.get("base_model") or "",
                "folder": item.get("folder") or "",
                "tags": item.get("tags") or [],
                **_preview_fields(item),
            }
        )
    return checkpoints
