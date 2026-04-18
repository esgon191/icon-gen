import io
import torch
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from pipeline import load_pipeline

app = FastAPI()
pipe = load_pipeline()  # загружается один раз при старте

class GenerateRequest(BaseModel):
    prompt: str
    width: int = 512
    height: int = 512
    steps: int = 28
    guidance_scale: float = 3.5

@app.post("/generate")
def generate(req: GenerateRequest):
    image = pipe(
        prompt=f"Icon Kit, {req.prompt}",
        width=req.width,
        height=req.height,
        num_inference_steps=req.steps,
        guidance_scale=req.guidance_scale,
    ).images[0]

    buf = io.BytesIO()
    image.save(buf, format="PNG")
    buf.seek(0)
    return StreamingResponse(buf, media_type="image/png")
