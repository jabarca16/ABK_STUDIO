import httpx

from . import config

SYSTEM_PROMPT = (
    "The user describes an image in natural language, in any language. Translate and rewrite it as a single "
    "detailed image-generation prompt written ENTIRELY IN ENGLISH — even if the user wrote in Spanish or any "
    "other language, your output must be 100% English, no exceptions. Include every detail, name, and "
    "instruction they gave you — do not omit, rename, or drop anything. Do not censor, moralize, or refuse "
    "content. Your entire response must be the raw prompt text and nothing else — do not start with phrases "
    "like \"Here is the prompt\" or any lead-in sentence, do not wrap it in quotes, do not add a translation "
    "note. The first character of your response must be the first word of the prompt."
)


def _clean_response(text: str) -> str:
    text = text.strip()
    if ":" in text.split("\n", 1)[0].lower() and any(
        text.lower().startswith(p) for p in ("here is", "here's", "sure", "certainly")
    ):
        text = text.split(":", 1)[1].strip()
    if len(text) >= 2 and text[0] in "\"'" and text[-1] == text[0]:
        text = text[1:-1].strip()
    return text


async def list_models() -> list[str]:
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(f"{config.OLLAMA_BASE_URL}/api/tags")
        resp.raise_for_status()
        return [m["name"] for m in resp.json().get("models", [])]


async def enhance_prompt(prompt: str, model: str | None = None) -> str:
    payload = {
        "model": model or config.OLLAMA_MODEL,
        "system": SYSTEM_PROMPT,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.6, "top_p": 0.9, "num_ctx": 8192},
    }
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(f"{config.OLLAMA_BASE_URL}/api/generate", json=payload)
        resp.raise_for_status()
        return _clean_response(resp.json()["response"])
