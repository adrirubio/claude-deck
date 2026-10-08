# Independent operations review — PR #16

Reviewer: B4 Product Validation, member 5 / slot 4. Date: 2026-10-02.
Repository: `juanrubio/claude-deck`; PR #16, `product/factory-operations`.
Reviewed exact head: `faa2efb84d23cd0bff16e733fa99154f160af9e6`.
Base: `ac9252242fcf436c3ea9997add5d32416cad2cd1`;
target: `feature/software-delivery-product-reposition`.
Independent disposable checkout: `/tmp/product-review-16-b4`, detached head.

**Disposition: changes required; no acceptance at this head.** Source-only review
of installed-source scripts/unit files/runbook, plus two isolated scratch checks.
`git diff --check` passed. No installed helper was executed; no live credentials,
API, tmux socket, service, process signal or runtime state was accessed/changed.

## Findings

1. **P1 — Shared HOLD publication crosses the agent/root write boundary.**
   `scripts/product-factory/product-supervisor:25-26` uses predictable
   `HOLD.json.tmp` in the agent-writable operations directory and follows an
   existing symlink with `write_text` and `chmod`. The service runs as root.
   A pre-existing link therefore directs the root write outside the intended
   hold file, and `os.replace` publishes the link itself. A scratch-only check
   against this exact function observed `target_modified: true` and
   `published_hold_is_symlink: true`. Use secure exclusive temporary-file
   creation without following links, controlled directory/file descriptors and
   atomic publication; verify the resulting ownership/access boundary.

2. **P1 — A freeze failure prevents the durable stop latch.**
   `product-supervisor:62` calls `freeze_product_execution()` before either
   HOLD write at lines 65–66. The freeze routine can raise for malformed launch
   state or a tmux timeout. `OnFailure` invokes the same `pause` function and
   therefore can fail identically. With API calls stubbed successful and freeze
   stubbed to raise TimeoutExpired, the exact function propagated the exception
   and wrote neither private nor shared HOLD. Persist the stop latch first;
   perform bounded best-effort freezing and durably record its failure.

3. **P1 — Arming does not enforce its declared product policy.**
   `scripts/product-factory/productctl:44-58` reads status but validates only
   hold, credential presence, tick age, packet acceptance, binding and a nonempty
   eligible list. It then enables hardcoded scope/preset 1 and prints a fixed
   human-merge/concurrency-one success statement. Repository/base, actual merge
   policy, scope identity/count, concurrency and healthy supervisor mode are not
   checked. Drift to automatic merge, a different target or wider concurrency
   would still arm, contrary to the authorized boundary. Validate the complete
   expected state before writes, fail on mismatch/uncertainty, and verify the
   resulting state instead of printing assumed policy. This finding is from
   control-flow inspection; no arming call was executed.

## Additional unresolved coverage

Process selection records start times but does not revalidate them before SIGSTOP;
it uses saved tmux targets and hardcoded UID 1002. Exact live slot/session identity,
PID reuse and descendant creation races need isolated coverage. Structured-log
tailing advances past an incomplete final JSON line, which can drop that record
when its remainder arrives. These have not been accepted as reliable supervision.

Scratch checks imported only the reviewed supervisor definitions with a non-main
run name, replaced state paths with temporary directories and stubbed API/freeze
functions. Results establish the two failure paths, not installed runtime behavior.
No actual model safety interruption was observed during review.

Findings sent to B1 via authenticated Agent Mail message 18 with issue/PR/head
context. Next action: operations owner corrects these boundaries and supplies a
new exact head with isolated regression evidence; B4 reviews that new head.
Human merge, pilot and promotion remain separate decisions.
