from fastapi import APIRouter
from pydantic import BaseModel
from src.lib.tts import generate_tts_audio  # 서비스 함수 임포트

router = APIRouter(prefix="/api/tts")

class TTSRequest(BaseModel):
    text: str
    voice: str = "onyx"

@router.post("/generate")
def tts_endpoint(request: TTSRequest):
    file_path = generate_tts_audio(request.text, request.voice)
    return {"file_path": file_path}
