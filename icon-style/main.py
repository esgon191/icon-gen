"""
Icon Style Analyzer — FastAPI + Ollama (LLaVA)
Принимает изображение иконки, возвращает описание стиля
в формате, готовом к использованию как text2image prompt.
"""

import base64
import io
import httpx
from fastapi import FastAPI, UploadFile, File, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from pydantic_settings import BaseSettings


# ── Настройки ────────────────────────────────────────────────

class Settings(BaseSettings):
    ollama_base_url: str = "http://localhost:11434"
    model: str = "llava:13b"
    timeout: float = 120.0

    class Config:
        env_prefix = "ICON_STYLE_"


settings = Settings()

# ── Промпт ────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are an expert visual style analyst for icons and illustrations.
Your task: analyze the uploaded icon image and produce a **concise style description**
that can be directly used as a style portion of a text-to-image prompt
(Stable Diffusion, Midjourney, DALL·E, etc.).

Output ONLY the style description — no explanations, no bullet points, no markdown.

Include these aspects in a single flowing description:
- visual style (flat, 3D, isometric, pixel art, line art, skeuomorphic, glassmorphism, neumorphism, etc.)
- rendering technique (vector, raster, hand-drawn, digital painting, etc.)
- color palette (specific colors or mood: vibrant, pastel, monochrome, gradient, duotone, etc.)
- lighting and shadows (soft shadows, hard shadows, ambient glow, no shadows, etc.)
- line work (thick outlines, thin strokes, no outlines, rounded corners, etc.)
- texture (smooth, grainy, noisy, glossy, matte, etc.)
- overall mood/aesthetic (modern, retro, minimalist, playful, corporate, etc.)

Format the output as a comma-separated style prompt, like:
"flat vector icon, bold outlines, vibrant gradient from blue to purple, soft drop shadow, rounded corners, smooth texture, modern minimalist aesthetic, clean design"

Keep it under 80 words. Be specific and precise."""


# ── FastAPI ───────────────────────────────────────────────────

app = FastAPI(
    title="Icon Style Analyzer",
    description="Анализирует стиль иконки и возвращает описание для text2image промпта",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class StyleResponse(BaseModel):
    style_prompt: str
    model: str

    class Config:
        json_schema_extra = {
            "example": {
                "style_prompt": "flat vector icon, bold outlines, vibrant gradient from blue to purple, soft drop shadow, rounded corners, smooth texture, modern minimalist aesthetic",
                "model": "llava:13b",
            }
        }


class HealthResponse(BaseModel):
    status: str
    ollama_url: str
    model: str
    ollama_available: bool


# ── Эндпоинты ────────────────────────────────────────────────


@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Проверяет доступность Ollama и загруженной модели."""
    available = False
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{settings.ollama_base_url}/api/tags")
            if resp.status_code == 200:
                models = [m["name"] for m in resp.json().get("models", [])]
                available = settings.model in models
    except Exception:
        pass

    return HealthResponse(
        status="ok" if available else "ollama_not_ready",
        ollama_url=settings.ollama_base_url,
        model=settings.model,
        ollama_available=available,
    )


@app.post("/analyze", response_model=StyleResponse)
async def analyze_icon_style(
    file: UploadFile = File(..., description="Изображение иконки (PNG, JPG, WEBP)"),
    model: str = Query(default=None, description="Модель Ollama (по умолчанию из настроек)"),
):
    """
    Принимает изображение иконки и возвращает описание стиля,
    пригодное для использования как text2image prompt.
    """
    # Проверяем тип файла
    if file.content_type and not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="Файл должен быть изображением")

    # Читаем и кодируем в base64
    image_bytes = await file.read()
    if len(image_bytes) > 20 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Файл слишком большой (макс. 20 МБ)")

    image_b64 = base64.b64encode(image_bytes).decode("utf-8")
    use_model = model or settings.model

    # Отправляем в Ollama
    payload = {
        "model": use_model,
        "prompt": SYSTEM_PROMPT,
        "images": [image_b64],
        "stream": False,
        "options": {
            "temperature": 0.3,
            "num_predict": 256,
        },
    }

    try:
        async with httpx.AsyncClient(timeout=settings.timeout) as client:
            resp = await client.post(
                f"{settings.ollama_base_url}/api/generate",
                json=payload,
            )
    except httpx.ConnectError:
        raise HTTPException(
            status_code=503,
            detail=f"Не удалось подключиться к Ollama по адресу {settings.ollama_base_url}. "
                   f"Убедитесь, что Ollama запущена: ollama serve",
        )
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Ollama не ответила вовремя (timeout)")

    if resp.status_code != 200:
        raise HTTPException(
            status_code=502,
            detail=f"Ollama вернула ошибку {resp.status_code}: {resp.text}",
        )

    data = resp.json()
    raw_response = data.get("response", "").strip()

    # Чистим от кавычек если модель обернула
    style_prompt = raw_response.strip('"').strip("'").strip()

    return StyleResponse(style_prompt=style_prompt, model=use_model)


@app.post("/analyze/batch", response_model=list[StyleResponse])
async def analyze_batch(
    files: list[UploadFile] = File(..., description="Несколько изображений иконок"),
    model: str = Query(default=None, description="Модель Ollama"),
):
    """Пакетный анализ нескольких иконок."""
    results = []
    for f in files:
        image_bytes = await f.read()
        image_b64 = base64.b64encode(image_bytes).decode("utf-8")
        use_model = model or settings.model

        payload = {
            "model": use_model,
            "prompt": SYSTEM_PROMPT,
            "images": [image_b64],
            "stream": False,
            "options": {"temperature": 0.3, "num_predict": 256},
        }

        try:
            async with httpx.AsyncClient(timeout=settings.timeout) as client:
                resp = await client.post(
                    f"{settings.ollama_base_url}/api/generate", json=payload
                )
            if resp.status_code == 200:
                raw = resp.json().get("response", "").strip().strip('"').strip("'")
                results.append(StyleResponse(style_prompt=raw, model=use_model))
            else:
                results.append(
                    StyleResponse(style_prompt=f"[error: {resp.status_code}]", model=use_model)
                )
        except Exception as e:
            results.append(StyleResponse(style_prompt=f"[error: {e}]", model=use_model))

    return results


# ── Запуск ────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
