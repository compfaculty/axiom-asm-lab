#!/usr/bin/env python3
"""Compile, verify and benchmark isolated AArch64 assembly candidates."""
import argparse
import hashlib
import json
import platform
import re
import shutil
import signal
import statistics
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
HARNESS = ROOT / 'src' / 'harness.c'
ABI_WRAP = ROOT / 'src' / 'abi_wrap.s'
SIZES = (0, 1, 3, 4, 7, 16, 64, 1024, 65536, 1048576)
ORACLE_SEED = 1
DEFAULT_BENCH_SEED = 1
BUILTIN_SOURCES = {
    'clang_o3': ROOT / 'src' / 'reference.c',
    'scalar': ROOT / 'asm' / 'scalar.s',
    'unrolled4': ROOT / 'asm' / 'unrolled4.s',
}
# Fixture name -> (expected classification, harness probe command)
FAULT_MATRIX = {
    'scalar': ('pass', 'probe'),
    'overread': ('memory_fault', 'probe-tight'),
    'underread': ('memory_fault', 'probe-head'),
    'input_write': ('memory_fault', 'probe'),
    'abi_corrupt': ('abi_fail', 'probe'),
    'trap': ('trap', 'probe'),
    'infinite_loop': ('timed_out', 'probe'),
}
NAME_RE = re.compile(r'^[A-Za-z0-9_-]+$')
# Artifact lifecycle: built -> verified -> measured; failed/stale are terminal for timing.
LIFECYCLE_BUILT = 'built'
LIFECYCLE_VERIFIED = 'verified'
LIFECYCLE_FAILED = 'failed'
LIFECYCLE_STALE = 'stale'
LIFECYCLE_MEASURED = 'measured'


def doctor():
    if sys.platform != 'darwin' or platform.machine() != 'arm64':
        raise RuntimeError('Requires macOS arm64 (Apple Silicon); current: '
                           + sys.platform + '/' + platform.machine())
    if not shutil.which('clang'):
        raise RuntimeError('clang missing; install Xcode Command Line Tools')


def run(args, timeout=120):
    return subprocess.run(args, cwd=ROOT, check=True, text=True,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          timeout=timeout).stdout.strip()


def sha256_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def clang_identity():
    return run(['clang', '--version']).splitlines()[0]


def sources(candidate=None):
    if candidate is None:
        return dict(BUILTIN_SOURCES)
    if not NAME_RE.fullmatch(candidate):
        raise ValueError('Candidate name must be a simple filename stem')
    if candidate in BUILTIN_SOURCES:
        raise ValueError('Candidate name collides with built-in: ' + candidate)
    path = ROOT / 'candidates' / (candidate + '.s')
    if not path.is_file():
        raise FileNotFoundError(path)
    return {candidate: path}


def new_run_dir():
    """Create a unique immutable run directory under build/runs/."""
    runs = ROOT / 'build' / 'runs'
    runs.mkdir(parents=True, exist_ok=True)
    for _ in range(8):
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')
        run_id = stamp + '_' + uuid.uuid4().hex[:8]
        path = runs / run_id
        try:
            path.mkdir(exist_ok=False)
            return run_id, path
        except FileExistsError:
            continue
    raise RuntimeError('Unable to allocate unique run directory')


def default_bench_output(run_id):
    return ROOT / 'results' / 'runs' / run_id / 'bench.json'


def refuse_overwrite(path):
    path = Path(path)
    if path.exists():
        raise FileExistsError('Refusing to overwrite existing artifact: ' + str(path))


def compile_one(name, source, run_dir):
    if not HARNESS.is_file():
        raise FileNotFoundError(HARNESS)
    if not ABI_WRAP.is_file():
        raise FileNotFoundError(ABI_WRAP)
    if not Path(source).is_file():
        raise FileNotFoundError(source)
    binary = run_dir / ('harness_' + name)
    refuse_overwrite(binary)
    argv = ['clang', '-O3', '-std=c11', '-Wall', '-Wextra',
            str(HARNESS), str(ABI_WRAP), str(source), '-o', str(binary)]
    run(argv)
    record = {
        'name': name,
        'lifecycle': LIFECYCLE_BUILT,
        'source_path': str(Path(source).resolve()),
        'source_sha256': sha256_file(source),
        'harness_path': str(HARNESS.resolve()),
        'harness_sha256': sha256_file(HARNESS),
        'abi_wrap_path': str(ABI_WRAP.resolve()),
        'abi_wrap_sha256': sha256_file(ABI_WRAP),
        'binary_path': str(binary.resolve()),
        'binary_sha256': sha256_file(binary),
        'binary_bytes': binary.stat().st_size,
        'build_argv': argv,
        'compiler_identity': clang_identity(),
        'verification': {'state': 'built', 'output': None},
        'diagnostics': [],
    }
    return binary, record


def append_diagnostic(record, kind, detail):
    entry = {
        'kind': kind,
        'detail': detail,
        'timestamp_utc': datetime.now(timezone.utc).isoformat(),
        'lifecycle': record.get('lifecycle'),
        'source_sha256': record.get('source_sha256'),
        'harness_sha256': record.get('harness_sha256'),
        'binary_sha256': record.get('binary_sha256'),
    }
    record.setdefault('diagnostics', []).append(entry)
    return entry


def persist_diagnostics(run_dir, record):
    """Write retained diagnostics for a variant (immutable per write)."""
    path = Path(run_dir) / ('diagnostics_' + record['name'] + '.json')
    refuse_overwrite(path)
    payload = {
        'name': record['name'],
        'lifecycle': record.get('lifecycle'),
        'verification': record.get('verification'),
        'oracle': record.get('oracle'),
        'diagnostics': record.get('diagnostics') or [],
    }
    path.write_text(json.dumps(payload, indent=2) + '\n')
    return path


def mark_failed(record, reason, output=None, run_dir=None):
    record['lifecycle'] = LIFECYCLE_FAILED
    record['verification'] = {
        'state': 'failed',
        'output': output,
        'reason': reason,
    }
    append_diagnostic(record, 'verification_failed', reason)
    if run_dir is not None:
        persist_diagnostics(run_dir, record)


def mark_stale(record, reason):
    record['lifecycle'] = LIFECYCLE_STALE
    record['verification'] = {'state': 'stale', 'reason': reason}
    append_diagnostic(record, 'stale', reason)


def verify_binary(binary, record, run_dir=None):
    """Run verify and record state; require source/harness hashes still current."""
    ensure_fresh(record)
    try:
        output = run([str(binary), 'verify'], timeout=60)
    except subprocess.CalledProcessError as exc:
        mark_failed(record, 'verify_process_failed',
                    output=(exc.stderr or exc.stdout or str(exc)), run_dir=run_dir)
        raise
    if output != 'PASS':
        mark_failed(record, 'unexpected_verify_output', output=output, run_dir=run_dir)
        raise RuntimeError('Unexpected verification output: ' + output)
    record['verification'] = {
        'state': 'pass',
        'output': output,
        'source_sha256_at_verify': sha256_file(record['source_path']),
        'harness_sha256_at_verify': sha256_file(HARNESS),
        'abi_wrap_sha256_at_verify': sha256_file(ABI_WRAP),
        'binary_sha256_at_verify': sha256_file(binary),
    }
    return output


def oracle_check(binary, run_dir, seed=ORACLE_SEED):
    """Differential check: native sum-file results must match independent Python oracle."""
    from kernels.sum_u64 import case_fingerprint, generate_cases, oracle, write_sum_file
    cases = generate_cases(seed)
    case_dir = run_dir / 'oracle_cases'
    case_dir.mkdir(exist_ok=True)
    mismatches = []
    for label, values in cases:
        path = case_dir / (label + '.txt')
        write_sum_file(path, values)
        got = int(run([str(binary), 'sum-file', str(path)], timeout=60))
        want = oracle(values)
        if got != want:
            mismatches.append({'label': label, 'n': len(values), 'got': got, 'want': want})
            break
    result = {
        'seed': seed,
        'case_count': len(cases),
        'fingerprint': case_fingerprint(cases),
        'mismatches': mismatches,
        'state': 'pass' if not mismatches else 'failed',
    }
    if mismatches:
        raise RuntimeError('Oracle mismatch for ' + mismatches[0]['label']
                           + f": got={mismatches[0]['got']} want={mismatches[0]['want']}")
    return result


def finalize_verified(record, oracle_result):
    if oracle_result.get('state') != 'pass':
        record['lifecycle'] = LIFECYCLE_FAILED
        append_diagnostic(record, 'oracle_failed', oracle_result)
        raise RuntimeError('Oracle check failed for ' + record['name'])
    record['oracle'] = oracle_result
    record['lifecycle'] = LIFECYCLE_VERIFIED
    append_diagnostic(record, 'verified', {'oracle_cases': oracle_result.get('case_count')})


def assert_measurable(record):
    """Refuse timing unless lifecycle is verified and artifact hashes still match."""
    if record.get('lifecycle') == LIFECYCLE_FAILED:
        raise RuntimeError('Refusing to measure failed variant: ' + record['name'])
    if record.get('lifecycle') == LIFECYCLE_STALE:
        raise RuntimeError('Refusing to measure stale variant: ' + record['name'])
    if record.get('lifecycle') != LIFECYCLE_VERIFIED:
        raise RuntimeError('Refusing to measure; lifecycle is '
                           + str(record.get('lifecycle')) + ' for ' + record['name'])
    ensure_fresh(record)
    if record['verification'].get('state') != 'pass':
        raise RuntimeError('Refusing to measure unverified variant: ' + record['name'])
    oracle = record.get('oracle') or {}
    if oracle.get('state') != 'pass':
        raise RuntimeError('Refusing to measure without oracle pass: ' + record['name'])


def ensure_fresh(record):
    """Invalidate verification if source, harness, or abi wrap changed since build/verify."""
    src = Path(record['source_path'])
    if not src.is_file():
        raise FileNotFoundError('Source missing after build: ' + str(src))
    if not HARNESS.is_file():
        raise FileNotFoundError(HARNESS)
    if not ABI_WRAP.is_file():
        raise FileNotFoundError(ABI_WRAP)
    src_hash = sha256_file(src)
    harness_hash = sha256_file(HARNESS)
    abi_hash = sha256_file(ABI_WRAP)
    if src_hash != record['source_sha256']:
        mark_stale(record, 'source hash mismatch')
        raise RuntimeError('Source changed after build; previous verification invalid for '
                           + record['name'])
    if harness_hash != record['harness_sha256']:
        mark_stale(record, 'harness hash mismatch')
        raise RuntimeError('Harness changed after build; previous verification invalid for '
                           + record['name'])
    if abi_hash != record.get('abi_wrap_sha256', abi_hash):
        mark_stale(record, 'abi_wrap hash mismatch')
        raise RuntimeError('ABI wrapper changed after build; previous verification invalid for '
                           + record['name'])
    ver = record.get('verification') or {}
    if ver.get('state') == 'pass':
        if (ver.get('source_sha256_at_verify') != src_hash
                or ver.get('harness_sha256_at_verify') != harness_hash
                or (ver.get('abi_wrap_sha256_at_verify')
                    and ver.get('abi_wrap_sha256_at_verify') != abi_hash)):
            mark_stale(record, 'post-verify hash mismatch')
            raise RuntimeError('Artifacts changed after verify; measurement refused for '
                               + record['name'])


def write_manifest(run_dir, run_id, command, records, extra=None):
    manifest = {
        'schema': 1,
        'run_id': run_id,
        'command': command,
        'timestamp_utc': datetime.now(timezone.utc).isoformat(),
        'host': platform.platform(),
        'machine': platform.machine(),
        'compiler_identity': clang_identity(),
        'harness_sha256': sha256_file(HARNESS),
        'variants': records,
    }
    if extra:
        manifest.update(extra)
    path = run_dir / 'manifest.json'
    refuse_overwrite(path)
    path.write_text(json.dumps(manifest, indent=2) + '\n')
    return path


def fixture_source(name):
    if name == 'scalar':
        return BUILTIN_SOURCES['scalar']
    path = ROOT / 'fixtures' / (name + '.s')
    if not path.is_file():
        raise FileNotFoundError(path)
    return path


def classify_child(returncode, stdout, stderr, timed_out=False):
    if timed_out:
        return 'timed_out'
    out = (stdout or '') + '\n' + (stderr or '')
    if returncode == 0 and 'PASS' in (stdout or ''):
        return 'pass'
    if returncode == 3 or 'ABI_FAIL' in out:
        return 'abi_fail'
    if returncode == 1 or 'FAIL' in out:
        return 'verification_failed'
    if returncode < 0:
        sig = -returncode
        if sig in (signal.SIGSEGV, signal.SIGBUS):
            return 'memory_fault'
        if sig in (signal.SIGILL, signal.SIGTRAP):
            return 'trap'
        return 'signal_' + str(sig)
    # macOS sometimes reports positive status with signal encoding; treat high bits.
    if returncode > 128:
        sig = returncode - 128
        if sig in (signal.SIGSEGV, signal.SIGBUS):
            return 'memory_fault'
        if sig in (signal.SIGILL, signal.SIGTRAP):
            return 'trap'
    return 'failed'


def run_child(args, timeout):
    try:
        proc = subprocess.run(args, cwd=ROOT, text=True,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              timeout=timeout)
        return {
            'returncode': proc.returncode,
            'stdout': proc.stdout,
            'stderr': proc.stderr,
            'timed_out': False,
            'classification': classify_child(proc.returncode, proc.stdout, proc.stderr, False),
        }
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout.decode() if isinstance(exc.stdout, bytes) else (exc.stdout or '')
        stderr = exc.stderr.decode() if isinstance(exc.stderr, bytes) else (exc.stderr or '')
        return {
            'returncode': None,
            'stdout': stdout,
            'stderr': stderr,
            'timed_out': True,
            'classification': 'timed_out',
        }


def fault_matrix(run_dir=None):
    """Compile fixtures + control scalar; run probe in child processes; classify outcomes."""
    if run_dir is None:
        _, run_dir = new_run_dir()
    results = {}
    mismatches = []
    for name, (expected, probe_cmd) in FAULT_MATRIX.items():
        source = fixture_source(name)
        binary, record = compile_one(name, source, run_dir)
        timeout = 1.0 if name == 'infinite_loop' else 30.0
        child = run_child([str(binary), probe_cmd], timeout=timeout)
        ok = child['classification'] == expected
        if child['classification'] == 'pass':
            record['lifecycle'] = LIFECYCLE_VERIFIED
            record['verification'] = {'state': 'pass', 'output': (child['stdout'] or '').strip()}
        else:
            record['lifecycle'] = LIFECYCLE_FAILED
            append_diagnostic(record, 'fault_matrix', {
                'expected': expected,
                'observed': child['classification'],
                'returncode': child['returncode'],
                'stderr_tail': (child['stderr'] or '')[-400:],
            })
            persist_diagnostics(run_dir, record)
            # Surviving child faults: continue remaining fixtures.
        results[name] = {
            'expected': expected,
            'observed': child['classification'],
            'probe_cmd': probe_cmd,
            'ok': ok,
            'lifecycle': record['lifecycle'],
            'returncode': child['returncode'],
            'timed_out': child['timed_out'],
            'stderr_tail': (child['stderr'] or '')[-400:],
            'source_sha256': record['source_sha256'],
            'binary_sha256': record['binary_sha256'],
        }
        status = 'OK' if ok else 'MISMATCH'
        print(f'{name:14} expected={expected:18} observed={child["classification"]:18} {status}',
              flush=True)
        if not ok:
            mismatches.append(name)
    return {'results': results, 'mismatches': mismatches, 'run_dir': str(run_dir)}


def calibrate_iterations(binary, n, target_ns, max_iters):
    line = run([str(binary), 'calibrate', str(n), str(target_ns), str(max_iters)],
               timeout=300)
    parts = line.split()
    if len(parts) != 3:
        raise RuntimeError('Bad calibrate output: ' + line)
    iterations = int(parts[0])
    elapsed_ns = int(parts[1])
    capped = parts[2] == '1'
    return {
        'iterations': iterations,
        'elapsed_ns': elapsed_ns,
        'target_ns': target_ns,
        'max_iters': max_iters,
        'capped': capped,
        'reached_target': elapsed_ns >= target_ns,
    }


def run_bench_raw_one(binary, n, iterations):
    """One calibrated sample: returns elapsed_ns, iterations, ns_per_call."""
    line = run([str(binary), 'bench-raw', str(n), '1', str(iterations)], timeout=300)
    parts = line.split()
    if len(parts) != 3:
        raise RuntimeError('Bad bench-raw output: ' + line)
    return {
        'elapsed_ns': int(parts[0]),
        'iterations': int(parts[1]),
        'ns_per_call': float(parts[2]),
    }


def main():
    from sampling import (
        DEFAULT_MEMORY_CAP_BYTES,
        MAX_CALIBRATE_ITERS,
        TARGET_SAMPLE_NS,
        cache_mode_label,
        filter_sizes_for_cap,
        host_notes,
        paired_schedule,
    )

    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('doctor')
    sub.add_parser('fault-matrix')
    for action in ('verify', 'bench'):
        cmd = sub.add_parser(action)
        cmd.add_argument('--candidate', help='Filename stem in candidates/')
        if action == 'bench':
            cmd.add_argument('--samples', type=int, default=15)
            cmd.add_argument('--seed', type=int, default=DEFAULT_BENCH_SEED,
                             help='RNG seed for paired variant order')
            cmd.add_argument('--target-sample-ms', type=float, default=20.0,
                             help='Calibration target duration per sample')
            cmd.add_argument('--memory-cap-bytes', type=int,
                             default=DEFAULT_MEMORY_CAP_BYTES)
            cmd.add_argument('--host-notes', default=None)
            cmd.add_argument('--output', type=Path, default=None,
                             help='Bench JSON path (must not already exist)')
    args = parser.parse_args()
    try:
        doctor()
        if args.command == 'doctor':
            print(platform.platform(), clang_identity())
            return
        if args.command == 'fault-matrix':
            run_id, run_dir = new_run_dir()
            report = fault_matrix(run_dir)
            out = run_dir / 'fault_matrix.json'
            refuse_overwrite(out)
            payload = {
                'schema': 1,
                'run_id': run_id,
                'timestamp_utc': datetime.now(timezone.utc).isoformat(),
                'host': platform.platform(),
                'machine': platform.machine(),
                'clang': clang_identity(),
                'matrix': report['results'],
                'mismatches': report['mismatches'],
            }
            out.write_text(json.dumps(payload, indent=2) + '\n')
            write_manifest(run_dir, run_id, 'fault-matrix', {}, {'fault_matrix': str(out)})
            print('Saved ' + str(out))
            if report['mismatches']:
                raise RuntimeError('Fault matrix mismatches: ' + ', '.join(report['mismatches']))
            return

        if args.command == 'bench' and not 3 <= args.samples <= 100:
            parser.error('--samples must be between 3 and 100')

        # Resolve output early so we never measure into a doomed overwrite.
        early_output = args.output.resolve() if (args.command == 'bench' and args.output) else None
        if early_output is not None:
            refuse_overwrite(early_output)

        run_id, run_dir = new_run_dir()
        records = {}
        binaries = {}
        for name, source in sources(args.candidate).items():
            binary, record = compile_one(name, source, run_dir)
            try:
                verify_binary(binary, record, run_dir=run_dir)
                oracle_result = oracle_check(binary, run_dir)
                finalize_verified(record, oracle_result)
            except (RuntimeError, subprocess.CalledProcessError):
                if record.get('lifecycle') != LIFECYCLE_FAILED:
                    mark_failed(record, 'verify_or_oracle_failed', run_dir=run_dir)
                raise
            print(name + ': PASS', flush=True)
            records[name] = record
            binaries[name] = binary

        if args.command == 'verify':
            write_manifest(run_dir, run_id, 'verify', records)
            print('Run ' + run_id + ' -> ' + str(run_dir / 'manifest.json'))
            return

        target_ns = int(args.target_sample_ms * 1_000_000)
        if target_ns < 1_000_000:
            parser.error('--target-sample-ms too small')
        measure_sizes = filter_sizes_for_cap(SIZES, args.memory_cap_bytes)
        skipped_sizes = [n for n in SIZES if n not in measure_sizes]
        if skipped_sizes:
            print('Skipping sizes over memory cap '
                  + str(args.memory_cap_bytes) + ': ' + str(skipped_sizes), flush=True)
        if not measure_sizes:
            raise RuntimeError('No sizes remain under memory cap')

        entries = {}
        for name, record in records.items():
            assert_measurable(record)
            entries[name] = {
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
                'calibration': {},
                'sizes': {},
            }

        # Calibrate iterations per (variant, size).
        for n in measure_sizes:
            for name in entries:
                assert_measurable(records[name])
                cal = calibrate_iterations(
                    binaries[name], n, target_ns, MAX_CALIBRATE_ITERS)
                entries[name]['calibration'][str(n)] = cal
                flag = 'CAP' if cal['capped'] and not cal['reached_target'] else 'ok'
                print(f'calibrate {name:12} n={n:8} iters={cal["iterations"]:<10} '
                      f'elapsed_ns={cal["elapsed_ns"]:<12} {flag}', flush=True)

        schedule = paired_schedule(
            list(entries.keys()), measure_sizes, args.samples, args.seed)
        raw_samples = []
        # Accumulate per-variant/size lists while respecting paired order.
        buckets = {(name, n): [] for name in entries for n in measure_sizes}
        for step in schedule:
            name = step['variant']
            n = step['size']
            assert_measurable(records[name])
            iters = entries[name]['calibration'][str(n)]['iterations']
            sample = run_bench_raw_one(binaries[name], n, iters)
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
            record['lifecycle'] = LIFECYCLE_MEASURED
            entries[name]['lifecycle'] = LIFECYCLE_MEASURED
            append_diagnostic(record, 'measured', {
                'sizes': measure_sizes,
                'seed': args.seed,
                'samples_per_size': args.samples,
            })

        output = early_output if early_output is not None else default_bench_output(run_id)
        refuse_overwrite(output)
        output.parent.mkdir(parents=True, exist_ok=True)
        samples_path = output.parent / 'samples.jsonl'
        refuse_overwrite(samples_path)
        with samples_path.open('w') as fh:
            for row in raw_samples:
                fh.write(json.dumps(row) + '\n')
        report = {
            'schema': 2,
            'run_id': run_id,
            'timestamp_utc': datetime.now(timezone.utc).isoformat(),
            'host': platform.platform(),
            'machine': platform.machine(),
            'clang': clang_identity(),
            'samples_per_size': args.samples,
            'seed': args.seed,
            'target_sample_ns': target_ns,
            'memory_cap_bytes': args.memory_cap_bytes,
            'measure_sizes': measure_sizes,
            'skipped_sizes': skipped_sizes,
            'schedule_len': len(schedule),
            'host_notes': host_notes(args.host_notes),
            'samples_jsonl': str(samples_path.resolve()),
            'run_dir': str(run_dir.resolve()),
            'variants': entries,
        }
        output.write_text(json.dumps(report, indent=2) + '\n')
        write_manifest(run_dir, run_id, 'bench', records, {
            'bench_output': str(output.resolve()),
            'samples_jsonl': str(samples_path.resolve()),
            'samples_per_size': args.samples,
            'seed': args.seed,
        })
        print('Saved ' + str(output))
        print('Samples ' + str(samples_path))
        print('Run ' + run_id + ' -> ' + str(run_dir / 'manifest.json'))
    except (RuntimeError, FileNotFoundError, FileExistsError, MemoryError,
            subprocess.CalledProcessError, subprocess.TimeoutExpired, ValueError) as exc:
        print('ERROR: ' + str(exc), file=sys.stderr)
        if isinstance(exc, subprocess.CalledProcessError) and exc.stderr:
            print(exc.stderr, file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
