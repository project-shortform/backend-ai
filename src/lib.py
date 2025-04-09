from litellm import embedding
import os
from dotenv import load_dotenv
from typing import Optional
import chromadb
import uuid

chroma_client = chromadb.PersistentClient()

if not chroma_client.heartbeat():
    raise Exception("Chroma DB 연결 실패")

video_collection = chroma_client.get_collection(name="video")

if video_collection is None:
    video_collection = chroma_client.create_collection(name="video")

# 환경 변수 로드
load_dotenv()

def get_embeddings(texts: list[str], model: str="embed-multilingual-v3.0", input_type: str="search_document", api_key: Optional[str]=None):
    """
    텍스트 리스트의 임베딩을 생성합니다.
    
    Args:
        texts (list): 임베딩을 생성할 텍스트 리스트
        model (str): 사용할 임베딩 모델명 (기본값: "embed-english-v3.0")
        input_type (str): 임베딩 입력 타입 (기본값: "search_document")
        api_key (str, optional): API 키. 지정하지 않으면 환경 변수에서 가져옵니다.
    
    Returns:
        list: 각 텍스트의 임베딩 벡터 리스트
    """
    if api_key is None:
        api_key = os.getenv("COHERE_API_KEY")
    
    response = embedding(
        model=model,
        input=texts,
        input_type=input_type,
        api_key=api_key
    )
    
    # 각 텍스트에 대한 임베딩 반환
    return [item['embedding'] for item in response.data]

def add_to_chroma(text: str, metadata: dict):
    """
    텍스트와 메타데이터를 Chroma DB에 추가합니다.
    
    Args:
        texts (list[str]): 저장할 텍스트 리스트
        metadata (list[dict]): 각 텍스트에 해당하는 메타데이터 리스트
        collection: ChromaDB 컬렉션 객체 (없으면 기본 컬렉션 사용)
    
    Returns:
        list: 생성된 ID 리스트
    """
    # UUID를 사용하여 고유 ID 생성
    ids = [str(uuid.uuid4())]
    
    embeddings = get_embeddings([text])

    video_collection.add(
        ids=ids,
        embeddings=embeddings,
        documents=[text],
        metadatas=[metadata]
    )
    
    return ids  # 생성된 ID 반환 (필요시 활용 가능)

def search_chroma(text: str, n_results: int = 10):
    """
    Chroma DB에서 텍스트를 검색합니다.
    
    Args:
        query (str): 검색할 쿼리 텍스트
        n_results (int): 검색 결과 수 (기본값: 10)
    
    Returns:
        list: 검색 결과 리스트
    """
    results = video_collection.query(
        query_embeddings=get_embeddings([text]),
        n_results=n_results
    )
    
    return results


# 사용 예시:
if __name__ == "__main__":
    texts = ["good morning from litellm", "this is another item"]
    embeddings = get_embeddings(texts)
    
    print(embeddings[0])
    print(embeddings[1])