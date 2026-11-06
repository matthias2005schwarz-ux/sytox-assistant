"""Run component tests in a process without any native Qt widgets.

On Windows, the actual Qt GUI suites each run in their own process so that
QApplication lifetimes do not collide with unrelated unittest fixtures.
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def component_suite():
    full_suite = unittest.defaultTestLoader.discover(str(ROOT / 'tests'))
    cases = []

    def collect(node):
        for child in node:
            if isinstance(child, unittest.TestSuite):
                collect(child)
            elif not child.id().startswith(('test_ollama_ui.', 'test_model_benchmark_ui.', 'test_voice_listener_v2.', 'test_chat_modes_ui.')):
                cases.append(child)

    collect(full_suite)
    if len(cases) < 100:
        raise RuntimeError(f'Expected at least 100 component tests, found {len(cases)}')
    return unittest.TestSuite(cases)


if __name__ == '__main__':
    result = unittest.TextTestRunner(verbosity=2).run(component_suite())
    sys.exit(0 if result.wasSuccessful() else 1)
