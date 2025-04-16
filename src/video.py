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
        images_content.append({
            "type": "input_image",
            "image_url": f"data:image/jpeg;base64,{base64_image}",
        })
    # 첫 프레임에만 질문 텍스트 추가
    content = [{"type": "input_text", "text": "영상의 프레임들인데, 이거를 통해 비디오 RAG 를 위한 임베딩에 쓸거야. 그에 맞게 임베딩용 텍스트를 추출해줘. 뭐 설명 필요 없이 딱 영상에대한 자세한 요약으로 바로 임베딩해서 데이터베이스 넣는 용도로 만들어줘. 최대한 자세하게 많은 정보를 담아서 영상 프레임에대한 요약 정보 뽑아줘. 그리고 무조건 영어로 만들어줘."}] + images_content

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
        with open(save_path, 'wb') as f:
            shutil.copyfileobj(r.raw, f)
    return save_path

# 사용 예시
# video_path = "path_to_your_video.mp4"
# result_text = video_to_text(video_path)
# print(result_text)