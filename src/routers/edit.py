from fastapi import APIRouter

router = APIRouter(prefix="/api/edit")


@router.post("/edit")
def edit_video(text: str):
    return {"text": text}
