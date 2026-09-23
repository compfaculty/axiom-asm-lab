"""Exercise main() dispatch before the platform-specific compiler boundary."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import lab


class CompilerBoundaryReached(Exception):
    pass


class CliDispatchTests(unittest.TestCase):
    def test_verify_and_bench_reach_compiler(self):
        for command in ('verify', 'bench'):
            with self.subTest(command=command), \
                    patch.object(sys, 'argv', ['lab.py', command]), \
                    patch.object(lab, 'doctor'), \
                    patch.object(lab, 'new_run_dir', return_value=('test', Path('/unused'))), \
                    patch.object(lab, 'compile_one', side_effect=CompilerBoundaryReached) as compile_one:
                with self.assertRaises(CompilerBoundaryReached):
                    lab.main()
                name, source, _ = compile_one.call_args.args
                self.assertEqual(name, 'clang_o3')
                self.assertEqual(source, lab.BUILTIN_SOURCES['clang_o3'])
