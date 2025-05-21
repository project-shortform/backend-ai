from moviepy import (
    VideoFileClip,
    TextClip,
    CompositeVideoClip,
    concatenate_videoclips,
    AudioFileClip
)
from moviepy.video import fx
import os

def create_composite_video(video_infos: list[dict], output_path: str) -> str:
    """
    비디오 클립들과 오디오를 합성하여 하나의 영상을 만듭니다.
    
    각 비디오는 오디오 길이에 맞게 중간 부분이 잘리고, 자막이 추가됩니다.
    그 후 모든 비디오가 순차적으로 합쳐집니다.
    
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
        
    Returns
    -------
    str
        생성된 비디오 파일 경로
    """
    if not video_infos:
        raise ValueError("비디오 정보가 제공되지 않았습니다.")
    
    # 출력 디렉토리 생성 (없는 경우)
    output_dir = os.path.dirname(output_path)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
    
    # 임시 디렉토리 생성 (없는 경우)
    temp_dir = "temp_video_processing"
    os.makedirs(temp_dir, exist_ok=True)
    
    final_clips = []
    base_resolution = (1920, 1080)  # 기준 해상도 (width, height)
    
    try:
        for i, info in enumerate(video_infos):
            # 필수 정보 확인
            if 'path' not in info:
                print(f"경고: 항목 {i}에 path가 없습니다. 건너뜁니다.")
                continue
            
            video_path = info['path']
            text = info.get('text', '')
            
            # 오디오 정보 확인 (파일 또는 길이)
            audio_path = info.get('audio_path', None)
            audio_duration = info.get('audio_duration', None)
            
            # 비디오 로드
            try:
                video_clip = VideoFileClip(video_path)
            except Exception as e:
                print(f"비디오 로드 중 오류: {video_path} - {e}")
                continue
            
            # 기준 해상도 설정 (첫 번째 유효한 비디오)
            if base_resolution is None:
                base_resolution = video_clip.size  # (width, height)
            
            # 오디오 로드 또는 기본 오디오 사용
            if audio_path:
                try:
                    audio_clip = AudioFileClip(audio_path)
                    audio_duration = audio_clip.duration
                except Exception as e:
                    print(f"오디오 로드 중 오류: {audio_path} - {e}")
                    # 오디오 로드 실패 시 비디오 원본 오디오 사용
                    audio_clip = video_clip.audio
                    audio_duration = audio_clip.duration if audio_clip else video_clip.duration
            elif audio_duration is not None:
                # 오디오 파일 없이 길이만 제공된 경우 비디오 원본 오디오 사용
                audio_clip = video_clip.audio
                # 원본 오디오가 없는 경우 (무음 비디오)
                if audio_clip is None:
                    audio_clip = None
            else:
                # 오디오 정보가 전혀 없는 경우 비디오 원본 오디오와 길이 사용
                audio_clip = video_clip.audio
                audio_duration = video_clip.duration if video_clip.audio else video_clip.duration
            
            # 비디오 길이 조정 (중간 부분을 오디오 길이에 맞게 자르기)
            if audio_duration and video_clip.duration > audio_duration:
                # 비디오 중간 부분을 오디오 길이에 맞게 자르기
                start_time = (video_clip.duration - audio_duration) / 2
                adjusted_clip = video_clip.subclipped(start_time, start_time + audio_duration)
            elif audio_duration and video_clip.duration < audio_duration:
                # 비디오가 오디오보다 짧은 경우, 비디오 속도 조절
                factor = video_clip.duration / audio_duration
                adjusted_clip = video_clip.with_speed_scaled(factor)
            else:
                # 길이가 같거나 오디오 길이 정보가 없는 경우
                adjusted_clip = video_clip
            
            # 오디오 할당 (오디오가 있는 경우)
            if audio_clip is not None:
                adjusted_clip = adjusted_clip.with_audio(audio_clip)
            
            # 해상도 맞추기 (기준 해상도에 맞게 리사이즈)
            if base_resolution is not None and adjusted_clip.size != base_resolution:
                adjusted_clip = adjusted_clip.with_effects([fx.Resize(base_resolution)])
            
            # 자막 추가
            if text:
                txt_clip = (
                    TextClip(
                        font="fonts/NotoSansKR-Medium.ttf",
                        font_size=24,
                        text=text,
                        color="white",
                        method='caption',
                        size=base_resolution  # 기준 해상도에 맞게 자막 크기 설정
                    )
                    .with_position(("center", "bottom"))
                    .with_duration(adjusted_clip.duration)  # duration 설정 복원
                )
                adjusted_clip = CompositeVideoClip([adjusted_clip, txt_clip])
            
            # 최종 클립 목록에 추가
            final_clips.append(adjusted_clip)
        
        # 클립이 없는 경우 처리
        if not final_clips:
            raise ValueError("처리할 수 있는 유효한 비디오 클립이 없습니다.")
        
        # 모든 클립 연결
        final_video = concatenate_videoclips(final_clips, method="compose")
        
        # 최종 비디오 저장
        final_video.write_videofile(
            output_path,
            codec="libx264",
            audio_codec="aac",
            temp_audiofile=f"{temp_dir}/temp-audio.m4a",
            remove_temp=True,
            fps=24
        )
        
        print(f"비디오 생성 완료: {output_path}")
        return output_path
        
    except Exception as e:
        print(f"비디오 합성 중 오류 발생: {e}")
        raise
    
    finally:
        # 모든 클립 자원 해제
        for clip in final_clips:
            try:
                clip.close()
            except:
                pass
        
        # 임시 디렉토리 정리 (선택적)
        # shutil.rmtree(temp_dir, ignore_errors=True)


# def edit_video_clips(
#     video_infos: list[dict], output_path: str, tts_durations: list[float]
# ) -> None:
#     # ... existing code ...
    
if __name__ == "__main__":
    video_infos = [
        {
            "path": "uploads/97c86863-c23a-4ffb-a19d-8164a4c5a3a2_downloaded.mp4", 
            "audio_path": "audios/97c86863-c23a-4ffb-a19d-8164a4c5a3a2.mp3",  # 오디오 파일 없이 길이만 지정
            "text": "첫 번째 비디오 설명"
        },
        {
            "path": "uploads/2096b708-c8a0-4e24-bf53-a73a821f125d_downloaded.mp4", 
            "audio_path": "audios/2096b708-c8a0-4e24-bf53-a73a821f125d.mp3",  # 오디오 파일 없이 길이만 지정
            "text": "두 번째 비디오 설명"
        }
    ]
    output_path = "final_video.mp4"
    create_composite_video(video_infos, output_path)
    
