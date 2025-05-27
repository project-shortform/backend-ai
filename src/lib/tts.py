import os
import uuid
import requests
import json
import time
from datetime import datetime
from src.lib.llm import client  # OpenAI client import
from dotenv import load_dotenv

load_dotenv()

# 저장 폴더
AUDIO_DIR = "./audios"
os.makedirs(AUDIO_DIR, exist_ok=True)

# Typecast API 설정
TYPECAST_API_URL = "https://typecast.ai/api/speak"
TYPECAST_API_KEY = os.getenv("TYPECAST_API_KEY")

# 액터 이름과 ID 매핑
TYPECAST_ACTORS = {
    "현주": "6335062fd260d463f7d7abb9",
    "지윤": "62296627a4ff5d1ee6bf4ecc",
    "한준": "618b1849ef7827cfea34ea1e",
    "진우": "632293f759d649937b97f323",
    "찬구": "5c547544fcfee90007fed455",
    "호빈이": "5ffda49bcba8f6d3d46fc447"
}

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

def generate_typecast_tts_audio(
    text: str, 
    actor_name: str = "현주",
    emotion_tone_preset: str = "normal-1",
    audio_format: str = "wav",
    tempo: float = 1.0,
    volume: int = 100,
    pitch: int = 0
) -> str:
    """
    Typecast API를 사용하여 텍스트를 음성으로 변환하고 /audios 폴더에 UUID 기반 파일로 저장.

    Args:
        text (str): 음성으로 변환할 텍스트
        actor_name (str): 사용할 음성 액터 이름 (현주, 지윤, 한준, 진우, 찬구)
        emotion_tone_preset (str): 감정 톤 프리셋 (예: angry-1, happy-1 등)
        audio_format (str): 오디오 포맷 (wav 또는 mp3)
        tempo (float): 음성 속도 (기본값: 1.0)
        volume (int): 음량 (0-100, 기본값: 100)
        pitch (int): 음높이 (-100 ~ 100, 기본값: 0)

    Returns:
        str: 저장된 오디오 파일의 경로

    Raises:
        Exception: API 요청 실패 또는 음성 생성 실패 시
        ValueError: 지원하지 않는 액터 이름인 경우
    """

    # 액터 이름을 ID로 변환
    if actor_name not in TYPECAST_ACTORS:
        available_actors = ", ".join(TYPECAST_ACTORS.keys())
        raise ValueError(f"지원하지 않는 액터 이름입니다: {actor_name}. 사용 가능한 액터: {available_actors}")
    
    actor_id = TYPECAST_ACTORS[actor_name]

    # UUID 기반 파일명 생성
    unique_id = uuid.uuid4().hex
    filename = f"{unique_id}.{audio_format}"
    filepath = os.path.join(AUDIO_DIR, filename)
    
    # print(actor_id)

    # Typecast API 요청 페이로드
    payload = json.dumps({
        "actor_id": actor_id,
        "text": text,
        "lang": "auto",
        "tempo": tempo,
        "volume": volume,
        "pitch": pitch,
        "xapi_hd": True,
        "max_seconds": 60,
        "model_version": "latest",
        "xapi_audio_format": audio_format,
        "emotion_tone_preset": emotion_tone_preset
    })

    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {TYPECAST_API_KEY}'
    }

    # 음성 생성 요청
    response = requests.post(TYPECAST_API_URL, headers=headers, data=payload)
    
    if response.status_code != 200:
        raise Exception(f"Typecast API 요청 실패: {response.status_code}, {response.text}")

    speak_url = response.json()['result']['speak_v2_url']

    # 음성 생성 완료까지 폴링 (최대 120초)
    for attempt in range(120):
        poll_response = requests.get(speak_url, headers=headers)
        
        if poll_response.status_code != 200:
            raise Exception(f"폴링 요청 실패: {poll_response.status_code}")
        
        result = poll_response.json()['result']
        
        if result['status'] == 'done':
            # 오디오 파일 다운로드
            audio_response = requests.get(result['audio_download_url'])
            
            if audio_response.status_code != 200:
                raise Exception(f"오디오 다운로드 실패: {audio_response.status_code}")
            
            # 파일로 저장
            with open(filepath, 'wb') as f:
                f.write(audio_response.content)
            
            return filepath
        
        elif result['status'] == 'failed':
            raise Exception(f"음성 생성 실패: {result.get('message', '알 수 없는 오류')}")
        
        else:
            print(f"상태: {result['status']}, 1초 후 재시도...")
            time.sleep(0.3)

    raise Exception("음성 생성 시간 초과 (120초)")


