import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from language import IrError, interpret, program_find, program_map_filter, program_sum, typecheck
from language.ir import Expr, Let, Program
from kernels import find_u8, map_filter_u64, sum_u64


class IrInterpreterTests(unittest.TestCase):
    def test_sum_matches_oracle(self):
        for vals in ([], [1, 2, 3], [2**64 - 1, 1], [7] * 20):
            self.assertEqual(interpret(program_sum(vals)), sum_u64.oracle(vals))

    def test_find_matches_oracle(self):
        cases = [([], 0), ([1, 2, 3], 2), ([5, 5], 9)]
        for buf, needle in cases:
            self.assertEqual(
                interpret(program_find(buf, needle)), find_u8.oracle(buf, needle))

    def test_map_filter_matches_oracle(self):
        for vals in ([], [1, 3], [2, 4, 6], [2, 3, 4, 5]):
            self.assertEqual(
                interpret(program_map_filter(vals)), map_filter_u64.oracle(vals))

    def test_generated_cases_match_oracles(self):
        for label, vals in sum_u64.generate_cases(2)[:20]:
            self.assertEqual(interpret(program_sum(vals)), sum_u64.oracle(vals), label)
        for label, buf, needle in find_u8.generate_cases(2)[:20]:
            self.assertEqual(
                interpret(program_find(buf, needle)), find_u8.oracle(buf, needle), label)
        for label, vals in map_filter_u64.generate_cases(2)[:20]:
            self.assertEqual(
                interpret(program_map_filter(vals)), map_filter_u64.oracle(vals), label)

    def test_ill_typed_rejected(self):
        bad = Program(
            lets=[
                Let('a', Expr('array_u8', [1, 2])),
                Let('s', Expr('reduce_sum_u64_wrap', ['a'])),
            ],
            ret='s',
        )
        with self.assertRaises(IrError):
            typecheck(bad)

    def test_unsupported_effect_rejected(self):
        bad = Program(
            lets=[Let('u', Expr('store_global_u64', [1]))],
            ret='u',
        )
        with self.assertRaises(IrError) as ctx:
            typecheck(bad)
        self.assertIn('unsupported', str(ctx.exception).lower())

    def test_unbound_return_rejected(self):
        bad = Program(lets=[Let('a', Expr('const_u64', [1]))], ret='missing')
        with self.assertRaises(IrError):
            typecheck(bad)


if __name__ == '__main__':
    unittest.main()
