# Benchmark protocol

Run on a plugged-in Apple Silicon Mac with no heavy background load. Record chip model, macOS release, compiler version, power mode, and temperatures if available. Do not compare results across machines as though they were one experiment.

`python3 lab.py bench --samples 15 --output results/run.json` verifies first, warms each binary, then measures 10 sizes from empty to one million elements. It reports nanoseconds per call and the median. The large size reflects cache and memory behavior; short sizes reflect call and branch overhead. There is no allocation inside the timed loop. The `volatile` sink prevents dead-result removal; separate linkage inhibits whole-program inlining. Numeric inputs are pseudorandom and seeded in native code.

Interpret improvements relative to Clang for each size, not as a universal speedup. Repeat full runs, compare medians, inspect outliers and disassembly, and discard thermal or background-load contamination. M003 will add randomized order and confidence estimates; current order may favor one candidate. The harness overhead dominates tiny inputs, so treat sub-nanosecond differences skeptically.
