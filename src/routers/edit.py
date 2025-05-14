from fastapi import APIRouter
from moviepy import VideoFileClip


router = APIRouter(prefix="/api/edit")

@router.post("/edit")
def edit_video(text: str):
    return {"text": text}
