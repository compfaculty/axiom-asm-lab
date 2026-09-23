import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from analysis import (
    BOOTSTRAP_RESAMPLES,
    classify_promotion,
    classify_session,
    geometric_mean,
    paired_bootstrap_ci,
    per_size_speedups,
    regression_violations,
)


def _paired_constant(b, c, sizes=('4', '16', '64'), n=30):
    return {s: [(b, c)] * n for s in sizes}


class AnalysisTests(unittest.TestCase):
    def test_geometric_mean(self):
        self.assertAlmostEqual(geometric_mean([2, 8]), 4.0)

    def test_per_size_speedups(self):
        sp = per_size_speedups({'4': 100.0, '16': 200.0}, {'4': 50.0, '16': 100.0})
        self.assertEqual(sp['4'], 2.0)
        self.assertEqual(sp['16'], 2.0)

    def test_regression_ceiling(self):
        # candidate 5% slower -> speedup 1/1.05 ≈ 0.952 < 0.97
        sp = {'4': 100 / 105}
        self.assertEqual(regression_violations(sp), ['4'])
        self.assertEqual(regression_violations({'4': 1.0}), [])

    def test_synthetic_win(self):
        paired = _paired_constant(100.0, 50.0)
        med_b = {s: 100.0 for s in paired}
        med_c = {s: 50.0 for s in paired}
        session = classify_session(med_b, med_c, paired=paired, bootstrap_seed=1,
                                   resamples=500)
        self.assertEqual(session['decision'], 'win')
        self.assertTrue(session['promote_eligible'])

    def test_synthetic_tie_inconclusive(self):
        paired = _paired_constant(100.0, 100.0)
        med = {s: 100.0 for s in paired}
        session = classify_session(med, med, paired=paired, bootstrap_seed=2,
                                   resamples=500)
        self.assertEqual(session['decision'], 'inconclusive')
        self.assertFalse(session['promote_eligible'])

    def test_synthetic_regression(self):
        paired = _paired_constant(50.0, 100.0)
        med_b = {s: 50.0 for s in paired}
        med_c = {s: 100.0 for s in paired}
        session = classify_session(med_b, med_c, paired=paired, bootstrap_seed=3,
                                   resamples=500)
        self.assertEqual(session['decision'], 'regression')
        self.assertFalse(session['promote_eligible'])

    def test_missing_data_cannot_promote(self):
        session = classify_session({'4': 10.0, '16': None}, {'4': 5.0, '16': 5.0},
                                   resamples=100)
        self.assertEqual(session['decision'], 'missing_data')
        promo = classify_promotion(session, session)
        self.assertFalse(promo['speed_claim'])
        self.assertEqual(promo['decision'], 'missing_data')

    def test_speed_claim_needs_two_sessions(self):
        paired = _paired_constant(100.0, 50.0)
        med_b = {s: 100.0 for s in paired}
        med_c = {s: 50.0 for s in paired}
        a = classify_session(med_b, med_c, paired=paired, bootstrap_seed=1, resamples=500)
        one = classify_promotion(a, None)
        self.assertFalse(one['speed_claim'])
        self.assertEqual(one['decision'], 'needs_second_session')
        b = classify_session(med_b, med_c, paired=paired, bootstrap_seed=2, resamples=500)
        a.update(run_id='a', identity={'test': 'same-artifacts'})
        b.update(run_id='b', identity={'test': 'same-artifacts'})
        two = classify_promotion(a, b)
        self.assertTrue(two['speed_claim'])
        self.assertEqual(two['decision'], 'promoted')

    def test_no_raw_samples_no_promotion(self):
        result = classify_session({'64': 100}, {'64': 50})
        self.assertFalse(result['promote_eligible'])

    def test_insufficient_samples_no_promotion(self):
        result = classify_session({'64': 100}, {'64': 50}, {'64': [(100, 50)] * 29})
        self.assertFalse(result['promote_eligible'])

    def test_duplicate_session_no_promotion(self):
        session = {'promote_eligible': True, 'run_id': 'same', 'identity': {'a': 1}}
        self.assertFalse(classify_promotion(session, session)['speed_claim'])

    def test_artifact_mismatch_no_promotion(self):
        a = {'promote_eligible': True, 'run_id': 'a', 'identity': {'source': 'x'}}
        b = {'promote_eligible': True, 'run_id': 'b', 'identity': {'source': 'y'}}
        self.assertFalse(classify_promotion(a, b)['speed_claim'])

    def test_precise_regression_ceiling(self):
        self.assertEqual(regression_violations({'64': 1 / 1.0305}), ['64'])

    def test_bootstrap_seed_reproducible(self):
        paired = _paired_constant(100.0, 80.0, n=15)
        x = paired_bootstrap_ci(paired, seed=99, resamples=200)
        y = paired_bootstrap_ci(paired, seed=99, resamples=200)
        self.assertEqual(x, y)


if __name__ == '__main__':
    unittest.main()
