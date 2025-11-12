import os
import gc
import psutil
import signal
import subprocess
import time
import threading
from contextlib import contextmanager
import json
import tempfile
import shutil
from pathlib import Path

# FFmpeg 프로세스 관리를 위한 전역 변수
_active_processes = set()
_process_lock = threading.Lock()


def kill_ffmpeg_processes():
    """남아있는 FFmpeg 프로세스들을 강제 종료합니다."""
    try:
        for proc in psutil.process_iter(["pid", "name"]):
            if proc.info["name"] and "ffmpeg" in proc.info["name"].lower():
                try:
                    proc.kill()
                    print(f"FFmpeg 프로세스 종료: PID {proc.info['pid']}")
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
    except Exception as e:
        print(f"FFmpeg 프로세스 정리 중 오류: {e}")


def run_ffmpeg_command(cmd, input_files=None, timeout=300):
    """FFmpeg 명령어를 실행하고 결과를 반환합니다."""
    try:
        print(f"🔧 FFmpeg 명령어 실행: {' '.join(cmd)}")

        with _process_lock:
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            _active_processes.add(process)

        try:
            stdout, stderr = process.communicate(timeout=timeout)
            returncode = process.returncode

            if returncode != 0:
                print(f"❌ FFmpeg 오류 (코드 {returncode}): {stderr}")
                raise subprocess.CalledProcessError(returncode, cmd, stderr)

            return stdout, stderr

        finally:
            with _process_lock:
                _active_processes.discard(process)

    except subprocess.TimeoutExpired:
        process.kill()
        with _process_lock:
            _active_processes.discard(process)
        raise Exception(f"FFmpeg 명령어 실행 시간 초과 ({timeout}초)")
    except Exception as e:
        print(f"❌ FFmpeg 명령어 실행 중 오류: {e}")
        raise


def get_video_info(video_path):
    """비디오 파일의 정보를 가져옵니다."""
    cmd = [
        "ffprobe",
        "-v",
        "quiet",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        video_path,
    ]

    try:
        stdout, _ = run_ffmpeg_command(cmd)
        info = json.loads(stdout)

        video_stream = None
        audio_stream = None

        for stream in info["streams"]:
            if stream["codec_type"] == "video" and video_stream is None:
                video_stream = stream
            elif stream["codec_type"] == "audio" and audio_stream is None:
                audio_stream = stream

        duration = float(info["format"].get("duration", 0))
        width = int(video_stream.get("width", 1920)) if video_stream else 1920
        height = int(video_stream.get("height", 1080)) if video_stream else 1080
        has_audio = audio_stream is not None

        return {
            "duration": duration,
            "width": width,
            "height": height,
            "has_audio": has_audio,
            "format": info["format"],
            "video_stream": video_stream,
            "audio_stream": audio_stream,
        }

    except Exception as e:
        print(f"❌ 비디오 정보 가져오기 실패: {video_path} - {e}")
        raise


def get_audio_duration(audio_path):
    """오디오 파일의 길이를 가져옵니다."""
    cmd = [
        "ffprobe",
        "-v",
        "quiet",
        "-print_format",
        "json",
        "-show_format",
        audio_path,
    ]

    try:
        stdout, _ = run_ffmpeg_command(cmd)
        info = json.loads(stdout)
        return float(info["format"].get("duration", 0))
    except Exception as e:
        print(f"❌ 오디오 길이 가져오기 실패: {audio_path} - {e}")
        return 0


def create_subtitle_file(text, duration, subtitle_path):
    """SRT 자막 파일을 생성합니다."""
    try:
        # SRT 형식으로 자막 생성
        srt_content = f"""1
00:00:00,000 --> {int(duration//3600):02d}:{int((duration%3600)//60):02d}:{int(duration%60):02d},{int((duration%1)*1000):03d}
{text}

"""

        with open(subtitle_path, "w", encoding="utf-8") as f:
            f.write(srt_content)

        print(f"✅ 자막 파일 생성: {subtitle_path}")

    except Exception as e:
        print(f"❌ 자막 파일 생성 실패: {e}")
        raise


def process_single_clip(info, temp_dir, base_resolution=(1920, 1080)):
    """단일 클립을 처리합니다."""
    video_path = info["path"]
    text = info.get("text", "")
    audio_path = info.get("audio_path", None)
    audio_duration = info.get("audio_duration", None)

    # 비디오 정보 가져오기
    video_info = get_video_info(video_path)
    video_duration = video_info["duration"]

    # 오디오 길이 결정
    if audio_path and os.path.exists(audio_path):
        audio_duration = get_audio_duration(audio_path)
        print(
            f"🔊 외부 오디오 사용: {os.path.basename(audio_path)} ({audio_duration:.1f}s)"
        )
    elif audio_duration is None:
        audio_duration = video_duration
        print(f"🔊 원본 비디오 오디오 사용 ({audio_duration:.1f}s)")

    # 임시 파일명 생성
    clip_id = str(int(time.time() * 1000000))
    temp_video = os.path.join(temp_dir, f"temp_video_{clip_id}.mp4")
    temp_with_audio = os.path.join(temp_dir, f"temp_audio_{clip_id}.mp4")
    temp_with_subtitle = os.path.join(temp_dir, f"temp_subtitle_{clip_id}.mp4")

    try:
        # 1단계: 비디오 길이 및 해상도 조정
        # 항상 비디오를 오디오 길이에 정확히 맞춤
        filter_parts = []
        input_options = []

        # 길이 조정 - 모든 경우에 정확한 길이로 맞춤
        if video_duration > audio_duration:
            # 비디오가 더 긴 경우: 중간 부분 자르기
            start_time = (video_duration - audio_duration) / 2
            input_options = ["-ss", str(start_time), "-t", str(audio_duration)]
            print(
                f"✂️ 비디오 길이 조정: {video_duration:.1f}s → {audio_duration:.1f}s (자르기)"
            )
        elif video_duration < audio_duration:
            # 비디오가 더 짧은 경우: 루프로 반복하여 길이 맞춤
            loops_needed = int(audio_duration / video_duration) + 1
            filter_parts.append(f"loop=loop={loops_needed}:size=1:start=0")
            filter_parts.append(f"trim=duration={audio_duration}")
            input_options = []
            print(
                f"🔄 비디오 길이 조정: {video_duration:.1f}s → {audio_duration:.1f}s (루프 {loops_needed}회)"
            )
        else:
            # 길이가 같은 경우에도 정확한 길이로 설정
            input_options = ["-t", str(audio_duration)]
            print(f"⏰ 비디오 길이 설정: {audio_duration:.1f}s")

        # 해상도 조정
        if (
            video_info["width"] != base_resolution[0]
            or video_info["height"] != base_resolution[1]
        ):
            filter_parts.append(f"scale={base_resolution[0]}:{base_resolution[1]}")
            print(
                f"📐 해상도 조정: {video_info['width']}x{video_info['height']} → {base_resolution[0]}x{base_resolution[1]}"
            )

        # 정확한 프레임레이트 설정
        filter_parts.append("fps=24")

        # FFmpeg 명령어 구성
        cmd = ["ffmpeg", "-y"] + input_options + ["-i", video_path]

        if filter_parts:
            cmd.extend(["-vf", ",".join(filter_parts)])

        cmd.extend(
            [
                "-c:v",
                "libx264",
                "-preset",
                "fast",
                "-crf",
                "23",
                "-r",
                "24",  # 프레임레이트 강제 설정
                "-t",
                str(audio_duration),  # 정확한 길이 설정
                "-an",  # 오디오 제거 (나중에 따로 추가)
                temp_video,
            ]
        )

        run_ffmpeg_command(cmd)

        # 2단계: 오디오 합성 - 정확한 길이로 동기화
        if audio_path and os.path.exists(audio_path):
            # 외부 오디오 파일 사용 - 정확한 길이 맞춤
            cmd = [
                "ffmpeg",
                "-y",
                "-i",
                temp_video,
                "-i",
                audio_path,
                "-c:v",
                "copy",
                "-c:a",
                "aac",
                "-map",
                "0:v:0",
                "-map",
                "1:a:0",
                "-t",
                str(audio_duration),  # 정확한 길이 설정
                "-avoid_negative_ts",
                "make_zero",  # 타임스탬프 문제 방지
                temp_with_audio,
            ]
            run_ffmpeg_command(cmd)
        elif video_info["has_audio"]:
            # 원본 비디오의 오디오 사용 - 정확한 길이 맞춤
            cmd = [
                "ffmpeg",
                "-y",
                "-i",
                temp_video,
                "-i",
                video_path,
                "-c:v",
                "copy",
                "-c:a",
                "aac",
                "-map",
                "0:v:0",
                "-map",
                "1:a:0",
                "-t",
                str(audio_duration),  # 정확한 길이 설정
                "-avoid_negative_ts",
                "make_zero",  # 타임스탬프 문제 방지
                temp_with_audio,
            ]
            run_ffmpeg_command(cmd)
        else:
            # 오디오가 없는 경우 - 무음 오디오 추가
            cmd = [
                "ffmpeg",
                "-y",
                "-i",
                temp_video,
                "-f",
                "lavfi",
                "-i",
                f"anullsrc=channel_layout=stereo:sample_rate=44100",
                "-c:v",
                "copy",
                "-c:a",
                "aac",
                "-t",
                str(audio_duration),  # 정확한 길이 설정
                "-avoid_negative_ts",
                "make_zero",
                temp_with_audio,
            ]
            run_ffmpeg_command(cmd)

        # 3단계: 자막 추가
        if text:
            # Windows 호환 경로 처리
            def normalize_path_for_ffmpeg(path):
                """FFmpeg에서 사용할 수 있도록 경로를 정규화합니다."""
                # Windows에서 백슬래시를 슬래시로 변경하고 이스케이프 처리
                normalized = path.replace("\\", "/")
                # 콜론을 이스케이프 처리 (드라이브 레터용)
                if ":" in normalized and len(normalized) > 1 and normalized[1] == ":":
                    normalized = normalized.replace(":", "\\:")
                return normalized

            # 자막 파일 생성
            subtitle_path = os.path.join(temp_dir, f"subtitle_{clip_id}.srt")
            create_subtitle_file(text, audio_duration, subtitle_path)

            # Windows 경로 정규화
            normalized_subtitle = normalize_path_for_ffmpeg(subtitle_path)

            # 자막 필터 구성 (크기 축소)
            subtitle_filter = f"subtitles='{normalized_subtitle}':force_style='FontSize=28,PrimaryColour=&Hffffff,OutlineColour=&H000000,Outline=2,Alignment=2'"

            # 폰트 디렉토리가 있는 경우 추가
            font_path = "fonts/NotoSansKR-Medium.ttf"
            if os.path.exists(font_path):
                font_dir = normalize_path_for_ffmpeg(
                    os.path.dirname(os.path.abspath(font_path))
                )
                subtitle_filter = f"subtitles='{normalized_subtitle}':fontsdir='{font_dir}':force_style='FontName=NotoSansKR-Medium,FontSize=28,PrimaryColour=&Hffffff,OutlineColour=&H000000,Outline=2,Alignment=2'"

            # 자막을 비디오에 합성 - 정확한 길이 유지
            cmd = [
                "ffmpeg",
                "-y",
                "-i",
                temp_with_audio,
                "-vf",
                subtitle_filter,
                "-c:a",
                "copy",
                "-c:v",
                "libx264",
                "-preset",
                "fast",
                "-crf",
                "23",
                "-r",
                "24",  # 프레임레이트 유지
                "-t",
                str(audio_duration),  # 정확한 길이 유지
                "-avoid_negative_ts",
                "make_zero",
                temp_with_subtitle,
            ]

            run_ffmpeg_command(cmd)
            result_path = temp_with_subtitle
            print(f"📝 자막 추가 완료")
        else:
            result_path = temp_with_audio

        return result_path

    except Exception as e:
        print(f"❌ 클립 처리 중 오류: {e}")
        raise


def create_composite_video(
    video_infos: list[dict],
    output_path: str,
    progress_callback=None,
    background_music_path: str = None,
    tts_volume: float = 1.0,
    background_music_volume: float = 0.2,
) -> str:
    """
    비디오 클립들과 오디오를 합성하여 하나의 영상을 만듭니다.

    순수 FFmpeg 명령어를 사용하여 moviepy 의존성 없이 구현됩니다.

    Parameters
    ----------
    video_infos : list[dict]
        각 비디오 정보를 담은 딕셔너리 리스트. 각 딕셔너리는 다음 키를 포함해야 합니다:
        - 'path' (str): 비디오 파일 경로
        - 'audio_path' (str, optional): 오디오 파일 경로 (없으면 비디오 원본 오디오 사용)
        - 'text' (str): 자막 텍스트
        - 'audio_duration' (float, optional): 오디오 길이(초). audio_path가 없을 때 사용됨
    output_path : str
        결과 비디오를 저장할 경로
    progress_callback : callable, optional
        진행 상황을 업데이트할 콜백 함수 (progress, step_detail)
    background_music_path : str, optional
        배경음악 파일 경로
    tts_volume : float, optional
        TTS 음성 볼륨 (0.0-2.0, 기본값: 1.0)
    background_music_volume : float, optional
        배경음악 볼륨 (0.0-1.0, 기본값: 0.2)

    Returns
    -------
    str
        생성된 비디오 파일 경로
    """
    if not video_infos:
        raise ValueError("비디오 정보가 제공되지 않았습니다.")

    # 출력 디렉토리 생성
    output_dir = os.path.dirname(output_path)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)

    # 임시 디렉토리 생성
    temp_dir = tempfile.mkdtemp(prefix="ffmpeg_video_processing_")
    processed_clips = []
    base_resolution = (1920, 1080)

    try:
        print(f"🎬 비디오 합성 시작: {len(video_infos)}개 클립 처리")

        if progress_callback:
            progress_callback(0, f"비디오 합성 시작: {len(video_infos)}개 클립 처리")

        # 각 클립 개별 처리 (80% of the progress - 0~80)
        for i, info in enumerate(video_infos):
            print(f"📹 클립 {i+1}/{len(video_infos)} 처리 중...")

            if progress_callback:
                clip_progress = int((i * 80) / len(video_infos))
                progress_callback(
                    clip_progress, f"클립 {i+1}/{len(video_infos)} 처리 중..."
                )

            if "path" not in info:
                print(f"경고: 항목 {i}에 path가 없습니다. 건너뜁니다.")
                continue

            try:
                processed_clip = process_single_clip(info, temp_dir, base_resolution)
                processed_clips.append(processed_clip)
                print(f"✅ 클립 {i+1} 처리 완료")

                if progress_callback:
                    clip_progress = int(((i + 1) * 80) / len(video_infos))
                    progress_callback(
                        clip_progress, f"클립 {i+1}/{len(video_infos)} 처리 완료"
                    )

            except Exception as e:
                print(f"❌ 클립 {i+1} 처리 중 오류: {e}")
                continue

        if not processed_clips:
            raise ValueError("처리할 수 있는 유효한 비디오 클립이 없습니다.")

        print(f"🔗 {len(processed_clips)}개 클립 연결 중...")

        if progress_callback:
            progress_callback(80, f"{len(processed_clips)}개 클립 연결 중...")

        # 클립들을 연결하기 위한 concat 파일 생성
        concat_file = os.path.join(temp_dir, "concat_list.txt")
        with open(concat_file, "w", encoding="utf-8") as f:
            for clip_path in processed_clips:
                # Windows 경로 호환성을 위해 forward slash 사용
                normalized_path = clip_path.replace("\\", "/")
                f.write(f"file '{normalized_path}'\n")

        print(f"💾 최종 비디오 저장 중: {output_path}")

        if progress_callback:
            progress_callback(90, f"최종 비디오 저장 중: {output_path}")

        # 최종 비디오 연결 및 저장 - 정확한 동기화
        cmd = [
            "ffmpeg",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            concat_file,
            # 배경음악이 있는 경우 추가
        ]

        # 배경음악 입력 추가
        if background_music_path and os.path.exists(background_music_path):
            # 볼륨 필터 생성
            volume_filter = f"[0:a]volume={tts_volume}[a0];[1:a]volume={background_music_volume}[a1];[a0][a1]amix=inputs=2:duration=first[aout]"

            cmd.extend(
                [
                    "-i",
                    background_music_path,
                    # 필터 설정: TTS 음성과 배경음악 볼륨 조절 후 믹스
                    "-filter_complex",
                    volume_filter,
                    "-map",
                    "0:v",  # 비디오는 concat 파일에서
                    "-map",
                    "[aout]",  # 오디오는 믹스된 결과
                    "-c:v",
                    "libx264",
                    "-c:a",
                    "aac",
                    "-preset",
                    "fast",
                    "-crf",
                    "23",
                    "-r",
                    "24",  # 24fps 설정
                    "-vsync",
                    "cfr",  # 일정한 프레임레이트 강제
                    "-async",
                    "1",  # 오디오 동기화
                    "-avoid_negative_ts",
                    "make_zero",  # 타임스탬프 문제 방지
                    "-fflags",
                    "+genpts",  # PTS 생성
                ]
            )
            print(
                f"🎵 배경음악 추가 (TTS: {tts_volume*100:.0f}%, 배경음악: {background_music_volume*100:.0f}%): {background_music_path}"
            )
        else:
            # 배경음악이 없는 경우 기존 방식 사용
            cmd.extend(
                [
                    "-c:v",
                    "libx264",
                    "-c:a",
                    "aac",
                    "-preset",
                    "fast",
                    "-crf",
                    "23",
                    "-r",
                    "24",  # 24fps 설정
                    "-vsync",
                    "cfr",  # 일정한 프레임레이트 강제
                    "-async",
                    "1",  # 오디오 동기화
                    "-avoid_negative_ts",
                    "make_zero",  # 타임스탬프 문제 방지
                    "-fflags",
                    "+genpts",  # PTS 생성
                ]
            )

        cmd.extend([output_path])

        run_ffmpeg_command(cmd)

        print(f"✅ 비디오 생성 완료: {output_path}")

        if progress_callback:
            progress_callback(100, f"비디오 생성 완료: {output_path}")

        return output_path

    except Exception as e:
        print(f"❌ 비디오 합성 중 오류 발생: {e}")
        raise

    finally:
        print("🧹 자원 정리 중...")

        # 임시 디렉토리 정리
        try:
            shutil.rmtree(temp_dir, ignore_errors=True)
        except Exception as e:
            print(f"임시 디렉토리 정리 중 오류: {e}")

        # FFmpeg 프로세스 정리
        time.sleep(1)
        kill_ffmpeg_processes()

        print("✅ 자원 정리 완료")


def cleanup_video_resources():
    """비디오 처리 후 남은 자원들을 정리합니다."""
    try:
        # FFmpeg 프로세스 정리
        kill_ffmpeg_processes()

        print("🧹 비디오 자원 정리 완료")

    except Exception as e:
        print(f"자원 정리 중 오류: {e}")


@contextmanager
def ffmpeg_context():
    """FFmpeg 작업을 위한 컨텍스트 매니저"""
    try:
        yield
    finally:
        cleanup_video_resources()


if __name__ == "__main__":
    video_infos = [
        {
            "path": "uploads/0a3aa9f9-766f-463f-9eec-b1a9b65c91f7_downloaded.mp4",
            "audio_path": "audios/97c86863-c23a-4ffb-a19d-8164a4c5a3a2.mp3",
            "text": "첫 번째 비디오 설명",
        },
        {
            "path": "uploads/00a3d74e-b21e-439c-94bf-8d3929ffa326_downloaded.mp4",
            "audio_path": "audios/2096b708-c8a0-4e24-bf53-a73a821f125d.mp3",
            "text": "두 번째 비디오 설명",
        },
    ]
    output_path = "final_video.mp4"

    try:
        with ffmpeg_context():
            create_composite_video(video_infos, output_path)
    except Exception as e:
        print(f"실행 중 오류: {e}")
