from tinydb import TinyDB, Query
import os
import json
from datetime import datetime

# DB 디렉토리 생성
os.makedirs('db', exist_ok=True)

# TinyDB 인스턴스 생성
video_db = TinyDB('db/videos.json')
task_db = TinyDB('db/tasks.json')  # 태스크 상태 저장용 DB
video_url_db = TinyDB('db/video_urls.json')  # 비디오 URL 저장용 DB

def save_video_generation_info(output_path, video_infos, story_request=None, generation_options=None):
    """
    영상 생성 정보를 DB에 저장합니다.
    
    Args:
        output_path (str): 생성된 최종 영상의 경로
        video_infos (list): 사용된 영상, 오디오, 자막 정보 리스트
        story_request (dict, optional): 원본 StoryRequest 인풋 데이터
        generation_options (dict, optional): 생성 시 사용된 옵션들
    
    Returns:
        int: 저장된 레코드의 ID
    """
    record = {
        'output_path': output_path,
        'created_at': datetime.now().isoformat(),
        'video_infos': video_infos,
        'story_request': story_request,  # 원본 인풋 데이터 저장
        'generation_options': generation_options  # 생성 옵션들 저장
    }
    
    return video_db.insert(record)

def get_video_generation_history():
    """
    저장된 모든 영상 생성 기록을 가져옵니다.
    
    Returns:
        list: 영상 생성 기록 리스트
    """
    return video_db.all()

def get_video_generation_by_id(record_id):
    """
    특정 ID의 영상 생성 기록을 가져옵니다.
    
    Args:
        record_id (int): 찾고자 하는 레코드 ID
    
    Returns:
        dict: 영상 생성 기록 또는 None
    """
    return video_db.get(doc_id=record_id)

# === 태스크 관리 함수들 ===

def save_task_info(task_id: str, task_data: dict):
    """
    태스크 정보를 DB에 저장합니다.
    
    Args:
        task_id (str): 태스크 ID
        task_data (dict): 태스크 데이터
    
    Returns:
        int: 저장된 레코드의 ID
    """
    record = {
        'task_id': task_id,
        'created_at': datetime.now().isoformat(),
        'updated_at': datetime.now().isoformat(),
        **task_data
    }
    
    return task_db.insert(record)

def update_task_info(task_id: str, update_data: dict):
    """
    태스크 정보를 업데이트합니다.
    
    Args:
        task_id (str): 태스크 ID
        update_data (dict): 업데이트할 데이터
    
    Returns:
        bool: 업데이트 성공 여부
    """
    Task = Query()
    update_data['updated_at'] = datetime.now().isoformat()
    
    result = task_db.update(update_data, Task.task_id == task_id)
    return len(result) > 0

def get_task_info(task_id: str):
    """
    특정 태스크 정보를 가져옵니다.
    
    Args:
        task_id (str): 태스크 ID
    
    Returns:
        dict: 태스크 정보 또는 None
    """
    Task = Query()
    return task_db.get(Task.task_id == task_id)

def get_all_tasks():
    """
    모든 태스크 정보를 가져옵니다.
    
    Returns:
        list: 태스크 정보 리스트
    """
    return task_db.all()

def delete_task_info(task_id: str):
    """
    태스크 정보를 삭제합니다.
    
    Args:
        task_id (str): 태스크 ID
    
    Returns:
        bool: 삭제 성공 여부
    """
    Task = Query()
    result = task_db.remove(Task.task_id == task_id)
    return len(result) > 0

# === 비디오 URL 관리 함수들 ===

def save_video_url(url: str, file_name: str, metadata: dict = None):
    """
    비디오 URL 정보를 DB에 저장합니다.
    
    Args:
        url (str): 비디오 URL
        file_name (str): 저장된 파일명
        metadata (dict, optional): 추가 메타데이터
    
    Returns:
        int: 저장된 레코드의 ID
    """
    record = {
        'url': url,
        'file_name': file_name,
        'created_at': datetime.now().isoformat(),
        'metadata': metadata or {}
    }
    
    return video_url_db.insert(record)

def check_url_exists(url: str):
    """
    URL이 이미 존재하는지 확인합니다.
    
    Args:
        url (str): 확인할 URL
    
    Returns:
        dict: 기존 레코드 정보 또는 None
    """
    UrlQuery = Query()
    return video_url_db.get(UrlQuery.url == url)

def get_all_video_urls():
    """
    저장된 모든 비디오 URL 정보를 가져옵니다.
    
    Returns:
        list: 비디오 URL 정보 리스트
    """
    return video_url_db.all()

def delete_video_url(url: str):
    """
    비디오 URL 정보를 삭제합니다.
    
    Args:
        url (str): 삭제할 URL
    
    Returns:
        bool: 삭제 성공 여부
    """
    UrlQuery = Query()
    result = video_url_db.remove(UrlQuery.url == url)
    return len(result) > 0
