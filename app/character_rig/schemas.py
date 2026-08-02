from pydantic import BaseModel, Field


class NewCharacterProjectRequest(BaseModel):
    name: str
    art_style: str = "Anime / gacha (Live2D-ready)"
    description: str
    pose: str = "Frontal - busto (recomendado para rig)"
    palette_hex: str = "#f0a83c"
    checkpoint: str
    seed: int = -1


class GenerateBaseRequest(BaseModel):
    positive_prompt: str
    negative_prompt: str = ""
    checkpoint: str
    seed: int = -1
    width: int = 1024
    height: int = 1024


class ApproveBaseRequest(BaseModel):
    iteration_image_path: str


class MaskUploadRequest(BaseModel):
    mask_png_base64: str  # data URL or raw base64, see router for parsing


class GenerateLayerRequest(BaseModel):
    part_key: str


class LayerPatchRequest(BaseModel):
    display_name: str | None = None
    order_index: int | None = None


class NewLayerRequest(BaseModel):
    part_key: str
    display_name: str
