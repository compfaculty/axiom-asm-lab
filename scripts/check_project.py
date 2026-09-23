#!/usr/bin/env python3
"""Validate project packet and task evidence bookkeeping, not code correctness."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REQUIRED = ['START_HERE.md', 'AGENTS.md', '.cursor/rules/axiom.mdc',
            'docs/PROJECT_SPEC.md', 'docs/ARCHITECTURE.md',
            'docs/IMPLEMENTATION_PLAN.md', 'docs/ACCEPTANCE.md',
            'docs/TEST_FLOW.md', 'docs/BENCHMARK_PROTOCOL.md',
            'docs/AI_WORKFLOW.md', 'docs/LANGUAGE_ROADMAP.md',
            'docs/SESSION_LOG.md', 'templates/EVIDENCE.md']


def validate(root, data):
    errors = []
    if data.get('schema_version') != 1:
        errors.append('Unsupported status schema')
    tasks = data.get('tasks', [])
    ids = [t.get('id') for t in tasks]
    if not tasks or len(set(ids)) != len(ids):
        errors.append('Task IDs must be nonempty and unique')
    states = {t.get('id'): t.get('state') for t in tasks}
    for task in tasks:
        name = task.get('id', '<missing>')
        state = task.get('state')
        if state not in ('pending', 'in_progress', 'blocked', 'done'):
            errors.append(f'{name}: invalid state')
        deps = task.get('depends_on', [])
        if any(d not in states or d == name for d in deps):
            errors.append(f'{name}: invalid dependency')
        if state == 'blocked' and not task.get('blocker'):
            errors.append(f'{name}: blocked without reason')
        if state == 'done':
            if any(states.get(d) != 'done' for d in deps):
                errors.append(f'{name}: dependency not done')
            evidence = task.get('evidence')
            if not isinstance(evidence, str):
                errors.append(f'{name}: missing evidence')
                continue
            path = (root / evidence).resolve()
            if not path.is_relative_to(root.resolve()) or not path.is_file():
                errors.append(f'{name}: evidence must be an existing project file')
            elif not path.read_text().strip():
                errors.append(f'{name}: empty evidence')
    return errors


def main():
    errors = [f'Missing {p}' for p in REQUIRED if not (ROOT / p).is_file()]
    try:
        errors += validate(ROOT, json.loads((ROOT / 'project/status.json').read_text()))
    except (OSError, ValueError, TypeError) as exc:
        errors.append(str(exc))
    if errors:
        print('\n'.join(errors))
        return 1
    print('PASS: packet and task bookkeeping. Native correctness/performance remain separate gates.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
