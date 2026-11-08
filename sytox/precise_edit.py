"""Prepare one exact source edit without touching the filesystem.

Matching uses the newline-normalized view produced by ordinary text readers.
Untouched bytes, including mixed line endings and a UTF-8 BOM, are retained.
"""
from __future__ import annotations

from array import array
from difflib import SequenceMatcher
import hashlib
import re


MAX_FILE_BYTES = 1024 * 1024
_MAX_LINE_MATCH_PRODUCT = 4_000_000
_BOM = b'\xef\xbb\xbf'
_NEWLINE = re.compile(rb'\r\n|\r|\n')


class EditError(ValueError):
    """An exact edit cannot safely be applied to the supplied source bytes."""


def _normalize(text):
    return text.replace('\r\n', '\n').replace('\r', '\n')


def _source_view(raw):
    """Map normalized Python character boundaries to original UTF-8 bytes."""
    try:
        text = raw.decode('utf-8')
    except UnicodeDecodeError as exc:
        raise EditError('Die Datei ist kein gültiger UTF-8-Text.') from exc
    characters, offsets = [], array('I', [0])
    position, byte_offset = 0, 0
    while position < len(text):
        character = text[position]
        if character == '\r':
            width = 2 if text[position:position + 2] == '\r\n' else 1
            characters.append('\n')
            byte_offset += width
            position += width
        else:
            characters.append(character)
            byte_offset += len(character.encode('utf-8'))
            position += 1
        offsets.append(byte_offset)
    return ''.join(characters), offsets


def _newline(raw, fallback=b'\n'):
    """Prefer the replaced region's predominant newline; ties keep the first."""
    endings = _NEWLINE.findall(raw)
    if not endings:
        return fallback
    counts = {}
    for ending in endings:
        counts[ending] = counts.get(ending, 0) + 1
    return max(counts, key=counts.get)


def _offsets(lines):
    offsets = array('I', [0])
    for line in lines:
        offsets.append(offsets[-1] + len(line))
    return offsets


def _join_segments(parts):
    """Do not merge two logical newlines into a new CRLF across an edit edge."""
    output = []
    previous = b''
    for part in parts:
        if not part:
            continue
        if previous.endswith(b'\r') and part.startswith(b'\n'):
            output.append(b'\r')
        output.append(part)
        previous = part
    return b''.join(output)


def _replacement(body, boundaries, start, old, new, newline):
    """Copy unchanged lines and shared character edges directly from the source."""
    def original(left, right):
        return body[boundaries[start + left]:boundaries[start + right]]

    # Most long excerpts differ in only a small span. Trim their equal edges
    # linearly before attempting line alignment of the actual changed span.
    prefix = 0
    while prefix < min(len(old), len(new)) and old[prefix] == new[prefix]:
        prefix += 1
    suffix = 0
    while suffix < min(len(old), len(new)) - prefix and old[-suffix - 1] == new[-suffix - 1]:
        suffix += 1
    prefix_bytes = original(0, prefix)
    suffix_bytes = original(len(old) - suffix, len(old)) if suffix else b''
    old = old[prefix:len(old) - suffix if suffix else len(old)]
    new = new[prefix:len(new) - suffix if suffix else len(new)]
    start += prefix
    old_lines, new_lines = old.splitlines(keepends=True), new.splitlines(keepends=True)
    if len(old_lines) * len(new_lines) > _MAX_LINE_MATCH_PRODUCT:
        raise EditError('Der geänderte Ausschnitt enthält zu viele Zeilen. Mehrere kleinere, eindeutige Änderungen verwenden.')
    old_offsets = _offsets(old_lines)
    output = [prefix_bytes]

    # Line-based matching avoids quadratic character matching on repetitive
    # large files. Shared edges also retain the exact EOL of a changed line.
    matcher = SequenceMatcher(a=old_lines, b=new_lines, autojunk=True)
    for kind, first, last, new_first, new_last in matcher.get_opcodes():
        left, right = old_offsets[first], old_offsets[last]
        if kind == 'equal':
            output.append(original(left, right))
            continue
        previous = ''.join(old_lines[first:last])
        replacement = ''.join(new_lines[new_first:new_last])
        prefix = 0
        while prefix < min(len(previous), len(replacement)) and previous[prefix] == replacement[prefix]:
            prefix += 1
        suffix = 0
        while (suffix < min(len(previous), len(replacement)) - prefix
               and previous[-suffix - 1] == replacement[-suffix - 1]):
            suffix += 1
        output.append(original(left, left + prefix))
        changed = replacement[prefix:len(replacement) - suffix if suffix else len(replacement)]
        local_newline = _newline(original(left, right), newline).decode('ascii')
        output.append(changed.replace('\n', local_newline).encode('utf-8'))
        if suffix:
            output.append(original(right - suffix, right))
    output.append(suffix_bytes)
    return _join_segments(output)


def prepare_edit(source: bytes, old_text: str, new_text: str,
                 expected_sha256: str | None = None) -> dict:
    """Replace exactly one occurrence and return new bytes plus raw hashes.

    No fuzzy, regex or indentation matching is performed. CRLF, LF and CR are
    equivalent only for matching; unchanged source bytes are copied verbatim.
    A repeated match, including overlapping matches, must be disambiguated by
    supplying more surrounding source text. This function performs no IO.
    """
    if not isinstance(source, bytes):
        raise EditError('Der Ausgangsinhalt muss als Bytes vorliegen.')
    if len(source) > MAX_FILE_BYTES:
        raise EditError('Die Datei ist größer als das Limit von 1 MiB.')
    if b'\0' in source:
        raise EditError('Binärdateien mit Nullbytes werden nicht bearbeitet.')
    if not isinstance(old_text, str) or not isinstance(new_text, str):
        raise EditError('Alter und neuer Ausschnitt müssen Text sein.')
    if not old_text:
        raise EditError('Der alte Ausschnitt darf nicht leer sein.')
    if '\0' in old_text or '\0' in new_text:
        raise EditError('Nullbytes sind in Quelltextausschnitten nicht erlaubt.')
    try:
        if len(old_text.encode('utf-8')) > MAX_FILE_BYTES or len(new_text.encode('utf-8')) > MAX_FILE_BYTES:
            raise EditError('Ein Ausschnitt ist größer als das Limit von 1 MiB.')
    except UnicodeEncodeError as exc:
        raise EditError('Die Ausschnitte müssen gültigen Unicode-Text enthalten.') from exc

    before = hashlib.sha256(source).hexdigest()
    if expected_sha256 is not None:
        if not isinstance(expected_sha256, str) or not re.fullmatch(r'[0-9a-fA-F]{64}', expected_sha256):
            raise EditError('expected_sha256 muss eine vollständige SHA-256-Prüfsumme sein.')
        if expected_sha256.casefold() != before:
            raise EditError('Die Datei wurde seit dem gelesenen Stand geändert (SHA-256 stimmt nicht überein).')

    bom = _BOM if source.startswith(_BOM) else b''
    body = source[len(bom):]
    view, boundaries = _source_view(body)
    includes_bom = bool(bom and old_text.startswith('\ufeff'))
    old = _normalize(old_text[1:] if includes_bom else old_text)
    if not old:
        raise EditError('Der alte Ausschnitt muss mehr als die UTF-8-Kennung enthalten.')
    if includes_bom:
        start = 0 if view.startswith(old) else -1
    else:
        start = view.find(old)
    if start < 0:
        raise EditError('Der alte Ausschnitt wurde nicht gefunden. Datei erneut lesen und exakten Text verwenden.')
    if not includes_bom and view.find(old, start + 1) >= 0:
        raise EditError('Der alte Ausschnitt ist nicht eindeutig. Mehr umgebende Zeilen angeben.')
    end = start + len(old)
    new = _normalize(new_text)
    if bom and start == 0 and new.startswith('\ufeff'):
        new = new[1:]

    result = source
    if new != old:
        left, right = boundaries[start], boundaries[end]
        region = body[left:right]
        following = _NEWLINE.search(body[right:])
        preceding = _NEWLINE.findall(body[:left])
        fallback = (following.group() if following else preceding[-1] if preceding else b'\n')
        inserted = _replacement(body, boundaries, start, old, new, _newline(region, fallback))
        result = _join_segments((bom, body[:left], inserted, body[right:]))
        if len(result) > MAX_FILE_BYTES:
            raise EditError('Die geänderte Datei würde das Limit von 1 MiB überschreiten.')

    return {'content': result, 'before_sha256': before,
            'after_sha256': hashlib.sha256(result).hexdigest(),
            'changed': result != source, 'start_line': view.count('\n', 0, start) + 1,
            'end_line': view.count('\n', 0, end - 1) + 1,
            'before_bytes': len(source), 'after_bytes': len(result)}
