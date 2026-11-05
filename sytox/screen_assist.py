"""Local screenshot question answering for an explicitly enabled session.

This module cannot take screenshots, open windows, or write images to disk.
All image data is supplied by the calling GUI after a user question.
"""
from __future__ import annotations

import base64
import re
import threading

import requests


def explain_image(png_data: bytes, question: str, model: str = 'qwen3-vl:2b',
                  stop: threading.Event | None = None) -> str:
    """Analyze one in-memory screenshot through loopback Ollama only."""
    if not isinstance(png_data, bytes) or not png_data.startswith(bytes.fromhex('89504e470d0a1a0a')):
        raise ValueError('Ungueltiges PNG-Bild.')
    if not 0 < len(png_data) <= 15 * 1024 * 1024:
        raise ValueError('PNG-Bild ist zu gross.')
    question = str(question or '').strip()
    if not question:
        raise ValueError('Bitte stelle eine Frage zum Bildschirm.')
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:/-]{0,127}', model):
        raise ValueError('Ungueltiger Modellname.')
    if stop is not None and stop.is_set():
        raise InterruptedError('Bildschirmfreigabe beendet.')

    payload = {
        'model': model,
        'stream': False,
        'messages': [
            {'role': 'system',
             'content': ('Du hilfst auf Deutsch bei einem vom Nutzer freigegebenen Screenshot. '
                         'Beschreibe erkannte Fehler und erklaere konkrete Schritte. '
                         'Wenn etwas nicht lesbar ist, sage es. '
                         'Gib keine Passwoerter oder privaten Codes aus.')},
            {'role': 'user', 'content': question[:2000],
             'images': [base64.b64encode(png_data).decode('ascii')]},
        ],
    }
    # Deliberately fixed loopback endpoint; no HTTP redirects to remote servers.
    response = requests.post('http://127.0.0.1:11434/api/chat', json=payload,
                             timeout=(5, 180), allow_redirects=False)
    response.raise_for_status()
    if stop is not None and stop.is_set():
        raise InterruptedError('Bildschirmfreigabe beendet.')
    result = response.json()
    return str(result.get('message', {}).get('content') or '').strip() or (
        'Ich konnte den Screenshot nicht sicher auswerten.')
