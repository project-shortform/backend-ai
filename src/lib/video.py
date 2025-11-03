import base64
import cv2
import requests
import shutil
import os
from google.genai import types
from src.lib.llm import gemini_client

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
    Gemini API를 호출하여 각 프레임에 대한 설명을 생성합니다.

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
    
    # 콘텐츠 파츠 준비
    parts = [
        types.Part.from_text(text="""
You are a vision-to-text conversion expert trained to analyze key visual scenes and generate concise, descriptive English captions suitable for text embedding and video search.

Your task is to receive 3 key video frames from a short background clip (less than 30 seconds) and generate a short, coherent English description for each frame. The descriptions should capture the essence of the visual scene, focusing on objects, actions, and setting.

Constraints:
- Output must be in English only.
- Do not include frame numbers or image file names.
- Each caption must be concise and under 30 words.
- Avoid subjective or speculative descriptions (e.g., do not guess emotions or unseen causes).
- Use consistent vocabulary to maximize embedding performance in search tasks.

Your output will be used for semantic search and automatic storyboard narration in a YouTube video generation system.
""")
    ]
    
    # 각 프레임 이미지 추가
    for frame_path in frame_paths:
        base64_image = encode_image(frame_path)
        parts.append(
            types.Part.from_bytes(
                data=base64.b64decode(base64_image),
                mime_type="image/jpeg"
            )
        )
    
    contents = [
        types.Content(
            role="user",
            parts=parts
        )
    ]
    
    generate_content_config = types.GenerateContentConfig(
        response_mime_type="text/plain",
    )
    
    # API 호출 및 응답 처리
    response = gemini_client.models.generate_content(
        model="gemini-2.5-flash-preview-05-20",
        contents=contents,
        config=generate_content_config,
    )
    
    return response.text


def music_to_text(music_path):
    """음악 파일을 분석하여 텍스트 설명을 생성합니다.

    Gemini API를 호출하여 음악의 특징과 분위기를 분석하고 설명을 생성합니다.

    Parameters
    ----------
    music_path : str
        텍스트 설명을 생성할 음악 파일의 경로입니다.

    Returns
    -------
    str
        생성된 음악 설명 텍스트입니다.
    """
    # 파일명에서 기본 정보 추출
    file_name = os.path.basename(music_path)
    name_without_ext = os.path.splitext(file_name)[0]
    
    # UUID 제거
    if "_" in name_without_ext:
        parts = name_without_ext.split("_", 1)
        if len(parts) > 1 and len(parts[0]) == 32:  # UUID 길이 확인
            name_without_ext = parts[1]
    
    # 음악 파일 정보 추출
    duration = get_audio_duration(music_path)
    
    # 음악 파일을 바이너리로 읽기
    try:
        with open(music_path, "rb") as audio_file:
            audio_data = audio_file.read()
    except Exception as e:
        print(f"음악 파일 읽기 실패: {music_path} - {e}")
        return f"음악 파일: {name_without_ext}"
    
    # MIME 타입 결정
    mime_type = "audio/mpeg"
    if music_path.lower().endswith('.wav'):
        mime_type = "audio/wav"
    elif music_path.lower().endswith('.flac'):
        mime_type = "audio/flac"
    elif music_path.lower().endswith('.aac'):
        mime_type = "audio/aac"
    elif music_path.lower().endswith('.ogg'):
        mime_type = "audio/ogg"
    
    # 콘텐츠 파츠 준비
    contents = [
        types.Content(
            role="user",
            parts=[
                types.Part.from_text(text=f"""
You are an audio analysis expert trained to analyze music files and generate descriptive English text suitable for text embedding and music search.

Your task is to analyze a music file and generate a comprehensive description that captures its musical characteristics, mood, and potential use cases.

File Information:
- File Name: {name_without_ext}
- Duration: {duration:.1f} seconds

Please analyze the music and provide a description that includes:
1. Musical genre and style
2. Mood and emotional tone
3. Instrumentation (if identifiable)
4. Tempo and rhythm characteristics
5. Potential use cases (e.g., background music, video editing, presentation)

Constraints:
- Output must be in English only.
- Be descriptive but concise (under 100 words).
- Focus on objective musical characteristics.
- Include potential use cases for video production.
- Use consistent vocabulary to maximize embedding performance in search tasks.

Your output will be used for semantic search and automatic music selection in a video generation system.
"""),
                types.Part.from_bytes(
                    data=audio_data,
                    mime_type=mime_type
                )
            ]
        )
    ]
    
    generate_content_config = types.GenerateContentConfig(
        response_mime_type="text/plain",
    )
    
    # API 호출 및 응답 처리
    try:
        response = gemini_client.models.generate_content(
            model="gemini-2.5-flash-preview-05-20",
            contents=contents,
            config=generate_content_config,
        )
        return response.text
    except Exception as e:
        print(f"Gemini API 호출 실패: {e}")
        return f"음악 파일: {name_without_ext} (재생시간: {duration:.1f}초)"


def get_audio_duration(file_path):
    """오디오 파일의 재생 시간을 가져옵니다."""
    try:
        import subprocess
        cmd = [
            "ffprobe",
            "-v", "quiet",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            file_path
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return float(result.stdout.strip())
    except Exception as e:
        print(f"오디오 길이 가져오기 실패: {file_path} - {e}")
        return 0.0


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


def create_thumbnail(video_path, thumbnail_path=None):
    """비디오의 첫 번째 프레임을 썸네일로 추출합니다.

    Parameters
    ----------
    video_path : str
        썸네일을 추출할 비디오 파일의 경로입니다.
    thumbnail_path : str, optional
        썸네일을 저장할 경로입니다. None이면 자동 생성됩니다.

    Returns
    -------
    str
        저장된 썸네일 파일의 경로입니다.
    """
    vidcap = cv2.VideoCapture(video_path)
    
    # 첫 번째 프레임을 읽기
    success, image = vidcap.read()
    
    if success:
        if thumbnail_path is None:
            # 비디오 파일명을 기반으로 썸네일 경로 생성
            video_name = video_path.stem if hasattr(video_path, 'stem') else video_path.split('/')[-1].split('.')[0]
            thumbnail_path = f"thumbnails/{video_name}_thumbnail.jpg"
        
        # 썸네일 크기 조정 (예: 320x240)
        height, width = image.shape[:2]
        aspect_ratio = width / height
        new_width = 320
        new_height = int(new_width / aspect_ratio)
        resized_image = cv2.resize(image, (new_width, new_height))
        
        cv2.imwrite(thumbnail_path, resized_image)
        vidcap.release()
        return thumbnail_path
    else:
        vidcap.release()
        raise Exception("비디오에서 프레임을 읽을 수 없습니다.")






    


