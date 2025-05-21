from fastapi import APIRouter, Body, HTTPException
from pydantic import BaseModel
from typing import List
from src.lib.embedding import search_chroma
from src.lib.tts import generate_tts_audio
from src.lib.edit import create_composite_video

router = APIRouter(prefix="/api/edit")

class Scene(BaseModel):
    scene: int
    script: str
    subtitle: str

class StoryRequest(BaseModel):
    story: List[Scene]

@router.post("/")
def edit_video(story_req: StoryRequest):
    story_req = story_req.model_dump()
    
    video_infos = []
    for scene in story_req["story"]:
        # 1. script로 유사도 높은 영상 검색
        search_result = search_chroma(scene["script"], n_results=1)

        # 결과가 없거나, 첫 번째 결과가 비어있으면 에러 반환
        if (
            not search_result["documents"]
            or not search_result["documents"][0]
            or not search_result["metadatas"]
            or not search_result["metadatas"][0]
        ):
            raise HTTPException(status_code=404, detail=f"Scene {scene['scene']}에 해당하는 영상을 찾을 수 없습니다.")
        
        # 0번째 리스트의 0번째 값에서 video_path 추출
        file_name = search_result["metadatas"][0][0].get("file_name")
        
        if not file_name:
            raise HTTPException(status_code=404, detail=f"Scene {scene['scene']}의 영상이 없습니다.")

        # 2. subtitle을 TTS로 변환
        audio_path = generate_tts_audio(scene["subtitle"])

        # video_infos에 정보 추가
        video_infos.append({
            "path": f"uploads/{file_name}",
            "audio_path": audio_path,
            "text": scene["subtitle"]
        })

    # 3. 영상과 오디오, 자막 합치기 (lib 함수 사용)
    output_path = "output/final_edit.mp4"
    try:
        create_composite_video(video_infos, output_path)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"비디오 합성 중 오류: {e}")

    return {"result": "success", "output_video": output_path}