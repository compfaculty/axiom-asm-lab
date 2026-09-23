# AI integration and autonomous search

## Two agent roles
The Cursor implementation agent builds the platform following AGENTS.md and task gates. The kernel proposal model suggests assembly within a fixed contract. These roles must use the same trusted evaluator; generated text cannot change acceptance rules or execute arbitrary tool commands.

## First integration: offline
Implement a JSON proposal importer and deterministic mock proposer. Keep provider-specific HTTP code behind an optional adapter. Offline replay must cover the complete lifecycle before network integration. The output includes schema_version=1, candidate_id, kernel_id, contract_version, parent_source_sha256 or null, hypothesis, source, expected_size_range, and provenance. Candidate IDs are restricted tokens. Enforce maximum source bytes, no unknown schema fields, allowed kernel IDs, and consistency of parent references. Imported source is written under an engine-selected run directory.

Assembly review must reject unexpected directives, external includes, embedded binaries and unexpected symbol references under the initial restricted profile. Such checks are defense in depth, not a sandbox or proof of safety. A future isolated worker may accept broader instruction sequences. Do not let model text choose shell commands, output paths, environment values or compiler flags.

## Proposal prompt template
Read templates/PROPOSAL_PROMPT.md. Supply contract, baseline source, exact available instruction features, parent measurements and known failed hypotheses. Ask for one hypothesis and one candidate. Include ABI and memory constraints. The model must label uncertainty and never assert a measured win before evaluation.

## Controller responsibilities
Validate -> persist -> compile -> verify -> measure -> compare -> record. Every transition is keyed by hashes. Record invalid proposals, compiler diagnostics, faults and negative results. A candidate that fails verification has no performance score. Preserve the current accepted implementation until replacement passes the gate. Implement budgets in configuration and test enforcement with the mock proposer. Resume idempotently; interrupted stages are incomplete.

## Optional online adapter
Choose a provider only when explicitly configured. Use environment credentials, redact logs, apply network timeout/retry caps, and track reported token usage/cost where available. Do not send host secrets or full environment dumps. Require an explicit nonzero spending budget. Network failures leave resumable state, not accepted candidates. The core must still work with no network.
