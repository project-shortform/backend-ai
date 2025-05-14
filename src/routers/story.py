from fastapi import APIRouter

router = APIRouter(prefix="/api/story")


@router.post("/generate")
def generate_story(text: str):
    return {"text": text}

