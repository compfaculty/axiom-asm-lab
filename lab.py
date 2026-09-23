#!/usr/bin/env python3
"""Compile, verify and benchmark isolated AArch64 assembly candidates."""
import argparse
import hashlib
import json
import platform
import re
import shutil
import statistics
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SIZES = (0, 1, 3, 4, 7, 16, 64, 1024, 65536, 1048576)


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


def sources(candidate=None):
    if candidate:
        if not re.fullmatch(r'[A-Za-z0-9_-]+', candidate):
            raise ValueError('Candidate name must be a simple filename stem')
        path = ROOT / 'candidates' / (candidate + '.s')
        if not path.is_file():
            raise FileNotFoundError(path)
        return {candidate: path}
    return {'clang_o3': ROOT / 'src/reference.c',
            'scalar': ROOT / 'asm/scalar.s',
            'unrolled4': ROOT / 'asm/unrolled4.s'}


def compile_one(name, source):
    build = ROOT / 'build'
    build.mkdir(exist_ok=True)
    binary = build / ('harness_' + name)
    run(['clang', '-O3', '-std=c11', '-Wall', '-Wextra',
         str(ROOT / 'src/harness.c'), str(source), '-o', str(binary)])
    return binary


def verify(binary):
    output = run([str(binary), 'verify'], timeout=60)
    if output != 'PASS':
        raise RuntimeError('Unexpected verification output: ' + output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('doctor')
    for action in ('verify', 'bench'):
        cmd = sub.add_parser(action)
        cmd.add_argument('--candidate', help='Filename stem in candidates/')
        if action == 'bench':
            cmd.add_argument('--samples', type=int, default=15)
            cmd.add_argument('--output', type=Path, default=ROOT / 'results/run.json')
    args = parser.parse_args()
    try:
        doctor()
        if args.command == 'doctor':
            print(platform.platform(), run(['clang', '--version']).splitlines()[0]); return
        if args.command == 'bench' and not 3 <= args.samples <= 100:
            parser.error('--samples must be between 3 and 100')
        entries = {}
        for name, source in sources(args.candidate).items():
            binary = compile_one(name, source)
            verify(binary)
            print(name + ': PASS', flush=True)
            if args.command == 'bench':
                entries[name] = {'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
                                 'binary_bytes': binary.stat().st_size, 'sizes': {}}
        if args.command != 'bench': return
        # Interleave candidates per size to reduce bias from sustained clock drift.
        for n in SIZES:
            for name in entries:
                binary = ROOT / 'build' / ('harness_' + name)
                samples = [float(s) for s in run([str(binary), 'bench', str(n),
                                                   str(args.samples)], timeout=180).splitlines()]
                entries[name]['sizes'][str(n)] = {
                    'ns_per_call': samples, 'median_ns': statistics.median(samples)}
                print(f'{name:12} n={n:8} median={statistics.median(samples):12.3f} ns', flush=True)
        report = {'schema': 1, 'timestamp_utc': datetime.now(timezone.utc).isoformat(),
                  'host': platform.platform(), 'machine': platform.machine(),
                  'clang': run(['clang', '--version']).splitlines()[0],
                  'samples_per_size': args.samples, 'variants': entries}
        output = args.output.resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2) + '\n')
        print('Saved ' + str(output))
    except (RuntimeError, FileNotFoundError, subprocess.CalledProcessError,
            subprocess.TimeoutExpired, ValueError) as exc:
        print('ERROR: ' + str(exc), file=sys.stderr)
        if isinstance(exc, subprocess.CalledProcessError) and exc.stderr:
            print(exc.stderr, file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
