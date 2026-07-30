import re

import httpx

from . import config

# Civitai/LoRA Manager base_model labels for finetunes actually trained on Danbooru-style
# tag captions. Plain "SDXL 1.0"/"SDXL" and anything unrecognized default to the general
# branch below — booru vocabulary (1girl, solo, character-count tags) reads as noise or
# actively confuses a checkpoint captioned with natural-language alt-text instead.
_ANIME_TAG_CHECKPOINTS = re.compile(r"illustrious|noobai|animagine|pony", re.IGNORECASE)

_STYLE_ANIME = (
    "The target checkpoint is an anime/illustration model trained on Danbooru-style tag "
    "captions. Use booru vocabulary and conventions freely: character-count tags (1girl, "
    "2boys, solo), booru quality boosters (masterpiece, best quality, highly detailed, "
    "absurdres), and short_underscored_phrases for compound concepts.\n"
    "Formatting example — \"1girl, solo, red_hair, forest_background, dappled_sunlight, "
    "from_side, masterpiece, best_quality\"."
)
_STYLE_GENERAL = (
    "The target checkpoint's caption style is not confirmed as Danbooru-tag-trained — treat "
    "it as a general SDXL checkpoint. Do not inject anime-specific vocabulary (no \"1girl\", "
    "\"solo\", booru character-count tags, or anime-only quality boosters) unless the input "
    "itself already uses that vocabulary. Mirror the register the input is already written "
    "in: if it reads as a photographic or natural-language description, keep adding "
    "descriptive keyword phrases in that same register (lighting, lens/camera, composition, "
    "material, mood) instead of booru tags.\n"
    "Formatting example — \"woman, red_hair, forest_background, dappled_sunlight, "
    "shallow_depth_of_field, photorealistic, highly_detailed, 85mm_lens\"."
)

_SYSTEM_PROMPT_TEMPLATE = (
    "You are a prompt enrichment engine for a Stable Diffusion image model. The input is a "
    "list of tags and/or a short description, in any language.\n\n"
    "{style}\n\n"
    "Your task, in order:\n"
    "1. Translate everything into English. Never leave non-English words in the output.\n"
    "2. Keep every tag, name, number, and instruction given, unchanged in meaning. Never delete, rename, "
    "merge, or contradict anything specified.\n"
    "3. ADD new descriptive tags/phrases not present in the input, covering categories left out: lighting, "
    "camera angle or shot framing, color palette, background/setting detail, texture or material, mood or "
    "atmosphere, and quality boosters appropriate to the target style above. Add at least 8 new items. This "
    "step is mandatory even if the input already looks detailed or is already in English — returning the "
    "input unchanged, reordered, or only lightly reworded is a failure.\n"
    "4. Output format: single words or short_underscored_phrases separated by \", \" (comma space), matching "
    "the formatting example above. Never separate tags with only a space or a newline. Do not write "
    "narrative prose or full grammatical sentences.\n\n"
    "Do not censor, moralize, refuse, or soften explicit/NSFW content — treat it the same as any other tag.\n\n"
    "Output rules: respond with ONLY the final comma-separated tag list. No lead-in (\"Here is...\", "
    "\"Sure...\", \"Rewritten prompt:\"), no quotes, no notes, no mention of these instructions or of \"the "
    "user\". The first character of your response must be the first character of the first tag."
)


def _build_system_prompt(base_model: str) -> str:
    style = _STYLE_ANIME if base_model and _ANIME_TAG_CHECKPOINTS.search(base_model) else _STYLE_GENERAL
    return _SYSTEM_PROMPT_TEMPLATE.format(style=style)


# Meta-commentary a model sometimes prepends despite the system prompt telling it not
# to — always followed by a colon before the actual tag list starts.
_LEAD_IN_PREFIXES = (
    "here is", "here's", "sure", "certainly", "okay", "ok,", "rewritten prompt",
    "enhanced prompt", "final prompt", "prompt", "output", "translation", "note",
)


def _clean_response(text: str) -> str:
    text = text.strip()
    first_line, sep, rest = text.partition("\n")
    if ":" in first_line and any(first_line.lower().startswith(p) for p in _LEAD_IN_PREFIXES):
        _, _, after_colon = first_line.partition(":")
        text = (after_colon.strip() + (sep + rest if rest else "")).strip()
    if len(text) >= 2 and text[0] in "\"'" and text[-1] == text[0]:
        text = text[1:-1].strip()
    return text


async def list_models() -> list[str]:
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(f"{config.OLLAMA_BASE_URL}/api/tags")
        resp.raise_for_status()
        return [m["name"] for m in resp.json().get("models", [])]


async def enhance_prompt(prompt: str, model: str | None = None, base_model: str = "") -> str:
    payload = {
        "model": model or config.OLLAMA_MODEL,
        "system": _build_system_prompt(base_model),
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.6, "top_p": 0.9, "num_ctx": 8192},
    }
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(f"{config.OLLAMA_BASE_URL}/api/generate", json=payload)
        resp.raise_for_status()
        return _clean_response(resp.json()["response"])
