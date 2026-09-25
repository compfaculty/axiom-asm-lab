"""Kernel contracts and oracles (trusted evaluator side)."""
from . import find_u8, map_filter_u64, sum_u64
from .descriptors import (
    DEFAULT_KERNEL,
    DESCRIPTORS,
    get_descriptor,
    list_descriptor_ids,
    sanitize_evidence_summary,
)
from .registry import KERNELS, list_kernel_ids, portfolio_contracts, run_oracle_selfchecks
from .experiments import build_experiment_report
from .native_compare import run_native_comparisons

__all__ = [
    'DEFAULT_KERNEL',
    'DESCRIPTORS',
    'KERNELS',
    'build_experiment_report',
    'find_u8',
    'get_descriptor',
    'list_descriptor_ids',
    'list_kernel_ids',
    'map_filter_u64',
    'portfolio_contracts',
    'run_native_comparisons',
    'run_oracle_selfchecks',
    'sanitize_evidence_summary',
    'sum_u64',
]
