# Starting and continuing the build in Codex

Version 3.2 · 20 November 2026

**Recommended first setting: GPT-6.2 Astra, Extra High (`xhigh`).** Use this runbook with the complete handoff. The [model guide](MODEL_AND_EFFORT.md) explains High, Extra High, Max and Ultra; the [start prompt](CODEX_START_PROMPT.md) defines the implementation scope.

## 1. Open the actual local repository

Use Codex on a local checkout for this laptop trial. Open the `ai-stock-insight` repository root in your Codex app or IDE, or start the CLI from that directory. The root is the folder containing the repository README and source code. A repository link or a folder of design documents alone is not the working checkout.

If you already have a checkout, use it and let Codex inspect its current state. If you do not, clone into a new, unused directory. For the handoff's Windows+WSL2 baseline, these commands run in a WSL terminal with Git installed:

```bash
mkdir -p ~/projects
cd ~/projects
git clone https://github.com/Freedom-Jack/ai-stock-insight.git
cd ai-stock-insight
```

For an existing checkout, navigate to its actual path instead. The audited commit in the handoff is context, not a command to reset your current code. Codex will inspect changes before choosing a development branch or worktree; neither should discard your work.

**Windows desktop app:** if you want Codex itself to execute in WSL2, select WSL as the agent environment in Settings and restart the app. The integrated terminal choice is a separate setting. To open a WSL folder, use **Add new project** / **Ctrl+O**, enter `\\wsl$\`, and choose the distribution and repository folder. On macOS/Linux, use your ordinary local checkout and skip the WSL-specific setup. [Official Windows instructions](https://learn.chatgpt.com/docs/windows/windows-app)

These instructions target local execution. A cloud task has a different filesystem; make the same checkout and handoff available in that selected environment before using the prompts. Files in your laptop's Downloads folder are not automatically present there.

## 2. Add the complete handoff folder

Download the latest `stock-insight-v3-codex-handoff.zip` and extract it. The archive keeps its stable filename; `START_HERE.md` identifies Version 3.2.

Place the extracted folder at `docs/stock-insight-v3/` inside the repository, so that these relative paths exist:

- `docs/stock-insight-v3/START_HERE.md`
- `docs/stock-insight-v3/delivery/CODEX_START_PROMPT.md`
- `docs/stock-insight-v3/delivery/BUILD_PLAN.md`
- `docs/stock-insight-v3/design/ARCHITECTURE.md`

The research, design, delivery and examples folders must all be present. If that destination already contains a previous handoff, use a fresh folder such as `docs/stock-insight-v3-2/` and substitute its actual path in the prompts below. Do not overwrite an existing repository `AGENTS.md` or Codex configuration with this package.

## 3. Select the model and execution mode

In the app/IDE model controls, choose **GPT-6.2 Astra → Extra High** if offered. Use the normal coding mode that can edit files and run commands, with the standard project permissions. The design already supplies the full direction; Codex should inspect, make a concrete implementation plan and proceed into code.

If using an installed Codex CLI, run this from the repository directory:

```bash
codex -m gpt-6.2-astra -c 'model_reasoning_effort="xhigh"'
```

Use `/model` to verify the selected model and supported effort choices. **More reasoning…** exposes Max/Ultra where supported. Typing a model name in a task prompt does not switch the actual session. If you want Ultra for a broad audit or review, select it there; the equivalent launch override is `model_reasoning_effort="ultra"`. [Model controls](https://learn.chatgpt.com/docs/models) · [Configuration reference](https://learn.chatgpt.com/docs/config-file/config-reference)

Sign in using your intended account/billing route. ChatGPT sign-in and API-key billing are different. Existing subscriptions do not establish financial-data access or unlimited model usage. If the required model is unavailable, check the updated client and available models; do not silently change billing routes. [Account and compatibility guidance](https://help.openai.com/en/articles/20001275-chatgpt-work-and-codex)

If Codex is not installed, use the [official quickstart](https://learn.chatgpt.com/docs/quickstart) for your chosen app, IDE or CLI, then return here. This runbook does not require switching away from a working Codex surface.

## 4. Send this first message

The message below adopts the complete implementation prompt from disk; you do not need to paste all the documents into the conversation. Change both package paths if you used another folder.

```text
The complete Stock Insight Version 3.2 handoff is at:
docs/stock-insight-v3/

Read delivery/CODEX_START_PROMPT.md in that folder and follow its implementation instructions, together with the current repository instructions.

Inspect the current checkout, working-tree changes, actual tooling and baseline tests. Preserve existing work and choose an appropriate development branch or worktree after inspection. Use the current code as the implementation starting point.

Begin implementing the integrated build plan now. Start with I1's research workspace and continue into I2's on-demand investigation, then the remaining increments toward the complete release. Keep stockwatch working alongside stockinsight. Produce working code, meaningful verification and a continuation record.

Use subagents for independent exploration, implementation or review where useful. Establish shared contracts before dependent edits, assign distinct file ownership or isolated worktrees, and integrate the result in the main session.

Maintain docs/implementation-status.md with completed work IDs, actual verification, enabled integrations, known gaps and next tasks. Distinguish fixture verification from live integration. Continue authorized independent work and raise only concrete decisions that block it. Follow the handoff's access and spending boundaries.
```

The full start prompt already defines the laptop/server profiles, inbound IBKR membership, runtime permissions, source/financial semantics and limits on external actions. Codex must read it before implementation. Give it the correct path if it reports that the file is missing.

## 5. Check working outcomes as development progresses

These are checkpoints within the complete build, not a demand for a planning-only approval turn or a promise that one session finishes the entire product.

| Checkpoint | What you should be able to observe |
|---|---|
| Starting state | Actual HEAD and existing changes recorded; applicable baseline verification; retained existing behavior |
| I1 workspace | A runnable private local UI, synthetic instrument-only watchlist, saved question/case, and exact saved source evidence that survives restart |
| I2 investigation | Question → application record → selected executor and recorded tools → accepted cited brief, with visible missing-data gaps; real integrations labeled separately from fixtures |
| I3–I5 recurring use | Upcoming events generate preparation; monitoring updates cases; methods and journal persist; missed runs and recovery are visible |
| I6 readiness | Backup restore and runtime boundaries verified, actual startup/update instructions, and prepared single-server configuration; server uptime remains unclaimed until commissioning |

After I2, start trying real questions through available authorized sources while development continues toward I3–I6. Unavailable optional providers should create visible gaps, not stall the workspace, public sources, UI and memory. A fixture-only core research path is not ready for normal research use.

## 6. Ask for an integrated review at a meaningful milestone

Extra High is sufficient to request parallel reviewers explicitly. Ultra is useful when you want deeper proactive delegation and accept the usage tradeoff. Choose the actual setting before sending:

```text
Review the current implementation against the handoff and its acceptance scenarios. Use independent reviewers for (1) financial and temporal semantics, (2) persistence, scheduling and recovery, and (3) runtime permissions and watchlist-only data boundaries.

Have reviewers inspect and report first. Reconcile their findings, fix substantiated defects with clear file ownership, and rerun the relevant checks. Verify the combined result. Update docs/implementation-status.md with evidence, limitations and the next unfinished increment, then continue authorized implementation work.
```

Parallel review can expose different failures; it does not replace the final integrated check. Avoid several uncontrolled sessions editing the same working tree. [Subagent guidance](https://learn.chatgpt.com/docs/agent-configuration/subagents)

## 7. Continue across sessions and start the application

Reuse the same session when practical. If you start a fresh session, select the intended model/effort again and send:

```text
Continue Stock Insight implementation in this checkout. Read the current repository instructions, docs/implementation-status.md, the handoff at docs/stock-insight-v3/, and the current code/diff. Verify the recorded state against the actual implementation. Resume the first unfinished integrated increment, preserving existing work and the complete release scope. Carry forward unresolved decisions and actual integration status.
```

Once the application runs, use the setup/start/stop commands Codex actually implemented and verified. Ask it to supply the exact commands and local URL. Names such as a proposed `stockinsight` CLI or `doctor` workflow in the design are targets to implement, not proof those commands exist today.

Configure real sources, executor access and schedules through that setup when it exists. Server commissioning comes after a host and its dependencies are selected. Development model settings must not become the scheduled research executor's settings by accidental inheritance.
