# Open this folder in Cursor

Extract the ZIP, then use **Open Folder** on `axiom-asm-lab` (the directory containing this file). The folder includes `.cursor/rules/axiom.mdc`, root `AGENTS.md`, source code, specs, a task ledger, and completion criteria.

Paste this into Cursor Agent:

> Read AGENTS.md and START_HERE.md, then the project specification, implementation plan, acceptance criteria, and project/status.json. Implement the first unblocked task and continue through the dependency chain. Follow the test/repair/retest workflow, record evidence, and update the session log. Preserve the long-term assembly-to-language objective. Do not label unexecuted native tests as passed. Start by inspecting the host and the existing bootstrap code; treat M001 as incomplete until native evidence exists.

## Initial commands

```sh
python3 scripts/check_project.py
python3 -m unittest discover -s tests -v
python3 lab.py doctor
python3 lab.py verify
python3 lab.py bench --samples 15 --output results/initial.json
```

The last three require Apple Silicon macOS. No Python dependencies are required for the bootstrap. Install Xcode Command Line Tools if `clang` is absent. The optional editor task file exposes the same commands.

## What is here now
Two sum assembly fixtures, a C baseline, a basic verifier, a sequential benchmark controller, and a development specification. Existing source is intentionally small. Guard pages, ABI validation, reliable performance promotion, model adapters, hardware exploration, and a language front end remain explicit implementation tasks.

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
