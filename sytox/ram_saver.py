"""Memory-friendly Ollama keep-alive policy for SYTOX requests.

The value is sent with every /api/chat request, so Ollama unloads the model
after the *completed* response has been idle for the configured duration.
No model files are deleted, and this does not terminate the Ollama server.
"""
from __future__ import annotations

DEFAULT_KEEP_ALIVE_SECONDS = 60
MAX_KEEP_ALIVE_SECONDS = 3600


def normalized_keep_alive_seconds(value):
    """Return a safe delay (seconds), falling back to one minute."""
    try:
        parsed = int(value)
    except (ValueError, TypeError, OverflowError):
        return DEFAULT_KEEP_ALIVE_SECONDS
    if not 0 <= parsed <= MAX_KEEP_ALIVE_SECONDS:
        return DEFAULT_KEEP_ALIVE_SECONDS
    return parsed


def keep_alive_for_config(config):
    """Ollama keep_alive: 0 for immediate unload, '<n>s', or None when off."""
    if not config.get('ram_saver_enabled', True):
        return None
    seconds = normalized_keep_alive_seconds(
        config.get('ram_keep_alive_seconds', DEFAULT_KEEP_ALIVE_SECONDS)
    )
    return 0 if seconds == 0 else f'{seconds}s'
