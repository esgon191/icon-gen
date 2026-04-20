import base64

from ..clients.base import StorageClient, T2IClient
from ..config import settings
from ..repositories.context import ContextRepository


class GenerationService:
    """
    Оркестрация генерации:
      1. Берём N случайных референсов из БД (у них уже есть style_description,
         посчитанный при загрузке через icon-style сервис).
      2. Агрегируем описания в одну style-строку.
      3. Передаём пользовательский промпт + style в T2I.

    На этом этапе vision-LLM не дёргается — тяжёлая работа сделана один раз
    при загрузке референса.
    """

    def __init__(
        self,
        repo: ContextRepository,
        storage: StorageClient,
        t2i: T2IClient,
    ) -> None:
        self.repo = repo
        self.storage = storage
        self.t2i = t2i

    def generate(self, user_prompt: str, n: int | None = None) -> dict:
        sample_size = n if n is not None else settings.context_sample_size
        samples = self.repo.random(sample_size)
        style = self._aggregate_style([s.style_description for s in samples])
        image, content_type = self.t2i.generate(user_prompt, style)
        return {
            "prompt": user_prompt,
            "style": style,
            "image_base64": base64.b64encode(image).decode(),
            "content_type": content_type,
        }

    @staticmethod
    def _aggregate_style(descriptions: list[str | None]) -> str:
        """
        MVP-агрегация: склеиваем непустые описания через "; ".
        При желании здесь можно подключить вторую LLM-модель для
        нормализации/усреднения — но сейчас избыточно.
        """
        parts = [d.strip() for d in descriptions if d and d.strip()]
        if not parts:
            return ""
        return "; ".join(parts)
