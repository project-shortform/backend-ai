"""
비디오 AI 생성 및 관리 API

이 모듈은 다양한 방식으로 비디오를 생성하고 관리하는 API를 제공합니다.

## 주요 API 엔드포인트

### 🎬 비디오 생성 API
1. **POST /api/ai/video_generate** - AI 기반 비디오 생성 (스크립트 자동 매칭)
2. **POST /api/ai/video_generate_custom** - 커스텀 비디오 생성 (직접 파일 지정)
3. **POST /api/ai/video_generate_flexible** - 유연한 비디오 생성 (다중 선택 방식)
4. **POST /api/ai/video_generate_mixed** - 혼합 비디오 생성 (다양한 씬 타입 조합)

### 📚 히스토리 관리 API
5. **GET /api/ai/video_history** - 비디오 생성 히스토리 조회
6. **GET /api/ai/video_history/{record_id}** - 특정 기록 상세 조회
7. **POST /api/ai/video_regenerate/{record_id}** - 이전 기록으로 비디오 재생성
8. **DELETE /api/ai/video_history/{record_id}** - 비디오 생성 기록 삭제

## 특징
- 🤖 AI 기반 영상 자동 매칭
- 🎯 직접 파일 선택 옵션
- 🔄 중복 영상 방지 기능
- 📐 세로 영상 필터링
- 💾 완전한 히스토리 관리
- 🔊 TTS 기반 자막 음성 생성
- 🎞️ 다양한 씬 타입 지원

자세한 사용법은 각 엔드포인트의 documentation을 참고하세요.
"""

from fastapi import APIRouter, Body, HTTPException, Query, BackgroundTasks
from pydantic import BaseModel
from typing import List, Optional, Union
from src.lib.embedding import search_chroma
from src.lib.tts import generate_typecast_tts_audio
from src.lib.edit import create_composite_video, cleanup_video_resources
from src.db import save_video_generation_info, get_video_generation_history, get_video_generation_by_id
from src.db import save_task_info, update_task_info, get_task_info, get_all_tasks, delete_task_info  # 태스크 DB 함수들
from src.task_queue import get_task_queue, TaskStatus  # 태스크 큐
from moviepy import VideoFileClip
import os
import re

router = APIRouter(prefix="/api/ai")

class Scene(BaseModel):
    scene: int
    script: str
    subtitle: str
    actor_name: Optional[str] = "현주"

class StoryRequest(BaseModel):
    story: List[Scene]

class CustomScene(BaseModel):
    scene: int
    video_file_name: str  # 직접 지정할 비디오 파일명
    subtitle: str
    script: Optional[str] = None  # 선택적 스크립트 (기록용)
    actor_name: Optional[str] = "현주"

class CustomStoryRequest(BaseModel):
    story: List[CustomScene]

class FlexibleScene(BaseModel):
    scene: int
    subtitle: str
    # 비디오 선택 방식 중 하나
    video_file_name: Optional[str] = None  # 직접 파일명 지정
    script: Optional[str] = None  # 스크립트로 검색
    search_keywords: Optional[List[str]] = None  # 키워드 리스트로 검색
    actor_name: Optional[str] = "현주"
    
class FlexibleStoryRequest(BaseModel):
    story: List[FlexibleScene]

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

# 비동기 처리를 위한 래퍼 함수들
def _async_edit_video(
    story_req_dict: dict,
    avoid_duplicates: bool = False,
    filter_vertical: bool = False,
    max_search_results: int = 10,
    task_id: str = None
):
    """비동기 비디오 생성 처리 함수"""
    try:
        # 원본 StoryRequest 데이터 보존
        original_story_request = story_req_dict
        
        # 생성 옵션들 저장
        generation_options = {
            "avoid_duplicates": avoid_duplicates,
            "filter_vertical": filter_vertical,
            "max_search_results": max_search_results,
            "async_processing": True
        }
        
        video_infos = []
        used_videos = set()
        
        for scene in story_req_dict["story"]:
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
                    
            except Exception as e:
                raise Exception(f"Scene {scene['scene']}: {str(e)}")

            # subtitle을 TTS로 변환
            actor_name = scene.get("actor_name", "현주")
            audio_path = generate_typecast_tts_audio(scene["subtitle"], actor_name)

            # video_infos에 정보 추가
            video_infos.append({
                "path": f"uploads/{file_name}",
                "audio_path": audio_path,
                "text": scene["subtitle"],
                "scene": scene["scene"],
                "script": scene["script"]
            })

        # 영상과 오디오, 자막 합치기
        output_path = get_next_output_path()
        
        try:
            create_composite_video(video_infos, output_path)
        finally:
            # 비디오 처리 후 자원 정리
            cleanup_video_resources()
        
        # DB에 생성 정보 저장
        record_id = save_video_generation_info(
            output_path=output_path, 
            video_infos=video_infos,
            story_request=original_story_request,
            generation_options=generation_options
        )
        
        # 태스크 완료 정보 업데이트
        if task_id:
            update_task_info(task_id, {
                "status": TaskStatus.COMPLETED.value,
                "result": {
                    "output_video": output_path,
                    "record_id": record_id,
                    "options_used": generation_options,
                    "videos_used": list(used_videos) if avoid_duplicates else None
                }
            })
        
        return {
            "result": "success", 
            "output_video": output_path, 
            "record_id": record_id,
            "options_used": generation_options,
            "videos_used": list(used_videos) if avoid_duplicates else None
        }
        
    except Exception as e:
        # 에러 발생 시에도 자원 정리
        try:
            cleanup_video_resources()
        except:
            pass
            
        # 태스크 실패 정보 업데이트
        if task_id:
            update_task_info(task_id, {
                "status": TaskStatus.FAILED.value,
                "error": {
                    "message": str(e),
                    "type": "video_generation_error"
                }
            })
        raise e

def _async_edit_video_mixed(
    scenes_data: list,
    avoid_duplicates: bool = False,
    filter_vertical: bool = False,
    max_search_results: int = 10,
    skip_unresolved: bool = False,
    task_id: str = None
):
    """비동기 혼합 비디오 생성 처리 함수"""
    try:
        original_request = scenes_data
        
        generation_options = {
            "generation_type": "mixed",
            "avoid_duplicates": avoid_duplicates,
            "filter_vertical": filter_vertical,
            "max_search_results": max_search_results,
            "skip_unresolved": skip_unresolved,
            "async_processing": True
        }
        
        video_infos = []
        used_videos = set()
        skipped_scenes = []
        
        for i, scene in enumerate(scenes_data):
            file_name = None
            metadata = {}
            selection_method = None
            
            try:
                # Scene 타입 감지 및 처리
                if "video_file_name" in scene and scene.get("video_file_name"):
                    selection_method = "direct_file"
                    file_name = scene["video_file_name"]
                    video_path = f"uploads/{file_name}"
                    
                    if not os.path.exists(video_path):
                        raise ValueError(f"파일 '{file_name}'을 찾을 수 없습니다.")
                    
                    if avoid_duplicates and file_name in used_videos:
                        raise ValueError("중복된 영상입니다.")
                    if filter_vertical and is_vertical_video(video_path):
                        raise ValueError("세로 영상입니다.")
                
                elif "search_keywords" in scene and scene.get("search_keywords"):
                    selection_method = "keyword_search"
                    search_query = " ".join(scene["search_keywords"])
                    file_name, metadata = select_video_with_options(
                        script=search_query,
                        used_videos=used_videos,
                        avoid_duplicates=avoid_duplicates,
                        filter_vertical=filter_vertical,
                        max_search_results=max_search_results
                    )
                
                elif "script" in scene and scene.get("script"):
                    selection_method = "script_search"
                    file_name, metadata = select_video_with_options(
                        script=scene["script"],
                        used_videos=used_videos,
                        avoid_duplicates=avoid_duplicates,
                        filter_vertical=filter_vertical,
                        max_search_results=max_search_results
                    )
                
                else:
                    raise ValueError("유효한 비디오 선택 방법이 제공되지 않았습니다.")
                
                # 사용된 영상 추가
                if avoid_duplicates:
                    used_videos.add(file_name)
                
            except Exception as e:
                if skip_unresolved:
                    skipped_scenes.append({
                        "scene": scene.get("scene", i + 1),
                        "reason": str(e),
                        "selection_method": selection_method
                    })
                    continue
                else:
                    raise Exception(f"Scene {scene.get('scene', i + 1)}: {str(e)}")
            
            # TTS 생성
            actor_name = scene.get("actor_name", "현주")
            audio_path = generate_typecast_tts_audio(scene["subtitle"], actor_name)
            
            # video_infos에 정보 추가
            video_infos.append({
                "path": f"uploads/{file_name}",
                "audio_path": audio_path,
                "text": scene["subtitle"],
                "scene": scene.get("scene", i + 1),
                "script": scene.get("script", ""),
                "search_keywords": scene.get("search_keywords"),
                "video_file_name": scene.get("video_file_name"),
                "selection_method": selection_method,
                "metadata": metadata
            })
        
        if not video_infos:
            raise Exception("처리할 수 있는 비디오가 없습니다.")
        
        # 영상 합성
        output_path = get_next_output_path()
        
        try:
            create_composite_video(video_infos, output_path)
        finally:
            # 비디오 처리 후 자원 정리
            cleanup_video_resources()
        
        # DB에 저장
        record_id = save_video_generation_info(
            output_path=output_path,
            video_infos=video_infos,
            story_request={"scenes": original_request},
            generation_options=generation_options
        )
        
        # 태스크 완료 정보 업데이트
        if task_id:
            update_task_info(task_id, {
                "status": TaskStatus.COMPLETED.value,
                "result": {
                    "output_video": output_path,
                    "record_id": record_id,
                    "options_used": generation_options,
                    "videos_used": list(used_videos) if avoid_duplicates else None,
                    "skipped_scenes": skipped_scenes if skipped_scenes else None,
                    "processed_scenes": len(video_infos)
                }
            })

        return {
            "result": "success",
            "output_video": output_path,
            "record_id": record_id,
            "options_used": generation_options,
            "videos_used": list(used_videos) if avoid_duplicates else None,
            "skipped_scenes": skipped_scenes if skipped_scenes else None,
            "processed_scenes": len(video_infos)
        }
        
    except Exception as e:
        # 에러 발생 시에도 자원 정리
        try:
            cleanup_video_resources()
        except:
            pass
            
        # 태스크 실패 정보 업데이트
        if task_id:
            update_task_info(task_id, {
                "status": TaskStatus.FAILED.value,
                "error": {
                    "message": str(e),
                    "type": "mixed_video_generation_error"
                }
            })
        raise e

@router.post("/video_generate_async",
    summary="🚀 비동기 AI 기반 비디오 생성",
    description="""
    **스크립트를 기반으로 비동기적으로 영상을 생성합니다.**
    
    ## 주요 기능
    - 🔄 백그라운드에서 비디오 생성 처리
    - 📊 실시간 진행 상태 추적
    - ⚡ 즉시 태스크 ID 반환
    - 🎯 큐 기반 순차 처리
    
    ## 처리 흐름
    1. **요청 접수**: 즉시 태스크 ID 반환
    2. **큐 대기**: 다른 작업 완료 후 순차 처리
    3. **비디오 생성**: 백그라운드에서 실제 작업 수행
    4. **결과 저장**: 완료 후 결과를 DB에 저장
    
    ## 사용 예시
    ```json
    {
      "story": [
        {
          "scene": 1,
          "script": "아름다운 바다 풍경과 석양",
          "subtitle": "오늘은 정말 아름다운 하루였습니다.",
          "actor_name": "현주"
        }
      ]
    }
    ```
    
    ## 응답 예시
    ```json
    {
      "result": "success",
      "task_id": "550e8400-e29b-41d4-a716-446655440000",
      "status": "pending",
      "message": "비디오 생성 작업이 큐에 추가되었습니다.",
      "queue_position": 2
    }
    ```
    
    ## 상태 확인
    반환된 `task_id`로 `/api/ai/task_status/{task_id}` 엔드포인트에서 진행 상황을 확인할 수 있습니다.
    """,
    response_description="태스크 ID와 초기 상태를 반환합니다.",
    tags=["Video Generation", "Async"]
)
def edit_video_async(
    story_req: StoryRequest,
    avoid_duplicates: bool = Query(False, description="중복 영상 방지 여부"),
    filter_vertical: bool = Query(False, description="세로 영상 필터링 여부"),
    max_search_results: int = Query(10, description="최대 검색 결과 수", ge=1, le=50)
):
    """비동기적으로 비디오를 생성합니다."""
    
    # 태스크 큐 가져오기
    queue = get_task_queue()
    
    # 태스크를 큐에 추가
    task_id = queue.add_task(
        task_func=_async_edit_video,
        task_kwargs={
            "story_req_dict": story_req.model_dump(),
            "avoid_duplicates": avoid_duplicates,
            "filter_vertical": filter_vertical,
            "max_search_results": max_search_results,
            "task_id": None  # 나중에 설정됨
        },
        task_type="video_generation"
    )
    
    # 태스크 ID를 함수 인자에 추가
    task_info = queue.get_task_status(task_id)
    if task_info:
        with queue._lock:
            queue.tasks[task_id]["kwargs"]["task_id"] = task_id
    
    # DB에 태스크 정보 저장
    save_task_info(task_id, {
        "type": "video_generation",
        "status": TaskStatus.PENDING.value,
        "request_data": story_req.model_dump(),
        "options": {
            "avoid_duplicates": avoid_duplicates,
            "filter_vertical": filter_vertical,
            "max_search_results": max_search_results
        }
    })
    
    # 큐 상태 조회
    queue_status = queue.get_queue_status()
    
    return {
        "result": "success",
        "task_id": task_id,
        "status": "pending",
        "message": "비디오 생성 작업이 큐에 추가되었습니다.",
        "queue_position": queue_status["pending"],
        "estimated_wait_time": f"{queue_status['pending'] * 2-5}분"  # 대략적인 예상 시간
    }

@router.post("/video_generate_mixed_async",
    summary="🚀 비동기 혼합 비디오 생성",
    description="""
    **다양한 타입의 씬들을 비동기적으로 혼합하여 영상을 생성합니다.**
    
    ## 주요 기능
    - 🔄 백그라운드에서 복잡한 혼합 비디오 처리
    - 📊 실시간 진행 상태 추적
    - ⚡ 즉시 태스크 ID 반환
    - 🎯 모든 씬 타입 지원 (Scene, CustomScene, FlexibleScene)
    
    ## 사용 예시
    ```json
    [
      {
        "scene": 1,
        "script": "바다와 석양",
        "subtitle": "AI가 선택한 바다 영상입니다.",
        "actor_name": "현주"
      },
      {
        "scene": 2,
        "video_file_name": "my_video.mp4",
        "subtitle": "직접 지정한 영상입니다.",
        "actor_name": "지윤"
      }
    ]
    ```
    
    ## 응답 예시
    ```json
    {
      "result": "success",
      "task_id": "550e8400-e29b-41d4-a716-446655440001",
      "status": "pending",
      "message": "혼합 비디오 생성 작업이 큐에 추가되었습니다.",
      "queue_position": 1
    }
    ```
    """,
    response_description="태스크 ID와 초기 상태를 반환합니다.",
    tags=["Video Generation", "Async", "Mixed"]
)
def edit_video_mixed_async(
    scenes: List[Union[Scene, CustomScene, FlexibleScene]],
    avoid_duplicates: bool = Query(False, description="중복 영상 방지 여부"),
    filter_vertical: bool = Query(False, description="세로 영상 필터링 여부"),
    max_search_results: int = Query(10, description="최대 검색 결과 수", ge=1, le=50),
    skip_unresolved: bool = Query(False, description="해결되지 않는 씬 건너뛰기")
):
    """비동기적으로 혼합 비디오를 생성합니다."""
    
    # 씬 데이터를 딕셔너리로 변환
    scenes_data = []
    for scene_data in scenes:
        if hasattr(scene_data, 'model_dump'):
            scenes_data.append(scene_data.model_dump())
        elif hasattr(scene_data, 'dict'):
            scenes_data.append(scene_data.dict())
        else:
            scenes_data.append(scene_data)
    
    # 태스크 큐 가져오기
    queue = get_task_queue()
    
    # 태스크를 큐에 추가
    task_id = queue.add_task(
        task_func=_async_edit_video_mixed,
        task_kwargs={
            "scenes_data": scenes_data,
            "avoid_duplicates": avoid_duplicates,
            "filter_vertical": filter_vertical,
            "max_search_results": max_search_results,
            "skip_unresolved": skip_unresolved,
            "task_id": None  # 나중에 설정됨
        },
        task_type="mixed_video_generation"
    )
    
    # 태스크 ID를 함수 인자에 추가
    task_info = queue.get_task_status(task_id)
    if task_info:
        with queue._lock:
            queue.tasks[task_id]["kwargs"]["task_id"] = task_id
    
    # DB에 태스크 정보 저장
    save_task_info(task_id, {
        "type": "mixed_video_generation",
        "status": TaskStatus.PENDING.value,
        "request_data": {"scenes": scenes_data},
        "options": {
            "avoid_duplicates": avoid_duplicates,
            "filter_vertical": filter_vertical,
            "max_search_results": max_search_results,
            "skip_unresolved": skip_unresolved
        }
    })
    
    # 큐 상태 조회
    queue_status = queue.get_queue_status()
    
    return {
        "result": "success",
        "task_id": task_id,
        "status": "pending",
        "message": "혼합 비디오 생성 작업이 큐에 추가되었습니다.",
        "queue_position": queue_status["pending"],
        "estimated_wait_time": f"{queue_status['pending'] * 3-7}분"  # 혼합 비디오는 더 오래 걸림
    }

@router.get("/task_status/{task_id}",
    summary="📊 태스크 상태 조회",
    description="""
    **특정 태스크의 현재 상태와 진행 상황을 조회합니다.**
    
    ## 태스크 상태
    - **pending**: 대기 중 (큐에서 순서를 기다리는 중)
    - **processing**: 처리 중 (실제 비디오 생성 작업 수행 중)
    - **completed**: 완료 (비디오 생성 완료, 결과 확인 가능)
    - **failed**: 실패 (에러 발생, 에러 메시지 확인 가능)
    
    ## 응답 예시
    
    ### 대기 중
    ```json
    {
      "result": "success",
      "task": {
        "id": "550e8400-e29b-41d4-a716-446655440000",
        "type": "video_generation",
        "status": "pending",
        "created_at": "2024-01-01T12:00:00",
        "progress": 0
      },
      "queue_position": 2
    }
    ```
    
    ### 처리 중
    ```json
    {
      "result": "success",
      "task": {
        "id": "550e8400-e29b-41d4-a716-446655440000",
        "type": "video_generation",
        "status": "processing",
        "started_at": "2024-01-01T12:05:00",
        "progress": 45
      }
    }
    ```
    
    ### 완료
    ```json
    {
      "result": "success",
      "task": {
        "id": "550e8400-e29b-41d4-a716-446655440000",
        "type": "video_generation",
        "status": "completed",
        "completed_at": "2024-01-01T12:10:00",
        "progress": 100,
        "result": {
          "output_video": "output/final_edit_1.mp4",
          "record_id": 1
        }
      }
    }
    ```
    """,
    response_description="태스크의 현재 상태와 진행 정보를 반환합니다.",
    tags=["Task Management"]
)
def get_task_status(task_id: str):
    """태스크 상태를 조회합니다."""
    
    # 메모리 큐에서 상태 조회
    queue = get_task_queue()
    task_status = queue.get_task_status(task_id)
    
    if not task_status:
        # DB에서 조회 (워커 재시작 등의 경우)
        db_task = get_task_info(task_id)
        if not db_task:
            raise HTTPException(status_code=404, detail="해당 태스크를 찾을 수 없습니다.")
        
        return {
            "result": "success",
            "task": {
                "id": task_id,
                "type": db_task.get("type"),
                "status": db_task.get("status"),
                "created_at": db_task.get("created_at"),
                "updated_at": db_task.get("updated_at"),
                "result": db_task.get("result"),
                "error": db_task.get("error")
            },
            "source": "database"
        }
    
    # 큐 위치 계산 (pending 상태인 경우)
    queue_position = None
    if task_status["status"] == "pending":
        queue_status = queue.get_queue_status()
        queue_position = queue_status["pending"]
    
    return {
        "result": "success",
        "task": task_status,
        "queue_position": queue_position,
        "source": "memory"
    }

@router.get("/queue_status",
    summary="🔄 태스크 큐 상태 조회",
    description="""
    **전체 태스크 큐의 현재 상태를 조회합니다.**
    
    ## 주요 정보
    - 큐 실행 상태 (실행 중/중지)
    - 대기 중인 태스크 수
    - 처리 중인 태스크 수
    - 완료/실패한 태스크 수
    - 전체 태스크 수
    
    ## 응답 예시
    ```json
    {
      "result": "success",
      "queue": {
        "is_running": true,
        "queue_size": 3,
        "total_tasks": 15,
        "pending": 3,
        "processing": 1,
        "completed": 10,
        "failed": 1
      },
      "recent_tasks": [
        {
          "id": "task-1",
          "type": "video_generation",
          "status": "completed",
          "created_at": "2024-01-01T12:00:00"
        }
      ]
    }
    ```
    """,
    response_description="태스크 큐의 전체 상태 정보를 반환합니다.",
    tags=["Task Management"]
)
def get_queue_status():
    """태스크 큐 상태를 조회합니다."""
    
    queue = get_task_queue()
    queue_status = queue.get_queue_status()
    all_tasks = queue.get_all_tasks()
    
    # 최근 태스크들 (최대 10개)
    recent_tasks = sorted(
        all_tasks.values(),
        key=lambda x: x.get("created_at", ""),
        reverse=True
    )[:10]
    
    return {
        "result": "success",
        "queue": queue_status,
        "recent_tasks": recent_tasks
    }

@router.delete("/task/{task_id}",
    summary="🗑️ 태스크 삭제",
    description="""
    **특정 태스크를 삭제합니다.**
    
    ## 주의사항
    - 처리 중인 태스크는 삭제할 수 없습니다
    - 완료된 태스크의 결과 파일은 별도로 삭제해야 합니다
    - 삭제된 태스크는 복구할 수 없습니다
    
    ## 응답 예시
    ```json
    {
      "result": "success",
      "message": "태스크가 삭제되었습니다.",
      "task_id": "550e8400-e29b-41d4-a716-446655440000"
    }
    ```
    """,
    response_description="삭제 결과를 반환합니다.",
    tags=["Task Management"]
)
def delete_task(task_id: str):
    """태스크를 삭제합니다."""
    
    queue = get_task_queue()
    task_status = queue.get_task_status(task_id)
    
    if not task_status:
        raise HTTPException(status_code=404, detail="해당 태스크를 찾을 수 없습니다.")
    
    if task_status["status"] == "processing":
        raise HTTPException(status_code=400, detail="처리 중인 태스크는 삭제할 수 없습니다.")
    
    # 메모리에서 삭제
    with queue._lock:
        if task_id in queue.tasks:
            del queue.tasks[task_id]
    
    # DB에서 삭제
    delete_task_info(task_id)
    
    return {
        "result": "success",
        "message": "태스크가 삭제되었습니다.",
        "task_id": task_id
    }

@router.post("/video_generate", 
    summary="AI 기반 비디오 생성 (스크립트 자동 매칭)",
    description="""
    **스크립트를 기반으로 자동으로 영상을 찾아서 비디오를 생성합니다.**
    
    ## 주요 기능
    - 스크립트를 AI 임베딩으로 검색하여 가장 적합한 영상 자동 선택
    - TTS를 통한 자막 음성 생성
    - 중복 영상 방지 및 세로 영상 필터링 옵션
    - 생성 이력 자동 저장
    - 🧹 자동 자원 정리 (FFmpeg 프로세스 누수 방지)
    
    ## 사용 예시
    ```json
    {
      "story": [
        {
          "scene": 1,
          "script": "아름다운 바다 풍경과 석양",
          "subtitle": "오늘은 정말 아름다운 하루였습니다.",
          "actor_name": "현주"
        },
        {
          "scene": 2,
          "script": "도시의 야경과 불빛들",
          "subtitle": "밤이 되면서 도시가 빛나기 시작했습니다.",
          "actor_name": "지윤"
        }
      ]
    }
    ```
    
    ## 옵션 설명
    - **avoid_duplicates**: 같은 영상이 여러 씬에서 사용되는 것을 방지
    - **filter_vertical**: 세로 영상(세로가 가로보다 긴)을 제외하고 검색
    - **max_search_results**: 검색할 후보 영상의 최대 개수 (1-50)
    - **actor_name**: TTS 음성 액터 (현주, 지윤, 한준, 진우, 찬구 중 선택, 기본값: 현주)
    """,
    response_description="생성된 비디오 정보와 기록 ID를 반환합니다.",
    tags=["Video Generation"]
)
def edit_video(
    story_req: StoryRequest,
    avoid_duplicates: bool = Query(False, description="중복 영상 방지 여부"),
    filter_vertical: bool = Query(False, description="세로 영상 필터링 여부"),
    max_search_results: int = Query(10, description="최대 검색 결과 수", ge=1, le=50)
):
    try:
        # 기존 로직 실행
        return _async_edit_video(
            story_req_dict=story_req.model_dump(),
            avoid_duplicates=avoid_duplicates,
            filter_vertical=filter_vertical,
            max_search_results=max_search_results,
            task_id=None
        )
    except Exception as e:
        # 에러 발생 시에도 자원 정리
        try:
            cleanup_video_resources()
        except:
            pass
        raise HTTPException(status_code=500, detail=f"비디오 생성 중 오류: {e}")

@router.get("/video_history",
    summary="비디오 생성 히스토리 조회",
    description="""
    **이전에 생성된 모든 비디오들의 히스토리를 조회합니다.**
    
    ## 주요 기능
    - 최신 생성 순으로 정렬된 기록 반환
    - 페이지네이션 지원 (offset, limit)
    - 각 기록의 상세 정보 포함 (원본 요청, 생성 옵션, 파일 경로 등)
    
    ## 사용 예시
    ```
    GET /api/ai/video_history?limit=10&offset=0
    ```
    
    ## 응답 예시
    ```json
    {
      "result": "success",
      "total_count": 25,
      "returned_count": 10,
      "offset": 0,
      "limit": 10,
      "history": [
        {
          "id": 1,
          "output_path": "output/final_edit_1.mp4",
          "created_at": "2024-01-01T12:00:00",
          "story_request": {...},
          "generation_options": {...},
          "video_infos": [...]
        }
      ]
    }
    ```
    """,
    response_description="비디오 생성 히스토리 목록을 반환합니다.",
    tags=["Video History"]
)
def get_video_history(
    limit: Optional[int] = Query(None, description="가져올 기록 수 제한", ge=1),
    offset: Optional[int] = Query(0, description="건너뛸 기록 수", ge=0)
):
    """
    이전에 생성된 비디오들의 히스토리를 가져옵니다.
    """
    try:
        all_records = get_video_generation_history()
        
        # 최신순으로 정렬 (created_at 기준 내림차순)
        sorted_records = sorted(
            all_records, 
            key=lambda x: x.get('created_at', ''), 
            reverse=True
        )
        
        # offset과 limit 적용
        if offset:
            sorted_records = sorted_records[offset:]
        
        if limit:
            sorted_records = sorted_records[:limit]
        
        # 각 레코드에 doc_id 추가 (TinyDB의 내부 ID)
        for record in sorted_records:
            if hasattr(record, 'doc_id'):
                record['id'] = record.doc_id
        
        return {
            "result": "success",
            "total_count": len(all_records),
            "returned_count": len(sorted_records),
            "offset": offset,
            "limit": limit,
            "history": sorted_records
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"히스토리 조회 중 오류: {e}")

@router.get("/video_history/{record_id}",
    summary="특정 비디오 생성 기록 상세 조회",
    description="""
    **특정 ID의 비디오 생성 기록을 상세하게 조회합니다.**
    
    ## 주요 기능
    - 특정 기록의 모든 상세 정보 반환
    - 파일 존재 여부 확인
    - 원본 요청 데이터 및 생성 옵션 포함
    
    ## 사용 예시
    ```
    GET /api/ai/video_history/1
    ```
    
    ## 응답 예시
    ```json
    {
      "result": "success",
      "record": {
        "id": 1,
        "output_path": "output/final_edit_1.mp4",
        "created_at": "2024-01-01T12:00:00",
        "story_request": {
          "story": [
            {
              "scene": 1,
              "script": "바다 풍경",
              "subtitle": "아름다운 바다입니다"
            }
          ]
        },
        "generation_options": {
          "avoid_duplicates": true,
          "filter_vertical": false
        },
        "video_infos": [...]
      },
      "file_exists": true
    }
    ```
    """,
    response_description="특정 비디오 생성 기록의 상세 정보를 반환합니다.",
    tags=["Video History"]
)
def get_video_by_id(record_id: int):
    """
    특정 ID의 비디오 생성 기록을 가져옵니다.
    """
    try:
        record = get_video_generation_by_id(record_id)
        
        if not record:
            raise HTTPException(status_code=404, detail="해당 ID의 기록을 찾을 수 없습니다.")
        
        # doc_id 추가
        record['id'] = record_id
        
        # 파일 존재 여부 확인
        output_path = record.get('output_path')
        file_exists = os.path.exists(output_path) if output_path else False
        
        return {
            "result": "success",
            "record": record,
            "file_exists": file_exists
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"기록 조회 중 오류: {e}")

@router.post("/video_regenerate/{record_id}",
    summary="이전 기록으로 비디오 재생성",
    description="""
    **이전에 저장된 기록의 StoryRequest를 사용하여 새로운 옵션으로 비디오를 다시 생성합니다.**
    
    ## 주요 기능
    - 이전 기록의 원본 요청 데이터 재사용
    - 새로운 생성 옵션 적용 가능
    - 같은 스토리로 다른 영상 조합 생성
    
    ## 사용 예시
    ```
    POST /api/ai/video_regenerate/1?avoid_duplicates=true&filter_vertical=true
    ```
    
    ## 응답 예시
    ```json
    {
      "result": "success",
      "output_video": "output/final_edit_2.mp4",
      "record_id": 2,
      "options_used": {
        "avoid_duplicates": true,
        "filter_vertical": true,
        "max_search_results": 10
      },
      "videos_used": ["video1.mp4", "video2.mp4"]
    }
    ```
    
    ## 장점
    - 이전 스토리를 다른 설정으로 빠르게 재생성
    - A/B 테스트나 옵션 비교에 유용
    - 수동으로 요청 데이터를 다시 입력할 필요 없음
    """,
    response_description="재생성된 비디오 정보를 반환합니다.",
    tags=["Video Generation", "Video History"]
)
def regenerate_video_from_history(
    record_id: int,
    avoid_duplicates: bool = Query(False, description="중복 영상 방지 여부"),
    filter_vertical: bool = Query(False, description="세로 영상 필터링 여부"),
    max_search_results: int = Query(10, description="최대 검색 결과 수", ge=1, le=50)
):
    """
    이전 기록의 StoryRequest를 사용하여 비디오를 다시 생성합니다.
    """
    try:
        # 기존 기록 조회
        record = get_video_generation_by_id(record_id)
        
        if not record:
            raise HTTPException(status_code=404, detail="해당 ID의 기록을 찾을 수 없습니다.")
        
        # 원본 StoryRequest 데이터 추출
        story_request = record.get('story_request')
        if not story_request:
            raise HTTPException(status_code=400, detail="해당 기록에 원본 StoryRequest 데이터가 없습니다.")
        
        # StoryRequest 객체로 변환
        story_req = StoryRequest(**story_request)
        
        # 기존 edit_video 함수 로직 재사용
        return edit_video(
            story_req=story_req,
            avoid_duplicates=avoid_duplicates,
            filter_vertical=filter_vertical,
            max_search_results=max_search_results
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"비디오 재생성 중 오류: {e}")

@router.delete("/video_history/{record_id}",
    summary="비디오 생성 기록 삭제",
    description="""
    **특정 ID의 비디오 생성 기록을 삭제합니다.**
    
    ## 주요 기능
    - DB에서 생성 기록 완전 삭제
    - 옵션으로 실제 비디오 파일도 함께 삭제 가능
    - 안전한 삭제 (존재하지 않는 기록 처리)
    
    ## 사용 예시
    ```
    # 기록만 삭제 (파일은 유지)
    DELETE /api/ai/video_history/1
    
    # 기록과 파일 모두 삭제
    DELETE /api/ai/video_history/1?delete_file=true
    ```
    
    ## 응답 예시
    ```json
    {
      "result": "success",
      "message": "기록 ID 1가 삭제되었습니다.",
      "file_deleted": true
    }
    ```
    
    ## 주의사항
    - delete_file=true 시 실제 비디오 파일이 영구 삭제됩니다
    - 삭제된 기록은 복구할 수 없습니다
    - 파일 삭제 실패 시에도 기록은 삭제됩니다
    """,
    response_description="삭제 결과를 반환합니다.",
    tags=["Video History"]
)
def delete_video_record(record_id: int, delete_file: bool = Query(False, description="실제 파일도 삭제할지 여부")):
    """
    특정 ID의 비디오 생성 기록을 삭제합니다.
    """
    try:
        record = get_video_generation_by_id(record_id)
        
        if not record:
            raise HTTPException(status_code=404, detail="해당 ID의 기록을 찾을 수 없습니다.")
        
        # 실제 파일 삭제 옵션
        if delete_file:
            output_path = record.get('output_path')
            if output_path and os.path.exists(output_path):
                try:
                    os.remove(output_path)
                except Exception as e:
                    print(f"파일 삭제 중 오류: {output_path} - {e}")
        
        # DB에서 기록 삭제
        from src.db import video_db
        video_db.remove(doc_ids=[record_id])
        
        return {
            "result": "success",
            "message": f"기록 ID {record_id}가 삭제되었습니다.",
            "file_deleted": delete_file
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"기록 삭제 중 오류: {e}")

@router.post("/video_generate_custom",
    summary="커스텀 비디오 생성 (직접 파일 지정)",
    description="""
    **비디오 파일을 직접 지정하여 영상을 생성합니다.**
    
    ## 주요 기능
    - AI 검색 없이 원하는 비디오 파일 직접 선택
    - 파일 존재 여부 자동 확인
    - 누락된 파일 건너뛰기 옵션
    - 완전한 제어와 예측 가능한 결과
    
    ## 사용 예시
    ```json
    {
      "story": [
        {
          "scene": 1,
          "video_file_name": "beach_sunset.mp4",
          "subtitle": "아름다운 석양이 바다를 물들입니다.",
          "script": "바다 석양 풍경",
          "actor_name": "현주"
        },
        {
          "scene": 2,
          "video_file_name": "city_night.mp4",
          "subtitle": "도시의 밤이 시작됩니다.",
          "actor_name": "한준"
        }
      ]
    }
    ```
    
    ## 옵션 설명
    - **skip_missing_files**: true 시 존재하지 않는 파일의 씬을 건너뛰고 계속 진행
    - **actor_name**: TTS 음성 액터 (현주, 지윤, 한준, 진우, 찬구 중 선택, 기본값: 현주)
    
    ## 응답 예시
    ```json
    {
      "result": "success",
      "output_video": "output/final_edit_3.mp4",
      "record_id": 3,
      "options_used": {
        "generation_type": "custom",
        "skip_missing_files": false
      },
      "skipped_scenes": null,
      "processed_scenes": 2
    }
    ```
    
    ## 장점
    - 정확히 원하는 영상으로 비디오 생성
    - AI 검색 결과에 의존하지 않음
    - 빠른 처리 속도
    """,
    response_description="생성된 커스텀 비디오 정보를 반환합니다.",
    tags=["Video Generation", "Custom"]
)
def edit_video_custom(
    story_req: CustomStoryRequest,
    skip_missing_files: bool = Query(False, description="존재하지 않는 파일 건너뛰기")
):
    """
    비디오 파일을 직접 지정하여 영상을 생성합니다.
    """
    original_story_request = story_req.model_dump()
    
    generation_options = {
        "generation_type": "custom",
        "skip_missing_files": skip_missing_files
    }
    
    story_req_dict = story_req.model_dump()
    
    video_infos = []
    skipped_scenes = []
    
    for scene in story_req_dict["story"]:
        video_file_name = scene["video_file_name"]
        video_path = f"uploads/{video_file_name}"
        
        # 파일 존재 여부 확인
        if not os.path.exists(video_path):
            if skip_missing_files:
                skipped_scenes.append({
                    "scene": scene["scene"],
                    "file_name": video_file_name,
                    "reason": "파일이 존재하지 않음"
                })
                continue
            else:
                raise HTTPException(
                    status_code=404, 
                    detail=f"Scene {scene['scene']}: 파일 '{video_file_name}'을 찾을 수 없습니다."
                )
        
        # TTS 생성
        actor_name = scene.get("actor_name", "현주")
        audio_path = generate_typecast_tts_audio(scene["subtitle"], actor_name)
        
        # video_infos에 정보 추가
        video_infos.append({
            "path": video_path,
            "audio_path": audio_path,
            "text": scene["subtitle"],
            "scene": scene["scene"],
            "script": scene.get("script", ""),
            "custom_selected": True
        })
    
    if not video_infos:
        raise HTTPException(status_code=400, detail="처리할 수 있는 비디오가 없습니다.")
    
    # 영상 합성
    output_path = get_next_output_path()
    try:
        create_composite_video(video_infos, output_path)
        
        # DB에 저장
        record_id = save_video_generation_info(
            output_path=output_path,
            video_infos=video_infos,
            story_request=original_story_request,
            generation_options=generation_options
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"비디오 합성 중 오류: {e}")
    
    return {
        "result": "success",
        "output_video": output_path,
        "record_id": record_id,
        "options_used": generation_options,
        "skipped_scenes": skipped_scenes if skipped_scenes else None,
        "processed_scenes": len(video_infos)
    }

@router.post("/video_generate_flexible",
    summary="유연한 비디오 생성 (다중 선택 방식)",
    description="""
    **다양한 방식으로 비디오를 선택하여 영상을 생성합니다.**
    
    ## 지원하는 선택 방식
    1. **직접 파일 지정**: `video_file_name`으로 정확한 파일명 지정
    2. **스크립트 검색**: `script`로 AI 임베딩 검색
    3. **키워드 검색**: `search_keywords` 배열로 다중 키워드 검색
    
    ## 사용 예시
    ```json
    {
      "story": [
        {
          "scene": 1,
          "subtitle": "직접 지정한 영상입니다.",
          "video_file_name": "specific_video.mp4",
          "actor_name": "현주"
        },
        {
          "scene": 2,
          "subtitle": "스크립트로 검색한 영상입니다.",
          "script": "아름다운 자연 풍경과 산",
          "actor_name": "지윤"
        },
        {
          "scene": 3,
          "subtitle": "키워드로 검색한 영상입니다.",
          "search_keywords": ["도시", "야경", "불빛", "건물"],
          "actor_name": "진우"
        }
      ]
    }
    ```
    
    ## 옵션 설명
    - **avoid_duplicates**: 중복 영상 방지
    - **filter_vertical**: 세로 영상 제외
    - **max_search_results**: 검색 후보 수 (1-50)
    - **skip_unresolved**: 해결되지 않는 씬 건너뛰기
    - **actor_name**: TTS 음성 액터 (현주, 지윤, 한준, 진우, 찬구 중 선택, 기본값: 현주)
    
    ## 응답 예시
    ```json
    {
      "result": "success",
      "output_video": "output/final_edit_4.mp4",
      "record_id": 4,
      "options_used": {
        "generation_type": "flexible",
        "avoid_duplicates": true,
        "filter_vertical": false
      },
      "videos_used": ["video1.mp4", "video2.mp4"],
      "skipped_scenes": [],
      "processed_scenes": 3
    }
    ```
    
    ## 장점
    - 한 요청에서 여러 선택 방식 조합 가능
    - 최대한의 유연성과 제어
    - 각 씬별로 최적의 선택 방식 적용
    """,
    response_description="생성된 유연한 비디오 정보를 반환합니다.",
    tags=["Video Generation", "Flexible"]
)
def edit_video_flexible(
    story_req: FlexibleStoryRequest,
    avoid_duplicates: bool = Query(False, description="중복 영상 방지 여부"),
    filter_vertical: bool = Query(False, description="세로 영상 필터링 여부"),
    max_search_results: int = Query(10, description="최대 검색 결과 수", ge=1, le=50),
    skip_unresolved: bool = Query(False, description="해결되지 않는 씬 건너뛰기")
):
    """
    다양한 방식으로 비디오를 선택하여 영상을 생성합니다.
    - video_file_name: 직접 파일명 지정
    - script: 스크립트로 검색
    - search_keywords: 키워드들로 검색
    """
    original_story_request = story_req.model_dump()
    
    generation_options = {
        "generation_type": "flexible",
        "avoid_duplicates": avoid_duplicates,
        "filter_vertical": filter_vertical,
        "max_search_results": max_search_results,
        "skip_unresolved": skip_unresolved
    }
    
    story_req_dict = story_req.model_dump()
    
    video_infos = []
    used_videos = set()
    skipped_scenes = []
    
    for scene in story_req_dict["story"]:
        file_name = None
        metadata = {}
        selection_method = None
        
        try:
            # 1. 직접 파일명이 지정된 경우
            if scene.get("video_file_name"):
                selection_method = "direct_file"
                file_name = scene["video_file_name"]
                video_path = f"uploads/{file_name}"
                
                if not os.path.exists(video_path):
                    raise ValueError(f"파일 '{file_name}'을 찾을 수 없습니다.")
                
                # 옵션 체크
                if avoid_duplicates and file_name in used_videos:
                    raise ValueError("중복된 영상입니다.")
                if filter_vertical and is_vertical_video(video_path):
                    raise ValueError("세로 영상입니다.")
            
            # 2. 스크립트로 검색
            elif scene.get("script"):
                selection_method = "script_search"
                file_name, metadata = select_video_with_options(
                    script=scene["script"],
                    used_videos=used_videos,
                    avoid_duplicates=avoid_duplicates,
                    filter_vertical=filter_vertical,
                    max_search_results=max_search_results
                )
            
            # 3. 키워드들로 검색
            elif scene.get("search_keywords"):
                selection_method = "keyword_search"
                # 키워드들을 결합하여 검색 쿼리 생성
                search_query = " ".join(scene["search_keywords"])
                file_name, metadata = select_video_with_options(
                    script=search_query,
                    used_videos=used_videos,
                    avoid_duplicates=avoid_duplicates,
                    filter_vertical=filter_vertical,
                    max_search_results=max_search_results
                )
            
            else:
                raise ValueError("video_file_name, script, search_keywords 중 하나는 제공되어야 합니다.")
            
            # 사용된 영상 추가
            if avoid_duplicates:
                used_videos.add(file_name)
            
        except Exception as e:
            if skip_unresolved:
                skipped_scenes.append({
                    "scene": scene["scene"],
                    "reason": str(e),
                    "selection_method": selection_method
                })
                continue
            else:
                raise HTTPException(
                    status_code=400,
                    detail=f"Scene {scene['scene']}: {str(e)}"
                )
        
        # TTS 생성
        actor_name = scene.get("actor_name", "현주")
        audio_path = generate_typecast_tts_audio(scene["subtitle"], actor_name)
        
        # video_infos에 정보 추가
        video_infos.append({
            "path": f"uploads/{file_name}",
            "audio_path": audio_path,
            "text": scene["subtitle"],
            "scene": scene["scene"],
            "script": scene.get("script", ""),
            "search_keywords": scene.get("search_keywords"),
            "selection_method": selection_method,
            "metadata": metadata
        })
    
    if not video_infos:
        raise HTTPException(status_code=400, detail="처리할 수 있는 비디오가 없습니다.")
    
    # 영상 합성
    output_path = get_next_output_path()
    try:
        create_composite_video(video_infos, output_path)
        
        # DB에 저장
        record_id = save_video_generation_info(
            output_path=output_path,
            video_infos=video_infos,
            story_request=original_story_request,
            generation_options=generation_options
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"비디오 합성 중 오류: {e}")
    
    return {
        "result": "success",
        "output_video": output_path,
        "record_id": record_id,
        "options_used": generation_options,
        "videos_used": list(used_videos) if avoid_duplicates else None,
        "skipped_scenes": skipped_scenes if skipped_scenes else None,
        "processed_scenes": len(video_infos)
    }

@router.post("/video_generate_mixed",
    summary="혼합 비디오 생성 (다양한 씬 타입 조합)",
    description="""
    **다양한 타입의 씬들을 자유롭게 혼합하여 영상을 생성합니다.**
    
    ## 지원하는 씬 타입
    1. **Scene**: 기본 AI 검색 방식 (`script` + `subtitle`)
    2. **CustomScene**: 직접 파일 지정 (`video_file_name` + `subtitle`)
    3. **FlexibleScene**: 다중 선택 방식 (위의 모든 방식 지원)
    
    ## 사용 예시
    ```json
    [
      {
        "scene": 1,
        "script": "바다와 석양",
        "subtitle": "AI가 선택한 바다 영상입니다.",
        "actor_name": "현주"
      },
      {
        "scene": 2,
        "video_file_name": "my_video.mp4",
        "subtitle": "직접 지정한 영상입니다.",
        "actor_name": "지윤"
      },
      {
        "scene": 3,
        "search_keywords": ["산", "자연", "녹색"],
        "subtitle": "키워드로 찾은 산 영상입니다.",
        "actor_name": "한준"
      },
      {
        "scene": 4,
        "script": "도시 야경",
        "subtitle": "마지막 도시 영상입니다.",
        "actor_name": "진우"
      }
    ]
    ```
    
    ## 고급 기능
    - **씬 타입 자동 감지**: 각 씬의 필드를 분석하여 적절한 처리 방식 자동 선택
    - **유연한 구조**: 배열 형태로 순서대로 씬 정의
    - **모든 옵션 지원**: 중복 방지, 세로 영상 필터링 등 모든 기능 사용 가능
    - **actor_name 지원**: 각 씬별로 다른 TTS 음성 액터 선택 가능 (현주, 지윤, 한준, 진우, 찬구)
    
    ## 응답 예시
    ```json
    {
      "result": "success",
      "output_video": "output/final_edit_5.mp4",
      "record_id": 5,
      "options_used": {
        "generation_type": "mixed",
        "avoid_duplicates": true,
        "filter_vertical": true
      },
      "videos_used": ["video1.mp4", "my_video.mp4", "video3.mp4"],
      "skipped_scenes": [],
      "processed_scenes": 4
    }
    ```
    
    ## 장점
    - 가장 자유로운 형태의 비디오 생성
    - 복잡한 프로젝트에 최적
    - 모든 선택 방식의 장점을 하나의 요청에서 활용
    """,
    response_description="생성된 혼합 비디오 정보를 반환합니다.",
    tags=["Video Generation", "Advanced", "Mixed"]
)
def edit_video_mixed(
    scenes: List[Union[Scene, CustomScene, FlexibleScene]],
    avoid_duplicates: bool = Query(False, description="중복 영상 방지 여부"),
    filter_vertical: bool = Query(False, description="세로 영상 필터링 여부"),
    max_search_results: int = Query(10, description="최대 검색 결과 수", ge=1, le=50),
    skip_unresolved: bool = Query(False, description="해결되지 않는 씬 건너뛰기")
):
    """
    다양한 타입의 씬들을 혼합하여 영상을 생성합니다.
    각 씬은 Scene, CustomScene, FlexibleScene 중 하나의 형식을 가질 수 있습니다.
    """
    original_request = [scene.dict() if hasattr(scene, 'dict') else scene for scene in scenes]
    
    generation_options = {
        "generation_type": "mixed",
        "avoid_duplicates": avoid_duplicates,
        "filter_vertical": filter_vertical,
        "max_search_results": max_search_results,
        "skip_unresolved": skip_unresolved
    }
    
    video_infos = []
    used_videos = set()
    skipped_scenes = []
    
    for i, scene in enumerate(scenes):
        # Pydantic 모델을 딕셔너리로 변환
        if hasattr(scene, 'model_dump'):
            scene = scene.model_dump()
        elif hasattr(scene, 'dict'):
            scene = scene.dict()
        else:
            scene = scene
        
        file_name = None
        metadata = {}
        selection_method = None
        
        try:
            # Scene 타입 감지 및 처리
            if "video_file_name" in scene and scene.get("video_file_name"):
                selection_method = "direct_file"
                file_name = scene["video_file_name"]
                video_path = f"uploads/{file_name}"
                
                if not os.path.exists(video_path):
                    raise ValueError(f"파일 '{file_name}'을 찾을 수 없습니다.")
                
                if avoid_duplicates and file_name in used_videos:
                    raise ValueError("중복된 영상입니다.")
                if filter_vertical and is_vertical_video(video_path):
                    raise ValueError("세로 영상입니다.")
            
            elif "search_keywords" in scene and scene.get("search_keywords"):
                selection_method = "keyword_search"
                search_query = " ".join(scene["search_keywords"])
                file_name, metadata = select_video_with_options(
                    script=search_query,
                    used_videos=used_videos,
                    avoid_duplicates=avoid_duplicates,
                    filter_vertical=filter_vertical,
                    max_search_results=max_search_results
                )
            
            elif "script" in scene and scene.get("script"):
                selection_method = "script_search"
                file_name, metadata = select_video_with_options(
                    script=scene["script"],
                    used_videos=used_videos,
                    avoid_duplicates=avoid_duplicates,
                    filter_vertical=filter_vertical,
                    max_search_results=max_search_results
                )
            
            else:
                raise ValueError("유효한 비디오 선택 방법이 제공되지 않았습니다.")
            
            # 사용된 영상 추가
            if avoid_duplicates:
                used_videos.add(file_name)
            
        except Exception as e:
            if skip_unresolved:
                skipped_scenes.append({
                    "scene": scene.get("scene", i + 1),
                    "reason": str(e),
                    "selection_method": selection_method
                })
                continue
            else:
                raise HTTPException(
                    status_code=400,
                    detail=f"Scene {scene.get('scene', i + 1)}: {str(e)}"
                )
        
        # TTS 생성
        actor_name = scene.get("actor_name", "현주")
        audio_path = generate_typecast_tts_audio(scene["subtitle"], actor_name)
        
        # video_infos에 정보 추가
        video_infos.append({
            "path": f"uploads/{file_name}",
            "audio_path": audio_path,
            "text": scene["subtitle"],
            "scene": scene.get("scene", i + 1),
            "script": scene.get("script", ""),
            "search_keywords": scene.get("search_keywords"),
            "video_file_name": scene.get("video_file_name"),
            "selection_method": selection_method,
            "metadata": metadata
        })
    
    if not video_infos:
        raise HTTPException(status_code=400, detail="처리할 수 있는 비디오가 없습니다.")
    
    # 영상 합성
    output_path = get_next_output_path()
    try:
        create_composite_video(video_infos, output_path)
        
        # DB에 저장
        record_id = save_video_generation_info(
            output_path=output_path,
            video_infos=video_infos,
            story_request={"scenes": original_request},
            generation_options=generation_options
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"비디오 합성 중 오류: {e}")
    
    return {
        "result": "success",
        "output_video": output_path,
        "record_id": record_id,
        "options_used": generation_options,
        "videos_used": list(used_videos) if avoid_duplicates else None,
        "skipped_scenes": skipped_scenes if skipped_scenes else None,
        "processed_scenes": len(video_infos)
    }