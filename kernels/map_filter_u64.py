"""map_filter_u64: stable filter of even values, map x -> x>>1 (wrapping)."""
from __future__ import annotations

import hashlib
import random
from typing import List, Sequence, Tuple

MASK = (1 << 64) - 1

CONTRACT = {
    'kernel_id': 'map_filter_u64',
    'contract_version': 1,
    'element_type': 'u64',
    'result_type': 'u64_compact',
    'semantics': (
        'Stable compact: for each x in order, if (x&1)==0 append (x>>1) & MASK. '
        'Return output length. Preserves relative order.'
    ),
    'empty_null': {'n': 0, 'pointer': None, 'out_len': 0},
    'abi': 'size_t map_filter_u64(const uint64_t *in, size_t n, uint64_t *out)',
}


def oracle(values: Sequence[int]) -> List[int]:
    out: List[int] = []
    for raw in values:
        x = int(raw) & MASK
        if (x & 1) == 0:
            out.append((x >> 1) & MASK)
    return out


def wrong_map_filter(values: Sequence[int]) -> List[int]:
    """Intentional fault: unstable / drops order by reversing kept items."""
    return list(reversed(oracle(values)))


Case = Tuple[str, List[int]]


def generate_cases(seed: int) -> List[Case]:
    rng = random.Random(seed ^ 0xC0FFEE)
    cases: List[Case] = [('empty', [])]
    for n in (1, 2, 3, 4, 7, 8, 16, 64, 256):
        cases.append((f'all_odd_n{n}', [1 + 2 * i for i in range(n)]))
        cases.append((f'all_even_n{n}', [2 * i for i in range(n)]))
        cases.append((f'mixed_n{n}', [rng.getrandbits(64) for _ in range(n)]))
        cases.append((f'alternating_n{n}', [0 if i % 2 == 0 else MASK for i in range(n)]))
    return cases


def write_map_filter_file(path, values) -> None:
    from pathlib import Path
    path = Path(path)
    lines = [str(len(values))]
    lines.extend(str(int(v) & MASK) for v in values)
    path.write_text('\n'.join(lines) + '\n')


def case_fingerprint(cases: Sequence[Case]) -> str:
    h = hashlib.sha256()
    for label, values in cases:
        h.update(label.encode())
        for v in values:
            h.update((int(v) & MASK).to_bytes(8, 'little'))
    return h.hexdigest()
