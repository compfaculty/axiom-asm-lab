# Language direction (research sketch)

Begin with a semantic reduction primitive: an array of fixed-width unsigned values, associative wrapping addition, explicit result type, and read-only input. A possible future syntax is `reduce(data, add.wrap_u64, identity=0)`. This permits reassociation and vector lanes without ambiguity. Checked arithmetic and floating-point reduction require different semantics.

The front end should produce a typed IR with effect, ownership, shape, and overflow facts. A lowering pass selects an assembly kernel from a verified catalog for a target CPU and size range. General compilation remains possible through a standard code generator. Discover more abstractions only after several kernels reveal reusable patterns. Memory safety requires bounds and lifetime guarantees at the language level, plus verification of lowering; benchmark success is not evidence of safety.
