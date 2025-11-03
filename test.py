import json
import time
import re
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

def get_pixabay_music_urls(url, max_results=5):
    """
    Pixabay 음악 검색 페이지에서 다운로드 URL을 추출합니다.
    
    Args:
        url (str): Pixabay 음악 검색 페이지 URL
        max_results (int): 최대 결과 수
    
    Returns:
        list: 음악 URL 목록
    """
    try:
        # 1. Selenium 웹드라이버 설정
        chrome_options = Options()
        chrome_options.add_argument("--headless")  # 브라우저 창을 표시하지 않음
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--window-size=1920,1080")
        chrome_options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
        
        # 드라이버 생성 (webdriver-manager 사용)
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=chrome_options)
        
        # 2. 페이지 접근 및 로딩 대기
        print(f"'{url}'에서 음악 URL 추출 시도 중...")
        driver.get(url)
        
        # 페이지가 완전히 로드될 때까지 대기
        WebDriverWait(driver, 20).until(
            EC.presence_of_element_located((By.TAG_NAME, "body"))
        )
        
        # 추가 로딩 시간 대기 (JavaScript 실행)
        print("페이지 로딩 대기 중...")
        time.sleep(15)  # 더 긴 대기 시간
        
        # 3. 페이지 스크롤하여 동적 콘텐츠 로드
        print("페이지 스크롤 중...")
        for i in range(3):  # 3번 스크롤
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(3)  # 스크롤 후 대기
        
        # 맨 위로 다시 스크롤
        driver.execute_script("window.scrollTo(0, 0);")
        time.sleep(3)
        
        # 4. 음악 카드 링크 찾기
        print("음악 카드 링크 찾는 중...")
        music_urls = []
        
        # 음악 카드를 나타내는 요소 찾기
        music_cards = driver.find_elements(By.CSS_SELECTOR, "a[href*='/music/']")
        print(f"{len(music_cards)}개의 음악 카드 링크를 찾았습니다.")
        
        # 각 음악 카드 링크에서 개별 음악 페이지로 이동
        for i, card in enumerate(music_cards[:max_results]):
            try:
                # 카드 링크 가져오기
                card_link = card.get_attribute("href")
                if not card_link or not card_link.startswith("http"):
                    continue
                
                print(f"{i+1}. 음악 페이지로 이동: {card_link}")
                
                # 새 탭에서 개별 음악 페이지 열기
                driver.execute_script("window.open('');")
                driver.switch_to.window(driver.window_handles[1])
                driver.get(card_link)
                
                # 페이지 로딩 대기
                time.sleep(5)
                
                # 개별 음악 페이지에서 다운로드 URL 찾기
                print("  개별 음악 페이지에서 다운로드 URL 찾는 중...")
                
                # 방법 1: 다운로드 버튼 찾기
                try:
                    download_btn = driver.find_element(By.CSS_SELECTOR, "[data-testid='download-button'], .download-button, .download")
                    if download_btn and download_btn.get_attribute("href"):
                        download_url = download_btn.get_attribute("href")
                        if 'cdn.pixabay.com/download/audio/' in download_url and download_url.endswith('.mp3'):
                            music_urls.append(download_url)
                            print(f"  다운로드 URL 찾음: {download_url}")
                except Exception as e:
                    print(f"  다운로드 버튼 찾기 오류: {e}")
                
                # 방법 2: 페이지 소스에서 URL 패턴 찾기
                if not music_urls or len(music_urls) <= i:
                    try:
                        page_source = driver.page_source
                        pattern = r'https://cdn\.pixabay\.com/download/audio/\d{4}/\d{2}/\d{2}/audio_[a-zA-Z0-9]+\.mp3\?filename=[^"\'\s]+'
                        matches = re.findall(pattern, page_source)
                        
                        for match in matches:
                            music_urls.append(match)
                            print(f"  페이지 소스에서 URL 찾음: {match}")
                    except Exception as e:
                        print(f"  페이지 소스에서 URL 찾기 오류: {e}")
                
                # 방법 3: JavaScript 실행으로 데이터 가져오기
                if not music_urls or len(music_urls) <= i:
                    try:
                        js_code = """
                        var downloadUrl = null;
                        
                        // 다운로드 버튼 찾기
                        var downloadBtn = document.querySelector("[data-testid='download-button'], .download-button, .download");
                        if (downloadBtn && downloadBtn.href) {
                            downloadUrl = downloadBtn.href;
                        }
                        
                        // 페이지 소스에서 URL 패턴 찾기
                        if (!downloadUrl) {
                            var pageSource = document.documentElement.outerHTML;
                            var pattern = /https:\\/\\/cdn\\.pixabay\\.com\\/download\\/audio\\/\\d{4}\\/\\d{2}\\/\\d{2}\\/audio_[a-zA-Z0-9]+\\.mp3\\?filename=[^"'\\s]+/g;
                            var matches = pageSource.match(pattern);
                            
                            if (matches && matches.length > 0) {
                                downloadUrl = matches[0];
                            }
                        }
                        
                        return downloadUrl;
                        """
                        
                        download_url = driver.execute_script(js_code)
                        if download_url and 'cdn.pixabay.com/download/audio/' in download_url and download_url.endswith('.mp3'):
                            music_urls.append(download_url)
                            print(f"  JavaScript 실행으로 URL 찾음: {download_url}")
                    except Exception as e:
                        print(f"  JavaScript 실행 오류: {e}")
                
                # 현재 탭 닫고 메인 탭으로 돌아가기
                driver.close()
                driver.switch_to.window(driver.window_handles[0])
                
                # 다음 음악 카드를 위해 잠시 대기
                time.sleep(2)
                
            except Exception as e:
                print(f"음악 카드 처리 오류: {e}")
                try:
                    # 현재 탭이 있으면 닫고 메인 탭으로 돌아가기
                    if len(driver.window_handles) > 1:
                        driver.close()
                        driver.switch_to.window(driver.window_handles[0])
                except:
                    pass
        
        driver.quit()
        
        # 중복 제거
        music_urls = list(set(music_urls))
        
        return music_urls[:max_results]
        
    except Exception as e:
        print(f"오류 발생: {e}")
        return []

# --- 스크립트 실행 ---
if __name__ == "__main__":
    target_url = 'https://pixabay.com/music/search/?order=ec'
    
    urls = get_pixabay_music_urls(target_url)
    
    if urls:
        print(f"\n[성공] 총 {len(urls)}개의 다운로드 URL을 추출했습니다:\n")
        for i, url in enumerate(urls, 1):
            print(f"{i:02d}. {url}")
    else:
        print("\n[실패] URL을 추출하지 못했습니다.")
        print("가능한 원인:")
        print("1. Pixabay 웹사이트 구조가 변경되었을 수 있습니다.")
        print("2. 로그인이 필요할 수 있습니다.")
        print("3. 봇 탐지 시스템에 차단되었을 수 있습니다.")