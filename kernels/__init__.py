"""Kernel contracts and oracles (trusted evaluator side)."""
from . import find_u8, map_filter_u64, sum_u64
from .registry import KERNELS, list_kernel_ids, portfolio_contracts, run_oracle_selfchecks
from .experiments import build_experiment_report
from .native_compare import run_native_comparisons

__all__ = [
    'KERNELS',
    'build_experiment_report',
    'find_u8',
    'list_kernel_ids',
    'map_filter_u64',
    'portfolio_contracts',
    'run_native_comparisons',
    'run_oracle_selfchecks',
    'sum_u64',
]
