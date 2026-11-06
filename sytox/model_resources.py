"""Adaptive arbitration of simultaneous local Ollama inference requests.

Keep speech recognition, GUI and the programming worker independent. Permit
two simultaneous requests only while enough physical RAM is available.
When memory is tight, serialize inference without cancelling either task;
interactive speech/questions receive the next available slot first.
"""
from __future__ import annotations

import ctypes
import os
import threading
from contextlib import contextmanager

TWO_MODEL_HEADROOM_BYTES = 8 * 1024 ** 3


def available_ram_bytes():
    """Free *physical* memory, without optional third-party dependencies."""
    if os.name == 'nt':
        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [
                ('dwLength', ctypes.c_ulong), ('dwMemoryLoad', ctypes.c_ulong),
                ('ullTotalPhys', ctypes.c_ulonglong),
                ('ullAvailPhys', ctypes.c_ulonglong),
                ('ullTotalPageFile', ctypes.c_ulonglong),
                ('ullAvailPageFile', ctypes.c_ulonglong),
                ('ullTotalVirtual', ctypes.c_ulonglong),
                ('ullAvailVirtual', ctypes.c_ulonglong),
                ('ullAvailExtendedVirtual', ctypes.c_ulonglong),
            ]
        state = MEMORYSTATUSEX()
        state.dwLength = ctypes.sizeof(state)
        try:
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(state)):
                return int(state.ullAvailPhys)
        except (AttributeError, OSError, ValueError):
            return None
        return None
    try:
        with open('/proc/meminfo', encoding='ascii') as source:
            for line in source:
                if line.startswith('MemAvailable:'):
                    return int(line.split()[1]) * 1024
    except (OSError, IndexError, ValueError):
        pass
    return None


class ModelResourceGate:
    def __init__(self):
        self.condition = threading.Condition(threading.RLock())
        self.active = 0
        self.waiting_interactive = 0

    def _slots(self):
        free = available_ram_bytes()
        return 2 if free is not None and free >= TWO_MODEL_HEADROOM_BYTES else 1

    @contextmanager
    def inference(self, priority='background', stop_event=None):
        """Reserve a request slot, regardless of which Ollama model is in use."""
        interactive = priority == 'interactive'
        with self.condition:
            if interactive:
                self.waiting_interactive += 1
            try:
                while (self.active >= self._slots()
                       or (not interactive and self.waiting_interactive)):
                    if stop_event is not None and stop_event.is_set():
                        raise InterruptedError('Lokale Modellausführung abgebrochen.')
                    self.condition.wait(timeout=0.15)
                if stop_event is not None and stop_event.is_set():
                    raise InterruptedError('Lokale Modellausführung abgebrochen.')
                self.active += 1
            finally:
                if interactive:
                    self.waiting_interactive -= 1
        try:
            yield
        finally:
            with self.condition:
                self.active -= 1
                self.condition.notify_all()


model_gate = ModelResourceGate()
