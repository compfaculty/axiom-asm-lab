import copy
import json
import platform
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, Mock

import lab
from analysis import validate_report
from proposals import mock_propose
from search import native_evaluate_attempt, atomic_write_json

ROOT = Path(__file__).resolve().parents[1]


def report_fixture():
    def variant(ns):
        return {'lifecycle': 'measured', 'verification': {'state': 'pass'},
                'oracle': {'state': 'pass'}, 'compiler_identity': 'clang',
                **{key: 'a' * 64 for key in ('source_sha256', 'binary_sha256',
                                           'harness_sha256', 'abi_wrap_sha256')},
                'sizes': {'64': {'median_ns': ns, 'raw_samples': [
                    {'sample_index': i, 'ns_per_call': ns, 'iterations': 1000000,
                     'elapsed_ns': ns * 1000000} for i in range(30)]}}}
    return {'schema': 2, 'run_id': 'run', 'host': 'host', 'machine': 'arm64',
            'clang': 'clang', 'measure_sizes': [64], 'target_sample_ns': 20000000,
            'variants': {'baseline': variant(100), 'candidate': variant(80)}}


class ReportIntegrityTests(unittest.TestCase):
    def test_valid_report(self):
        validate_report(report_fixture(), 'baseline', 'candidate', [64])

    def test_invalid_reports_rejected(self):
        for fault in ('summary_only', 'duplicate_index', 'nan', 'wrong_median',
                      'missing_objective', 'short_duration', 'unverified'):
            with self.subTest(fault=fault):
                report = report_fixture()
                variant = report['variants']['candidate']
                payload = variant['sizes']['64']
                if fault == 'summary_only': payload['raw_samples'] = []
                if fault == 'duplicate_index': payload['raw_samples'][1]['sample_index'] = 0
                if fault == 'nan': payload['raw_samples'][0]['ns_per_call'] = float('nan')
                if fault == 'wrong_median': payload['median_ns'] = 1
                if fault == 'missing_objective': report['measure_sizes'] = []
                if fault == 'short_duration': report['target_sample_ns'] = 5000000
                if fault == 'unverified': variant['verification']['state'] = 'built'
                with self.assertRaises(ValueError):
                    validate_report(report, 'baseline', 'candidate', [64])


class NativeEvaluatorWiringTests(unittest.TestCase):
    def test_evaluator_requires_real_output(self):
        # Simulate a zero exit without a report: it must not count as verified.
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            import time
            atomic_write_json(directory / 'search_state.json',
                              {'budgets': {'max_seconds': 60}, 'wall_started': time.time()})
            child = Mock(returncode=0)
            child.communicate.return_value = ('', '')
            with patch('search.subprocess.Popen', return_value=child) as spawn:
                result = native_evaluate_attempt(ROOT, directory, mock_propose(ROOT), 0)
            self.assertEqual(result.stage, 'failed')
            self.assertIn('evaluate-proposal', spawn.call_args.args[0])


@unittest.skipUnless(sys.platform == 'darwin' and platform.machine() == 'arm64'
                     and shutil.which('clang'), 'requires macOS arm64 and clang')
class NativeBoundaryTests(unittest.TestCase):
    def test_normal_verifier_rejects_boundary_faults(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            for name in ('overread', 'underread', 'input_write', 'abi_corrupt'):
                with self.subTest(name=name):
                    binary, record = lab.compile_one(name, ROOT / 'fixtures' / (name + '.s'), directory)
                    with self.assertRaises(Exception):
                        lab.verify_binary(binary, record, directory)
                    self.assertEqual(record['verification']['state'], 'failed')
            binary, record = lab.compile_one('control', ROOT / 'asm/scalar.s', directory)
            self.assertEqual(lab.verify_binary(binary, record, directory), 'PASS')
