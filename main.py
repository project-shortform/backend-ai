from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pathlib import Path
import uvicorn
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from src.routers import video, story, edit, tts_service
import os

# 태스크 큐 임포트
from src.task_queue import get_task_queue

app = FastAPI(
    title="Backend AI Video Generation API",
    description="AI 기반 비디오 생성 및 관리 시스템",
    version="1.0.0"
)

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
app.mount("/output", StaticFiles(directory="output"), name="output")
app.mount("/thumbnails", StaticFiles(directory="thumbnails"), name="thumbnails")

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

@app.on_event("startup")
async def startup_event():
    """애플리케이션 시작 시 태스크 큐 워커를 시작합니다."""
    print("🚀 애플리케이션이 시작됩니다...")
    
    # 태스크 큐 워커 시작
    task_queue = get_task_queue()
    task_queue.start_worker()
    
    print("✅ 태스크 큐 워커가 시작되었습니다.")

@app.on_event("shutdown")
async def shutdown_event():
    """애플리케이션 종료 시 태스크 큐 워커를 정리합니다."""
    print("🛑 애플리케이션이 종료됩니다...")
    
    # 태스크 큐 워커 중지
    task_queue = get_task_queue()
    task_queue.stop_worker()
    
    print("✅ 태스크 큐 워커가 정리되었습니다.")

@app.get("/")
def read_root():
    return {"message": "Backend AI Video Generation API", "status": "running"}

@app.get("/health")
def health_check():
    """헬스 체크 엔드포인트"""
    task_queue = get_task_queue()
    queue_status = task_queue.get_queue_status()
    
    return {
        "status": "healthy",
        "task_queue_running": queue_status["is_running"],
        "pending_tasks": queue_status["pending"],
        "processing_tasks": queue_status["processing"]
    }

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=5000)
