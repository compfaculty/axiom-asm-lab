import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import lab


def _verified_record(tmp: Path):
    source = tmp / 'cand.s'
    source.write_text('nop\n')
    harness = tmp / 'harness.c'
    harness.write_text('/* h */\n')
    abi = tmp / 'abi_wrap.s'
    abi.write_text('/* a */\n')
    # Point module paths at copies so edits are isolated.
    lab.HARNESS = harness
    lab.ABI_WRAP = abi
    record = {
        'name': 'cand',
        'lifecycle': lab.LIFECYCLE_VERIFIED,
        'source_path': str(source),
        'source_sha256': lab.sha256_file(source),
        'harness_sha256': lab.sha256_file(harness),
        'abi_wrap_sha256': lab.sha256_file(abi),
        'binary_sha256': '0' * 64,
        'verification': {
            'state': 'pass',
            'output': 'PASS',
            'source_sha256_at_verify': lab.sha256_file(source),
            'harness_sha256_at_verify': lab.sha256_file(harness),
            'abi_wrap_sha256_at_verify': lab.sha256_file(abi),
        },
        'oracle': {'state': 'pass', 'case_count': 1},
        'diagnostics': [],
    }
    return record, source, harness


class LifecycleTests(unittest.TestCase):
    def tearDown(self):
        lab.HARNESS = lab.ROOT / 'src' / 'harness.c'
        lab.ABI_WRAP = lab.ROOT / 'src' / 'abi_wrap.s'

    def test_assert_measurable_requires_verified(self):
        with tempfile.TemporaryDirectory() as tmp:
            record, _, _ = _verified_record(Path(tmp))
            record['lifecycle'] = lab.LIFECYCLE_BUILT
            with self.assertRaises(RuntimeError) as ctx:
                lab.assert_measurable(record)
            self.assertIn('lifecycle is built', str(ctx.exception))

    def test_failed_cannot_measure(self):
        with tempfile.TemporaryDirectory() as tmp:
            record, _, _ = _verified_record(Path(tmp))
            record['lifecycle'] = lab.LIFECYCLE_FAILED
            with self.assertRaises(RuntimeError) as ctx:
                lab.assert_measurable(record)
            self.assertIn('failed', str(ctx.exception))

    def test_source_change_invalidates_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            record, source, _ = _verified_record(Path(tmp))
            lab.assert_measurable(record)
            source.write_text('changed\n')
            with self.assertRaises(RuntimeError) as ctx:
                lab.assert_measurable(record)
            self.assertIn('Source changed', str(ctx.exception))
            self.assertEqual(record['lifecycle'], lab.LIFECYCLE_STALE)
            self.assertEqual(record['verification']['state'], 'stale')
            # Stale PASS cannot be reused for timing.
            with self.assertRaises(RuntimeError):
                lab.assert_measurable(record)

    def test_persist_diagnostics(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            record, _, _ = _verified_record(tmp)
            lab.mark_failed(record, 'unit_test_failure', output='FAIL', run_dir=tmp)
            path = tmp / 'diagnostics_cand.json'
            self.assertTrue(path.is_file())
            text = path.read_text()
            self.assertIn('unit_test_failure', text)
            self.assertEqual(record['lifecycle'], lab.LIFECYCLE_FAILED)


if __name__ == '__main__':
    unittest.main()
