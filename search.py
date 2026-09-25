"""Bounded offline search with ranking, confirmation, and recoverable state.

Time budget counts active evaluation seconds only (not idle gaps between resumes).

Incumbent replacement policy: a challenger may replace ``accepted`` only when it
has a documented promotion vs Clang *and* its aggregate score strictly exceeds the
incumbent's score. Independently beating Clang is not proof of beating the
incumbent.
"""
from __future__ import annotations

import fcntl
import json
import hashlib
import inspect
import os
import signal
import subprocess
import sys
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Protocol, TextIO

from analysis import (
    classify_promotion,
    classify_session,
    extract_medians,
    extract_paired_ns,
    validate_report,
)
from evaluate import (
    NORMALIZED_COMPILE_FLAGS,
    PROTOCOL_SIZES,
    SMOKE_TARGET_NS,
    evaluation_config,
)
from proposals import ProposalError, import_proposal, mock_propose, sha256_text, validate_proposal
from sampling import DEFAULT_MEMORY_CAP_BYTES, TARGET_SAMPLE_NS, cpu_brand


# Conservative charge applied when an in-flight attempt dies without a finer checkpoint.
CONSERVATIVE_INTERRUPT_CHARGE_SECONDS = 1.0

INCUMBENT_POLICY = {
    'rule': 'challenger_score_must_strictly_exceed_incumbent',
    'note': (
        'Promotion vs clang_o3 is necessary but not sufficient to replace an '
        'accepted incumbent; aggregate bootstrap score must be strictly higher.'
    ),
}


@dataclass
class SearchBudgets:
    max_proposals: int = 20
    max_seconds: float = 1800.0  # active evaluation seconds
    max_stagnation: int = 5


@dataclass
class AttemptRecord:
    attempt_id: str
    candidate_id: str
    source_sha256: str
    stage: str
    stop_reason: Optional[str] = None
    detail: Dict[str, Any] = field(default_factory=dict)


class Provider(Protocol):
    def propose(self, index: int, root: Path) -> Dict[str, Any]:
        ...


class OfflineMockProvider:
    """Pipeline fixture: scalar copies with unique comments (not real variants)."""

    def propose(self, index: int, root: Path) -> Dict[str, Any]:
        proposal = mock_propose(root, candidate_id=f'mock_search_{index:04d}')
        proposal['source'] = proposal['source'].rstrip() + f'\n// search_index={index}\n'
        proposal['hypothesis'] = (
            proposal['hypothesis'] + f' search_index={index} (no measured claim).')
        validate_proposal(proposal, root)
        return proposal


CATALOG_ENTRIES = (
    ('catalog_scalar', 'asm/scalar.s', 'Existing scalar sum_u64.'),
    ('catalog_unrolled4', 'asm/unrolled4.s', 'Existing four-accumulator unroll.'),
    ('catalog_neon', 'asm/neon_sum.s', 'NEON 2x uint64x2 with scalar tail.'),
    ('catalog_unrolled2', 'asm/unrolled2.s', 'Two-accumulator unroll.'),
    ('catalog_unrolled8', 'asm/unrolled8.s', 'Eight-wide unroll with scalar tail.'),
)


class OfflineCatalogProvider:
    """Deterministic real implementation variants; exhausted after catalog length."""

    def propose(self, index: int, root: Path) -> Dict[str, Any]:
        import hashlib
        if index >= len(CATALOG_ENTRIES):
            raise StopIteration('catalog exhausted')
        cand_id, rel, hypothesis = CATALOG_ENTRIES[index]
        src_path = root / rel
        source = src_path.read_text()
        parent = hashlib.sha256(src_path.read_bytes()).hexdigest()
        proposal = {
            'schema_version': 1,
            'candidate_id': cand_id,
            'kernel_id': 'sum_u64',
            'contract_version': 1,
            'parent_source_sha256': parent,
            'hypothesis': hypothesis,
            'source': source,
            'expected_size_range': [0, 1048576],
            'provenance': {
                'mode': 'offline',
                'provider': 'catalog',
                'catalog_index': index,
                'source_path': rel,
            },
        }
        validate_proposal(proposal, root)
        return proposal


def get_provider(mode: str = 'catalog') -> Provider:
    mode = (mode or 'catalog').lower()
    if mode == 'catalog':
        return OfflineCatalogProvider()
    if mode in ('mock', 'offline'):
        return OfflineMockProvider()
    if mode == 'online':
        if not os.environ.get('AXIOM_PROVIDER'):
            raise RuntimeError(
                'online provider not configured (set AXIOM_PROVIDER); offline needs no API key')
        raise RuntimeError('online provider adapter not implemented')
    raise RuntimeError('unknown provider mode: ' + mode)


def host_session_identity() -> Dict[str, Any]:
    """Concrete CPU + normalized compiler config for resume/session fingerprints."""
    try:
        import lab as L
        clang = L.clang_identity()
    except Exception:
        clang = None
    return {
        'cpu_brand': cpu_brand(),
        'machine': os.uname().machine if hasattr(os, 'uname') else None,
        'clang': clang,
        'compiler_config': {
            'baseline_flags': list(NORMALIZED_COMPILE_FLAGS),
            'candidate_flags': list(NORMALIZED_COMPILE_FLAGS),
        },
    }


def beats_incumbent(incumbent: Dict[str, Any], challenger: Dict[str, Any]) -> bool:
    """Return True if challenger may replace incumbent under INCUMBENT_POLICY."""
    if not incumbent:
        return True
    try:
        inc_score = float(incumbent.get('score'))
        ch_score = float(challenger.get('score'))
    except (TypeError, ValueError):
        return False
    return ch_score > inc_score


class SearchDirLock:
    """Exclusive lock so two controllers cannot write one search_state.json."""

    def __init__(self, search_dir: Path):
        self.search_dir = Path(search_dir)
        self.lock_path = self.search_dir / '.search.lock'
        self._fh: Optional[TextIO] = None

    def __enter__(self) -> 'SearchDirLock':
        self.search_dir.mkdir(parents=True, exist_ok=True)
        self._fh = open(self.lock_path, 'a+', encoding='utf-8')
        try:
            fcntl.flock(self._fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            self._fh.close()
            self._fh = None
            raise RuntimeError(
                'search directory locked by another controller: ' + str(self.search_dir)
            ) from exc
        self._fh.seek(0)
        self._fh.truncate()
        self._fh.write(f'pid={os.getpid()}\n')
        self._fh.flush()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._fh is not None:
            try:
                fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
            finally:
                self._fh.close()
                self._fh = None


def atomic_write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(payload, indent=2) + '\n')
    tmp.replace(path)


def load_search_state(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text())


def validate_measurement_evidence(report_path: Path, *, expect_samples: bool = True) -> Dict[str, Any]:
    """Authenticate an on-disk measurement report before reusing rankings."""
    report_path = Path(report_path)
    if not report_path.is_file():
        raise ValueError('missing measurement report: ' + str(report_path))
    report = json.loads(report_path.read_text())
    if report.get('schema') != 2:
        raise ValueError('unsupported measurement schema')
    if not report.get('run_id'):
        raise ValueError('measurement missing run_id')
    variants = report.get('variants') or {}
    if not variants:
        raise ValueError('measurement missing variants')
    for name, var in variants.items():
        for key in ('source_sha256', 'harness_sha256', 'abi_wrap_sha256', 'binary_sha256'):
            val = var.get(key)
            if not val or not isinstance(val, str):
                raise ValueError(f'{name} missing {key}')
        binary = var.get('binary_path')
        if binary:
            bpath = Path(binary)
            if bpath.is_file():
                digest = hashlib.sha256(bpath.read_bytes()).hexdigest()
                if digest != var.get('binary_sha256'):
                    raise ValueError(f'{name} binary hash mismatch')
    if expect_samples:
        samples = report.get('samples_jsonl')
        if not samples or not Path(samples).is_file():
            # Fall back to sibling samples.jsonl next to the report.
            sibling = report_path.parent / 'samples.jsonl'
            if not sibling.is_file():
                raise ValueError('missing samples.jsonl for measurement')
    return report


def revalidate_persisted_rankings(state: Dict[str, Any]) -> None:
    """Validate stored measurement files before trusting best_observed / accepted."""
    for key in ('best_observed', 'accepted'):
        entry = state.get(key)
        if not entry or not isinstance(entry, dict):
            continue
        paths: List[str] = []
        if entry.get('report'):
            paths.append(str(entry['report']))
        session = entry.get('session') or {}
        if session.get('report_path'):
            paths.append(str(session['report_path']))
        for sk in ('session_a', 'session_b'):
            sub = entry.get(sk) or {}
            if sub.get('report_path'):
                paths.append(str(sub['report_path']))
        for path in paths:
            validate_measurement_evidence(Path(path), expect_samples=True)


def session_identity_from_report(report: Dict[str, Any], baseline: str,
                                 candidate: str) -> Dict[str, Any]:
    b = report['variants'][baseline]
    c = report['variants'][candidate]
    return {
        'host': report.get('host'),
        'machine': report.get('machine'),
        'cpu_brand': report.get('cpu_brand') or (report.get('host_notes') or {}).get('cpu_brand'),
        'clang': report.get('clang'),
        'compiler_config': report.get('compiler_config') or {
            'baseline_flags': list(NORMALIZED_COMPILE_FLAGS),
            'candidate_flags': list(NORMALIZED_COMPILE_FLAGS),
        },
        'baseline_source_sha256': b.get('source_sha256'),
        'candidate_source_sha256': c.get('source_sha256'),
        'harness_sha256': c.get('harness_sha256'),
        'abi_wrap_sha256': c.get('abi_wrap_sha256'),
        'measure_sizes': list(report.get('measure_sizes') or []),
        'samples_per_size': report.get('samples_per_size'),
        'target_sample_ns': report.get('target_sample_ns'),
        'kernel': 'sum_u64',
    }


def rank_from_report(report: Dict[str, Any], baseline: str, candidate: str,
                     expected_sizes, bootstrap_seed: int = 1) -> Dict[str, Any]:
    """Validate protocol report and classify one session. Failed candidates get no score."""
    validate_report(report, baseline, candidate, expected_sizes)
    med_b = extract_medians(report, baseline)
    med_c = extract_medians(report, candidate)
    paired = extract_paired_ns(report, baseline, candidate)
    session = classify_session(med_b, med_c, paired=paired, bootstrap_seed=bootstrap_seed)
    session['run_id'] = report['run_id']
    session['identity'] = session_identity_from_report(report, baseline, candidate)
    session['score'] = session.get('bootstrap', {}).get('aggregate_speedup')
    session['report_path'] = None
    return session


def refuse_stale_promotion(record: Dict[str, Any], promote: Callable[[], None]) -> None:
    life = record.get('lifecycle')
    if life in ('stale', 'failed', 'built'):
        raise RuntimeError('refusing to promote candidate with lifecycle ' + str(life))
    if record.get('verification', {}).get('state') != 'pass':
        raise RuntimeError('refusing to promote unverified candidate')
    promote()


class SearchController:
    def __init__(self, root: Path, search_dir: Path, budgets: SearchBudgets,
                 provider: Optional[Provider] = None,
                 evaluate_fn: Optional[Callable[..., AttemptRecord]] = None,
                 smoke: bool = False,
                 samples: int = 30,
                 seed: int = 1,
                 provider_mode: str = 'catalog',
                 memory_cap_bytes: int = DEFAULT_MEMORY_CAP_BYTES):
        self.root = root
        self.search_dir = search_dir
        self.budgets = budgets
        self.provider = provider or get_provider('catalog')
        self.evaluate_fn = evaluate_fn or default_evaluate_attempt
        self.smoke = smoke
        self.samples = samples
        self.seed = seed
        self.provider_mode = provider_mode
        self.memory_cap_bytes = memory_cap_bytes
        self.state_path = search_dir / 'search_state.json'
        target_ns = SMOKE_TARGET_NS if smoke else TARGET_SAMPLE_NS
        self.eval_config = evaluation_config(
            protocol=not smoke,
            samples=samples,
            seed=seed,
            target_sample_ns=target_ns,
            memory_cap_bytes=memory_cap_bytes,
        )

    def _empty_state(self) -> Dict[str, Any]:
        return {
            'resume_identity': self.resume_identity(),
            'schema': 3,
            'search_id': self.search_dir.name,
            'budgets': asdict(self.budgets),
            'started_utc': time.time(),
            'provider_mode': self.provider_mode,
            'smoke': self.smoke,
            'evaluation_config': self.eval_config,
            'time_budget_mode': 'active_evaluation_seconds',
            'active_eval_seconds': 0.0,
            'next_proposal_index': 0,
            'in_flight': None,
            'incumbent_policy': dict(INCUMBENT_POLICY),
            'attempts': [],
            'completed_source_sha256': [],
            'consecutive_no_improve': 0,
            'best_observed': None,
            'accepted': None,
            'stop_reason': None,
            'status': 'running',
        }

    def save(self, state: Dict[str, Any]) -> None:
        atomic_write_json(self.state_path, state)

    def checkpoint_in_flight(self, state: Dict[str, Any], *, attempt_id: str,
                             proposal_index: int, stage: str,
                             source_sha256: Optional[str] = None,
                             candidate_id: Optional[str] = None,
                             charged_seconds: float = 0.0) -> None:
        """Persist mid-evaluation progress for crash recovery / conservative charging."""
        prev = state.get('in_flight') or {}
        started_wall = prev.get('started_wall') or time.time()
        state['in_flight'] = {
            'attempt_id': attempt_id,
            'proposal_index': proposal_index,
            'stage': stage,
            'source_sha256': source_sha256,
            'candidate_id': candidate_id,
            'started_wall': started_wall,
            'charged_seconds': float(charged_seconds),
            'updated_wall': time.time(),
        }
        self.save(state)

    def clear_in_flight(self, state: Dict[str, Any]) -> None:
        state['in_flight'] = None

    def load_or_init(self, resume: bool) -> Dict[str, Any]:
        if resume:
            if not self.state_path.is_file():
                raise FileNotFoundError('no search_state.json to resume: ' + str(self.state_path))
            state = load_search_state(self.state_path)
            self._validate_resume_config(state)
            try:
                revalidate_persisted_rankings(state)
            except (OSError, ValueError, KeyError, json.JSONDecodeError, TypeError) as exc:
                raise RuntimeError(
                    'persisted ranking failed evidence revalidation: ' + str(exc)
                ) from exc
            state['budgets'] = asdict(self.budgets)
            if state.get('status') in ('running', 'resuming', 'stopped'):
                state['status'] = 'resuming'
            return state
        if self.search_dir.exists() and any(
                p.name not in ('.search.lock',) for p in self.search_dir.iterdir()):
            # Allow empty dir that only has a stale lock file from a dead process.
            raise FileExistsError('search dir not empty; pass --resume or new dir')
        self.search_dir.mkdir(parents=True, exist_ok=True)
        state = self._empty_state()
        self.save(state)
        return state

    def resume_identity(self):
        """Reject reuse when evaluator, contracts, harness, catalog or host/compiler changed."""
        paths = sorted({p for pattern in ('*.py', 'kernels/*.py', 'src/*', 'asm/*.s')
                        for p in self.root.glob(pattern) if p.is_file()})
        artifacts = {str(p.relative_to(self.root)): hashlib.sha256(p.read_bytes()).hexdigest()
                     for p in paths}
        return {
            'artifacts': artifacts,
            'host': host_session_identity(),
        }

    def _validate_resume_config(self, state: Dict[str, Any]) -> None:
        expected = self.resume_identity()
        prev_identity = state.get('resume_identity')
        # Legacy flat sha maps are rejected: require host+artifact schema.
        if not isinstance(prev_identity, dict) or 'artifacts' not in prev_identity:
            raise RuntimeError('resume artifact identity changed or missing; start a new search directory')
        if prev_identity != expected:
            raise RuntimeError('resume artifact identity changed or missing; start a new search directory')
        prev = state.get('evaluation_config') or {}
        cur = self.eval_config
        for key in ('protocol', 'sizes', 'samples_per_size', 'target_sample_ns',
                    'memory_cap_bytes', 'kernel', 'seed', 'cpu_brand', 'compiler_config'):
            if key in prev and prev.get(key) != cur.get(key):
                raise RuntimeError(
                    f'resume evaluation_config mismatch on {key}: '
                    f'{prev.get(key)!r} vs {cur.get(key)!r}')
        if state.get('provider_mode') not in (None, self.provider_mode):
            raise RuntimeError('resume provider_mode mismatch')
        if 'smoke' in state and bool(state.get('smoke')) != bool(self.smoke):
            raise RuntimeError('resume smoke/protocol mode mismatch')

    COMPLETE_STAGES = frozenset({
        'measured', 'ranked', 'accepted', 'rejected', 'failed', 'skipped', 'imported',
    })
    INCOMPLETE_STAGES = frozenset({
        'proposed', 'built', 'verified', 'confirming',
    })

    def _charge_interrupted(self, state: Dict[str, Any], detail: Dict[str, Any]) -> None:
        charged = detail.get('charged_seconds')
        if charged is None:
            charged = CONSERVATIVE_INTERRUPT_CHARGE_SECONDS
        in_flight = state.get('in_flight') or {}
        if in_flight.get('started_wall'):
            wall = max(0.0, time.time() - float(in_flight['started_wall']))
            charged = max(float(charged), min(wall, float(self.budgets.max_seconds)))
        state['active_eval_seconds'] = float(state.get('active_eval_seconds') or 0) + float(charged)
        detail['charged_seconds'] = float(charged)
        detail['charge_policy'] = 'conservative_interrupt'

    def reconcile_incomplete_attempts(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """Mark interrupted mid-stage attempts failed and retryable; charge lost work.

        Retryable failures keep their proposal_index so the catalog entry is retried
        instead of silently skipped.
        """
        done = set(state.get('completed_source_sha256') or [])
        changed = False
        retry_indices: List[int] = []
        for attempt in state.get('attempts') or []:
            stage = attempt.get('stage')
            if stage in self.INCOMPLETE_STAGES:
                src = attempt.get('source_sha256')
                prior = stage
                attempt['stage'] = 'failed'
                detail = dict(attempt.get('detail') or {})
                detail['error'] = 'interrupted_incomplete_stage:' + str(prior)
                detail['prior_stage'] = prior
                detail['score'] = None
                detail['retryable'] = True
                if 'proposal_index' not in detail and attempt.get('proposal_index') is not None:
                    detail['proposal_index'] = attempt['proposal_index']
                if detail.get('proposal_index') is None:
                    # Fall back to position among attempts when older records omit the field.
                    detail['proposal_index'] = state['attempts'].index(attempt)
                attempt['proposal_index'] = detail['proposal_index']
                self._charge_interrupted(state, detail)
                attempt['detail'] = detail
                retry_indices.append(int(detail['proposal_index']))
                if src in done:
                    done.discard(src)
                changed = True
        # In-flight marker without a matching attempt record.
        in_flight = state.get('in_flight')
        if in_flight and in_flight.get('attempt_id'):
            ids = {a.get('attempt_id') for a in (state.get('attempts') or [])}
            if in_flight['attempt_id'] not in ids:
                detail = {
                    'error': 'interrupted_in_flight',
                    'prior_stage': in_flight.get('stage'),
                    'retryable': True,
                    'proposal_index': in_flight.get('proposal_index', 0),
                    'charged_seconds': in_flight.get('charged_seconds'),
                }
                self._charge_interrupted(state, detail)
                state.setdefault('attempts', []).append({
                    'attempt_id': in_flight['attempt_id'],
                    'candidate_id': in_flight.get('candidate_id') or 'in_flight',
                    'source_sha256': in_flight.get('source_sha256') or (
                        'in_flight_' + in_flight['attempt_id']),
                    'stage': 'failed',
                    'proposal_index': detail['proposal_index'],
                    'detail': detail,
                })
                retry_indices.append(int(detail['proposal_index']))
                changed = True
            state['in_flight'] = None
            changed = True
        # Orphan attempt dirs left by a crash before state append are incomplete
        # evidence. Charge time but do not treat them as catalog skip or retry
        # targets — in_flight / incomplete attempts own the proposal_index.
        attempts_root = self.search_dir / 'attempts'
        recorded_ids = {a.get('attempt_id') for a in (state.get('attempts') or [])}
        orphans = list(state.get('orphaned_attempts') or [])
        known_orphan_ids = {o.get('attempt_id') for o in orphans}
        if attempts_root.is_dir():
            for path in sorted(attempts_root.iterdir()):
                if not path.is_dir():
                    continue
                parts = path.name.split('_', 1)
                aid = parts[1] if len(parts) == 2 else path.name
                if aid in recorded_ids or aid in known_orphan_ids:
                    continue
                marker = path / 'attempt.json'
                stage = 'proposed'
                src_hash = None
                payload: Dict[str, Any] = {}
                if marker.is_file():
                    try:
                        payload = json.loads(marker.read_text())
                        stage = payload.get('stage') or stage
                        src_hash = payload.get('source_sha256')
                        if not src_hash and isinstance(payload.get('detail'), dict):
                            src_hash = payload['detail'].get('source_sha256')
                    except (OSError, json.JSONDecodeError, TypeError):
                        pass
                detail = {
                    'error': 'orphan_incomplete_attempt_dir',
                    'prior_stage': stage,
                    'path': str(path),
                    'score': None,
                    'retryable': False,
                }
                self._charge_interrupted(state, detail)
                orphan = {
                    'attempt_id': aid,
                    'candidate_id': payload_candidate(path),
                    'source_sha256': src_hash or ('orphan_' + aid),
                    'stage': 'failed',
                    'detail': detail,
                }
                orphans.append(orphan)
                if src_hash and src_hash in done:
                    done.discard(src_hash)
                changed = True
                atomic_write_json(path / 'attempt.json', orphan)
        state['orphaned_attempts'] = orphans
        state['completed_source_sha256'] = sorted(done)
        if retry_indices:
            # Retry the earliest interrupted catalog entry; do not skip ahead.
            state['next_proposal_index'] = min(retry_indices)
            changed = True
        if changed:
            state['status'] = 'resuming'
            self.save(state)
        return state

    def next_proposal_index(self, state: Dict[str, Any]) -> int:
        """Return catalog/proposal index, preferring retryable interrupted entries."""
        for attempt in state.get('attempts') or []:
            detail = attempt.get('detail') or {}
            if attempt.get('stage') == 'failed' and detail.get('retryable'):
                idx = detail.get('proposal_index', attempt.get('proposal_index'))
                if idx is not None:
                    return int(idx)
        if 'next_proposal_index' in state:
            return int(state['next_proposal_index'])
        return len(state.get('attempts') or [])

    def _mark_retry_consumed(self, state: Dict[str, Any], proposal_index: int,
                             new_attempt_id: str) -> None:
        for attempt in state.get('attempts') or []:
            detail = attempt.get('detail') or {}
            if (attempt.get('stage') == 'failed' and detail.get('retryable')
                    and int(detail.get('proposal_index', -1)) == proposal_index):
                detail['retryable'] = False
                detail['superseded_by'] = new_attempt_id
                attempt['detail'] = detail

    def stop_reason(self, state: Dict[str, Any]) -> Optional[str]:
        if len(state['attempts']) >= self.budgets.max_proposals:
            return 'max_proposals'
        if float(state.get('active_eval_seconds') or 0) >= self.budgets.max_seconds:
            return 'max_seconds'
        if state['consecutive_no_improve'] >= self.budgets.max_stagnation:
            return 'max_stagnation'
        return None

    def run(self, resume: bool = False) -> Dict[str, Any]:
        with SearchDirLock(self.search_dir):
            return self._run_locked(resume=resume)

    def _run_locked(self, resume: bool = False) -> Dict[str, Any]:
        state = self.load_or_init(resume)
        if resume:
            state = self.reconcile_incomplete_attempts(state)
        state['wall_started'] = state.get('wall_started') or time.time()
        state['status'] = 'running'
        state.setdefault('active_eval_seconds', 0.0)
        state.setdefault('next_proposal_index', self.next_proposal_index(state))
        state.setdefault('incumbent_policy', dict(INCUMBENT_POLICY))
        self.save(state)

        done_hashes = set(state.get('completed_source_sha256') or [])
        while True:
            reason = self.stop_reason(state)
            if reason:
                state['stop_reason'] = reason
                state['status'] = 'stopped'
                self.save(state)
                return state

            index = self.next_proposal_index(state)
            try:
                proposal = self.provider.propose(index, self.root)
            except StopIteration:
                state['stop_reason'] = 'catalog_exhausted'
                state['status'] = 'stopped'
                self.save(state)
                return state
            try:
                validate_proposal(proposal, self.root)
            except (ProposalError, TypeError) as exc:
                attempt = AttemptRecord(
                    attempt_id=uuid.uuid4().hex[:12],
                    candidate_id=str(proposal.get('candidate_id')) if isinstance(proposal, dict) else '<invalid>',
                    source_sha256=sha256_text(repr(proposal)),
                    stage='failed',
                    detail={'error': str(exc), 'phase': 'validate',
                            'proposal_index': index, 'retryable': False},
                )
                self._mark_retry_consumed(state, index, attempt.attempt_id)
                state['attempts'].append(asdict(attempt))
                state['consecutive_no_improve'] += 1
                state['next_proposal_index'] = index + 1
                self.save(state)
                continue

            src_hash = sha256_text(proposal['source'])
            if src_hash in done_hashes:
                attempt = AttemptRecord(
                    attempt_id=uuid.uuid4().hex[:12],
                    candidate_id=proposal['candidate_id'],
                    source_sha256=src_hash,
                    stage='skipped',
                    detail={'reason': 'duplicate_source_hash',
                            'proposal_index': index, 'retryable': False},
                )
                self._mark_retry_consumed(state, index, attempt.attempt_id)
                state['attempts'].append(asdict(attempt))
                state['consecutive_no_improve'] += 1
                state['next_proposal_index'] = index + 1
                self.save(state)
                continue

            attempt_id = uuid.uuid4().hex[:12]
            self.checkpoint_in_flight(
                state, attempt_id=attempt_id, proposal_index=index, stage='proposed',
                source_sha256=src_hash, candidate_id=proposal.get('candidate_id'),
                charged_seconds=0.0)
            t0 = time.monotonic()
            attempt = self._call_evaluate(proposal, index, state)
            elapsed = time.monotonic() - t0
            # Prefer evaluator-reported charge if present; else wall elapsed.
            detail = attempt.detail or {}
            charged = detail.get('eval_elapsed_seconds')
            if charged is None:
                charged = elapsed
            state['active_eval_seconds'] = float(state.get('active_eval_seconds') or 0) + float(charged)
            detail['proposal_index'] = index
            detail.setdefault('retryable', False)
            attempt.detail = detail
            rec = asdict(attempt)
            rec['proposal_index'] = index
            self._mark_retry_consumed(state, index, attempt.attempt_id)
            state['attempts'].append(rec)
            self.clear_in_flight(state)
            # Only completed evaluation stages consume the source hash.
            if attempt.stage not in self.INCOMPLETE_STAGES:
                done_hashes.add(src_hash)
                state['next_proposal_index'] = index + 1
            else:
                # Incomplete return: keep proposal_index for retry.
                detail['retryable'] = True
                attempt.detail = detail
                state['attempts'][-1] = asdict(attempt)
                state['attempts'][-1]['proposal_index'] = index
                state['next_proposal_index'] = index
            state['completed_source_sha256'] = sorted(done_hashes)

            self._update_ranking(state, attempt)
            # Reflect possible stage downgrade from incumbent policy.
            state['attempts'][-1] = asdict(attempt)
            state['attempts'][-1]['proposal_index'] = index
            self.save(state)

        return state

    def _call_evaluate(self, proposal, index, state):
        # Determine arity before invocation: an internal TypeError must not rerun work.
        signature = inspect.signature(self.evaluate_fn)
        args = (self.root, self.search_dir, proposal, index)
        try:
            signature.bind(*args, state)
        except TypeError:
            signature.bind(*args)
            return self.evaluate_fn(*args)
        return self.evaluate_fn(*args, state)

    def _update_ranking(self, state: Dict[str, Any], attempt: AttemptRecord) -> None:
        detail = attempt.detail or {}
        stage = attempt.stage

        if stage not in ('measured', 'ranked', 'accepted', 'rejected'):
            if stage in ('imported', 'verified', 'failed', 'built', 'proposed', 'confirming'):
                state['consecutive_no_improve'] += 1
            return

        score = detail.get('score')
        session = detail.get('session') or {}
        best = state.get('best_observed')
        improved = False
        if score is not None and isinstance(score, (int, float)):
            if best is None or score > float(best.get('score') or float('-inf')):
                state['best_observed'] = {
                    'candidate_id': attempt.candidate_id,
                    'attempt_id': attempt.attempt_id,
                    'source_sha256': attempt.source_sha256,
                    'score': score,
                    'decision': session.get('decision'),
                    'report': detail.get('report'),
                    'session': session,
                }
                improved = True
                state['consecutive_no_improve'] = 0
            else:
                state['consecutive_no_improve'] += 1
        else:
            # Measured without score (smoke): count toward stagnation.
            state['consecutive_no_improve'] += 1

        if detail.get('accepted'):
            challenger = detail['accepted']
            incumbent = state.get('accepted')
            if incumbent and not beats_incumbent(incumbent, challenger):
                detail['rejection_reason'] = (
                    'incumbent_policy: challenger does not beat incumbent score')
                detail['incumbent_policy'] = dict(INCUMBENT_POLICY)
                detail.pop('accepted', None)
                attempt.stage = 'rejected'
                attempt.detail = detail
            else:
                state['accepted'] = challenger

        attempt.detail['improved'] = improved

    def write_summary(self, state: Dict[str, Any]) -> Path:
        lines = [
            '# Search summary',
            '',
            f"- search_id: `{state.get('search_id')}`",
            f"- status: `{state.get('status')}`",
            f"- stop_reason: `{state.get('stop_reason')}`",
            f"- time_budget_mode: `{state.get('time_budget_mode')}`",
            f"- active_eval_seconds: `{state.get('active_eval_seconds')}`",
            f"- provider: `{state.get('provider_mode')}`",
            f"- smoke: `{state.get('smoke')}`",
            '',
            '## Best observed',
            '',
            '```json',
            json.dumps(state.get('best_observed'), indent=2),
            '```',
            '',
            '## Accepted',
            '',
            '```json',
            json.dumps(state.get('accepted'), indent=2),
            '```',
            '',
            '## Attempts',
            '',
        ]
        for a in state.get('attempts') or []:
            d = a.get('detail') or {}
            lines.append(
                f"- `{a.get('candidate_id')}` stage=`{a.get('stage')}` "
                f"score=`{d.get('score')}` decision=`{(d.get('session') or {}).get('decision')}` "
                f"reject=`{d.get('rejection_reason')}`"
            )
        path = self.search_dir / 'search_summary.md'
        path.write_text('\n'.join(lines) + '\n')
        return path


def payload_candidate(attempt_dir: Path) -> str:
    marker = attempt_dir / 'attempt.json'
    if marker.is_file():
        try:
            data = json.loads(marker.read_text())
            cid = data.get('candidate_id')
            if cid:
                return str(cid)
        except (OSError, json.JSONDecodeError, TypeError):
            pass
    inp = attempt_dir / 'input.json'
    if inp.is_file():
        try:
            return str(json.loads(inp.read_text()).get('candidate_id') or 'unknown')
        except (OSError, json.JSONDecodeError, TypeError):
            pass
    return 'unknown'


def default_evaluate_attempt(root: Path, search_dir: Path, proposal: Dict[str, Any],
                             index: int, state: Optional[Dict[str, Any]] = None
                             ) -> AttemptRecord:
    """Import-only dry path for unit tests."""
    attempt_id = uuid.uuid4().hex[:12]
    run_dir = search_dir / 'attempts' / f'{index:04d}_{attempt_id}'
    run_dir.mkdir(parents=True, exist_ok=False)
    atomic_write_json(run_dir / 'attempt.json', {
        'attempt_id': attempt_id,
        'stage': 'proposed',
        'candidate_id': proposal.get('candidate_id'),
    })
    try:
        imported = import_proposal(proposal, run_dir, root)
    except (ProposalError, FileExistsError, OSError) as exc:
        rec = AttemptRecord(
            attempt_id=attempt_id,
            candidate_id=str(proposal.get('candidate_id')),
            source_sha256=sha256_text(proposal.get('source', '')),
            stage='failed',
            detail={'error': str(exc), 'phase': 'import'},
        )
        atomic_write_json(run_dir / 'attempt.json', asdict(rec))
        return rec
    atomic_write_json(run_dir / 'attempt.json', {
        'attempt_id': attempt_id,
        'imported': imported,
        'stage': 'imported',
    })
    return AttemptRecord(
        attempt_id=attempt_id,
        candidate_id=proposal['candidate_id'],
        source_sha256=imported['source_sha256'],
        stage='imported',
        detail={'improved': False, 'score': None, 'imported': imported, 'dry': True},
    )


def _killpg(child: subprocess.Popen) -> None:
    try:
        os.killpg(child.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def _spawn_evaluate(root: Path, proposal_path: Path, output: Path,
                    remaining: float, extra_args: List[str]) -> Dict[str, Any]:
    if remaining <= 0:
        raise subprocess.TimeoutExpired('evaluate-proposal', 0)
    cmd = [sys.executable, str(root / 'lab.py'), 'evaluate-proposal',
           '--proposal', str(proposal_path), '--output', str(output)] + extra_args
    child = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        cwd=root, start_new_session=True)
    try:
        stdout, stderr = child.communicate(timeout=remaining)
    except subprocess.TimeoutExpired:
        _killpg(child)
        stdout, stderr = child.communicate()
        raise subprocess.TimeoutExpired(cmd, remaining, output=stdout, stderr=stderr)
    return {
        'returncode': child.returncode,
        'stdout': stdout,
        'stderr': stderr,
    }


def make_evaluate_fn(*, smoke: bool, samples: int, seed: int,
                     memory_cap_bytes: int = DEFAULT_MEMORY_CAP_BYTES
                     ) -> Callable[..., AttemptRecord]:
    def _evaluate(root, search_dir, proposal, index, state=None):
        return native_evaluate_attempt(
            root, search_dir, proposal, index, state=state,
            smoke=smoke, samples=samples, seed=seed,
            memory_cap_bytes=memory_cap_bytes)
    return _evaluate


def native_evaluate_attempt(root, search_dir, proposal, index, state=None,
                            smoke: bool = False, samples: int = 30, seed: int = 1,
                            memory_cap_bytes: int = DEFAULT_MEMORY_CAP_BYTES,
                            confirm: bool = True):
    """Native evaluate with optional ranking and confirmation."""
    if state is None:
        state = load_search_state(search_dir / 'search_state.json')
    in_flight = state.get('in_flight') or {}
    attempt_id = in_flight.get('attempt_id') or uuid.uuid4().hex[:12]
    dest = search_dir / 'attempts' / f'{index:04d}_{attempt_id}'
    dest.mkdir(parents=True, exist_ok=False)
    proposal_path = dest / 'input.json'
    atomic_write_json(proposal_path, proposal)
    atomic_write_json(dest / 'attempt.json', {
        'attempt_id': attempt_id,
        'stage': 'proposed',
        'candidate_id': proposal.get('candidate_id'),
        'source_sha256': sha256_text(proposal.get('source', '')),
        'proposal_index': index,
    })

    budgets = state.get('budgets') or {}
    max_seconds = float(budgets.get('max_seconds', 1800))
    active = float(state.get('active_eval_seconds') or 0)
    remaining = max_seconds - active

    detail: Dict[str, Any] = {
        'improved': False,
        'score': None,
        'smoke': smoke,
        'proposal_index': index,
    }
    stage = 'failed'
    started = time.monotonic()
    output = dest / 'primary' / 'measurement.json'

    def _checkpoint(stage_name: str) -> None:
        elapsed = time.monotonic() - started
        detail['eval_elapsed_seconds'] = elapsed
        atomic_write_json(dest / 'attempt.json', {
            'attempt_id': attempt_id,
            'stage': stage_name,
            'candidate_id': proposal.get('candidate_id'),
            'source_sha256': sha256_text(proposal.get('source', '')),
            'proposal_index': index,
            'detail': detail,
        })
        state['in_flight'] = {
            'attempt_id': attempt_id,
            'proposal_index': index,
            'stage': stage_name,
            'source_sha256': sha256_text(proposal.get('source', '')),
            'candidate_id': proposal.get('candidate_id'),
            'started_wall': (state.get('in_flight') or {}).get('started_wall') or time.time(),
            'charged_seconds': elapsed,
            'updated_wall': time.time(),
        }
        # Only rewrite full controller state; unit tests may pass a minimal dict.
        if state.get('schema') is not None and 'attempts' in state:
            atomic_write_json(search_dir / 'search_state.json', state)

    if smoke:
        extra = ['--smoke', '--samples', str(samples), '--seed', str(seed)]
    else:
        extra = ['--protocol', '--samples', str(samples), '--seed', str(seed)]
    if memory_cap_bytes != DEFAULT_MEMORY_CAP_BYTES:
        extra += ['--memory-cap-bytes', str(memory_cap_bytes)]

    try:
        _checkpoint('proposed')
        spawn = _spawn_evaluate(root, proposal_path, output, remaining, extra)
        (dest / 'stdout.log').write_text(spawn['stdout'] or '')
        (dest / 'stderr.log').write_text(spawn['stderr'] or '')
        detail['returncode'] = spawn['returncode']
        if spawn['returncode'] != 0:
            raise RuntimeError('evaluate-proposal failed rc=' + str(spawn['returncode']))
        report = json.loads(output.read_text())
        cand = proposal['candidate_id']
        variant = report['variants'][cand]
        if (variant['lifecycle'] != 'measured' or
                variant['verification']['state'] != 'pass' or
                variant['oracle']['state'] != 'pass' or not variant['sizes']):
            raise ValueError('Native evaluator did not provide measured verification evidence')
        stage = 'measured'
        detail['report'] = str(output)
        detail['lifecycle'] = variant['lifecycle']
        detail['verification'] = variant['verification']
        _checkpoint('measured')

        if smoke or report.get('promotional') is False:
            detail['rejection_reason'] = 'smoke_non_promotional'
            stage = 'measured'
        else:
            expected = list(PROTOCOL_SIZES)
            session = rank_from_report(report, 'clang_o3', cand, expected, bootstrap_seed=seed)
            session['report_path'] = str(output)
            detail['session'] = session
            detail['score'] = session.get('score')
            stage = 'ranked'
            _checkpoint('ranked')

            if confirm and session.get('promote_eligible') and not smoke:
                stage = 'confirming'
                _checkpoint('confirming')
                confirm_out = dest / 'confirmation' / 'measurement.json'
                confirm_seed = seed + 10_000 + index
                rem2 = max_seconds - active - (time.monotonic() - started)
                c_extra = ['--protocol', '--samples', str(samples),
                           '--seed', str(confirm_seed),
                           '--memory-cap-bytes', str(memory_cap_bytes)]
                spawn2 = _spawn_evaluate(root, proposal_path, confirm_out, rem2, c_extra)
                (dest / 'confirm_stdout.log').write_text(spawn2['stdout'] or '')
                (dest / 'confirm_stderr.log').write_text(spawn2['stderr'] or '')
                if spawn2['returncode'] != 0:
                    detail['rejection_reason'] = 'confirmation_failed'
                    stage = 'rejected'
                else:
                    report2 = json.loads(confirm_out.read_text())
                    session_b = rank_from_report(
                        report2, 'clang_o3', cand, expected, bootstrap_seed=confirm_seed)
                    session_b['report_path'] = str(confirm_out)
                    detail['session_b'] = session_b
                    promo = classify_promotion(session, session_b)
                    detail['promotion'] = promo
                    if promo.get('speed_claim'):
                        def _do_accept():
                            detail['accepted'] = {
                                'candidate_id': cand,
                                'attempt_id': attempt_id,
                                'source_sha256': sha256_text(proposal['source']),
                                'score': session.get('score'),
                                'session_a': session,
                                'session_b': session_b,
                                'promotion': promo,
                            }
                        refuse_stale_promotion(variant, _do_accept)
                        stage = 'accepted'
                    else:
                        detail['rejection_reason'] = promo.get('reason') or 'not_promoted'
                        stage = 'rejected'
            elif not session.get('promote_eligible'):
                detail['rejection_reason'] = session.get('reason') or 'not_promote_eligible'
                stage = 'ranked'

    except (subprocess.TimeoutExpired, OSError, ValueError, KeyError, RuntimeError) as exc:
        detail['error'] = str(exc)
        if stage not in ('ranked', 'accepted', 'rejected', 'measured'):
            stage = 'failed'

    detail['eval_elapsed_seconds'] = time.monotonic() - started
    result = AttemptRecord(
        attempt_id, proposal['candidate_id'],
        sha256_text(proposal['source']), stage, detail=detail)
    atomic_write_json(dest / 'attempt.json', asdict(result))
    return result
