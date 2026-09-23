import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from search import (
    OfflineMockProvider,
    SearchBudgets,
    SearchController,
    get_provider,
    refuse_stale_promotion,
)

ROOT = Path(__file__).resolve().parents[1]


class SearchTests(unittest.TestCase):
    def test_offline_provider_no_api_key(self):
        os.environ.pop('AXIOM_PROVIDER', None)
        os.environ.pop('OPENAI_API_KEY', None)
        p = get_provider('offline')
        self.assertIsInstance(p, OfflineMockProvider)
        with self.assertRaises(RuntimeError):
            get_provider('online')

    def test_stops_max_proposals(self):
        with tempfile.TemporaryDirectory() as tmp:
            ctrl = SearchController(
                ROOT, Path(tmp) / 's1',
                SearchBudgets(max_proposals=2, max_seconds=60, max_stagnation=100))
            state = ctrl.run(resume=False)
            self.assertEqual(state['stop_reason'], 'max_proposals')
            self.assertEqual(len(state['attempts']), 2)
            self.assertTrue((Path(tmp) / 's1' / 'search_state.json').is_file())

    def test_stops_max_seconds(self):
        with tempfile.TemporaryDirectory() as tmp:
            ctrl = SearchController(
                ROOT, Path(tmp) / 's2',
                SearchBudgets(max_proposals=50, max_seconds=0.0, max_stagnation=100))
            state = ctrl.run(resume=False)
            self.assertEqual(state['stop_reason'], 'max_seconds')
            self.assertEqual(len(state['attempts']), 0)

    def test_stops_max_stagnation(self):
        with tempfile.TemporaryDirectory() as tmp:
            ctrl = SearchController(
                ROOT, Path(tmp) / 's3',
                SearchBudgets(max_proposals=20, max_seconds=60, max_stagnation=2))
            state = ctrl.run(resume=False)
            self.assertEqual(state['stop_reason'], 'max_stagnation')
            self.assertGreaterEqual(len(state['attempts']), 2)

    def test_resume_recovers_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp) / 's4'
            ctrl = SearchController(
                ROOT, d,
                SearchBudgets(max_proposals=2, max_seconds=60, max_stagnation=100))
            state1 = ctrl.run(resume=False)
            self.assertEqual(state1['stop_reason'], 'max_proposals')
            ctrl2 = SearchController(
                ROOT, d,
                SearchBudgets(max_proposals=4, max_seconds=60, max_stagnation=100))
            state2 = ctrl2.run(resume=True)
            self.assertEqual(state2['stop_reason'], 'max_proposals')
            self.assertEqual(len(state2['attempts']), 4)

    def test_refuse_stale_promotion(self):
        called = []
        with self.assertRaises(RuntimeError):
            refuse_stale_promotion(
                {'lifecycle': 'stale', 'verification': {'state': 'pass'}},
                lambda: called.append(1))
        self.assertEqual(called, [])
        refuse_stale_promotion(
            {'lifecycle': 'verified', 'verification': {'state': 'pass'}},
            lambda: called.append(1))
        self.assertEqual(called, [1])


if __name__ == '__main__':
    unittest.main()
