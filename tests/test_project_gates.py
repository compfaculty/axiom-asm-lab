import importlib.util
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('gates', Path(__file__).resolve().parents[1] / 'scripts/check_project.py')
gates = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gates)


class GateTests(unittest.TestCase):
    def test_done_without_evidence_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            errors = gates.validate(Path(directory), {'schema_version': 1, 'tasks': [
                {'id': 'A', 'state': 'done', 'depends_on': []}]})
            self.assertIn('A: missing evidence', errors)

    def test_done_before_dependency_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'report.md').write_text('Actual checks belong here.')
            errors = gates.validate(root, {'schema_version': 1, 'tasks': [
                {'id': 'A', 'state': 'pending', 'depends_on': []},
                {'id': 'B', 'state': 'done', 'depends_on': ['A'], 'evidence': 'report.md'}]})
            self.assertIn('B: dependency not done', errors)

    def test_blocker_required(self):
        with tempfile.TemporaryDirectory() as directory:
            errors = gates.validate(Path(directory), {'schema_version': 1, 'tasks': [
                {'id': 'A', 'state': 'blocked', 'depends_on': []}]})
            self.assertIn('A: blocked without reason', errors)
