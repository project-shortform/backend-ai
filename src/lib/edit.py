from moviepy import (
    VideoFileClip,
    TextClip,
    CompositeVideoClip,
    concatenate_videoclips,
)
import random

def edit_video_clips(
    video_infos: list[dict],
) -> None:
    """
    주어진 비디오 정보와 텍스트 정보를 기반으로 비디오를 편집합니다.
    """
    video_clips = []
    
    for video_info in video_infos:
        video_path = video_info["video_path"]
        text = video_info["text"]
        clip = VideoFileClip(video_path)
        video_clips.append(clip)
    
    final_clip = concatenate_videoclips(video_clips, method="compose")
    
    
def adjust_video_speed(
    video_path: str,
    text: str,
) -> None:
    """
    주어진 비디오에 텍스트를 추가합니다.
    """
    
if __name__ == "__main__":
    # video_infos = [
    #     {
    #         "video_path": "uploads/97c86863-c23a-4ffb-a19d-8164a4c5a3a2_downloaded.mp4",
    #         "text": "This is the first video"
    #     }
    # ]
    
    video_info = {
            "video_path": "uploads/97c86863-c23a-4ffb-a19d-8164a4c5a3a2_downloaded.mp4",
            "text": "This is the first video"
        }
