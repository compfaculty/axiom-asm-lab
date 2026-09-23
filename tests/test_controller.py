import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import lab


class ControllerTests(unittest.TestCase):
    def test_reject_path_traversal(self):
        with self.assertRaises(ValueError):
            lab.sources('../escape')

    def test_builtins_exist(self):
        for path in lab.sources().values():
            self.assertTrue(path.is_file())


if __name__ == '__main__':
    unittest.main()
