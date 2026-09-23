"""Reference interpreter for typed IR (oracle for lowering)."""
from __future__ import annotations

from typing import Any, Dict, List

from kernels import find_u8 as find_k
from kernels import map_filter_u64 as mf_k
from kernels import sum_u64 as sum_k

from .ir import Effect, Expr, IrError, Program, Ty, typecheck


MASK = (1 << 64) - 1


def interpret(prog: Program) -> Any:
    prog = typecheck(prog)
    env: Dict[str, Any] = {}
    for let in prog.lets:
        env[let.name] = _eval(let.expr, env)
    return env[prog.ret]


def _eval(expr: Expr, env: Dict[str, Any]) -> Any:
    op = expr.op
    args = expr.args
    if op == 'const_u64':
        return int(args[0]) & MASK
    if op == 'const_u8':
        return int(args[0]) & 0xFF
    if op == 'array_u64':
        return [int(x) & MASK for x in args]
    if op == 'array_u8':
        return [int(x) & 0xFF for x in args]
    if op == 'reduce_sum_u64_wrap':
        arr = env[args[0]]
        return sum_k.oracle(arr)
    if op == 'find_u8':
        arr = env[args[0]]
        needle = env[args[1]] if isinstance(args[1], str) else int(args[1]) & 0xFF
        return find_k.oracle(arr, needle)
    if op == 'map_filter_even_shr1_u64':
        arr = env[args[0]]
        return mf_k.oracle(arr)
    raise IrError(f'cannot evaluate op {op}')


def program_sum(values: List[int]) -> Program:
    from .ir import Let
    return Program(
        name='sum_example',
        lets=[
            Let('a', Expr('array_u64', list(values))),
            Let('s', Expr('reduce_sum_u64_wrap', ['a'])),
        ],
        ret='s',
    )


def program_find(buf: List[int], needle: int) -> Program:
    from .ir import Let
    return Program(
        name='find_example',
        lets=[
            Let('a', Expr('array_u8', list(buf))),
            Let('n', Expr('const_u8', [needle])),
            Let('i', Expr('find_u8', ['a', 'n'])),
        ],
        ret='i',
    )


def program_map_filter(values: List[int]) -> Program:
    from .ir import Let
    return Program(
        name='map_filter_example',
        lets=[
            Let('a', Expr('array_u64', list(values))),
            Let('b', Expr('map_filter_even_shr1_u64', ['a'])),
        ],
        ret='b',
    )
