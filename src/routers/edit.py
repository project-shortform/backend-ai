from fastapi import APIRouter, Body, HTTPException, Query
from pydantic import BaseModel
from typing import List, Optional
from src.lib.embedding import search_chroma
from src.lib.tts import generate_tts_audio
from src.lib.edit import create_composite_video
from src.db import save_video_generation_info
from moviepy import VideoFileClip
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

def is_vertical_video(video_path: str) -> bool:
    """영상이 세로 영상인지 확인합니다."""
    try:
        with VideoFileClip(video_path) as clip:
            width, height = clip.size
            return height > width
    except Exception as e:
        print(f"영상 정보 확인 중 오류: {video_path} - {e}")
        return False

def select_video_with_options(
    script: str, 
    used_videos: set, 
    avoid_duplicates: bool = False, 
    filter_vertical: bool = False,
    max_search_results: int = 10
) -> tuple[str, dict]:
    """
    옵션에 따라 적절한 영상을 선택합니다.
    
    Args:
        script: 검색할 스크립트
        used_videos: 이미 사용된 영상들의 파일명 집합
        avoid_duplicates: 중복 영상 방지 여부
        filter_vertical: 세로 영상 필터링 여부
        max_search_results: 최대 검색 결과 수
    
    Returns:
        tuple: (선택된 파일명, 메타데이터)
    """
    search_result = search_chroma(script, n_results=max_search_results)
    
    if (
        not search_result["documents"]
        or not search_result["documents"][0]
        or not search_result["metadatas"]
        or not search_result["metadatas"][0]
    ):
        raise HTTPException(status_code=404, detail="해당하는 영상을 찾을 수 없습니다.")
    
    # 검색 결과를 순회하면서 조건에 맞는 영상 찾기
    for i, metadata in enumerate(search_result["metadatas"][0]):
        file_name = metadata.get("file_name")
        
        if not file_name:
            continue
            
        # 중복 영상 체크
        if avoid_duplicates and file_name in used_videos:
            continue
            
        video_path = f"uploads/{file_name}"
        
        # 파일 존재 여부 확인
        if not os.path.exists(video_path):
            continue
            
        # 세로 영상 필터링
        if filter_vertical and is_vertical_video(video_path):
            continue
            
        # 조건을 만족하는 영상 발견
        return file_name, metadata
    
    # 조건을 만족하는 영상이 없는 경우
    raise HTTPException(
        status_code=404, 
        detail="조건을 만족하는 영상을 찾을 수 없습니다. (중복 방지 또는 세로 영상 필터링으로 인해 제외됨)"
    )

@router.post("/video_generate")
def edit_video(
    story_req: StoryRequest,
    avoid_duplicates: bool = Query(False, description="중복 영상 방지 여부"),
    filter_vertical: bool = Query(False, description="세로 영상 필터링 여부"),
    max_search_results: int = Query(10, description="최대 검색 결과 수", ge=1, le=50)
):
    story_req = story_req.model_dump()
    
    video_infos = []
    used_videos = set()  # 사용된 영상들을 추적
    
    for scene in story_req["story"]:
        try:
            # 옵션에 따라 영상 선택
            file_name, metadata = select_video_with_options(
                script=scene["script"],
                used_videos=used_videos,
                avoid_duplicates=avoid_duplicates,
                filter_vertical=filter_vertical,
                max_search_results=max_search_results
            )
            
            # 사용된 영상 목록에 추가
            if avoid_duplicates:
                used_videos.add(file_name)
                
        except HTTPException as e:
            # 더 구체적인 에러 메시지
            raise HTTPException(
                status_code=e.status_code, 
                detail=f"Scene {scene['scene']}: {e.detail}"
            )

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

    return {
        "result": "success", 
        "output_video": output_path, 
        "record_id": record_id,
        "options_used": {
            "avoid_duplicates": avoid_duplicates,
            "filter_vertical": filter_vertical,
            "max_search_results": max_search_results
        },
        "videos_used": list(used_videos) if avoid_duplicates else None
    }