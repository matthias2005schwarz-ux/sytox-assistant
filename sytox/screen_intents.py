"""Explicit screen-assistance command recognition."""

import re


def screen_intent(text):
    line = ' '.join(str(text or '').casefold().split())
    if not re.search(r'bildschirm|screen', line):
        return None
    if re.search(r'verlass|rausgeh|ausschalt|deaktivier|stop|beend', line):
        return 'stop'
    if re.search(r'schau|guck|sieh|anseh|analysier|zeig|aktivier|start', line):
        return 'start'
    return None
