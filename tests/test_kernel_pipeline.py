"""T010: multi-kernel descriptor pipeline tests."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from kernels.descriptors import (
    DESCRIPTORS,
    get_descriptor,
    list_descriptor_ids,
    sanitize_evidence_summary,
)
from proposals import ProposalError, validate_proposal
from test_search_rank import make_report

ROOT = Path(__file__).resolve().parents[1]


class DescriptorTests(unittest.TestCase):
    def test_three_descriptors(self):
        ids = list_descriptor_ids()
        self.assertEqual(ids, ['find_u8', 'map_filter_u64', 'sum_u64'])
        for kid in ids:
            d = get_descriptor(kid)
            self.assertTrue(Path(d['harness']).is_file(), kid)
            self.assertTrue(Path(d['abi_wrap']).is_file(), kid)
            self.assertTrue(Path(d['baseline_source']).is_file(), kid)
            self.assertTrue(Path(d['asm_baseline']).is_file(), kid)
            self.assertTrue(Path(d['wrong_candidate']).is_file(), kid)
            self.assertIn(d['asm_symbol'], ('_sum_array', '_find_u8', '_map_filter_u64'))

    def test_sanitize_summary(self):
        report = make_report('r1', 100, 50)
        summary = sanitize_evidence_summary(report)
        self.assertEqual(summary['schema'], 'evidence_summary_v1')
        self.assertIn('full_report_sha256', summary)
        self.assertNotIn('raw_samples', str(summary['variants']))


class ProposalKernelTests(unittest.TestCase):
    def test_find_proposal_requires_symbol(self):
        src = (ROOT / 'asm' / 'find_u8.s').read_text()
        parent = __import__('hashlib').sha256(
            (ROOT / 'asm' / 'find_u8.s').read_bytes()).hexdigest()
        proposal = {
            'schema_version': 1,
            'candidate_id': 'find_ok',
            'kernel_id': 'find_u8',
            'contract_version': 1,
            'parent_source_sha256': parent,
            'hypothesis': 'find template',
            'source': src,
            'expected_size_range': [0, 1024],
            'provenance': {'mode': 'offline'},
        }
        validate_proposal(proposal, ROOT)

    def test_sum_source_rejected_for_find_kernel(self):
        from proposals import mock_propose
        p = mock_propose(ROOT)
        p['kernel_id'] = 'find_u8'
        with self.assertRaises(ProposalError):
            validate_proposal(p, ROOT)


@unittest.skipUnless(
    __import__('sys').platform == 'darwin'
    and __import__('platform').machine() == 'arm64'
    and __import__('shutil').which('clang'),
    'requires macOS arm64 and clang')
class NativeKernelPipelineTests(unittest.TestCase):
    def test_find_build_verify_oracle(self):
        from evaluate import build_and_verify
        with tempfile.TemporaryDirectory() as tmp:
            binary, record = build_and_verify(
                'find_ref', ROOT / 'src' / 'find_u8_ref.c', Path(tmp),
                kernel_id='find_u8')
            self.assertEqual(record['lifecycle'], 'verified')
            self.assertEqual(record['oracle']['state'], 'pass')

    def test_map_filter_build_verify_oracle(self):
        from evaluate import build_and_verify
        with tempfile.TemporaryDirectory() as tmp:
            binary, record = build_and_verify(
                'mf_ref', ROOT / 'src' / 'map_filter_u64_ref.c', Path(tmp),
                kernel_id='map_filter_u64')
            self.assertEqual(record['lifecycle'], 'verified')

    def test_wrong_find_fails(self):
        from evaluate import build_and_verify
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(Exception):
                build_and_verify(
                    'wrong_find', ROOT / 'candidates' / 'wrong_find.s', Path(tmp),
                    kernel_id='find_u8')


if __name__ == '__main__':
    unittest.main()
