"""find_u8 kernel: first-index byte search with independent oracle."""
from __future__ import annotations

import hashlib
import random
from typing import List, Sequence, Tuple

CONTRACT = {
    'kernel_id': 'find_u8',
    'contract_version': 1,
    'element_type': 'u8',
    'result_type': 'usize_index_or_n',
    'semantics': 'return least i in [0,n) with a[i]==needle; else return n',
    'empty_null': {'n': 0, 'pointer': None, 'result': 0},
    'abi': 'size_t find_u8(const uint8_t *a, size_t n, uint8_t needle)',
}


def oracle(haystack: Sequence[int], needle: int) -> int:
    needle &= 0xFF
    for i, b in enumerate(haystack):
        if (int(b) & 0xFF) == needle:
            return i
    return len(haystack)


def wrong_find(haystack: Sequence[int], needle: int) -> int:
    """Intentional fault: returns last match index or n+1 style error."""
    needle &= 0xFF
    last = len(haystack)
    for i, b in enumerate(haystack):
        if (int(b) & 0xFF) == needle:
            last = i
    if last == len(haystack):
        return len(haystack) + 1
    return last


Case = Tuple[str, List[int], int]


def generate_cases(seed: int) -> List[Case]:
    rng = random.Random(seed)
    cases: List[Case] = [('empty', [], 0)]
    for n in (1, 2, 3, 4, 7, 8, 16, 64, 256):
        buf = [rng.randrange(256) for _ in range(n)]
        cases.append((f'random_n{n}_miss', buf, (max(buf) + 1) % 256 if buf else 0))
        needle = buf[n // 2]
        cases.append((f'random_n{n}_hit', buf, needle))
        # First-byte hit
        cases.append((f'first_n{n}', [needle] + [0xFF] * (n - 1), needle))
    return cases


def write_find_file(path, haystack, needle: int) -> None:
    from pathlib import Path
    path = Path(path)
    lines = [f'{len(haystack)} {int(needle) & 0xFF}']
    lines.extend(str(int(b) & 0xFF) for b in haystack)
    path.write_text('\n'.join(lines) + '\n')


def case_fingerprint(cases: Sequence[Case]) -> str:
    h = hashlib.sha256()
    for label, buf, needle in cases:
        h.update(label.encode())
        h.update(bytes(b & 0xFF for b in buf))
        h.update(bytes([needle & 0xFF]))
    return h.hexdigest()
