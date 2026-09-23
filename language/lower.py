"""Lower typed IR programs onto verified assembly templates (T012)."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import List, Optional

from .ir import Program, typecheck


TEMPLATE_DIR = Path(__file__).resolve().parent / 'templates'


class CoverageError(ValueError):
    """Program is outside the explicitly supported lowering subset."""


class KernelKind(Enum):
    SUM_U64 = 'sum_u64'
    FIND_U8 = 'find_u8'
    MAP_FILTER_U64 = 'map_filter_u64'


@dataclass(frozen=True)
class Lowered:
    kind: KernelKind
    template: Path
    symbol: str
    array: List[int]
    needle: Optional[int] = None


_TEMPLATES = {
    KernelKind.SUM_U64: (TEMPLATE_DIR / 'sum_u64.s', 'sum_array'),
    KernelKind.FIND_U8: (TEMPLATE_DIR / 'find_u8.s', 'find_u8'),
    KernelKind.MAP_FILTER_U64: (TEMPLATE_DIR / 'map_filter_u64.s', 'map_filter_u64'),
}


def classify(prog: Program) -> KernelKind:
    """Match IR shape to a catalog kernel; raise CoverageError otherwise."""
    prog = typecheck(prog)
    ops = [let.expr.op for let in prog.lets]
    if ops == ['array_u64', 'reduce_sum_u64_wrap']:
        a, r = prog.lets
        if r.expr.args == [a.name] and prog.ret == r.name:
            return KernelKind.SUM_U64
    if ops == ['array_u8', 'const_u8', 'find_u8']:
        a, n, f = prog.lets
        if f.expr.args == [a.name, n.name] and prog.ret == f.name:
            return KernelKind.FIND_U8
    if ops == ['array_u8', 'find_u8']:
        a, f = prog.lets
        if (len(f.expr.args) == 2 and f.expr.args[0] == a.name
                and isinstance(f.expr.args[1], int) and prog.ret == f.name):
            return KernelKind.FIND_U8
    if ops == ['array_u64', 'map_filter_even_shr1_u64']:
        a, m = prog.lets
        if m.expr.args == [a.name] and prog.ret == m.name:
            return KernelKind.MAP_FILTER_U64
    raise CoverageError(
        'unsupported program shape for native lowering; '
        'v1 covers sum/find/map_filter templates only')


def lower(prog: Program) -> Lowered:
    prog = typecheck(prog)
    kind = classify(prog)
    template, symbol = _TEMPLATES[kind]
    if not template.is_file():
        raise FileNotFoundError(template)
    array, needle = _extract_inputs(prog, kind)
    return Lowered(kind=kind, template=template, symbol=symbol, array=array, needle=needle)


def _extract_inputs(prog: Program, kind: KernelKind):
    if kind == KernelKind.SUM_U64:
        return list(prog.lets[0].expr.args), None
    if kind == KernelKind.MAP_FILTER_U64:
        return list(prog.lets[0].expr.args), None
    if kind == KernelKind.FIND_U8:
        arr = list(prog.lets[0].expr.args)
        if len(prog.lets) == 3:
            needle = int(prog.lets[1].expr.args[0])
        else:
            needle = int(prog.lets[1].expr.args[1])
        return arr, needle
    raise CoverageError(f'no input extraction for {kind}')


def emit_asm(prog: Program, dest: Path) -> Lowered:
    """Copy the selected catalog template to dest."""
    lowered = lower(prog)
    dest.write_bytes(lowered.template.read_bytes())
    return lowered
