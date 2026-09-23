import json
import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import lab


class ControllerTests(unittest.TestCase):
    def test_reject_path_traversal(self):
        with self.assertRaises(ValueError):
            lab.sources('../escape')

    def test_reject_malformed_candidate_name(self):
        with self.assertRaises(ValueError):
            lab.sources('bad name')
        with self.assertRaises(ValueError):
            lab.sources('has/slash')

    def test_reject_builtin_collision(self):
        for name in ('clang_o3', 'scalar', 'unrolled4'):
            with self.assertRaises(ValueError) as ctx:
                lab.sources(name)
            self.assertIn('collides with built-in', str(ctx.exception))

    def test_missing_candidate_file(self):
        with self.assertRaises(FileNotFoundError):
            lab.sources('does_not_exist_candidate')

    def test_builtins_exist(self):
        for path in lab.sources().values():
            self.assertTrue(path.is_file())

    def test_unique_run_dirs(self):
        a_id, a_path = lab.new_run_dir()
        b_id, b_path = lab.new_run_dir()
        self.assertNotEqual(a_id, b_id)
        self.assertNotEqual(a_path, b_path)
        self.assertTrue(a_path.is_dir())
        self.assertTrue(b_path.is_dir())
        self.assertTrue((a_path.parent / a_id).samefile(a_path))

    def test_refuse_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'artifact.json'
            path.write_text('x\n')
            with self.assertRaises(FileExistsError):
                lab.refuse_overwrite(path)

    def test_ensure_fresh_invalidates_source_edit(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            source = tmp / 'cand.s'
            source.write_text('nop\n')
            binary = tmp / 'binary'
            binary.write_bytes(b'fixture')
            record = {
                'name': 'cand',
                'source_path': str(source),
                'binary_path': str(binary),
                'binary_sha256': lab.sha256_file(binary),
                'source_sha256': lab.sha256_file(source),
                'harness_sha256': lab.sha256_file(lab.HARNESS),
                'verification': {'state': 'built', 'output': None},
            }
            lab.ensure_fresh(record)
            source.write_text('changed\n')
            with self.assertRaises(RuntimeError) as ctx:
                lab.ensure_fresh(record)
            self.assertIn('Source changed', str(ctx.exception))
            self.assertEqual(record['verification']['state'], 'stale')

    def test_ensure_fresh_invalidates_harness_edit(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            source = tmp / 'cand.s'
            source.write_text('nop\n')
            binary = tmp / 'binary'
            binary.write_bytes(b'fixture')
            # Point record at a copy of the harness so we can edit it safely.
            harness_copy = tmp / 'harness.c'
            harness_copy.write_bytes(lab.HARNESS.read_bytes())
            original = lab.HARNESS
            try:
                lab.HARNESS = harness_copy
                record = {
                    'name': 'cand',
                    'source_path': str(source),
                'binary_path': str(binary),
                'binary_sha256': lab.sha256_file(binary),
                    'source_sha256': lab.sha256_file(source),
                    'harness_sha256': lab.sha256_file(harness_copy),
                    'verification': {'state': 'pass',
                                     'binary_sha256_at_verify': lab.sha256_file(binary),
                                     'source_sha256_at_verify': lab.sha256_file(source),
                                     'harness_sha256_at_verify': lab.sha256_file(harness_copy)},
                }
                lab.ensure_fresh(record)
                harness_copy.write_text(harness_copy.read_text() + '\n/* edit */\n')
                with self.assertRaises(RuntimeError) as ctx:
                    lab.ensure_fresh(record)
                self.assertIn('Harness changed', str(ctx.exception))
                self.assertEqual(record['verification']['state'], 'stale')
            finally:
                lab.HARNESS = original


if __name__ == '__main__':
    unittest.main()
