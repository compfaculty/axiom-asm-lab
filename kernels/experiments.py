"""Cache / dependency micro-experiments with observation vs inference labels."""
from __future__ import annotations

from typing import Any, Dict, List

from sampling import array_bytes, cache_mode_label


def cache_footprint_experiment(sizes: List[int]) -> Dict[str, Any]:
    rows = []
    for n in sizes:
        rows.append({
            'n': n,
            'array_bytes': array_bytes(n),
            'cache_mode_label': cache_mode_label(n),
            'observation': f'logical footprint {array_bytes(n)} bytes for n={n}',
            'inference': (
                'Label is a footprint heuristic, not a measured LLC miss rate; '
                'do not treat as causal proof of DRAM traffic.'
            ),
        })
    return {
        'experiment_id': 'cache_footprint_labels',
        'kind': 'observation_with_explicit_inference_boundary',
        'rows': rows,
    }


def dependency_notes() -> Dict[str, Any]:
    return {
        'experiment_id': 'dependency_structure_notes',
        'kind': 'qualitative',
        'observations': [
            'sum_u64 forms a long carry/dependency chain through the accumulator.',
            'find_u8 is early-exit data-dependent; branch behavior varies with hit index.',
            'map_filter_u64 is mostly element-local with a compacting write pointer.',
        ],
        'inferences': [
            'Expect find_u8 timing to be more input-content sensitive than sum_u64.',
            'These inferences are hypotheses for later measurement; not promotion claims.',
        ],
        'speedup_required': False,
    }


def build_experiment_report(sizes: List[int] | None = None) -> Dict[str, Any]:
    if sizes is None:
        sizes = [0, 16, 1024, 65536, 1048576]
    return {
        'schema': 1,
        'mandatory_speedup': False,
        'cache': cache_footprint_experiment(sizes),
        'dependencies': dependency_notes(),
        'note': 'Reports separate observation from inferred explanation per T010.',
    }
