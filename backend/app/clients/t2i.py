_PLACEHOLDER_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000d49444154789c63000100000500010d0a2db40000000049454e44ae426082"
)


class StubT2IClient:
    def generate(self, user_prompt: str, style: str) -> tuple[bytes, str]:
        return _PLACEHOLDER_PNG, "image/png"
