"""Shared build/verify/measure pipeline for bench and search.

Protocol measurements use full objective sizes, >=30 paired samples,
>=20 ms calibration, and produce schema-2 reports accepted by compare.
Smoke measurements are explicitly non-promotional and must not rank.
"""
from __future__ import annotations

import json
import platform
import statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from sampling import (
    DEFAULT_MEMORY_CAP_BYTES,
    MAX_CALIBRATE_ITERS,
    TARGET_SAMPLE_NS,
    cache_mode_label,
    cpu_brand,
    filter_sizes_for_cap,
    host_notes,
    paired_schedule,
)

# Normalized compile flags for both Clang baseline and asm candidates (lab.compile_one).
NORMALIZED_COMPILE_FLAGS = ['-O3', '-std=c11', '-Wall', '-Wextra']

# Full predefined objective (BENCHMARK_PROTOCOL / lab.SIZES).
PROTOCOL_SIZES = (0, 1, 3, 4, 7, 16, 64, 1024, 65536, 1048576)
SMOKE_SIZES = (0, 1, 16, 1024)
SMOKE_TARGET_NS = 5_000_000
PROTOCOL_MIN_SAMPLES = 30


def build_and_verify(name: str, source: Path, run_dir: Path,
                     capture_disasm: bool = True,
                     kernel_id: str = 'sum_u64') -> Tuple[Path, Dict[str, Any]]:
    """Compile, verify, oracle-check; returns (binary, record). Raises on failure."""
    import lab as L

    binary, record = L.compile_one(name, source, run_dir, kernel_id=kernel_id)
    try:
        L.verify_binary(binary, record, run_dir=run_dir)
        oracle_result = L.oracle_check(binary, run_dir, kernel_id=kernel_id)
        L.finalize_verified(record, oracle_result)
    except Exception:
        if record.get('lifecycle') != L.LIFECYCLE_FAILED:
            L.mark_failed(record, 'verify_or_oracle_failed', run_dir=run_dir)
        raise
    if capture_disasm:
        disasm = L.capture_disassembly(binary, run_dir, name)
        record['disassembly'] = str(disasm.resolve())
    return binary, record


def variant_entry_from_record(record: Dict[str, Any],
                              extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    entry = {
        'lifecycle': record['lifecycle'],
        'source_sha256': record['source_sha256'],
        'harness_sha256': record['harness_sha256'],
        'abi_wrap_sha256': record['abi_wrap_sha256'],
        'binary_sha256': record['binary_sha256'],
        'binary_bytes': record['binary_bytes'],
        'build_argv': record['build_argv'],
        'compiler_identity': record['compiler_identity'],
        'verification': record['verification'],
        'oracle': record['oracle'],
        'diagnostics': record.get('diagnostics'),
        'disassembly': record.get('disassembly'),
        'calibration': {},
        'sizes': {},
    }
    if extra:
        entry.update(extra)
    return entry


def measure_paired(
        records: Dict[str, Dict[str, Any]],
        binaries: Dict[str, Path],
        *,
        sizes: Sequence[int],
        samples: int,
        seed: int,
        target_sample_ns: int,
        memory_cap_bytes: int = DEFAULT_MEMORY_CAP_BYTES,
        progress: bool = True,
        kernel_id: str = 'sum_u64',
) -> Tuple[Dict[str, Any], List[Dict[str, Any]], List[int], List[int]]:
    """Calibrate and collect paired raw samples. No score on failed variants.

    Returns (entries, raw_samples, measure_sizes, skipped_sizes).
    Mutates records to lifecycle measured on success.
    """
    import lab as L
    from kernels.descriptors import array_bytes_for_kernel

    if target_sample_ns < 1_000_000:
        raise ValueError('target_sample_ns too small')
    measure_sizes = []
    skipped_sizes = []
    for n in sizes:
        need = array_bytes_for_kernel(kernel_id, int(n))
        if need > memory_cap_bytes:
            skipped_sizes.append(int(n))
        else:
            measure_sizes.append(int(n))
    if not measure_sizes:
        raise RuntimeError('No sizes remain under memory cap')

    entries: Dict[str, Any] = {}
    for name, record in records.items():
        L.assert_measurable(record)
        entries[name] = variant_entry_from_record(record)

    for n in measure_sizes:
        for name in entries:
            L.assert_measurable(records[name])
            cal = L.calibrate_iterations(
                binaries[name], n, target_sample_ns, MAX_CALIBRATE_ITERS)
            entries[name]['calibration'][str(n)] = cal
            if progress:
                flag = 'CAP' if cal['capped'] and not cal['reached_target'] else 'ok'
                print(f'calibrate {name:12} n={n:8} iters={cal["iterations"]:<10} '
                      f'elapsed_ns={cal["elapsed_ns"]:<12} {flag}', flush=True)

    schedule = paired_schedule(list(entries.keys()), measure_sizes, samples, seed)
    raw_samples: List[Dict[str, Any]] = []
    buckets = {(name, n): [] for name in entries for n in measure_sizes}
    for step in schedule:
        name = step['variant']
        n = step['size']
        L.assert_measurable(records[name])
        iters = entries[name]['calibration'][str(n)]['iterations']
        sample = L.run_bench_raw_one(binaries[name], n, iters)
        sample_rec = {
            'size': n,
            'sample_index': step['sample_index'],
            'variant': name,
            'iterations': sample['iterations'],
            'elapsed_ns': sample['elapsed_ns'],
            'ns_per_call': sample['ns_per_call'],
            'cache_mode': cache_mode_label(n),
        }
        raw_samples.append(sample_rec)
        buckets[(name, n)].append(sample_rec)
        if progress:
            print(f'{name:12} n={n:8} i={step["sample_index"]:<3} '
                  f'ns/call={sample["ns_per_call"]:12.3f}', flush=True)

    for name in entries:
        for n in measure_sizes:
            rows = buckets[(name, n)]
            ns_list = [r['ns_per_call'] for r in rows]
            entries[name]['sizes'][str(n)] = {
                'cache_mode': cache_mode_label(n),
                'array_bytes': n * 8,
                'calibration': entries[name]['calibration'][str(n)],
                'raw_samples': rows,
                'ns_per_call': ns_list,
                'median_ns': statistics.median(ns_list),
            }

    for name, record in records.items():
        record['lifecycle'] = L.LIFECYCLE_MEASURED
        entries[name]['lifecycle'] = L.LIFECYCLE_MEASURED
        L.append_diagnostic(record, 'measured', {
            'sizes': measure_sizes,
            'seed': seed,
            'samples_per_size': samples,
        })

    return entries, raw_samples, measure_sizes, skipped_sizes


def write_bench_report(
        *,
        run_id: str,
        run_dir: Path,
        command: str,
        entries: Dict[str, Any],
        raw_samples: List[Dict[str, Any]],
        measure_sizes: Sequence[int],
        skipped_sizes: Sequence[int],
        samples: int,
        seed: int,
        target_sample_ns: int,
        memory_cap_bytes: int,
        output: Path,
        host_notes_extra: Optional[str] = None,
        promotional: bool = True,
        extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Persist schema-2 report + samples.jsonl. Smoke reports set promotional=False."""
    import lab as L

    L.refuse_overwrite(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    samples_path = output.parent / 'samples.jsonl'
    L.refuse_overwrite(samples_path)
    with samples_path.open('w') as fh:
        for row in raw_samples:
            fh.write(json.dumps(row) + '\n')

    report: Dict[str, Any] = {
        'schema': 2,
        'run_id': run_id,
        'command': command,
        'timestamp_utc': datetime.now(timezone.utc).isoformat(),
        'host': platform.platform(),
        'machine': platform.machine(),
        'cpu_brand': cpu_brand(),
        'clang': L.clang_identity(),
        'compiler_config': {
            'baseline_flags': list(NORMALIZED_COMPILE_FLAGS),
            'candidate_flags': list(NORMALIZED_COMPILE_FLAGS),
        },
        'samples_per_size': samples,
        'seed': seed,
        'target_sample_ns': target_sample_ns,
        'memory_cap_bytes': memory_cap_bytes,
        'measure_sizes': list(measure_sizes),
        'skipped_sizes': list(skipped_sizes),
        'schedule_len': len(raw_samples),
        'host_notes': host_notes(host_notes_extra),
        'samples_jsonl': str(samples_path.resolve()),
        'run_dir': str(run_dir.resolve()),
        'promotional': bool(promotional),
        'variants': entries,
    }
    if extra:
        report.update(extra)
    output.write_text(json.dumps(report, indent=2) + '\n')
    return report


def ensure_baseline_clang(run_dir: Path,
                          records: Dict[str, Dict[str, Any]],
                          binaries: Dict[str, Path],
                          kernel_id: str = 'sum_u64') -> None:
    """Ensure kernel baseline is built and verified alongside candidates for paired scoring."""
    from kernels.descriptors import get_descriptor
    desc = get_descriptor(kernel_id)
    baseline_id = desc['baseline_id']
    if baseline_id in records:
        return
    source = Path(desc['baseline_source'])
    binary, record = build_and_verify(baseline_id, source, run_dir, kernel_id=kernel_id)
    records[baseline_id] = record
    binaries[baseline_id] = binary


def evaluation_config(*, protocol: bool, samples: int, seed: int,
                      target_sample_ns: int, memory_cap_bytes: int,
                      kernel: str = 'sum_u64') -> Dict[str, Any]:
    from kernels.descriptors import get_descriptor
    desc = get_descriptor(kernel)
    sizes = list(desc['protocol_sizes'] if protocol else (0, 1, 16, 1024))
    return {
        'protocol': protocol,
        'promotional': protocol,
        'sizes': sizes,
        'samples_per_size': samples,
        'seed': seed,
        'target_sample_ns': target_sample_ns,
        'memory_cap_bytes': memory_cap_bytes,
        'kernel': kernel,
        'baseline_id': desc['baseline_id'],
        'cpu_brand': cpu_brand(),
        'compiler_config': {
            'baseline_flags': list(NORMALIZED_COMPILE_FLAGS),
            'candidate_flags': list(NORMALIZED_COMPILE_FLAGS),
        },
    }
