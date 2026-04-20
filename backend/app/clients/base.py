from typing import Protocol


class StorageClient(Protocol):
    def put(self, key: str, data: bytes, content_type: str) -> None: ...
    def get(self, key: str) -> bytes: ...
    def delete(self, key: str) -> None: ...


class StyleAnalyzer(Protocol):
    """
    Анализирует стиль одной картинки и возвращает строку-описание,
    пригодную для использования как style-часть T2I промпта.
    Может вернуть None, если внешний сервис недоступен / анализ не удался —
    в этом случае запись в БД создаётся без описания и её можно
    переанализировать позже через /v1/context/{id}/reanalyze.
    """

    def analyze(self, image_bytes: bytes, content_type: str) -> str | None: ...


class T2IClient(Protocol):
    def generate(self, user_prompt: str, style: str) -> tuple[bytes, str]: ...
