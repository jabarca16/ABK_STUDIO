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


class NewProjectRequest(BaseModel):
    name: str


class DeleteHistoryRequest(BaseModel):
    ids: list[str]


class EnhancePromptRequest(BaseModel):
    prompt: str


class LoraFavoriteRequest(BaseModel):
    name: str
    favorite: bool
