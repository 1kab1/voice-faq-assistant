
import os
import json
import urllib.request
import urllib.error
from dotenv import load_dotenv

# Load settings from the .env file
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))

# Reusable constant to avoid duplicated string literals
JSON_CONTENT_TYPE = "application/json"

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-20b").strip()

ENABLE_OLLAMA = os.getenv("ENABLE_OLLAMA", "false").lower() == "true"
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:3b")
OLLAMA_URL = os.getenv(
    "OLLAMA_URL",
    "http://127.0.0.1:11434/api/chat"
)

SYSTEM_PROMPT = """
You are a helpful voice-based FAQ assistant.

Answer questions clearly and accurately.
You can discuss technology, science, education, health,
history, and everyday topics.

Keep answers concise and easy to understand because
they may be spoken aloud.

If you do not know something, say so.
"""


def ask_groq(question, conversation_history=None):
    """Get an AI response from GroqCloud."""

    if not GROQ_API_KEY or GROQ_API_KEY == "your_key_here":
        raise RuntimeError(
            "Groq API key is missing. Check your .env file."
        )

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT}
    ]

    # Include previous conversation messages when available
    if isinstance(conversation_history, list):
        for item in conversation_history:
            if not isinstance(item, dict):
                continue

            role = item.get("role")
            content = item.get("content")

            if role in ("user", "assistant") and isinstance(content, str):
                messages.append({
                    "role": role,
                    "content": content
                })

    messages.append({
        "role": "user",
        "content": str(question)
    })

    payload = {
        "model": GROQ_MODEL,
        "messages": messages,
        "temperature": 0.7,
        "max_tokens": 500
    }

    request = urllib.request.Request(
        "https://api.groq.com/openai/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {GROQ_API_KEY}",
            "Content-Type": JSON_CONTENT_TYPE,
            "Accept": JSON_CONTENT_TYPE,
            "User-Agent": "VoiceFAQAssistant/1.0"
        },
        method="POST"
    )

    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            result = json.load(response)

        return result["choices"][0]["message"]["content"].strip()

    except urllib.error.HTTPError as error:
        details = error.read().decode(
            "utf-8", errors="replace"
        )
        raise RuntimeError(
            f"Groq HTTP {error.code}: {details[:500]}"
        ) from error

    except urllib.error.URLError as error:
        raise RuntimeError(
            f"Groq connection error: {error.reason}"
        ) from error


def ask_ollama(question, conversation_history=None):
    """Get an AI response from local Ollama."""

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT}
    ]

    if isinstance(conversation_history, list):
        for item in conversation_history:
            if not isinstance(item, dict):
                continue

            role = item.get("role")
            content = item.get("content")

            if role in ("user", "assistant") and isinstance(content, str):
                messages.append({
                    "role": role,
                    "content": content
                })

    messages.append({
        "role": "user",
        "content": str(question)
    })

    payload = {
        "model": OLLAMA_MODEL,
        "messages": messages,
        "stream": False
    }

    request = urllib.request.Request(
        OLLAMA_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": JSON_CONTENT_TYPE
        },
        method="POST"
    )

    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            result = json.load(response)

        return result["message"]["content"].strip()

    except Exception as error:
        raise RuntimeError(
            f"Ollama request failed: {error}"
        ) from error


def generate_answer(question, conversation_history=None):
    """
    Main AI function.

    Accepts both:
        generate_answer(question)
        generate_answer(question, conversation_history)
    """

    try:
        return ask_groq(question, conversation_history)

    except Exception as groq_error:
        print(f"[Groq error] {groq_error}")

        if ENABLE_OLLAMA:
            try:
                return ask_ollama(question, conversation_history)

            except Exception as ollama_error:
                print(f"[Ollama error] {ollama_error}")

                return (
                    "I couldn't reach an AI model right now. "
                    f"Groq error: {groq_error}. "
                    f"Ollama error: {ollama_error}"
                )

        return (
            "I couldn't reach an AI model right now. "
            f"{groq_error}"
        )


# Compatibility functions
def get_ai_response(question, conversation_history=None):
    return generate_answer(question, conversation_history)


def generate_ai_answer(question, conversation_history=None):
    return generate_answer(question, conversation_history)


def ask_ai(question, conversation_history=None):
    return generate_answer(question, conversation_history)
