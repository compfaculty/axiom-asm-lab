"""Paired bootstrap comparison and promotion classification (BENCHMARK_PROTOCOL)."""
from __future__ import annotations

import math
import random
import statistics
from typing import Dict, List, Optional, Sequence, Tuple

SPEEDUP_MIN = 1.05
REGRESSION_CEILING = 0.03  # max allowed candidate/baseline median slowdown
BOOTSTRAP_RESAMPLES = 10_000
CI_LEVEL = 0.95


def geometric_mean(values: Sequence[float]) -> float:
    vals = [float(v) for v in values]
    if not vals or any(v <= 0 for v in vals):
        raise ValueError('geometric_mean requires positive values')
    return math.exp(sum(math.log(v) for v in vals) / len(vals))


def per_size_speedups(baseline_medians: Dict[str, float],
                      candidate_medians: Dict[str, float]) -> Dict[str, float]:
    """speedup = baseline_time / candidate_time (>1 means candidate faster)."""
    sizes = sorted(set(baseline_medians) & set(candidate_medians), key=lambda s: int(s))
    out = {}
    for s in sizes:
        b = baseline_medians[s]
        c = candidate_medians[s]
        if b is None or c is None or c <= 0 or b <= 0:
            raise ValueError('missing or non-positive median for size ' + s)
        out[s] = b / c
    return out


def regression_violations(speedups: Dict[str, float],
                          ceiling: float = REGRESSION_CEILING) -> List[str]:
    """Sizes where candidate is slower than baseline by more than ceiling (ratio < 1-ceiling)."""
    bad = []
    floor = 1.0 / (1.0 + ceiling)
    for s, sp in speedups.items():
        if sp < floor:
            bad.append(s)
    return bad


def extract_medians(bench_report: dict, variant: str) -> Dict[str, Optional[float]]:
    var = bench_report.get('variants', {}).get(variant)
    if not var:
        raise KeyError('variant not in report: ' + variant)
    out = {}
    for size, payload in var.get('sizes', {}).items():
        out[size] = payload.get('median_ns')
    return out


def extract_paired_ns(bench_report: dict, baseline: str, candidate: str
                      ) -> Dict[str, List[Tuple[float, float]]]:
    """Map size -> list of (baseline_ns, candidate_ns) aligned by sample_index."""
    b = bench_report['variants'][baseline]['sizes']
    c = bench_report['variants'][candidate]['sizes']
    paired = {}
    for size in set(b) & set(c):
        brows = {r['sample_index']: r['ns_per_call'] for r in b[size].get('raw_samples', [])}
        crows = {r['sample_index']: r['ns_per_call'] for r in c[size].get('raw_samples', [])}
        idxs = sorted(set(brows) & set(crows))
        if set(brows) != set(crows) or len(brows) != len(b[size].get('raw_samples', [])) or len(crows) != len(c[size].get('raw_samples', [])):
            raise ValueError('Unmatched or duplicate paired sample indexes')
        paired[size] = [(brows[i], crows[i]) for i in idxs]
    return paired


def _geomean_from_paired(paired: Dict[str, List[Tuple[float, float]]]) -> float:
    ratios = []
    for size in sorted(paired, key=lambda s: int(s)):
        pairs = paired[size]
        if not pairs:
            raise ValueError('empty pairs for size ' + size)
        bmed = statistics.median(p[0] for p in pairs)
        cmed = statistics.median(p[1] for p in pairs)
        if bmed <= 0 or cmed <= 0:
            raise ValueError('non-positive median')
        ratios.append(bmed / cmed)
    return geometric_mean(ratios)


def paired_bootstrap_ci(paired: Dict[str, List[Tuple[float, float]]],
                        seed: int,
                        resamples: int = BOOTSTRAP_RESAMPLES,
                        ci_level: float = CI_LEVEL) -> Dict:
    """Seeded paired bootstrap on per-size sample pairs; CI for geomean speedup."""
    if not paired:
        raise ValueError('no paired sizes')
    if resamples < 1 or not 0 < ci_level < 1:
        raise ValueError('Invalid bootstrap configuration')
    point = _geomean_from_paired(paired)
    rng = random.Random(seed)
    boots = []
    sizes = sorted(paired, key=int)
    for _ in range(resamples):
        resampled = {}
        for s in sizes:
            rows = paired[s]
            resampled[s] = [rows[rng.randrange(len(rows))] for _ in rows]
        boots.append(_geomean_from_paired(resampled))
    boots.sort()
    alpha = 1.0 - ci_level
    lo_i = int(alpha / 2 * resamples)
    hi_i = int((1.0 - alpha / 2) * resamples) - 1
    hi_i = max(0, min(hi_i, resamples - 1))
    return {
        'aggregate_speedup': point,
        'ci_level': ci_level,
        'ci_low': boots[lo_i],
        'ci_high': boots[hi_i],
        'resamples': resamples,
        'seed': seed,
    }


def classify_session(baseline_medians: Dict[str, Optional[float]],
                     candidate_medians: Dict[str, Optional[float]],
                     paired: Optional[Dict[str, List[Tuple[float, float]]]] = None,
                     bootstrap_seed: int = 1,
                     resamples: int = BOOTSTRAP_RESAMPLES) -> Dict:
    """Classify one session: promote_eligible / regression / inconclusive / missing_data."""
    # Missing data check
    sizes = sorted(set(baseline_medians) | set(candidate_medians), key=lambda s: int(s))
    missing = []
    for s in sizes:
        if baseline_medians.get(s) is None or candidate_medians.get(s) is None:
            missing.append(s)
    if missing or not (set(baseline_medians) & set(candidate_medians)):
        return {
            'decision': 'missing_data',
            'promote_eligible': False,
            'missing_sizes': missing,
            'reason': 'missing medians prevent promotion',
        }

    speedups = per_size_speedups(
        {s: baseline_medians[s] for s in baseline_medians if baseline_medians[s] is not None},
        {s: candidate_medians[s] for s in candidate_medians if candidate_medians[s] is not None},
    )
    regs = regression_violations(speedups)
    if (paired is None or set(paired) != set(sizes)
            or any(len(rows) < 30 for rows in paired.values())
            or any(not math.isfinite(v) or v <= 0
                   for rows in paired.values() for pair in rows for v in pair)):
        return {'decision': 'missing_data', 'promote_eligible': False,
                'reason': 'Require 30 finite positive raw pairs for every objective size'}
    boot = paired_bootstrap_ci(paired, seed=bootstrap_seed, resamples=resamples)
    agg = boot['aggregate_speedup']
    ci_low = boot['ci_low']

    if regs:
        decision = 'regression'
        eligible = False
        reason = 'size regression exceeds ceiling: ' + ','.join(regs)
    elif agg >= SPEEDUP_MIN and ci_low > 1.0:
        decision = 'win'
        eligible = True
        reason = 'aggregate speedup and CI clear defaults'
    elif agg < 1.0 and ci_low < 1.0:
        decision = 'regression'
        eligible = False
        reason = 'aggregate favors baseline'
    else:
        decision = 'inconclusive'
        eligible = False
        reason = 'speedup/CI do not clear promotion defaults'

    return {
        'decision': decision,
        'promote_eligible': eligible,
        'per_size_speedups': speedups,
        'regression_sizes': regs,
        'bootstrap': boot,
        'thresholds': {
            'speedup_min': SPEEDUP_MIN,
            'regression_ceiling': REGRESSION_CEILING,
        },
        'reason': reason,
    }


def classify_promotion(session_a: Dict, session_b: Optional[Dict] = None) -> Dict:
    """Speed claim requires two fresh sessions both promote_eligible."""
    if session_a.get('decision') == 'missing_data' or (
            session_b and session_b.get('decision') == 'missing_data'):
        return {
            'speed_claim': False,
            'decision': 'missing_data',
            'reason': 'missing data cannot promote',
            'sessions_required': 2,
            'sessions_provided': 1 + (1 if session_b else 0),
        }
    if session_b is None:
        return {
            'speed_claim': False,
            'decision': 'needs_second_session',
            'reason': 'fresh second session required for a speed claim',
            'session_a': session_a.get('decision'),
            'sessions_required': 2,
            'sessions_provided': 1,
        }
    if (not session_a.get('run_id') or not session_b.get('run_id')
            or session_a['run_id'] == session_b['run_id']
            or not session_a.get('identity')
            or session_a['identity'] != session_b.get('identity')):
        return {'speed_claim': False, 'decision': 'invalid_sessions',
                'reason': 'Require distinct runs with matching host, artifacts and objectives'}
    if session_a.get('promote_eligible') and session_b.get('promote_eligible'):
        return {
            'speed_claim': True,
            'decision': 'promoted',
            'reason': 'both sessions promote_eligible',
            'session_a': session_a.get('decision'),
            'session_b': session_b.get('decision'),
            'sessions_required': 2,
            'sessions_provided': 2,
        }
    return {
        'speed_claim': False,
        'decision': 'not_promoted',
        'reason': 'not both sessions promote_eligible',
        'session_a': session_a.get('decision'),
        'session_b': session_b.get('decision'),
        'sessions_required': 2,
        'sessions_provided': 2,
    }


def validate_report(report, baseline, candidate, expected_sizes):
    """Fail closed before statistical analysis; legacy summaries are not evidence."""
    if not report.get('run_id') or report.get('schema') != 2:
        raise ValueError('Missing run identity or unsupported report schema')
    for key in ('host', 'machine', 'clang'):
        if not report.get(key):
            raise ValueError('Missing report identity: ' + key)
    expected = {str(n) for n in expected_sizes}
    if {str(n) for n in report.get('measure_sizes', [])} != expected or report.get('skipped_sizes'):
        raise ValueError('Incomplete predefined objective sizes')
    if report.get('target_sample_ns', 0) < 20_000_000:
        raise ValueError('Promotion requires 20 ms target samples')
    for name in (baseline, candidate):
        var = report.get('variants', {}).get(name, {})
        if (var.get('lifecycle') != 'measured' or
                var.get('verification', {}).get('state') != 'pass' or
                var.get('oracle', {}).get('state') != 'pass'):
            raise ValueError('Unverified or unmeasured variant: ' + name)
        for key in ('source_sha256', 'harness_sha256', 'abi_wrap_sha256', 'binary_sha256'):
            value = var.get(key, '')
            if not isinstance(value, str) or len(value) != 64 or any(c not in '0123456789abcdef' for c in value):
                raise ValueError('Missing artifact hash: ' + key)
        if not var.get('compiler_identity'):
            raise ValueError('Missing compiler identity')
        if set(var.get('sizes', {})) != expected:
            raise ValueError('Incomplete variant sizes')
        for size, payload in var['sizes'].items():
            rows = payload.get('raw_samples', [])
            if len(rows) < 30:
                raise ValueError('At least 30 raw samples required')
            indexes = [row.get('sample_index') for row in rows]
            if any(type(i) is not int or i < 0 for i in indexes) or len(set(indexes)) != len(indexes):
                raise ValueError('Invalid or duplicate sample indexes')
            for row in rows:
                ns = row.get('ns_per_call')
                if not isinstance(ns, (int, float)) or not math.isfinite(ns) or ns <= 0:
                    raise ValueError('Non-finite or invalid timing')
                iters, elapsed = row.get('iterations', 0), row.get('elapsed_ns', 0)
                if type(iters) is not int or iters <= 0 or not isinstance(elapsed, (float, int)) or elapsed <= 0 or not math.isfinite(elapsed):
                    raise ValueError('Invalid raw timing counters')
                if not math.isclose(ns, elapsed / iters, rel_tol=1e-5, abs_tol=0.001):
                    raise ValueError('Raw timing counters disagree')
            if payload.get('median_ns') != statistics.median(row['ns_per_call'] for row in rows):
                raise ValueError('Median disagrees with raw samples')
    extract_paired_ns(report, baseline, candidate)
