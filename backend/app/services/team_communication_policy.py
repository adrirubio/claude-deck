"""Shared writing guidance for team members. This module does not grant authority."""

CONTROLLED_LANGUAGE_GUIDANCE = """Communication: ASD-STE100 guidance
Use ASD-STE100 writing rules for team messages, GitHub text, comments, reports, and documentation.
Use short, clear English. Use active voice and simple verb forms.
Use the same word for the same meaning. Define necessary technical terms.
Give one instruction in each sentence. Use at most 20 words in an instruction.
Use at most 25 words in a description. Put one topic in each paragraph.
Use at most six sentences in a paragraph. Use lists for steps and conditions.
Keep code, commands, paths, identifiers, quotations, and precise evidence unchanged.
Keep each safety condition, exception, approval rule, decision gate, and evidence limit.
Do not remove facts to shorten the text. Do not claim certified ASD-STE100 compliance.
These instructions guide your output. Deck does not check the full controlled dictionary."""

OWN_WRITING_STYLE_GUIDANCE = """Communication: member writing style
The operator disabled Deck's ASD-STE100 guidance for this member. Use your own writing style.
This choice replaces only Deck's earlier controlled-language instruction for this member.
Keep the human summary requirement. Keep all other instructions, safety conditions, authority rules, and decision gates."""

OPERATOR_ACTION_CONTEXT_GUIDANCE = """Current operator action instructions
Before requesting human input, call deck_prepare_operator_action_contexts for the intended requests.
For automatic review or recovery requests, call deck_get_operator_action_contexts.
Publish the completed records near the start of the main GitHub issue body.
Use the returned markers and heading. Replace each WRITE_ placeholder.
State the reason, responsible person, exact action, evidence, and completion condition.
Name delegated recovery explicitly. Do not imply that an agent task needs a new human decision.
State the PR target and reviewed head for a PR request. Give a current UTC update time.
Preserve other issue facts and other scopes. Use existing authorized GitHub access.
Do not leave the instructions only in Mail or comments. Never publish private credentials, prompts, or raw logs.
Clear or supersede old records when the request changes or ends.
After editing the issue, read fresh coordination before reporting its assessment.
Missing or stale instructions remain visible as Action details pending.
These records grant no approval, retry, lease, merge, or milestone authority."""

WORK_REMAINING_GUIDANCE = """Brief work remaining summary
Keep the operator's remaining-work summary to three short lines: Remaining, Estimate, Next.
State the remaining tasks and gates. Name the next actor and action.
An estimate is a scoped range of active effort with confidence. Exclude unestimated waiting time.
Use Unknown when no responsible agent can give a reliable range.
Do not infer a percentage or completion time from commits, elapsed time or passing tests.
The Leader calls deck_prepare_work_remaining_summary after each safe published checkpoint and at review handoffs.
The owner supplies the estimate. Put completed work and assumptions in the tool's optional details fields.
Publish its marked block near the start of the main GitHub issue and PR with existing authorized access.
Replace only that block. Preserve other facts and all operator-action records.
Refresh the block when source, scope, phase or review findings change.
Put technical details and evidence behind links. Never publish private values, prompts or raw command output.
The report is a team claim. It grants no authority and satisfies no approval, review, CI or milestone gate."""

HUMAN_REVIEW_SUMMARY_GUIDANCE = """Summary for human review
PR means GitHub pull request. CI means automatic checks.
Before you request human review or merge, add a brief Human review summary.
Put the summary near the start of both the PR body and its main issue body.
State the goal in one or two sentences. List the main changes.
State the completed checks and material limits. Distinguish source review, CI, and human trials.
State the requested human action. Link the PR. State its target branch and any separate decision gate.
Keep the summary brief. Link detailed evidence below it.
Use deck_render_github_summary for a compact current summary when the team's process selects that format.
Keep one responsible issue and PR body publisher. Replace owned sections instead of appending current status paragraphs.
Keep superseded estimates and source states in history. Preserve human requirements and other Deck sections.
Preserve the original issue facts and existing PR metadata. Update a clearly marked summary section.
Update the summary when the PR head, results, or requested action changes.
Do not use a comment as the only summary. Do not claim completion without evidence.
The summary does not replace approval, independent review, or the configured merge policy.""" + "\n\n" + WORK_REMAINING_GUIDANCE + "\n\n" + OPERATOR_ACTION_CONTEXT_GUIDANCE


def team_communication_guidance(controlled_language_enabled: bool = True) -> str:
    """Keep human summaries required when a member opts out of controlled language."""
    writing_style = CONTROLLED_LANGUAGE_GUIDANCE if controlled_language_enabled else OWN_WRITING_STYLE_GUIDANCE
    return f"{writing_style}\n\n{HUMAN_REVIEW_SUMMARY_GUIDANCE}"
