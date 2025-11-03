# Backend AI - 비디오 AI 생성 서비스

AI 기반 비디오 생성 및 관리 서비스입니다.

## 환경 설정

### 필수 환경 변수

프로젝트 루트에 `.env` 파일을 생성하고 다음 환경 변수들을 설정해주세요:

```bash
# Google Gemini API (TTS용)
GEMINI_API_KEY=your_gemini_api_key_here

# OpenAI API (기존 TTS 및 LLM용)
OPENAI_API_KEY=your_openai_api_key_here

# 기타 설정...
```

### TTS (Text-to-Speech) 설정

현재 **Google Gemini 2.5 Flash TTS**를 사용합니다.

#### 지원하는 Gemini TTS 보이스
- **Zephyr** - 기본 여성 보이스
- **Charon** - 남성 보이스
- **Kore** - 여성 보이스
- **Fenrir** - 남성 보이스  
- **Aoede** - 여성 보이스
- **Puck** - 남성 보이스

> API 호출 시 `voice_name` 파라미터에 위 보이스 이름을 직접 사용하세요.

## 프로젝트 실행

```bash
uv run main.py
```

## API 문서 접속

```bash
http://localhost:5000/docs
```

## 주요 기능

- 🤖 AI 기반 비디오 자동 생성
- 🎯 스크립트 기반 영상 매칭
- 🔊 Gemini TTS를 활용한 음성 생성
- 📊 비동기 작업 큐 관리
- 📚 비디오 생성 히스토리 관리

