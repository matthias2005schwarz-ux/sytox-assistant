"""Analyze an explicitly supplied in-memory screenshot with local Ollama."""

import base64
import requests

def explain_image(png_data, question, model="qwen3-vl:2b"):
    """Only caller-supplied images. No automatic recording or file storage."""
    if not png_data or not question.strip():
        raise ValueError("Bild und Frage erforderlich.")
    if not model or any(c in model for c in " /\\\n"):
        raise ValueError("Ungueltiges Modell.")
    payload = {
        "model": model,
        "stream": False,
        "messages": [{"role": "user",
                      "content": question,
                      "images": [base64.b64encode(png_data).decode("ascii")]}],
    }
    response = requests.post("http://127.0.0.1:11434/api/chat", json=payload, timeout=180)
    response.raise_for_status()
    return response.json().get("message", {}).get("content", "")
