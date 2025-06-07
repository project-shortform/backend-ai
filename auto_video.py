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
    # 모든 카테고리 리스트
    categories = [
        "backgrounds", "fashion", "nature", "science", "education", 
        "feelings", "health", "people", "religion", "places", 
        "animals", "industry", "computer", "food", "sports", 
        "transportation", "travel", "buildings", "business", "music"
    ]
    
    # 시작할 카테고리 설정 (None이면 처음부터, 특정 카테고리명을 입력하면 해당 카테고리부터 시작)
    start_category = "science"  # 예: "nature", "animals", "music" 등
    
    total_uploaded = 0
    
    # 시작 카테고리가 지정된 경우, 해당 카테고리부터 시작하도록 리스트 슬라이싱
    if start_category:
        if start_category in categories:
            start_index = categories.index(start_category)
            categories = categories[start_index:]
            print(f"'{start_category}' 카테고리부터 시작합니다.")
        else:
            print(f"경고: '{start_category}' 카테고리를 찾을 수 없습니다. 처음부터 시작합니다.")
            print(f"사용 가능한 카테고리: {', '.join(categories)}")
    
    for category in categories:
        print(f"=== 카테고리: {category} ===")
        page = 1  # 각 카테고리마다 페이지 1부터 시작
        
        while True:
            print(f"현재 카테고리: {category}, 페이지: {page}")
            video_urls = get_large_video_urls(category=category, per_page=100, page=page)

            print(video_urls)

            if not video_urls:
                print(f"카테고리 '{category}'에서 더 이상 비디오가 없습니다. 다음 카테고리로 이동합니다.")
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

        print(f"카테고리 '{category}' 완료. 총 업로드된 비디오 수: {total_uploaded}")
        print("=" * 50)

    print(f"모든 카테고리 완료! 총 업로드된 비디오 수: {total_uploaded}")

        # 너무 많은 요청을 방지하기 위해 잠깐 대기 (필요시)
        # import time; time.sleep(1)
