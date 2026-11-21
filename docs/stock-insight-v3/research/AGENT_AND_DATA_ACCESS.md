# Agent and financial data access

Verified against primary documentation on **20 November 2026**. This is an implementation handoff, not a record of installed integrations or successful authenticated data retrieval.

## 1. Decision

**Use existing official financial tools before building equivalent tools.** Agent-accessible event summaries, transcripts, financial statements, market history and numerical analytics already exist. The first implementation should connect one suitable provider, discover its actual tools and permissions, and let the investigator choose relevant calls. Build Stock Insight's research memory, evidence records and capability-gap handling around those calls.

The preferred initial candidate is **Fiscal.ai's free API/MCP access**, combined with issuer and SEC sources: its documented 100-company allowance includes NVIDIA and Microsoft and permits 250 calls/day. This is a useful starting entitlement to verify during setup, not a promise that every Fiscal dataset is free. In particular, its Street Consensus reference explicitly excludes personal API plans. [Free API access](https://docs.fiscal.ai/docs/guides/free-trial) · [Dataset reference](https://docs.fiscal.ai/docs/api-reference)

Use an already-owned suitable subscription first. Quartr is especially useful for event summaries if Jack already has an eligible Pro subscription. FMP and Alpha Vantage offer official MCP alternatives; there is no reason to build generic wrappers for all three in the first release. Provider selection must not prevent the full research, follow-up and decision-history workflow from operating with explicit coverage gaps.

## 2. What this research establishes

Public documentation establishes the routes below. No provider account was created, no plugin installed, no paid endpoint invoked, and no subscription or credential verified. In this session, read-only plugin-directory searches did not surface exact matches for these named vendors. That directory is account-dependent and nonexhaustive; absence from these results does not establish general unavailability. The session's generic financial web lookup is not evidence of an entitled historical data feed.

Represent access as separate observations:

| State | Meaning | Evidence to retain |
|---|---|---|
| Documented | An official integration and capability are described | Documentation URL and checked date |
| Configured | The selected host has the connector configured | Host/server identifier; configuration version |
| Authenticated | The provider accepted authorization | Status and expiry metadata; never a raw token |
| Discovered | The host obtained actual tool names and schemas | Catalog snapshot or hash and observation time |
| Entitled | The account can request this dataset, company and interval | Plan metadata or an actual endpoint response |
| Usable | Returned data meets this question's semantics and freshness | Source, period, basis, timestamp and completeness |
| Observed successful | A real call completed and its result was retained | Request/result receipt and validated evidence IDs |

These are dimensions, not a one-time certification. A connection may remain authenticated while a quota expires, a dataset changes, or a particular historical interval is unavailable.

## 3. Verified connection and entitlement matrix

All five vendor MCP endpoints below are vendor-hosted HTTPS services. A laptop executor or recording client can connect outbound; these integrations do not require exposing the laptop to the internet.

| Provider | Exact route and authorization | Entitlement and verified cost boundary |
|---|---|---|
| **Fiscal.ai** | `https://api.fiscal.ai/mcp`, Streamable HTTP. OAuth sign-in or `Authorization: Bearer <API key>`; both map to the same account access. REST is also available. | Free API: 100 specified companies, 250 calls/day, no card required; NVDA/MSFT included. Terminal and API/MCP are separate products. Confirm endpoint packages. Current paid API/MCP dollar pricing was not established here; do not reuse an older blog's annual price. [MCP](https://docs.fiscal.ai/docs/guides/mcp-integration) · [Free](https://docs.fiscal.ai/docs/guides/free-trial) · [Account products](https://fiscal.ai/help/) |
| **Quartr** | `https://mcp.quartr.com/mcp`, stateless Streamable HTTP; OAuth 2.1/PKCE, no API key. Request read access where supported. | Requires Quartr Pro; Student excluded. Intended for individual subscribers' own research. Product integrations use Quartr Public API. Pro/API public pricing is sales-led; no dollar quote verified. Combined limits: 100/minute, 2,250/hour, 8,500/day, plus per-tool limits. [Connection and terms](https://mcp.quartr.com/docs) · [Pricing](https://quartr.com/pricing) |
| **FMP** | `https://financialmodelingprep.com/mcp`, Streamable HTTP. Generic clients: `X-API-Key` header preferred. Official ChatGPT/Claude connectors use OAuth; custom OAuth clients require preregistration. | MCP follows API plan limits. Basic: $0, 250 calls/day. Published annual-billing equivalents: Starter $19/month, Premium $49, Ultimate $99. These are not month-to-month quotations. Higher tiers list broader history, intraday data and transcripts. [MCP](https://site.financialmodelingprep.com/developer/docs/mcp-server) · [Pricing](https://site.financialmodelingprep.com/pricing-plans) |
| **Alpha Vantage** | `https://mcp.alphavantage.co/mcp`; OAuth consent authorizes an Alpha Vantage API key. Official local stdio implementation also exists. | Standard free quota: 25 calls/day. Premium endpoints and timely US market data have additional requirements; premium purchase does not replace the documented market-data entitlement process. Current paid dollar amounts were not retrievable reliably. [MCP](https://mcp.alphavantage.co/) · [Premium/entitlements](https://www.alphavantage.co/premium/) |
| **Finnhub** | `https://mcp.finnhub.io/mcp`, Streamable HTTP; OAuth using a Finnhub account, no key pasted into the assistant. | Each dataset follows the account's plan. Official guide documents a broad tool catalog; it does not establish that a free account receives every tool's data. Current personal pricing and exact historical package access were not verified. [Official guide](https://finnhub.io/static/finnhub-how-to-connect-mcp-server.html) |

Do not place keys in repository files, prompts or saved source URLs. Prefer host secret storage and supported header/OAuth configuration. A connector installation supplies a route; it does not supply the provider's entire data license.

## 4. What agents can actually call

The names below are documented tool names unless explicitly identified as REST routes. Fiscal's REST semantics were verified, but its current MCP operation names were not obtained; discover those from the connected server rather than inventing aliases.

| Provider | Concrete useful operations | Interpretation and history boundaries |
|---|---|---|
| **Quartr** | `search_companies`, `list_events`, `get_event_summary`, `get_document_summary`, `read_transcript`, `search_documents`, `get_financials`. | Event summaries can return `null`; fall back to the transcript/documents. Transcript responses expose live status and timestamp pagination. Financials carry filing references; quarterly cash-flow entries can be year-to-date, so period normalization matters. Default financial windows are limited, with older retrieval supported. [Tool reference](https://mcp.quartr.com/docs/tools) |
| **Fiscal.ai** | REST capabilities include `/v1/company/news-summary`, `/v1/company/ir-events/transcript/{eventKey}`, standardized/as-reported statements, ratios and company KPIs. MCP exposes the account's supported endpoints. | News summaries are generated collections, not guaranteed instant explanations of a price move; inspect generation/applicability times. Coverage and package availability must be checked per company. Distinguish company/period identifiers from ticker text. [Introduction](https://docs.fiscal.ai/docs/introduction) · [API reference](https://docs.fiscal.ai/docs/api-reference) |
| **FMP** | Grouped tools include `quote`, `statements`, `company`, `calendar`, `secFilings`, `technicalIndicators`, `news`. Each takes an `endpoint` enum plus endpoint-specific arguments. Example: `quote` with `endpoint: quote`, `symbol: NVDA`. | `tools/list` filters endpoints by the key's plan. Inspect required parameters for the selected endpoint. Idle sessions expire after 15 minutes; reinitialize after expiry. Narrow calls that hit its 25-second timeout. Empty results are distinct from tool errors. [MCP schemas and behavior](https://site.financialmodelingprep.com/developer/docs/mcp-server) |
| **Alpha Vantage** | Direct MCP functions include `GLOBAL_QUOTE`, `TIME_SERIES_DAILY`, `NEWS_SENTIMENT`, `EARNINGS_CALL_TRANSCRIPT`, statements, `ANALYTICS_FIXED_WINDOW`, `ANALYTICS_SLIDING_WINDOW` and technical indicators. | Fixed-window analytics computes return/risk statistics, including drawdown and correlations. This is numerical computation, not an earnings-specific historical study. Intraday/full or adjusted history can require premium access; transcripts are documented back to 2010 Q1. [MCP tools](https://mcp.alphavantage.co/) · [API definitions](https://www.alphavantage.co/documentation/) |
| **Finnhub** | `quote`, `ohlc`, `financials`, `basic_financials`, `eps_estimates`, `revenue_estimates`, `earnings_calendar`, `earnings_call_transcript`, `sec_filings`, `economic_calendar`, `newsroom`, `press_releases`. | These provide data for investigation; the published catalog alone does not prove a generated event-summary service or a usable historical consensus archive. Check price timestamp, resolution and plan access. [Tool catalog](https://finnhub.io/static/finnhub-how-to-connect-mcp-server.html) |

### Expectations are the material trap

Fiscal separates **Agentic Consensus**, constructed from guidance, models and vendor estimation, from **Street Consensus**, sourced from Zacks. The latter documents daily consensus-change history, but excludes personal API plans; the published `asOf` example is a date, not proof of intraday pre-announcement availability. Do not label Agentic Consensus as Wall Street expectations or promise free point-in-time Street history. [Agentic methodology](https://docs.fiscal.ai/docs/reference/estimates) · [Street access and history](https://docs.fiscal.ai/docs/api-reference)

More generally, a current estimate cannot silently stand in for the estimate immediately before an earnings release. Price history, transcript history and historical analyst expectations are separate datasets. If sufficient history is absent, preserve current snapshots prospectively and explain which retrospective comparison cannot yet be supported.

### Summaries, calculations and investment judgments are separate

A provider summary helps locate relevant disclosures. A statement endpoint supplies figures. A numerical service computes an explicitly defined statistic. A skill guides investigation and interpretation. None alone establishes why a stock moved or whether buying suits Jack's horizon and existing exposure.

Use existing computations when their definitions fit. Add small reproducible local calculations for genuinely missing work, such as comparing matching accounting periods or studying a specified event cohort. Preserve inputs, code/version and assumptions. Do not rebuild a general finance analytics platform merely because one required comparison is missing.

## 5. Existing agent methods and execution routes

**Anthropic's financial-services repository is useful reusable methodology.** It contains financial-analysis and equity-research workflows, modeling methods, earnings-review patterns and Managed Agents examples, under Apache 2.0. Adapt the relevant methods and preserve licensing. A skill/plugin gives instructions and integration configuration; it does not grant FactSet, S&P, LSEG or another provider's subscription. The published EarningsReviewer pattern is a reference, not a requirement to deploy several permanent specialist agents. [Official repository](https://github.com/anthropics/financial-services) · [Managed examples](https://github.com/anthropics/financial-services/blob/main/managed-agent-cookbooks/README.md)

Fiscal also publishes skills for company analysis, news/events, earnings calls and reactions. These can improve tool selection and interpretation, provided the selected host actually loads the method and has the relevant tools. They are not independent validated financial engines. [Fiscal skills](https://docs.fiscal.ai/docs/guides/mcp-skills)

| Host route | Role and access boundary |
|---|---|
| **Local Codex CLI/SDK** | Preferred initial laptop executor when existing ChatGPT-backed usage and local authentication are available. Programmatic execution and MCP reuse the borrowed agent runtime. Keep Stock Insight's private-use authentication separate from later hosted/commercial distribution. [Noninteractive execution](https://learn.chatgpt.com/docs/non-interactive-mode.md) · [SDK](https://learn.chatgpt.com/docs/codex-sdk.md) |
| **Claude Code / Cowork** | Alternative if already subscribed and its tools fit better. Financial methods can be adopted without migrating the durable research record. Native Claude cloud tasks provide a documented subscription-funded trigger route; account limits and actual result submission remain setup checks. [Cloud tasks](https://code.claude.com/docs/en/routines) |
| **ChatGPT Work / dot** | Useful research interface and optional executor through compatible tools/events. Treat the user's observed scheduling failures as operational evidence: completion is established by a stored accepted result, not the existence of a schedule. [Custom events](https://developers.openai.com/plugins/build/mcp-events) |
| **Managed-agent API** | Optional when credits or an agreed capped budget justify it. Claude Managed Agents accepts remote MCP servers/toolsets and session authorization through vaults. API/runtime charges and provider data charges are separate from consumer subscriptions. [MCP integration](https://platform.claude.com/docs/en/managed-agents/mcp-connector) · [Pricing](https://platform.claude.com/docs/en/about-claude/pricing) |

Do not add another assistant subscription merely to have a second executor. Use the deployment guide for laptop availability and the selected host's current authentication configuration. Native execution cannot make a sleeping laptop run local work.

### ChatGPT's institutional finance product is a different entitlement

OpenAI documents a separate **ChatGPT for Financial Services** plan, sold to institutions and built on Enterprise. Selected financial datasets are included without separate provider setup, but this is not an entitlement to assume for a personal ChatGPT account. Published included coverage has material limits, including 15-minute delayed Nasdaq pricing and Daloopa's 24-hour delay and per-user allowance. Additional sources may require separate provider access. This product's hosted datasets are not automatically a portable API available to a separate Codex application. [Official plan description](https://help.openai.com/en/articles/20001517-chatgpt-for-financial-services)

## 6. Connection direction

The documented provider route permits a local MCP client to connect outbound to the vendor's service. It does not require the executor to own that connection directly.

For the selected laptop design, use the thin recording MCP bridge/client described in [Architecture, section 5](../design/ARCHITECTURE.md#5-financial-tool-integration). It forwards the provider's actual schemas and calls while recording permitted requests, responses and receipts. Direct native-host calls remain an option, with their actual, potentially weaker provenance preserved; do not fabricate service receipts or use an unobserved call to satisfy a required source check. Stock Insight's own tools can stay on loopback or use a local transport. A vendor data request and a request to Jack's private research store are different connections.

For a cloud executor, vendor MCP remains remotely reachable, but its authorization must be configured for that executor. A ChatGPT app connection does not by itself prove that an unrelated API session inherited permission. Reaching private laptop tools requires a supported outbound custom-tool/result bridge, a supported tunnel, or another deliberately chosen arrangement; a cloud process cannot directly address the laptop's `localhost`. [OpenAI application functions](https://developers.openai.com/api/docs/guides/agents-api/tools/functions) · [Claude custom tools](https://platform.claude.com/docs/en/managed-agents/tools)

Provider webhooks reverse the direction: the provider calls a receiving endpoint. Fiscal documents signed update webhooks and short retry behavior, which does not establish durable catch-up after a laptop has been offline. Begin with outbound polling/reconciliation where appropriate; do not introduce public laptop exposure just to use a financial MCP server. [Fiscal webhooks](https://docs.fiscal.ai/docs/guides/webhooks)

## 7. Required behavior: “NVIDIA tanks; should I buy?”

The agent should formulate and revise an investigation within available permissions. It need not follow a user-authored list of every possible event.

1. **Clarify the observed move from data.** Resolve the security, price interval, trading session, adjustment basis and feed delay. Compare the move with relevant market/sector context when available. Do not infer a real-time crash from a stale closing price.
2. **Find the relevant evidence.** Inspect current events, issuer disclosures, news and existing case context. Use an available summary for orientation, then verify material claims against underlying disclosures or transcript passages. Follow unexpected but relevant leads.
3. **Test competing explanations.** Compare actuals, guidance, margins and key operating measures with compatible expectations. Investigate broad-market effects and simultaneous disclosures. Separate observed facts from causal hypotheses.
4. **Use available numerical tools.** Calculate relevant returns, valuation scenarios and sensitivity. Request a historical comparison only if its cohort, information cutoff and data coverage are supportable. A provider's generic correlation function does not answer a conditional earnings-reaction question automatically.
5. **Relate the findings to the decision.** Use known horizon, thesis, exposure and constraints; ask only for missing context that materially affects the decision. Produce conditional conclusions, contrary evidence, missing information and what would change the view.
6. **Preserve and follow up.** Store sources, calculations, decision rationale and unresolved questions. Create appropriate follow-up research, including recovery when a call fails. Never turn incomplete data into confident certainty.

Tool discovery should use the selected host's or recording bridge's MCP discovery support, as applicable to the configured route. Persist the actual exposed schemas and choose from that catalog. Do not require Jack to name tools, and do not fabricate a catalog from provider marketing.

## 8. Capability gaps and economical implementation

When a needed capability is missing, continue the useful investigation and record a precise gap:

```yaml
capability: earnings_consensus_as_of
question: NVDA expectations immediately before the specified release
required:
  - fiscal period and accounting basis
  - EPS and revenue, currency, analyst count
  - defensible information cutoff
status: not_entitled
attempt: provider, actual tool, receipt or documented restriction
fallback: issuer guidance and clearly labeled available estimates
impact: cannot quantify a verified surprise against prior Street consensus
next_step: investigate an entitled historical source or begin prospective snapshots
```

Other statuses include `not_connected`, `not_exposed`, `unsupported`, `history_missing`, `semantics_unverified`, `stale`, `rate_limited` and `temporarily_unavailable`. A gap is evidence for later engineering or a purchase decision; it does not authorize buying data, installing arbitrary servers or changing credentials.

During construction, verify one selected provider end to end: discover tools, make a permitted small request, inspect timestamps and accounting semantics, store provenance, and exercise a denied or missing response. These are normal integration requirements within the complete solution, not a separate narrow product experiment.

Budget independently for the agent host, financial datasets, and any infrastructure. Start with existing included host usage plus a free or already-owned data entitlement. Record actual request quotas and charges. Buy one additional dataset only when a documented gap materially improves the workflow; do not treat zero incremental subscription cost as unlimited capacity. Before product expansion, revisit storage, display and redistribution permissions for each provider, rather than extending a personal research entitlement by assumption.
