import os
import uuid
import struct
import mimetypes
from google import genai
from google.genai import types
from src.lib.llm import client  # OpenAI client import (기존 generate_tts_audio용)
from dotenv import load_dotenv

load_dotenv()

# 저장 폴더
AUDIO_DIR = "./audios"
os.makedirs(AUDIO_DIR, exist_ok=True)

# Gemini API 설정
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")


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


def save_binary_file(file_name: str, data: bytes) -> None:
    """바이너리 데이터를 파일로 저장합니다."""
    with open(file_name, "wb") as f:
        f.write(data)
    print(f"파일이 저장되었습니다: {file_name}")


def convert_to_wav(audio_data: bytes, mime_type: str) -> bytes:
    """오디오 데이터를 WAV 형식으로 변환합니다.

    Args:
        audio_data: 원본 오디오 데이터 (bytes)
        mime_type: 오디오 데이터의 MIME 타입

    Returns:
        WAV 헤더가 포함된 오디오 데이터 (bytes)
    """
    parameters = parse_audio_mime_type(mime_type)
    bits_per_sample = parameters["bits_per_sample"]
    sample_rate = parameters["rate"]
    num_channels = 1
    data_size = len(audio_data)
    bytes_per_sample = bits_per_sample // 8
    block_align = num_channels * bytes_per_sample
    byte_rate = sample_rate * block_align
    chunk_size = 36 + data_size  # 36 bytes for header fields before data chunk size

    # WAV 헤더 생성 (http://soundfile.sapp.org/doc/WaveFormat/)
    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF",  # ChunkID
        chunk_size,  # ChunkSize (total file size - 8 bytes)
        b"WAVE",  # Format
        b"fmt ",  # Subchunk1ID
        16,  # Subchunk1Size (16 for PCM)
        1,  # AudioFormat (1 for PCM)
        num_channels,  # NumChannels
        sample_rate,  # SampleRate
        byte_rate,  # ByteRate
        block_align,  # BlockAlign
        bits_per_sample,  # BitsPerSample
        b"data",  # Subchunk2ID
        data_size,  # Subchunk2Size (size of audio data)
    )
    return header + audio_data


def parse_audio_mime_type(mime_type: str) -> dict[str, int]:
    """오디오 MIME 타입에서 비트율과 샘플레이트를 파싱합니다.

    Args:
        mime_type: 오디오 MIME 타입 문자열 (예: "audio/L16;rate=24000")

    Returns:
        "bits_per_sample"과 "rate" 키를 포함한 딕셔너리
    """
    bits_per_sample = 16
    rate = 24000

    # 파라미터에서 rate 추출
    parts = mime_type.split(";")
    for param in parts:
        param = param.strip()
        if param.lower().startswith("rate="):
            try:
                rate_str = param.split("=", 1)[1]
                rate = int(rate_str)
            except (ValueError, IndexError):
                pass  # 기본값 유지
        elif param.startswith("audio/L"):
            try:
                bits_per_sample = int(param.split("L", 1)[1])
            except (ValueError, IndexError):
                pass  # 기본값 유지

    return {"bits_per_sample": bits_per_sample, "rate": rate}


def generate_gemini_tts_audio(
    text: str,
    voice: str = "Zephyr",
) -> str:
    """
    Google Gemini 2.5 Flash TTS를 사용하여 텍스트를 음성으로 변환하고 /audios 폴더에 UUID 기반 파일로 저장.

    Args:
        text (str): 음성으로 변환할 텍스트
        voice (str): Gemini TTS 보이스 이름 (Zephyr, Charon, Kore, Fenrir, Aoede, Puck 등)

    Returns:
        str: 저장된 오디오 파일의 경로

    Raises:
        Exception: API 요청 실패 또는 음성 생성 실패 시
    """

    # Gemini API 클라이언트 초기화
    if not GEMINI_API_KEY:
        raise Exception("GEMINI_API_KEY 환경 변수가 설정되지 않았습니다.")

    client = genai.Client(api_key=GEMINI_API_KEY)

    # UUID 기반 파일명 생성
    unique_id = uuid.uuid4().hex
    filename = f"{unique_id}.wav"  # 항상 WAV 형식으로 저장
    filepath = os.path.join(AUDIO_DIR, filename)

    try:
        model = "gemini-2.5-flash-preview-tts"
        contents = [
            types.Content(
                role="user",
                parts=[
                    types.Part.from_text(text=text),
                ],
            ),
        ]

        generate_content_config = types.GenerateContentConfig(
            temperature=1,
            response_modalities=["audio"],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name=voice
                    )
                )
            ),
        )

        # 스트리밍으로 오디오 데이터 생성
        audio_chunks = []
        for chunk in client.models.generate_content_stream(
            model=model,
            contents=contents,
            config=generate_content_config,
        ):
            if (
                chunk.candidates is None
                or chunk.candidates[0].content is None
                or chunk.candidates[0].content.parts is None
            ):
                continue

            if (
                chunk.candidates[0].content.parts[0].inline_data
                and chunk.candidates[0].content.parts[0].inline_data.data
            ):

                inline_data = chunk.candidates[0].content.parts[0].inline_data
                data_buffer = inline_data.data

                # MIME 타입에 따라 WAV로 변환
                file_extension = mimetypes.guess_extension(inline_data.mime_type)
                if file_extension is None:
                    data_buffer = convert_to_wav(
                        inline_data.data, inline_data.mime_type
                    )

                audio_chunks.append(data_buffer)

        if not audio_chunks:
            raise Exception("오디오 데이터가 생성되지 않았습니다.")

        # 모든 오디오 청크를 하나의 파일로 결합
        combined_audio = b"".join(audio_chunks)
        save_binary_file(filepath, combined_audio)

        return filepath

    except Exception as e:
        raise Exception(f"Gemini TTS 생성 실패: {str(e)}")

