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
) -> tuple[str, dict, bool]:
    """
    옵션에 따라 적절한 영상을 선택합니다.

    Args:
        script: 검색할 스크립트
        used_videos: 이미 사용된 영상들의 파일명 집합
        avoid_duplicates: 중복 영상 방지 여부
        filter_vertical: 세로 영상 필터링 여부
        max_search_results: 최대 검색 결과 수

    Returns:
        tuple: (선택된 파일명, 메타데이터, 중복 여부)
    """
    search_result = search_chroma(script, n_results=max_search_results)

    if (
        not search_result["documents"]
        or not search_result["documents"][0]
        or not search_result["metadatas"]
        or not search_result["metadatas"][0]
    ):
        raise HTTPException(status_code=404, detail="해당하는 영상을 찾을 수 없습니다.")

    first_valid_video = None  # 첫 번째 유효한 영상 (중복이어도)
    is_duplicate = False

    # 검색 결과를 순회하면서 조건에 맞는 영상 찾기
    for i, metadata in enumerate(search_result["metadatas"][0]):
        file_name = metadata.get("file_name")

        if not file_name:
            continue

        video_path = f"uploads/{file_name}"

        # 파일 존재 여부 확인
        if not os.path.exists(video_path):
            continue

        # 세로 영상 필터링
        if filter_vertical and is_vertical_video(video_path):
            continue

        # 첫 번째 유효한 영상 저장 (중복 체크 전)
        if first_valid_video is None:
            first_valid_video = (file_name, metadata)

        # 중복 영상 체크
        if avoid_duplicates and file_name in used_videos:
            # 중복이면 계속 검색
            continue

        # 조건을 만족하는 영상 발견 (중복 아님)
        return file_name, metadata, False

    # 중복되지 않은 영상을 찾지 못한 경우
    if first_valid_video is not None:
        # 중복이지만 사용 가능한 영상이 있으면 경고와 함께 반환
        file_name, metadata = first_valid_video
        if avoid_duplicates and file_name in used_videos:
            print(f"⚠️ 경고: 중복 영상 사용 - {file_name}")
            return file_name, metadata, True
        return file_name, metadata, False

    # 조건을 만족하는 영상이 전혀 없는 경우
    raise HTTPException(
        status_code=404,
        detail="조건을 만족하는 영상을 찾을 수 없습니다. (세로 영상 필터링 또는 파일 없음)",
    )


# 비동기 처리를 위한 래퍼 함수들
def _async_edit_video(
    story_req_dict: dict,
    avoid_duplicates: bool = False,
    filter_vertical: bool = False,
    max_search_results: int = 10,
    voice: Optional[str] = "Zephyr",
    background_music_path: Optional[str] = None,
    tts_volume: float = 1.0,
    background_music_volume: float = 0.2,
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

        video_infos = []
        used_videos = set()

        total_scenes = len(story_req_dict["story"])

        # 비디오 선택 및 TTS 생성 단계 (0-30%)
        for i, scene in enumerate(story_req_dict["story"]):
            scene_num = i + 1

            # 비디오 선택 단계 (각 씬당 15% 할당)
            if task_id:
                select_progress = int((i * 15) / total_scenes)
                update_task_info(
                    task_id,
                    {
                        "progress": select_progress,
                        "current_step": f"씬 {scene_num}/{total_scenes}: 영상 선택 중...",
                    },
                )

            try:
                # 옵션에 따라 영상 선택
                file_name, metadata, is_duplicate = select_video_with_options(
                    script=scene["script"],
                    used_videos=used_videos,
                    avoid_duplicates=avoid_duplicates,
                    filter_vertical=filter_vertical,
                    max_search_results=max_search_results,
                )

                # 중복 영상 경고 처리
                if is_duplicate and avoid_duplicates:
                    if task_id:
                        update_task_info(
                            task_id,
                            {
                                "progress": select_progress,
                                "current_step": f"씬 {scene_num}/{total_scenes}: ⚠️ 중복 영상 사용 - {file_name}",
                            },
                        )

                # 사용된 영상 목록에 추가
                if avoid_duplicates:
                    used_videos.add(file_name)

            except Exception as e:
                raise Exception(f"Scene {scene['scene']}: {str(e)}")

            # TTS 생성 단계 (각 씬당 15% 할당, 15-30%)
            if task_id:
                tts_progress = 15 + int((i * 15) / total_scenes)
                update_task_info(
                    task_id,
                    {
                        "progress": tts_progress,
                        "current_step": f"씬 {scene_num}/{total_scenes}: 음성 생성 중...",
                    },
                )

            print(f"🎤 씬 {scene_num}/{total_scenes} TTS 음성 생성: {voice}")
            audio_path = generate_gemini_tts_audio(scene["subtitle"], voice)

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

            # 씬 준비 완료
            if task_id:
                ready_progress = 15 + int(((i + 1) * 15) / total_scenes)
                update_task_info(
                    task_id,
                    {
                        "progress": ready_progress,
                        "current_step": f"씬 {scene_num}/{total_scenes}: 준비 완료",
                    },
                )

        # 영상과 오디오, 자막 합치기
        output_path = get_next_output_path()

        # 진행도 콜백 함수 정의 (30-100% 범위로 매핑)
        def progress_callback(progress: int, step: str):
            """진행 상황을 태스크 DB에 업데이트 (30-100% 범위)"""
            if task_id:
                # create_composite_video의 0-100%를 30-100%로 변환
                adjusted_progress = 30 + int((progress * 70) / 100)
                update_task_info(
                    task_id,
                    {
                        "progress": adjusted_progress,
                        "current_step": f"비디오 합성: {step}",
                    },
                )

        try:
            create_composite_video(
                video_infos,
                output_path,
                progress_callback=progress_callback,
                background_music_path=background_music_path,
                tts_volume=tts_volume,
                background_music_volume=background_music_volume,
            )
        finally:
            # 비디오 처리 후 자원 정리
            cleanup_video_resources()

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
                    "progress": 100,
                    "current_step": "비디오 생성 완료",
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
    voice: Optional[str] = "Zephyr",
    background_music_path: Optional[str] = None,
    tts_volume: float = 1.0,
    background_music_volume: float = 0.2,
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
            "voice": voice,
            "async_processing": True,
        }

        video_infos = []
        used_videos = set()
        skipped_scenes = []

        total_scenes = len(scenes_data)

        # 비디오 선택 및 TTS 생성 단계 (0-30%)
        for i, scene in enumerate(scenes_data):
            scene_num = scene.get("scene", i + 1)
            file_name = None
            metadata = {}
            selection_method = None

            # 비디오 선택 단계 (각 씬당 15% 할당)
            if task_id:
                select_progress = int((i * 15) / total_scenes)
                update_task_info(
                    task_id,
                    {
                        "progress": select_progress,
                        "current_step": f"씬 {scene_num}/{total_scenes}: 영상 선택 중...",
                    },
                )

            try:
                # Scene 타입 감지 및 처리
                if "video_file_name" in scene and scene.get("video_file_name"):
                    selection_method = "direct_file"
                    file_name = scene["video_file_name"]
                    video_path = f"uploads/{file_name}"

                    if not os.path.exists(video_path):
                        raise ValueError(f"파일 '{file_name}'을 찾을 수 없습니다.")

                    # 중복 영상 경고 (예외 발생 안 함)
                    if avoid_duplicates and file_name in used_videos:
                        print(
                            f"⚠️ 씬 {scene_num}: 중복 영상 사용 (직접 지정) - {file_name}"
                        )
                        if task_id:
                            update_task_info(
                                task_id,
                                {
                                    "progress": select_progress,
                                    "current_step": f"씬 {scene_num}/{total_scenes}: ⚠️ 중복 영상 사용 (직접 지정)",
                                },
                            )

                    if filter_vertical and is_vertical_video(video_path):
                        raise ValueError("세로 영상입니다.")

                elif "search_keywords" in scene and scene.get("search_keywords"):
                    selection_method = "keyword_search"
                    search_query = " ".join(scene["search_keywords"])
                    file_name, metadata, is_duplicate = select_video_with_options(
                        script=search_query,
                        used_videos=used_videos,
                        avoid_duplicates=avoid_duplicates,
                        filter_vertical=filter_vertical,
                        max_search_results=max_search_results,
                    )

                    # 중복 영상 경고
                    if is_duplicate and avoid_duplicates:
                        print(f"⚠️ 씬 {scene_num}: 중복 영상 사용 - {file_name}")
                        if task_id:
                            update_task_info(
                                task_id,
                                {
                                    "progress": select_progress,
                                    "current_step": f"씬 {scene_num}/{total_scenes}: ⚠️ 중복 영상 사용",
                                },
                            )

                elif "script" in scene and scene.get("script"):
                    selection_method = "script_search"
                    file_name, metadata, is_duplicate = select_video_with_options(
                        script=scene["script"],
                        used_videos=used_videos,
                        avoid_duplicates=avoid_duplicates,
                        filter_vertical=filter_vertical,
                        max_search_results=max_search_results,
                    )

                    # 중복 영상 경고
                    if is_duplicate and avoid_duplicates:
                        print(f"⚠️ 씬 {scene_num}: 중복 영상 사용 - {file_name}")
                        if task_id:
                            update_task_info(
                                task_id,
                                {
                                    "progress": select_progress,
                                    "current_step": f"씬 {scene_num}/{total_scenes}: ⚠️ 중복 영상 사용",
                                },
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
                            "scene": scene_num,
                            "reason": str(e),
                            "selection_method": selection_method,
                        }
                    )
                    # 건너뛴 씬은 진행도만 업데이트하고 계속
                    if task_id:
                        skip_progress = 15 + int(((i + 1) * 15) / total_scenes)
                        update_task_info(
                            task_id,
                            {
                                "progress": skip_progress,
                                "current_step": f"씬 {scene_num}/{total_scenes}: 건너뜀 ({str(e)})",
                            },
                        )
                    continue
                else:
                    raise Exception(f"Scene {scene_num}: {str(e)}")

            # TTS 생성 단계 (각 씬당 15% 할당, 15-30%)
            if task_id:
                tts_progress = 15 + int((i * 15) / total_scenes)
                update_task_info(
                    task_id,
                    {
                        "progress": tts_progress,
                        "current_step": f"씬 {scene_num}/{total_scenes}: 음성 생성 중...",
                    },
                )

            print(f"🎤 씬 {scene_num}/{total_scenes} TTS 음성 생성: {voice}")
            audio_path = generate_gemini_tts_audio(scene["subtitle"], voice)

            # video_infos에 정보 추가
            video_infos.append(
                {
                    "path": f"uploads/{file_name}",
                    "audio_path": audio_path,
                    "text": scene["subtitle"],
                    "scene": scene_num,
                    "script": scene.get("script", ""),
                    "search_keywords": scene.get("search_keywords"),
                    "video_file_name": scene.get("video_file_name"),
                    "selection_method": selection_method,
                    "metadata": metadata,
                }
            )

            # 씬 준비 완료
            if task_id:
                ready_progress = 15 + int(((i + 1) * 15) / total_scenes)
                update_task_info(
                    task_id,
                    {
                        "progress": ready_progress,
                        "current_step": f"씬 {scene_num}/{total_scenes}: 준비 완료",
                    },
                )

        if not video_infos:
            raise Exception("처리할 수 있는 비디오가 없습니다.")

        # 영상 합성
        output_path = get_next_output_path()

        # 진행도 콜백 함수 정의 (30-100% 범위로 매핑)
        def progress_callback(progress: int, step: str):
            """진행 상황을 태스크 DB에 업데이트 (30-100% 범위)"""
            if task_id:
                # create_composite_video의 0-100%를 30-100%로 변환
                adjusted_progress = 30 + int((progress * 70) / 100)
                update_task_info(
                    task_id,
                    {
                        "progress": adjusted_progress,
                        "current_step": f"비디오 합성: {step}",
                    },
                )

        try:
            create_composite_video(
                video_infos,
                output_path,
                progress_callback=progress_callback,
                background_music_path=background_music_path,
                tts_volume=tts_volume,
                background_music_volume=background_music_volume,
            )
        finally:
            # 비디오 처리 후 자원 정리
            cleanup_video_resources()

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
                    "progress": 100,
                    "current_step": "혼합 비디오 생성 완료",
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


# @router.post(
#     "/video_generate_async",
#     summary="🚀 비동기 AI 기반 비디오 생성",
#     description="""
#     **스크립트를 기반으로 비동기적으로 영상을 생성합니다.**

#     ## 주요 기능
#     - 🔄 백그라운드에서 비디오 생성 처리
#     - 📊 실시간 진행 상태 추적
#     - ⚡ 즉시 태스크 ID 반환
#     - 🎯 큐 기반 순차 처리
#     - 🎵 배경음악 추가 지원
#     - 🎤 Gemini TTS 음성 선택 가능

#     ## 처리 흐름
#     1. **요청 접수**: 즉시 태스크 ID 반환
#     2. **큐 대기**: 다른 작업 완료 후 순차 처리
#     3. **비디오 생성**: 백그라운드에서 실제 작업 수행
#     4. **결과 저장**: 완료 후 결과를 DB에 저장

#     ## 요청 파라미터

#     ### Body (JSON)
#     ```json
#     {
#       "story": [
#         {
#           "scene": 1,
#           "script": "아름다운 바다 풍경과 석양",
#           "subtitle": "오늘은 정말 아름다운 하루였습니다."
#         }
#       ]
#     }
#     ```

#     ### Query Parameters
#     - **voice** (선택): TTS 음성 이름 (기본값: "Zephyr")
#       - 사용 가능한 음성: Zephyr, Charon, Kore, Fenrir, Aoede, Puck
#       - 예시: `?voice=Aoede`

#     - **avoid_duplicates** (선택): 중복 영상 방지 여부 (기본값: false)
#       - true로 설정 시 동일한 영상이 반복 사용되지 않음
#       - 예시: `?avoid_duplicates=true`

#     - **filter_vertical** (선택): 세로 영상 필터링 여부 (기본값: false)
#       - true로 설정 시 세로 영상 제외
#       - 예시: `?filter_vertical=true`

#     - **max_search_results** (선택): 최대 검색 결과 수 (기본값: 10, 범위: 1-50)
#       - 영상 검색 시 고려할 최대 결과 수
#       - 예시: `?max_search_results=20`

#     - **background_music** (선택): 배경음악 파일명
#       - 음악 파일명만 입력 (music/ 디렉토리는 자동 추가)
#       - 지원 형식: MP3, WAV, FLAC, AAC, OGG
#       - 예시: `?background_music=abc123_downloaded.mp3`
#       - 음악 파일은 `/api/music/upload_url`로 업로드 후 파일명 사용

#     ## 전체 요청 예시
#     ```bash
#     POST /api/ai/video_generate_async?voice=Aoede&avoid_duplicates=true&background_music=abc123_downloaded.mp3

#     Body:
#     {
#       "story": [
#         {
#           "scene": 1,
#           "script": "아름다운 바다 풍경과 석양",
#           "subtitle": "오늘은 정말 아름다운 하루였습니다."
#         },
#         {
#           "scene": 2,
#           "script": "도시의 야경과 불빛",
#           "subtitle": "밤이 되면 도시는 더욱 아름답습니다."
#         }
#       ]
#     }
#     ```

#     ## 응답 예시
#     ```json
#     {
#       "result": "success",
#       "task_id": "550e8400-e29b-41d4-a716-446655440000",
#       "status": "pending",
#       "message": "비디오 생성 작업이 큐에 추가되었습니다.",
#       "queue_position": 2,
#       "estimated_wait_time": "4-10분"
#     }
#     ```

#     ## 상태 확인
#     반환된 `task_id`로 `/api/ai/task_status/{task_id}` 엔드포인트에서 진행 상황을 확인할 수 있습니다.

#     ## 배경음악 사용 방법
#     1. 음악 파일 업로드: `POST /api/music/upload_url?url=https://example.com/music.mp3`
#     2. 응답에서 `file_name` 확인 (예: "abc123_downloaded.mp3")
#     3. 비디오 생성 시 파라미터로 전달: `?background_music=abc123_downloaded.mp3`

#     ## 주의사항
#     - 배경음악은 TTS 음성과 자동으로 믹싱됩니다
#     - 배경음악 볼륨은 TTS 음성을 방해하지 않도록 자동 조절됩니다
#     - 배경음악이 비디오보다 짧으면 반복 재생되고, 길면 잘립니다
#     """,
#     response_description="태스크 ID와 초기 상태를 반환합니다.",
#     tags=["Video Generation", "Async"],
# )
# def edit_video_async(
#     story_req: StoryRequest,
#     voice: Optional[str] = "Zephyr",
#     avoid_duplicates: bool = Query(False, description="중복 영상 방지 여부"),
#     filter_vertical: bool = Query(False, description="세로 영상 필터링 여부"),
#     max_search_results: int = Query(10, description="최대 검색 결과 수", ge=1, le=50),
#     background_music: Optional[str] = Query(
#         None, description="배경음악 파일명 (예: abc123_downloaded.mp3)"
#     ),
# ):
#     """비동기적으로 비디오를 생성합니다."""

#     # 배경음악 파일 경로 처리
#     background_music_path = None
#     if background_music:
#         # 파일명만 제공된 경우 music/ 디렉토리 추가
#         if not background_music.startswith("music/"):
#             background_music_path = f"music/{background_music}"
#         else:
#             background_music_path = background_music

#     # 태스크 큐 가져오기
#     queue = get_task_queue()

#     # 태스크를 큐에 추가
#     task_id = queue.add_task(
#         task_func=_async_edit_video,
#         task_kwargs={
#             "story_req_dict": story_req.model_dump(),
#             "voice": voice,
#             "avoid_duplicates": avoid_duplicates,
#             "filter_vertical": filter_vertical,
#             "max_search_results": max_search_results,
#             "background_music_path": background_music_path,
#             "task_id": None,  # 나중에 설정됨
#         },
#         task_type="video_generation",
#     )

#     # 태스크 ID를 함수 인자에 추가
#     task_info = queue.get_task_status(task_id)
#     if task_info:
#         with queue._lock:
#             queue.tasks[task_id]["kwargs"]["task_id"] = task_id

#     # DB에 태스크 정보 저장
#     save_task_info(
#         task_id,
#         {
#             "type": "video_generation",
#             "status": TaskStatus.PENDING.value,
#             "request_data": story_req.model_dump(),
#             "options": {
#                 "avoid_duplicates": avoid_duplicates,
#                 "filter_vertical": filter_vertical,
#                 "max_search_results": max_search_results,
#                 "voice": voice,
#             },
#         },
#     )

#     # 큐 상태 조회
#     queue_status = queue.get_queue_status()

#     return {
#         "result": "success",
#         "task_id": task_id,
#         "status": "pending",
#         "message": "비디오 생성 작업이 큐에 추가되었습니다.",
#         "queue_position": queue_status["pending"],
#         "estimated_wait_time": f"{queue_status['pending'] * 2-5}분",  # 대략적인 예상 시간
#     }


@router.post(
    "/video_generate_mixed_async",
    summary="🚀 비동기 혼합 비디오 생성",
    description="""
    **다양한 타입의 씬들을 비동기적으로 혼합하여 영상을 생성합니다.**
    
    ## 주요 기능
    - 🔄 백그라운드에서 복잡한 혼합 비디오 처리
    - 📊 실시간 진행 상태 추적
    - ⚡ 즉시 태스크 ID 반환
    - 🎯 모든 씬 타입 지원 (Scene, CustomScene, FlexibleScene)
    - 🎵 배경음악 추가 지원
    - 🎤 Gemini TTS 음성 선택 가능
    
    ## 요청 파라미터
    
    ### Body (JSON Array)
    ```json
    [
      {
        "scene": 1,
        "script": "바다와 석양",
        "subtitle": "AI가 선택한 바다 영상입니다."
      },
      {
        "scene": 2,
        "video_file_name": "my_video.mp4",
        "subtitle": "직접 지정한 영상입니다."
      },
      {
        "scene": 3,
        "search_keywords": ["도시", "야경", "불빛"],
        "subtitle": "키워드로 검색한 영상입니다."
      }
    ]
    ```
    
    ### Query Parameters
    - **voice** (선택): TTS 음성 이름 (기본값: "Zephyr")
      - 사용 가능한 음성: Zephyr, Charon, Kore, Fenrir, Aoede, Puck
      - 예시: `?voice=Aoede`
    
    - **avoid_duplicates** (선택): 중복 영상 방지 여부 (기본값: false)
      - true로 설정 시 동일한 영상이 반복 사용되지 않음
      - 예시: `?avoid_duplicates=true`
    
    - **filter_vertical** (선택): 세로 영상 필터링 여부 (기본값: false)
      - true로 설정 시 세로 영상 제외
      - 예시: `?filter_vertical=true`
    
    - **max_search_results** (선택): 최대 검색 결과 수 (기본값: 10, 범위: 1-50)
      - 영상 검색 시 고려할 최대 결과 수
      - 예시: `?max_search_results=20`
    
    - **skip_unresolved** (선택): 해결되지 않는 씬 건너뛰기 (기본값: false)
      - true로 설정 시 문제가 있는 씬은 건너뛰고 계속 진행
      - 예시: `?skip_unresolved=true`
    
    - **background_music** (선택): 배경음악 파일명
      - 음악 파일명만 입력 (music/ 디렉토리는 자동 추가)
      - 지원 형식: MP3, WAV, FLAC, AAC, OGG
      - 예시: `?background_music=abc123_downloaded.mp3`
      - 음악 파일은 `/api/music/upload_url`로 업로드 후 파일명 사용
    
    - **tts_volume** (선택): TTS 음성 볼륨 (기본값: 1.0)
      - 범위: 0.0-2.0
      - 예시: `?tts_volume=1.0` (100%), `?tts_volume=0.8` (80%)
    
    - **background_music_volume** (선택): 배경음악 볼륨 (기본값: 0.2)
      - 범위: 0.0-1.0
      - 예시: `?background_music_volume=0.2` (20%), `?background_music_volume=0.3` (30%)
    
    ## 씬 타입 설명
    
    ### 1. AI 자동 선택 (Script 기반)
    ```json
    {
      "scene": 1,
      "script": "아름다운 바다 풍경과 석양",
      "subtitle": "오늘은 정말 아름다운 하루였습니다."
    }
    ```
    - `script`를 기반으로 AI가 자동으로 적합한 영상 선택
    
    ### 2. 직접 파일 지정
    ```json
    {
      "scene": 2,
      "video_file_name": "abc123_my_video.mp4",
      "subtitle": "직접 선택한 영상입니다."
    }
    ```
    - `video_file_name`으로 특정 파일 직접 지정
    - 파일은 `uploads/` 디렉토리에 있어야 함
    
    ### 3. 키워드 검색
    ```json
    {
      "scene": 3,
      "search_keywords": ["도시", "야경", "불빛"],
      "subtitle": "키워드로 검색한 영상입니다."
    }
    ```
    - `search_keywords` 배열로 여러 키워드 조합 검색
    
    ## 전체 요청 예시
    ```bash
    POST /api/ai/video_generate_mixed_async?voice=Aoede&avoid_duplicates=true&background_music=abc123_downloaded.mp3&tts_volume=1.0&background_music_volume=0.2
    
    Body:
    [
      {
        "scene": 1,
        "script": "아름다운 바다 풍경과 석양",
        "subtitle": "오늘은 정말 아름다운 하루였습니다."
      },
      {
        "scene": 2,
        "video_file_name": "my_custom_video.mp4",
        "subtitle": "이것은 제가 직접 선택한 영상입니다."
      },
      {
        "scene": 3,
        "search_keywords": ["도시", "야경"],
        "subtitle": "밤이 되면 도시는 더욱 아름답습니다."
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
      "queue_position": 1,
      "estimated_wait_time": "6-14분"
    }
    ```
    
    ## 배경음악 사용 방법
    1. 음악 파일 업로드: `POST /api/music/upload_url?url=https://example.com/music.mp3`
    2. 응답에서 `file_name` 확인 (예: "abc123_downloaded.mp3")
    3. 비디오 생성 시 파라미터로 전달: `?background_music=abc123_downloaded.mp3`
    
    ## 주의사항
    - 배경음악은 TTS 음성과 자동으로 믹싱됩니다
    - TTS 음성 볼륨 기본값은 1.0 (100%), 배경음악은 0.2 (20%)로 설정되어 있습니다
    - 볼륨 값을 조절하여 원하는 믹스 비율을 만들 수 있습니다
    - 모든 씬에 동일한 TTS 음성이 적용됩니다
    - `skip_unresolved=true`를 사용하면 일부 씬이 누락될 수 있습니다
    """,
    response_description="태스크 ID와 초기 상태를 반환합니다.",
    tags=["Video Generation"],
)
def edit_video_mixed_async(
    scenes: List[Union[Scene, CustomScene, FlexibleScene]],
    voice: Optional[str] = Query(
        "Zephyr",
        description="TTS 음성 이름 (Zephyr, Charon, Kore, Fenrir, Aoede, Puck)",
    ),
    avoid_duplicates: bool = Query(False, description="중복 영상 방지 여부"),
    filter_vertical: bool = Query(False, description="세로 영상 필터링 여부"),
    max_search_results: int = Query(10, description="최대 검색 결과 수", ge=1, le=50),
    skip_unresolved: bool = Query(False, description="해결되지 않는 씬 건너뛰기"),
    background_music: Optional[str] = Query(
        None, description="배경음악 파일명 (예: abc123_downloaded.mp3)"
    ),
    tts_volume: float = Query(
        1.0, description="TTS 음성 볼륨 (0.0-2.0)", ge=0.0, le=2.0
    ),
    background_music_volume: float = Query(
        0.2, description="배경음악 볼륨 (0.0-1.0)", ge=0.0, le=1.0
    ),
):
    """비동기적으로 혼합 비디오를 생성합니다."""

    # 배경음악 파일 경로 처리
    background_music_path = None
    if background_music:
        # 파일명만 제공된 경우 music/ 디렉토리 추가
        if not background_music.startswith("music/"):
            background_music_path = f"music/{background_music}"
        else:
            background_music_path = background_music

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
            "voice": voice,
            "avoid_duplicates": avoid_duplicates,
            "filter_vertical": filter_vertical,
            "max_search_results": max_search_results,
            "skip_unresolved": skip_unresolved,
            "background_music_path": background_music_path,
            "tts_volume": tts_volume,
            "background_music_volume": background_music_volume,
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
                "voice": voice,
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

        return {
            "result": "success",
            "task": {
                "id": task_id,
                "type": db_task.get("type"),
                "status": db_task.get("status"),
                "created_at": db_task.get("created_at"),
                "updated_at": db_task.get("updated_at"),
                "result": db_task.get("result"),
                "error": db_task.get("error"),
            },
            "source": "database",
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
        "source": "memory",
    }


@router.get(
    "/queue_status",
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
