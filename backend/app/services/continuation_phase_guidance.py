"""The one wording that tells an agent which continuation phase a change belongs in.

Every prompt that explains the `diagnostic` and `implementation` phases takes this text, so a reader cannot
meet two versions of it.
"""

PHASE_GUIDANCE = (
    "Temporary diagnostic changes (instrumentation, hosted log collection, probe edits) use phase "
    "`diagnostic` and must be reverted with `revert_diagnostic_changes`. Any change that stays in the PR, "
    "including re-adding tests or code, uses phase `implementation` and includes `push_pr_head` plus "
    "`request_verification`."
)
