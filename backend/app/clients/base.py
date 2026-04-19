from dataclasses import dataclass
from typing import Protocol, Sequence


@dataclass
class StyleImage:
    data: bytes
    content_type: str
    prompt: str


class StorageClient(Protocol):
    def put(self, key: str, data: bytes, content_type: str) -> None: ...
    def get(self, key: str) -> bytes: ...
    def delete(self, key: str) -> None: ...


class LLMClient(Protocol):
    def describe_style(
        self, user_prompt: str, samples: Sequence[StyleImage]
    ) -> str: ...


class T2IClient(Protocol):
    def generate(self, user_prompt: str, style: str) -> tuple[bytes, str]: ...
