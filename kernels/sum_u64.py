"""sum_u64 kernel contract, independent wrapping oracle, and seeded case generators."""
from __future__ import annotations

import hashlib
import random
from typing import Iterable, List, Sequence, Tuple

MASK = (1 << 64) - 1

# Lengths around scalar/unroll/vector-ish boundaries (unrolled4 uses groups of 4).
BOUNDARY_LENGTHS: Tuple[int, ...] = (
    0, 1, 2, 3, 4, 5, 7, 8, 15, 16, 31, 32, 63, 64, 127, 128, 255, 256, 1024, 4096,
)

CONTRACT = {
    'kernel_id': 'sum_u64',
    'contract_version': 1,
    'element_type': 'u64',
    'result_type': 'u64',
    'overflow': 'wrap_mod_2_64',
    'empty_null': {
        'n': 0,
        'pointer': None,
        'result': 0,
        'note': 'n==0 must return 0 without accessing memory',
    },
    'abi': 'AAPCS64 sum_array(const uint64_t *a, size_t n) -> uint64_t in x0',
    'boundary_lengths': list(BOUNDARY_LENGTHS),
}


def oracle(values: Sequence[int]) -> int:
    """Independent wrapping sum; must not share code with the native harness oracle."""
    total = 0
    for raw in values:
        total = (total + (int(raw) & MASK)) & MASK
    return total


def wrong_sum(values: Sequence[int]) -> int:
    """Intentional incorrect reduction used to prove the evaluator can reject faults."""
    return (oracle(values) + 1) & MASK


Case = Tuple[str, List[int]]


def _pattern(name: str, n: int, seed: int) -> List[int]:
    if n == 0:
        return []
    rng = random.Random((seed ^ hashlib.sha256(name.encode()).digest()[0]) & 0xFFFFFFFF)
    if name == 'zeros':
        return [0] * n
    if name == 'ones':
        return [1] * n
    if name == 'max':
        return [MASK] * n
    if name == 'alternating':
        return [MASK if (i % 2) == 0 else 0 for i in range(n)]
    if name == 'overflow_edges':
        edges = [MASK, 1, MASK, MASK, 4, 0, 1]
        return [edges[i % len(edges)] for i in range(n)]
    if name == 'random':
        return [rng.getrandbits(64) for _ in range(n)]
    raise ValueError('unknown pattern: ' + name)


def generate_cases(seed: int) -> List[Case]:
    """Deterministic labeled vectors covering distributions and boundary lengths."""
    cases: List[Case] = [('empty_null', [])]
    patterns = ('zeros', 'ones', 'max', 'alternating', 'overflow_edges', 'random')
    for n in BOUNDARY_LENGTHS:
        if n == 0:
            continue
        for pattern in patterns:
            label = f'{pattern}_n{n}'
            cases.append((label, _pattern(pattern, n, seed)))
    return cases


def case_fingerprint(cases: Iterable[Case]) -> str:
    h = hashlib.sha256()
    for label, values in cases:
        h.update(label.encode())
        h.update(b'\0')
        for v in values:
            h.update((v & MASK).to_bytes(8, 'little'))
        h.update(b'\n')
    return h.hexdigest()


def write_sum_file(path, values: Sequence[int]) -> None:
    lines = [str(len(values))] + [str(int(v) & MASK) for v in values]
    path.write_text('\n'.join(lines) + '\n')
