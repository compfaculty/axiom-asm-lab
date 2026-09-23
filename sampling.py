"""Reproducible sampling: calibration helpers, paired schedules, memory caps."""
from __future__ import annotations

import os
import platform
import random
from typing import Dict, Iterable, List, Sequence

TARGET_SAMPLE_NS = 20_000_000  # 20 ms per sample (BENCHMARK_PROTOCOL)
MAX_CALIBRATE_ITERS = 50_000_000
DEFAULT_MEMORY_CAP_BYTES = 256 * 1024 * 1024  # 256 MiB


def array_bytes(n: int) -> int:
    return int(n) * 8


def enforce_memory_cap(n: int, cap_bytes: int = DEFAULT_MEMORY_CAP_BYTES) -> int:
    need = array_bytes(n)
    if need > cap_bytes:
        raise MemoryError(
            f'n={n} requires {need} bytes which exceeds memory cap {cap_bytes}')
    return need


def filter_sizes_for_cap(sizes: Sequence[int], cap_bytes: int) -> List[int]:
    allowed = []
    for n in sizes:
        try:
            enforce_memory_cap(n, cap_bytes)
            allowed.append(int(n))
        except MemoryError:
            continue
    return allowed


def cache_mode_label(n: int) -> str:
    """Coarse cache-resident vs DRAM label from logical footprint (not measured LLC)."""
    b = array_bytes(n)
    if n == 0 or b <= 32 * 1024:
        return 'cache_hot_l1'
    if b <= 256 * 1024:
        return 'cache_hot_l2'
    if b <= 12 * 1024 * 1024:
        return 'cache_warm_llc'
    return 'cache_cold_dram'


def paired_schedule(variants: Sequence[str], sizes: Sequence[int],
                    samples_per_size: int, seed: int) -> List[Dict]:
    """Randomize variant order within each (size, sample_index) pair; seed-reproducible."""
    rng = random.Random(seed)
    schedule: List[Dict] = []
    for n in sizes:
        for sample_index in range(samples_per_size):
            order = list(variants)
            rng.shuffle(order)
            for variant in order:
                schedule.append({
                    'size': int(n),
                    'sample_index': sample_index,
                    'variant': variant,
                })
    return schedule


def host_notes(extra: str | None = None) -> Dict:
    notes = {
        'platform': platform.platform(),
        'machine': platform.machine(),
        'processor': platform.processor(),
        'python': platform.python_version(),
        'env_AXIOM_HOST_NOTES': os.environ.get('AXIOM_HOST_NOTES'),
    }
    if extra:
        notes['cli_host_notes'] = extra
    return notes
