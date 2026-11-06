"""Conservative, evidence-based time estimates for running SYTOX tasks.

Only observed step durations and an explicit remaining-step estimate can
produce a rough range. Without both, say so instead of inventing a deadline.
"""
from __future__ import annotations

import json
import math
import statistics


def _checkpoint(task: dict) -> dict:
    value = task.get('checkpoint') or {}
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, dict) else {}
    except (ValueError, TypeError):
        return {}


def _valid_steps(value) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        count = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return count if 1 <= count <= 100 else None


def _observed_durations(checkpoint: dict) -> list[float]:
    samples = checkpoint.get('step_durations', [])
    if not isinstance(samples, list):
        return []
    result = []
    for entry in samples[-12:]:
        value = entry.get('seconds') if isinstance(entry, dict) else entry
        try:
            seconds = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(seconds) and 0.2 <= seconds <= 3600:
            result.append(seconds)
    return result


def task_eta(task: dict | None) -> dict:
    """Return a displayable ETA with honest uncertainty and recorded evidence."""
    if not task:
        return {'state': 'unknown', 'text':
            'Der Auftrag wird gestartet. Für eine Restzeitschätzung liegen noch keine Daten vor.'}
    status = str(task.get('status') or 'unknown')
    cp = _checkpoint(task)
    try:
        steps = max(0, int(cp.get('steps', 0)))
    except (ValueError, TypeError, OverflowError):
        steps = 0
    notes = cp.get('progress_notes') if isinstance(cp.get('progress_notes'), list) else []
    latest = next((n for n in reversed(notes) if isinstance(n, dict)
                   and str(n.get('next_step') or '').strip()), {})
    next_step = str(latest.get('next_step') or '').strip()[:160]
    suffix = (' Nächster Schritt: ' + next_step) if next_step else ''
    if status != 'running':
        return {'state': status, 'text':
            ('Der Auftrag ist ' + status + '; deshalb gibt es derzeit keine laufende Restzeit.')
            + suffix}
    remaining = _valid_steps(cp.get('remaining_steps'))
    reported_at = cp.get('remaining_steps_at')
    try:
        fresh = reported_at is not None and 0 <= steps - int(reported_at) <= 6
    except (TypeError, ValueError, OverflowError):
        fresh = False
    samples = _observed_durations(cp)
    if remaining is None or not fresh or len(samples) < 2:
        parts = [f'Der Auftrag läuft; {steps} Arbeitsschritte sind protokolliert.']
        if remaining is None or not fresh:
            parts.append('Die offenen Schritte sind noch nicht verlässlich eingegrenzt.')
        else:
            parts.append('Es gibt noch zu wenige gemessene Arbeitsschritte für eine Restzeit.')
        parts.append('Ich kann noch keine seriöse Minutenangabe machen.')
        return {'state': 'unknown', 'steps': steps, 'text': ' '.join(parts) + suffix}

    # Median resists occasional very slow tool calls, but the uncertainty band
    # also includes observed min/max to avoid false precision.
    typical = statistics.median(samples)
    lower_rate = max(5.0, min(samples[-8:]))
    upper_rate = max(typical, max(samples[-8:]))
    low_seconds = remaining * min(typical, lower_rate * 1.3) * 0.75
    high_seconds = remaining * max(typical * 2.0, upper_rate * 1.6)
    low_minutes = max(1, int(math.floor(low_seconds / 60)))
    high_minutes = max(low_minutes + 1, int(math.ceil(high_seconds / 60)))
    if high_minutes > 24 * 60:
        return {'state': 'unknown', 'steps': steps, 'text':
            'Die Arbeitsschritte dauern derzeit sehr unterschiedlich lange. '
            'Eine Restzeit ist deshalb noch nicht sinnvoll eingrenzbar.' + suffix}
    note = (' Die Schätzung ist unsicher; neue Fehler oder Tests können sie verändern.')
    return {
        'state': 'estimated', 'low_minutes': low_minutes,
        'high_minutes': high_minutes, 'remaining_steps': remaining,
        'observed_steps': len(samples), 'steps': steps,
        'text': (f'Grob geschätzt noch etwa {low_minutes} bis {high_minutes} Minuten, '
                 f'basierend auf {len(samples)} gemessenen Schritten und '
                 f'{remaining} noch eingeplanten Schritten.' + note + suffix),
    }
