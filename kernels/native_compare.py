"""Native C reference checks vs Python oracles for the kernel portfolio."""
from __future__ import annotations

import ctypes
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, List

from kernels import find_u8, map_filter_u64, sum_u64


def _compile_shared(src: Path, out: Path) -> None:
    subprocess.run(
        ['clang', '-O3', '-std=c11', '-shared', '-fPIC', str(src), '-o', str(out)],
        check=True, capture_output=True, text=True)


def compare_find_u8(root: Path, seed: int = 1) -> Dict[str, Any]:
    with tempfile.TemporaryDirectory() as tmp:
        lib_path = Path(tmp) / 'libfind.dylib'
        _compile_shared(root / 'src' / 'find_u8_ref.c', lib_path)
        lib = ctypes.CDLL(str(lib_path))
        lib.find_u8.argtypes = [ctypes.POINTER(ctypes.c_uint8), ctypes.c_size_t, ctypes.c_uint8]
        lib.find_u8.restype = ctypes.c_size_t
        mismatches = []
        for label, buf, needle in find_u8.generate_cases(seed):
            want = find_u8.oracle(buf, needle)
            if not buf:
                got = lib.find_u8(None, 0, needle)
            else:
                arr = (ctypes.c_uint8 * len(buf))(*[b & 0xFF for b in buf])
                got = lib.find_u8(arr, len(buf), needle & 0xFF)
            if got != want:
                mismatches.append({'label': label, 'got': got, 'want': want})
                break
        return {
            'kernel_id': 'find_u8',
            'baseline': 'clang_o3_ref',
            'candidate': 'python_oracle',
            'ok': not mismatches,
            'mismatches': mismatches,
            'observation': 'C reference matched Python oracle on generated cases'
            if not mismatches else 'C reference diverged from oracle',
            'inference': 'Match supports shared contract interpretation; not a speed claim.',
        }


def compare_map_filter(root: Path, seed: int = 1) -> Dict[str, Any]:
    with tempfile.TemporaryDirectory() as tmp:
        lib_path = Path(tmp) / 'libmf.dylib'
        _compile_shared(root / 'src' / 'map_filter_u64_ref.c', lib_path)
        lib = ctypes.CDLL(str(lib_path))
        lib.map_filter_u64.argtypes = [
            ctypes.POINTER(ctypes.c_uint64), ctypes.c_size_t,
            ctypes.POINTER(ctypes.c_uint64)]
        lib.map_filter_u64.restype = ctypes.c_size_t
        mismatches = []
        for label, vals in map_filter_u64.generate_cases(seed):
            want = map_filter_u64.oracle(vals)
            out_buf = (ctypes.c_uint64 * max(len(vals), 1))()
            if not vals:
                got_n = lib.map_filter_u64(None, 0, out_buf)
                got = []
            else:
                inn = (ctypes.c_uint64 * len(vals))(*[v & ((1 << 64) - 1) for v in vals])
                got_n = lib.map_filter_u64(inn, len(vals), out_buf)
                got = [int(out_buf[i]) for i in range(got_n)]
            if got != want:
                mismatches.append({'label': label, 'got': got, 'want': want})
                break
        return {
            'kernel_id': 'map_filter_u64',
            'baseline': 'clang_o3_ref',
            'candidate': 'python_oracle',
            'ok': not mismatches,
            'mismatches': mismatches,
            'observation': 'C reference matched Python oracle on generated cases'
            if not mismatches else 'C reference diverged from oracle',
            'inference': 'Stable filter/map contract holds for this baseline; no speedup claimed.',
        }


def compare_sum_builtin_note() -> Dict[str, Any]:
    return {
        'kernel_id': 'sum_u64',
        'baseline': 'clang_o3',
        'candidate': 'scalar/unrolled4',
        'ok': True,
        'observation': 'Existing lab verify/oracle_check already diffs builtins against sum_u64 oracle.',
        'inference': 'Reuse T003 evidence; portfolio adds sibling kernels rather than re-proving sum.',
        'speedup_required': False,
    }


def run_native_comparisons(root: Path, seed: int = 1) -> Dict[str, Any]:
    comps = [
        compare_sum_builtin_note(),
        compare_find_u8(root, seed),
        compare_map_filter(root, seed),
    ]
    return {
        'comparisons': comps,
        'all_ok': all(c['ok'] for c in comps),
        'mandatory_speedup': False,
    }
