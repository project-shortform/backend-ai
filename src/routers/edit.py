"""
비디오 AI 생성 및 관리 API

이 모듈은 다양한 방식으로 비디오를 생성하고 관리하는 API를 제공합니다.

## 주요 API 엔드포인트

### 🎬 비디오 생성 API
1. **POST /api/ai/video_generate** - AI 기반 비디오 생성 (스크립트 자동 매칭)
2. **POST /api/ai/video_generate_mixed** - 혼합 비디오 생성 (다양한 씬 타입 조합)

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
from src.lib.tts import generate_gemini_tts_audio
from src.lib.edit import create_composite_video, cleanup_video_resources
from src.db import (
    save_video_generation_info,
    get_video_generation_history,
    get_video_generation_by_id,
)
from src.db import (
    save_task_info,
    update_task_info,
    get_task_info,
    get_all_tasks,
    delete_task_info,
)  # 태스크 DB 함수들
from src.task_queue import get_task_queue, TaskStatus  # 태스크 큐
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


class CustomScene(BaseModel):
    scene: int
    video_file_name: str  # 직접 지정할 비디오 파일명
    subtitle: str
    script: Optional[str] = None  # 선택적 스크립트 (기록용)


class CustomStoryRequest(BaseModel):
    story: List[CustomScene]


class FlexibleScene(BaseModel):
    scene: int
    subtitle: str
    # 비디오 선택 방식 중 하나
    video_file_name: Optional[str] = None  # 직접 파일명 지정
    script: Optional[str] = None  # 스크립트로 검색
    search_keywords: Optional[List[str]] = None  # 키워드 리스트로 검색


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
    max_search_results: int = 10,
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
        detail="조건을 만족하는 영상을 찾을 수 없습니다. (중복 방지 또는 세로 영상 필터링으로 인해 제외됨)",
    )


# 비동기 처리를 위한 래퍼 함수들
def _async_edit_video(
    story_req_dict: dict,
    avoid_duplicates: bool = False,
    filter_vertical: bool = False,
    max_search_results: int = 10,
    voice_name: Optional[str] = "Zephyr",
    task_id: str = None,
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
            "async_processing": True,
        }

        total_scenes = len(story_req_dict["story"])
        video_infos = []
        used_videos = set()

        # Step 1: TTS 변환 및 비디오 선택 (0-40%)
        if task_id:
            update_task_info(
                task_id,
                {
                    "status": TaskStatus.PROCESSING.value,
                    "progress": 0,
                    "current_step": "TTS 변환 및 비디오 선택",
                    "step_details": f"0/{total_scenes} 씬 처리 완료",
                },
            )

        for idx, scene in enumerate(story_req_dict["story"]):
            try:
                # 옵션에 따라 영상 선택
                file_name, metadata = select_video_with_options(
                    script=scene["script"],
                    used_videos=used_videos,
                    avoid_duplicates=avoid_duplicates,
                    filter_vertical=filter_vertical,
                    max_search_results=max_search_results,
                )

                # 사용된 영상 목록에 추가
                if avoid_duplicates:
                    used_videos.add(file_name)

            except Exception as e:
                raise Exception(f"Scene {scene['scene']}: {str(e)}")

            # subtitle을 TTS로 변환
            print(f"TTS 보이스: {voice_name}")
            audio_path = generate_gemini_tts_audio(scene["subtitle"], voice_name)

            # video_infos에 정보 추가
            video_infos.append(
                {
                    "path": f"uploads/{file_name}",
                    "audio_path": audio_path,
                    "text": scene["subtitle"],
                    "scene": scene["scene"],
                    "script": scene["script"],
                }
            )

            # TTS 단계 진행 상황 업데이트
            if task_id:
                current_progress = int((idx + 1) * 40 / total_scenes)
                update_task_info(
                    task_id,
                    {
                        "progress": current_progress,
                        "current_step": "TTS 변환 및 비디오 선택",
                        "step_details": f"{idx + 1}/{total_scenes} 씬 처리 완료",
                    },
                )

        # Step 2: 비디오 합성 시작 (40-95%)
        if task_id:
            update_task_info(
                task_id,
                {
                    "progress": 40,
                    "current_step": "비디오 합성",
                    "step_details": "비디오 합성을 시작합니다...",
                },
            )

        # 영상과 오디오, 자막 합치기
        output_path = get_next_output_path()

        def progress_callback(step_progress, step_detail):
            """비디오 합성 진행 상황 콜백"""
            if task_id:
                # 40% ~ 95% 범위에서 진행
                video_progress = int(40 + (step_progress * 55 / 100))
                update_task_info(
                    task_id,
                    {
                        "progress": video_progress,
                        "current_step": "비디오 합성",
                        "step_details": step_detail,
                    },
                )

        try:
            create_composite_video(
                video_infos, output_path, progress_callback=progress_callback
            )
        finally:
            # 비디오 처리 후 자원 정리
            cleanup_video_resources()

        # Step 3: 완료 (95-100%)
        if task_id:
            update_task_info(
                task_id,
                {
                    "progress": 100,
                    "current_step": "완료",
                    "step_details": "비디오 생성이 완료되었습니다.",
                },
            )

        # DB에 생성 정보 저장
        record_id = save_video_generation_info(
            output_path=output_path,
            video_infos=video_infos,
            story_request=original_story_request,
            generation_options=generation_options,
        )

        # 태스크 완료 정보 업데이트
        if task_id:
            update_task_info(
                task_id,
                {
                    "status": TaskStatus.COMPLETED.value,
                    "result": {
                        "output_video": output_path,
                        "record_id": record_id,
                        "options_used": generation_options,
                        "videos_used": list(used_videos) if avoid_duplicates else None,
                    },
                },
            )

        return {
            "result": "success",
            "output_video": output_path,
            "record_id": record_id,
            "options_used": generation_options,
            "videos_used": list(used_videos) if avoid_duplicates else None,
        }

    except Exception as e:
        # 에러 발생 시에도 자원 정리
        try:
            cleanup_video_resources()
        except:
            pass

        # 태스크 실패 정보 업데이트
        if task_id:
            update_task_info(
                task_id,
                {
                    "status": TaskStatus.FAILED.value,
                    "error": {"message": str(e), "type": "video_generation_error"},
                },
            )
        raise e


def _async_edit_video_mixed(
    scenes_data: list,
    avoid_duplicates: bool = False,
    filter_vertical: bool = False,
    max_search_results: int = 10,
    skip_unresolved: bool = False,
    voice_name: Optional[str] = "Zephyr",
    task_id: str = None,
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
            "voice_name": voice_name,
            "async_processing": True,
        }

        total_scenes = len(scenes_data)
        video_infos = []
        used_videos = set()
        skipped_scenes = []

        # Step 1: TTS 변환 및 비디오 선택 (0-40%)
        if task_id:
            update_task_info(
                task_id,
                {
                    "status": TaskStatus.PROCESSING.value,
                    "progress": 0,
                    "current_step": "TTS 변환 및 비디오 선택",
                    "step_details": f"0/{total_scenes} 씬 처리 완료",
                },
            )

        processed_scenes = 0
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
                        max_search_results=max_search_results,
                    )

                elif "script" in scene and scene.get("script"):
                    selection_method = "script_search"
                    file_name, metadata = select_video_with_options(
                        script=scene["script"],
                        used_videos=used_videos,
                        avoid_duplicates=avoid_duplicates,
                        filter_vertical=filter_vertical,
                        max_search_results=max_search_results,
                    )

                else:
                    raise ValueError("유효한 비디오 선택 방법이 제공되지 않았습니다.")

                # 사용된 영상 추가
                if avoid_duplicates:
                    used_videos.add(file_name)

            except Exception as e:
                if skip_unresolved:
                    skipped_scenes.append(
                        {
                            "scene": scene.get("scene", i + 1),
                            "reason": str(e),
                            "selection_method": selection_method,
                        }
                    )
                    continue
                else:
                    raise Exception(f"Scene {scene.get('scene', i + 1)}: {str(e)}")

            # TTS 생성 (전체 설정 voice_name 사용)
            audio_path = generate_gemini_tts_audio(scene["subtitle"], voice_name)

            # video_infos에 정보 추가
            video_infos.append(
                {
                    "path": f"uploads/{file_name}",
                    "audio_path": audio_path,
                    "text": scene["subtitle"],
                    "scene": scene.get("scene", i + 1),
                    "script": scene.get("script", ""),
                    "search_keywords": scene.get("search_keywords"),
                    "video_file_name": scene.get("video_file_name"),
                    "selection_method": selection_method,
                    "metadata": metadata,
                }
            )

            processed_scenes += 1

            # TTS 단계 진행 상황 업데이트
            if task_id:
                current_progress = int(processed_scenes * 40 / total_scenes)
                update_task_info(
                    task_id,
                    {
                        "progress": current_progress,
                        "current_step": "TTS 변환 및 비디오 선택",
                        "step_details": f"{processed_scenes}/{total_scenes} 씬 처리 완료 (스킵: {len(skipped_scenes)})",
                    },
                )

        if not video_infos:
            raise Exception("처리할 수 있는 비디오가 없습니다.")

        # Step 2: 비디오 합성 시작 (40-95%)
        if task_id:
            update_task_info(
                task_id,
                {
                    "progress": 40,
                    "current_step": "비디오 합성",
                    "step_details": "비디오 합성을 시작합니다...",
                },
            )

        # 영상 합성
        output_path = get_next_output_path()

        def progress_callback(step_progress, step_detail):
            """비디오 합성 진행 상황 콜백"""
            if task_id:
                # 40% ~ 95% 범위에서 진행
                video_progress = int(40 + (step_progress * 55 / 100))
                update_task_info(
                    task_id,
                    {
                        "progress": video_progress,
                        "current_step": "비디오 합성",
                        "step_details": step_detail,
                    },
                )

        try:
            create_composite_video(
                video_infos, output_path, progress_callback=progress_callback
            )
        finally:
            # 비디오 처리 후 자원 정리
            cleanup_video_resources()

        # Step 3: 완료 (95-100%)
        if task_id:
            update_task_info(
                task_id,
                {
                    "progress": 100,
                    "current_step": "완료",
                    "step_details": "비디오 생성이 완료되었습니다.",
                },
            )

        # DB에 저장
        record_id = save_video_generation_info(
            output_path=output_path,
            video_infos=video_infos,
            story_request={"scenes": original_request},
            generation_options=generation_options,
        )

        # 태스크 완료 정보 업데이트
        if task_id:
            update_task_info(
                task_id,
                {
                    "status": TaskStatus.COMPLETED.value,
                    "result": {
                        "output_video": output_path,
                        "record_id": record_id,
                        "options_used": generation_options,
                        "videos_used": list(used_videos) if avoid_duplicates else None,
                        "skipped_scenes": skipped_scenes if skipped_scenes else None,
                        "processed_scenes": len(video_infos),
                    },
                },
            )

        return {
            "result": "success",
            "output_video": output_path,
            "record_id": record_id,
            "options_used": generation_options,
            "videos_used": list(used_videos) if avoid_duplicates else None,
            "skipped_scenes": skipped_scenes if skipped_scenes else None,
            "processed_scenes": len(video_infos),
        }

    except Exception as e:
        # 에러 발생 시에도 자원 정리
        try:
            cleanup_video_resources()
        except:
            pass

        # 태스크 실패 정보 업데이트
        if task_id:
            update_task_info(
                task_id,
                {
                    "status": TaskStatus.FAILED.value,
                    "error": {
                        "message": str(e),
                        "type": "mixed_video_generation_error",
                    },
                },
            )
        raise e


@router.post(
    "/video_generate_async",
    summary="🚀 비동기 AI 기반 비디오 생성",
    description="""
    **스크립트를 기반으로 비동기적으로 영상을 생성합니다.**
    
    ## 주요 기능
    - 🔄 백그라운드에서 비디오 생성 처리
    - 📊 실시간 진행 상태 추적 (0-100%)
    - ⚡ 즉시 태스크 ID 반환
    - 🎯 큐 기반 순차 처리
    - 🤖 AI 기반 영상 자동 매칭
    - 🔊 TTS(Text-To-Speech) 기반 음성 생성
    - 🎬 자동 비디오-오디오 동기화
    - 📝 자막 자동 삽입
    
    ## 처리 흐름
    1. **요청 접수**: 즉시 태스크 ID 반환
    2. **큐 대기**: 다른 작업 완료 후 순차 처리
    3. **Step 1 (0-40%)**: TTS 변환 및 비디오 선택
       - 각 씬의 script를 기반으로 AI가 적절한 영상 검색
       - subtitle을 TTS로 변환하여 음성 파일 생성
       - 진행 표시: "2/3 씬 처리 완료"
    4. **Step 2 (40-95%)**: 비디오 합성
       - 선택된 비디오를 오디오 길이에 맞춰 정확히 조정
       - TTS 음성과 비디오 동기화
       - 자막 삽입 및 해상도 통일
       - 진행 표시: "클립 2/3 처리 완료"
    5. **Step 3 (95-100%)**: 최종 완료
       - 모든 클립을 하나의 영상으로 연결
       - 결과 파일 저장 및 DB 기록
    
    ## 입력 데이터 구조
    ```json
    {
      "story": [
        {
          "scene": 1,
          "script": "아름다운 바다 풍경과 석양",
          "subtitle": "오늘은 정말 아름다운 하루였습니다."
        },
        {
          "scene": 2,
          "script": "도시의 야경과 네온사인",
          "subtitle": "밤이 되면 도시는 더욱 아름다워집니다."
        }
      ]
    }
    ```
    
    - **scene**: 씬 번호 (순서대로 처리됨)
    - **script**: AI가 영상 검색에 사용할 텍스트 (검색 키워드 역할)
    - **subtitle**: 화면에 표시될 자막 및 TTS 변환 대상 텍스트
    
    ## 옵션 설정
    
    ### Query Parameters
    - **voice_name**: TTS 보이스 ("Zephyr", "Charon" 등)
    - **avoid_duplicates**: 중복 영상 방지 (true/false)
    - **filter_vertical**: 세로 영상 필터링 (true/false)
    - **max_search_results**: 최대 검색 결과 수 (1-50)
    
    ### 사용 예시
    ```
    POST /api/ai/video_generate_async?voice_name=Zephyr&avoid_duplicates=true&filter_vertical=false&max_search_results=10
    ```
    
    ## 응답 예시
    
    ### 요청 성공
    ```json
    {
      "result": "success",
      "task_id": "550e8400-e29b-41d4-a716-446655440000",
      "status": "pending",
      "message": "비디오 생성 작업이 큐에 추가되었습니다.",
      "queue_position": 2,
      "estimated_wait_time": "4-10분"
    }
    ```
    
    ### 완료된 태스크 조회 결과
    ```json
    {
      "result": "success",
      "task": {
        "status": "completed",
        "progress": 100,
        "result": {
          "output_video": "output/final_edit_86.mp4",
          "record_id": 37,
          "options_used": {
            "avoid_duplicates": true,
            "filter_vertical": false,
            "max_search_results": 10,
            "async_processing": true
          },
          "videos_used": [
            "sunset_beach.mp4",
            "city_night.mp4",
            "nature_scene.mp4"
          ]
        },
        "progress_info": {
          "percentage": 100,
          "current_step": "완료",
          "step_details": "비디오 생성이 완료되었습니다."
        }
      }
    }
    ```
    
    ## 진행 상황 확인
    반환된 `task_id`로 `/api/ai/task_status/{task_id}` 엔드포인트에서 실시간 진행 상황을 확인할 수 있습니다.
    
    ### 폴링 방법
    ```javascript
    // JavaScript 예시
    const checkProgress = async (taskId) => {
      const response = await fetch(`/api/ai/task_status/${taskId}`);
      const data = await response.json();
      
      console.log(`진행률: ${data.task.progress}%`);
      console.log(`현재 단계: ${data.task.current_step}`);
      console.log(`상세: ${data.task.step_details}`);
      
      if (data.task.status === 'completed') {
        console.log('완료!', data.task.result.output_video);
      } else if (data.task.status === 'processing') {
        setTimeout(() => checkProgress(taskId), 2000); // 2초 후 재확인
      }
    };
    ```
    """,
    response_description="태스크 ID와 초기 상태를 반환합니다.",
    tags=["Video Generation", "Async"],
)
def edit_video_async(
    story_req: StoryRequest,
    voice_name: Optional[str] = "Zephyr",
    avoid_duplicates: bool = Query(False, description="중복 영상 방지 여부"),
    filter_vertical: bool = Query(False, description="세로 영상 필터링 여부"),
    max_search_results: int = Query(10, description="최대 검색 결과 수", ge=1, le=50),
):
    """비동기적으로 비디오를 생성합니다."""

    # 태스크 큐 가져오기
    queue = get_task_queue()

    # 태스크를 큐에 추가
    task_id = queue.add_task(
        task_func=_async_edit_video,
        task_kwargs={
            "story_req_dict": story_req.model_dump(),
            "voice_name": voice_name,
            "avoid_duplicates": avoid_duplicates,
            "filter_vertical": filter_vertical,
            "max_search_results": max_search_results,
            "task_id": None,  # 나중에 설정됨
        },
        task_type="video_generation",
    )

    # 태스크 ID를 함수 인자에 추가
    task_info = queue.get_task_status(task_id)
    if task_info:
        with queue._lock:
            queue.tasks[task_id]["kwargs"]["task_id"] = task_id

    # DB에 태스크 정보 저장
    save_task_info(
        task_id,
        {
            "type": "video_generation",
            "status": TaskStatus.PENDING.value,
            "request_data": story_req.model_dump(),
            "options": {
                "avoid_duplicates": avoid_duplicates,
                "filter_vertical": filter_vertical,
                "max_search_results": max_search_results,
                "voice_name": voice_name,
            },
        },
    )

    # 큐 상태 조회
    queue_status = queue.get_queue_status()

    return {
        "result": "success",
        "task_id": task_id,
        "status": "pending",
        "message": "비디오 생성 작업이 큐에 추가되었습니다.",
        "queue_position": queue_status["pending"],
        "estimated_wait_time": f"{queue_status['pending'] * 2-5}분",  # 대략적인 예상 시간
    }


@router.post(
    "/video_generate_mixed_async",
    summary="🚀 비동기 혼합 비디오 생성",
    description="""
    **다양한 타입의 씬들을 비동기적으로 혼합하여 영상을 생성합니다.**
    
    ## 주요 기능
    - 🔄 백그라운드에서 복잡한 혼합 비디오 처리
    - 📊 실시간 진행 상태 추적 (0-100%)
    - ⚡ 즉시 태스크 ID 반환
    - 🎯 모든 씬 타입 지원 (Scene, CustomScene, FlexibleScene)
    - 🎬 유연한 비디오 선택 방식 (AI 검색, 직접 지정, 키워드 검색)
    - 🎵 통일된 TTS 음성 적용
    - 🔍 스킵 기능 (해결되지 않는 씬 자동 건너뛰기)
    
    ## 처리 흐름
    1. **요청 접수**: 즉시 태스크 ID 반환
    2. **큐 대기**: 다른 작업 완료 후 순차 처리
    3. **Step 1 (0-40%)**: TTS 변환 및 비디오 선택 (각 씬별 진행)
    4. **Step 2 (40-95%)**: 비디오 합성 (각 클립별 진행)
    5. **Step 3 (95-100%)**: 최종 완료 및 결과 저장
    
    ## 지원되는 씬 타입
    
    ### 1. Scene (AI 자동 선택)
    ```json
    {
      "scene": 1,
      "script": "아름다운 바다 풍경과 석양",
      "subtitle": "오늘은 정말 아름다운 하루였습니다."
    }
    ```
    - **script**: AI가 이 텍스트를 기반으로 적절한 영상 자동 선택
    - **subtitle**: 화면에 표시될 자막 텍스트
    
    ### 2. CustomScene (직접 파일 지정)
    ```json
    {
      "scene": 2,
      "video_file_name": "sunset_beach.mp4",
      "subtitle": "직접 선택한 바다 영상입니다.",
      "script": "바다 영상 (기록용)"
    }
    ```
    - **video_file_name**: uploads/ 폴더의 정확한 파일명
    - **script**: 선택사항 (기록 목적)
    
    ### 3. FlexibleScene (키워드 검색)
    ```json
    {
      "scene": 3,
      "search_keywords": ["자연", "풍경", "산"],
      "subtitle": "키워드로 검색한 자연 영상입니다."
    }
    ```
    - **search_keywords**: 검색에 사용할 키워드 리스트
    
    ## 사용 예시
    
    ### 혼합 씬 타입 사용
    ```json
    [
      {
        "scene": 1,
        "script": "바다와 석양",
        "subtitle": "AI가 선택한 바다 영상입니다."
      },
      {
        "scene": 2,
        "video_file_name": "my_custom_video.mp4",
        "subtitle": "직접 지정한 영상입니다."
      },
      {
        "scene": 3,
        "search_keywords": ["도시", "밤", "네온"],
        "subtitle": "키워드로 찾은 도시 영상입니다."
      }
    ]
    ```
    
    ### 옵션 설정 예시
    ```
    POST /api/ai/video_generate_mixed_async?voice_name=Zephyr&avoid_duplicates=true&filter_vertical=true&skip_unresolved=true
    ```
    
    ## 응답 예시
    
    ### 요청 성공
    ```json
    {
      "result": "success",
      "task_id": "550e8400-e29b-41d4-a716-446655440001",
      "status": "pending",
      "message": "혼합 비디오 생성 작업이 큐에 추가되었습니다.",
      "queue_position": 1,
      "estimated_wait_time": "3-7분"
    }
    ```
    
    ### 완료된 태스크 조회 결과
    ```json
    {
      "result": "success",
      "task": {
        "status": "completed",
        "progress": 100,
        "result": {
          "output_video": "output/final_edit_86.mp4",
          "record_id": 37,
          "options_used": {
            "generation_type": "mixed",
            "voice_name": "Zephyr",
            "avoid_duplicates": true,
            "skip_unresolved": true
          },
          "videos_used": ["video1.mp4", "video2.mp4"],
          "skipped_scenes": null,
          "processed_scenes": 3
        }
      }
    }
    ```
    """,
    response_description="태스크 ID와 초기 상태를 반환합니다.",
    tags=["Video Generation", "Async", "Mixed"],
)
def edit_video_mixed_async(
    scenes: List[Union[Scene, CustomScene, FlexibleScene]],
    voice_name: Optional[str] = Query("Zephyr", description="Gemini TTS 보이스 이름"),
    avoid_duplicates: bool = Query(False, description="중복 영상 방지 여부"),
    filter_vertical: bool = Query(False, description="세로 영상 필터링 여부"),
    max_search_results: int = Query(10, description="최대 검색 결과 수", ge=1, le=50),
    skip_unresolved: bool = Query(False, description="해결되지 않는 씬 건너뛰기"),
):
    """비동기적으로 혼합 비디오를 생성합니다."""

    # 씬 데이터를 딕셔너리로 변환
    scenes_data = []
    for scene_data in scenes:
        if hasattr(scene_data, "model_dump"):
            scenes_data.append(scene_data.model_dump())
        elif hasattr(scene_data, "dict"):
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
            "voice_name": voice_name,
            "avoid_duplicates": avoid_duplicates,
            "filter_vertical": filter_vertical,
            "max_search_results": max_search_results,
            "skip_unresolved": skip_unresolved,
            "task_id": None,  # 나중에 설정됨
        },
        task_type="mixed_video_generation",
    )

    # 태스크 ID를 함수 인자에 추가
    task_info = queue.get_task_status(task_id)
    if task_info:
        with queue._lock:
            queue.tasks[task_id]["kwargs"]["task_id"] = task_id

    # DB에 태스크 정보 저장
    save_task_info(
        task_id,
        {
            "type": "mixed_video_generation",
            "status": TaskStatus.PENDING.value,
            "request_data": {"scenes": scenes_data},
            "options": {
                "voice_name": voice_name,
                "avoid_duplicates": avoid_duplicates,
                "filter_vertical": filter_vertical,
                "max_search_results": max_search_results,
                "skip_unresolved": skip_unresolved,
            },
        },
    )

    # 큐 상태 조회
    queue_status = queue.get_queue_status()

    return {
        "result": "success",
        "task_id": task_id,
        "status": "pending",
        "message": "혼합 비디오 생성 작업이 큐에 추가되었습니다.",
        "queue_position": queue_status["pending"],
        "estimated_wait_time": f"{queue_status['pending'] * 3-7}분",  # 혼합 비디오는 더 오래 걸림
    }


@router.get(
    "/task_status/{task_id}",
    summary="📊 태스크 상태 조회",
    description="""
    **특정 태스크의 현재 상태와 진행 상황을 조회합니다.**
    
    ## 태스크 상태
    - **pending**: 대기 중 (큐에서 순서를 기다리는 중)
    - **processing**: 처리 중 (실제 비디오 생성 작업 수행 중)
    - **completed**: 완료 (비디오 생성 완료, 결과 확인 가능)
    - **failed**: 실패 (에러 발생, 에러 메시지 확인 가능)
    
    ## 진행 단계 세부 사항
    
    ### 1단계: TTS 변환 및 비디오 선택 (0-40%)
    - 각 씬의 스크립트를 기반으로 비디오 검색 및 선택
    - 자막 텍스트를 TTS(Text-To-Speech)로 변환
    - 중복 영상 방지 및 세로 영상 필터링 적용
    - **진행 표시**: "2/3 씬 처리 완료" 형태로 표시
    
    ### 2단계: 비디오 합성 (40-95%)
    - 선택된 비디오 클립들의 길이를 오디오에 맞춰 조정
    - 각 클립에 TTS 오디오와 자막 합성
    - 해상도 통일 및 프레임레이트 정규화
    - **진행 표시**: "클립 2/3 처리 완료" 형태로 표시
    
    ### 3단계: 최종 완료 (95-100%)
    - 모든 클립을 하나의 비디오로 연결
    - 결과 파일 저장 및 DB 기록
    - 자원 정리 및 완료 처리
    
    ## 응답 예시
    
    ### 대기 중
    ```json
    {
      "result": "success",
      "task": {
        "id": "550e8400-e29b-41d4-a716-446655440000",
        "type": "video_generation",
        "status": "pending",
        "created_at": "2025-09-08T22:00:00.000000",
        "progress": 0,
        "progress_info": {
          "percentage": 0,
          "current_step": "대기 중",
          "step_details": ""
        }
      },
      "queue_position": 2,
      "source": "memory"
    }
    ```
    
    ### TTS 변환 및 비디오 선택 중
    ```json
    {
      "result": "success",
      "task": {
        "id": "550e8400-e29b-41d4-a716-446655440000",
        "type": "video_generation",
        "status": "processing",
        "started_at": "2025-09-08T22:01:00.000000",
        "progress": 27,
        "current_step": "TTS 변환 및 비디오 선택",
        "step_details": "2/3 씬 처리 완료",
        "progress_info": {
          "percentage": 27,
          "current_step": "TTS 변환 및 비디오 선택",
          "step_details": "2/3 씬 처리 완료"
        }
      },
      "source": "memory"
    }
    ```
    
    ### 비디오 합성 중
    ```json
    {
      "result": "success",
      "task": {
        "id": "550e8400-e29b-41d4-a716-446655440000",
        "type": "video_generation",
        "status": "processing",
        "progress": 74,
        "current_step": "비디오 합성",
        "step_details": "클립 2/3 처리 완료",
        "progress_info": {
          "percentage": 74,
          "current_step": "비디오 합성",
          "step_details": "클립 2/3 처리 완료"
        }
      },
      "source": "memory"
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
        "created_at": "2025-09-08T22:00:00.000000",
        "started_at": "2025-09-08T22:01:00.000000",
        "completed_at": "2025-09-08T22:05:30.000000",
        "progress": 100,
        "current_step": "완료",
        "step_details": "비디오 생성이 완료되었습니다.",
        "result": {
          "result": "success",
          "output_video": "output/final_edit_86.mp4",
          "record_id": 37,
          "options_used": {
            "avoid_duplicates": true,
            "filter_vertical": false,
            "max_search_results": 10,
            "async_processing": true
          },
          "videos_used": [
            "video1.mp4",
            "video2.mp4",
            "video3.mp4"
          ]
        },
        "progress_info": {
          "percentage": 100,
          "current_step": "완료",
          "step_details": "비디오 생성이 완료되었습니다."
        }
      },
      "source": "memory"
    }
    ```
    
    ### 실패
    ```json
    {
      "result": "success",
      "task": {
        "id": "550e8400-e29b-41d4-a716-446655440000",
        "type": "video_generation",
        "status": "failed",
        "created_at": "2025-09-08T22:00:00.000000",
        "started_at": "2025-09-08T22:01:00.000000",
        "completed_at": "2025-09-08T22:02:15.000000",
        "progress": 25,
        "error": {
          "message": "Scene 2: 조건을 만족하는 영상을 찾을 수 없습니다.",
          "type": "video_generation_error"
        },
        "current_step": "TTS 변환 및 비디오 선택",
        "step_details": "1/3 씬 처리 완료",
        "progress_info": {
          "percentage": 25,
          "current_step": "TTS 변환 및 비디오 선택",
          "step_details": "1/3 씬 처리 완료"
        }
      },
      "source": "memory"
    }
    ```
    """,
    response_description="태스크의 현재 상태와 진행 정보를 반환합니다.",
    tags=["Task Management"],
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
            raise HTTPException(
                status_code=404, detail="해당 태스크를 찾을 수 없습니다."
            )

        # DB 태스크 정보 포맷팅
        db_task_formatted = {
            "id": task_id,
            "type": db_task.get("type"),
            "status": db_task.get("status"),
            "created_at": db_task.get("created_at"),
            "updated_at": db_task.get("updated_at"),
            "result": db_task.get("result"),
            "error": db_task.get("error"),
            "progress_info": {
                "percentage": db_task.get(
                    "progress", 100 if db_task.get("status") == "completed" else 0
                ),
                "current_step": db_task.get(
                    "current_step",
                    "완료" if db_task.get("status") == "completed" else "알 수 없음",
                ),
                "step_details": db_task.get("step_details", ""),
            },
        }

        return {
            "result": "success",
            "task": db_task_formatted,
            "source": "database",
        }

    # 큐 위치 계산 (pending 상태인 경우)
    queue_position = None
    if task_status["status"] == "pending":
        queue_status = queue.get_queue_status()
        queue_position = queue_status["pending"]

    # 진행 상황 정보 포맷팅
    formatted_task = {
        **task_status,
        "progress_info": {
            "percentage": task_status.get("progress", 0),
            "current_step": task_status.get("current_step", "대기 중"),
            "step_details": task_status.get("step_details", ""),
        },
    }

    return {
        "result": "success",
        "task": formatted_task,
        "queue_position": queue_position,
        "source": "memory",
    }


@router.get(
    "/queue_status",
    summary="🔄 태스크 큐 상태 조회",
    description="""
    **전체 태스크 큐의 현재 상태를 조회합니다.**
    
    ## 주요 정보
    - **큐 실행 상태**: 워커 스레드 동작 여부
    - **대기 중인 태스크**: 큐에서 처리를 기다리는 태스크 수
    - **처리 중인 태스크**: 현재 실행 중인 태스크 수 (최대 1개)
    - **완료/실패한 태스크**: 처리 완료된 태스크 통계
    - **최근 태스크**: 최근 10개 태스크의 상태 정보
    
    ## 용도
    - 시스템 부하 상태 확인
    - 대기 시간 예측
    - 큐 성능 모니터링
    - 문제 진단 및 디버깅
    
    ## 응답 예시
    
    ### 정상 동작 중
    ```json
    {
      "result": "success",
      "queue": {
        "is_running": true,
        "queue_size": 2,
        "total_tasks": 25,
        "pending": 2,
        "processing": 1,
        "completed": 20,
        "failed": 2
      },
      "recent_tasks": [
        {
          "id": "550e8400-e29b-41d4-a716-446655440000",
          "type": "video_generation",
          "status": "completed",
          "created_at": "2025-09-08T22:05:00.000000",
          "progress": 100,
          "result": {
            "output_video": "output/final_edit_86.mp4"
          }
        },
        {
          "id": "550e8400-e29b-41d4-a716-446655440001",
          "type": "mixed_video_generation",
          "status": "processing",
          "created_at": "2025-09-08T22:06:00.000000",
          "progress": 65,
          "current_step": "비디오 합성"
        }
      ]
    }
    ```
    
    ### 큐 비어있음
    ```json
    {
      "result": "success",
      "queue": {
        "is_running": true,
        "queue_size": 0,
        "total_tasks": 0,
        "pending": 0,
        "processing": 0,
        "completed": 0,
        "failed": 0
      },
      "recent_tasks": []
    }
    ```
    
    ## 상태 해석
    - **queue_size > 5**: 높은 부하, 대기 시간 증가 예상
    - **processing = 0**: 워커가 유휴 상태 또는 문제 발생
    - **failed 비율 높음**: 시스템 문제 가능성
    - **is_running = false**: 워커 스레드 중지됨 (재시작 필요)
    """,
    response_description="태스크 큐의 전체 상태 정보를 반환합니다.",
    tags=["Task Management"],
)
def get_queue_status():
    """태스크 큐 상태를 조회합니다."""

    queue = get_task_queue()
    queue_status = queue.get_queue_status()
    all_tasks = queue.get_all_tasks()

    # 최근 태스크들 (최대 10개)
    recent_tasks = sorted(
        all_tasks.values(), key=lambda x: x.get("created_at", ""), reverse=True
    )[:10]

    return {"result": "success", "queue": queue_status, "recent_tasks": recent_tasks}


@router.delete(
    "/task/{task_id}",
    summary="🗑️ 태스크 삭제",
    description="""
    **특정 태스크를 삭제합니다.**
    
    ## 주의사항
    - ⚠️ **처리 중인 태스크는 삭제할 수 없습니다** (safety 보장)
    - 📁 완료된 태스크의 결과 비디오 파일은 별도로 삭제해야 합니다
    - 🗑️ 삭제된 태스크는 복구할 수 없습니다
    - 💾 DB에서도 함께 삭제됩니다
    
    ## 삭제 가능한 상태
    - ✅ **pending**: 대기 중인 태스크
    - ✅ **completed**: 완료된 태스크
    - ✅ **failed**: 실패한 태스크
    - ❌ **processing**: 처리 중인 태스크 (삭제 불가)
    
    ## 사용 케이스
    - 불필요한 대기 중 태스크 제거
    - 실패한 태스크 정리
    - 완료된 태스크 기록 정리
    - 큐 관리 및 최적화
    
    ## 응답 예시
    
    ### 삭제 성공
    ```json
    {
      "result": "success",
      "message": "태스크가 삭제되었습니다.",
      "task_id": "550e8400-e29b-41d4-a716-446655440000"
    }
    ```
    
    ### 삭제 실패 (처리 중)
    ```json
    {
      "detail": "처리 중인 태스크는 삭제할 수 없습니다."
    }
    ```
    
    ### 삭제 실패 (존재하지 않음)
    ```json
    {
      "detail": "해당 태스크를 찾을 수 없습니다."
    }
    ```
    """,
    response_description="삭제 결과를 반환합니다.",
    tags=["Task Management"],
)
def delete_task(task_id: str):
    """태스크를 삭제합니다."""

    queue = get_task_queue()
    task_status = queue.get_task_status(task_id)

    if not task_status:
        raise HTTPException(status_code=404, detail="해당 태스크를 찾을 수 없습니다.")

    if task_status["status"] == "processing":
        raise HTTPException(
            status_code=400, detail="처리 중인 태스크는 삭제할 수 없습니다."
        )

    # 메모리에서 삭제
    with queue._lock:
        if task_id in queue.tasks:
            del queue.tasks[task_id]

    # DB에서 삭제
    delete_task_info(task_id)

    return {
        "result": "success",
        "message": "태스크가 삭제되었습니다.",
        "task_id": task_id,
    }


@router.get(
    "/video_history",
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
    tags=["Video History"],
)
def get_video_history(
    limit: Optional[int] = Query(None, description="가져올 기록 수 제한", ge=1),
    offset: Optional[int] = Query(0, description="건너뛸 기록 수", ge=0),
):
    """
    이전에 생성된 비디오들의 히스토리를 가져옵니다.
    """
    try:
        all_records = get_video_generation_history()

        # 최신순으로 정렬 (created_at 기준 내림차순)
        sorted_records = sorted(
            all_records, key=lambda x: x.get("created_at", ""), reverse=True
        )

        # offset과 limit 적용
        if offset:
            sorted_records = sorted_records[offset:]

        if limit:
            sorted_records = sorted_records[:limit]

        # 각 레코드에 doc_id 추가 (TinyDB의 내부 ID)
        for record in sorted_records:
            if hasattr(record, "doc_id"):
                record["id"] = record.doc_id

        return {
            "result": "success",
            "total_count": len(all_records),
            "returned_count": len(sorted_records),
            "offset": offset,
            "limit": limit,
            "history": sorted_records,
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"히스토리 조회 중 오류: {e}")


@router.get(
    "/video_history/{record_id}",
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
    tags=["Video History"],
)
def get_video_by_id(record_id: int):
    """
    특정 ID의 비디오 생성 기록을 가져옵니다.
    """
    try:
        record = get_video_generation_by_id(record_id)

        if not record:
            raise HTTPException(
                status_code=404, detail="해당 ID의 기록을 찾을 수 없습니다."
            )

        # doc_id 추가
        record["id"] = record_id

        # 파일 존재 여부 확인
        output_path = record.get("output_path")
        file_exists = os.path.exists(output_path) if output_path else False

        return {"result": "success", "record": record, "file_exists": file_exists}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"기록 조회 중 오류: {e}")


@router.delete(
    "/video_history/{record_id}",
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
    tags=["Video History"],
)
def delete_video_record(
    record_id: int,
    delete_file: bool = Query(False, description="실제 파일도 삭제할지 여부"),
):
    """
    특정 ID의 비디오 생성 기록을 삭제합니다.
    """
    try:
        record = get_video_generation_by_id(record_id)

        if not record:
            raise HTTPException(
                status_code=404, detail="해당 ID의 기록을 찾을 수 없습니다."
            )

        # 실제 파일 삭제 옵션
        if delete_file:
            output_path = record.get("output_path")
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
            "file_deleted": delete_file,
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"기록 삭제 중 오류: {e}")
