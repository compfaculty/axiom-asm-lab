"""Regressions for confirmation output, deadlines, resume and dispatch."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from test_search_rank import make_report
from evaluate import PROTOCOL_SIZES, write_bench_report
from proposals import mock_propose
from search import SearchController, SearchBudgets, native_evaluate_attempt

ROOT = Path(__file__).resolve().parents[1]


class SearchReviewTests(unittest.TestCase):
    def test_confirmation_uses_distinct_sample_files_and_remaining_budget(self):
        calls = []
        def spawn(root, proposal_path, output, remaining, args):
            calls.append((output, remaining, args))
            report = make_report(str(len(calls)), 200, 100,
                                 sizes=list(PROTOCOL_SIZES), candidate='mock_scalar_copy')
            # Exercise the real persistence function: samples.jsonl cannot be overwritten.
            write_bench_report(run_id=report['run_id'], run_dir=output.parent,
                command='test', entries=report['variants'], raw_samples=[],
                measure_sizes=list(PROTOCOL_SIZES), skipped_sizes=[], samples=30,
                seed=1, target_sample_ns=20000000, memory_cap_bytes=123456789,
                output=output)
            return {'returncode': 0, 'stdout': '', 'stderr': ''}
        with tempfile.TemporaryDirectory() as tmp, \
                patch('search._spawn_evaluate', side_effect=spawn), \
                patch('lab.clang_identity', return_value='clang'), \
                patch('search.time.monotonic', side_effect=[100, 125]):
            result = native_evaluate_attempt(ROOT, Path(tmp), mock_propose(ROOT), 0,
                state={'budgets': {'max_seconds': 100}, 'active_eval_seconds': 10},
                memory_cap_bytes=123456789)
            self.assertEqual(result.stage, 'accepted', result.detail)
            self.assertNotEqual(calls[0][0].parent, calls[1][0].parent)
            self.assertEqual(calls[1][1], 65)
            self.assertIn('123456789', calls[1][2])

    def test_evaluator_internal_typeerror_not_retried(self):
        calls = []
        def broken(*args):
            calls.append(args)
            raise TypeError('internal fault')
        with tempfile.TemporaryDirectory() as tmp:
            ctrl = SearchController(ROOT, Path(tmp), SearchBudgets(), evaluate_fn=broken)
            with self.assertRaisesRegex(TypeError, 'internal fault'):
                ctrl._call_evaluate({}, 0, {})
            self.assertEqual(len(calls), 1)

    def test_resume_rejects_changed_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'root';root.mkdir()
            code = root / 'evaluate.py';code.write_text('original')
            ctrl = SearchController(root, Path(tmp) / 'state', SearchBudgets())
            ctrl.load_or_init(False)
            code.write_text('modified')
            with self.assertRaisesRegex(RuntimeError, 'artifact identity'):
                ctrl.load_or_init(True)

    def test_resume_rejects_changed_seed(self):
        with tempfile.TemporaryDirectory() as tmp:
            ctrl = SearchController(ROOT, Path(tmp) / 'state', SearchBudgets(), seed=1)
            ctrl.load_or_init(False)
            changed = SearchController(ROOT, Path(tmp) / 'state', SearchBudgets(), seed=2)
            with self.assertRaisesRegex(RuntimeError, 'seed'):
                changed.load_or_init(True)

    def test_malformed_proposal_recorded(self):
        class BadProvider:
            def propose(self, index, root): return []
        with tempfile.TemporaryDirectory() as tmp:
            ctrl = SearchController(ROOT, Path(tmp) / 'state',
                                    SearchBudgets(max_proposals=1), provider=BadProvider())
            state = ctrl.run()
            self.assertEqual(state['attempts'][0]['stage'], 'failed')
