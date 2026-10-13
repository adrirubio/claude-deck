# Native harness screens

Fixtures for #549 (scope 8): recognizing a team pane that waits at an interactive screen. Each file is one `tmux capture-pane` of a native session. `.txt` is plain text (`capture-pane -p`), and `.ansi` keeps the escape codes (`capture-pane -p -e`).

| File | Harness | Expected state |
|---|---|---|
| `claude-question-form.txt` / `.ansi` | Claude Code 2.1.292 | waiting: question form (one question, "↑/↓ to navigate") |
| `claude-question-form-two-questions.txt` | Claude Code 2.1.292 | waiting: question form (two questions, "Tab/Arrow keys to navigate", wrapped footer) |
| `claude-trust-prompt.txt` / `.ansi` | Claude Code 2.1.292 | waiting: workspace trust prompt |
| `claude-trust-prompt-with-permissions.txt` | Claude Code 2.1.292 | waiting: trust prompt with the "pre-approves tool permissions" warning |
| `codex-sign-in.txt` / `.ansi` | Codex CLI 0.159.2 | waiting: sign-in screen |
| `claude-idle-after-declined-question.txt` | Claude Code 2.1.292 | **not** waiting: the normal prompt. The scrollback still mentions the declined question |
| `codex-idle-prompt.txt` | Codex CLI 0.159.2 | **not** waiting: the normal prompt |

How they were made (2026-10-13, by the v3.1 supervisor):
- Live captures: each harness ran in a **private tmux server** with a throwaway home, never in the team's server, with no Agent Mail server configured. The Codex sign-in screen needs `--no-daemon` with a fresh `CODEX_HOME`. `codex-idle-prompt.txt` is a read-only capture of an idle team pane.
- `claude-question-form-two-questions.txt` and `claude-trust-prompt-with-permissions.txt` are transcribed from live team panes (2026-10-12). They are plain text only.
- Sanitized: temporary paths are `<workspace>`, and home paths are `/home/<user>`.

Recognize the **active** prompt area at the bottom of the screen, not the scrollback. Screens change between CLI versions, so record the version with each new capture.
