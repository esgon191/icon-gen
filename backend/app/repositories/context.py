from typing import Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import StyleContext


class ContextRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def add(self, object_key: str, prompt: str, content_type: str) -> StyleContext:
        item = StyleContext(
            object_key=object_key, prompt=prompt, content_type=content_type
        )
        self.db.add(item)
        self.db.commit()
        self.db.refresh(item)
        return item

    def list(self, limit: int = 100) -> Sequence[StyleContext]:
        stmt = (
            select(StyleContext)
            .order_by(StyleContext.created_at.desc())
            .limit(limit)
        )
        return self.db.execute(stmt).scalars().all()

    def get(self, item_id: str) -> StyleContext | None:
        return self.db.get(StyleContext, item_id)

    def delete(self, item_id: str) -> bool:
        item = self.get(item_id)
        if item is None:
            return False
        self.db.delete(item)
        self.db.commit()
        return True

    def random(self, n: int) -> Sequence[StyleContext]:
        stmt = select(StyleContext).order_by(func.random()).limit(n)
        return self.db.execute(stmt).scalars().all()
