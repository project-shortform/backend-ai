from fastapi import APIRouter
from pydantic import BaseModel
from src.lib.tts import generate_typecast_tts_audio

router = APIRouter(prefix="/api/tts")

class TTSRequest(BaseModel):
    text: str
    actor_name: str = "현주"

@router.post("/generate")
def tts_endpoint(request: TTSRequest):
    file_path = generate_typecast_tts_audio(request.text, request.actor_name)
    return {"file_path": file_path}
