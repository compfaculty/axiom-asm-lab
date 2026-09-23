import signal
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import lab


class FaultClassifyTests(unittest.TestCase):
    def test_pass(self):
        self.assertEqual(lab.classify_child(0, 'PASS\n', ''), 'pass')

    def test_abi_fail(self):
        self.assertEqual(lab.classify_child(3, '', 'ABI_FAIL n=4\n'), 'abi_fail')

    def test_verification_failed(self):
        self.assertEqual(lab.classify_child(1, '', 'FAIL empty\n'), 'verification_failed')

    def test_memory_fault_signal(self):
        self.assertEqual(lab.classify_child(-signal.SIGSEGV, '', ''), 'memory_fault')
        self.assertEqual(lab.classify_child(-signal.SIGBUS, '', ''), 'memory_fault')

    def test_trap_signal(self):
        self.assertEqual(lab.classify_child(-signal.SIGTRAP, '', ''), 'trap')
        self.assertEqual(lab.classify_child(-signal.SIGILL, '', ''), 'trap')

    def test_timeout(self):
        self.assertEqual(lab.classify_child(None, '', '', timed_out=True), 'timed_out')

    def test_fault_matrix_keys(self):
        for name in ('overread', 'underread', 'input_write', 'abi_corrupt', 'trap',
                     'infinite_loop', 'scalar'):
            self.assertIn(name, lab.FAULT_MATRIX)


if __name__ == '__main__':
    unittest.main()
