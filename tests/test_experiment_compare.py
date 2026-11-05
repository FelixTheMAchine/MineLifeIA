"""A/B/C harness uses production planning over isolated synthetic databases."""
import unittest

from scripts.experiment_compare import run_experiment


class ExperimentCompareTest(unittest.TestCase):
    def test_reproducible_decisions_and_honest_memory_ablation(self):
        report = run_experiment((7, 19))
        self.assertEqual(report, run_experiment((7, 19)))
        self.assertTrue(report['synthetic'])
        self.assertFalse(report['gameplay_verified'])
        self.assertFalse(report['model_inference'])
        for run in report['runs']:
            arms = {arm['arm']: arm for arm in run['arms']}
            self.assertEqual(len({arm['initial_event_count'] for arm in arms.values()}), 1)
            self.assertIsNone(arms['A']['suggestion_accepted'])
            self.assertTrue(arms['B']['suggestion_accepted'])
            self.assertTrue(arms['C']['suggestion_accepted'])
            self.assertEqual(arms['B']['recalled_memories'], 0)
            self.assertGreater(arms['C']['recalled_memories'], 0)
            self.assertEqual(arms['B']['source_events'], arms['C']['source_events'])
            self.assertEqual(arms['B']['selected_action'], arms['C']['selected_action'])
            for arm in arms.values():
                self.assertFalse(arm['factual_mutations_from_suggestion'])
                self.assertEqual(arm['confirmed_action_outcomes'], 0)
        # Both unchanged and genuinely influenced choices occur in these fixtures.
        first, second = report['runs']
        self.assertEqual([arm['selected_action'] for arm in first['arms']], ['explore']*3)
        self.assertFalse(any(arm['influenced'] for arm in first['arms']))
        self.assertEqual([arm['selected_action'] for arm in second['arms']], ['approach', 'explore', 'explore'])
        self.assertEqual([arm['influenced'] for arm in second['arms']], [False, True, True])

    def test_invalid_seeds_are_rejected_before_any_experiment(self):
        for seeds in ((), (True,), (-1,), (2**32,), range(33)):
            with self.subTest(seeds=seeds), self.assertRaises(ValueError):
                run_experiment(seeds)


if __name__ == '__main__':
    unittest.main()
