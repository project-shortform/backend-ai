from fastapi import APIRouter, UploadFile, File, Query
from pathlib import Path
import uuid
from src.lib.embedding import add_to_chroma, search_chroma
from src.lib.video import video_to_text, download_video_from_url, create_thumbnail

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
        "infomation": text,
        "thumbnail": thumbnail_url
    }
    ids = add_to_chroma(text, metadata)

    return {
        "file_name": file_name, 
        "infomation": text,
        "thumbnail": thumbnail_url
    }


@router.post("/upload_url")
def upload_video_url(url: str = Query(..., description="비디오 파일의 URL")):
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
        "infomation": text,
        "thumbnail": thumbnail_url
    }
    ids = add_to_chroma(text, metadata)
    print(ids)

    return {
        "file_name": file_name, 
        "infomation": text,
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