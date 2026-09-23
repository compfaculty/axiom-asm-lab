import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import proposals
from proposals import ProposalError, import_proposal, mock_propose, validate_proposal

ROOT = Path(__file__).resolve().parents[1]


def _valid():
    return mock_propose(ROOT, candidate_id='mock_ok')


class ProposalTests(unittest.TestCase):
    def test_mock_validates(self):
        p = _valid()
        self.assertEqual(p['schema_version'], 1)
        self.assertEqual(p['kernel_id'], 'sum_u64')

    def test_malformed_id(self):
        p = _valid()
        p['candidate_id'] = 'bad id!'
        with self.assertRaises(ProposalError):
            validate_proposal(p, ROOT)

    def test_unknown_kernel(self):
        p = _valid()
        p['kernel_id'] = 'not_a_kernel'
        with self.assertRaises(ProposalError):
            validate_proposal(p, ROOT)

    def test_invalid_parent(self):
        p = _valid()
        p['parent_source_sha256'] = 'ab' * 32
        with self.assertRaises(ProposalError) as ctx:
            validate_proposal(p, ROOT)
        self.assertIn('invalid parent', str(ctx.exception))

    def test_oversized_source(self):
        p = _valid()
        p['source'] = 'x' * (proposals.MAX_SOURCE_BYTES + 1)
        with self.assertRaises(ProposalError) as ctx:
            validate_proposal(p, ROOT)
        self.assertIn('max bytes', str(ctx.exception))

    def test_include_rejected(self):
        p = _valid()
        p['source'] = '.text\n.include "evil.s"\n.globl _sum_array\n_sum_array:\n ret\n'
        with self.assertRaises(ProposalError) as ctx:
            validate_proposal(p, ROOT)
        self.assertIn('.include', str(ctx.exception))

    def test_unknown_field_rejected(self):
        p = _valid()
        p['extra_field'] = 1
        with self.assertRaises(ProposalError):
            validate_proposal(p, ROOT)

    def test_immutable_import(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            p = _valid()
            info = import_proposal(p, tmp, ROOT)
            self.assertTrue(Path(info['source_path']).is_file())
            with self.assertRaises(FileExistsError):
                import_proposal(p, tmp, ROOT)


if __name__ == '__main__':
    unittest.main()
