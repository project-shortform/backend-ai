from fastapi import APIRouter, Query, HTTPException
from fastapi.responses import JSONResponse
from pathlib import Path
import uuid
import time
import requests
import os
from typing import Dict, Any, Optional
from pydantic import BaseModel
from src.lib.embedding import add_to_chroma_music, search_chroma_music
from src.lib.video import music_to_text, get_audio_duration
from src.db import save_music_url, check_music_url_exists, get_all_music_urls, delete_music_url

router = APIRouter(
    prefix="/api/music",
    tags=["Music Management"],
    responses={404: {"description": "Not found"}}
)

# 음악 파일 저장 디렉토리
MUSIC_DIR = Path("music")
MUSIC_DIR.mkdir(exist_ok=True)

# Response Models
class MusicUploadResponse(BaseModel):
    status: str
    message: str
    file_name: str
    information: str
    duration: Optional[float]

class DuplicateMusicResponse(BaseModel):
    status: str
    message: str
    existing_data: Dict[str, Any]

class MusicUrlsResponse(BaseModel):
    status: str
    data: list
    count: int

class DeleteResponse(BaseModel):
    status: str
    message: str

class SearchResultItem(BaseModel):
    metadata: Dict[str, Any]
    distance: float

def download_music_from_url(url: str, save_path: str) -> str:
    """주어진 URL에서 음악 파일을 다운로드하여 지정된 경로에 저장합니다."""
    try:
        with requests.get(url, stream=True) as r:
            r.raise_for_status()
            with open(save_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)
        return save_path
    except Exception as e:
        raise Exception(f"음악 파일 다운로드 실패: {str(e)}")

def extract_music_info(file_path: str) -> str:
    """음악 파일에서 기본 정보를 추출합니다."""
    try:
        # Gemini LLM을 사용하여 음악 분석
        print(f"🎵 음악 분석 시작: {file_path}")
        music_info = music_to_text(file_path)
        print(f"📝 LLM 분석 결과: {music_info}")
        
        # 분석 결과가 없거나 실패한 경우, 기본 정보 반환
        if not music_info or len(music_info.strip()) == 0:
            print("⚠️ LLM 분석 결과가 없어 기본 정보 사용")
            # 파일명에서 정보 추출 (폴백)
            file_name = os.path.basename(file_path)
            name_without_ext = os.path.splitext(file_name)[0]
            
            # UUID 제거
            if "_" in name_without_ext:
                parts = name_without_ext.split("_", 1)
                if len(parts) > 1 and len(parts[0]) == 32:  # UUID 길이 확인
                    name_without_ext = parts[1]
            
            # 기본 정보 생성
            info = f"음악 파일: {name_without_ext}"
            duration = get_audio_duration(file_path)
            if duration > 0:
                info += f" (재생시간: {duration:.1f}초)"
            
            return info
        
        print("✅ LLM 분석 성공")
        return music_info
    except Exception as e:
        print(f"❌ 음악 정보 추출 실패: {file_path} - {e}")
        # 오류 발생 시 기본 정보 반환
        file_name = os.path.basename(file_path)
        return f"음악 파일: {os.path.splitext(file_name)[0]}"

@router.post(
    "/upload_url",
    summary="URL로 음악 업로드",
    description="""
    음악 URL을 통해 원격 음악 파일을 다운로드하고 처리합니다.
    
    **처리 과정:**
    1. URL 중복 여부 확인
    2. 음악 파일 다운로드
    3. 음악 정보 추출
    4. 벡터 임베딩 생성
    5. URL 정보를 데이터베이스에 저장
    
    **지원 URL:** 직접 음악 파일 링크 (MP3, WAV 등)
    """,
    responses={
        200: {
            "description": "성공 또는 중복",
            "content": {
                "application/json": {
                    "examples": {
                        "success": {
                            "summary": "성공적인 업로드",
                            "value": {
                                "status": "success",
                                "message": "음악이 성공적으로 업로드되었습니다.",
                                "file_name": "abc123_downloaded.mp3",
                                "information": "A gentle piano melody with slow tempo, creating a peaceful and contemplative mood. The music features soft piano arpeggios with minimal accompaniment, suitable for background music in emotional scenes or meditation content.",
                                "llm_analysis": "A gentle piano melody with slow tempo, creating a peaceful and contemplative mood. The music features soft piano arpeggios with minimal accompaniment, suitable for background music in emotional scenes or meditation content.",
                                "duration": 180.5,
                                "processing_time": "3.2초"
                            }
                        },
                        "duplicate": {
                            "summary": "중복된 URL",
                            "value": {
                                "status": "duplicate",
                                "message": "이미 업로드된 음악입니다.",
                                "existing_data": {
                                    "file_name": "abc123_downloaded.mp3",
                                    "created_at": "2024-01-15T09:30:00.123456",
                                    "metadata": {
                                        "file_name": "abc123_downloaded.mp3",
                                        "information": "음악 파일: 예쁜노래",
                                        "duration": 180.5
                                    }
                                }
                            }
                        }
                    }
                }
            }
        },
        400: {"description": "잘못된 URL 형식"},
        404: {"description": "음악을 찾을 수 없음"},
        500: {"description": "다운로드 또는 처리 중 오류"}
    }
)
async def upload_music_url(
    url: str = Query(
        ..., 
        description="다운로드할 음악의 URL (예: https://example.com/music.mp3)",
        example="https://example.com/music.mp3"
    )
):
    """URL로 음악 파일을 다운로드하고 처리합니다."""
    start_time = time.time()
    
    # URL 중복 검증
    print(f"🔍 음악 URL 중복 검증: {url}")
    existing_record = check_music_url_exists(url)
    if existing_record:
        print(f"⚠️ 중복된 음악 URL 발견: {url}")
        return {
            "status": "duplicate",
            "message": "이미 업로드된 음악입니다.",
            "existing_data": {
                "file_name": existing_record["file_name"],
                "created_at": existing_record["created_at"],
                "metadata": existing_record.get("metadata", {})
            }
        }
    print(f"✅ 새로운 음악 URL: {url}")
    
    # 파일 확장자 확인
    file_extension = ".mp3"  # 기본값
    if url.lower().endswith(('.mp3', '.wav', '.flac', '.aac', '.ogg')):
        file_extension = url[url.rfind('.'):].lower()
    
    file_name = f"{uuid.uuid4()}_downloaded{file_extension}"
    file_path = MUSIC_DIR / file_name

    try:
        # 음악 다운로드
        download_music_from_url(url, str(file_path))
        
        # 음악 정보 추출
        music_info = extract_music_info(str(file_path))
        music_duration = get_audio_duration(str(file_path))
        
        # 임베딩 생성 및 ChromaDB에 저장
        metadata = {
            "file_name": file_name, 
            "information": music_info,
            "llm_analysis": music_info,
            "duration": music_duration,
            "type": "music"
        }
        print(f"📊 ChromaDB에 음악 정보 저장: {file_name}")
        ids = add_to_chroma_music(music_info, metadata)
        
        # URL 정보를 DB에 저장
        print(f"💾 TinyDB에 음악 URL 정보 저장: {url}")
        record_id = save_music_url(url, file_name, metadata)
        print(f"✅ DB 저장 완료 (ID: {record_id})")
        
        processing_time = round(time.time() - start_time, 1)
        
        return {
            "status": "success",
            "message": "음악이 성공적으로 업로드되었습니다.",
            "file_name": file_name, 
            "information": music_info,
            "llm_analysis": music_info,  # LLM 분석 결과 추가
            "duration": music_duration,
            "processing_time": f"{processing_time}초"
        }
        
    except Exception as e:
        # 오류 발생 시 다운로드된 파일 삭제
        if file_path.exists():
            file_path.unlink()
        raise HTTPException(status_code=500, detail=f"음악 처리 중 오류 발생: {str(e)}")

@router.get(
    "/search",
    response_model=list[SearchResultItem],
    summary="음악 콘텐츠 검색",
    description="""
    업로드된 음악들에서 텍스트 기반 시맨틱 검색을 수행합니다.
    
    **검색 방식:**
    - 벡터 유사도 기반 시맨틱 검색
    - 업로드된 모든 음악의 정보에서 검색
    - 가장 관련성 높은 결과부터 정렬하여 반환
    
    **활용 예시:**
    - "감성적인 음악" 검색 → 감성적인 분위기의 음악들 찾기
    - "빠른 템포" 검색 → 빠른 템포의 음악들 찾기
    """,
    responses={
        200: {
            "description": "검색 결과 목록",
            "content": {
                "application/json": {
                    "example": [
                        {
                            "metadata": {
                                "file_name": "abc123_emotional.mp3",
                                "information": "A gentle piano melody with slow tempo, creating a peaceful and contemplative mood. The music features soft piano arpeggios with minimal accompaniment, suitable for background music in emotional scenes or meditation content.",
                                "duration": 240.0,
                                "type": "music"
                            },
                            "distance": 0.25
                        }
                    ]
                }
            }
        },
        400: {"description": "검색어가 비어있음"},
        404: {"description": "검색 결과 없음"}
    }
)
def search_music(
    text: str = Query(
        ..., 
        description="검색할 키워드나 문장",
        example="감성적인 피아노 음악",
        min_length=1
    )
):
    """음악을 검색합니다."""
    try:
        results = search_chroma_music(text)
        
        # 결과 가공
        processed_results = []
        
        for i in range(len(results["documents"][0])):
            metadata = results["metadatas"][0][i]
            
            # 음악 타입만 필터링
            if metadata.get("type") == "music":
                processed_results.append({
                    "metadata": metadata,
                    "distance": results["distances"][0][i],
                })
        
        return processed_results
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"음악 검색 중 오류: {str(e)}")

@router.get(
    "/urls",
    response_model=MusicUrlsResponse,
    summary="저장된 음악 URL 목록 조회",
    description="""
    시스템에 저장된 모든 음악 URL 정보를 조회합니다.
    
    **포함 정보:**
    - 원본 URL
    - 저장된 파일명
    - 업로드 시간
    - 메타데이터 (음악 정보, 재생시간 등)
    
    **용도:**
    - 중복 관리
    - 업로드 이력 확인
    - 시스템 모니터링
    """,
    responses={
        200: {
            "description": "URL 목록 조회 성공",
            "content": {
                "application/json": {
                    "example": {
                        "status": "success",
                        "data": [
                            {
                                "url": "https://example.com/music1.mp3",
                                "file_name": "abc123_downloaded.mp3",
                                "created_at": "2024-01-15T09:30:00.123456",
                                "metadata": {
                                    "file_name": "abc123_downloaded.mp3",
                                    "information": "A gentle piano melody with slow tempo, creating a peaceful and contemplative mood. The music features soft piano arpeggios with minimal accompaniment, suitable for background music in emotional scenes or meditation content.",
                                    "duration": 180.5,
                                    "type": "music"
                                }
                            }
                        ],
                        "count": 1
                    }
                }
            }
        }
    }
)
def get_music_urls():
    """저장된 모든 음악 URL 목록을 가져옵니다."""
    try:
        urls = get_all_music_urls()
        return {
            "status": "success",
            "data": urls,
            "count": len(urls)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"음악 URL 목록 조회 중 오류: {str(e)}")

@router.delete(
    "/urls",
    response_model=DeleteResponse,
    summary="음악 URL 레코드 삭제",
    description="""
    특정 음악 URL의 데이터베이스 레코드를 삭제합니다.
    
    **주의사항:**
    - URL 레코드만 삭제되며, 실제 음악 파일은 삭제되지 않습니다
    - ChromaDB의 벡터 데이터는 별도로 관리됩니다
    - 삭제 후 복구가 불가능합니다
    
    **사용 시나리오:**
    - 잘못 업로드된 URL 정리
    - 시스템 정리 및 유지보수
    - 중복 데이터 관리
    """,
    responses={
        200: {
            "description": "삭제 결과",
            "content": {
                "application/json": {
                    "examples": {
                        "success": {
                            "summary": "성공적인 삭제",
                            "value": {
                                "status": "success",
                                "message": "URL이 성공적으로 삭제되었습니다."
                            }
                        },
                        "not_found": {
                            "summary": "URL을 찾을 수 없음",
                            "value": {
                                "status": "error",
                                "message": "해당 URL을 찾을 수 없습니다."
                            }
                        }
                    }
                }
            }
        },
        400: {"description": "잘못된 URL 형식"}
    }
)
def delete_music_url_record(
    url: str = Query(
        ..., 
        description="삭제할 음악 URL (정확한 URL 입력 필요)",
        example="https://example.com/music.mp3"
    )
):
    """특정 음악 URL 레코드를 삭제합니다."""
    try:
        success = delete_music_url(url)
        
        if success:
            return {
                "status": "success",
                "message": "URL이 성공적으로 삭제되었습니다."
            }
        else:
            return {
                "status": "error",
                "message": "해당 URL을 찾을 수 없습니다."
            }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"음악 URL 삭제 중 오류: {str(e)}")
