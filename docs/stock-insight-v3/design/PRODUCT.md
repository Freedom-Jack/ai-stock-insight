# Product specification

Status: accepted implementation direction. Version 3.1, 20 November 2026.

## 1. Purpose

A saved high-level goal starts regular discovery, event preparation and watchlist-scoped investigations. An external notification brings consequential findings to the user while the site is closed. The website holds cited reports, follow-up, review and execution status. Daily visits and per-investigation source selection are unnecessary.

Stock Insight is a personal research desk with initiative. It helps Jack notice consequential events, understand how they connect to companies, examine claims with appropriate tools, preserve what he has learned, and return to unresolved questions without needing him to invent an expert process each time.

The user should be able to say “Keep me prepared for important developments affecting these companies” or “NVIDIA has fallen; is buying now supported by the evidence?” The system translates that goal into appropriate research, uses available data and explains its conclusion. It may challenge the question's premise, suggest a better comparison or identify missing information. It should not ask the user to prescribe every source or step.

Dependable execution and uncertain market inference are different. The application can make source checks, arithmetic, timestamps and follow-up inspectable. It cannot make the next price movement deterministic. A useful answer contains a ranked judgment, its assumptions, the strongest counterevidence and the next observation that could change it.

## 2. First usable release

All seven capabilities below belong in the release; their depth can improve during use.

| Capability | User experience | Persistent result |
|---|---|---|
| Anticipation | Upcoming earnings, macro releases, elections/policy milestones and relevant industry events appear before the user asks | Versioned events, preparation cases, scenarios and scheduled follow-up |
| Monitoring | Important new filings, issuer releases and enabled news sources are checked; a bounded discovery scan looks beyond existing questions | Documents, origin clusters, relevance reasons and coverage gaps |
| Investigation | The agent selects financial tools and methods appropriate to the question | Cited brief, calculations, alternatives, unknowns and follow-up |
| Continuity | New sessions recover company context, prior reasoning and unresolved issues | Dossiers, cases, claims, questions and revisions |
| Guided learning | The system identifies the next useful inquiry and explains the analytical method in context | Ranked agenda and versioned methods |
| Decision review | User rationale and optional conditions can be recalled and revisited | Attributed decision notes, observations and later reviews |
| Execution visibility | The user can see whether work ran, what it covered and whether delivery succeeded | Expected runs, jobs, tool receipts, delivery state and recovery history |

A release with only earnings analysis or only monitoring is incomplete. Conversely, a complete release need not include options modeling, streaming tick data, every vendor, a mobile application or a predictive trading model. Descriptive historical analysis and explicit unsupported-data states are valid first-release behavior.

## 3. Research universe and themes

A **watchlist** is an explicit set of financial instruments. A **company** is an entity that may have several instruments. A **theme** is a research grouping or hypothesis: semiconductors, AI infrastructure, data-center power, export restrictions or exposure to falling interest rates. Sector labels are useful metadata but do not replace themes.

Theme membership is many-to-many and carries a reason. An instrument can belong to several themes, a theme can cover companies absent from the broker list, and a company can be relevant without being held. Exposure links are typed and sourced: supplier, customer, competitor, geographic dependence, regulation or shared demand driver. No ownership or portfolio allocation is inferred from membership.

The research universe includes companies and instruments from active selected source-list memberships, local manual pins and adopted theme memberships. Theme membership has an explicit company-or-instrument subject. Adding a company to research does not automatically select all its share classes/listings for price monitoring: choose a specific resolved instrument when the question requires one. Agent-suggested additions remain proposals until adopted. A discovery budget can investigate an adjacent company without silently adding it to permanent monitoring. Show why each entity or instrument is being followed.

IBKR owns membership of its selected Client Portal/Mobile lists; Stock Insight owns research state, local themes and local additions. The initial direction is external list → Stock Insight. Membership authority is independent of whether the snapshot arrives manually, through a file or through a verified API. A later native Stock Insight list is a deliberate adoption/copy with provenance, not an automatic change of authority or a two-way merge requirement. See [watchlist synchronization](WATCHLIST_SYNC.md). Initial relevance does not require holdings, quantities, purchase prices, account IDs or balances.

## 4. Primary surfaces

Provide a private local web interface with six views backed by the same records:

| View | Required content and actions |
|---|---|
| Today | Important changes; short research agenda; pending analysis; missed checks; ask a question; mark a brief reviewed |
| Upcoming | Calendar, tentative/confirmed times, event relevance, preparation state and next checkpoints |
| Companies & themes | Dossiers, lists and their freshness, sourced exposures, open questions and recent changes |
| Research | Cases, briefs, passages, calculations, alternatives, methods and revision history |
| Journal | User notes, stated intentions or reported actions, review conditions and outcome reflections |
| Status | Coverage, source health, expected runs, delivery, executor access, quotas/costs, import state and backup status |

Chat-style questioning is available from the local view and the local agent. A cloud ChatGPT/other-host connector is optional later; it must not be a prerequisite for the laptop release. A cloud agent cannot be assumed to call a laptop's loopback service. See the architecture's outbound API alternative.

The interface should show the answer first, then evidence and uncertainty. Internal lease generations, SQL IDs and provider plumbing belong in expandable diagnostics, not the normal research reading flow.

## 5. Brief contract as experienced by the user

Each substantive brief answers: what changed; why it matters to the question; what the evidence supports; what remains uncertain; and what happens next. It includes:

1. A dated conclusion with a defined horizon or an explicit missing-horizon assumption.
2. Relevant facts and calculations, with source links and timestamps.
3. A ranked explanation and the strongest plausible alternative.
4. Distinctions between reported fact, management statement, estimate, agent inference and user belief.
5. Coverage and missing inputs that could materially change the answer.
6. A small next-action/research agenda, including review conditions when useful.

Avoid a list of equally weighted possibilities with no judgment. Do not manufacture numerical confidence or an individualized trade size. A useful directional assessment can be conditional and qualitative. If a probability is given, identify whether it is an empirical estimate or a subjective forecast and specify the outcome, horizon, method and resolution rule.

For “should I buy?”, research can proceed while a material context question is asked. Distinguish business value, price paid and near-term timing. An absent holding record does not prevent analysis of those issues. If the user wants allocation advice, acknowledge that the product has no portfolio view and ask only for context needed for that separate question; do not obtain account data to fill the gap.

## 6. Natural-language delegation

Save a `Goal` that captures objective, universe, output, schedule, deadline semantics, permitted autonomy and budget. Show a readable interpretation once. “Report at six” means research begins before a six-o'clock report deadline; “start checking at six” means a different trigger. Ask only when ambiguity changes behavior materially.

Suggested initial schedules are configurable defaults, not automatically created by this document: a weekly look-ahead on Sunday at 18:00 New York time, a short weekday pre-market update at 08:30, and a weekday closing review at 16:30. Company events follow actual calendars; market-day summaries honor exchange holidays and early closes. Exact event times may be unknown or revised. Source polling follows rate limits and expected cadence, not a single universal interval.

Allow autonomous public-source retrieval, deterministic calculations, draft interpretations, internal research questions and bounded follow-up. New credentials, paid access, external publication, brokerage access and code deployment are different actions and do not follow merely from a research question. The runtime agent can propose a capability improvement; the coding workflow implements it separately.

## 7. Availability and attention

The laptop is the initial development, testing and trial environment. Use a foreground application with a durable inbox and a verified notification route that reaches the user with the browser closed. Automatic startup is optional. The planned `server_single_node` profile uses one supervised Linux host and the same application and data contracts. Continuous operation depends on source, provider, network and host availability.

The laptop trial checks while the machine is awake and the application is running with usable network/authentication. It must show its actual active periods. If the machine sleeps across a deadline, preserve the missed deadline and recover useful work after resume. A late reconstruction must not look like an on-time check. Server deployment removes dependence on laptop sleep; it does not guarantee an always-current broker session or watchlist snapshot.

A quiet report states the enabled sources checked and any gaps. “Nothing important found” is an analytical conclusion; “all required sources checked successfully” is an operational claim that needs receipts. An unavailable source cannot be hidden by a fluent summary from another source.

The Windows trial delivers a native notification while the computer is awake and the user session is interactive. The Today inbox retains reports for later reading and explicit review. The continuous server profile requires a configured off-device route and independent health observation. An urgent verified source fact can appear before a longer investigation. Delivery, opening and explicit review have separate records. External messaging services and server commissioning require operator authorization.

## 8. Learning during use

Keep useful earlier chats with authorship and provenance, then extract preferences, facts to verify, hypotheses, methods and decisions as distinct records. Never promote a prior assistant answer directly to a verified fact. Reading a brief is not agreement with it.

When new evidence changes an interpretation, append a revision and identify affected conclusions. Preserve the prior reasoning and its as-of state. A successful Microsoft/NVIDIA analogy becomes a hypothesis to study, not an automatic universal rule.

A missing financial tool should produce a structured `CapabilityGap` with the blocked question, attempted alternatives and a concrete acceptance example. This feeds the development backlog. The system continues with useful supported analysis and makes the limitation visible. See [research workflows](AGENT_WORKFLOWS.md).

## 9. Excluded from this release

Order execution; account/portfolio ingestion; personalized position sizing; hidden subscriptions or paid fallbacks; arbitrary runtime installation of tools; public multi-user hosting; mandatory vector/graph databases; and a custom general-purpose agent framework. These exclusions define a coherent personal product. They do not prevent future product expansion through explicit architecture decisions.
