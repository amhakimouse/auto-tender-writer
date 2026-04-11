import os
import json
import google.generativeai as genai
from dotenv import load_dotenv
from loguru import logger
from app.core.config import settings

# Load environment variables
load_dotenv()

# Configuration
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

if not GEMINI_API_KEY:
    logger.error("GEMINI_API_KEY not found in environment variables.")
else:
    genai.configure(api_key=GEMINI_API_KEY)

# Step 1: Singleton Model
# Using the model name from settings to match available models
MODEL_NAME = settings.GEMINI_MODEL
gemini_model = genai.GenerativeModel(MODEL_NAME)

async def call_llm(
    system_prompt: str,
    user_message: str,
    model: str = MODEL_NAME,
    temperature: float = 0.7,
    response_format: str = "text"
) -> str:
    """
    Generic wrapper to call Gemini using the singleton model.
    """
    try:
        combined_prompt = f"SYSTEM: {system_prompt}\n\nUSER: {user_message}"
        
        generation_config = genai.GenerationConfig(
            temperature=temperature,
            response_mime_type="application/json" if response_format == "json" else "text/plain"
        )
        
        response = await gemini_model.generate_content_async(
            combined_prompt,
            generation_config=generation_config
        )
        
        return response.text
    except Exception as e:
        logger.error("LLM call failed: {error}", error=str(e))
        raise RuntimeError(f"LLM Generation failed: {str(e)}")
