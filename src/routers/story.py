from fastapi import APIRouter
from src.lib.llm import client

router = APIRouter(prefix="/api/story")


@router.post("/generate")
def generate_story(text: str):
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "developer", "content": """
             You are a storyteller.
             You are given a text of a video.
             """},
            {"role": "user", "content": text},
        ],
    )
    return {"result": response.choices[0].message.content}
