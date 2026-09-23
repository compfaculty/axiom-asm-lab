# Supported language subset (T012 / M006)

This is the **explicit** surface covered by the parser and native lowering.
Anything outside this set is rejected (`ParseError`, `IrError`, or `CoverageError`).

## Surface syntax
```text
fn name() -> ret_ty          # optional wrapper
let x = op(args...)
...
return x
```
- Comments: `# ...` to end of line
- Integers: decimal or `0x` hex
- Bindings are immutable; no mutation, no indexing syntax, no loops
- No parameters on `fn` yet (inputs are literal arrays/consts in the body)

## Allowed ops (must typecheck)
| Op | Result | Notes |
|---|---|---|
| `const_u64` / `const_u8` | scalar | `const_u8` in `0..255` |
| `array_u64` / `array_u8` | array | literals only |
| `reduce_sum_u64_wrap` | `u64` | wrapping sum |
| `find_u8` | `index` | search |
| `map_filter_even_shr1_u64` | `arr_u64` | stable even→`x>>1` |

## Rejected
- Unknown ops / ill-typed args
- Effects `write` / `unsafe_io` (e.g. `store_global_u64`)
- Ownership `moved`
- Program shapes that are not one of the three templates below

## Native lowering templates
| Shape | Template | Symbol |
|---|---|---|
| `array_u64` → `reduce_sum_u64_wrap` | `templates/sum_u64.s` | `sum_array` |
| `array_u8` → (`const_u8`) → `find_u8` | `templates/find_u8.s` | `find_u8` |
| `array_u64` → `map_filter_even_shr1_u64` | `templates/map_filter_u64.s` | `map_filter_u64` |

The IR interpreter remains the semantic oracle; native output must match it.
