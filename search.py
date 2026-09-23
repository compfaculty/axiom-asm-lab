"""Bounded offline search with ranking, confirmation, and recoverable state.

Time budget counts active evaluation seconds only (not idle gaps between resumes).
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Protocol

from analysis import (
    classify_promotion,
    classify_session,
    extract_medians,
    extract_paired_ns,
    validate_report,
)
from evaluate import (
    PROTOCOL_SIZES,
    SMOKE_TARGET_NS,
    evaluation_config,
)
from proposals import ProposalError, import_proposal, mock_propose, sha256_text, validate_proposal
from sampling import DEFAULT_MEMORY_CAP_BYTES, TARGET_SAMPLE_NS


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


def atomic_write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(payload, indent=2) + '\n')
    tmp.replace(path)


def load_search_state(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text())


def session_identity_from_report(report: Dict[str, Any], baseline: str,
                                 candidate: str) -> Dict[str, Any]:
    b = report['variants'][baseline]
    c = report['variants'][candidate]
    return {
        'host': report.get('host'),
        'machine': report.get('machine'),
        'clang': report.get('clang'),
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
            'schema': 2,
            'search_id': self.search_dir.name,
            'budgets': asdict(self.budgets),
            'started_utc': time.time(),
            'provider_mode': self.provider_mode,
            'smoke': self.smoke,
            'evaluation_config': self.eval_config,
            'time_budget_mode': 'active_evaluation_seconds',
            'active_eval_seconds': 0.0,
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

    def load_or_init(self, resume: bool) -> Dict[str, Any]:
        if resume:
            if not self.state_path.is_file():
                raise FileNotFoundError('no search_state.json to resume: ' + str(self.state_path))
            state = load_search_state(self.state_path)
            self._validate_resume_config(state)
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

    def _validate_resume_config(self, state: Dict[str, Any]) -> None:
        prev = state.get('evaluation_config') or {}
        cur = self.eval_config
        for key in ('protocol', 'sizes', 'samples_per_size', 'target_sample_ns',
                    'memory_cap_bytes', 'kernel'):
            if key in prev and prev.get(key) != cur.get(key):
                raise RuntimeError(
                    f'resume evaluation_config mismatch on {key}: '
                    f'{prev.get(key)!r} vs {cur.get(key)!r}')
        if state.get('provider_mode') not in (None, self.provider_mode):
            raise RuntimeError('resume provider_mode mismatch')
        if 'smoke' in state and bool(state.get('smoke')) != bool(self.smoke):
            raise RuntimeError('resume smoke/protocol mode mismatch')

    def stop_reason(self, state: Dict[str, Any]) -> Optional[str]:
        if len(state['attempts']) >= self.budgets.max_proposals:
            return 'max_proposals'
        if float(state.get('active_eval_seconds') or 0) >= self.budgets.max_seconds:
            return 'max_seconds'
        if state['consecutive_no_improve'] >= self.budgets.max_stagnation:
            return 'max_stagnation'
        return None

    def run(self, resume: bool = False) -> Dict[str, Any]:
        state = self.load_or_init(resume)
        state['wall_started'] = state.get('wall_started') or time.time()
        state['status'] = 'running'
        state.setdefault('active_eval_seconds', 0.0)
        self.save(state)

        done_hashes = set(state.get('completed_source_sha256') or [])
        index = len(state['attempts'])
        while True:
            reason = self.stop_reason(state)
            if reason:
                state['stop_reason'] = reason
                state['status'] = 'stopped'
                self.save(state)
                return state

            try:
                proposal = self.provider.propose(index, self.root)
            except StopIteration:
                state['stop_reason'] = 'catalog_exhausted'
                state['status'] = 'stopped'
                self.save(state)
                return state
            try:
                validate_proposal(proposal, self.root)
            except ProposalError as exc:
                attempt = AttemptRecord(
                    attempt_id=uuid.uuid4().hex[:12],
                    candidate_id=str(proposal.get('candidate_id')),
                    source_sha256=sha256_text(proposal.get('source', '')),
                    stage='failed',
                    detail={'error': str(exc), 'phase': 'validate'},
                )
                state['attempts'].append(asdict(attempt))
                state['consecutive_no_improve'] += 1
                self.save(state)
                index += 1
                continue

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

            t0 = time.time()
            attempt = self._call_evaluate(proposal, index, state)
            elapsed = time.time() - t0
            state['active_eval_seconds'] = float(state.get('active_eval_seconds') or 0) + elapsed
            state['attempts'].append(asdict(attempt))
            done_hashes.add(src_hash)
            state['completed_source_sha256'] = sorted(done_hashes)

            self._update_ranking(state, attempt)
            self.save(state)
            index += 1

        return state

    def _call_evaluate(self, proposal, index, state):
        # Support both old (4-arg) and new (5-arg with state) evaluators.
        try:
            return self.evaluate_fn(self.root, self.search_dir, proposal, index, state)
        except TypeError:
            return self.evaluate_fn(self.root, self.search_dir, proposal, index)

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
            state['accepted'] = detail['accepted']

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
    attempt_id = uuid.uuid4().hex[:12]
    dest = search_dir / 'attempts' / f'{index:04d}_{attempt_id}'
    dest.mkdir(parents=True, exist_ok=False)
    proposal_path = dest / 'input.json'
    atomic_write_json(proposal_path, proposal)
    atomic_write_json(dest / 'attempt.json', {
        'attempt_id': attempt_id,
        'stage': 'proposed',
        'candidate_id': proposal.get('candidate_id'),
        'source_sha256': sha256_text(proposal.get('source', '')),
    })

    if state is None:
        state = load_search_state(search_dir / 'search_state.json')
    budgets = state.get('budgets') or {}
    max_seconds = float(budgets.get('max_seconds', 1800))
    active = float(state.get('active_eval_seconds') or 0)
    remaining = max_seconds - active

    detail: Dict[str, Any] = {
        'improved': False,
        'score': None,
        'smoke': smoke,
    }
    stage = 'failed'
    output = dest / 'measurement.json'

    if smoke:
        extra = ['--smoke', '--samples', str(samples), '--seed', str(seed)]
    else:
        extra = ['--protocol', '--samples', str(samples), '--seed', str(seed)]
    if memory_cap_bytes != DEFAULT_MEMORY_CAP_BYTES:
        extra += ['--memory-cap-bytes', str(memory_cap_bytes)]

    try:
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

            if confirm and session.get('promote_eligible') and not smoke:
                stage = 'confirming'
                atomic_write_json(dest / 'attempt.json', {
                    'attempt_id': attempt_id,
                    'stage': stage,
                    'detail': detail,
                })
                confirm_out = dest / 'confirmation.json'
                confirm_seed = seed + 10_000 + index
                rem2 = max_seconds - active - 1.0
                c_extra = ['--protocol', '--samples', str(samples),
                           '--seed', str(confirm_seed)]
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

    result = AttemptRecord(
        attempt_id, proposal['candidate_id'],
        sha256_text(proposal['source']), stage, detail=detail)
    atomic_write_json(dest / 'attempt.json', asdict(result))
    return result
