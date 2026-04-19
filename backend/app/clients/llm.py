from typing import Sequence

from .base import StyleImage


class StubLLMClient:
    def describe_style(
        self, user_prompt: str, samples: Sequence[StyleImage]
    ) -> str:
        notes = "; ".join(s.prompt for s in samples if s.prompt)
        return (
            f"[stub style based on {len(samples)} references] "
            f"user wants: {user_prompt!r}. "
            f"aggregated references: {notes or 'no textual notes available'}."
        )
