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
DEFAULT_KERNEL = 'sum_u64'
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


def compile_one(name, source, run_dir, kernel_id=DEFAULT_KERNEL):
    from kernels.descriptors import get_descriptor
    desc = get_descriptor(kernel_id)
    harness = Path(desc['harness'])
    abi_wrap = Path(desc['abi_wrap'])
    if not harness.is_file():
        raise FileNotFoundError(harness)
    if not abi_wrap.is_file():
        raise FileNotFoundError(abi_wrap)
    if not Path(source).is_file():
        raise FileNotFoundError(source)
    binary = run_dir / ('harness_' + name)
    refuse_overwrite(binary)
    argv = ['clang', '-O3', '-std=c11', '-Wall', '-Wextra',
            str(harness), str(abi_wrap), str(source), '-o', str(binary)]
    run(argv)
    record = {
        'name': name,
        'kernel_id': kernel_id,
        'lifecycle': LIFECYCLE_BUILT,
        'source_path': str(Path(source).resolve()),
        'source_sha256': sha256_file(source),
        'harness_path': str(harness.resolve()),
        'harness_sha256': sha256_file(harness),
        'abi_wrap_path': str(abi_wrap.resolve()),
        'abi_wrap_sha256': sha256_file(abi_wrap),
        'binary_path': str(binary.resolve()),
        'binary_sha256': sha256_file(binary),
        'binary_bytes': binary.stat().st_size,
        'build_argv': argv,
        'compiler_identity': clang_identity(),
        'verification': {'state': 'built', 'output': None},
        'diagnostics': [],
    }
    return binary, record


def capture_disassembly(binary, run_dir, name):
    """Capture native disassembly for the harness binary (otool on macOS)."""
    if not shutil.which('otool'):
        raise RuntimeError('otool missing; required for disassembly capture')
    text = run(['otool', '-tV', str(binary)], timeout=60)
    path = Path(run_dir) / ('disasm_' + name + '.txt')
    refuse_overwrite(path)
    path.write_text(text + '\n')
    return path


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
    harness_path = Path(record.get('harness_path') or HARNESS)
    abi_path = Path(record.get('abi_wrap_path') or ABI_WRAP)
    try:
        output = run([str(binary), 'verify'], timeout=120)
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
        'harness_sha256_at_verify': sha256_file(harness_path),
        'abi_wrap_sha256_at_verify': sha256_file(abi_path),
        'binary_sha256_at_verify': sha256_file(binary),
    }
    return output


def oracle_check(binary, run_dir, seed=ORACLE_SEED, kernel_id=DEFAULT_KERNEL):
    """Differential check: native oracle-file results must match independent Python oracle."""
    from kernels.descriptors import get_descriptor, parse_map_filter_output
    desc = get_descriptor(kernel_id)
    mod = desc['module']
    case_dir = run_dir / 'oracle_cases'
    case_dir.mkdir(exist_ok=True)
    mismatches = []
    cmd = desc['oracle_cmd']

    if kernel_id == 'sum_u64':
        cases = mod.generate_cases(seed)
        for label, values in cases:
            path = case_dir / (label + '.txt')
            mod.write_sum_file(path, values)
            got = int(run([str(binary), cmd, str(path)], timeout=60))
            want = mod.oracle(values)
            if got != want:
                mismatches.append({'label': label, 'n': len(values), 'got': got, 'want': want})
                break
        fingerprint = mod.case_fingerprint(cases)
        case_count = len(cases)
    elif kernel_id == 'find_u8':
        cases = mod.generate_cases(seed)
        for label, buf, needle in cases:
            path = case_dir / (label + '.txt')
            mod.write_find_file(path, buf, needle)
            got = int(run([str(binary), cmd, str(path)], timeout=60))
            want = mod.oracle(buf, needle)
            if got != want:
                mismatches.append({'label': label, 'n': len(buf), 'got': got, 'want': want})
                break
        fingerprint = mod.case_fingerprint(cases)
        case_count = len(cases)
    elif kernel_id == 'map_filter_u64':
        cases = mod.generate_cases(seed)
        for label, values in cases:
            path = case_dir / (label + '.txt')
            mod.write_map_filter_file(path, values)
            text = run([str(binary), cmd, str(path)], timeout=60)
            got = parse_map_filter_output(text)
            want = mod.oracle(values)
            if got != want:
                mismatches.append({'label': label, 'n': len(values), 'got': got, 'want': want})
                break
        fingerprint = mod.case_fingerprint(cases)
        case_count = len(cases)
    else:
        raise ValueError('unsupported kernel for oracle_check: ' + kernel_id)

    result = {
        'seed': seed,
        'kernel_id': kernel_id,
        'case_count': case_count,
        'fingerprint': fingerprint,
        'mismatches': mismatches,
        'state': 'pass' if not mismatches else 'failed',
    }
    if mismatches:
        raise RuntimeError('Oracle mismatch for ' + str(mismatches[0]['label'])
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
    harness = Path(record.get('harness_path') or HARNESS)
    abi_wrap = Path(record.get('abi_wrap_path') or ABI_WRAP)
    if not harness.is_file():
        raise FileNotFoundError(harness)
    if not abi_wrap.is_file():
        raise FileNotFoundError(abi_wrap)
    src_hash = sha256_file(src)
    harness_hash = sha256_file(harness)
    abi_hash = sha256_file(abi_wrap)
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
    binary = Path(record.get('binary_path', ''))
    if (not binary.is_file() or sha256_file(binary) != record.get('binary_sha256')):
        mark_stale(record, 'binary missing or hash mismatch')
        raise RuntimeError('Binary changed or missing after build; measurement refused')
    ver = record.get('verification') or {}
    if ver.get('state') == 'pass' and ver.get('binary_sha256_at_verify') != sha256_file(binary):
        mark_stale(record, 'post-verify binary hash mismatch')
        raise RuntimeError('Binary changed after verify; measurement refused')
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
    mock_p = sub.add_parser('propose-mock')
    mock_p.add_argument('--candidate-id', default='mock_scalar_copy')
    mock_p.add_argument('--output', type=Path, default=None)
    search_cmd = sub.add_parser(
        'search',
        epilog=(
            'Time budget counts active evaluation seconds only (not idle gaps '
            'between resumes). Use --smoke for a non-promotional end-to-end check; '
            'full search without --smoke enforces the measurement protocol.'
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    search_cmd.add_argument('--dir', type=Path, required=True,
                            help='Search directory for atomic state')
    search_cmd.add_argument('--resume', action='store_true')
    search_cmd.add_argument('--max-proposals', type=int, default=20)
    search_cmd.add_argument('--max-seconds', type=float, default=1800.0,
                            help='Active evaluation-time budget in seconds')
    search_cmd.add_argument('--max-stagnation', type=int, default=5)
    search_cmd.add_argument(
        '--provider', default='catalog',
        help='catalog (default real variants), mock (pipeline fixture), or online')
    search_cmd.add_argument(
        '--smoke', action='store_true',
        help='Non-promotional smoke: short sizes/samples; cannot accept winners')
    search_cmd.add_argument('--samples', type=int, default=None,
                            help='Samples per size (protocol default 30; smoke default 3)')
    search_cmd.add_argument('--seed', type=int, default=DEFAULT_BENCH_SEED)
    port = sub.add_parser('portfolio')
    port.add_argument('--seed', type=int, default=1)
    port.add_argument('--output', type=Path, default=None)
    kev = sub.add_parser('kernel-eval',
                         help='Verify+smoke-measure all kernel descriptors (T010 pipeline)')
    kev.add_argument('--samples', type=int, default=3)
    kev.add_argument('--seed', type=int, default=1)
    kev.add_argument('--output', type=Path, default=None,
                     help='JSON report path (must not already exist)')
    lang = sub.add_parser('lang-check')
    lang.add_argument('--source', type=Path, action='append', default=None,
                      help='.ax source path (default: language/examples/*.ax)')
    lang.add_argument('--output', type=Path, default=None)
    ev = sub.add_parser('evaluate-proposal')
    ev.add_argument('--proposal', type=Path, default=None,
                    help='JSON proposal path (omit with --mock)')
    ev.add_argument('--mock', action='store_true', help='Use deterministic mock proposer')
    ev.add_argument('--candidate-id', default='mock_scalar_copy')
    ev.add_argument('--samples', type=int, default=None,
                    help='Samples per size (protocol default 30; smoke default 3)')
    ev.add_argument('--seed', type=int, default=DEFAULT_BENCH_SEED)
    ev.add_argument('--output', type=Path, default=None)
    ev_mode = ev.add_mutually_exclusive_group()
    ev_mode.add_argument(
        '--protocol', action='store_true',
        help='Full protocol measure paired with clang_o3 (for search ranking)')
    ev_mode.add_argument(
        '--smoke', action='store_true',
        help='Short non-promotional measure (cannot rank/promote)')
    ev.add_argument('--target-sample-ms', type=float, default=None)
    ev.add_argument('--memory-cap-bytes', type=int, default=DEFAULT_MEMORY_CAP_BYTES)
    cmp_cmd = sub.add_parser('compare')
    cmp_cmd.add_argument('--baseline', default='clang_o3')
    cmp_cmd.add_argument('--candidate', required=True)
    cmp_cmd.add_argument('--session', action='append', type=Path, required=True,
                         help='Bench JSON path; pass twice for a speed claim')
    cmp_cmd.add_argument('--bootstrap-seed', type=int, default=1)
    cmp_cmd.add_argument('--resamples', type=int, default=None)
    cmp_cmd.add_argument('--output', type=Path, default=None)
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
        if args.command not in ('compare', 'propose-mock'):
            doctor()
        if args.command == 'doctor':
            print(platform.platform(), clang_identity())
            return
        if args.command == 'propose-mock':
            from proposals import mock_propose
            proposal = mock_propose(ROOT, candidate_id=args.candidate_id)
            text = json.dumps(proposal, indent=2) + '\n'
            if args.output:
                refuse_overwrite(args.output.resolve())
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(text)
                print('Saved ' + str(args.output.resolve()))
            else:
                sys.stdout.write(text)
            return
        if args.command == 'search':
            from search import SearchBudgets, SearchController, get_provider, make_evaluate_fn
            provider = get_provider(args.provider)
            smoke = bool(args.smoke)
            samples = args.samples if args.samples is not None else (3 if smoke else 30)
            if not 3 <= samples <= 100:
                parser.error('--samples must be between 3 and 100')
            if not smoke and samples < 30:
                parser.error('protocol search requires --samples >= 30 (or use --smoke)')
            budgets = SearchBudgets(
                max_proposals=args.max_proposals,
                max_seconds=args.max_seconds,
                max_stagnation=args.max_stagnation,
            )
            eval_fn = make_evaluate_fn(
                smoke=smoke, samples=samples, seed=args.seed,
                memory_cap_bytes=DEFAULT_MEMORY_CAP_BYTES)
            ctrl = SearchController(
                ROOT, args.dir.resolve(), budgets, provider=provider,
                evaluate_fn=eval_fn, smoke=smoke,
                samples=samples, seed=args.seed,
                provider_mode=args.provider)
            state = ctrl.run(resume=args.resume)
            summary_path = ctrl.write_summary(state)
            print(json.dumps({
                'status': state.get('status'),
                'stop_reason': state.get('stop_reason'),
                'attempts': len(state.get('attempts') or []),
                'best_observed': state.get('best_observed'),
                'accepted': state.get('accepted'),
                'active_eval_seconds': state.get('active_eval_seconds'),
                'state': str(ctrl.state_path),
                'summary': str(summary_path),
            }, indent=2))
            return
        if args.command == 'portfolio':
            from kernels import (
                build_experiment_report,
                list_kernel_ids,
                portfolio_contracts,
                run_native_comparisons,
                run_oracle_selfchecks,
            )
            payload = {
                'schema': 1,
                'timestamp_utc': datetime.now(timezone.utc).isoformat(),
                'host': platform.platform(),
                'machine': platform.machine(),
                'kernel_ids': list_kernel_ids(),
                'contracts': portfolio_contracts(),
                'oracle_selfchecks': run_oracle_selfchecks(seed=args.seed),
                'native_comparisons': run_native_comparisons(ROOT, seed=args.seed),
                'experiments': build_experiment_report(),
                'mandatory_speedup': False,
            }
            ok = (payload['oracle_selfchecks']['all_passed']
                  and payload['native_comparisons']['all_ok'])
            text = json.dumps(payload, indent=2) + '\n'
            if args.output:
                refuse_overwrite(args.output.resolve())
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(text)
                print('Saved ' + str(args.output.resolve()))
            else:
                sys.stdout.write(text)
            if not ok:
                raise RuntimeError('portfolio checks failed')
            print('portfolio: PASS kernels=' + ','.join(payload['kernel_ids']), flush=True)
            return
        if args.command == 'kernel-eval':
            from evaluate import (
                SMOKE_SIZES,
                SMOKE_TARGET_NS,
                build_and_verify,
                ensure_baseline_clang,
                measure_paired,
                write_bench_report,
            )
            from kernels.descriptors import (
                get_descriptor,
                list_descriptor_ids,
                sanitize_evidence_summary,
            )
            from sampling import DEFAULT_MEMORY_CAP_BYTES as _MEMCAP
            run_id, run_dir = new_run_dir()
            report_kernels = {}
            wrong_blocked = {}
            for kid in list_descriptor_ids():
                desc = get_descriptor(kid)
                kdir = run_dir / kid
                kdir.mkdir()
                records = {}
                binaries = {}
                ensure_baseline_clang(kdir, records, binaries, kernel_id=kid)
                cand_id = kid + '_asm'
                binary, record = build_and_verify(
                    cand_id, Path(desc['asm_baseline']), kdir, kernel_id=kid)
                records[cand_id] = record
                binaries[cand_id] = binary
                entries, raw_samples, measure_sizes, skipped = measure_paired(
                    records, binaries,
                    sizes=SMOKE_SIZES,
                    samples=args.samples,
                    seed=args.seed,
                    target_sample_ns=SMOKE_TARGET_NS,
                    kernel_id=kid,
                )
                out = kdir / 'smoke_measurement.json'
                report = write_bench_report(
                    run_id=f'{run_id}_{kid}',
                    run_dir=kdir,
                    command='kernel-eval',
                    entries=entries,
                    raw_samples=raw_samples,
                    measure_sizes=measure_sizes,
                    skipped_sizes=skipped,
                    samples=args.samples,
                    seed=args.seed,
                    target_sample_ns=SMOKE_TARGET_NS,
                    memory_cap_bytes=_MEMCAP,
                    output=out,
                    promotional=False,
                    extra={'kernel': kid, 'baseline_id': desc['baseline_id']},
                )
                summary = sanitize_evidence_summary({**report, 'kernel': kid})
                (kdir / 'evidence_summary.json').write_text(
                    json.dumps(summary, indent=2) + '\n')
                wrong_src = Path(desc['wrong_candidate'])
                wdir = kdir / 'wrong'
                wdir.mkdir()
                try:
                    build_and_verify('wrong_' + kid, wrong_src, wdir, kernel_id=kid)
                    wrong_blocked[kid] = {'blocked': False, 'error': 'unexpected_pass'}
                except Exception as exc:
                    wrong_blocked[kid] = {'blocked': True, 'error': str(exc)[:200]}
                report_kernels[kid] = {
                    'baseline': desc['baseline_id'],
                    'candidate': cand_id,
                    'measurement': str(out.resolve()),
                    'evidence_summary': str((kdir / 'evidence_summary.json').resolve()),
                    'measure_sizes': measure_sizes,
                    'wrong_blocked_timing': wrong_blocked[kid]['blocked'],
                }
                print(f'{kid}: verify+smoke PASS; wrong_blocked={wrong_blocked[kid]["blocked"]}',
                      flush=True)
            payload = {
                'schema': 1,
                'run_id': run_id,
                'run_dir': str(run_dir.resolve()),
                'kernels': report_kernels,
                'wrong_blocked': wrong_blocked,
                'mandatory_speedup': False,
                'all_ok': all(k['wrong_blocked_timing'] for k in report_kernels.values()),
            }
            text = json.dumps(payload, indent=2) + '\n'
            if args.output:
                refuse_overwrite(args.output.resolve())
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(text)
                print('Saved ' + str(args.output.resolve()))
            else:
                (run_dir / 'kernel_eval.json').write_text(text)
                print('Saved ' + str((run_dir / 'kernel_eval.json').resolve()))
            if not payload['all_ok']:
                raise RuntimeError('kernel-eval failed: wrong candidate not blocked')
            print('kernel-eval: PASS kernels=' + ','.join(report_kernels), flush=True)
            return
        if args.command == 'lang-check':
            from language.native import check_source_equiv
            source_paths = args.source
            if not source_paths:
                source_paths = sorted((ROOT / 'language' / 'examples').glob('*.ax'))
            results = []
            for path in source_paths:
                path = Path(path)
                result = check_source_equiv(path.read_text())
                result['source'] = str(path.resolve())
                results.append(result)
            payload = {
                'schema': 1,
                'timestamp_utc': datetime.now(timezone.utc).isoformat(),
                'host': platform.platform(),
                'machine': platform.machine(),
                'results': results,
                'all_ok': all(r['ok'] for r in results),
            }
            text = json.dumps(payload, indent=2) + '\n'
            if args.output:
                refuse_overwrite(args.output.resolve())
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(text)
                print('Saved ' + str(args.output.resolve()))
            else:
                sys.stdout.write(text)
            if not payload['all_ok']:
                raise RuntimeError('lang-check failed')
            print('lang-check: PASS n=' + str(len(results)), flush=True)
            return
        if args.command == 'evaluate-proposal':
            from proposals import import_proposal, mock_propose, validate_proposal
            from evaluate import (
                PROTOCOL_MIN_SAMPLES,
                PROTOCOL_SIZES,
                SMOKE_SIZES,
                SMOKE_TARGET_NS,
                build_and_verify,
                ensure_baseline_clang,
                measure_paired,
                write_bench_report,
            )
            from sampling import TARGET_SAMPLE_NS as _TSN
            if args.mock == bool(args.proposal):
                parser.error('evaluate-proposal requires exactly one of --mock or --proposal')
            if args.protocol:
                protocol = True
            elif args.smoke:
                protocol = False
            else:
                # Backward-compatible default: non-promotional smoke unless --protocol.
                protocol = False
            samples = args.samples if args.samples is not None else (
                PROTOCOL_MIN_SAMPLES if protocol else 3)
            if not 3 <= samples <= 100:
                parser.error('--samples must be between 3 and 100')
            if protocol and samples < PROTOCOL_MIN_SAMPLES:
                parser.error('--protocol requires --samples >= 30')
            if args.target_sample_ms is not None:
                target_ns = int(args.target_sample_ms * 1_000_000)
            else:
                target_ns = int(_TSN) if protocol else SMOKE_TARGET_NS
            if protocol and target_ns < 20_000_000:
                parser.error('--protocol requires target sample >= 20 ms')
            early_output = args.output.resolve() if args.output else None
            if early_output is not None:
                refuse_overwrite(early_output)
            run_id, run_dir = new_run_dir()
            if args.mock:
                proposal = mock_propose(ROOT, candidate_id=args.candidate_id)
            else:
                proposal = json.loads(args.proposal.read_text())
                validate_proposal(proposal, ROOT)
            imported = import_proposal(proposal, run_dir, ROOT)
            print('Imported ' + imported['candidate_id'] + ' -> ' + imported['dir'], flush=True)
            name = imported['candidate_id']
            source = Path(imported['source_path'])
            kernel_id = proposal.get('kernel_id') or DEFAULT_KERNEL
            from kernels.descriptors import get_descriptor, sanitize_evidence_summary
            desc = get_descriptor(kernel_id)
            records = {}
            binaries = {}
            binary, record = build_and_verify(name, source, run_dir, kernel_id=kernel_id)
            records[name] = record
            binaries[name] = binary
            print(name + ': PASS', flush=True)
            baseline_id = desc['baseline_id']
            if protocol:
                ensure_baseline_clang(run_dir, records, binaries, kernel_id=kernel_id)
                print(baseline_id + ': PASS', flush=True)
            sizes = tuple(desc['protocol_sizes']) if protocol else SMOKE_SIZES
            entries, raw_samples, measure_sizes, skipped_sizes = measure_paired(
                records, binaries,
                sizes=sizes,
                samples=samples,
                seed=args.seed,
                target_sample_ns=target_ns,
                memory_cap_bytes=args.memory_cap_bytes,
                kernel_id=kernel_id,
            )
            for key, entry in entries.items():
                if key == name:
                    entry['proposal'] = imported
            output = early_output if early_output else default_bench_output(run_id)
            report = write_bench_report(
                run_id=run_id,
                run_dir=run_dir,
                command='evaluate-proposal',
                entries=entries,
                raw_samples=raw_samples,
                measure_sizes=measure_sizes,
                skipped_sizes=skipped_sizes,
                samples=samples,
                seed=args.seed,
                target_sample_ns=target_ns,
                memory_cap_bytes=args.memory_cap_bytes,
                output=output,
                promotional=protocol,
                extra={'proposal_import': imported, 'kernel': kernel_id,
                       'baseline_id': baseline_id},
            )
            summary = sanitize_evidence_summary(report)
            (run_dir / 'evidence_summary.json').write_text(
                json.dumps(summary, indent=2) + '\n')
            write_manifest(run_dir, run_id, 'evaluate-proposal', records, {
                'bench_output': str(output.resolve()),
                'proposal_dir': imported['dir'],
                'promotional': protocol,
                'kernel': kernel_id,
                'evidence_summary': str((run_dir / 'evidence_summary.json').resolve()),
            })
            print('Saved ' + str(output))
            print('Run ' + run_id + ' -> ' + str(run_dir / 'manifest.json'))
            if not protocol:
                print('NOTE: non-promotional smoke report; not valid for ranking/promotion',
                      flush=True)
            return
        if args.command == 'compare':
            from analysis import (
                BOOTSTRAP_RESAMPLES,
                classify_promotion,
                classify_session,
                extract_medians,
                extract_paired_ns,
                validate_report,
            )
            if not 1 <= len(args.session) <= 2:
                parser.error('compare requires one or two --session paths')
            resamples = args.resamples if args.resamples is not None else BOOTSTRAP_RESAMPLES
            sessions = []
            reports = []
            for i, path in enumerate(args.session):
                report = json.loads(path.read_text())
                validate_report(report, args.baseline, args.candidate, SIZES)
                reports.append(report)
                med_b = extract_medians(report, args.baseline)
                med_c = extract_medians(report, args.candidate)
                paired = extract_paired_ns(report, args.baseline, args.candidate)
                session = classify_session(
                    med_b, med_c, paired=paired,
                    bootstrap_seed=args.bootstrap_seed + i,
                    resamples=resamples)
                session['bench_path'] = str(path.resolve())
                session['samples_jsonl'] = report.get('samples_jsonl')
                session['run_id'] = report['run_id']
                session['identity'] = {
                    'host': report['host'], 'machine': report['machine'],
                    'clang': report['clang'], 'sizes': report['measure_sizes'],
                    'variants': {name: {key: report['variants'][name][key] for key in
                        ('source_sha256', 'harness_sha256', 'abi_wrap_sha256', 'compiler_identity')}
                        for name in (args.baseline, args.candidate)},
                }
                sessions.append(session)
                print(f'session{i} decision={session["decision"]} '
                      f'agg={session.get("bootstrap", {}).get("aggregate_speedup")} '
                      f'ci_low={session.get("bootstrap", {}).get("ci_low")}',
                      flush=True)
            promo = classify_promotion(sessions[0], sessions[1] if len(sessions) > 1 else None)
            print('promotion', promo['decision'], 'speed_claim=' + str(promo['speed_claim']),
                  flush=True)
            out_payload = {
                'schema': 1,
                'baseline': args.baseline,
                'candidate': args.candidate,
                'sessions': sessions,
                'promotion': promo,
            }
            if args.output:
                refuse_overwrite(args.output.resolve())
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(json.dumps(out_payload, indent=2) + '\n')
                print('Saved ' + str(args.output.resolve()))
            else:
                print(json.dumps(out_payload, indent=2))
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
            except (RuntimeError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
                if record.get('lifecycle') != LIFECYCLE_FAILED:
                    mark_failed(record, 'verify_or_oracle_failed', run_dir=run_dir)
                raise
            print(name + ': PASS', flush=True)
            records[name] = record
            binaries[name] = binary
            disasm = capture_disassembly(binary, run_dir, name)
            record['disassembly'] = str(disasm.resolve())

        if args.command == 'verify':
            write_manifest(run_dir, run_id, 'verify', records)
            print('Run ' + run_id + ' -> ' + str(run_dir / 'manifest.json'))
            return

        target_ns = int(args.target_sample_ms * 1_000_000)
        if target_ns < 1_000_000:
            parser.error('--target-sample-ms too small')
        from evaluate import measure_paired, write_bench_report
        entries, raw_samples, measure_sizes, skipped_sizes = measure_paired(
            records, binaries,
            sizes=SIZES,
            samples=args.samples,
            seed=args.seed,
            target_sample_ns=target_ns,
            memory_cap_bytes=args.memory_cap_bytes,
        )
        if skipped_sizes:
            print('Skipping sizes over memory cap '
                  + str(args.memory_cap_bytes) + ': ' + str(skipped_sizes), flush=True)
        output = early_output if early_output is not None else default_bench_output(run_id)
        report = write_bench_report(
            run_id=run_id,
            run_dir=run_dir,
            command='bench',
            entries=entries,
            raw_samples=raw_samples,
            measure_sizes=measure_sizes,
            skipped_sizes=skipped_sizes,
            samples=args.samples,
            seed=args.seed,
            target_sample_ns=target_ns,
            memory_cap_bytes=args.memory_cap_bytes,
            output=output,
            host_notes_extra=args.host_notes,
            promotional=True,
        )
        write_manifest(run_dir, run_id, 'bench', records, {
            'bench_output': str(output.resolve()),
            'samples_jsonl': report['samples_jsonl'],
            'samples_per_size': args.samples,
            'seed': args.seed,
        })
        print('Saved ' + str(output))
        print('Samples ' + report['samples_jsonl'])
        print('Run ' + run_id + ' -> ' + str(run_dir / 'manifest.json'))
    except (RuntimeError, FileNotFoundError, FileExistsError, MemoryError,
            subprocess.CalledProcessError, subprocess.TimeoutExpired, ValueError) as exc:
        print('ERROR: ' + str(exc), file=sys.stderr)
        if isinstance(exc, subprocess.CalledProcessError) and exc.stderr:
            print(exc.stderr, file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
