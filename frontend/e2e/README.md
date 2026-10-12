# Deck E2E journeys

The E2E journeys drive the built Deck UI in Chromium against one isolated Deck instance. They use synthetic seed data. They use no real agents, no credentials and no network except the local instance.

## Terms

| Term | Meaning |
|---|---|
| Journey | One Playwright test in `e2e/<gate>/*.spec.ts`. |
| Gate | A milestone check, for example `g0`. The directory name is the gate. |
| `@active` | A journey that must pass. The required `e2e` CI job runs it. |
| `@pending` | A journey for work that is not merged yet. The `e2e-pending` job runs it and reports progress. It does not block a merge. |
| Instance | The backend and the built UI that `scripts/e2e-instance.sh` starts. |

## The isolated instance

`scripts/e2e-instance.sh` does these steps:

1. It makes a temporary root. `HOME`, the database and `TMUX_TMPDIR` are in it. It unsets `TMUX`.
2. It writes fake harness binaries (`claude`, `codex`, `copilot`, `opencode`, `pi`) first on `PATH`. Each one answers `--version` and echoes its input. A fake `gh` always fails.
3. It builds `frontend/dist`, unless `E2E_SKIP_BUILD=1`.
4. It writes the seed database with `scripts/e2e/seed.py`.
5. It starts the backend on `127.0.0.1:$E2E_PORT` (default `18765`) from the temporary root, so no `.env` file loads. The backend serves the UI on the same origin.
6. On exit, it stops the backend, stops its own tmux server and removes the temporary root.

The instance sets `TEST_INSTANCE=1`. With this setting the backend does not start the dispatch scheduler and does not run the start-up relay cleanup. All GitHub HTTP calls fail as connection errors and open no socket. The journey `g0/isolation.spec.ts` checks that the instance does not signal a `tmux attach-session` process outside its own server.

## Rules for every journey

Import `test` and `expect` from `e2e/support/guard.ts`. The guard fixture runs in every journey. It fails the journey on:

- a console error or an uncaught page error;
- a failed request, or a 4xx or 5xx response that the journey did not declare;
- a request to an origin that is not the instance;
- a repeated request (same method and URL) after a 4xx response.

Declare an expected status before the request: `guard.expectStatus('GET', /\/api\/v1\/work-items\/999999$/, 404)`. A repeat after that 4xx still fails.

Use the helpers:

- `e2e/support/director-key.ts` enters the synthetic Director key when Deck asks for it.
- `e2e/support/time.ts` gives the fixed browser zone and locale, the seed clock (`SEED_NOW`) and local-time assertions.

Use seeded names from `scripts/e2e/scenarios.py`. Do not depend on database IDs that the seed does not fix.

## Run the journeys

From `frontend/`:

```bash
npm run e2e            # all @active journeys; starts and stops the instance
npm run e2e:pending    # all @pending journeys
npx playwright test e2e/g0/routes.spec.ts             # one file
npx playwright test --grep "Overview"                 # journeys whose title matches
```

The first run needs the backend venv (`backend/venv`) and Chromium (`npx playwright install chromium`).

To keep one instance running while you edit a journey:

```bash
# Terminal 1, from the repository root
E2E_KEEP_ROOT=1 bash scripts/e2e-instance.sh
# Terminal 2, from frontend/
E2E_REUSE_INSTANCE=1 npx playwright test e2e/g0/routes.spec.ts --headed
```

After a failure, open the trace: `npx playwright show-trace test-results/<journey>/trace.zip`.

## Move a journey from `@pending` to `@active`

The supervisor does this when a lane gate passes:

1. Confirm that the work for the journey is merged into the target branch.
2. Confirm that the `e2e-pending` job shows the journey as passing on that branch.
3. In the journey title, change `@pending` to `@active`.
4. Open a PR with only that change. The required `e2e` job must pass on the PR head.

Do not move a journey to `@active` to make a lane look complete. Do not delete a failing `@active` journey. Fix the cause, or return it to `@pending` with a linked issue.

## Add a lane journey

1. Read the lane issues' "Done when" and the [design reference](../../docs/plans/2026-10-11-v3.1-director-ui/README.md). The issue text is authoritative.
2. Add the seed state that the journey needs to `scripts/e2e/scenarios.py`. Use synthetic data only. Fill every NOT NULL column.
3. Add `e2e/<gate>/<name>.spec.ts` with `@pending` in each title.
4. Run it locally. A pending journey can fail; it must not be flaky.
