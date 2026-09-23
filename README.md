# Cursor project package

**Start with [START_HERE.md](START_HERE.md).** It contains the Cursor kickoff prompt and development workflow. See [AGENTS.md](AGENTS.md) for agent instructions and [docs/IMPLEMENTATION_PLAN.md](docs/IMPLEMENTATION_PLAN.md) for the ordered backlog. The code below is the initial bootstrap, with native acceptance still pending.

# Axiom Assembly Lab

An assembly-first research starter for Apple Silicon (macOS arm64). The first kernel is a wrapping sum of `uint64_t` values. Two assembly candidates compete with a Clang `-O3` C baseline. A separate executable verifies each implementation before any benchmark.

## Requirements

- Apple Silicon Mac, macOS, Xcode Command Line Tools (`xcode-select --install`)
- Python 3.10+; no Python packages or API keys

```sh
python3 lab.py doctor
python3 lab.py verify
python3 lab.py bench --samples 15 --output results/run.json
python3 -m unittest discover -s tests -v
```

`bench` verifies all variants first, then writes reproducible JSON including toolchain, host, source SHA-256, sizes, samples, and median ns/call. Results will depend on CPU load and power state. The bench invokes functions through a native executable with a monotonic clock. The C baseline and assembly functions share the same harness, inputs, and call overhead.

To try a candidate, create `candidates/my_name.s` exporting `_sum_array`. Run `python3 lab.py verify --candidate my_name` then `python3 lab.py bench --candidate my_name`. The controller accepts only simple filename stems in the candidates directory; every candidate is separately compiled and linked. Treat submitted assembly as executable code, and review it before running.

The runner is intentionally macOS arm64 only. This Linux workspace cannot execute the native assembly; run the commands above on your Mac. See `docs/` for design, milestones, verification, benchmark protocol, AI workflow, and proposed language semantics.
