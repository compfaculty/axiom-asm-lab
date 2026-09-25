"""Per-kernel evaluation descriptors for the shared verify/measure pipeline."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from . import find_u8, map_filter_u64, sum_u64

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_KERNEL = 'sum_u64'

# Sizes used for paired measurement when kernel-specific lists are not required.
COMMON_PROTOCOL_SIZES = (0, 1, 3, 4, 7, 16, 64, 1024, 65536, 1048576)
FIND_PROTOCOL_SIZES = (0, 1, 3, 4, 7, 16, 64, 1024, 65536, 1048576)
# map_filter allocates in+out; keep large sizes but memory cap still applies.
MAP_PROTOCOL_SIZES = (0, 1, 3, 4, 7, 16, 64, 1024, 65536, 1048576)


def _element_bytes(kernel_id: str) -> int:
    if kernel_id == 'find_u8':
        return 1
    return 8


Descriptor = Dict[str, Any]


def get_descriptor(kernel_id: str) -> Descriptor:
    try:
        return DESCRIPTORS[kernel_id]
    except KeyError as exc:
        raise KeyError(f'unknown kernel_id: {kernel_id}') from exc


def list_descriptor_ids() -> List[str]:
    return sorted(DESCRIPTORS)


DESCRIPTORS: Dict[str, Descriptor] = {
    'sum_u64': {
        'kernel_id': 'sum_u64',
        'symbol': 'sum_array',
        'asm_symbol': '_sum_array',
        'module': sum_u64,
        'contract': sum_u64.CONTRACT,
        'harness': ROOT / 'src' / 'harness.c',
        'abi_wrap': ROOT / 'src' / 'abi_wrap.s',
        'baseline_id': 'clang_o3',
        'baseline_source': ROOT / 'src' / 'reference.c',
        'asm_baseline': ROOT / 'asm' / 'scalar.s',
        'wrong_candidate': ROOT / 'candidates' / 'wrong_sum.s',
        'oracle_cmd': 'sum-file',
        'protocol_sizes': COMMON_PROTOCOL_SIZES,
        'element_bytes': 8,
        'write_case_file': lambda path, case: sum_u64.write_sum_file(path, case[1]),
        'run_oracle_cases': None,  # filled below after helpers exist
    },
    'find_u8': {
        'kernel_id': 'find_u8',
        'symbol': 'find_u8',
        'asm_symbol': '_find_u8',
        'module': find_u8,
        'contract': find_u8.CONTRACT,
        'harness': ROOT / 'src' / 'harness_find.c',
        'abi_wrap': ROOT / 'src' / 'abi_wrap_find.s',
        'baseline_id': 'find_u8_ref',
        'baseline_source': ROOT / 'src' / 'find_u8_ref.c',
        'asm_baseline': ROOT / 'asm' / 'find_u8.s',
        'wrong_candidate': ROOT / 'candidates' / 'wrong_find.s',
        'oracle_cmd': 'find-file',
        'protocol_sizes': FIND_PROTOCOL_SIZES,
        'element_bytes': 1,
    },
    'map_filter_u64': {
        'kernel_id': 'map_filter_u64',
        'symbol': 'map_filter_u64',
        'asm_symbol': '_map_filter_u64',
        'module': map_filter_u64,
        'contract': map_filter_u64.CONTRACT,
        'harness': ROOT / 'src' / 'harness_map_filter.c',
        'abi_wrap': ROOT / 'src' / 'abi_wrap_map_filter.s',
        'baseline_id': 'map_filter_u64_ref',
        'baseline_source': ROOT / 'src' / 'map_filter_u64_ref.c',
        'asm_baseline': ROOT / 'asm' / 'map_filter_u64.s',
        'wrong_candidate': ROOT / 'candidates' / 'wrong_map_filter.s',
        'oracle_cmd': 'map-filter-file',
        'protocol_sizes': MAP_PROTOCOL_SIZES,
        'element_bytes': 8,
    },
}


def write_find_file(path: Path, haystack: Sequence[int], needle: int) -> None:
    path = Path(path)
    lines = [f'{len(haystack)} {int(needle) & 0xFF}']
    lines.extend(str(int(b) & 0xFF) for b in haystack)
    path.write_text('\n'.join(lines) + '\n')


def write_map_filter_file(path: Path, values: Sequence[int]) -> None:
    path = Path(path)
    lines = [str(len(values))]
    lines.extend(str(int(v) & ((1 << 64) - 1)) for v in values)
    path.write_text('\n'.join(lines) + '\n')


def parse_map_filter_output(text: str) -> List[int]:
    lines = [ln.strip() for ln in text.strip().splitlines() if ln.strip()]
    if not lines:
        raise ValueError('empty map-filter output')
    n = int(lines[0])
    vals = [int(x) for x in lines[1:]]
    if len(vals) != n:
        raise ValueError(f'map-filter length mismatch: header={n} values={len(vals)}')
    return vals


def array_bytes_for_kernel(kernel_id: str, n: int) -> int:
    desc = get_descriptor(kernel_id)
    # map_filter needs in+out scratch ≈ 2x.
    mult = 2 if kernel_id == 'map_filter_u64' else 1
    return int(n) * int(desc['element_bytes']) * mult


def sanitize_evidence_summary(report: Dict[str, Any]) -> Dict[str, Any]:
    """Compact summary + hash pointers; omits raw sample arrays."""
    import hashlib
    import json
    raw = json.dumps(report, sort_keys=True, default=str).encode()
    variants = {}
    for name, var in (report.get('variants') or {}).items():
        variants[name] = {
            'lifecycle': var.get('lifecycle'),
            'source_sha256': var.get('source_sha256'),
            'binary_sha256': var.get('binary_sha256'),
            'verification': (var.get('verification') or {}).get('state'),
            'oracle': (var.get('oracle') or {}).get('state'),
            'size_count': len(var.get('sizes') or {}),
        }
    return {
        'schema': 'evidence_summary_v1',
        'run_id': report.get('run_id'),
        'kernel': report.get('kernel') or (report.get('extra') or {}).get('kernel'),
        'host': report.get('host'),
        'machine': report.get('machine'),
        'cpu_brand': report.get('cpu_brand'),
        'promotional': report.get('promotional'),
        'measure_sizes': report.get('measure_sizes'),
        'samples_per_size': report.get('samples_per_size'),
        'variants': variants,
        'full_report_sha256': hashlib.sha256(raw).hexdigest(),
        'samples_jsonl': report.get('samples_jsonl'),
    }
