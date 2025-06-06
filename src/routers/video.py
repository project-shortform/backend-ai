from fastapi import APIRouter, UploadFile, File, Query, HTTPException
from fastapi.responses import JSONResponse
from pathlib import Path
import uuid
import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import List, Dict, Any, Optional
from pydantic import BaseModel
from src.lib.embedding import add_to_chroma, search_chroma
from src.lib.video import video_to_text, download_video_from_url, create_thumbnail
from src.db import save_video_url, check_url_exists, get_all_video_urls, delete_video_url

router = APIRouter(
    prefix="/api/video",
    tags=["비디오 관리"],
    responses={404: {"description": "Not found"}}
)

UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)

# 썸네일 디렉토리 생성
THUMBNAIL_DIR = Path("thumbnails")
THUMBNAIL_DIR.mkdir(exist_ok=True)

# Response Models
class VideoUploadResponse(BaseModel):
    status: str
    message: str
    file_name: str
    information: str
    thumbnail: Optional[str]

class DuplicateVideoResponse(BaseModel):
    status: str
    message: str
    existing_data: Dict[str, Any]

class SearchResultItem(BaseModel):
    metadata: Dict[str, Any]
    distance: float

class VideoUrlsResponse(BaseModel):
    status: str
    data: List[Dict[str, Any]]
    count: int

class DeleteResponse(BaseModel):
    status: str
    message: str

@router.post(
    "/upload",
    response_model=VideoUploadResponse,
    summary="비디오 파일 업로드 (병렬 처리)",
    description="""
    로컬 비디오 파일을 업로드하고 병렬 처리로 최적화된 성능을 제공합니다.
    
    **병렬 처리 최적화:**
    - 텍스트 추출과 썸네일 생성을 동시에 실행
    - 전체 처리 시간 단축
    - 서버 리소스 효율적 활용
    
    **처리 과정:**
    1. 업로드된 파일을 서버에 저장
    2. 텍스트 추출 + 썸네일 생성 (병렬 실행)
    3. 벡터 임베딩 생성 및 ChromaDB에 저장
    
    **지원 형식:** MP4, AVI, MOV, WMV 등 일반적인 비디오 형식
    """,
    responses={
        200: {
            "description": "성공적으로 업로드됨",
            "content": {
                "application/json": {
                    "example": {
                        "status": "success",
                        "message": "비디오가 성공적으로 업로드되었습니다.",
                        "file_name": "abc123_example.mp4",
                        "information": "안녕하세요. 이 비디오는 FastAPI 사용법에 대해 설명합니다...",
                        "thumbnail": "/thumbnails/abc123_thumbnail.jpg",
                        "processing_time": "12.5초"
                    }
                }
            }
        },
        400: {"description": "잘못된 파일 형식"},
        500: {"description": "서버 내부 오류"}
    }
)
async def upload_file(
    file: UploadFile = File(..., description="업로드할 비디오 파일")
):
    import time
    start_time = time.time()
    
    file_name = f"{uuid.uuid4()}_{file.filename}"

    # 파일 저장
    file_path = UPLOAD_DIR / file_name
    with open(file_path, "wb") as buffer:
        content = file.file.read()
        buffer.write(content)

    # 썸네일 경로 준비
    thumbnail_name = f"{file_path.stem}_thumbnail.jpg"
    thumbnail_path = THUMBNAIL_DIR / thumbnail_name

    # 병렬 처리: 텍스트 추출과 썸네일 생성을 동시에 실행
    executor = ThreadPoolExecutor(max_workers=2)
    loop = asyncio.get_event_loop()
    
    try:
        # 텍스트 추출과 썸네일 생성을 병렬로 실행
        text_task = loop.run_in_executor(executor, video_to_text, file_path)
        thumbnail_task = loop.run_in_executor(executor, create_thumbnail, file_path, str(thumbnail_path))
        
        # 두 작업이 모두 완료될 때까지 대기
        text, thumbnail_result = await asyncio.gather(text_task, thumbnail_task, return_exceptions=True)
        
        # 썸네일 생성 결과 처리
        if isinstance(thumbnail_result, Exception):
            print(f"썸네일 생성 실패: {thumbnail_result}")
            thumbnail_url = None
        else:
            thumbnail_url = f"/thumbnails/{thumbnail_name}"
            
    except Exception as e:
        print(f"병렬 처리 중 오류 발생: {e}")
        # 폴백: 순차 처리
        text = video_to_text(file_path)
        try:
            create_thumbnail(file_path, str(thumbnail_path))
            thumbnail_url = f"/thumbnails/{thumbnail_name}"
        except Exception as thumb_e:
            print(f"썸네일 생성 실패: {thumb_e}")
            thumbnail_url = None
    
    finally:
        executor.shutdown(wait=False)

    # 임베딩 생성 (텍스트 추출 완료 후 실행)
    metadata = {
        "file_name": file_name, 
        "information": text,
        "thumbnail": thumbnail_url
    }
    ids = add_to_chroma(text, metadata)
    
    processing_time = round(time.time() - start_time, 1)

    return {
        "status": "success",
        "message": "비디오가 성공적으로 업로드되었습니다.",
        "file_name": file_name, 
        "information": text,
        "thumbnail": thumbnail_url,
        "processing_time": f"{processing_time}초"
    }


@router.post(
    "/upload_url",
    summary="URL로 비디오 업로드 (병렬 처리)",
    description="""
    비디오 URL을 통해 원격 비디오를 다운로드하고 병렬 처리로 최적화된 성능을 제공합니다.
    
    **병렬 처리 최적화:**
    - 텍스트 추출과 썸네일 생성을 동시에 실행
    - 전체 처리 시간 단축
    - 서버 리소스 효율적 활용
    
    **중복 검증 기능:**
    - 동일한 URL이 이미 업로드된 경우 중복임을 알려줍니다
    - 에러가 아닌 정보성 메시지로 처리됩니다
    
    **처리 과정:**
    1. URL 중복 여부 확인
    2. 비디오 파일 다운로드
    3. 텍스트 추출 + 썸네일 생성 (병렬 실행)
    4. 벡터 임베딩 생성
    5. URL 정보를 데이터베이스에 저장
    
    **지원 URL:** YouTube, Vimeo, 직접 비디오 링크 등
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
                                "message": "비디오가 성공적으로 업로드되었습니다.",
                                "file_name": "def456_downloaded.mp4",
                                "information": "이 영상은 Python 프로그래밍에 대해 설명합니다...",
                                "thumbnail": "/thumbnails/def456_thumbnail.jpg",
                                "processing_time": "8.3초"
                            }
                        },
                        "duplicate": {
                            "summary": "중복된 URL",
                            "value": {
                                "status": "duplicate",
                                "message": "이미 업로드된 비디오입니다.",
                                "existing_data": {
                                    "file_name": "def456_downloaded.mp4",
                                    "created_at": "2024-01-15T09:30:00.123456",
                                    "metadata": {
                                        "file_name": "def456_downloaded.mp4",
                                        "information": "기존 비디오 텍스트...",
                                        "thumbnail": "/thumbnails/def456_thumbnail.jpg"
                                    }
                                }
                            }
                        }
                    }
                }
            }
        },
        400: {"description": "잘못된 URL 형식"},
        404: {"description": "비디오를 찾을 수 없음"},
        500: {"description": "다운로드 또는 처리 중 오류"}
    }
)
async def upload_video_url(
    url: str = Query(
        ..., 
        description="다운로드할 비디오의 URL (예: https://youtube.com/watch?v=example)",
        example="https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    )
):
    import time
    start_time = time.time()
    
    # URL 중복 검증
    existing_record = check_url_exists(url)
    if existing_record:
        return {
            "status": "duplicate",
            "message": "이미 업로드된 비디오입니다.",
            "existing_data": {
                "file_name": existing_record["file_name"],
                "created_at": existing_record["created_at"],
                "metadata": existing_record.get("metadata", {})
            }
        }
    
    file_name = f"{uuid.uuid4()}_downloaded.mp4"
    file_path = UPLOAD_DIR / file_name

    # 비디오 다운로드
    download_video_from_url(url, str(file_path))

    # 썸네일 경로 준비
    thumbnail_name = f"{file_path.stem}_thumbnail.jpg"
    thumbnail_path = THUMBNAIL_DIR / thumbnail_name

    # 병렬 처리: 텍스트 추출과 썸네일 생성을 동시에 실행
    executor = ThreadPoolExecutor(max_workers=2)
    loop = asyncio.get_event_loop()
    
    try:
        # 텍스트 추출과 썸네일 생성을 병렬로 실행
        text_task = loop.run_in_executor(executor, video_to_text, file_path)
        thumbnail_task = loop.run_in_executor(executor, create_thumbnail, file_path, str(thumbnail_path))
        
        # 두 작업이 모두 완료될 때까지 대기
        text, thumbnail_result = await asyncio.gather(text_task, thumbnail_task, return_exceptions=True)
        
        # 썸네일 생성 결과 처리
        if isinstance(thumbnail_result, Exception):
            print(f"썸네일 생성 실패: {thumbnail_result}")
            thumbnail_url = None
        else:
            thumbnail_url = f"/thumbnails/{thumbnail_name}"
            
    except Exception as e:
        print(f"병렬 처리 중 오류 발생: {e}")
        # 폴백: 순차 처리
        text = video_to_text(file_path)
        try:
            create_thumbnail(file_path, str(thumbnail_path))
            thumbnail_url = f"/thumbnails/{thumbnail_name}"
        except Exception as thumb_e:
            print(f"썸네일 생성 실패: {thumb_e}")
            thumbnail_url = None
    
    finally:
        executor.shutdown(wait=False)

    # 임베딩 생성 (텍스트 추출 완료 후 실행)
    metadata = {
        "file_name": file_name, 
        "information": text,
        "thumbnail": thumbnail_url
    }
    ids = add_to_chroma(text, metadata)
    print(ids)

    # URL 정보를 DB에 저장
    save_video_url(url, file_name, metadata)
    
    processing_time = round(time.time() - start_time, 1)

    return {
        "status": "success",
        "message": "비디오가 성공적으로 업로드되었습니다.",
        "file_name": file_name, 
        "information": text,
        "thumbnail": thumbnail_url,
        "processing_time": f"{processing_time}초"
    }


@router.get(
    "/search",
    response_model=List[SearchResultItem],
    summary="비디오 콘텐츠 검색",
    description="""
    업로드된 비디오들에서 텍스트 기반 시맨틱 검색을 수행합니다.
    
    **검색 방식:**
    - 벡터 유사도 기반 시맨틱 검색
    - 업로드된 모든 비디오의 음성/자막 내용에서 검색
    - 가장 관련성 높은 결과부터 정렬하여 반환
    
    **활용 예시:**
    - "Python 강의" 검색 → Python 관련 비디오들 찾기
    - "데이터베이스 설계" 검색 → DB 관련 콘텐츠 찾기
    """,
    responses={
        200: {
            "description": "검색 결과 목록",
            "content": {
                "application/json": {
                    "example": [
                        {
                            "metadata": {
                                "file_name": "abc123_python_tutorial.mp4",
                                "information": "이 강의에서는 Python 기초 문법을 다룹니다...",
                                "thumbnail": "/thumbnails/abc123_thumbnail.jpg"
                            },
                            "distance": 0.25
                        },
                        {
                            "metadata": {
                                "file_name": "def456_advanced_python.mp4",
                                "information": "Python 고급 개념인 데코레이터와 제너레이터를...",
                                "thumbnail": "/thumbnails/def456_thumbnail.jpg"
                            },
                            "distance": 0.45
                        }
                    ]
                }
            }
        },
        400: {"description": "검색어가 비어있음"},
        404: {"description": "검색 결과 없음"}
    }
)
def search_file(
    text: str = Query(
        ..., 
        description="검색할 키워드나 문장",
        example="Python 프로그래밍 기초",
        min_length=1
    )
):
    results = search_chroma(text)

    # 결과 가공
    processed_results = []

    for i in range(len(results["documents"][0])):
        processed_results.append(
            {
                "metadata": results["metadatas"][0][i],
                "distance": results["distances"][0][i],
            }
        )

    return processed_results 

@router.get(
    "/urls",
    response_model=VideoUrlsResponse,
    summary="저장된 비디오 URL 목록 조회",
    description="""
    시스템에 저장된 모든 비디오 URL 정보를 조회합니다.
    
    **포함 정보:**
    - 원본 URL
    - 저장된 파일명
    - 업로드 시간
    - 메타데이터 (텍스트 내용, 썸네일 등)
    
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
                                "url": "https://youtube.com/watch?v=example1",
                                "file_name": "abc123_downloaded.mp4",
                                "created_at": "2024-01-15T09:30:00.123456",
                                "metadata": {
                                    "file_name": "abc123_downloaded.mp4",
                                    "information": "이 비디오는 React 기초를 다룹니다...",
                                    "thumbnail": "/thumbnails/abc123_thumbnail.jpg"
                                }
                            },
                            {
                                "url": "https://vimeo.com/123456789",
                                "file_name": "def456_downloaded.mp4",
                                "created_at": "2024-01-15T10:15:00.654321",
                                "metadata": {
                                    "file_name": "def456_downloaded.mp4",
                                    "information": "Node.js 서버 개발 강의입니다...",
                                    "thumbnail": "/thumbnails/def456_thumbnail.jpg"
                                }
                            }
                        ],
                        "count": 2
                    }
                }
            }
        }
    }
)
def get_video_urls():
    """저장된 모든 비디오 URL 목록을 가져옵니다."""
    urls = get_all_video_urls()
    return {
        "status": "success",
        "data": urls,
        "count": len(urls)
    }

@router.delete(
    "/urls",
    response_model=DeleteResponse,
    summary="비디오 URL 레코드 삭제",
    description="""
    특정 비디오 URL의 데이터베이스 레코드를 삭제합니다.
    
    **주의사항:**
    - URL 레코드만 삭제되며, 실제 비디오 파일은 삭제되지 않습니다
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
def delete_video_url_record(
    url: str = Query(
        ..., 
        description="삭제할 비디오 URL (정확한 URL 입력 필요)",
        example="https://youtube.com/watch?v=dQw4w9WgXcQ"
    )
):
    """특정 비디오 URL 레코드를 삭제합니다."""
    success = delete_video_url(url)
    
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