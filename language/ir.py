"""Typed semantic IR for the Axiom language sketch (pre-syntax)."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence, Union


class Ty(Enum):
    U64 = 'u64'
    U8 = 'u8'
    INDEX = 'index'  # usize-like index result
    UNIT = 'unit'
    ARR_U64 = 'arr_u64'
    ARR_U8 = 'arr_u8'


class Effect(Enum):
    PURE = 'pure'
    READ = 'read'  # reads borrowed array input
    WRITE = 'write'  # unsupported in v1 interpreter
    ALLOC = 'alloc'  # allocates owned output buffer
    UNSAFE_IO = 'unsafe_io'  # unsupported


class Ownership(Enum):
    BORROWED = 'borrowed'  # input not mutated
    OWNED = 'owned'  # callee produces owned value
    MOVED = 'moved'  # unsupported transfer


@dataclass(frozen=True)
class OpInfo:
    name: str
    result: Ty
    effects: frozenset
    ownership: Ownership
    wrapping: Optional[str] = None  # e.g. 'u64_mod_2_64'


OPS: Dict[str, OpInfo] = {
    'const_u64': OpInfo('const_u64', Ty.U64, frozenset({Effect.PURE}), Ownership.OWNED),
    'const_u8': OpInfo('const_u8', Ty.U8, frozenset({Effect.PURE}), Ownership.OWNED),
    'array_u64': OpInfo('array_u64', Ty.ARR_U64, frozenset({Effect.ALLOC}), Ownership.OWNED),
    'array_u8': OpInfo('array_u8', Ty.ARR_U8, frozenset({Effect.ALLOC}), Ownership.OWNED),
    'reduce_sum_u64_wrap': OpInfo(
        'reduce_sum_u64_wrap', Ty.U64, frozenset({Effect.READ}), Ownership.BORROWED,
        wrapping='u64_mod_2_64'),
    'find_u8': OpInfo(
        'find_u8', Ty.INDEX, frozenset({Effect.READ}), Ownership.BORROWED),
    'map_filter_even_shr1_u64': OpInfo(
        'map_filter_even_shr1_u64', Ty.ARR_U64,
        frozenset({Effect.READ, Effect.ALLOC}), Ownership.OWNED,
        wrapping='u64_mod_2_64'),
    # Unsupported placeholders for rejection tests:
    'store_global_u64': OpInfo(
        'store_global_u64', Ty.UNIT, frozenset({Effect.WRITE, Effect.UNSAFE_IO}),
        Ownership.MOVED),
}


@dataclass
class Expr:
    op: str
    args: List[Any] = field(default_factory=list)  # literals or Var names
    ty: Optional[Ty] = None


@dataclass
class Let:
    name: str
    expr: Expr


@dataclass
class Program:
    lets: List[Let]
    ret: str  # variable name
    name: str = 'main'


class IrError(ValueError):
    """Ill-typed or unsupported IR program."""


SUPPORTED_EFFECTS = frozenset({Effect.PURE, Effect.READ, Effect.ALLOC})


def typecheck(prog: Program) -> Program:
    env: Dict[str, Ty] = {}
    for let in prog.lets:
        if let.name in env:
            raise IrError(f'duplicate binding {let.name}')
        info = OPS.get(let.expr.op)
        if info is None:
            raise IrError(f'unknown op {let.expr.op}')
        unsupported = info.effects - SUPPORTED_EFFECTS
        if unsupported:
            raise IrError(
                f'unsupported effects for {let.expr.op}: '
                + ','.join(sorted(e.value for e in unsupported)))
        if info.ownership == Ownership.MOVED:
            raise IrError(f'unsupported ownership for {let.expr.op}: moved')
        _check_args(let.expr, info, env)
        let.expr.ty = info.result
        env[let.name] = info.result
    if prog.ret not in env:
        raise IrError(f'return refers to unbound name {prog.ret}')
    return prog


def _check_args(expr: Expr, info: OpInfo, env: Dict[str, Ty]) -> None:
    op = expr.op
    args = expr.args
    if op == 'const_u64':
        if len(args) != 1 or not isinstance(args[0], int):
            raise IrError('const_u64 expects one int literal')
    elif op == 'const_u8':
        if len(args) != 1 or not isinstance(args[0], int) or not 0 <= args[0] <= 255:
            raise IrError('const_u8 expects int 0..255')
    elif op == 'array_u64':
        if not isinstance(args, list) or not all(isinstance(x, int) for x in args):
            raise IrError('array_u64 expects int literals')
    elif op == 'array_u8':
        if not isinstance(args, list) or not all(isinstance(x, int) and 0 <= x <= 255 for x in args):
            raise IrError('array_u8 expects u8 literals')
    elif op == 'reduce_sum_u64_wrap':
        if len(args) != 1 or not isinstance(args[0], str) or env.get(args[0]) != Ty.ARR_U64:
            raise IrError('reduce_sum_u64_wrap expects arr_u64 variable')
    elif op == 'find_u8':
        if len(args) != 2:
            raise IrError('find_u8 expects (arr_u8_var, u8_var_or_lit)')
        if not isinstance(args[0], str) or env.get(args[0]) != Ty.ARR_U8:
            raise IrError('find_u8 first arg must be arr_u8')
        if isinstance(args[1], str):
            if env.get(args[1]) != Ty.U8:
                raise IrError('find_u8 needle var must be u8')
        elif not isinstance(args[1], int) or not 0 <= args[1] <= 255:
            raise IrError('find_u8 needle literal must be u8')
    elif op == 'map_filter_even_shr1_u64':
        if len(args) != 1 or not isinstance(args[0], str) or env.get(args[0]) != Ty.ARR_U64:
            raise IrError('map_filter_even_shr1_u64 expects arr_u64 variable')
    elif op == 'store_global_u64':
        raise IrError('store_global_u64 unsupported in v1')
    else:
        raise IrError(f'no argument rule for {op}')
