from fastapi import APIRouter
from src.lib.llm import client
from pydantic import BaseModel
from fastapi import Body

router = APIRouter(prefix="/api/story")

# 입력 프롬프트 - Request body

class Style(BaseModel):
    category: str
    concept: str
    quantity: str

class Viewers(BaseModel):
    sex: str
    age: str
    viewers_style: str

class Info(BaseModel):
    request_info: str

class StoryInput(BaseModel):
    style: Style
    viewers: Viewers
    info: Info

# 출력 프롬프트 - Response body

class Scene(BaseModel):
    scene: int
    script: str
    subtitle: str

class Story(BaseModel):
    story: list[Scene]


@router.post("/generate")
def generate_story(input: StoryInput = Body(...)):
    # JSON 입력을 텍스트 포맷으로 변환
    text = f"""
**[영상 스타일 정보]**
- 카테고리: {input.style.category}
- 스토리 컨셉: {input.style.concept}
- 분량: {input.style.quantity}

**[영상 시청자 정보]**
- 성별: {input.viewers.sex}
- 연령대: {input.viewers.age}
- 시청자 스타일: {input.viewers.viewers_style}

**[상세 정보]**
- 영상에 대한 추가 요구사항: {input.info.request_info}
"""

    response = client.responses.parse(
        model="gpt-4.1",
        input=[
            {"role": "system", "content": """
             ### System Instructions (Custom GPT용)

            당신은 `StoryboardMaker`라는 이름의 스토리보드 제작 전문가 AI 어시스턴트입니다.  
            당신의 주 임무는 사용자가 제공한 입력 항목을 바탕으로, 콘텐츠 기획자나 영상 제작자가 사용할 수 있는 **구조적이고 감정 흐름이 명확한 스토리보드**를 작성하는 것입니다.

            ---

            ### 입력 항목 설명

            사용자는 아래 형식으로 스토리보드 제작을 요청합니다. 이 항목들을 분석하여 스토리보드 구성의 기반으로 삼으십시오.

            **[영상 스타일 정보]**  
            - 카테고리 (예: 정보전달, 광고&홍보, 교육 등)  
            - 스토리 컨셉 (예: 유머러스한, 감성적인, 신뢰감 있는 등)  
            - 분량 (예: 15초, 30초, 1분, 3분, 5분)

            **[영상 시청자 정보]**  
            - 성별 (예: 여자, 남자, 선택 안함)
            - 연령대 (예: 10대, 20-30대, 노인 등)
            - 시청자 스타일 (예: 빠른 정보 소비형, 지식을 중요하게 생각하는  등)

            **[상세 정보]**  
            - 영상에 대한 추가 요구사항 (예: 포함해야 할 장면, 톤앤매너, 감정선, 효과, 내레이션 등)

            ---

            ### 출력 형식 안내

            당신은 다음과 같은 형식으로 스토리보드를 작성해야 합니다:

            ```
            [
            {
                "scene" : 1
                "script": "A window seat with soft sunlight. Latte and a flower on a wooden table. Calm piano music in the background. A young woman is filming coffee on her phone.",
                "subtitle": "나만의 시간을 더 특별하게 만드는 공간,"
            },
            {
                "scene" : 2
                ...
            }
            ]
            ```

            - 총 분량과 균형을 고려하여 적절한 수의 장면을 구성하십시오.
            - 시청자의 몰입을 유도하기 위한 감정 흐름과 템포 조절이 중요합니다.
            - scene 타이틀을 입력하지 마세요. 최대한 장면 설명에 입력되게 작성해주세요.
            - 음성 및 자막에서 나레이션과 대사를 구분하지 않습니다. 또한, 쌍따옴표(")를 입력하지 말고 텍스트로만 출력하세요.
            - script 는 '영어'로 작성하세요.
            - subtitle 은 '한국어'로 작성하세요.
            - script는 영상 임베딩에 사용할 내용이므로 영상 임베딩에 최대의 효율을 낼 수 있도록 작성해줘.
            
            <영상 분량(quantity) 조절 관련 참고 사항> 
            - 사용자가 입력한 분량 (예: 15초, 30초, 1분, 3분, 5분) 에 맞게 씬 개수를 적절히 선택하세요.
            - 15초 → 한 씬 당 자막 길이 TTS로 읽었을 때 4초 → 씬 개수 4개
            - 30초 → 한 씬 당 자막 길이 TTS로 읽었을 때 4초 → 씬 개수 8개
            - 1분 → 한 씬 당 자막 길이 TTS로 읽었을 때 5초 → 씬 개수 12개
            - 3분 → 한 씬 당 자막 길이 TTS로 읽었을 때 5초 → 씬 개수 36개
            - 5분 → 한 씬 당 자막 길이 TTS로 읽었을 때 5초 → 씬 개수 60개

            Important!
            - 출력 형식을 반드시 **JSON 코드** 형식으로 반환해주세요.
            ```
            ---

            ### 지켜야 할 핵심 원칙

            - 사용자의 입력 내용을 충실히 반영하십시오.  
            - 입력이 불완전한 경우, **상황에 맞게 창의적으로 보완**하십시오.  
            - 장면 구성은 **명확한 흐름, 감정 곡선**, 그리고 **시청자 몰입도**를 고려해 설계되어야 합니다. 
            - **단순 설명이 아닌, 시각적으로 그려지는 구성**을 목표로 하십시오.
            - 출력 형식을 **JSON 코드**로 반환하십시오.
            - 절대 씬의 내용(script, subtitle)을 비우지 마세요.
            
             """},
            {
                "role": "user", 
                "content": text
            },
        ],
        text_format=Story,
    )

    return response.output_parsed