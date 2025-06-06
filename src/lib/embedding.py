from google import genai
import os
from dotenv import load_dotenv
from typing import Optional
import chromadb
import uuid

chroma_client = chromadb.PersistentClient()

if not chroma_client.heartbeat():
    raise Exception("Chroma DB 연결 실패")

# Gemini 임베딩 모델에 최적화된 코사인 거리 함수 사용
video_collection = chroma_client.get_or_create_collection(
    name="video", 
    metadata={"hnsw:space": "cosine"}
)

# 환경 변수 로드
load_dotenv()

# Gemini 클라이언트 초기화
def get_gemini_client(api_key: Optional[str] = None):
    """Gemini 클라이언트를 초기화합니다."""
    if api_key is None:
        api_key = os.getenv("GEMINI_API_KEY")
    return genai.Client(api_key=api_key)


def get_embeddings(
    texts: list[str],
    model: str = "gemini-embedding-exp-03-07",
    api_key: Optional[str] = None,
):
    """
    텍스트 리스트의 임베딩을 생성합니다.

    Args:
        texts (list): 임베딩을 생성할 텍스트 리스트
        model (str): 사용할 임베딩 모델명 (기본값: "gemini-embedding-exp-03-07")
        api_key (str, optional): API 키. 지정하지 않으면 환경 변수에서 가져옵니다.

    Returns:
        list: 각 텍스트의 임베딩 벡터 리스트
    """
    client = get_gemini_client(api_key)
    
    embeddings = []
    for text in texts:
        result = client.models.embed_content(
            model=model,
            contents=text,
        )
        # result.embeddings는 ContentEmbedding 객체들의 리스트
        # 각 ContentEmbedding 객체에서 values 속성을 추출
        if hasattr(result.embeddings[0], 'values'):
            embeddings.append(result.embeddings[0].values)
        else:
            # 이미 float 리스트인 경우
            embeddings.append(result.embeddings[0])

    return embeddings


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
        ids=ids, embeddings=embeddings, documents=[text], metadatas=[metadata]
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
        
    Note:
        코사인 거리 해석:
        - 0.0 ~ 0.2: 매우 유사함
        - 0.2 ~ 0.5: 유사함  
        - 0.5 ~ 1.0: 보통
        - 1.0 ~ 2.0: 다름
    """
    results = video_collection.query(
        query_embeddings=get_embeddings([text]), n_results=n_results
    )

    return results


# 사용 예시:
if __name__ == "__main__":
    texts = ["good morning from litellm", "this is another item"]
    embeddings = get_embeddings(texts)

    print(embeddings[0])
    print(embeddings[1])
