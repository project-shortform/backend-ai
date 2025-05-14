from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pathlib import Path
import uvicorn
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from src.routers import video, story, edit, tts_service

app = FastAPI()

# CORS 미들웨어 추가
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 모든 오리진 허용, 필요시 특정 도메인으로 변경 가능
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API 라우터 추가
app.include_router(video.router)
app.include_router(story.router)
app.include_router(edit.router)
app.include_router(tts_service.router)


# uploads 폴더를 /uploads 경로로 스태틱 서빙
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")

# React 빌드 파일 서빙 설정
# app.mount("/assets", StaticFiles(directory="frontend/dist/assets"), name="assets")

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
