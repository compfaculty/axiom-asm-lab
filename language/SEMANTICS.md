# Semantic IR (T011)

Exact semantics are defined before surface syntax. The interpreter in
`language/interpreter.py` is the reference oracle for lowering (T012).
Surface syntax and the supported native subset are in `language/SUBSET.md`.

## Types
| Type | Meaning |
|---|---|
| `u64` | Unsigned 64-bit; wrapping ops use mod 2^64 |
| `u8` | Unsigned 8-bit |
| `index` | Result of search: index in `[0,n]` where `n` means not found |
| `arr_u64` / `arr_u8` | Dense arrays; inputs are borrowed read-only unless stated |
| `unit` | Side-effecting ops (unsupported in v1) |

## Ownership assumptions
- **Borrowed inputs**: `reduce_sum_u64_wrap`, `find_u8`, and the input side of
  `map_filter_even_shr1_u64` must not mutate caller storage.
- **Owned results**: `array_*` and map/filter outputs are owned by the callee result.
- **Moved** ownership is rejected in v1.

## Effects
Allowed: `pure`, `read`, `alloc`.  
Rejected: `write`, `unsafe_io` (and any op declaring them), e.g. `store_global_u64`.

## Operations and wrapping
### `reduce_sum_u64_wrap(arr_u64) -> u64`
Wrapping sum of elements mod 2^64. Empty array yields `0`. Matches kernel `sum_u64`.

### `find_u8(arr_u8, needle_u8) -> index`
Least index `i` with `a[i]==needle`, else `len(a)`. Matches kernel `find_u8`.

### `map_filter_even_shr1_u64(arr_u64) -> arr_u64`
Stable compact: keep even `x`, append `(x>>1) mod 2^64`. Matches `map_filter_u64`.

## Examples

Sum:

```text
let a = array_u64(1, 2, UINT64_MAX)
let s = reduce_sum_u64_wrap(a)
return s   # == 2  (wrap)
```

Find:

```text
let a = array_u8(9, 7, 7)
let n = const_u8(7)
let i = find_u8(a, n)
return i   # == 1
```

Map/filter:

```text
let a = array_u64(2, 3, 4)
let b = map_filter_even_shr1_u64(a)
return b   # == [1, 2]
```

## Invalid programs
- Wrong argument types (e.g. reduce on `arr_u8`) → `IrError`
- Unsupported effects / moved ownership → `IrError`
- Unbound return name → `IrError`
