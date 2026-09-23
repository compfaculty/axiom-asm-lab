"""Minimal surface syntax parser → typed IR (T012).

Supported subset: language/SUBSET.md.
"""
from __future__ import annotations

import re
from typing import Any, List, Optional

from .ir import Expr, IrError, Let, Program, Ty, typecheck


class ParseError(ValueError):
    """Surface syntax error."""


_IDENT = re.compile(r'[A-Za-z_][A-Za-z0-9_]*')
_INT = re.compile(r'(?:0[xX][0-9A-Fa-f]+|\d+)')

_RET_TY = {
    'u64': Ty.U64,
    'u8': Ty.U8,
    'index': Ty.INDEX,
    'arr_u64': Ty.ARR_U64,
    'arr_u8': Ty.ARR_U8,
    'unit': Ty.UNIT,
}


class _Tok:
    __slots__ = ('kind', 'val', 'line')

    def __init__(self, kind: str, val: str, line: int):
        self.kind = kind
        self.val = val
        self.line = line


def _tokenize(src: str) -> List[_Tok]:
    lines = src.splitlines()
    out: List[_Tok] = []
    for li, line in enumerate(lines, 1):
        if '#' in line:
            line = line[: line.index('#')]
        i = 0
        while i < len(line):
            c = line[i]
            if c.isspace():
                i += 1
                continue
            if c == '=':
                out.append(_Tok('EQ', '=', li))
                i += 1
                continue
            if c in '()[],':
                out.append(_Tok(c, c, li))
                i += 1
                continue
            if c == '-' and i + 1 < len(line) and line[i + 1] == '>':
                out.append(_Tok('ARROW', '->', li))
                i += 2
                continue
            m = _IDENT.match(line, i)
            if m:
                word = m.group(0)
                if word in ('fn', 'let', 'return'):
                    out.append(_Tok(word.upper(), word, li))
                else:
                    out.append(_Tok('IDENT', word, li))
                i = m.end()
                continue
            m = _INT.match(line, i)
            if m:
                out.append(_Tok('INT', m.group(0), li))
                i = m.end()
                continue
            raise ParseError(f'line {li}: unexpected character {c!r}')
    out.append(_Tok('EOF', '', len(lines) or 1))
    return out


def _parse_int(tok: _Tok) -> int:
    v = tok.val
    if v.lower().startswith('0x'):
        return int(v, 16)
    return int(v, 10)


class _P:
    def __init__(self, toks: List[_Tok]):
        self.toks = toks
        self.i = 0

    def peek(self) -> _Tok:
        return self.toks[self.i]

    def take(self, kind: Optional[str] = None) -> _Tok:
        t = self.peek()
        if kind is not None and t.kind != kind:
            raise ParseError(f'line {t.line}: expected {kind}, got {t.kind} ({t.val!r})')
        self.i += 1
        return t

    def parse_program(self) -> tuple[Program, Optional[str]]:
        declared: Optional[str] = None
        if self.peek().kind == 'FN':
            self.take('FN')
            name = self.take('IDENT').val
            self.take('(')
            self.take(')')
            self.take('ARROW')
            declared = self.take('IDENT').val
            prog = self._parse_body(name=name)
            return prog, declared
        return self._parse_body(name='main'), None

    def _parse_body(self, name: str) -> Program:
        lets: List[Let] = []
        while self.peek().kind == 'LET':
            self.take('LET')
            bind = self.take('IDENT').val
            self.take('EQ')
            expr = self._parse_expr()
            lets.append(Let(bind, expr))
        self.take('RETURN')
        ret = self.take('IDENT').val
        return Program(lets=lets, ret=ret, name=name)

    def _parse_expr(self) -> Expr:
        op = self.take('IDENT').val
        self.take('(')
        args: List[Any] = []
        if self.peek().kind != ')':
            args.append(self._parse_arg())
            while self.peek().kind == ',':
                self.take(',')
                args.append(self._parse_arg())
        self.take(')')
        return Expr(op, args)

    def _parse_arg(self) -> Any:
        t = self.peek()
        if t.kind == 'INT':
            self.take('INT')
            return _parse_int(t)
        if t.kind == 'IDENT':
            self.take('IDENT')
            return t.val
        raise ParseError(f'line {t.line}: expected argument, got {t.kind}')


def parse(source: str) -> Program:
    """Parse source into a typechecked IR Program."""
    toks = _tokenize(source)
    p = _P(toks)
    prog, declared = p.parse_program()
    if p.peek().kind != 'EOF':
        t = p.peek()
        raise ParseError(f'line {t.line}: trailing tokens starting at {t.val!r}')
    prog = typecheck(prog)
    if declared is not None:
        if declared not in _RET_TY:
            raise ParseError(f'unknown return type {declared!r}')
        env = {let.name: let.expr.ty for let in prog.lets}
        got = env.get(prog.ret)
        if got != _RET_TY[declared]:
            raise IrError(
                f'return type annotation {declared} does not match '
                f'{got.value if got else None}')
    return prog
