import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class StyleContext(Base):
    __tablename__ = "style_context"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    object_key: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    prompt: Mapped[str] = mapped_column(String, nullable=False)
    content_type: Mapped[str] = mapped_column(String(64), nullable=False)
    # Описание стиля от LLaVA, заполняется при загрузке (может быть None,
    # если сервис icon-style был недоступен — тогда переанализировать
    # можно через POST /v1/context/{id}/reanalyze).
    style_description: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
