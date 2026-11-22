# Decisions, defaults and open items

Version 3.2, 20 November 2026. This file prevents research possibilities from silently becoming build requirements. This revision changes development guidance in D16 and adds a launch runbook; the product and architecture remain those of Version 3.1.

## 1. Accepted direction

| ID | Decision | Reason and consequence |
|---|---|---|
| D01 | Complete personal research desk built in integrated increments | Covers the full recurring workflow; no narrow pilot prerequisite |
| D02 | Existing agent runtime plus owned domain record | Reuse reasoning/tool selection while preserving research and execution accountability |
| D03 | Markdown handoff and versioned methods; structured runtime state | Agents can read the design; SQL supplies transactions, identity, scheduling and revision safety |
| D04 | Local trial, planned single-server continuous operation | Windows+WSL2 foreground trial; same app/data contracts on a supervised Linux server for 24/7 use; no mandatory Windows companion |
| D05 | One Python app, SQLite/files, modest local UI | Small operational footprint; no initial distributed platform |
| D06 | One selected executor, initially local Codex if preflight passes | Familiar supported local route; replaceable contract; building with Codex does not lock the runtime |
| D07 | Official financial MCP/API reuse first | Existing summaries/data/analytics are available; connect and validate before rebuilding |
| D08 | Strict watchlist-only initial scope | No holdings, account IDs, balances, P&L or trading; relevance comes from lists/themes/questions |
| D09 | Client Portal/Mobile source with manual snapshot fallback | Existing IBKR list owns membership; instrument-only paste/file import needs no broker credential or TWS installation; verified automatic inbound retrieval can replace transport |
| D10 | Broker source owns selected membership; app owns research | Inbound mirror plus local themes/proposals; no two-way list mutation |
| D11 | Agent freedom over investigation, explicit evidence/outputs | Methods guide professional work without a user-authored list of every step |
| D12 | Capability gaps feed normal development | Useful research continues; runtime does not install tools or edit production code |
| D13 | Due work, accepted research, delivery and user review are separate | Missed invocations and failed delivery remain observable |
| D14 | One schedule authority and one writer ownership domain | Avoid duplicate dispatch on laptop, restart and later migration |
| D15 | No silent paid fallback or privilege expansion | Account access is observed, spending/access choices explicit |
| D16 | Astra Extra High as the initial development recommendation | Prioritize reasoning over speed while reconciling interacting contracts; High for bounded implementation, Ultra for broad independent audits/reviews, Sol Medium for economical routine work; check actual client/account access; separate runtime configuration |
| D17 | Authority is per list and separate from transport | External membership remains external through manual/file/API changes; a future native list is a deliberate adoption/copy with lineage |

## 2. Configuration defaults, not hard product requirements

- U.S. equities with globally relevant sources; America/New_York market timezone and America/Toronto reporting timezone.
- One runtime investigation at a time; bounded per-job requests and wall time; source-specific rate limits.
- Trial uses the local inbox and a verified external notification route. Windows desktop delivery satisfies the local requirement. Continuous server operation uses a configured off-device notification route, independent health and off-host backups.
- Weekly look-ahead, pre-market and closing summaries are suggested schedules, activated/configured during setup.
- Instrument-only manual/selected-file snapshots of the external list; authority remains IBKR; company/instrument identity stays explicit; semiconductors is an example theme.
- Prefer a free/already-owned data entitlement. Fiscal.ai's documented free NVDA/MSFT coverage is a candidate, not evidence of the user's configured access.
- Prefer WAL only with a verified patched SQLite runtime; rollback journal is acceptable initially.
- Backup during active use and after recovery when overdue; off-device destination requires an actual configured location.

Defaults may be changed by ordinary configuration without redesigning the domain model. Preserve provenance when a user preference changes.

## 3. Integration conditions

| Item | What is known | What must be verified | Does it block general construction? |
|---|---|---|---|
| Local executor | Official noninteractive/tool interfaces exist | Installed version, actual account mode, usable model/tools, enforceable restrictions and accepted-result round trip | No; adapter/fixtures and other work proceed |
| Structured financial provider | Official MCP/API routes and documented plans exist | Exact required company/endpoint/history/freshness access, quota and retention | No; public sources and explicit gaps remain useful |
| Price route | Multiple documented sources exist | Delayed vs timely data, regular/extended sessions, adjusted history and use rights | Blocks only claims requiring unavailable prices |
| Historical Street expectations | Some vendor products document them | Account entitlement and true pre-event availability semantics; a date-only field may be insufficient | No; use other comparisons and record gap |
| IBKR automatic watchlist sync | Watchlist endpoints exist | Narrow scope or explicit broader trust choice; supported startup without account acquisition; endpoint discrepancy; session behavior | No; file import is the default |
| Local trial setup | Windows+WSL2 is the working baseline | Actual distro, networking, runtime/library versions and live-data permissions; foreground operation first | Does not require Windows companion development |
| Planned server commissioning | One host, same app and record | Actual host, executor auth, private access, notifications, health observer, off-host backup and watchlist input route | Software/profile can be built now; deployment waits for a configured target |
| Backup destination | Portable app backup defined | User's actual local/off-device path and restore evidence | Local backup works; off-device protection stays unverified |
| Future product distribution | Architecture can migrate | Provider redistribution terms, hosted auth model, tenant isolation and operating requirements | Deferred |

## 4. Resolved user clarifications

The user confirmed that the laptop is primarily for testing and initial use, with a server intended for 24/7 operation. The watched stock list currently lives in **IBKR Client Portal and Mobile**. External platforms should initially own their list membership, and Stock Insight should fetch only. A future Stock Insight-owned list is a possibility, not a current two-way-sync requirement. No need to ask these questions again.

Setup choices—selected source list, companies/themes, reporting times, actual subscriptions, backup path and eventual server target—can be collected when actionable. Do not halt independent coding for a preference questionnaire. Read [model and effort](MODEL_AND_EFFORT.md) before starting development; actual model availability is checked in the chosen Codex client.

## 5. Explicitly deferred

Automatic broker API activation pending its documented conditions; portfolio analytics; trade execution; two-way watchlist synchronization; adapters for every platform; native authoritative-list adoption; public remote MCP endpoint/tunnel; multiple runtime hosts; rich real-time market feeds; predictive strategy validation; generalized tool installation; vector/graph databases; multi-user product hosting. The single-server deployment profile is planned, not in this deferred-feature list; its actual commissioning occurs when the user selects the target and access.

## 6. Decision amendment template

Record: decision ID/date; evidence or user instruction; chosen change; alternatives considered; affected contracts/configuration/migrations; compatibility and access/cost implications; validation evidence; and unresolved limitations. A changed vendor plan may require an adapter/configuration update without changing the product architecture. Do not treat an old research note as authority to broaden current scope.
