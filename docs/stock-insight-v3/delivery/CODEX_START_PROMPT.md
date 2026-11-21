# Copy-ready implementation prompt

Use this prompt with the repository open and this complete package available. If convenient, place the package under `docs/stock-insight-v3/` without overwriting unrelated files. The prompt does not require that exact location; identify its actual path first.

## Select the development model before sending the prompt

Recommended starting setting: **GPT-6.2 Astra — Extra High** (`gpt-6.2-astra`, `xhigh`). Keep it for the initial integrated implementation and difficult reviews. High is a usage-conscious option for bounded work. Ultra is appropriate for broad independent audits/reviews and other work that splits cleanly, when offered by the client/account; it is not required to request subagents explicitly. Sol — Medium is the economical routine-work option. See [MODEL_AND_EFFORT.md](MODEL_AND_EFFORT.md) for the reasoning and [CODEX_RUNBOOK.md](CODEX_RUNBOOK.md) for owner steps.

In the chosen Codex app/IDE, select the model and effort in the model controls. In a WSL terminal, start a session with:

```bash
codex -m gpt-6.2-astra -c 'model_reasoning_effort="xhigh"'
```

Then provide the prompt below. Text inside a prompt does not switch the actual model. These settings select the development session; the Stock Insight runtime executor has its own explicit configuration and must not inherit this session's model/effort or billing mode.

---

Implement the complete personal Stock Insight system described in the attached Version 3.2 handoff for the repository `Freedom-Jack/ai-stock-insight`. The included Version 3.1 product, architecture and acceptance specifications remain applicable; Version 3.2 refines the Codex development guidance.

Start by reading the package's `START_HERE.md`, `delivery/MODEL_AND_EFFORT.md`, `design/PRODUCT.md`, `design/ARCHITECTURE.md`, `design/DATA_AND_TOOL_CONTRACTS.md`, `delivery/BUILD_PLAN.md` and `delivery/DECISIONS_AND_OPEN_ITEMS.md`. Record the actual development model/effort in the continuation note if the client exposes them; do not claim a setting merely because the prompt names it. Read the relevant workflow, deployment, watchlist and acceptance documents as you implement. Research files provide evidence and alternatives; the selected design and current user instructions govern implementation. Do not require the previous DOCX.

Inspect applicable repository instructions, current HEAD, existing code/tests, working-tree changes and actual local tooling. The handoff audited commit `835f06bdca2e7baea4ef1e652b46948d19ed4a74`; do not assume the current repository is unchanged. Preserve user work and the working `stockwatch` regression behavior. Use an isolated branch/worktree if appropriate. Do not push, deploy, publish, purchase subscriptions or connect a brokerage account as a consequence of this prompt.

Use subagents when independent exploration, implementation or review can improve the result. Start parallel work with bounded responsibilities; establish shared schema and tool contracts before dependent writers proceed. Assign one owner to each edited file or use isolated worktrees, and integrate and verify the combined changes in the main session. A new Git branch alone does not separate existing uncommitted edits. Preserve them and report any relevant overlap.

Proceed to implementation, not another research-only plan. Build the integrated increments in `BUILD_PLAN.md`, maintaining the complete first-release goal: anticipation, broad monitoring, investigation, memory, guided methodology, decision review and visible execution/recovery. The first useful on-demand investigation should connect the real record, selected executor, available data tools and accepted brief. Expand the proactive and continuity workflows in the subsequent increments. Do not reduce the product to a one-event earthquake pilot or make market-performance testing a prerequisite.

Use one Python app, SQLite/files, a private web view and one runtime executor. Implement `local_trial` as a simple foreground Windows+WSL2 development/testing profile and `server_single_node` as the planned 24/7 profile using the same application and records. Windows companion/autostart/toasts are optional and must not delay the useful local research loop. Prepare server supervision, health, notification and backup configuration; do not deploy or buy a server merely because this profile exists. Do not add Docker, a public tunnel, distributed services or multiple agent frameworks without a documented need. Inspect actual versions and supported library/API contracts before implementing integrations. Prefer existing official financial MCP/API tools and reusable research methods over rebuilding equivalent services.

The coding agent and runtime investigator have different permissions. The runtime investigator may select approved tools, calculate, research, propose questions and record capability gaps. It may not install arbitrary tools, edit production code, alter credentials, access broker/account/portfolio data, place trades or publish externally. Apply the actual runtime restrictions and verify them rather than relying on a prompt to enforce isolation.

Implement strict watchlist-only relevance. The user's list currently lives in IBKR Client Portal/Mobile. The external list owns membership; Stock Insight consumes it one way. Begin with instrument-only manual/file snapshots, preserving external authority and validating/projecting before persistence; do not require TWS or claim an unverified native Portal export. Keep authority separate from transport and local research additions. A future native Stock Insight list is an explicit adoption/copy, not a reason to build two-way synchronization or every provider adapter now. Do not import old portfolio examples/fields. Automatic IBKR retrieval remains conditional until the documented access/startup questions are resolved; a read-only broker credential is not automatically watchlist-only. Server operation does not eliminate broker authentication limitations.

Confirm only the account access that is actually configured and authorized. If a credential or paid dataset is unavailable, implement the adapter and meaningful fixtures, expose the gap, and continue independent work. Do not fabricate successful integrations, historical consensus, live prices or test results. Never silently switch subscription execution to paid API billing. Ask for a material access/spending decision only when necessary to activate that concrete integration.

Retain exact source versions, periods, units, as-of semantics and actual tool receipts. Missing inputs produce partial results and actionable capability-gap records. Scheduled work needs expected-run records before dispatch; sleeping-laptop misses remain missed after catch-up. A successful process exit, tool event or notification acceptance is not by itself an accepted research result or user review.

Write code and documentation in cohesive increments. Use meaningful contract, financial, privacy and recovery tests from `ACCEPTANCE.md`; do not optimize for test count or assert an exact agent tool sequence. Verify enabled providers with small authorized calls when available. Record what is fixture-verified, live-integration-verified and observed during normal use separately.

Maintain a concise `docs/implementation-status.md` with adopted decisions, completed work-item IDs, meaningful verification, actual enabled integrations, known gaps and the next concrete tasks. Maintain schema/migration and method versions. If work spans sessions, leave the repository and continuation record coherent so the next session resumes implementation without repeating product discovery.

At each substantial checkpoint, report what now works, how it was verified, remaining limitations and the next integrated increment. Continue all authorized independent work; do not stop merely to ask whether to proceed. The desired outcome is a complete useful research system, easy to trial on the laptop, with a prepared single-server profile for continuous operation and a capability-improvement workflow. Distinguish local readiness from live server commissioning; do not claim 24/7 operation before a selected host and its external dependencies are verified.

---

## Owner handoff

Give Codex the entire extracted folder, not just this prompt. The examples are proposed application schemas/configuration, not secrets or live account data. Once code exists, use the implemented setup/doctor workflow to select actual accounts, sources and schedules. This document does not itself create schedules or connect services.
