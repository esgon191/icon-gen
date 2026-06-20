import time
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from .database import Base, engine
from .deps import get_storage
from .routers import context, generate, openai


def _init_db() -> None:
    Base.metadata.create_all(bind=engine)
    # Лёгкие in-place миграции для уже существующих БД —
    # пока мы живём без Alembic. Каждое ALTER должно быть идемпотентным.
    with engine.begin() as conn:
        conn.execute(
            text(
                "ALTER TABLE style_context "
                "ADD COLUMN IF NOT EXISTS style_description TEXT"
            )
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    for attempt in range(30):
        try:
            _init_db()
            break
        except OperationalError:
            if attempt == 29:
                raise
            time.sleep(1)
    get_storage()
    yield


app = FastAPI(title="icon-gen", lifespan=lifespan)
app.include_router(context.router)
app.include_router(generate.router)
app.include_router(openai.router)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
