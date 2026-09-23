import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from kernels import (
    build_experiment_report,
    find_u8,
    list_kernel_ids,
    map_filter_u64,
    run_native_comparisons,
    run_oracle_selfchecks,
    sum_u64,
)

ROOT = Path(__file__).resolve().parents[1]


class PortfolioTests(unittest.TestCase):
    def test_three_kernel_families(self):
        ids = list_kernel_ids()
        self.assertEqual(ids, ['find_u8', 'map_filter_u64', 'sum_u64'])

    def test_oracle_selfchecks(self):
        report = run_oracle_selfchecks(seed=3)
        self.assertTrue(report['all_passed'])
        for kid in list_kernel_ids():
            self.assertTrue(report['kernels'][kid]['wrong_diverges'])

    def test_find_oracle_and_wrong(self):
        self.assertEqual(find_u8.oracle([1, 2, 3], 2), 1)
        self.assertEqual(find_u8.oracle([1, 2, 3], 9), 3)
        self.assertNotEqual(find_u8.wrong_find([1, 2, 1], 1), find_u8.oracle([1, 2, 1], 1))

    def test_map_filter_stable(self):
        self.assertEqual(map_filter_u64.oracle([2, 3, 4]), [1, 2])
        self.assertEqual(map_filter_u64.oracle([1, 3, 5]), [])
        vals = [2, 4, 6]
        self.assertNotEqual(map_filter_u64.wrong_map_filter(vals), map_filter_u64.oracle(vals))

    def test_experiments_separate_observation_inference(self):
        rep = build_experiment_report([16, 1048576])
        self.assertFalse(rep['mandatory_speedup'])
        row = rep['cache']['rows'][0]
        self.assertIn('observation', row)
        self.assertIn('inference', row)
        self.assertIn('observations', rep['dependencies'])
        self.assertIn('inferences', rep['dependencies'])

    def test_native_comparisons(self):
        rep = run_native_comparisons(ROOT, seed=1)
        self.assertTrue(rep['all_ok'])
        self.assertFalse(rep['mandatory_speedup'])


if __name__ == '__main__':
    unittest.main()
