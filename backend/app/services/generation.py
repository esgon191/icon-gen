import base64

from ..clients.base import LLMClient, StorageClient, StyleImage, T2IClient
from ..config import settings
from ..repositories.context import ContextRepository


class GenerationService:
    def __init__(
        self,
        repo: ContextRepository,
        storage: StorageClient,
        llm: LLMClient,
        t2i: T2IClient,
    ) -> None:
        self.repo = repo
        self.storage = storage
        self.llm = llm
        self.t2i = t2i

    def generate(self, user_prompt: str, n: int | None = None) -> dict:
        sample_size = n if n is not None else settings.context_sample_size
        samples = self.repo.random(sample_size)
        style_images = [
            StyleImage(
                data=self.storage.get(s.object_key),
                content_type=s.content_type,
                prompt=s.prompt,
            )
            for s in samples
        ]
        style = self.llm.describe_style(user_prompt, style_images)
        image, content_type = self.t2i.generate(user_prompt, style)
        return {
            "prompt": user_prompt,
            "style": style,
            "image_base64": base64.b64encode(image).decode(),
            "content_type": content_type,
        }
