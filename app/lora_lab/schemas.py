from pydantic import BaseModel


class NewJobRequest(BaseModel):
    name: str
    trigger_word: str
    checkpoint: str = ""


class CaptionUpdateRequest(BaseModel):
    caption: str


class TrainRequest(BaseModel):
    preset: str
    checkpoint: str
