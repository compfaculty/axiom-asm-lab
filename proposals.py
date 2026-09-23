"""Offline proposal schema validation, source review, mock proposer, immutable import."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ALLOWED_KERNELS = {'sum_u64'}
ALLOWED_CONTRACT_VERSIONS = {1}
REQUIRED_FIELDS = (
    'schema_version',
    'candidate_id',
    'kernel_id',
    'contract_version',
    'parent_source_sha256',
    'hypothesis',
    'source',
    'expected_size_range',
    'provenance',
)
MAX_SOURCE_BYTES = 64 * 1024
CANDIDATE_ID_RE = re.compile(r'^[A-Za-z0-9_-]+$')
FORBIDDEN_SOURCE_PATTERNS = (
    (re.compile(r'^\s*\.include\b', re.I | re.M), 'unexpected .include'),
    (re.compile(r'^\s*\.incbin\b', re.I | re.M), 'unexpected .incbin'),
    (re.compile(r'^\s*#\s*include\b', re.I | re.M), 'C-style include'),
    (re.compile(r'^\s*\.file\b', re.I | re.M), 'unexpected .file directive'),
    (re.compile(r'^\s*\.extern\b', re.I | re.M), 'unexpected .extern'),
    (re.compile(r'^\s*\.set\b', re.I | re.M), 'unexpected .set'),
    (re.compile(r'/\*', re.M), 'block comment not allowed in restricted profile'),
)


class ProposalError(ValueError):
    """Invalid proposal rejected before evaluation."""


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def known_parent_hashes(root: Path) -> Dict[str, str]:
    """Map builtin assembly path stem -> sha256 for parent reference checks."""
    out = {}
    for path in (root / 'asm').glob('*.s'):
        out[path.stem] = hashlib.sha256(path.read_bytes()).hexdigest()
    return out


def review_assembly_source(source: str) -> None:
    if not isinstance(source, str):
        raise ProposalError('source must be a string')
    raw = source.encode('utf-8')
    if len(raw) > MAX_SOURCE_BYTES:
        raise ProposalError(f'source exceeds max bytes ({len(raw)} > {MAX_SOURCE_BYTES})')
    if len(raw) == 0:
        raise ProposalError('source is empty')
    for pattern, reason in FORBIDDEN_SOURCE_PATTERNS:
        if pattern.search(source):
            raise ProposalError('source review failed: ' + reason)
    if '_sum_array' not in source:
        raise ProposalError('source review failed: missing _sum_array symbol')
    # Reject non-text / embedded-looking payloads.
    if '\x00' in source:
        raise ProposalError('source review failed: embedded NUL / binary content')


def validate_proposal(obj: Any, root: Path) -> Dict[str, Any]:
    if not isinstance(obj, dict):
        raise ProposalError('proposal must be a JSON object')
    unknown = set(obj) - set(REQUIRED_FIELDS)
    if unknown:
        raise ProposalError('unknown schema fields: ' + ', '.join(sorted(unknown)))
    missing = [k for k in REQUIRED_FIELDS if k not in obj]
    if missing:
        raise ProposalError('missing fields: ' + ', '.join(missing))
    if obj['schema_version'] != 1:
        raise ProposalError('unsupported schema_version')
    cid = obj['candidate_id']
    if not isinstance(cid, str) or not CANDIDATE_ID_RE.fullmatch(cid):
        raise ProposalError('malformed candidate_id')
    # Collision with builtins is rejected at import/evaluate via lab.sources rules;
    # also reject here if id matches builtin stems.
    if cid in ('clang_o3', 'scalar', 'unrolled4'):
        raise ProposalError('candidate_id collides with built-in')
    if obj['kernel_id'] not in ALLOWED_KERNELS:
        raise ProposalError('unknown kernel_id: ' + str(obj['kernel_id']))
    if obj['contract_version'] not in ALLOWED_CONTRACT_VERSIONS:
        raise ProposalError('unsupported contract_version')
    parent = obj['parent_source_sha256']
    if parent is not None:
        if not isinstance(parent, str) or len(parent) != 64:
            raise ProposalError('invalid parent_source_sha256')
        parents = known_parent_hashes(root)
        if parent not in parents.values():
            raise ProposalError('invalid parent: sha256 not a known builtin assembly source')
    if not isinstance(obj['hypothesis'], str) or not obj['hypothesis'].strip():
        raise ProposalError('hypothesis must be a non-empty string')
    review_assembly_source(obj['source'])
    esr = obj['expected_size_range']
    if not (isinstance(esr, list) and len(esr) == 2
            and all(isinstance(x, int) and x >= 0 for x in esr) and esr[0] <= esr[1]):
        raise ProposalError('expected_size_range must be [lo, hi] ints')
    prov = obj['provenance']
    if not isinstance(prov, dict) or 'mode' not in prov:
        raise ProposalError('provenance must be an object with mode')
    if prov.get('mode') not in ('mock', 'manual', 'offline'):
        raise ProposalError('unsupported provenance.mode')
    return obj


def mock_propose(root: Path, candidate_id: str = 'mock_scalar_copy') -> Dict[str, Any]:
    """Deterministic offline proposer: emits a reviewed scalar-equivalent candidate."""
    scalar = (root / 'asm' / 'scalar.s').read_text()
    source = scalar.rstrip() + '\n// mock_proposer: identity scalar parent\n'
    parent = hashlib.sha256((root / 'asm' / 'scalar.s').read_bytes()).hexdigest()
    proposal = {
        'schema_version': 1,
        'candidate_id': candidate_id,
        'kernel_id': 'sum_u64',
        'contract_version': 1,
        'parent_source_sha256': parent,
        'hypothesis': 'Offline mock: scalar-equivalent control for pipeline validation.',
        'source': source,
        'expected_size_range': [0, 1048576],
        'provenance': {
            'mode': 'mock',
            'proposer': 'mock_propose',
            'note': 'deterministic offline fixture; not a performance claim',
        },
    }
    validate_proposal(proposal, root)
    return proposal


def import_proposal(proposal: Dict[str, Any], run_dir: Path, root: Path) -> Dict[str, Any]:
    """Immutable import under run_dir/proposals/<id>/; refuses overwrite."""
    validate_proposal(proposal, root)
    cid = proposal['candidate_id']
    dest = run_dir / 'proposals' / cid
    if dest.exists():
        raise FileExistsError('Refusing to overwrite proposal import: ' + str(dest))
    dest.mkdir(parents=True, exist_ok=False)
    prop_path = dest / 'proposal.json'
    src_path = dest / (cid + '.s')
    payload = dict(proposal)
    payload['source_sha256'] = sha256_text(proposal['source'])
    prop_path.write_text(json.dumps(payload, indent=2) + '\n')
    src_path.write_text(proposal['source'])
    # Integrity: re-read and hash
    if sha256_text(src_path.read_text()) != payload['source_sha256']:
        raise ProposalError('import integrity failure')
    return {
        'candidate_id': cid,
        'proposal_path': str(prop_path.resolve()),
        'source_path': str(src_path.resolve()),
        'source_sha256': payload['source_sha256'],
        'dir': str(dest.resolve()),
    }
