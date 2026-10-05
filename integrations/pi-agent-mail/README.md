# Pi Agent Mail tools

The Pi tool list must match the real standalone MCP server. Keep the private close tool out of the public list.

After you change an MCP tool, run these commands from this directory. Use Python with the backend MCP dependencies installed.

```sh
python sync_manifest.py
python sync_manifest.py --check
```

The command reads tool definitions. It does not register an agent or call the Deck API.

Backend tests compare the complete list with the real server. The pinned Pi runtime tests check argument validation. Fixture transport tests keep the existing schema check, pane fence, and uncertain outcome rules.

## Native activity

After authenticated Mail startup, the owning opted-in extension writes a small activity file beside the current native
session. The file contains process identity, session identity, state, and time.
It contains no prompt, reply, tool argument, credential, or UI prompt title.
It does not grant dispatch, approval, or Mail authority.

Deck reads this file through the current authenticated Mail pane binding. It
checks the authenticated session's exact native PID, its kernel start, its pane ancestry, its project,
and the native session header. Pi keeps the first turn in memory until the first
assistant reply. The extension supplies the SDK header during that turn. Deck
also checks the file header as soon as the file exists. It does not select the
newest session file.
The native process must have existed when its authenticated Mail session was
created. PID reuse cannot inherit that session's observation. The recorder
checks its current Mail generation and pane fence before each write. A refused
or retired generation cannot overwrite the owner's marker. A confirmed dead
auxiliary session does not hide a live owner. Different live native identities
remain unknown.
Missing access, an older extension, or `--no-session` gives an unknown state.
Share only the session directory when a controller uses another Unix account.
The activity file uses mode 0640, subject to the native process umask.

An agent start or native progress event shows working. Tool calls and automatic
retries keep that state. The `agent_settled` event shows idle after all automatic
continuations end. A blocking Pi UI prompt also shows a static state. Idle does
not mean that the assigned task or work item is complete. An expired native
observation shows unknown. No timer turns process liveness into a work signal.

The controller and this extension must both be updated. Load the extension at a
safe session boundary. Do not reload or restart an agent during an active task
only to update this display. Existing working animation and reduced-motion rules
apply to verified Pi activity.
