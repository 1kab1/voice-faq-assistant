"""Keyword FAQ first, Groq then optional Ollama only on FAQ misses."""
from knowledge_base import FAQS
from ai_engine import generate_answer
import re

def normalize(text):
    return " ".join(re.findall(r"[a-z0-9]+", text.lower()))

def match_faq(question):
    query = normalize(question)
    if not query:
        return None
    for key, answer in FAQS.items():
        normalized = normalize(key)
        if query == normalized or (len(normalized.split()) >= 3 and normalized in query):
            return answer
    return None

def answer_question(question, history=None):
    match = match_faq(question)
    return match if match is not None else generate_answer(question, history)
