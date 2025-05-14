import base64
import cv2
from openai import OpenAI
import requests
import shutil

client = OpenAI()


# Function to encode the image
def encode_image(image_path):
    """이미지 파일을 base64로 인코딩합니다.

    Parameters
    ----------
    image_path : str
        인코딩할 이미지 파일의 경로입니다.

    Returns
    -------
    str
        Base64로 인코딩된 이미지 문자열입니다.
    """
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode("utf-8")


def extract_frames(video_path, num_frames=3):
    """비디오에서 여러 프레임을 추출하여 이미지 파일로 저장합니다.

    비디오 전체 길이에서 균등한 간격으로 `num_frames`개의 프레임을 선택하여
    jpg 이미지 파일로 저장합니다.

    Parameters
    ----------
    video_path : str
        프레임을 추출할 비디오 파일의 경로입니다.
    num_frames : int, optional
        추출할 프레임의 개수입니다. 기본값은 3입니다.

    Returns
    -------
    list[str]
        저장된 프레임 이미지 파일들의 경로 리스트입니다.
    """
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
    """비디오의 주요 프레임들을 분석하여 텍스트 설명을 생성합니다.

    `extract_frames` 함수를 사용하여 비디오에서 프레임들을 추출하고,
    OpenAI API를 호출하여 각 프레임에 대한 설명을 생성합니다.

    Parameters
    ----------
    video_path : str
        텍스트 설명을 생성할 비디오 파일의 경로입니다.
    num_frames : int, optional
        분석에 사용할 프레임의 개수입니다. 기본값은 3입니다.

    Returns
    -------
    str
        생성된 비디오 설명 텍스트입니다.
    """
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
    """주어진 URL에서 비디오 파일을 다운로드하여 지정된 경로에 저장합니다.

    Parameters
    ----------
    url : str
        다운로드할 비디오 파일의 URL입니다.
    save_path : str
        다운로드한 비디오 파일을 저장할 경로입니다.

    Returns
    -------
    str
        성공 시 저장된 파일 경로를 반환합니다.

    Raises
    ------
    requests.exceptions.HTTPError
        HTTP 요청이 실패했을 경우 발생합니다.
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
