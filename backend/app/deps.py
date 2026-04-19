from functools import lru_cache

from fastapi import Depends
from sqlalchemy.orm import Session

from .clients.base import LLMClient, StorageClient, T2IClient
from .clients.llm import StubLLMClient
from .clients.storage import S3Storage
from .clients.t2i import StubT2IClient
from .database import get_db
from .repositories.context import ContextRepository
from .services.generation import GenerationService


@lru_cache
def get_storage() -> StorageClient:
    return S3Storage()


@lru_cache
def get_llm() -> LLMClient:
    return StubLLMClient()


@lru_cache
def get_t2i() -> T2IClient:
    return StubT2IClient()


def get_context_repo(db: Session = Depends(get_db)) -> ContextRepository:
    return ContextRepository(db)


def get_generation_service(
    repo: ContextRepository = Depends(get_context_repo),
    storage: StorageClient = Depends(get_storage),
    llm: LLMClient = Depends(get_llm),
    t2i: T2IClient = Depends(get_t2i),
) -> GenerationService:
    return GenerationService(repo, storage, llm, t2i)
