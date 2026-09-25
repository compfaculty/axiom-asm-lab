"""Compile lowered templates and compare native results to the IR interpreter."""
from __future__ import annotations

import ctypes
import json
import subprocess
import sys
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
        got = int(lib.find_u8(None, 0, needle))
        if got != 0:
            raise RuntimeError(f'find_u8 empty return size invalid: {got}')
        return got
    arr = (ctypes.c_uint8 * len(buf))(*buf)
    got = int(lib.find_u8(arr, len(buf), needle))
    if got > len(buf):
        raise RuntimeError(f'find_u8 return index {got} exceeds n={len(buf)}')
    return got


def _call_map_filter(lib: ctypes.CDLL, lowered: Lowered) -> List[int]:
    lib.map_filter_u64.argtypes = [
        ctypes.POINTER(ctypes.c_uint64), ctypes.c_size_t,
        ctypes.POINTER(ctypes.c_uint64)]
    lib.map_filter_u64.restype = ctypes.c_size_t
    vals = [v & MASK for v in lowered.array]
    out_buf = (ctypes.c_uint64 * max(len(vals), 1))()
    if not vals:
        n = int(lib.map_filter_u64(None, 0, out_buf))
        if n != 0:
            raise RuntimeError(f'map_filter empty return size invalid: {n}')
        return []
    inn = (ctypes.c_uint64 * len(vals))(*vals)
    n = int(lib.map_filter_u64(inn, len(vals), out_buf))
    if n < 0 or n > len(vals):
        raise RuntimeError(f'map_filter return size {n} exceeds input bound {len(vals)}')
    return [int(out_buf[i]) for i in range(n)]


def check_source_equiv(source: str, *, isolate: bool = True) -> Dict[str, Any]:
    """Parse source, compare interpreter vs native; used by tests and lab CLI.

    When isolate=True (default), native execution runs in a child Python process so a
    crashing template cannot corrupt the controller address space.
    """
    from .parser import parse
    prog = parse(source)
    want = interpret(prog)
    if isolate:
        got = _native_in_child(source)
    else:
        got = run_native(prog)
    kind = lower(prog).kind.value
    return {
        'ok': got == want,
        'program': prog.name,
        'kind': kind,
        'kernel_id': kind,
        'interpreter': want,
        'native': got,
        'isolated': isolate,
    }


def _native_in_child(source: str) -> Any:
    """Child-process native runner; keeps ctypes load out of the controller process."""
    with tempfile.TemporaryDirectory() as tmp:
        src_path = Path(tmp) / 'prog.ax'
        out_path = Path(tmp) / 'result.json'
        src_path.write_text(source)
        helper = Path(tmp) / 'runner.py'
        helper.write_text(
            'import json, sys\n'
            'from pathlib import Path\n'
            'sys.path.insert(0, sys.argv[1])\n'
            'from language.parser import parse\n'
            'from language.native import run_native\n'
            'src = Path(sys.argv[2]).read_text()\n'
            'got = run_native(parse(src))\n'
            'Path(sys.argv[3]).write_text(json.dumps(got) + "\\n")\n'
        )
        root = str(Path(__file__).resolve().parents[1])
        proc = subprocess.run(
            [sys.executable, str(helper), root, str(src_path), str(out_path)],
            capture_output=True, text=True)
        if proc.returncode != 0:
            raise RuntimeError(
                'isolated native runner failed: '
                + (proc.stderr or proc.stdout or str(proc.returncode)))
        return json.loads(out_path.read_text())


def disassemble_template(kind: KernelKind) -> str:
    from kernels.descriptors import get_descriptor
    from .lower import _TEMPLATES
    desc = get_descriptor(kind.value)
    template = Path(desc['asm_baseline'])
    if not template.is_file():
        template, _ = _TEMPLATES[kind]
    with tempfile.TemporaryDirectory() as tmp:
        obj = Path(tmp) / 't.o'
        subprocess.run(
            ['clang', '-c', str(template), '-o', str(obj)],
            check=True, capture_output=True, text=True)
        return subprocess.run(
            ['otool', '-tV', str(obj)],
            check=True, capture_output=True, text=True).stdout
