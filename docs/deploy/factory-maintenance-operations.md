# Factory maintenance and current summaries

## Current GitHub summary

The team can select a compact summary for its issue and PR bodies. The summary is a report. It grants no approval or execution authority.

Use `deck_render_github_summary` with the latest body and public summary fields. The renderer updates only `deck:current-summary`. It preserves human requirements, operator-action records, remaining-work records and history outside that section.

The summary states the goal, status, completed work, remaining work, estimate, waiting, next action and human action. Active effort needs a range, confidence and scope. Use Unknown when there is no reliable estimate. State unestimated waiting separately. A source SHA identifies a public checkpoint; it does not prove acceptance.

Use one responsible body publisher for each team. Reconcile concurrent edits before publication. The optional expected body hash checks the input supplied to the renderer. It is not an atomic GitHub write guard. Read back the published body through existing authorized access.

Do not append competing current-status paragraphs. Keep detailed evidence in linked records. Label old estimates and states as history. Clear or supersede operator-action records through their existing process.

The standalone renderer uses the same protocol:

```sh
python scripts/factory-summary.py \
  --body-file /tmp/issue-body.md \
  --summary-file /tmp/current-summary.json \
  --output-file /tmp/rendered-issue-body.md
```

The JSON file contains the required public fields and an aware `reported_at` timestamp. Optional fields are `waiting`, `source_sha`, `effort_low_minutes`, `effort_high_minutes`, `confidence` and `effort_scope`. The output file must not exist. This command performs no GitHub write.

## Maintenance work in progress

Upstream issue #482 tracks recorded observation recovery, a reusable controller upgrade and accepted integration updates. These operations are not supplied by the summary renderer. Their deployment requires a reviewed implementation and a safe owner handoff.

Keep each team's recorded policy and task gates until explicit adoption. Do not restart a native member to activate a communication change during an implementation batch.
