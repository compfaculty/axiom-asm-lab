# Verification plan

Run `python3 lab.py verify`. The harness checks every size 0..4096 using deterministic pseudo-random data; also checks shifted starts and arithmetic-overflow cases. Expected values use unsigned C arithmetic, which is defined modulo 2^64. `python3 -m unittest discover -s tests -v` tests controller filename validation and repository fixtures and runs on non-Mac hosts too.

A nonzero verifier exit blocks timing. Each candidate has its own linked executable. The timeout bounds hung code but does not sandbox arbitrary instructions; review submitted assembly. Future M002 adds page boundaries and ABI checks. Tests alone do not prove equivalence: exhaustive proof of a bounded kernel or SMT reasoning is a later research path, with a precisely modeled ISA and memory contract.
