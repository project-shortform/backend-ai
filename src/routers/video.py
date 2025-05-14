from fastapi import APIRouter, UploadFile, File, Query
from pathlib import Path
import uuid
from src.lib.embedding import add_to_chroma, search_chroma
from src.lib.video import video_to_text, download_video_from_url

router = APIRouter(prefix="/api/video")

UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)

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

    # 임베딩 생성
    ids = add_to_chroma(text, {"file_name": file_name, "infomation": text})
    print(ids)

    return {"file_name": file_name, "infomation": text}


@router.post("/upload_url")
def upload_video_url(url: str = Query(..., description="비디오 파일의 URL")):
    file_name = f"{uuid.uuid4()}_downloaded.mp4"
    file_path = UPLOAD_DIR / file_name

    # 비디오 다운로드
    download_video_from_url(url, str(file_path))

    # 비디오 텍스트 추출
    text = video_to_text(file_path)

    # 임베딩 생성
    ids = add_to_chroma(text, {"file_name": file_name, "infomation": text})
    print(ids)

    return {"file_name": file_name, "infomation": text}


@router.get("/search")
def search_file(text: str):
    results = search_chroma(text)

    # 결과 가공
    processed_results = []

    for i in range(len(results["documents"][0])):
        processed_results.append(
            {
                "file_name": results["metadatas"][0][i]["file_name"],
                "metadata": results["metadatas"][0][i],
                "distance": results["distances"][0][i],
            }
        )

    return processed_results 