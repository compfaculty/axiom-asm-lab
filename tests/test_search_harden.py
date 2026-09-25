"""T009H: recovery, evidence revalidation, locks, incumbent, catalog retry."""
from __future__ import annotations

import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from search import (
    AttemptRecord,
    OfflineMockProvider,
    SearchBudgets,
    SearchController,
    SearchDirLock,
    beats_incumbent,
    revalidate_persisted_rankings,
    validate_measurement_evidence,
)
from test_search_rank import make_report

ROOT = Path(__file__).resolve().parents[1]


class IncumbentPolicyTests(unittest.TestCase):
    def test_beats_incumbent_requires_strictly_higher_score(self):
        self.assertTrue(beats_incumbent(None, {'score': 1.1}))
        self.assertTrue(beats_incumbent({'score': 1.1}, {'score': 1.2}))
        self.assertFalse(beats_incumbent({'score': 1.2}, {'score': 1.2}))
        self.assertFalse(beats_incumbent({'score': 1.2}, {'score': 1.1}))

    def test_challenger_beating_clang_only_does_not_replace_incumbent(self):
        def eval_fn(root, search_dir, proposal, index, state=None):
            if index == 0:
                return AttemptRecord(
                    'id0', proposal['candidate_id'], 'a' * 64, 'accepted',
                    detail={
                        'score': 1.4,
                        'accepted': {'candidate_id': 'incumbent', 'score': 1.4},
                        'session': {'decision': 'win', 'score': 1.4},
                    },
                )
            return AttemptRecord(
                'id1', proposal['candidate_id'], 'b' * 64, 'accepted',
                detail={
                    'score': 1.25,
                    'accepted': {'candidate_id': 'challenger', 'score': 1.25},
                    'session': {'decision': 'win', 'score': 1.25},
                },
            )

        with tempfile.TemporaryDirectory() as tmp:
            ctrl = SearchController(
                ROOT, Path(tmp) / 'inc',
                SearchBudgets(max_proposals=2, max_seconds=60, max_stagnation=100),
                provider=OfflineMockProvider(), evaluate_fn=eval_fn,
                samples=30, provider_mode='mock')
            state = ctrl.run(resume=False)
            self.assertEqual(state['accepted']['candidate_id'], 'incumbent')
            self.assertEqual(state['attempts'][1]['stage'], 'rejected')
            self.assertIn('incumbent_policy', state['attempts'][1]['detail']['rejection_reason'])


class SearchLockTests(unittest.TestCase):
    def test_concurrent_controller_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp) / 'locked'
            d.mkdir()
            hold = threading.Event()
            acquired = threading.Event()
            errors = []

            def holder():
                with SearchDirLock(d):
                    acquired.set()
                    hold.wait(timeout=5)

            t = threading.Thread(target=holder)
            t.start()
            self.assertTrue(acquired.wait(timeout=2))
            with self.assertRaisesRegex(RuntimeError, 'locked by another controller'):
                with SearchDirLock(d):
                    pass
            hold.set()
            t.join(timeout=2)


class EvidenceRevalidationTests(unittest.TestCase):
    def test_corrupted_measurement_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            report_path = Path(tmp) / 'measurement.json'
            report_path.write_text('{not-json')
            with self.assertRaises((ValueError, json.JSONDecodeError)):
                validate_measurement_evidence(report_path)

    def test_missing_samples_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = make_report('r1', 200, 100)
            report.pop('samples_jsonl', None)
            path = Path(tmp) / 'measurement.json'
            path.write_text(json.dumps(report))
            with self.assertRaisesRegex(ValueError, 'samples'):
                validate_measurement_evidence(path)

    def test_resume_rejects_corrupted_best_observed(self):
        def eval_fn(root, search_dir, proposal, index, state=None):
            return AttemptRecord(
                f'i{index}', proposal['candidate_id'], (str(index) + 'c' * 63)[:64],
                'ranked',
                detail={'score': 0.8, 'session': {'decision': 'regression', 'score': 0.8}},
            )

        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp) / 'bad'
            ctrl = SearchController(
                ROOT, d, SearchBudgets(max_proposals=1, max_seconds=60, max_stagnation=100),
                provider=OfflineMockProvider(), evaluate_fn=eval_fn,
                samples=30, provider_mode='mock')
            ctrl.run(resume=False)
            state = json.loads((d / 'search_state.json').read_text())
            bogus = d / 'missing_measurement.json'
            state['best_observed'] = {
                'candidate_id': 'x',
                'score': 0.9,
                'report': str(bogus),
                'session': {'report_path': str(bogus)},
            }
            (d / 'search_state.json').write_text(json.dumps(state))
            ctrl2 = SearchController(
                ROOT, d, SearchBudgets(max_proposals=2, max_seconds=60, max_stagnation=100),
                provider=OfflineMockProvider(), evaluate_fn=eval_fn,
                samples=30, provider_mode='mock')
            with self.assertRaisesRegex(RuntimeError, 'evidence revalidation|missing measurement'):
                ctrl2.run(resume=True)

    def test_synthetic_accepted_without_report_path_ok(self):
        state = {'accepted': {'candidate_id': 'x', 'score': 1.1}, 'best_observed': None}
        revalidate_persisted_rankings(state)  # no paths -> no-op


class CatalogRetryTests(unittest.TestCase):
    def test_interrupted_attempt_retries_same_catalog_index(self):
        seen = []

        def eval_fn(root, search_dir, proposal, index, state=None):
            seen.append(index)
            return AttemptRecord(
                f'id{index}_{len(seen)}', proposal['candidate_id'],
                (proposal['candidate_id'] + 'z' * 64)[:64],
                'ranked',
                detail={'score': 0.7, 'session': {'decision': 'regression', 'score': 0.7}},
            )

        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp) / 'retry'
            ctrl = SearchController(
                ROOT, d,
                SearchBudgets(max_proposals=1, max_seconds=60, max_stagnation=100),
                provider=OfflineMockProvider(), evaluate_fn=eval_fn,
                samples=30, provider_mode='mock')
            ctrl.run(resume=False)
            self.assertEqual(seen, [0])
            state = json.loads((d / 'search_state.json').read_text())
            state['attempts'].append({
                'attempt_id': 'deadbeef',
                'candidate_id': 'interrupted',
                'source_sha256': 'f' * 64,
                'stage': 'confirming',
                'proposal_index': 1,
                'detail': {'score': 1.5, 'proposal_index': 1},
            })
            (d / 'search_state.json').write_text(json.dumps(state))
            ctrl2 = SearchController(
                ROOT, d,
                SearchBudgets(max_proposals=3, max_seconds=60, max_stagnation=100),
                provider=OfflineMockProvider(), evaluate_fn=eval_fn,
                samples=30, provider_mode='mock')
            state2 = ctrl2.run(resume=True)
            # After reconcile, proposal_index 1 is retried (not skipped to 2).
            self.assertIn(1, seen)
            self.assertEqual(seen.count(1), 1)
            self.assertEqual(state2['attempts'][1]['stage'], 'failed')
            self.assertTrue(
                state2['attempts'][1]['detail'].get('superseded_by')
                or not state2['attempts'][1]['detail'].get('retryable'))


class InterruptChargeTests(unittest.TestCase):
    def test_incomplete_stage_charges_active_time(self):
        def eval_fn(root, search_dir, proposal, index, state=None):
            return AttemptRecord(
                f'id{index}', proposal['candidate_id'],
                (str(index) + 'e' * 63)[:64], 'ranked',
                detail={'score': 0.7, 'session': {'decision': 'regression', 'score': 0.7}},
            )

        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp) / 'charge'
            ctrl = SearchController(
                ROOT, d,
                SearchBudgets(max_proposals=1, max_seconds=60, max_stagnation=100),
                provider=OfflineMockProvider(), evaluate_fn=eval_fn,
                samples=30, provider_mode='mock')
            ctrl.run(resume=False)
            state = json.loads((d / 'search_state.json').read_text())
            before = float(state.get('active_eval_seconds') or 0)
            state['attempts'].append({
                'attempt_id': 'mid',
                'candidate_id': 'x',
                'source_sha256': 'ab' * 32,
                'stage': 'confirming',
                'proposal_index': 1,
                'detail': {'proposal_index': 1},
            })
            (d / 'search_state.json').write_text(json.dumps(state))
            ctrl2 = SearchController(
                ROOT, d,
                SearchBudgets(max_proposals=2, max_seconds=60, max_stagnation=100),
                provider=OfflineMockProvider(), evaluate_fn=eval_fn,
                samples=30, provider_mode='mock')
            state2 = ctrl2.run(resume=True)
            self.assertGreater(state2['active_eval_seconds'], before)
            mid = next(a for a in state2['attempts'] if a['attempt_id'] == 'mid')
            self.assertEqual(mid['detail'].get('charge_policy'), 'conservative_interrupt')


class PhaseInterruptTests(unittest.TestCase):
    def test_interrupt_at_confirmation_preserves_incumbent_and_retries(self):
        """Simulate crash while confirming: incumbent kept, catalog index retried."""
        calls = {'n': 0}

        def eval_fn(root, search_dir, proposal, index, state=None):
            calls['n'] += 1
            if calls['n'] == 1:
                return AttemptRecord(
                    'first', proposal['candidate_id'], 'a' * 64, 'accepted',
                    detail={
                        'score': 1.3,
                        'accepted': {'candidate_id': 'keep', 'score': 1.3},
                        'session': {'decision': 'win', 'score': 1.3},
                    },
                )
            if calls['n'] == 2:
                # Leave confirming incomplete via controller path: return confirming.
                return AttemptRecord(
                    'second', proposal['candidate_id'], 'b' * 64, 'confirming',
                    detail={'score': 1.5, 'session': {'decision': 'win', 'score': 1.5}},
                )
            return AttemptRecord(
                'third', proposal['candidate_id'], 'c' * 64, 'ranked',
                detail={
                    'score': 0.9,
                    'session': {'decision': 'regression', 'score': 0.9},
                },
            )

        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp) / 'phase'
            ctrl = SearchController(
                ROOT, d,
                SearchBudgets(max_proposals=2, max_seconds=60, max_stagnation=100),
                provider=OfflineMockProvider(), evaluate_fn=eval_fn,
                samples=30, provider_mode='mock')
            s1 = ctrl.run(resume=False)
            self.assertEqual(s1['accepted']['candidate_id'], 'keep')
            # Second attempt left incomplete / retryable.
            self.assertEqual(s1['attempts'][1]['stage'], 'confirming')
            ctrl2 = SearchController(
                ROOT, d,
                SearchBudgets(max_proposals=4, max_seconds=60, max_stagnation=100),
                provider=OfflineMockProvider(), evaluate_fn=eval_fn,
                samples=30, provider_mode='mock')
            s2 = ctrl2.run(resume=True)
            self.assertEqual(s2['accepted']['candidate_id'], 'keep')
            failed = [a for a in s2['attempts'] if a['attempt_id'] == 'second'][0]
            self.assertEqual(failed['stage'], 'failed')


class ResumeIdentityHostTests(unittest.TestCase):
    def test_resume_identity_includes_cpu_and_compiler(self):
        with tempfile.TemporaryDirectory() as tmp:
            ctrl = SearchController(ROOT, Path(tmp) / 'id', SearchBudgets())
            identity = ctrl.resume_identity()
            self.assertIn('artifacts', identity)
            self.assertIn('host', identity)
            self.assertIn('cpu_brand', identity['host'])
            self.assertIn('compiler_config', identity['host'])
            self.assertEqual(
                identity['host']['compiler_config']['baseline_flags'],
                ['-O3', '-std=c11', '-Wall', '-Wextra'])


if __name__ == '__main__':
    unittest.main()
