# From assembly experiments to a language

Do not lose this objective while optimizing sum. The assembly lab is the evidence collection stage for a new programming model.

## Stage 1: machine and kernel knowledge
Measure scalar/vector throughput, dependencies, branch behavior and memory access patterns with documented microbenchmarks. Hardware observations are empirical and versioned by machine. Use several kernels to identify repeated patterns: reductions, maps, scans, compaction and bounded parsing.

## Stage 2: semantic IR
Create typed operations preserving array shape, element type, ownership/effects and overflow policy. Define exact semantics before syntax. `reduce_u64_wrap` permits reassociation. Checked integer operations need precise error order; floating-point reassociation is forbidden by default. Distinguish ordered filtering from unordered compaction. Never infer concurrency legality from syntax alone.

## Stage 3: readable source
Minimal subset: typed functions, immutable local bindings, arrays/slices, bounded iteration, and selected pure operations. Parser and type checker lower to semantic IR. Initial backend selects verified templates, with explicit coverage errors for unsupported constructs. The IR interpreter is a reference oracle. Tests compare interpreter and native output across generated programs.

## Stage 4: safety and concurrency
Ownership/region rules, bounds checking, error semantics and scoped tasks become language features. Inference may simplify common cases; ambiguous ownership must produce a clear diagnostic or documented managed behavior. Child task cancellation and cleanup require a runtime contract. No claim of language memory safety until front end, runtime, foreign calls and lowering assumptions are addressed.

## Stage 5: broaden targets
Keep source semantics stable while adding backend capability negotiation and target-specific catalogs. Reuse LLVM/MLIR if useful; direct assembly templates remain an experiment path. Replacing existing backend infrastructure requires a measured limitation and an ADR. Portability means one semantics with different code generation, not one binary optimized for all processors.
