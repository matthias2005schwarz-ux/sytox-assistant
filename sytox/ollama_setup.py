"""Non-destructive Ollama readiness checks for the Windows desktop client.

This module deliberately never starts a process, downloads a model, or contacts a
remote service on behalf of the user.  The UI offers explicit setup steps.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from urllib.parse import urlparse

import requests

OLLAMA_DOWNLOAD = 'https://ollama.com/download/windows'
_MODEL_PATTERN = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_.:/-]{0,127}$')


@dataclass(frozen=True)
class OllamaStatus:
    state: str  # ready, offline, missing_model, invalid_config, error
    title: str
    details: str
    available_models: tuple[str, ...] = ()

    @property
    def ready(self) -> bool:
        return self.state == 'ready'


def model_pull_command(model: str) -> str:
    """Return a safe command that may be *copied*, never executed by SYTOX."""
    if not _MODEL_PATTERN.fullmatch(str(model).strip()):
        raise ValueError('Ungültiger Modellname. Bitte in den Einstellungen korrigieren.')
    return 'ollama pull ' + model.strip()


def check_ollama_status(base_url: str, model: str, get=None) -> OllamaStatus:
    """Check the Ollama tags API with a bounded timeout and distinguish causes."""
    url = str(base_url or '').strip().rstrip('/')
    model = str(model or '').strip()
    parsed = urlparse(url)
    if (parsed.scheme not in ('http', 'https') or not parsed.hostname
            or parsed.username is not None or parsed.password is not None
            or parsed.query or parsed.fragment or not _MODEL_PATTERN.fullmatch(model)):
        return OllamaStatus('invalid_config', 'Einstellungen prüfen',
                            'Ollama-Adresse oder Modellname ist ungültig.')
    # Prevent a forged base URL with a path from changing the API target.
    if parsed.path not in ('', '/'):
        return OllamaStatus('invalid_config', 'Einstellungen prüfen',
                            'Die Ollama-Adresse darf keinen zusätzlichen Pfad enthalten.')
    request = get or requests.get
    try:
        response = request(url + '/api/tags', timeout=5)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict) or not isinstance(payload.get('models'), list):
            raise ValueError('Ollama hat keine gültige Modellliste zurückgegeben.')
        names = tuple(str(entry['name']) for entry in payload['models']
                      if isinstance(entry, dict) and isinstance(entry.get('name'), str))
    except (requests.exceptions.ConnectionError, requests.exceptions.Timeout):
        return OllamaStatus('offline', 'Ollama nicht erreichbar',
                            'Ollama installieren beziehungsweise starten, dann erneut prüfen.')
    except (requests.exceptions.RequestException, ValueError, TypeError, KeyError) as exc:
        return OllamaStatus('error', 'Verbindung nicht bereit',
                            f'Ollama-Abfrage fehlgeschlagen: {type(exc).__name__}: {str(exc)[:180]}')
    # Ollama accepts a model name without a tag as shorthand for ':latest'.
    requested = model if ':' in model.rsplit('/', 1)[-1] else model + ':latest'
    if model not in names and requested not in names:
        return OllamaStatus('missing_model', 'KI-Modell fehlt',
            f'Ollama läuft, aber das ausgewählte Modell „{model}“ ist nicht installiert.', names)
    return OllamaStatus('ready', 'KI bereit', f'Ollama verbunden · {model}', names)
