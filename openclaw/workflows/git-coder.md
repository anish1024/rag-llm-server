# Workflow: Local Git Coding Loop (Refined for Small LLMs)
This deterministic playbook governs multi-file code modifications. Follow each checkpoint precisely. Do not skip steps.

## Phase 1: Environment & Workspace Preparation
1. **Target Discovery:** Navigate to the requested path using `@openclaw/shell`. Verify the path exists.
2. **Sync Mainline:** Run `git checkout main && git pull` to prevent working on stale code.
3. **Isolate Feature Branch:** - Generate a short, context-specific branch name prefixed with `agent/` (e.g., `agent/fix-auth-expiry`).
   - Run `git checkout -b <branch_name>`.

## Phase 2: Targeted Code Ingestion & Modification
[cite_start]*Crucial: To protect the 64k token context window, do not read entire directories blindly.* [cite: 58, 68]

1. [cite_start]**Locate Target Files:** Use terminal tools (`find`, `grep`, or file viewing) to isolate only the files relevant to the issue description.
2. **Incremental Ingestion:** Read files one by one. Maximize attention by reading only structural headers or specific code blocks first if files exceed 300 lines.
3. [cite_start]**Draft the Patch:** Plan changes logically before touching the file[cite: 132]. Rewrite only the target functions or components. Maintain existing code styling and formatting rules.

## Phase 3: Defensive Testing & Failure Recovery
1. [cite_start]**Execute Suite:** Run the project's native test command (e.g., `npm test`, `pytest`, or `cargo test`) via `@openclaw/shell`[cite: 210, 212].
2. **Evaluate Test Pipeline State:**
   - **IF TESTS PASS:** Advance immediately to Phase 4.
   - **IF TESTS FAIL (Self-Correction Loop):**
     - Capture the exact error or stack trace from the terminal output.
     - **Limit:** You are permitted a maximum of **3 self-correction iterations** to prevent infinite processing loops.
     - Analyze the failure against recent code modifications, apply an adjusted fix, and re-run the tests.
     - If failures persist after 3 attempts, halt the workflow and skip directly to Phase 5 (Alerting User of Failure).

## Phase 4: Staging & Upstream Deployment
1. **Validate Git Status:** Run `git status` to ensure only the intended code changes are being staged.
2. **Commit Changes:** Stage files and run `git commit -m "feat(agent): automated patch implementation with validated test passes"`.
3. [cite_start]**Push & PR Generation:** Use the `@openclaw/github` skill to push your branch upstream to the remote repository and construct a clear Pull Request[cite: 210]. 
   - Name the PR title clearly and summarize the edits made in the description body.

## Phase 5: Telegram Notification & Handoff
1. **Compile Reporting Metrics:** Check your operational state.
2. [cite_start]**Dispatch Message:** Send an update directly to the user via the paired Telegram channel[cite: 201].
   - [cite_start]**Success Template:** "✅ Task completed successfully! Branch `<branch_name>` verified against test suite. Pull Request opened: <PR_URL>. Standing by for your next assignment or review comments." [cite: 221]
   - **Failure Template:** "⚠️ Execution stalled. Applied code fixes are failing unit tests after 3 optimization cycles. Reviewing logs is recommended. Standing by for instructions."
3. **Power Down/Standby:** Sleep background processes and wait cleanly for the user's next explicit chat string.