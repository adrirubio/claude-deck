# v3.1 installation fixture

This is the shared **Fixture** in `compatibility.md` §7, for issue #801.
It supplies the baseline for T-D1, T-D7 and T-G2. It does not implement or
claim a pass for those upgrade tests.

Run it with the backend environment:

```sh
cd backend
source venv/bin/activate
pytest tests/upgrade -q
```

The repository must contain tag `v3.1.0` at the reviewed commit
`a68a02cb768eb8fa9afa90df81871dbccc464a09`. Missing or changed history is an
error, never a skipped test. The backend CI job already uses `fetch-depth: 0`
and runs these tests as part of `pytest tests` for `release/v4.0`.

`build_v31_install(tmp_path)` exports that immutable source as temporary test
input. A separate Python process imports only the exported application and
uses a fresh HOME with the original default resource paths. No candidate
application models or hand-written SQL/ORM inserts create the fixture.

The old APIs create teams, slots (including Pi), settings, mail registrations
and history, a disabled dispatch scope with its old default labels, backups,
and two attachments. A controlled clock makes one attachment expired. Old
installer APIs create Claude Code, Codex, Copilot and OpenCode registrations;
only the Codex/Copilot external `mcp add/list` boundary is simulated. An
OpenCode registration then receives a custom URL, as an operator could set.
The installer-generated hooks/plugin and source-resolving commands stay on
disk. A backup is listed, downloaded, validated, and actually restored after
a setting has been deliberately changed.

The seeder checkpoints the initial state, creates a final team through the
API, and exports the quiescent SQLite main/WAL/SHM set before closing its
connections. It restores those exact exported bytes after shutdown so a
non-empty, committed WAL survives as test input. A test proves that the final
team is absent from the main file alone and present when the WAL is read.
This is a frozen SQLite snapshot, not evidence of power-loss safety.

The returned `V31Install` gives callers `database`, `home`, `source`, `app_dir`,
`browser_state`, `manifest`, and the `before` semantic snapshot. The browser
state contains both original keys, in their original namespaces: the operator
token in `sessionStorage`, the provider in `localStorage`. The manifest records
the old Pi command, extension path and opt-in environment; it does not claim
that a Pi executable, Node dependencies, or a real provider session were run.

For an independently mutable installation, call `build_v31_install` with a new
empty temporary directory. The module-scoped `v31_install` fixture is a shared
read-only baseline for this contract suite. Later upgrade tests should build
their own installation instead of changing it.

`SemanticSnapshot.capture(database)` inspects a temporary copy of the complete
SQLite file set; it never opens/checkpoints the source. It records all tables
by primary key, all pre-existing field values, digests of every owned backup
and attachment file, and exact `file_path`, `storage_path`, `agent_path`, and
`prompt_text` values. After a later test starts the upgraded product:

```python
after = SemanticSnapshot.capture(new_database)
install.before.assert_preserved(after, path_map=exact_path_mapping)
```

New tables, rows and columns are allowed. Old identities/fields/file bytes
must survive. Retargeting requires an exact mapping for each changed value;
only the four path fields can use it. Unrelated charter/message text and
stored dispatch labels cannot be rewritten through that exception. For T-D7,
derive mappings from the migration journal's actual allocated destinations,
including full prompt values. For T-G2, also restore the complete home,
provider configuration and both browser storage areas: the database snapshot
alone does not represent the complete pre-upgrade recovery set.

Isolation is deliberate: no startup lifespan/scheduler, no server ports, no
real provider/tmux subprocesses, and no network sockets. Managed system config
locations point into the throwaway home. Authentication uses synthetic test
credentials and the old API-issued session tokens. These tests do not change
product authentication, dispatch, approval, HOLD, or lifecycle rules.
