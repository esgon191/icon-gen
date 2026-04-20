import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from ..clients.base import StorageClient, StyleAnalyzer
from ..deps import get_context_repo, get_storage, get_style_analyzer
from ..repositories.context import ContextRepository
from ..schemas import ContextItem

router = APIRouter(prefix="/v1/context", tags=["context"])


@router.post("", response_model=ContextItem, status_code=201)
def upload_context(
    prompt: str = Form(...),
    file: UploadFile = File(...),
    repo: ContextRepository = Depends(get_context_repo),
    storage: StorageClient = Depends(get_storage),
    analyzer: StyleAnalyzer = Depends(get_style_analyzer),
) -> ContextItem:
    content_type = file.content_type or "application/octet-stream"
    if not content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="file must be an image")

    ext = content_type.split("/")[-1]
    object_key = f"{uuid.uuid4()}.{ext}"
    data = file.file.read()

    # 1. Кладём бинарник в S3.
    storage.put(object_key, data, content_type)

    # 2. Просим icon-style описать стиль. Если упадёт — запись всё равно
    #    создаётся, style_description будет null, можно позже переанализировать.
    style_description = analyzer.analyze(data, content_type)

    # 3. Создаём запись в БД.
    item = repo.add(
        object_key=object_key,
        prompt=prompt,
        content_type=content_type,
        style_description=style_description,
    )
    return ContextItem.model_validate(item)


@router.get("", response_model=list[ContextItem])
def list_context(
    repo: ContextRepository = Depends(get_context_repo),
) -> list[ContextItem]:
    return [ContextItem.model_validate(x) for x in repo.list()]


@router.delete("/{item_id}", status_code=204)
def delete_context(
    item_id: str,
    repo: ContextRepository = Depends(get_context_repo),
    storage: StorageClient = Depends(get_storage),
) -> None:
    item = repo.get(item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="not found")
    storage.delete(item.object_key)
    repo.delete(item_id)


@router.post("/{item_id}/reanalyze", response_model=ContextItem)
def reanalyze_context(
    item_id: str,
    repo: ContextRepository = Depends(get_context_repo),
    storage: StorageClient = Depends(get_storage),
    analyzer: StyleAnalyzer = Depends(get_style_analyzer),
) -> ContextItem:
    """
    Повторно проанализировать стиль уже загруженной картинки.
    Пригодится если icon-style был недоступен при загрузке или если
    поменялся промпт/модель в самом icon-style.
    """
    item = repo.get(item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="not found")

    data = storage.get(item.object_key)
    description = analyzer.analyze(data, item.content_type)
    if description is None:
        raise HTTPException(
            status_code=502,
            detail="style analyzer is unavailable or returned empty result",
        )

    updated = repo.set_style_description(item_id, description)
    assert updated is not None  # мы его только что читали
    return ContextItem.model_validate(updated)
