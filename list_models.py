import os
import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv() # Ensure GEMINI_API_KEY is loaded
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

if not GEMINI_API_KEY:
    print("GEMINI_API_KEY not found. Please set it in your .env file.")
else:
    genai.configure(api_key=GEMINI_API_KEY)
    print("Available Gemini Models:")
    for m in genai.list_models():
        if 'generateContent' in m.supported_generation_methods:
            print(f"  - {m.name} (Supports generateContent)")