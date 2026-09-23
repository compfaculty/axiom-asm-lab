"""Bounded offline search with atomic state, resume-by-hash, and optional provider hook."""
from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Protocol

from proposals import ProposalError, import_proposal, mock_propose, sha256_text, validate_proposal


@dataclass
class SearchBudgets:
    max_proposals: int = 20
    max_seconds: float = 1800.0
    max_stagnation: int = 5


@dataclass
class AttemptRecord:
    attempt_id: str
    candidate_id: str
    source_sha256: str
    stage: str  # proposed|imported|built|verified|failed|skipped
    stop_reason: Optional[str] = None
    detail: Dict[str, Any] = field(default_factory=dict)


class Provider(Protocol):
    """Optional proposal provider. Offline mock needs no API key."""

    def propose(self, index: int, root: Path) -> Dict[str, Any]:
        ...


class OfflineMockProvider:
    def propose(self, index: int, root: Path) -> Dict[str, Any]:
        proposal = mock_propose(root, candidate_id=f'mock_search_{index:04d}')
        # Unique source per index so budgets exercise distinct attempts.
        proposal['source'] = proposal['source'].rstrip() + f'\n// search_index={index}\n'
        proposal['hypothesis'] = (
            proposal['hypothesis'] + f' search_index={index} (no measured claim).')
        validate_proposal(proposal, root)
        return proposal


def get_provider(mode: str = 'offline') -> Provider:
    mode = (mode or 'offline').lower()
    if mode == 'offline':
        return OfflineMockProvider()
    if mode == 'online':
        # Interface only: refuse unless explicitly configured later.
        if not os.environ.get('AXIOM_PROVIDER'):
            raise RuntimeError(
                'online provider not configured (set AXIOM_PROVIDER); offline mode needs no API key')
        raise RuntimeError('online provider adapter not implemented')
    raise RuntimeError('unknown provider mode: ' + mode)


def atomic_write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(payload, indent=2) + '\n')
    tmp.replace(path)


def load_search_state(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text())


class SearchController:
    def __init__(self, root: Path, search_dir: Path, budgets: SearchBudgets,
                 provider: Optional[Provider] = None,
                 evaluate_fn: Optional[Callable[..., AttemptRecord]] = None):
        self.root = root
        self.search_dir = search_dir
        self.budgets = budgets
        self.provider = provider or get_provider('offline')
        self.evaluate_fn = evaluate_fn or default_evaluate_attempt
        self.state_path = search_dir / 'search_state.json'

    def _empty_state(self) -> Dict[str, Any]:
        return {
            'schema': 1,
            'search_id': self.search_dir.name,
            'budgets': asdict(self.budgets),
            'started_utc': time.time(),
            'provider_mode': 'offline',
            'attempts': [],
            'completed_source_sha256': [],
            'consecutive_no_improve': 0,
            'best_score': None,
            'stop_reason': None,
            'status': 'running',
        }

    def save(self, state: Dict[str, Any]) -> None:
        atomic_write_json(self.state_path, state)

    def load_or_init(self, resume: bool) -> Dict[str, Any]:
        if resume:
            if not self.state_path.is_file():
                raise FileNotFoundError('no search_state.json to resume: ' + str(self.state_path))
            state = load_search_state(self.state_path)
            # Allow continuing with possibly updated budgets from the controller.
            state['budgets'] = asdict(self.budgets)
            if state.get('status') in ('running', 'resuming', 'stopped'):
                state['status'] = 'resuming'
            return state
        if self.search_dir.exists() and any(self.search_dir.iterdir()):
            raise FileExistsError('search dir not empty; pass --resume or new dir')
        self.search_dir.mkdir(parents=True, exist_ok=True)
        state = self._empty_state()
        self.save(state)
        return state

    def stop_reason(self, state: Dict[str, Any], started: float) -> Optional[str]:
        if len(state['attempts']) >= self.budgets.max_proposals:
            return 'max_proposals'
        if (time.time() - started) >= self.budgets.max_seconds:
            return 'max_seconds'
        if state['consecutive_no_improve'] >= self.budgets.max_stagnation:
            return 'max_stagnation'
        return None

    def run(self, resume: bool = False) -> Dict[str, Any]:
        state = self.load_or_init(resume)
        started = state.get('wall_started') or time.time()
        state['wall_started'] = started
        state['status'] = 'running'
        self.save(state)

        done_hashes = set(state.get('completed_source_sha256') or [])
        index = len(state['attempts'])
        while True:
            reason = self.stop_reason(state, started)
            if reason:
                state['stop_reason'] = reason
                state['status'] = 'stopped'
                self.save(state)
                return state

            proposal = self.provider.propose(index, self.root)
            validate_proposal(proposal, self.root)
            src_hash = sha256_text(proposal['source'])
            if src_hash in done_hashes:
                attempt = AttemptRecord(
                    attempt_id=uuid.uuid4().hex[:12],
                    candidate_id=proposal['candidate_id'],
                    source_sha256=src_hash,
                    stage='skipped',
                    detail={'reason': 'duplicate_source_hash'},
                )
                state['attempts'].append(asdict(attempt))
                state['consecutive_no_improve'] += 1
                self.save(state)
                index += 1
                continue

            attempt = self.evaluate_fn(self.root, self.search_dir, proposal, index)
            state['attempts'].append(asdict(attempt))
            done_hashes.add(src_hash)
            state['completed_source_sha256'] = sorted(done_hashes)

            improved = bool(attempt.detail.get('improved'))
            if attempt.stage == 'verified' and improved:
                state['consecutive_no_improve'] = 0
                state['best_score'] = attempt.detail.get('score')
            else:
                # Correct-but-no-improve and failures both count toward stagnation
                # when the attempt completed evaluation (not skip-only duplicates above).
                if attempt.stage in ('verified', 'failed', 'built'):
                    state['consecutive_no_improve'] += 1

            self.save(state)
            index += 1

        return state


def default_evaluate_attempt(root: Path, search_dir: Path, proposal: Dict[str, Any],
                             index: int) -> AttemptRecord:
    """Import + record stages without promoting; used by unit tests / dry path.

    Native compile/verify is wired from lab.search_native_evaluate.
    """
    attempt_id = uuid.uuid4().hex[:12]
    run_dir = search_dir / 'attempts' / f'{index:04d}_{attempt_id}'
    run_dir.mkdir(parents=True, exist_ok=False)
    try:
        imported = import_proposal(proposal, run_dir, root)
    except (ProposalError, FileExistsError, OSError) as exc:
        return AttemptRecord(
            attempt_id=attempt_id,
            candidate_id=str(proposal.get('candidate_id')),
            source_sha256=sha256_text(proposal.get('source', '')),
            stage='failed',
            detail={'error': str(exc), 'phase': 'import'},
        )
    # Dry evaluation: treat successful import as verified-without-improve for budgets.
    atomic_write_json(run_dir / 'attempt.json', {
        'attempt_id': attempt_id,
        'imported': imported,
        'stage': 'imported',
    })
    return AttemptRecord(
        attempt_id=attempt_id,
        candidate_id=proposal['candidate_id'],
        source_sha256=imported['source_sha256'],
        stage='verified',
        detail={'improved': False, 'score': None, 'imported': imported, 'dry': True},
    )


def refuse_stale_promotion(record: Dict[str, Any], promote: Callable[[], None]) -> None:
    """Promotion gate: stale/failed lifecycles cannot promote."""
    life = record.get('lifecycle')
    if life in ('stale', 'failed', 'built'):
        raise RuntimeError('refusing to promote candidate with lifecycle ' + str(life))
    if record.get('verification', {}).get('state') != 'pass':
        raise RuntimeError('refusing to promote unverified candidate')
    promote()
