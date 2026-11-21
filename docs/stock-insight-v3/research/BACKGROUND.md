# Product and research rationale

Reviewed 20 November 2026. This document explains the reasoning behind Version 3.1; [Product](../design/PRODUCT.md) and [Architecture](../design/ARCHITECTURE.md) define the selected implementation. Vendor capabilities below come from public documentation, not account-level or financial-quality validation. The earlier report's source identifiers are retained where helpful; the links lead to primary sources.

## 1. What problem is actually established?

The user's examples reveal three connected needs. A scheduled political event should prompt preparation before the user has investigated its implications. An earnings beat followed by a decline should lead to a defensible comparison, rather than repetition of a remembered Microsoft episode. Useful conversations should accumulate into methods and company knowledge that guide subsequent research.

These are broader than a request for stock summaries. The missing experience is continuity between **noticing, investigating, deciding what to examine next, and remembering why**. A finance learner should not have to invent an analyst's procedure for each question.

The user also reports unreliable scheduled follow-through and incomplete adherence to intent in existing assistants. Those experiences justify visible completion, coverage and recovery. Without the original execution logs, they do not identify a universal cause: interpretation, scheduling, tool access, quotas, delivery and machine availability are different possible failure points. It would be unjustified to infer that every hosted agent fails, that a different model solves the problem, or that writing a custom agent loop guarantees reliability.

Likewise, recognizing a price pattern once does not establish predictive skill. The useful design response is a system that makes evidence and process inspectable while preserving uncertainty. Watchlists and research themes provide relevance; ownership, portfolio balances and brokerage access are unnecessary for this initial purpose.

## 2. Product forms considered independently

| Form | Strongest case for it | Remaining difficulty for this user |
|---|---|---|
| Existing assistant with instructions, projects and skills | Familiar interaction, little software to maintain, potentially included usage | The combined event, research-memory and completion workflow must actually be accessible and dependable. A good individual answer does not establish that whole workflow. |
| Financial terminal with calendars and alerts | Existing financial data and company-research surfaces | Personal hypotheses, prior chat reasoning and follow-up decisions may still need a separate record. Terminal access does not automatically authorize programmatic use. |
| Small domain application with a borrowed agent | Independent continuity and execution records while reusing reasoning and tool selection | The application adds operational work, backups and integration maintenance. |
| Full custom autonomous-agent platform | Detailed control of every execution and interface choice | The largest maintenance burden, with no inherent advantage in financial inference. |

The selected form is the third: a small laptop application owns research state and accountability; an existing agent investigates. This is an architectural judgment, not a claim that custom software is always superior. If a host later supplies the necessary durable interfaces and execution evidence, duplicated application responsibilities can shrink.

Three roles explain the boundary: the **interface** is where the user reads and asks; the **executor** performs the investigation; the **record** preserves evidence, interpretations and obligations. Keeping them distinguishable permits an interface or model change without abandoning accumulated research.

This combines agent discretion with ordinary application responsibilities. An agent can revise its investigative plan, while time eligibility, saved results and delivery state remain explicit. Anthropic's distinction between dynamically directed agents and predefined workflows supports this separation conceptually; it does not establish one product's financial quality. [S43: Building effective agents](https://www.anthropic.com/research/building-effective-agents)

## 3. Existing agents remain serious candidates

ChatGPT Work/dot documents tasks, memory and compatible plugin events; those are useful routes for conversation and possible execution. A transport acknowledgement is still different from an accepted research result. Claude Code documents scheduled/cloud tasks, while Codex documents noninteractive execution and an SDK. These interfaces make borrowing a runtime plausible; they do not establish the user's entitlements or observed completion quality. [S03: MCP events](https://developers.openai.com/plugins/build/mcp-events), [S04: dot tasks and memory](https://learn.chatgpt.com/docs/dots/tasks-and-memory), [S07: Claude tasks](https://code.claude.com/docs/en/routines), [S09: Codex SDK](https://learn.chatgpt.com/docs/codex-sdk), [S10: noninteractive execution](https://learn.chatgpt.com/docs/non-interactive-mode)

**Muse personal agent, Muse Code, and the Meta model API are distinct candidates.** Personal-app allowances do not establish API entitlement. Muse Code has its own subscription/authentication arrangements and automation facilities; ordinary API keys have separate metering. OpenClaw offers self-hosted automation and memory, making it another possible host, but introduces a service to operate rather than removing that responsibility. [S14: Muse](https://ai.meta.com/muse/), [S15: Muse Code automation](https://dev.meta.ai/docs/muse-code/extending), [S16: subscriptions](https://dev.meta.ai/docs/muse-code/subscriptions), [S18: Meta API pricing](https://dev.meta.ai/docs/pricing-rate-limits), [S19: OpenClaw automation](https://docs.openclaw.ai/automation/cron-jobs) and [memory](https://docs.openclaw.ai/concepts/memory)

Managed-agent APIs are a meaningful alternative to local execution because they provide runtime/session facilities beyond a raw model response. Their economics differ from consumer subscription usage: model/tool/runtime charges, financial-data charges and maintenance are separate. Documented credit benefits may make an API route attractive for eligible accounts, but neither eligibility nor unlimited use follows from owning a subscription. [S46: OpenAI Agents API](https://developers.openai.com/api/docs/guides/agents-api/overview), [S48: Claude Managed Agents](https://platform.claude.com/docs/en/managed-agents/overview), [S06: OpenAI credits](https://help.openai.com/en/articles/20001626-api-credits-benefit-for-eligible-chatgpt-subscriptions), [S50: Anthropic credits](https://support.claude.com/en/articles/17154008-monthly-api-credits-for-max-ultra-and-team-plans)

The local-trial selection reflects the initial development/testing environment and reuse of available access. A planned single-server profile provides continuous operation later; the laptop is not the permanent availability model. Foreground local use avoids unnecessary Windows infrastructure before the research loop is useful. Included usage can lower incremental spending without eliminating quotas, credential expiry or maintenance. Detailed provider evidence is in [Agent and data access](AGENT_AND_DATA_ACCESS.md).

## 4. Investment-method evidence and its limits

### A repeatable process, with room for judgment

CFA's financial-analysis framework progresses through defining purpose, collecting and processing information, interpretation, communication and follow-up. It also recognizes that analysis has no universal rigid structure. That supports reusable methods with evidence requirements and stopping conditions, rather than either an unrestricted conversation or an exhaustive user-authored checklist. [S34: Financial Analysis Techniques](https://www.cfainstitute.org/insights/professional-learning/refresher-readings/2026/financial-analysis-techniques)

For an election, usefulness begins with mechanisms: which business drivers could change, through which policy process, on what timetable, and with what countervailing effects? An election result, a proposed policy and an implemented rule are different observations. Official election, monetary-policy and economic-release calendars provide dates; they do not provide a directional stock-market forecast. [S26: BLS](https://www.bls.gov/schedule/2026/), [S27: FOMC](https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm), [S28: FEC](https://www.fec.gov/resources/cms-content/documents/2026pdates.pdf)

### Why an earnings beat can coexist with a decline

“Beat” compresses several comparisons. Earnings, revenue and forward guidance can convey different surprises; actuals may also be incomparable with an estimate because the period, units or accounting basis differ. Hand and colleagues' research supports considering revenue and guidance surprises alongside earnings surprise. It does not imply that beats should rise, that declines are bargains, or that one historical analogy supplies a trading rule. [S35: author-institution research summary](https://www.colorado.edu/business/faculty-research/2021/03/23/explaining-firms-earnings-announcement-stock-using-factset-and-i/b/e/s-data-feeds)

For the user's case, weaker outlook, margin pressure, investment requirements, valuation assumptions and simultaneous market developments are competing explanations to investigate. Listing them is not evidence that any caused the observed move. A useful conclusion ranks the support, identifies contrary evidence and separates business valuation from short-term timing.

The comparison depends on what was known **before** release. A current consensus downloaded afterward is not a valid substitute for that snapshot. The NVIDIA earnings release can establish issuer-reported actuals and guidance, but cannot alone validate the user's complete beat-and-price-reaction story. That additionally needs compatible pre-release expectations and timestamped prices. [S39: NVIDIA issuer release](https://nvidianews.nvidia.com/news/nvidia-announces-financial-results-for-third-quarter-fiscal-2027)

### Historical comparisons: descriptive first

A remembered Microsoft event supplies a hypothesis, not a cohort. A meaningful comparison specifies the event definition, eligible universe, information cutoff, initial-reaction trigger, outcome horizon and exclusions. For a “buy after a decline” question, the decision timestamp follows the observable decline; selecting the eventual daily low introduces hindsight. A price-path comparison also differs from achievable returns after delay, spreads and costs.

MacKinlay's event-study framework provides a basis for estimating returns relative to a stated benchmark. That residual is not automatically a causal effect: concurrent disclosures, market conditions and selection still matter. For a broad political or macro event, the benchmark itself may react, so subtracting it answers a relative-performance question and can remove part of the total movement of interest. Raw and relative paths answer different questions. [S36: Event Studies in Economics and Finance](https://www.bu.edu/econ/files/2011/01/MacKinlay-1996-Event-Studies-in-Economics-and-Finance.pdf)

Historical honesty also concerns data availability. Revised data, current-survivor universes and later estimates can make a reconstruction more informed than a real decision could have been. ALFRED's vintage-data model illustrates the difference between an economic observation's date and the values available at a historical date. [S30: ALFRED vintage data](https://alfred.stlouisfed.org/help/downloaddata) A further evaluation limitation follows for this design: restricting retrieved documents cannot establish that a model lacks training-time knowledge of later outcomes. Historical LLM explanations therefore cannot by themselves demonstrate prospective forecasting skill.

### Calibration and decision discipline

Repeatedly trying cohort definitions until a persuasive pattern appears creates overfitting risk. The record of unsuccessful definitions matters alongside the selected result; later observations are more informative about generalization than repeated retrospective refinement. [S38: The Probability of Backtest Overfitting](https://scholarworks.wmich.edu/math_pubs/42/)

A historical frequency, model forecast and subjective scenario estimate are different outputs. Proper scoring rules, including Brier loss for defined binary outcomes, support evaluating probabilistic forecasts against a relevant baseline. They require an explicit outcome, horizon and resolution rule; a few correlated successes do not establish calibration or useful discrimination. No numerical probability is preferable to fabricated precision when the evidence is inadequate. [S37: Strictly Proper Scoring Rules](https://sites.stat.washington.edu/raftery/Research/PDF/Gneiting2007jasa.pdf)

The user's wish for greater determinism is best understood as a wish for a more dependable process. Optional precommitments—such as reviewing a call before reconsidering a thesis—can make choices reviewable. They are user preferences, not an inferred universal waiting rule, mandatory cooling-off period or authority to trade. Process quality and the eventual market outcome remain separate judgments.

## 5. Broad release without unlimited scope

The user's rejection of a narrow prebuild pilot is compatible with integrated delivery. Anticipation, monitoring, investigation, memory, guided methodology, decision review and execution visibility all belong to the initial usable experience. Successive increments can connect those capabilities while their analytical depth improves during use.

Completeness does not require every vendor, market, model or interface. A supported earnings investigation with a clearly identified consensus-history gap is useful; inventing that history to appear complete is not. An unsupported advanced calculation is a capability gap while available research continues. Validation accompanies construction and real use, rather than becoming an isolated predictive-performance gate before the broader product exists.

Operational verification and research evaluation answer different questions. Did the source check actually occur? Was the comparison valid? Did the interpretation help? A fluent completion claim answers none of these by itself. Agent-evaluation guidance similarly distinguishes observed outcomes from conversational claims and combines different forms of assessment. [S45: Demystifying evals for AI agents](https://www.anthropic.com/research/demystifying-evals-for-ai-agents)

## 6. Reuse map and repository baseline

| Existing resource | Reusable contribution | Remaining Stock Insight responsibility |
|---|---|---|
| Agent runtimes | Reasoning, tool selection and session execution | Durable assignments, accepted results and recovery visibility |
| Financial-services reference methods | Earnings research, company coverage and analytical workflows | Adaptation to personal goals, evidence quality and retained method versions |
| Entitled financial providers and public primary sources | Statements, filings, transcripts, calendars and price inputs | Comparable definitions, source timing, gaps and lawful retention |
| Existing `stockwatch` code | Evidence provenance, duplicate handling, replay and source-health behavior | General events, richer research state and the full personal workflow |

Anthropic's reference repository supplies concrete financial methods under Apache 2.0; it does not grant the connected datasets. SEC's APIs provide submissions and extracted XBRL, complementing rather than replacing reading the filing. [S20: financial-services repository](https://github.com/anthropics/financial-services), [S24: SEC APIs](https://www.sec.gov/search-filings/edgar-application-programming-interfaces)

The recorded repository audit used commit **`835f06bdca2e7baea4ef1e652b46948d19ed4a74`**. Its **68 existing standard-library tests passed offline**. This is a result from the pinned audit, not a fresh test of current HEAD, live feeds, broad research quality or predictive value. [S01: reviewed snapshot](https://github.com/Freedom-Jack/ai-stock-insight/tree/835f06bdca2e7baea4ef1e652b46948d19ed4a74)

The audited implementation specializes in earthquake observations and TSMC relationships. Useful evidence/replay semantics coexist with assumptions that do not represent future scheduled events or general company research; issuer excerpts are also too limited for passage-level analysis. This explains the choice to preserve verified behavior while developing the broader domain alongside it. The earthquake case remains a regression example rather than the product's organizing principle. No optional holdings functionality in older materials expands the current watchlist-only scope. [S02: audited source](https://github.com/Freedom-Jack/ai-stock-insight/tree/835f06bdca2e7baea4ef1e652b46948d19ed4a74/stockwatch)
