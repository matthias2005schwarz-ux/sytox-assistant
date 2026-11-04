"""Conservative German conversation intents for controlling a long-running task.

Only clear user requests alter a task. Ordinary discussion about pausing,
negated requests, and quoted examples must not stop an active programmer.
This router never invokes any tools itself.
"""
from __future__ import annotations

import re


def work_intent(utterance: str) -> str | None:
    """Return 'pause', 'resume', 'silence', or None for an explicit instruction.

    Pause is reversible: the Agent persists its checkpoint when stopped.
    Uncertain statements stay in the ordinary side conversation.
    """
    text = re.sub(r'\s+', ' ', str(utterance or '').lower()).strip()
    text = text.strip(' \t\r\n.!?,;:')
    if not text or len(text) > 240:
        return None
    # Quotes and questions about examples are content, not commands.
    if any(marker in text for marker in ('"', '„', '“', '«', '»', '`')):
        return None
    if re.search(r'\b(?:warum|was bedeutet|was heißt|wenn ich sage|zum beispiel|sag mal was|'
                 r'was wäre wenn|was passiert wenn)\b', text):
        return None

    # Do not turn negative instructions into positive commands.
    if re.search(r'\b(?:nicht|niemals|nie|kein|keine)\s+'
                 r'(?:aufhören|pausieren|stoppen|anhalten|unterbrechen|aufgeben)\b', text):
        return None
    if re.search(r'\b(?:hör|hoer|höre|halte|mach|mache|pausier|pausiere|'
                 r'unterbrich|stoppe|stopp)\b.{0,55}\b(?:nicht|niemals|nie)\b', text):
        return None

    # Optional polite lead-in; remaining wording must be a direct instruction.
    text = re.sub(
        r'^(?:hey sytox[, ]*|sytox[, ]*)?', '', text
    ).strip()
    text = re.sub(
        r'^(?:(?:kannst|könntest|würdest) du(?: vielleicht)?|'
        r'können wir|bitte)\s+', '', text
    )
    text = re.sub(r'^(?:bitte|doch|einfach|mal|jetzt|gerade)\s+', '', text)
    text = re.sub(r'\s+(?:bitte|danke)$', '', text).strip()
    # Strip other harmless courtesy tokens without altering the action.
    text = re.sub(r'\b(?:bitte|mal|doch|einfach)\b', '', text)
    text = re.sub(r'\s+', ' ', text).strip()
    text = re.sub(r'^(?:also|okay|ok|naja|ach|so)\s+', '', text).strip()

    domain = r'(?:programmier(?:en|ung)?|coden|code schreiben|arbeiten|deine arbeit|'
    domain += r'(?:dem|den|die|das|der|meinem|meinen|meiner) (?:auftrag|projekt|programmieren|arbeit))'

    if re.fullmatch(r'(?:sei still|ruhe|hör auf zu reden|hör mit dem reden auf|'
                    r'rede (?:jetzt )?nicht mehr|hör auf zu sprechen|'
                    r'hör auf zu quatschen)', text):
        return 'silence'

    # Express instructions to stop only the current task, not the app.
    pause_patterns = (
        rf'(?:hör|höre|hoer)\s+(?:(?:kurz|erstmal|vorerst)\s+)?'
        rf'(?:auf\s+(?:zu\s+{domain}|mit\s+{domain})|'
        rf'mit\s+{domain}\s+auf)',
        rf'(?:stoppe|stopp|pausier|pausiere|unterbrich|halte)'
        rf'(?:\s+(?:jetzt|kurz|erstmal|vorerst))?'
        rf'(?:\s+(?:den auftrag|die arbeit|das projekt|die programmierung|'
        rf'das programmieren|mit dem programmieren|mich|es))?',
        rf'(?:mach|mache)(?:\s+(?:jetzt|kurz|erstmal|vorerst))?'
        rf'\s+(?:eine|ne|n)?\s*pause(?:\s+(?:mit\s+{domain}))?',
        rf'(?:warte|wart)(?:\s+(?:jetzt|kurz|erstmal|vorerst))?'
        rf'\s+mit\s+{domain}',
        r'(?:(?:jetzt|kurz|erstmal)\s+)?'
        r'aufhören\s+zu\s+(?:programmieren|arbeiten|coden)',
        r'(?:programmier|programmiere|arbeite)\s+(?:jetzt\s+)?nicht\s+weiter',
        r'lass\s+(?:das\s+)?(?:programmieren|arbeiten|projekt)\s+'
        r'(?:erstmal|vorerst|für heute)\s+sein',
    )

    resume_patterns = (
        r'(?:mach|mache|arbeite)(?:\s+(?:jetzt|gerne|ruhig))?'
        r'\s+(?:wieder\s+)?weiter',
        r'(?:programmier|programmiere|code|codiere|arbeite)'
        r'(?:\s+(?:jetzt|gerne|ruhig|wieder))?\s+weiter',
        r'(?:setz|setze)(?:\s+(?:jetzt|wieder))?'
        r'\s+(?:(?:den auftrag|die arbeit|das projekt|die programmierung|'
        r'das programmieren)\s+)?fort',
        r'(?:fang|fange)(?:\s+(?:jetzt|wieder))?\s+an'
        r'(?:\s+(?:zu programmieren|mit der arbeit|mit dem projekt))?',
        r'(?:du kannst|du darfst)(?:\s+(?:jetzt|wieder))?'
        r'\s+(?:weitermachen|weiterarbeiten|weiterprogrammieren)',
        r'(?:weiter\s+(?:mit\s+)?(?:dem|den|der|die|das)\s+'
        r'(?:programmieren|auftrag|arbeit|projekt|programmierung))',
        r'(?:(?:jetzt|wieder)\s+)?(?:weitermachen|weiterarbeiten|weiterprogrammieren)',
        r'(?:kannst du)\s+(?:jetzt\s+)?(?:wieder\s+)?'
        r'(?:weiterprogrammieren|weitermachen|weiterarbeiten)',
    )

    if any(re.fullmatch(pattern, text) for pattern in pause_patterns):
        return 'pause'
    if any(re.fullmatch(pattern, text) for pattern in resume_patterns):
        return 'resume'
    return None
