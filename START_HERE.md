# Open this folder in Cursor

**Current status:** review fixes await native validation (T009R). Follow [docs/NEXT_CURSOR_PLAN.md](docs/NEXT_CURSOR_PLAN.md) before expanding the kernel portfolio.

Extract the ZIP, then use **Open Folder** on `axiom-asm-lab` (the directory containing this file). The folder includes `.cursor/rules/axiom.mdc`, root `AGENTS.md`, source code, specs, a task ledger, and completion criteria.

Paste this into Cursor Agent:

> Read AGENTS.md and START_HERE.md, then the project specification, implementation plan, acceptance criteria, and project/status.json. Implement the first unblocked task and continue through the dependency chain. Follow the test/repair/retest workflow, record evidence, and update the session log. Preserve the long-term assembly-to-language objective. Do not label unexecuted native tests as passed. Start by inspecting the host and the existing bootstrap code; treat M001 as incomplete until native evidence exists.

## Initial commands

```sh
python3 scripts/check_project.py
python3 -m unittest discover -s tests -v
python3 lab.py doctor
python3 lab.py verify
python3 lab.py search --dir build/searches/smoke --smoke --provider catalog --max-proposals 2 --samples 3
python3 lab.py search --dir build/searches/run1 --provider catalog --max-proposals 5 --samples 30 --seed 1
```

The last four require Apple Silicon macOS. Search without `--smoke` enforces the full measurement protocol (30 pairs, all objective sizes, confirmation when eligible). Time budgets count **active evaluation seconds** only.

## What is here now
A shared build/verify/measure pipeline, paired Clang comparisons, catalog scalar/unrolled/NEON variants, search ranking and confirmation, guard-page and ABI checks, and a limited language template prototype. See NEXT_CURSOR_PLAN for concrete recovery/evidence work still outstanding.

## Document map
- PROJECT_SPEC: goals, requirements, limits, success definition.
- ARCHITECTURE: subsystem boundaries and interfaces.
- IMPLEMENTATION_PLAN: ordered work and per-task completion checks.
- ACCEPTANCE: measurable gates and definition of done.
- TEST_FLOW: developer workflow and failure handling.
- BENCHMARK_PROTOCOL: experimental design and promotion rules.
- AI_WORKFLOW: provider-neutral model proposal pipeline.
- LANGUAGE_ROADMAP: route from assembly experiments to a language.
- SESSION_LOG and project/status.json: continuity across sessions.

All documents above are in docs/ unless a different path is stated. Existing DESIGN, TESTING, BENCHMARK, AI_INTEGRATION, LANGUAGE, and MILESTONES files describe the bootstrap; the new detailed specifications define subsequent implementation. Where they differ, current source describes implemented behavior and the new specs describe required target behavior. Never silently claim target behavior already exists.

Cursor rule format reference: https://cursor.com/docs/rules . Rules provide agent guidance; executable checks and recorded evidence remain necessary.
