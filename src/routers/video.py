from fastapi import APIRouter, UploadFile, File, Query
from pathlib import Path
import uuid
from src.lib.embedding import add_to_chroma, search_chroma
from src.lib.video import video_to_text, download_video_from_url, create_thumbnail
from src.db import save_video_url, check_url_exists, get_all_video_urls, delete_video_url

router = APIRouter(prefix="/api/video")

UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)

# 썸네일 디렉토리 생성
THUMBNAIL_DIR = Path("thumbnails")
THUMBNAIL_DIR.mkdir(exist_ok=True)

@router.post("/upload")
def upload_file(
    file: UploadFile = File(...),
):
    file_name = f"{uuid.uuid4()}_{file.filename}"

    # 파일 저장
    file_path = UPLOAD_DIR / file_name
    with open(file_path, "wb") as buffer:
        content = file.file.read()
        buffer.write(content)

    # 비디오 텍스트 추출
    text = video_to_text(file_path)

    # 썸네일 생성
    thumbnail_name = f"{file_path.stem}_thumbnail.jpg"
    thumbnail_path = THUMBNAIL_DIR / thumbnail_name
    try:
        created_thumbnail_path = create_thumbnail(file_path, str(thumbnail_path))
        thumbnail_url = f"/thumbnails/{thumbnail_name}"
    except Exception as e:
        print(f"썸네일 생성 실패: {e}")
        thumbnail_url = None

    # 임베딩 생성 (썸네일 정보도 메타데이터에 포함)
    metadata = {
        "file_name": file_name, 
        "information": text,
        "thumbnail": thumbnail_url
    }
    ids = add_to_chroma(text, metadata)

    return {
        "file_name": file_name, 
        "information": text,
        "thumbnail": thumbnail_url
    }


@router.post("/upload_url")
def upload_video_url(url: str = Query(..., description="비디오 파일의 URL")):
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

    # 비디오 텍스트 추출
    text = video_to_text(file_path)

    # 썸네일 생성
    thumbnail_name = f"{file_path.stem}_thumbnail.jpg"
    thumbnail_path = THUMBNAIL_DIR / thumbnail_name
    try:
        created_thumbnail_path = create_thumbnail(file_path, str(thumbnail_path))
        thumbnail_url = f"/thumbnails/{thumbnail_name}"
    except Exception as e:
        print(f"썸네일 생성 실패: {e}")
        thumbnail_url = None

    # 임베딩 생성 (썸네일 정보도 메타데이터에 포함)
    metadata = {
        "file_name": file_name, 
        "information": text,
        "thumbnail": thumbnail_url
    }
    ids = add_to_chroma(text, metadata)
    print(ids)

    # URL 정보를 DB에 저장
    save_video_url(url, file_name, metadata)

    return {
        "status": "success",
        "message": "비디오가 성공적으로 업로드되었습니다.",
        "file_name": file_name, 
        "information": text,
        "thumbnail": thumbnail_url
    }


@router.get("/search")
def search_file(text: str):
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

@router.get("/urls")
def get_video_urls():
    """저장된 모든 비디오 URL 목록을 가져옵니다."""
    urls = get_all_video_urls()
    return {
        "status": "success",
        "data": urls,
        "count": len(urls)
    }

@router.delete("/urls")
def delete_video_url_record(url: str = Query(..., description="삭제할 비디오 URL")):
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