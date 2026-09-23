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
        'source_path': str(Path(source).resolve()),
        'source_sha256': sha256_file(source),
        'harness_path': str(HARNESS.resolve()),
        'harness_sha256': sha256_file(HARNESS),
        'binary_path': str(binary.resolve()),
        'binary_sha256': sha256_file(binary),
        'binary_bytes': binary.stat().st_size,
        'build_argv': argv,
        'compiler_identity': clang_identity(),
        'verification': {'state': 'built', 'output': None},
    }
    return binary, record


def verify_binary(binary, record):
    """Run verify and record state; require source/harness hashes still current."""
    ensure_fresh(record)
    output = run([str(binary), 'verify'], timeout=60)
    if output != 'PASS':
        record['verification'] = {'state': 'failed', 'output': output}
        raise RuntimeError('Unexpected verification output: ' + output)
    record['verification'] = {
        'state': 'pass',
        'output': output,
        'source_sha256_at_verify': sha256_file(record['source_path']),
        'harness_sha256_at_verify': sha256_file(HARNESS),
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


def ensure_fresh(record):
    """Invalidate verification if source or harness changed since build/verify."""
    src = Path(record['source_path'])
    if not src.is_file():
        raise FileNotFoundError('Source missing after build: ' + str(src))
    if not HARNESS.is_file():
        raise FileNotFoundError(HARNESS)
    src_hash = sha256_file(src)
    harness_hash = sha256_file(HARNESS)
    if src_hash != record['source_sha256']:
        record['verification'] = {'state': 'stale', 'reason': 'source hash mismatch'}
        raise RuntimeError('Source changed after build; previous verification invalid for '
                           + record['name'])
    if harness_hash != record['harness_sha256']:
        record['verification'] = {'state': 'stale', 'reason': 'harness hash mismatch'}
        raise RuntimeError('Harness changed after build; previous verification invalid for '
                           + record['name'])
    ver = record.get('verification') or {}
    if ver.get('state') == 'pass':
        if (ver.get('source_sha256_at_verify') != src_hash
                or ver.get('harness_sha256_at_verify') != harness_hash):
            record['verification'] = {'state': 'stale', 'reason': 'post-verify hash mismatch'}
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
        results[name] = {
            'expected': expected,
            'observed': child['classification'],
            'probe_cmd': probe_cmd,
            'ok': ok,
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('doctor')
    sub.add_parser('fault-matrix')
    for action in ('verify', 'bench'):
        cmd = sub.add_parser(action)
        cmd.add_argument('--candidate', help='Filename stem in candidates/')
        if action == 'bench':
            cmd.add_argument('--samples', type=int, default=15)
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
            verify_binary(binary, record)
            record['oracle'] = oracle_check(binary, run_dir)
            print(name + ': PASS', flush=True)
            records[name] = record
            binaries[name] = binary

        if args.command == 'verify':
            write_manifest(run_dir, run_id, 'verify', records)
            print('Run ' + run_id + ' -> ' + str(run_dir / 'manifest.json'))
            return

        entries = {}
        for name, record in records.items():
            ensure_fresh(record)
            entries[name] = {
                'source_sha256': record['source_sha256'],
                'harness_sha256': record['harness_sha256'],
                'binary_sha256': record['binary_sha256'],
                'binary_bytes': record['binary_bytes'],
                'build_argv': record['build_argv'],
                'compiler_identity': record['compiler_identity'],
                'verification': record['verification'],
                'oracle': record['oracle'],
                'sizes': {},
            }

        for n in SIZES:
            for name in entries:
                ensure_fresh(records[name])
                if records[name]['verification'].get('state') != 'pass':
                    raise RuntimeError('Refusing to measure unverified variant: ' + name)
                samples = [float(s) for s in run(
                    [str(binaries[name]), 'bench', str(n), str(args.samples)],
                    timeout=180).splitlines()]
                entries[name]['sizes'][str(n)] = {
                    'ns_per_call': samples,
                    'median_ns': statistics.median(samples),
                }
                print(f'{name:12} n={n:8} median={statistics.median(samples):12.3f} ns',
                      flush=True)

        output = early_output if early_output is not None else default_bench_output(run_id)
        refuse_overwrite(output)
        output.parent.mkdir(parents=True, exist_ok=True)
        report = {
            'schema': 1,
            'run_id': run_id,
            'timestamp_utc': datetime.now(timezone.utc).isoformat(),
            'host': platform.platform(),
            'machine': platform.machine(),
            'clang': clang_identity(),
            'samples_per_size': args.samples,
            'run_dir': str(run_dir.resolve()),
            'variants': entries,
        }
        output.write_text(json.dumps(report, indent=2) + '\n')
        write_manifest(run_dir, run_id, 'bench', records, {
            'bench_output': str(output.resolve()),
            'samples_per_size': args.samples,
        })
        print('Saved ' + str(output))
        print('Run ' + run_id + ' -> ' + str(run_dir / 'manifest.json'))
    except (RuntimeError, FileNotFoundError, FileExistsError,
            subprocess.CalledProcessError, subprocess.TimeoutExpired, ValueError) as exc:
        print('ERROR: ' + str(exc), file=sys.stderr)
        if isinstance(exc, subprocess.CalledProcessError) and exc.stderr:
            print(exc.stderr, file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
