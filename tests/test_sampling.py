import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sampling import (
    DEFAULT_MEMORY_CAP_BYTES,
    array_bytes,
    cache_mode_label,
    enforce_memory_cap,
    filter_sizes_for_cap,
    paired_schedule,
)


class SamplingTests(unittest.TestCase):
    def test_memory_cap_enforced(self):
        enforce_memory_cap(1024, cap_bytes=1024 * 8)
        with self.assertRaises(MemoryError):
            enforce_memory_cap(1025, cap_bytes=1024 * 8)

    def test_filter_sizes(self):
        sizes = (0, 1, 1024, 10**9)
        # 1e9 * 8 exceeds default cap
        allowed = filter_sizes_for_cap(sizes, DEFAULT_MEMORY_CAP_BYTES)
        self.assertIn(0, allowed)
        self.assertIn(1024, allowed)
        self.assertNotIn(10**9, allowed)

    def test_cache_mode_labels(self):
        self.assertEqual(cache_mode_label(0), 'cache_hot_l1')
        self.assertEqual(cache_mode_label(16), 'cache_hot_l1')  # 128 B
        self.assertTrue(cache_mode_label(1048576).startswith('cache_'))

    def test_paired_schedule_reproducible(self):
        a = paired_schedule(['clang_o3', 'scalar', 'unrolled4'], [4, 16], 5, seed=7)
        b = paired_schedule(['clang_o3', 'scalar', 'unrolled4'], [4, 16], 5, seed=7)
        c = paired_schedule(['clang_o3', 'scalar', 'unrolled4'], [4, 16], 5, seed=8)
        self.assertEqual(a, b)
        self.assertNotEqual(a, c)
        self.assertEqual(len(a), 2 * 5 * 3)
        # Within one sample slot, all variants appear once.
        first = [s['variant'] for s in a if s['size'] == 4 and s['sample_index'] == 0]
        self.assertEqual(sorted(first), ['clang_o3', 'scalar', 'unrolled4'])

    def test_array_bytes(self):
        self.assertEqual(array_bytes(10), 80)


if __name__ == '__main__':
    unittest.main()
