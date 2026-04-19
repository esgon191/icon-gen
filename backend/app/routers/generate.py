from fastapi import APIRouter, Depends

from ..deps import get_generation_service
from ..schemas import GenerateRequest, GenerateResponse
from ..services.generation import GenerationService

router = APIRouter(prefix="/v1", tags=["generate"])


@router.post("/generate", response_model=GenerateResponse)
def generate(
    request: GenerateRequest,
    service: GenerationService = Depends(get_generation_service),
) -> GenerateResponse:
    result = service.generate(request.prompt, n=request.n)
    return GenerateResponse(**result)
