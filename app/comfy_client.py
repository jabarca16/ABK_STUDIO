import json

import httpx
import websockets

from . import config


async def queue_prompt(graph: dict, client_id: str, ui_workflow: dict | None = None) -> dict:
    payload = {"prompt": graph, "client_id": client_id}
    if ui_workflow is not None:
        payload["extra_data"] = {"extra_pnginfo": {"workflow": ui_workflow}}
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(f"{config.COMFY_BASE_URL}/prompt", json=payload)
        resp.raise_for_status()
        return resp.json()


async def get_history(prompt_id: str) -> dict:
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(f"{config.COMFY_BASE_URL}/history/{prompt_id}")
        resp.raise_for_status()
        return resp.json()


async def get_queue() -> dict:
    async with httpx.AsyncClient(timeout=5) as client:
        resp = await client.get(f"{config.COMFY_BASE_URL}/queue")
        resp.raise_for_status()
        return resp.json()


async def get_object_info(node_class: str) -> dict:
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(f"{config.COMFY_BASE_URL}/object_info/{node_class}")
        resp.raise_for_status()
        return resp.json()


async def get_model_manager_list(kind: str, page_size: int = 500) -> list[dict]:
    items: list[dict] = []
    page = 1
    async with httpx.AsyncClient(timeout=30) as client:
        while True:
            resp = await client.get(
                f"{config.COMFY_BASE_URL}/api/lm/{kind}/list",
                params={"page": page, "page_size": page_size},
            )
            resp.raise_for_status()
            data = resp.json()
            items.extend(data.get("items", []))
            if page >= data.get("total_pages", 1):
                break
            page += 1
    return items


async def get_lora_manager_list(page_size: int = 500) -> list[dict]:
    return await get_model_manager_list("loras", page_size)


async def get_preview_bytes(relative_path: str) -> tuple[bytes, str]:
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(f"{config.COMFY_BASE_URL}{relative_path}")
        resp.raise_for_status()
        return resp.content, resp.headers.get("content-type", "application/octet-stream")


async def subscribe_logs(client_id: str, enabled: bool) -> None:
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.patch(
            f"{config.COMFY_BASE_URL}/internal/logs/subscribe",
            json={"clientId": client_id, "enabled": enabled},
        )
        resp.raise_for_status()


async def stream_log_lines(client_id: str):
    """Yields raw ComfyUI console log lines for this client_id until the socket closes."""
    ws_url = f"ws://{config.COMFY_HOST}:{config.COMFY_PORT}/ws?clientId={client_id}"
    await subscribe_logs(client_id, True)
    try:
        async with websockets.connect(ws_url, open_timeout=10) as ws:
            async for raw in ws:
                if isinstance(raw, bytes):
                    continue  # binary preview frames, not log messages
                try:
                    msg = json.loads(raw)
                except ValueError:
                    continue
                if msg.get("type") != "logs":
                    continue
                for entry in msg.get("data", {}).get("entries", []):
                    line = entry.get("m", "").strip()
                    if line:
                        yield line
    finally:
        try:
            await subscribe_logs(client_id, False)
        except Exception:
            pass


def extract_output_images(history_entry: dict) -> list[str]:
    """Pulls relative output paths (subfolder/filename) from a /history/{id} outputs block."""
    paths = []
    outputs = history_entry.get("outputs", {})
    for node_output in outputs.values():
        for img in node_output.get("images", []):
            if img.get("type") != "output":
                continue
            subfolder = img.get("subfolder", "")
            filename = img["filename"]
            rel = f"{subfolder}/{filename}" if subfolder else filename
            paths.append(rel)
    return paths
