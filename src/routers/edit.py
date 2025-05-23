from fastapi import APIRouter, Body, HTTPException
from pydantic import BaseModel
from typing import List
from src.lib.embedding import search_chroma
from src.lib.tts import generate_tts_audio
from src.lib.edit import create_composite_video
from src.db import save_video_generation_info
import os
import re

router = APIRouter(prefix="/api/ai")

class Scene(BaseModel):
    scene: int
    script: str
    subtitle: str

class StoryRequest(BaseModel):
    story: List[Scene]

def get_next_output_path():
    output_dir = "output"
    base_name = "final_edit"
    ext = ".mp4"
    pattern = re.compile(rf"{base_name}_(\d+){re.escape(ext)}")
    max_idx = 0

    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    for fname in os.listdir(output_dir):
        match = pattern.match(fname)
        if match:
            idx = int(match.group(1))
            if idx > max_idx:
                max_idx = idx

    next_idx = max_idx + 1
    return output_dir + "/" + f"{base_name}_{next_idx}{ext}"

@router.post("/video_generate")
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
            "text": scene["subtitle"],
            "scene": scene["scene"],
            "script": scene["script"]
        })

    # 3. 영상과 오디오, 자막 합치기 (lib 함수 사용)
    output_path = get_next_output_path()
    try:
        create_composite_video(video_infos, output_path)
        
        # 4. DB에 생성 정보 저장
        record_id = save_video_generation_info(output_path, video_infos)
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"비디오 합성 중 오류: {e}")

    return {"result": "success", "output_video": output_path, "record_id": record_id}