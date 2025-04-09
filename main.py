from fastapi import FastAPI, UploadFile, File, Body
from pathlib import Path
import uuid
from pydantic import BaseModel
import uvicorn
from src.lib import get_embeddings, add_to_chroma, search_chroma

app = FastAPI()

UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)
TEMP_DIR = Path("temp")
TEMP_DIR.mkdir(exist_ok=True)



@app.get("/")
def read_root():
    return {"message": "Hello World"}

@app.post("/upload")
def upload_file(
    file: UploadFile = File(...),
):
    infomation = file.filename
    
    file_name = f"{uuid.uuid4()}_{file.filename}"
    
    # 파일 저장
    file_path = UPLOAD_DIR / file_name
    with open(file_path, "wb") as buffer:
        content = file.file.read()
        buffer.write(content)

    # 임베딩 생성
    ids = add_to_chroma(infomation, {"file_name": file_name, "infomation": infomation})
    print(ids)

    return ids

@app.get("/search")
def search_file(
    text: str
):
    results = search_chroma(text)
    
    # 결과 가공
    processed_results = []
    
    for i in range(len(results["documents"][0])):
        processed_results.append({
            "file_name": results["metadatas"][0][i]["file_name"],
            "metadata": results["metadatas"][0][i]
        })
    
    return processed_results

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=5000)
