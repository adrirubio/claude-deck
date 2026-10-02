# Independent operations re-review — PR #16

Reviewer B4 Product Validation, member 5 / slot 4, 2026-10-02.
Exact head `54f3c0b9e5404fe6f9594cde5b648f2a02f5d098` on
`juanrubio/claude-deck`, target `feature/software-delivery-product-reposition`.
Detached disposable checkout `/tmp/product-review-16-b4`.

**Changes required.** This review supersedes findings at `faa2efb` only as
described below. No live API, database, credential, service, tmux or process-freeze
operation was exercised. `git diff --check` passed.

Verified with scratch paths and stubs against the exact reviewed functions:

- Secure private staging replaces the destination symlink without modifying its
  target; the published HOLD is a regular file. Original finding 1 is resolved.
- A mocked freeze timeout leaves both HOLD files present and records
  `freeze_error: TimeoutExpired`. Original finding 2 is resolved.
- Source inspection confirms controller binding rows, saved target filtering,
  UID and PID-start checks replace the tmux subprocess for freeze selection.
- Arming now checks the named primary-scope policy and supervisor state.

Remaining findings:

1. **P1 — Arming does not require exactly one scope.**
   `scripts/product-factory/productctl:57` selects `scopes[0]`. Both status and
   validation ignore additional scopes. A fully stubbed arm execution supplied
   compliant scope 1 and a second enabled scope with another repository and auto
   merge policy; it still emitted the preset-enable PATCH. Enabling that preset
   permits its other enabled scope to run, violating the single-scope product
   boundary. Require the complete scope set to be exactly the expected scope
   before mutation and validate that same snapshot's policy.

2. **P2 — Incremental log reads discard incomplete trailing records.**
   `scripts/product-factory/product-supervisor:129-135` catches JSON decode errors
   and advances the saved offset past the incomplete line. A synthetic recognized
   event split into two writes across two tick calls was never detected, although
   the completed record independently matched the classifier. Keep the offset at
   the beginning of an incomplete trailing record and consume only complete lines;
   test append completion separately from malformed completed lines.

The arm test executed only the parsed arm branch with synthetic API responses,
scratch state/ledger paths, stubbed status and captured PATCH calls. The log test
redirected session discovery to a temporary directory and replaced pause with a
recorder. No real execution was armed or stopped.

Findings sent to B1 through authenticated Mail message 25. Next action: operations
owner fixes the two remaining conditions and supplies another exact head. No
runtime, pilot, merge or promotion acceptance is asserted.
