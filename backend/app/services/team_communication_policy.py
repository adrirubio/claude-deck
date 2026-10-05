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

HUMAN_REVIEW_SUMMARY_GUIDANCE = """Summary for human review
PR means GitHub pull request. CI means automatic checks.
Before you request human review or merge, add a brief Human review summary.
Put the summary near the start of both the PR body and its main issue body.
State the goal in one or two sentences. List the main changes.
State the completed checks and material limits. Distinguish source review, CI, and human trials.
State the requested human action. Link the PR. State its target branch and any separate decision gate.
Keep the summary brief. Link detailed evidence below it.
Preserve the original issue facts and existing PR metadata. Update a clearly marked summary section.
Update the summary when the PR head, results, or requested action changes.
Do not use a comment as the only summary. Do not claim completion without evidence.
The summary does not replace approval, independent review, or the configured merge policy."""


def team_communication_guidance(controlled_language_enabled: bool = True) -> str:
    """Keep human summaries required when a member opts out of controlled language."""
    parts = [HUMAN_REVIEW_SUMMARY_GUIDANCE]
    if controlled_language_enabled:
        parts.insert(0, CONTROLLED_LANGUAGE_GUIDANCE)
    return "\n\n".join(parts)
