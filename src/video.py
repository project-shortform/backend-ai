import base64
import cv2
from openai import OpenAI
import requests
import shutil

client = OpenAI()


# Function to encode the image
def encode_image(image_path):
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode("utf-8")


def extract_frames(video_path, num_frames=3):
    vidcap = cv2.VideoCapture(video_path)
    total_frames = int(vidcap.get(cv2.CAP_PROP_FRAME_COUNT))
    frame_idxs = [int(i * total_frames / num_frames) for i in range(num_frames)]
    frames = []
    for idx in frame_idxs:
        vidcap.set(cv2.CAP_PROP_POS_FRAMES, idx)
        success, image = vidcap.read()
        if success:
            frame_path = f"frames/frame_{idx}.jpg"
            cv2.imwrite(frame_path, image)
            frames.append(frame_path)
    vidcap.release()
    return frames


def video_to_text(video_path, num_frames=3):
    frame_paths = extract_frames(video_path, num_frames)
    images_content = []
    for frame_path in frame_paths:
        base64_image = encode_image(frame_path)
        images_content.append(
            {
                "type": "input_image",
                "image_url": f"data:image/jpeg;base64,{base64_image}",
            }
        )
    # 첫 프레임에만 질문 텍스트 추가
    content = (
        [
            {
                "type": "input_text",
                "text": """
You are a vision-to-text conversion expert trained to analyze key visual scenes and generate concise, descriptive English captions suitable for text embedding and video search.

Your task is to receive 3 key video frames from a short background clip (less than 30 seconds) and generate a short, coherent English description for each frame. The descriptions should capture the essence of the visual scene, focusing on objects, actions, and setting.

Constraints:
- Output must be in English only.
- Do not include frame numbers or image file names.
- Each caption must be concise and under 30 words.
- Avoid subjective or speculative descriptions (e.g., do not guess emotions or unseen causes).
- Use consistent vocabulary to maximize embedding performance in search tasks.

Your output will be used for semantic search and automatic storyboard narration in a YouTube video generation system.

""",
            }
        ]
        + images_content
    )

    response = client.responses.create(
        model="gpt-4.1",
        input=[
            {
                "role": "user",
                "content": content,
            }
        ],
    )
    return response.output_text


def download_video_from_url(url: str, save_path: str) -> str:
    """
    주어진 URL에서 비디오 파일을 다운로드하여 save_path에 저장합니다.
    성공 시 저장된 파일 경로를 반환합니다.
    """
    with requests.get(url, stream=True) as r:
        r.raise_for_status()
        with open(save_path, "wb") as f:
            shutil.copyfileobj(r.raw, f)
    return save_path


# 사용 예시
# video_path = "path_to_your_video.mp4"
# result_text = video_to_text(video_path)
# print(result_text)
