"""Kernel portfolio registry and experiment reporting helpers."""
from __future__ import annotations

from typing import Any, Dict, List

from . import find_u8, map_filter_u64, sum_u64

KERNELS = {
    'sum_u64': sum_u64,
    'find_u8': find_u8,
    'map_filter_u64': map_filter_u64,
}


def list_kernel_ids() -> List[str]:
    return sorted(KERNELS)


def portfolio_contracts() -> Dict[str, Dict[str, Any]]:
    return {kid: mod.CONTRACT for kid, mod in KERNELS.items()}


def run_oracle_selfchecks(seed: int = 1) -> Dict[str, Any]:
    """Positive oracle consistency + intentional wrong-* divergence per kernel."""
    report: Dict[str, Any] = {'seed': seed, 'kernels': {}}
    # sum_u64
    cases = sum_u64.generate_cases(seed)
    wrong_hits = [
        label for label, vals in cases
        if sum_u64.wrong_sum(vals) != sum_u64.oracle(vals)
    ]
    report['kernels']['sum_u64'] = {
        'case_count': len(cases),
        'fingerprint': sum_u64.case_fingerprint(cases),
        'wrong_diverges': bool(wrong_hits),
        'first_wrong_label': wrong_hits[0] if wrong_hits else None,
        'oracle_ok': all(
            sum_u64.oracle(vals) == sum_u64.oracle(list(vals)) for _, vals in cases),
    }
    # find_u8
    fcases = find_u8.generate_cases(seed)
    fwrong = [
        label for label, buf, needle in fcases
        if find_u8.wrong_find(buf, needle) != find_u8.oracle(buf, needle)
    ]
    report['kernels']['find_u8'] = {
        'case_count': len(fcases),
        'fingerprint': find_u8.case_fingerprint(fcases),
        'wrong_diverges': bool(fwrong),
        'first_wrong_label': fwrong[0] if fwrong else None,
        'oracle_ok': all(
            find_u8.oracle(buf, needle) == find_u8.oracle(list(buf), needle)
            for _, buf, needle in fcases),
    }
    # map_filter_u64
    mcases = map_filter_u64.generate_cases(seed)
    mwrong = [
        label for label, vals in mcases
        if map_filter_u64.wrong_map_filter(vals) != map_filter_u64.oracle(vals)
    ]
    report['kernels']['map_filter_u64'] = {
        'case_count': len(mcases),
        'fingerprint': map_filter_u64.case_fingerprint(mcases),
        'wrong_diverges': bool(mwrong),
        'first_wrong_label': mwrong[0] if mwrong else None,
        'oracle_ok': all(
            map_filter_u64.oracle(vals) == map_filter_u64.oracle(list(vals))
            for _, vals in mcases),
    }
    report['all_passed'] = all(
        k['oracle_ok'] and k['wrong_diverges'] for k in report['kernels'].values())
    return report
