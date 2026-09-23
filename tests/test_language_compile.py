import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from language.interpreter import interpret
from language.ir import IrError
from language.lower import CoverageError, KernelKind, classify, lower
from language.native import check_source_equiv, run_native
from language.parser import ParseError, parse
from language.interpreter import program_find, program_map_filter, program_sum
from kernels import find_u8, map_filter_u64, sum_u64

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / 'language' / 'examples'


class ParserTests(unittest.TestCase):
    def test_examples_parse(self):
        for name in ('sum.ax', 'find.ax', 'map_filter.ax'):
            prog = parse((EXAMPLES / name).read_text())
            self.assertTrue(prog.lets)

    def test_ill_typed_source_rejected(self):
        src = 'let a = array_u8(1, 2)\nlet s = reduce_sum_u64_wrap(a)\nreturn s\n'
        with self.assertRaises(IrError):
            parse(src)

    def test_unsupported_effect_rejected(self):
        src = 'let u = store_global_u64(1)\nreturn u\n'
        with self.assertRaises(IrError):
            parse(src)

    def test_const_u8_bounds_rejected(self):
        src = 'let n = const_u8(256)\nreturn n\n'
        with self.assertRaises(IrError):
            parse(src)

    def test_return_type_mismatch_rejected(self):
        src = (
            'fn bad() -> u8\n'
            'let a = array_u64(1)\n'
            'let s = reduce_sum_u64_wrap(a)\n'
            'return s\n')
        with self.assertRaises(IrError):
            parse(src)

    def test_parse_error_on_junk(self):
        with self.assertRaises(ParseError):
            parse('let a = ???\n')


class LowerNativeTests(unittest.TestCase):
    def test_examples_native_match_interpreter(self):
        for name in ('sum.ax', 'find.ax', 'map_filter.ax'):
            result = check_source_equiv((EXAMPLES / name).read_text())
            self.assertTrue(result['ok'], result)

    def test_generated_cases_native_match(self):
        for _label, vals in sum_u64.generate_cases(3)[:15]:
            prog = program_sum(vals)
            self.assertEqual(run_native(prog), interpret(prog))
            self.assertEqual(classify(prog), KernelKind.SUM_U64)
        for _label, buf, needle in find_u8.generate_cases(3)[:15]:
            prog = program_find(buf, needle)
            self.assertEqual(run_native(prog), interpret(prog))
        for _label, vals in map_filter_u64.generate_cases(3)[:15]:
            prog = program_map_filter(vals)
            self.assertEqual(run_native(prog), interpret(prog))

    def test_unsupported_shape_coverage_error(self):
        src = 'let x = const_u64(1)\nreturn x\n'
        prog = parse(src)
        with self.assertRaises(CoverageError):
            lower(prog)

    def test_templates_exist(self):
        td = ROOT / 'language' / 'templates'
        self.assertTrue((td / 'sum_u64.s').is_file())
        self.assertTrue((td / 'find_u8.s').is_file())
        self.assertTrue((td / 'map_filter_u64.s').is_file())


if __name__ == '__main__':
    unittest.main()
