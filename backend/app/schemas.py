from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ContextItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    object_key: str
    prompt: str
    content_type: str
    created_at: datetime


class GenerateRequest(BaseModel):
    prompt: str
    n: int | None = None


class GenerateResponse(BaseModel):
    prompt: str
    style: str
    image_base64: str
    content_type: str
