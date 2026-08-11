from pydantic import BaseModel, Field


class LoraSelection(BaseModel):
    name: str
    strength: float = 0.8


class GenerateRequest(BaseModel):
    project: str = "(root)"
    positive_prompt: str
    negative_prompt: str = ""
    loras: list[LoraSelection] = Field(default_factory=list)
    seed: int = -1
    width: int = 1024
    height: int = 1536
    batch_size: int = 1
    steps: int = 40
    cfg: float = 5.0
    sampler: str = "euler_ancestral"
    scheduler: str = "normal"
    checkpoint: str


class InpaintRequest(BaseModel):
    generation_id: str
    image_path: str
    mask_base64: str
    prompt: str
    mode: str = "edit"  # "add" | "edit" | "remove"
    negative_prompt: str = ""
    denoise: float = 0.65
    steps: int = 30
    cfg: float = 5.0
    sampler: str = "euler_ancestral"
    scheduler: str = "normal"
    grow_mask_by: int = 6
    checkpoint: str | None = None
    loras: list[LoraSelection] | None = None
    control_base64: str | None = None  # hand-drawn shape sketch (white line on black), optional
    control_strength: float = 0.6


class NewProjectRequest(BaseModel):
    name: str


class RenameProjectRequest(BaseModel):
    old_name: str
    new_name: str


class DeleteHistoryRequest(BaseModel):
    ids: list[str]


class MoveHistoryRequest(BaseModel):
    ids: list[str]
    project: str


class EnhancePromptRequest(BaseModel):
    prompt: str
    base_model: str = ""


class LoraFavoriteRequest(BaseModel):
    name: str
    favorite: bool


class SaveRecipeRequest(BaseModel):
    name: str
    checkpoint: str
    width: int
    height: int
    batch_size: int
    steps: int
    cfg: float
    sampler: str
    scheduler: str
    loras: list[LoraSelection] = Field(default_factory=list)
