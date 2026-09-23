"""Decision tests for ranking, confirmation, resume, and smoke (synthetic timings)."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from analysis import classify_promotion, classify_session, validate_report
from evaluate import PROTOCOL_SIZES
from search import (
    AttemptRecord,
    OfflineCatalogProvider,
    OfflineMockProvider,
    SearchBudgets,
    SearchController,
    get_provider,
    rank_from_report,
    refuse_stale_promotion,
)

ROOT = Path(__file__).resolve().parents[1]
SIZES = [64, 1024]


def _raw(ns, n=30):
    return [
        {
            'sample_index': i,
            'ns_per_call': ns,
            'iterations': 1_000_000,
            'elapsed_ns': ns * 1_000_000,
        }
        for i in range(n)
    ]


def make_report(run_id, baseline_ns, candidate_ns, sizes=None, promotional=True,
                candidate='cand', samples=30):
    sizes = sizes or SIZES
    def variant(ns, name):
        return {
            'lifecycle': 'measured',
            'verification': {'state': 'pass'},
            'oracle': {'state': 'pass'},
            'compiler_identity': 'clang',
            **{k: ('b' if name == 'clang_o3' else 'c') * 64
               for k in ('source_sha256', 'binary_sha256', 'harness_sha256', 'abi_wrap_sha256')},
            'sizes': {
                str(s): {
                    'median_ns': ns,
                    'raw_samples': _raw(ns, samples),
                }
                for s in sizes
            },
        }
    return {
        'schema': 2,
        'run_id': run_id,
        'host': 'host',
        'machine': 'arm64',
        'clang': 'clang',
        'measure_sizes': sizes,
        'skipped_sizes': [],
        'target_sample_ns': 20_000_000,
        'samples_per_size': samples,
        'promotional': promotional,
        'variants': {
            'clang_o3': variant(baseline_ns, 'clang_o3'),
            candidate: variant(candidate_ns, candidate),
        },
    }


class SmokeReportTests(unittest.TestCase):
    def test_smoke_report_rejected_by_validate(self):
        report = make_report('r1', 100, 50, promotional=False)
        with self.assertRaises(ValueError) as ctx:
            validate_report(report, 'clang_o3', 'cand', SIZES)
        self.assertIn('Non-promotional', str(ctx.exception))


class RankingDecisionTests(unittest.TestCase):
    def test_verified_paired_measurement_ranks(self):
        # Candidate 2x faster -> win / promote_eligible
        report = make_report('sess_a', baseline_ns=200, candidate_ns=100)
        session = rank_from_report(report, 'clang_o3', 'cand', SIZES, bootstrap_seed=1)
        self.assertEqual(session['decision'], 'win')
        self.assertTrue(session['promote_eligible'])
        self.assertGreater(session['score'], 1.05)

    def test_first_win_confirm_loss_no_promotion(self):
        a = rank_from_report(
            make_report('a', 200, 100), 'clang_o3', 'cand', SIZES, bootstrap_seed=1)
        b = rank_from_report(
            make_report('b', 100, 200), 'clang_o3', 'cand', SIZES, bootstrap_seed=2)
        self.assertTrue(a['promote_eligible'])
        self.assertFalse(b['promote_eligible'])
        promo = classify_promotion(a, b)
        self.assertFalse(promo['speed_claim'])
        self.assertEqual(promo['decision'], 'not_promoted')

    def test_two_winning_sessions_accept(self):
        a = rank_from_report(
            make_report('a', 200, 100), 'clang_o3', 'cand', SIZES, bootstrap_seed=1)
        b = rank_from_report(
            make_report('b', 200, 100), 'clang_o3', 'cand', SIZES, bootstrap_seed=2)
        promo = classify_promotion(a, b)
        self.assertTrue(promo['speed_claim'])
        self.assertEqual(promo['decision'], 'promoted')

    def test_duplicate_session_rejected(self):
        a = rank_from_report(
            make_report('same', 200, 100), 'clang_o3', 'cand', SIZES, bootstrap_seed=1)
        b = dict(a)  # same run_id
        promo = classify_promotion(a, b)
        self.assertFalse(promo['speed_claim'])
        self.assertEqual(promo['decision'], 'invalid_sessions')

    def test_missing_evidence_rejected(self):
        report = make_report('m', 200, 100, samples=5)
        with self.assertRaises(ValueError):
            validate_report(report, 'clang_o3', 'cand', SIZES)

    def test_all_lose_search_no_accepted(self):
        """Synthetic evaluator: all candidates lose to clang; search completes with accepted=None."""
        def eval_lose(root, search_dir, proposal, index, state=None):
            # Score < 1.0 means slower than baseline
            score = 0.5 - index * 0.01
            return AttemptRecord(
                attempt_id=f'a{index}',
                candidate_id=proposal['candidate_id'],
                source_sha256=proposal['candidate_id'] + '0' * 48,
                stage='ranked',
                detail={
                    'score': score,
                    'session': {
                        'decision': 'regression',
                        'promote_eligible': False,
                        'reason': 'aggregate favors baseline',
                        'score': score,
                    },
                    'rejection_reason': 'aggregate favors baseline',
                },
            )

        with tempfile.TemporaryDirectory() as tmp:
            ctrl = SearchController(
                ROOT, Path(tmp) / 'lose',
                SearchBudgets(max_proposals=3, max_seconds=60, max_stagnation=100),
                provider=OfflineMockProvider(),
                evaluate_fn=eval_lose,
                smoke=False,
                samples=30,
                provider_mode='mock',
            )
            state = ctrl.run(resume=False)
            self.assertEqual(state['stop_reason'], 'max_proposals')
            self.assertIsNone(state['accepted'])
            self.assertIsNotNone(state['best_observed'])
            self.assertEqual(state['best_observed']['score'], 0.5)

    def test_confirm_loss_preserves_incumbent(self):
        accepted_holder = {'value': {'candidate_id': 'incumbent'}}

        def eval_fn(root, search_dir, proposal, index, state=None):
            if index == 0:
                return AttemptRecord(
                    'id0', proposal['candidate_id'], 'a' * 64, 'accepted',
                    detail={
                        'score': 1.2,
                        'accepted': accepted_holder['value'],
                        'session': {'decision': 'win', 'promote_eligible': True, 'score': 1.2},
                    },
                )
            # Second: ranked win on first session but confirmation failed -> rejected, no accepted key
            return AttemptRecord(
                'id1', proposal['candidate_id'], 'b' * 64, 'rejected',
                detail={
                    'score': 1.3,
                    'rejection_reason': 'not both sessions promote_eligible',
                    'session': {'decision': 'win', 'promote_eligible': True, 'score': 1.3},
                },
            )

        with tempfile.TemporaryDirectory() as tmp:
            ctrl = SearchController(
                ROOT, Path(tmp) / 'inc',
                SearchBudgets(max_proposals=2, max_seconds=60, max_stagnation=100),
                provider=OfflineMockProvider(),
                evaluate_fn=eval_fn,
                samples=30,
                provider_mode='mock',
            )
            state = ctrl.run(resume=False)
            self.assertEqual(state['accepted'], accepted_holder['value'])
            self.assertEqual(state['best_observed']['score'], 1.3)

    def test_crash_preserves_incumbent(self):
        def eval_fn(root, search_dir, proposal, index, state=None):
            if index == 0:
                return AttemptRecord(
                    'id0', proposal['candidate_id'], 'a' * 64, 'accepted',
                    detail={
                        'score': 1.1,
                        'accepted': {'candidate_id': 'keep'},
                        'session': {'decision': 'win', 'score': 1.1},
                    },
                )
            return AttemptRecord(
                'id1', proposal['candidate_id'], 'b' * 64, 'failed',
                detail={'error': 'timeout', 'score': None},
            )

        with tempfile.TemporaryDirectory() as tmp:
            ctrl = SearchController(
                ROOT, Path(tmp) / 'crash',
                SearchBudgets(max_proposals=2, max_seconds=60, max_stagnation=100),
                provider=OfflineMockProvider(),
                evaluate_fn=eval_fn,
                samples=30,
                provider_mode='mock',
            )
            state = ctrl.run(resume=False)
            self.assertEqual(state['accepted']['candidate_id'], 'keep')

    def test_interrupted_search_resumes(self):
        calls = {'n': 0}

        def eval_fn(root, search_dir, proposal, index, state=None):
            calls['n'] += 1
            return AttemptRecord(
                f'id{index}', proposal['candidate_id'],
                (proposal['candidate_id'] + 'x' * 64)[:64],
                'ranked',
                detail={
                    'score': 0.9,
                    'session': {'decision': 'regression', 'score': 0.9},
                },
            )

        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp) / 'res'
            ctrl = SearchController(
                ROOT, d,
                SearchBudgets(max_proposals=2, max_seconds=60, max_stagnation=100),
                provider=OfflineMockProvider(),
                evaluate_fn=eval_fn,
                samples=30,
                provider_mode='mock',
            )
            s1 = ctrl.run(resume=False)
            self.assertEqual(s1['stop_reason'], 'max_proposals')
            self.assertEqual(len(s1['attempts']), 2)
            ctrl2 = SearchController(
                ROOT, d,
                SearchBudgets(max_proposals=4, max_seconds=60, max_stagnation=100),
                provider=OfflineMockProvider(),
                evaluate_fn=eval_fn,
                samples=30,
                provider_mode='mock',
            )
            s2 = ctrl2.run(resume=True)
            self.assertEqual(len(s2['attempts']), 4)
            self.assertEqual(s2['stop_reason'], 'max_proposals')

    def test_resume_config_mismatch_rejected(self):
        def eval_fn(root, search_dir, proposal, index, state=None):
            return AttemptRecord('x', proposal['candidate_id'], 'c' * 64, 'imported',
                                 detail={'dry': True})

        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp) / 'mismatch'
            ctrl = SearchController(
                ROOT, d, SearchBudgets(max_proposals=1, max_seconds=60, max_stagnation=100),
                provider=OfflineMockProvider(), evaluate_fn=eval_fn,
                samples=30, smoke=False, provider_mode='mock')
            ctrl.run(resume=False)
            ctrl2 = SearchController(
                ROOT, d, SearchBudgets(max_proposals=2, max_seconds=60, max_stagnation=100),
                provider=OfflineMockProvider(), evaluate_fn=eval_fn,
                samples=30, smoke=True, provider_mode='mock')
            with self.assertRaises(RuntimeError):
                ctrl2.run(resume=True)

    def test_active_time_budget_not_wall(self):
        """max_seconds uses active_eval_seconds; idle wall time does not stop search."""
        def eval_fn(root, search_dir, proposal, index, state=None):
            return AttemptRecord(
                f'i{index}', proposal['candidate_id'],
                (str(index) + 'd' * 63)[:64], 'ranked',
                detail={'score': 0.8, 'session': {'decision': 'regression', 'score': 0.8}},
            )

        with tempfile.TemporaryDirectory() as tmp:
            ctrl = SearchController(
                ROOT, Path(tmp) / 'time',
                SearchBudgets(max_proposals=2, max_seconds=1000, max_stagnation=100),
                provider=OfflineMockProvider(), evaluate_fn=eval_fn,
                samples=30, provider_mode='mock')
            state = ctrl.run(resume=False)
            self.assertEqual(state['stop_reason'], 'max_proposals')
            self.assertEqual(state['time_budget_mode'], 'active_evaluation_seconds')
            self.assertGreaterEqual(state['active_eval_seconds'], 0.0)


class CatalogProviderTests(unittest.TestCase):
    def test_catalog_distinct_sources(self):
        p = OfflineCatalogProvider()
        hashes = set()
        for i in range(5):
            prop = p.propose(i, ROOT)
            hashes.add(prop['source'])
        self.assertEqual(len(hashes), 5)
        with self.assertRaises(StopIteration):
            p.propose(5, ROOT)

    def test_get_provider_modes(self):
        self.assertIsInstance(get_provider('catalog'), OfflineCatalogProvider)
        self.assertIsInstance(get_provider('mock'), OfflineMockProvider)
        self.assertIsInstance(get_provider('offline'), OfflineMockProvider)



class ResumeRecoveryTests(unittest.TestCase):
    def test_incomplete_stage_not_treated_completed(self):
        def eval_fn(root, search_dir, proposal, index, state=None):
            return AttemptRecord(
                f'id{index}', proposal['candidate_id'],
                (str(index) + 'e' * 63)[:64], 'ranked',
                detail={'score': 0.7, 'session': {'decision': 'regression', 'score': 0.7}},
            )

        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp) / 'rec'
            ctrl = SearchController(
                ROOT, d,
                SearchBudgets(max_proposals=1, max_seconds=60, max_stagnation=100),
                provider=OfflineMockProvider(), evaluate_fn=eval_fn,
                samples=30, provider_mode='mock')
            ctrl.run(resume=False)
            # Inject an interrupted confirming attempt that was wrongly left incomplete.
            state = json.loads((d / 'search_state.json').read_text())
            state['attempts'].append({
                'attempt_id': 'deadbeef',
                'candidate_id': 'interrupted',
                'source_sha256': 'f' * 64,
                'stage': 'confirming',
                'detail': {'score': 1.5},
            })
            state['completed_source_sha256'].append('f' * 64)
            (d / 'search_state.json').write_text(json.dumps(state))
            # Orphan dir from crash before state append.
            orphan = d / 'attempts' / '0099_orphan99ab'
            orphan.mkdir(parents=True)
            (orphan / 'attempt.json').write_text(json.dumps({
                'attempt_id': 'orphan99ab',
                'candidate_id': 'orphan_cand',
                'stage': 'proposed',
                'source_sha256': 'a' * 64,
            }))
            ctrl2 = SearchController(
                ROOT, d,
                SearchBudgets(max_proposals=3, max_seconds=60, max_stagnation=100),
                provider=OfflineMockProvider(), evaluate_fn=eval_fn,
                samples=30, provider_mode='mock')
            state2 = ctrl2.run(resume=True)
            stages = {a['attempt_id']: a['stage'] for a in state2['attempts']}
            self.assertEqual(stages['deadbeef'], 'failed')
            self.assertNotIn('f' * 64, state2['completed_source_sha256'])
            orphans = state2.get('orphaned_attempts') or []
            self.assertTrue(any(o.get('attempt_id') == 'orphan99ab' for o in orphans))
            self.assertEqual(orphans[0]['stage'], 'failed')
            # Proposal index still advances only via attempts list, not orphans.
            self.assertEqual(state2['stop_reason'], 'max_proposals')
            self.assertEqual(len(state2['attempts']), 3)


class NeonNativeTests(unittest.TestCase):
    @unittest.skipUnless(
        __import__('sys').platform == 'darwin'
        and __import__('platform').machine() == 'arm64'
        and __import__('shutil').which('clang'),
        'requires macOS arm64 and clang')
    def test_neon_odd_lengths_and_boundaries(self):
        import tempfile
        from evaluate import build_and_verify
        with tempfile.TemporaryDirectory() as tmp:
            binary, record = build_and_verify(
                'neon_sum', ROOT / 'asm' / 'neon_sum.s', Path(tmp))
            self.assertEqual(record['lifecycle'], 'verified')
            self.assertEqual(record['oracle']['state'], 'pass')
            # Spot-check odd and NEON-boundary lengths via harness sum-file.
            from kernels.sum_u64 import oracle, write_sum_file
            import lab
            for n in (0, 1, 3, 5, 7, 9, 15, 17):
                values = [(i * 0x9E3779B97F4A7C15) & ((1 << 64) - 1) for i in range(n)]
                path = Path(tmp) / f'n{n}.txt'
                write_sum_file(path, values)
                got = int(lab.run([str(binary), 'sum-file', str(path)], timeout=30))
                self.assertEqual(got, oracle(values), f'n={n}')


if __name__ == '__main__':
    unittest.main()
