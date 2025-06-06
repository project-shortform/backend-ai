from openai import OpenAI
from dotenv import load_dotenv
import os
from google import genai

load_dotenv()

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# Gemini 클라이언트 생성
gemini_client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))