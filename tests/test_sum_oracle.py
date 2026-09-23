import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from kernels.sum_u64 import (
    BOUNDARY_LENGTHS,
    CONTRACT,
    MASK,
    case_fingerprint,
    generate_cases,
    oracle,
    wrong_sum,
)


class SumOracleTests(unittest.TestCase):
    def test_contract_metadata(self):
        self.assertEqual(CONTRACT['kernel_id'], 'sum_u64')
        self.assertEqual(CONTRACT['overflow'], 'wrap_mod_2_64')
        self.assertEqual(CONTRACT['empty_null']['result'], 0)
        self.assertIsNone(CONTRACT['empty_null']['pointer'])

    def test_empty_null_semantics(self):
        self.assertEqual(oracle([]), 0)

    def test_wrapping_overflow(self):
        self.assertEqual(oracle([MASK, 1]), 0)
        self.assertEqual(oracle([MASK, MASK]), (MASK + MASK) & MASK)

    def test_boundary_lengths_include_unroll_edges(self):
        for n in (0, 1, 3, 4, 7, 8, 15, 16, 63, 64):
            self.assertIn(n, BOUNDARY_LENGTHS)

    def test_distributions_cover_patterns(self):
        labels = [label for label, _ in generate_cases(1)]
        self.assertIn('empty_null', labels)
        joined = ' '.join(labels)
        for pattern in ('zeros', 'ones', 'max', 'alternating', 'overflow_edges', 'random'):
            self.assertIn(pattern, joined)

    def test_seed_reproduces_cases(self):
        a = generate_cases(42)
        b = generate_cases(42)
        c = generate_cases(43)
        self.assertEqual(case_fingerprint(a), case_fingerprint(b))
        self.assertNotEqual(case_fingerprint(a), case_fingerprint(c))
        self.assertEqual(a, b)

    def test_wrong_sum_diverges_and_seed_reproduces_failure(self):
        cases = generate_cases(7)
        failures = []
        for label, values in cases:
            if wrong_sum(values) != oracle(values):
                failures.append(label)
        self.assertTrue(failures)
        # Replay with the same seed yields the same first failing label.
        again = generate_cases(7)
        first = next(label for label, values in again if wrong_sum(values) != oracle(values))
        self.assertEqual(first, failures[0])

    def test_cases_match_oracle_identity(self):
        for label, values in generate_cases(1):
            self.assertEqual(oracle(values), oracle(list(values)), label)


if __name__ == '__main__':
    unittest.main()
