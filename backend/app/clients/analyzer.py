import logging

import httpx

from ..config import settings

logger = logging.getLogger(__name__)


class OllamaStyleAnalyzerClient:
    """
    Клиент к сервису icon-style (FastAPI + Ollama LLaVA).
    Вызывает POST /analyze для одной картинки.
    """

    def __init__(self) -> None:
        self.base_url = settings.icon_style_url.rstrip("/")
        self.timeout = settings.icon_style_timeout

    def analyze(self, image_bytes: bytes, content_type: str) -> str | None:
        files = {"file": ("icon", image_bytes, content_type or "image/png")}
        try:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.post(f"{self.base_url}/analyze", files=files)
        except httpx.RequestError as exc:
            logger.warning("icon-style request failed: %s", exc)
            return None

        if resp.status_code != 200:
            logger.warning(
                "icon-style returned %s: %s", resp.status_code, resp.text[:200]
            )
            return None

        try:
            return resp.json()["style_prompt"]
        except (ValueError, KeyError) as exc:
            logger.warning("icon-style returned malformed body: %s", exc)
            return None


class NullStyleAnalyzer:
    """
    Заглушка — ничего не делает, просто возвращает None.
    Полезна для тестов и для локальной разработки без Ollama.
    """

    def analyze(self, image_bytes: bytes, content_type: str) -> str | None:
        return None
