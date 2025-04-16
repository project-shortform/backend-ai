from fastapi import FastAPI, UploadFile, File, Body, Query, HTTPException
from fastapi.responses import FileResponse
from pathlib import Path
import uuid
from pydantic import BaseModel
import uvicorn
from src.lib import get_embeddings, add_to_chroma, search_chroma
from src.video import video_to_text, download_video_from_url
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

# CORS 미들웨어 추가
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 모든 오리진 허용, 필요시 특정 도메인으로 변경 가능
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# uploads 폴더를 /uploads 경로로 스태틱 서빙
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")

# React 빌드 파일 서빙 설정
app.mount("/assets", StaticFiles(directory="frontend/dist/assets"), name="assets")

UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)
TEMP_DIR = Path("temp")
TEMP_DIR.mkdir(exist_ok=True)


@app.post("/api/upload")
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


@app.post("/api/upload_url")
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


@app.get("/api/search")
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


# React 앱의 모든 경로를 처리하기 위한 라우트
@app.get("/{full_path:path}")
async def serve_react_app(full_path: str):
    # API 경로는 이 핸들러에서 처리하지 않음
    if full_path.startswith("api/"):
        raise HTTPException(status_code=404, detail="Not Found")

    # index.html 파일 반환
    index_file = Path("frontend/dist/index.html")
    if index_file.exists():
        return FileResponse(index_file)
    else:
        raise HTTPException(status_code=404, detail="React build files not found")


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=5000)
