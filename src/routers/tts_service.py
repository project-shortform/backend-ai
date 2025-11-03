from fastapi import APIRouter
from pydantic import BaseModel
from src.lib.tts import generate_gemini_tts_audio

router = APIRouter(prefix="/api/tts")


class TTSRequest(BaseModel):
    text: str
    voice_name: str = "Zephyr"


@router.post("/generate")
def tts_endpoint(request: TTSRequest):
    file_path = generate_gemini_tts_audio(request.text, request.voice_name)
    return {"file_path": file_path}
