import requests
import urllib.parse
import os
from dotenv import load_dotenv
import requests

load_dotenv()

def get_large_video_urls(search_term="", category="", video_type="film", per_page=20, page=1):
    """
    Pixabay API를 사용해서 검색 결과 중 large 사이즈 비디오 URL 리스트를 가져오는 함수
    
    Args:
        search_term (str): 검색할 키워드
        per_page (int): 페이지당 결과 수 (3-200, 기본값: 20)
        page (int): 페이지 번호 (기본값: 1)
    
    Returns:
        list: large 사이즈 비디오 URL 리스트
    """
    API_KEY = os.getenv("PIXABAY_API_KEY")
    BASE_URL = 'https://pixabay.com/api/videos/'
    
    # 검색어 URL 인코딩
    encoded_search_term = urllib.parse.quote(search_term)
    
    # API 요청 파라미터
    params = {
        'key': API_KEY,
        'q': encoded_search_term,
        'category': category,
        'video_type': video_type,
        'per_page': per_page,
        'page': page,
        'safesearch': 'true'  # 안전 검색 활성화
    }
    
    try:
        # API 요청
        response = requests.get(BASE_URL, params=params)
        response.raise_for_status()  # HTTP 에러 체크
        
        data = response.json()
        
        # large 비디오 URL 리스트 추출
        large_video_urls = []
        
        if 'hits' in data:
            for video in data['hits']:
                if 'videos' in video and 'large' in video['videos']:
                    large_url = video['videos']['large']['url']
                    if large_url:  # URL이 비어있지 않은 경우만 추가
                        large_video_urls.append(large_url)
        
        return large_video_urls
        
    except requests.exceptions.RequestException as e:
        print(f"API 요청 오류: {e}")
        return []
    except Exception as e:
        print(f"처리 중 오류 발생: {e}")
        return []

# 사용 예시
if __name__ == "__main__":
    video_urls = get_large_video_urls(per_page=100, page=2)
    print(video_urls)
    print("--------------------------------")
    
    for i, url in enumerate(video_urls, 1):
        res = requests.post("http://49.143.34.88:5000/api/video/upload_url?url=" + url)
        print("index: ", i)
        print(res.json())
        print("--------------------------------")
