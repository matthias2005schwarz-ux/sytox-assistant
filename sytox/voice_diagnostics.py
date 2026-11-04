"""On-device, opt-in microphone diagnostics; no audio saved or uploaded.

The test uses the same 16 kHz mono PCM input format as WakeListener.
Recognition and spoken interruption are verified by the actual WakeListener and
Speaker from the UI, not by simulated prerecorded audio.
"""
from __future__ import annotations

from array import array
import math
import sys
import threading
import time


def pcm_rms_percent(pcm: bytes) -> float:
    """Return measured RMS relative to 16-bit full scale, 0 through 100%."""
    if len(pcm) % 2:
        raise ValueError('16-Bit-Mikrofondaten unvollständig.')
    values = array('h')
    values.frombytes(pcm)
    if sys.byteorder != 'little':
        values.byteswap()
    if not values:
        return 0.0
    rms = math.sqrt(sum(value * value for value in values) / len(values))
    return min(100.0, 100.0 * rms / 32768.0)


def microphone_probe(progress, cancel_event=None, seconds=5, sound_module=None, clock=None):
    """Sample the system-default microphone without writing any recordings.

    Test success requires actual PCM samples and speech-like amplitude. The
    default device and 16 kHz stream are deliberately shared with WakeListener,
    so incompatible Windows sound hardware is reported rather than hidden.
    """
    if sound_module is None:
        import sounddevice as sd
    else:
        sd = sound_module
    clock = clock or time.monotonic
    cancel_event = cancel_event if cancel_event is not None else threading.Event()
    if seconds <= 0 or seconds > 30:
        raise ValueError('Ungültige Testdauer.')
    if cancel_event.is_set():
        raise InterruptedError('Mikrofontest abgebrochen.')
    device = sd.query_devices(kind='input')
    name = str(device.get('name', 'Unbekanntes Mikrofon'))
    if int(device.get('max_input_channels', 0)) < 1:
        raise RuntimeError('Kein Mikrofon verfügbar. Bitte ein Eingabegerät anschließen.')
    received = 0
    peak = 0.0
    lock = threading.Lock()

    def on_audio(indata, frames, timing, status):
        nonlocal received, peak
        audio = bytes(indata)
        level = pcm_rms_percent(audio)
        with lock:
            received += len(audio)
            peak = max(peak, level)
        # No audio is retained. Only this number crosses thread boundaries.
        progress(level)

    start = clock()
    with sd.RawInputStream(samplerate=16000, channels=1, dtype='int16',
                           blocksize=2048, callback=on_audio):
        while clock() - start < seconds:
            if cancel_event.wait(0.05):
                raise InterruptedError('Mikrofontest abgebrochen.')
    if received == 0:
        raise RuntimeError('Mikrofon geöffnet, aber keine Audiodaten empfangen.')
    # 0.7% RMS is a conservative indication of human speech, not proof of it.
    return {'device': name, 'peak_percent': round(peak, 2),
            'signal_detected': peak >= 0.7, 'bytes_read': received}
