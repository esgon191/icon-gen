import time
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..deps import get_generation_service
from ..services.generation import GenerationService

router = APIRouter(prefix="/v1", tags=["openai"])

MODEL_ID = "icon-gen"


class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str


class ChatCompletionRequest(BaseModel):
    model: str
    messages: list[ChatMessage]
    stream: bool = False


class ChatChoiceMessage(BaseModel):
    role: Literal["assistant"] = "assistant"
    content: str


class ChatChoice(BaseModel):
    index: int = 0
    message: ChatChoiceMessage
    finish_reason: Literal["stop"] = "stop"


class ChatUsage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class ChatCompletionResponse(BaseModel):
    id: str
    object: Literal["chat.completion"] = "chat.completion"
    created: int
    model: str
    choices: list[ChatChoice]
    usage: ChatUsage = ChatUsage()


class ModelCard(BaseModel):
    id: str
    object: Literal["model"] = "model"
    created: int
    owned_by: str = "icon-gen"


class ModelList(BaseModel):
    object: Literal["list"] = "list"
    data: list[ModelCard]


@router.get("/models", response_model=ModelList)
def list_models() -> ModelList:
    return ModelList(data=[ModelCard(id=MODEL_ID, created=int(time.time()))])


@router.post("/chat/completions", response_model=ChatCompletionResponse)
def chat_completions(
    request: ChatCompletionRequest,
    service: GenerationService = Depends(get_generation_service),
) -> ChatCompletionResponse:
    if request.stream:
        raise HTTPException(status_code=400, detail="streaming is not supported yet")

    user_messages = [m for m in request.messages if m.role == "user"]
    if not user_messages:
        raise HTTPException(status_code=400, detail="no user message found")
    prompt = user_messages[-1].content

    result = service.generate(prompt)
    data_uri = f"data:{result['content_type']};base64,{result['image_base64']}"
    content = f"![icon]({data_uri})"

    return ChatCompletionResponse(
        id=f"chatcmpl-{uuid.uuid4().hex}",
        created=int(time.time()),
        model=request.model,
        choices=[ChatChoice(message=ChatChoiceMessage(content=content))],
    )
