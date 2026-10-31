import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env from project root
load_dotenv()

# Base directories
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
OUTPUT_DIR = BASE_DIR / "output"
SAMPLE_DIR = BASE_DIR / "sample"

DATA_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# API Keys and URLs
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
FUENTES_URL = os.getenv("FUENTES_URL", "https://reto-pii-fuentes-production.up.railway.app/v1")
FUENTES_TOKEN = os.getenv("FUENTES_TOKEN", "")

# Default LLM model for contextual processing
DEFAULT_MODEL = os.getenv("DEFAULT_MODEL", "openai/gpt-4o-mini")

# Database path
DB_PATH = DATA_DIR / "entity_map.db"


def get_openrouter_client():
    """Returns an OpenAI client configured for OpenRouter."""
    from openai import OpenAI

    api_key = os.getenv("OPENROUTER_API_KEY", OPENROUTER_API_KEY)
    if not api_key:
        raise ValueError("OPENROUTER_API_KEY not configured.")
    return OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=api_key,
    )


def query_llm(
    prompt: str,
    system_prompt: str = "Eres un asistente especializado en procesamiento de lenguaje natural y anonimización de datos.",
    model: str = DEFAULT_MODEL,
    temperature: float = 0.1,
    max_tokens: int = 1000,
) -> str:
    """Executes a chat completion query against OpenRouter."""
    client = get_openrouter_client()
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ],
        temperature=temperature,
        max_tokens=max_tokens,
    )
    return response.choices[0].message.content or ""
