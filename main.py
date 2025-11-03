from fastapi import FastAPI
import uvicorn
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from src.routers import video, story, edit, tts_service, music
from src.task_queue import get_task_queue

app = FastAPI(
    title="Backend AI Video Generation API",
    description="AI 기반 비디오 생성 및 관리 시스템",
    version="1.0.0",
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
app.include_router(music.router)

# 스태틱 파일 서빙
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")
app.mount("/output", StaticFiles(directory="output"), name="output")
app.mount("/thumbnails", StaticFiles(directory="thumbnails"), name="thumbnails")
app.mount("/music", StaticFiles(directory="music"), name="music")


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
        "processing_tasks": queue_status["processing"],
    }


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=5000)
