import os
import uuid
from datetime import datetime
from src.lib.llm import client  # OpenAI client import

# 저장 폴더
AUDIO_DIR = "./audios"
os.makedirs(AUDIO_DIR, exist_ok=True)

def generate_tts_audio(text: str, voice: str = "onyx") -> str:
    """
    텍스트를 음성으로 변환하고 /audios 폴더에 UUID 기반 mp3 파일로 저장.

    Args:
        text (str): 음성으로 변환할 텍스트
        voice (str): 사용할 음성 스타일 (예: onyx, nova 등)

    Returns:
        str: 저장된 mp3 파일의 경로
    """

    # UUID 기반 파일명 생성
    unique_id = uuid.uuid4().hex
    filename = f"{unique_id}.mp3"
    filepath = os.path.join(AUDIO_DIR, filename)

    # TTS 생성
    response = client.audio.speech.create(
        model="tts-1",
        voice=voice,
        input=text,
    )

    # 파일로 저장
    with open(filepath, "wb") as f:
        f.write(response.content)

    return filepath
