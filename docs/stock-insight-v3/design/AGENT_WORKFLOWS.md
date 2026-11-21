# Research workflows and method guide

Status: normative behavior, with room for the agent to choose relevant steps. These are methods to implement as versioned Markdown plus structured metadata, not a long mandatory sequence for every question.

## 1. Professional autonomy

The investigator receives an objective, relevant history, time horizon/cutoff, permitted tools and a budget. It decides which sources and calculations are useful, follows material surprises, and stops when additional work is unlikely to change the answer within that budget. It may challenge the premise and propose a better question.

Every method specifies: purpose, applicability, material inputs, acceptable fallbacks, output obligations, stop conditions and reopening triggers. The application checks outcomes and evidence, not whether the agent reproduced an identical hidden reasoning trace. Avoid both a vague “be a financial expert” prompt and a brittle universal checklist.

Adopt suitable ideas from [Anthropic's financial-services methods](https://github.com/anthropics/financial-services), with attribution and license notices where code/text is reused. Existing provider methods can also help interpret their tools. A skill supplies instructions/resources; invocation, data access, recordkeeping and completion evidence are separate responsibilities. See [research background](../research/BACKGROUND.md).

## 2. Shared investigation structure

1. **Frame.** Identify the actual decision/research question, horizon and relevant instrument/company. Recover prior reasoning and state material assumptions.
2. **Establish what happened.** Obtain primary evidence and current-enough prices if price movement is part of the premise. Record publication, event and observation times.
3. **Choose tools.** Inspect configured capabilities, exact semantics and access. Prefer existing reliable computations; add local deterministic calculations where the comparison requires them.
4. **Explain and challenge.** Rank mechanisms and alternatives. Look for contrary evidence and confounders. A plausible story is not proof of market causation.
5. **Conclude.** Answer the user's question as far as the evidence supports, with assumptions, uncertainty and the weakest important link.
6. **Preserve and revisit.** Commit evidence, calculations, interpretation, open questions and useful follow-up. Record capability gaps when relevant.

The method can omit irrelevant steps, split a large inquiry, or issue an early partial result. It must not fill missing numerical inputs with guesses merely to complete a template.

## 3. Company orientation and ongoing dossier

When a company enters active monitoring, create a concise sourced dossier: business drivers, segments, customers/suppliers where evidenced, geography, reporting calendar, key financial measures, valuation questions and risks. Distinguish business-level facts from instrument-specific pricing. A semiconductor theme can link designers, foundries, equipment vendors, memory producers and customers through different mechanisms.

Maintain a small set of open questions, each with why it matters, current evidence, next observation and a review date/trigger. Updates should identify what changed since the user's reviewed revision. Avoid regenerating a generic company profile on every event.

## 4. Anticipating a major event

Example: an election, regulatory decision or major macro release. This is a reusable scenario, not a claim that a particular historical event is still upcoming.

- Obtain the event date/status from an authoritative calendar and preserve revisions. Scheduled dates, policy implementation dates and market reaction times can differ.
- Trace plausible mechanisms to watched companies/themes: taxes, export controls, subsidies, procurement, energy policy, rates or demand. Record exposed revenue/cost/geography where available; do not infer party-to-stock direction from a slogan.
- Write a few decision-relevant scenarios with evidence and observable signposts. Election outcome, legislative feasibility and implemented policy are separate stages.
- Inspect what expectations are already observable; clearly distinguish quoted market expectations, analyst opinion and the agent's scenario assumptions.
- Schedule preparation and subsequent checks around useful observations. Date changes update the same event and cancel obsolete future reminders.

Output: event brief, exposure map, supported scenarios, unknowns, ranked research priorities and next checkpoints. A large event may be consequential yet offer no clear directional edge; the system should say that.

## 5. Earnings preparation and review

### Before the release

Pin the expected release/call timing and relevant fiscal period. Capture available Street estimates, management guidance, operational KPIs and the current thesis as separate `ExpectationSnapshot` types. Store estimate provider/as-of precision, capture time, metric basis, units and analyst-count information when supplied. Use licensed historical snapshots only when their availability semantics support the required cutoff.

Write the questions the release should resolve: growth mix, margins, demand/backlog, cash conversion, capex, guidance or company-specific issues. Establish price/valuation context from a verified feed. Do not make “beat or miss” the whole research question.

### After the release

Compare compatible actuals with the frozen baseline. Check guidance, revisions, business quality and relevant segment/KPI detail. A provider summary can orient the investigation; material claims should cite the release or transcript. An initial release-based result may be partial while the call is pending.

When the transcript arrives, reopen only material questions and add qualifications/new information to the existing case. A correction to a conclusion the user reviewed deserves a visible notice. Retain the original result as-of state.

If Street consensus is unavailable, compare with issuer guidance and prior periods, naming that limitation. Fiscal's Agentic Consensus is not interchangeable with Street consensus, and a current estimate retrieved after the event does not establish pre-release expectations. See [agent/data access](../research/AGENT_AND_DATA_ACCESS.md).

## 6. Worked workflow: “NVIDIA has fallen; should I buy?”

This is a behavior example. It contains no live price assertion or recommendation.

**First, check the premise and decision context.** Resolve the instrument and interval: since yesterday's close, after the earnings release, intraday, or over several weeks? Verify price timestamp, trading session and feed delay. Compare relevant benchmark/sector movement when available. Use the user's known horizon; if unknown, present separate near-term timing and longer-term investment implications while asking one material question.

**Next, investigate the likely driver.** Inspect the existing case, issuer disclosures, relevant news and available event summary. If earnings are relevant, compare actuals/guidance with defensible expectations; investigate business/valuation implications. If another catalyst is more relevant, change method. Do not force earnings analysis onto every decline.

**Then, choose the smallest useful analytical set.** Examples include matched financial comparisons, valuation sensitivities, benchmark-relative returns, estimate revisions, or a historical cohort. Technical indicators are context if relevant; they are not mandatory evidence that a bottom has formed. An unsupported intraday question should not be answered with daily bars.

**Produce a decision-oriented assessment.** Explain whether the evidence strengthens/weakens the business thesis, whether the new price plausibly changes valuation under stated assumptions, and how uncertain the timing remains. State the strongest contrary evidence and what would change the assessment. “A decline alone is insufficient evidence of value; the thesis depends on these observable assumptions” can be useful when supported. Avoid an automatic buy/sell recommendation or a mandatory waiting period invented by the software.

**Follow through.** Offer an optional review condition, such as revisiting after the transcript, a specified guidance clarification or a user-defined valuation threshold. This is a decision aid, not order authority. Save the user's expressed rationale and any later reported action separately from the agent's advice.

### Missing-tool branch

Suppose the agent needs pre-release Street revenue/EPS estimates but only current company financials and an event summary are accessible. It should:

1. Confirm the exact gap, including entitlement or time-history failure, with a receipt or documented restriction.
2. Continue with release/guidance/prior-period analysis and mark the absent comparison.
3. Create a `CapabilityGap` for defensible pre-event expectations, with period/basis/as-of requirements and a concrete acceptance example.
4. Check existing approved providers and public documentation for a reusable remedy. It may recommend prospective snapshots or an entitled dataset; it may not buy/install one autonomously.
5. Link the gap to a proposed development task. The coding agent can implement an adapter or calculation later under normal development authority.

This is how everyday use grows the product. The first release needs discovery, gap tracking and a complete supported workflow; it does not need every future analytical tool in advance.

## 7. Investigating the Microsoft analogy

“Microsoft beat expectations and fell; perhaps NVIDIA will too” is a hypothesis, not a scientific rule. Recover the specific event if possible and distinguish remembered observation from verified data. Specify what “beat,” “fell” and “later recovery” mean before examining outcomes.

A useful historical comparison defines the observable trigger, universe, event dates, accounting basis, surprise threshold, price window and benchmark. The cohort must include unfavorable and missing outcomes; preserve exclusions and reasons. Use information available at the explicitly defined decision time for selection, excluding later outcome information. For a "beat followed by an initial decline" trigger, that decision time occurs after the release and specified initial price window; it must precede the later return being studied. Do not choose a benchmark/window because it makes the desired story appear.

Start with descriptive sample counts, median/quantile outcomes, counterexamples and sensitivity to reasonable definitions. Explain whether semiconductor and software cases are comparable. Small samples and overlapping macro events limit inference. A post-event price decline does not identify a cause by itself.

Historical methods can improve question formulation and provide base rates. Prospective dated forecasts and later resolution are needed to assess predictive usefulness; an LLM may already know famous historical outcomes from training. No narrow market-validation pilot blocks implementing the system.

## 8. Financial quality and valuation

Use matching periods and definitions for revenue/margin/cash-flow trends, operating leverage, dilution, balance-sheet resilience and company-specific KPIs. Work from verified numbers, not a summary's unsourced total. Explain unusual items and accounting changes when material.

Prefer transparent sensitivity tables over a single precise target price. State scenario drivers, forecast periods, discount/terminal assumptions or comparable multiples, and why those choices fit the business. The calculation tool owns arithmetic; the agent owns interpretation and assumption discussion. A calculated value is conditional on those assumptions, not an observed fact.

A full institutional model is not required for every user question. Reuse existing provider computations where definitions fit, and retain enough inputs/versions to reproduce the material comparison. Missing data narrows the conclusion instead of inviting invented estimates.

## 9. Weekly synthesis and autonomous agenda

Produce a short look-ahead covering upcoming events, unresolved thesis questions, new contradictions, stale dossiers and selected discovery. Explain why each proposed inquiry matters. Rank by correction urgency, direct relevance, approaching deadlines, novelty and expected information value; do not display an arbitrary score as market-move probability.

Maintain an attention budget: default a few actionable research items and consolidate duplicates. Let the user adjust cadence and depth through ordinary feedback. Repeatedly ignored low-value alerts can be proposed for reduction, but absence of a click is not proof the user wants important coverage disabled.

## 10. Memory and method improvement

Conversation import retains author/time/source. Extract candidates into distinct preference, fact, question, hypothesis, method and decision records. Verify factual candidates before promoting them. A preference changes only with attributable user intent.

Method revisions require a reason, examples, counterexamples, expected improvement and a new version. A single successful call can create a proposal, not silently rewrite the method. Existing briefs retain the version used. Keep corrections and recurring capability gaps as development evidence.

## 11. Stop and escalation rules

Stop when the question is sufficiently answered, the bounded budget is exhausted, additional retrieval has little likely value, or a material missing input cannot be obtained. Submit a useful partial result with precise gaps and next steps. Ask the user only for a decision/context that materially changes the work, such as horizon, a new data purchase or expanded access. Do not require confirmation for ordinary authorized research, calculations or internal follow-up.

No method can authorize new broker access, trading, external publication, installing untrusted tools or changing runtime permissions. These are application/development decisions. Within the approved boundary, preserve the agent's freedom to reason and investigate.
