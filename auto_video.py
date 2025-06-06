import requests
import urllib.parse
import os
from dotenv import load_dotenv
import requests

load_dotenv()


def get_large_video_urls(
    search_term="", category="", video_type="film", per_page=20, page=1
):
    """
    Pixabay API를 사용해서 검색 결과 중 1920x1080 해상도 비디오 URL 리스트를 가져오는 함수

    Args:
        search_term (str): 검색할 키워드
        per_page (int): 페이지당 결과 수 (3-200, 기본값: 20)
        page (int): 페이지 번호 (기본값: 1)

    Returns:
        list: 1920x1080 해상도 비디오 URL 리스트
    """
    API_KEY = os.getenv("PIXABAY_API_KEY")
    BASE_URL = "https://pixabay.com/api/videos/"

    # 검색어 URL 인코딩
    encoded_search_term = urllib.parse.quote(search_term)

    # API 요청 파라미터
    params = {
        "key": API_KEY,
        "q": encoded_search_term,
        "category": category,
        "video_type": video_type,
        "per_page": per_page,
        "page": page,
        "safesearch": "true",  # 안전 검색 활성화
    }

    try:
        # API 요청
        response = requests.get(BASE_URL, params=params)
        response.raise_for_status()  # HTTP 에러 체크

        data = response.json()

        # 1920x1080 해상도 비디오 URL 리스트 추출
        hd_video_urls = []

        if "hits" in data:
            for video in data["hits"]:
                if "videos" in video:
                    # 모든 비디오 품질 옵션을 확인 (large, medium, small, tiny)
                    for quality in ["large", "medium", "small", "tiny"]:
                        if quality in video["videos"]:
                            video_info = video["videos"][quality]
                            # 1920x1080 해상도인지 확인
                            if (
                                video_info.get("width") == 1920
                                and video_info.get("height") == 1080
                            ):
                                url = video_info.get("url")
                                if url:  # URL이 비어있지 않은 경우만 추가
                                    hd_video_urls.append(url)
                                    break  # 하나의 영상에서 1920x1080을 찾으면 다른 품질은 확인하지 않음

        return hd_video_urls

    except requests.exceptions.RequestException as e:
        print(f"API 요청 오류: {e}")
        return []
    except Exception as e:
        print(f"처리 중 오류 발생: {e}")
        return []


# 사용 예시
if __name__ == "__main__":
    page = 1
    total_uploaded = 0
    while True:
        print(f"현재 페이지: {page}")
        video_urls = get_large_video_urls(per_page=100, page=page)

        print(video_urls)

        if not video_urls:
            print("더 이상 비디오가 없습니다. 종료합니다.")
            break
        print(f"가져온 비디오 개수: {len(video_urls)}")
        print("--------------------------------")
        for i, url in enumerate(video_urls, 1):
            try:
                res = requests.post(
                    "http://49.143.34.88:5000/api/video/upload_url?url=" + url
                )
                print("index: ", total_uploaded + i)
                print(f"응답 상태 코드: {res.status_code}")
                
                # 응답 상태 코드 확인
                if res.status_code == 200:
                    # 응답 내용이 JSON인지 확인
                    try:
                        response_json = res.json()
                        print(response_json)
                    except ValueError as json_error:
                        print(f"JSON 파싱 오류: {json_error}")
                        print(f"응답 내용: {res.text}")
                else:
                    print(f"서버 오류: {res.status_code}")
                    print(f"응답 내용: {res.text}")
                    
            except requests.exceptions.RequestException as e:
                print(f"네트워크 오류 발생: {e}")
            except Exception as e:
                print(f"기타 오류 발생: {e}")
            print("--------------------------------")
        total_uploaded += len(video_urls)
        page += 1

        # 너무 많은 요청을 방지하기 위해 잠깐 대기 (필요시)
        # import time; time.sleep(1)
