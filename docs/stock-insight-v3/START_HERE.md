# Stock Insight — implementation handoff

Version 3.2 · 20 November 2026 · Prepared for Jack Xu

## Decision

Build a **personal research system with a lightweight laptop trial and a planned single-server deployment for 24/7 operation**. It borrows an existing agent for reasoning and existing financial tools for data and analysis. The application owns the normalized research universe, evidence, research memory, due work, accepted results and delivery status. External platforms initially own their selected watchlists' membership. It prepares for events, investigates developments, preserves reasoning and guides the next useful question.

Version 3.1 incorporates the user's clarification: the laptop is primarily for development/testing and initial use; IBKR Client Portal/Mobile currently holds the watched list; synchronization is inbound only. A future native Stock Insight list is possible, but does not require two-way synchronization or every provider adapter now.

Version 3.2 adds the owner's step-by-step Codex runbook and refines the development default to Astra Extra High for the initial integrated build. The Version 3.1 product, architecture and acceptance specifications remain applicable. High remains a usage-conscious option; Ultra is useful for ambitious work that can be delegated cleanly. This is a task-based recommendation, not a benchmark result on this repository.

The first usable release covers the whole research cycle. Build it in integrated increments and use it during development. Do not turn this plan into another isolated earthquake pilot or require a predictive-performance experiment before implementing the broader product.

This package is a specification, not an implemented application. Commands, schemas and module names marked as targets must be built. No financial provider account, brokerage session or paid endpoint was exercised in preparing this package. Public documentation establishes available interfaces; account access and output quality still need implementation-time checks.

## Read in this order

| Reader / task | Files |
|---|---|
| Owner: understand the product | [Product](design/PRODUCT.md), [decisions and open items](delivery/DECISIONS_AND_OPEN_ITEMS.md) |
| Owner: launch Codex | [Codex runbook](delivery/CODEX_RUNBOOK.md), [model and effort](delivery/MODEL_AND_EFFORT.md) |
| Codex: start implementing | [Model and effort](delivery/MODEL_AND_EFFORT.md), [start prompt](delivery/CODEX_START_PROMPT.md), [architecture](design/ARCHITECTURE.md), [build plan](delivery/BUILD_PLAN.md) |
| Implement a feature | Relevant [contracts](design/DATA_AND_TOOL_CONTRACTS.md), [research workflows](design/AGENT_WORKFLOWS.md), [watchlist sync](design/WATCHLIST_SYNC.md), or [laptop operations](design/LAPTOP_OPERATIONS.md) |
| Establish completion | [Acceptance scenarios](delivery/ACCEPTANCE.md) |
| Check the rationale or a vendor claim | [Background](research/BACKGROUND.md), [agent/data access](research/AGENT_AND_DATA_ACCESS.md), [IBKR findings](research/IBKR_FINDINGS.md), [sources](research/SOURCES.md) |

Research files explain evidence, alternatives and uncertainty. Design files define the selected implementation. Delivery files define sequencing and completion. Vendor documentation can change: confirm an interface before coding it, then record the version and observed behavior. A research table is not a promise that an account has every listed capability.

## Authority and change control

The user's current instructions and applicable repository instructions govern the work. Within this package, accepted decisions in `delivery/DECISIONS_AND_OPEN_ITEMS.md` and the design contracts are normative; examples illustrate them. Research findings do not silently override the selected design. When evidence requires a material change, record a decision with reason and affected files, then update the contracts and examples together.

This package supersedes the **implementation guidance** in the earlier Version 2 DOCX and Version 3 handoff where they differ. Earlier research remains background. In particular:

- `local_trial` is a foreground laptop development/testing profile; `server_single_node` is the planned profile for continuous operation. A Windows companion is optional.
- Initial integration uses a local executor and outbound provider access; no public tunnel is required.
- Watchlists and research themes define relevance. Holdings, portfolio balances, account IDs and trading capabilities are outside the initial product.
- The user's Client Portal/Mobile list remains authoritative. Initial manual/file snapshots are a transport fallback; verified automatic inbound retrieval can replace the transport. TWS installation and provider writeback are unnecessary.
- Prefer documented official financial MCP/API tools before writing replacement data services.
- Missing analytical capabilities produce explicit gaps and engineering proposals, while available analysis continues.

## Concrete defaults

| Area | Selected starting point |
|---|---|
| Product | Personal U.S.-equity research; global sources when relevant; monitoring and understanding first |
| Laptop | Windows with WSL2 as the working baseline; adapt deployment only if the actual machine differs |
| Coding agent | GPT-6.2 Astra with Extra High for the initial integrated build; High for bounded implementation, Ultra for broad parallel audits/reviews, Sol Medium for economical routine work; verify actual account/client availability |
| Application | One Python application, SQLite, immutable permitted document files, server-rendered local web view |
| Runtime agent | One local Codex CLI adapter if supported authentication, tool access and permissions pass preflight; an outbound API adapter is the alternative |
| Research tools | Official provider MCP/API routes, selected during setup by exact capability and entitlement; public primary sources remain useful without them |
| Financial-data seed | Evaluate Fiscal.ai's documented free universe for NVDA/MSFT and required endpoints; choose one price route after checking freshness and limits |
| Watch universe | Inbound mirror of the selected IBKR Client Portal/Mobile list; authority is separate from manual/file/API transport; local pins, themes and proposals remain separate |
| Clock | UTC storage; America/Toronto reporting and America/New_York market-session scheduling; local device clock monitored for skew |
| Availability | Trial runs while the laptop is available; planned server profile provides continuous execution with explicit outage/recovery behavior |
| Spending | No automatic paid fallback; explicit configuration required for paid provider/runtime use |
| Planned server | Same application and research record on one Linux host, supervised and backed up; no distributed rewrite required |

These defaults do not assume the user owns a particular subscription. Setup must display actual executor and data access. Missing optional credentials do not block public-source work, the UI, memory, scheduler or the rest of development.

## Examples

- [Local settings](examples/local.settings.example.toml): proposed configuration, with optional integrations disabled until configured.
- [Server settings](examples/server.settings.example.toml): deployment-profile overlay for the same application; service activation requires real configured access and destinations.
- [Codex development settings](examples/codex.config.example.toml): optional model/effort snippet; separate from application runtime settings.
- [Normalized watchlist](examples/watchlist.normalized.example.json): synthetic instrument-only snapshot; no account or portfolio fields.
- [Capability gap](examples/capability-gap.example.json): an actionable engineering request created during research.
- [Job result](examples/job-result.example.json): illustrative application payload, not a vendor API response or a real stock recommendation.

## Repository baseline

The reviewed repository is [Freedom-Jack/ai-stock-insight](https://github.com/Freedom-Jack/ai-stock-insight), audited at commit `835f06bdca2e7baea4ef1e652b46948d19ed4a74`. Its 68 existing tests passed offline during the preceding review. This is evidence about that snapshot, not a claim about current HEAD or live feed operation. Codex must inspect the current checkout, preserve user changes, rerun the relevant baseline and adapt the migration to actual differences.

Deliver the new system alongside the existing `stockwatch` implementation, retaining its useful regression behavior and provenance. The detailed migration and first implementation tasks are in the build plan. The package is self-contained; Codex does not need the previous DOCX to implement it.
