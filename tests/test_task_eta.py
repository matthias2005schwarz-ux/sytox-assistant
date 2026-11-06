"""Conservative remaining-time estimates from real measured progress."""
import json
import unittest

from sytox.task_eta import task_eta
from sytox.voice_features import agent_status_intent


class TaskEtaTests(unittest.TestCase):
    @staticmethod
    def task(*, status='running', steps=5, remaining=4, report_step=5,
             samples=(28, 42, 37), next_step='Tests ausführen'):
        cp = {
            'steps': steps,
            'remaining_steps': remaining,
            'remaining_steps_at': report_step,
            'step_durations': [
                {'step': i + 1, 'seconds': sec}
                for i, sec in enumerate(samples)
            ],
            'progress_notes': [
                {'next_step': next_step, 'completed': 'Programmdatei erstellt',
                 'evidence': 'run_command bestanden'}
            ],
        }
        return {'status': status, 'checkpoint': json.dumps(cp, ensure_ascii=False)}

    def test_estimate_is_rough_range_with_disclaimer(self):
        data = task_eta(self.task())
        self.assertEqual(data['state'], 'estimated')
        self.assertEqual(data['remaining_steps'], 4)
        self.assertGreater(data['high_minutes'], data['low_minutes'])
        self.assertIn('Grob geschätzt', data['text'])
        self.assertIn('unsicher', data['text'])
        self.assertIn('Tests ausführen', data['text'])

    def test_no_invented_duration_before_real_samples(self):
        data = task_eta(self.task(samples=(45,)))
        self.assertEqual(data['state'], 'unknown')
        self.assertNotIn('noch etwa', data['text'])
        self.assertIn('zu wenige', data['text'])

    def test_no_invented_duration_before_remaining_work_is_known(self):
        data = task_eta(self.task(remaining=None))
        self.assertEqual(data['state'], 'unknown')
        self.assertIn('keine seriöse Minutenangabe', data['text'])

    def test_stale_plan_and_nonrunning_task_have_no_eta(self):
        stale = task_eta(self.task(steps=14, report_step=2))
        self.assertEqual(stale['state'], 'unknown')
        finished = task_eta(self.task(status='done'))
        self.assertEqual(finished['state'], 'done')
        self.assertNotIn('noch etwa', finished['text'])

    def test_corrupt_legacy_checkpoint_safe(self):
        self.assertEqual(task_eta({'status': 'running', 'checkpoint': '{broken'})['state'], 'unknown')
        self.assertEqual(task_eta(None)['state'], 'unknown')
        cp = {'steps': 'oops', 'remaining_steps': 999999,
              'remaining_steps_at': 2,
              'step_durations': [0, -1, None, 'oops', float('inf')]}
        self.assertEqual(task_eta({'status': 'running', 'checkpoint': cp})['state'], 'unknown')

    def test_status_and_eta_are_distinct_spoken_intents(self):
        phrases = (
            'Wie lange brauchst du noch?',
            'Wie lange dauert das noch?',
            'Wann bist du fertig?',
            'Wie viel Zeit brauchst du noch?',
            'Wie lange dauert die Programmierung noch?',
            'Wie lange noch?',
        )
        for phrase in phrases:
            with self.subTest(phrase=phrase):
                self.assertEqual(agent_status_intent(phrase), 'eta')
        self.assertEqual(agent_status_intent('Wie weit bist du?'), 'status')
        self.assertIsNone(agent_status_intent('Erkläre mir Python'))


if __name__ == '__main__':
    unittest.main()
