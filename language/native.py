"""Compile lowered templates and compare native results to the IR interpreter."""
from __future__ import annotations

import ctypes
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, List

from .interpreter import interpret
from .ir import Program
from .lower import KernelKind, Lowered, lower


MASK = (1 << 64) - 1


def _compile_shared(asm: Path, out: Path) -> None:
    subprocess.run(
        ['clang', '-O0', '-shared', '-fPIC', str(asm), '-o', str(out)],
        check=True, capture_output=True, text=True)


def run_native(prog: Program) -> Any:
    """Execute the lowered template natively; return Python value matching interpret()."""
    lowered = lower(prog)
    with tempfile.TemporaryDirectory() as tmp:
        lib_path = Path(tmp) / 'libkern.dylib'
        _compile_shared(lowered.template, lib_path)
        lib = ctypes.CDLL(str(lib_path))
        if lowered.kind == KernelKind.SUM_U64:
            return _call_sum(lib, lowered)
        if lowered.kind == KernelKind.FIND_U8:
            return _call_find(lib, lowered)
        if lowered.kind == KernelKind.MAP_FILTER_U64:
            return _call_map_filter(lib, lowered)
        raise RuntimeError(f'unhandled kind {lowered.kind}')


def _call_sum(lib: ctypes.CDLL, lowered: Lowered) -> int:
    lib.sum_array.argtypes = [ctypes.POINTER(ctypes.c_uint64), ctypes.c_size_t]
    lib.sum_array.restype = ctypes.c_uint64
    vals = [v & MASK for v in lowered.array]
    if not vals:
        return int(lib.sum_array(None, 0))
    arr = (ctypes.c_uint64 * len(vals))(*vals)
    return int(lib.sum_array(arr, len(vals)))


def _call_find(lib: ctypes.CDLL, lowered: Lowered) -> int:
    lib.find_u8.argtypes = [
        ctypes.POINTER(ctypes.c_uint8), ctypes.c_size_t, ctypes.c_uint8]
    lib.find_u8.restype = ctypes.c_size_t
    needle = int(lowered.needle) & 0xFF
    buf = [b & 0xFF for b in lowered.array]
    if not buf:
        return int(lib.find_u8(None, 0, needle))
    arr = (ctypes.c_uint8 * len(buf))(*buf)
    return int(lib.find_u8(arr, len(buf), needle))


def _call_map_filter(lib: ctypes.CDLL, lowered: Lowered) -> List[int]:
    lib.map_filter_u64.argtypes = [
        ctypes.POINTER(ctypes.c_uint64), ctypes.c_size_t,
        ctypes.POINTER(ctypes.c_uint64)]
    lib.map_filter_u64.restype = ctypes.c_size_t
    vals = [v & MASK for v in lowered.array]
    out_buf = (ctypes.c_uint64 * max(len(vals), 1))()
    if not vals:
        n = lib.map_filter_u64(None, 0, out_buf)
        return []
    inn = (ctypes.c_uint64 * len(vals))(*vals)
    n = lib.map_filter_u64(inn, len(vals), out_buf)
    return [int(out_buf[i]) for i in range(n)]


def check_source_equiv(source: str) -> Dict[str, Any]:
    """Parse source, compare interpreter vs native; used by tests and lab CLI."""
    from .parser import parse
    prog = parse(source)
    want = interpret(prog)
    got = run_native(prog)
    return {
        'ok': got == want,
        'program': prog.name,
        'kind': lower(prog).kind.value,
        'interpreter': want,
        'native': got,
    }


def disassemble_template(kind: KernelKind) -> str:
    from .lower import _TEMPLATES
    template, _ = _TEMPLATES[kind]
    return subprocess.run(
        ['otool', '-tV', str(template)],
        check=True, capture_output=True, text=True).stdout
