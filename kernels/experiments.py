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


def controlled_paired_smoke_protocol() -> Dict[str, Any]:
    """Document the controlled experiment used for multi-kernel pipeline checks.

    Assumptions are explicit: same host session, same sizes/samples/seed family,
    paired schedule, verified binaries only. This is not a speed claim.
    """
    return {
        'experiment_id': 'controlled_paired_smoke',
        'kind': 'controlled_measurement_protocol',
        'controls': [
            'Identical measure sizes and sample counts for baseline and candidate.',
            'Paired randomized schedule (sampling.paired_schedule) with fixed seed.',
            'Verification + oracle must pass before calibrate/bench-raw.',
            'Memory cap applied via array_bytes_for_kernel (map_filter counts in+out).',
        ],
        'assumptions': [
            'Host thermal/power state is not actively controlled; treat single-session '
            'smoke medians as observational, not promotional.',
            'find_u8 bench needle is fixed at 0x5A with a guaranteed mid-buffer hit.',
            'Cache-mode labels remain footprint heuristics, not counter-derived LLC stats.',
        ],
        'observation_vs_inference': (
            'Raw samples and medians are observations; any explanation of why one '
            'kernel is faster is inference and must be labeled as such.'
        ),
        'speedup_required': False,
    }


def build_experiment_report(sizes: List[int] | None = None) -> Dict[str, Any]:
    if sizes is None:
        sizes = [0, 16, 1024, 65536, 1048576]
    return {
        'schema': 2,
        'mandatory_speedup': False,
        'cache': cache_footprint_experiment(sizes),
        'dependencies': dependency_notes(),
        'controlled_protocol': controlled_paired_smoke_protocol(),
        'note': 'Reports separate observation from inferred explanation per T010.',
    }
