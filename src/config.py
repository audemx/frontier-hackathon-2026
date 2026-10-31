import os
from openai import OpenAI

def get_openrouter_client():
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        raise ValueError("OPENROUTER_API_KEY not configured in terminal.")
    
    return OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=api_key,
    )

def query_llm(prompt: str, system_prompt: str = "You are a helpful engineering assistant."):
    client = get_openrouter_client()
    response = client.chat.completions.create(
        model="google/gemini-2.0-flash-001",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt}
        ],
        temperature=0.2 # Lower temperature for more deterministic responses
    )
    return response.choices[0].message.content