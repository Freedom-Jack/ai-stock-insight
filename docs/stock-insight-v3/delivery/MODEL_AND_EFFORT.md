# Development model and reasoning effort

Official documentation checked **20 November 2026**. This guide selects the **coding agent building Stock Insight**. It does not select the finished application's research model or grant access to a model, subscription or API.

## 1. Recommended profile

**Start the handoff with GPT-6.2 Astra and Extra High reasoning (`xhigh`).** For the initial integrated build, the interacting persistence, scheduling, evidence and permission contracts justify prioritizing depth over latency. Keep this setting if you want one choice without managing it task by task.

The earlier High recommendation was a usage-conscious default, not a demonstrated quality ceiling. This revision makes that tradeoff explicit. No controlled comparison of High, Extra High, Max or Ultra has been run on this repository; higher effort is not a guarantee of correct software.

| Development work | Exact model ID | Reasoning setting | Stock Insight examples |
|---|---|---|---|
| Initial handoff, integrated implementation and difficult review | `gpt-6.2-astra` | Extra High: `xhigh` | Reconcile the current repository and handoff; implement and verify interacting persistence, lease/recovery, temporal and permission contracts |
| Bounded substantial implementation | `gpt-6.2-astra` | High: `high` | Implement a feature once its interfaces and acceptance behavior are established; choose this when usage matters |
| Broad audit or review with independent parts | `gpt-6.2-astra` | Ultra: `ultra`, if offered | Delegate repository migration, temporal/financial correctness, recovery and permissions reviews; integrate findings in one session |
| A particularly difficult single investigation | `gpt-6.2-astra` | Max: `max`, if offered | Diagnose an unresolved interacting failure when additional individual reasoning is useful |
| Bounded routine implementation | `gpt-6.2-sol` | Medium: `medium` | A specified UI route, a straightforward parser change, focused regression tests or ordinary review fixes |

These are recommendations for this project, not universal OpenAI defaults. There is no requirement to lower effort for routine work. Sol at Medium is an economical alternative once a task's boundaries and expected behavior are clear.

OpenAI's current guidance recommends Astra for demanding engineering and Sol for everyday coding. Its Codex prompting guide associates Extra High with interacting causes; its best-practices guide recommends Extra High for long, agentic, reasoning-heavy work. That guidance supports the initial-build recommendation but does not measure this particular repository. [Codex models](https://learn.chatgpt.com/docs/models) · [GPT-6.2 prompting](https://learn.chatgpt.com/guides/prompting-gpt-6-2-astra) · [Best practices](https://learn.chatgpt.com/guides/best-practices) · [Model selection](https://developers.openai.com/api/docs/guides/model-selection)

## 2. Select the model outside the task prompt

In the Codex app, choose **GPT-6.2 Astra** and **Extra High** in the model/reasoning controls. In an interactive CLI session, use `/model` to inspect and change the available selection. A sentence such as “use Astra Extra High” inside the handoff prompt describes a preference; it does not establish that the client selected that model. [Model controls](https://learn.chatgpt.com/docs/models)

Check the actual account, workspace and client. OpenAI currently documents Codex CLI **0.166.0 or later** for GPT-6.2 Astra and Sol. Model visibility also depends on plan, seat and workspace settings. The research environment's CLI was `0.172.0-alpha.2`; that is not a check of Jack's installation. [Compatibility and access](https://help.openai.com/en/articles/20001275-chatgpt-work-and-codex)

If Astra is unavailable, Sol at High is a reasonable project fallback if offered. Record the substitution. Do not claim an unavailable model was used or silently switch to separately billed API access.

## 3. Exact CLI examples

From the repository checkout, start the recommended initial development session:

```bash
codex -m gpt-6.2-astra -c 'model_reasoning_effort="xhigh"'
```

Then provide [the handoff start prompt](CODEX_START_PROMPT.md). The command selects the model and effort; the prompt defines the work.

For bounded work with a lower usage preference:

```bash
codex -m gpt-6.2-astra -c 'model_reasoning_effort="high"'
```

For a broad parallel audit/review, after confirming Ultra is offered:

```bash
codex -m gpt-6.2-astra -c 'model_reasoning_effort="ultra"'
```

For bounded routine work:

```bash
codex -m gpt-6.2-sol -c 'model_reasoning_effort="medium"'
```

These examples use Bash/WSL quoting. `-m` selects the model; `-c` supplies a TOML configuration override. They do not change sandbox permissions, approval rules or authentication. The installed CLI's read-only help confirmed both flags; no authenticated model request was executed during this research. [Model selection in CLI](https://learn.chatgpt.com/docs/models) · [Configuration reference](https://learn.chatgpt.com/docs/config-file/config-reference)

## 4. Minimal configuration keys

The equivalent development settings are:

```toml
model = "gpt-6.2-astra"
model_reasoning_effort = "xhigh"
```

Prefer the explicit session commands initially. If these keys are saved in a development configuration, retain its scope and review how it interacts with existing user, project and managed settings. Do not replace a whole configuration file just to add two fields.

The effort strings discussed here are `medium`, `high`, `xhigh`, `max` and `ultra`; availability depends on the selected model and client. A configuration key accepting a string is not proof that an account can execute every value. [Configuration reference](https://learn.chatgpt.com/docs/config-file/config-reference)

## 5. Usage and billing

Signing in to Codex with ChatGPT uses the account's applicable ChatGPT/Codex allowance and billing. Using an API key follows separate API pricing and the API account's model access. The same model name does not make those billing routes interchangeable. [Authentication and billing distinction](https://help.openai.com/en/articles/20001275-chatgpt-work-and-codex)

Start with existing supported access. An included allowance is finite; larger context, more reasoning and longer work can increase usage. Do not estimate included tasks by dividing a subscription price by API token rates. If limits are reached, inspect the actual usage status and resume or choose an already-authorized alternative. A paid fallback requires explicit configuration. [Codex pricing and usage](https://learn.chatgpt.com/docs/pricing)

This handoff does not verify Jack's plan, remaining quota, API credits, model permissions or financial-data subscriptions. Selecting Astra or Sol does not grant any additional provider entitlement.

## 6. What Ultra adds, and when to use it

OpenAI describes **Max** as more reasoning for a single difficult task. **Ultra** combines maximum reasoning with proactive delegation to subagents. Supported choices can be inspected through `/model` and **More reasoning…**. Higher effort increases time and token use; parallel agents add their own work. [Reasoning choices](https://learn.chatgpt.com/docs/models#know-when-to-use-max-or-ultra) · [Subagent behavior](https://learn.chatgpt.com/docs/agent-configuration/subagents)

Ultra is a reasonable choice for the initial repository/specification audit or an integrated release review: migration, financial/time semantics, recovery and permissions are meaningful independent review areas. It is also an option for the full build when the owner prefers its usage tradeoff; the main agent must still sequence dependent work and reconcile the result. It does not remove the need for shared contracts or verification.

Extra High can also use subagents when explicitly requested. The start prompt now requests them where useful. Prefer independent exploration and review first; for concurrent edits, assign distinct ownership or use isolated worktrees, then verify the integrated result. Official guidance cautions that parallel writers can conflict and add coordination overhead. [Subagent workflow guidance](https://learn.chatgpt.com/docs/agent-configuration/subagents)

The practical default remains **Extra High for the initial build, Ultra for ambitious work that splits cleanly**. Actual quality, iteration cost and quota use should inform later changes. Do not invent a percentage quality improvement, a token multiplier or a guaranteed completion time.

## 7. Keep the production research executor separate

The development agent reads and changes repository code. The runtime research agent investigates financial questions through scoped tools. They have different permissions, execution patterns and cost constraints.

The implementation must explicitly configure the runtime's provider, model, reasoning effort, authentication route and budget. Pass those settings into each worker invocation instead of inheriting a developer's global/project Codex defaults. Record the actual executor/model configuration with each run. A development session switching to Extra High must not silently increase the cost of subsequent scheduled research.

Select the runtime profile during implementation using available access and observed research quality. This document does not make Astra Extra High or Ultra the runtime default. The durable job, evidence and result contracts remain independent of that later choice.
