# Stock Insight implementation record

## Review boundary

I1 and I2 are the review milestone on `codex/stock-insight-i1-i2`. The operator chose a free fixture investigation and a separate live public-data check. The API investigator stays disabled. I3–I6 remain in the release plan pending independent review.

## Starting point and decisions

- **F01**. The isolated checkout started clean at `835f06bdca2e7baea4ef1e652b46948d19ed4a74`, the audited Stockwatch commit. The main checkout held an untracked Version 3.2 handoff. Its files were copied into this worktree with the originals preserved. There was no repository `AGENTS.md`. The root `CLAUDE.md` and README supplied the Stockwatch instructions.
- Windows foreground trial, CPython 3.14.7, SQLite 3.53.1, FTS5 and rollback journal. FastAPI, Jinja, Uvicorn and the optional official MCP client are pinned in `uv.lock`. WSL reported zero installed distributions. The development client identifies Codex/GPT-6 but did not expose a specific model variant/effort. Runtime model configuration is independent.
- Separate private trial and fixture directories and a separate package beside `stockwatch`. They share no portfolio, database, session or writer. An installation mode guard rejects mixing the two research modes or opening an unrelated database.
- Codex CLI 0.151.0 reported ChatGPT login. Inspection of the installed interface did not establish a tool-only subscription worker with the required file restrictions. The selected live adapter is an explicitly configured outbound Responses function loop; the model would receive scoped application functions. No paid call, subscription purchase, brokerage login, external deployment, notification or normal-use observation occurred.

## Work items and evidence

| Work ID | State at this milestone | Evidence |
|---|---|---|
| F02, F03 | Versioned local schema, increasing commit sequence, immutable source editions/passages, FTS5, public-availability cutoff and local commit replay | Separate publication and receipt times, correction retrieval, fixture/live separation and transaction tests |
| F04, W01, W02 | Company/listing identities, local themes and sourced relationships, manual text and stabilized file snapshots, external source reconciliation | Rejected account fields leave safe diagnostics, partial/empty/destructive imports preserve the active list, two source memberships and history survive removals. NVDA and MSFT common stock have curated CIK mappings. Bare symbols stay provisional. |
| X01, X04 | Scoped on-demand tools and acceptance, single active investigation, fenced leases, request idempotency, immutable brief, durable inbox and explicit user review | Concurrent claim/reassignment, stale-result rejection, revision conflict with retained draft, scoped read set, quote validation, duplicate submission and restart |
| X02, X03, O03, O04 | Runtime adapter, discovery and access controls implemented for I2. Live model and optional vendor integration remain unverified. | Scripted Responses calls including malformed replies, auth/quota failure, budgets and restricted function surface. Fiscal MCP discovery exercised with the installed SDK against a mock provider. The live public adapter is verified below. |
| R04, R06 | Financial comparisons and actionable capability gaps implemented for on-demand cases. Price and valuation capabilities remain limited. | Decimal financial comparison, period/basis/unit compatibility, near-zero denominators, immutable versions and deduplicated gaps tied to actual tool receipts |
| S01, U01, O01 | I1/I2 slices delivered. Named historical issuer capture and SEC concept adapter. Private Research, Companies & themes, and Status views. | Local browser form flow, authentication, Host/Origin, CSRF, acceptance and review tested through a real loopback Uvicorn server. Broader sources, six complete surfaces and server supervision are later work. |

## Verification ledger

The original **68 Stockwatch tests passed** before implementation. On this workstation, the sandbox's virtual Windows temp directory failed five Stockwatch HTML file replacements. Running the same tests with TEMP and TMP pointing to a workspace-local temporary directory passed with unchanged Stockwatch code.

**Combined verification: 112 tests passed** using the locked environment with the Fiscal extra, including all 68 original regressions. Two consecutive `stockwatch demo --monitor` runs produced one linked follow-up, then zero additional documents or alerts. A clean Stock Insight directory reproduced the fixture twice, passed `verify-sources` with one retained full version, and opened the saved case through the foreground CLI server. Operator startup, stop and walkthrough commands are in the [README](../README.md#try-the-private-stock-insight-research-desk).

The browser forms were exercised over loopback HTTP, including a duplicate POST, private import rejection, exact version download and explicit review. The desktop browser-control connection was unavailable for a visual inspection. A separate simulated Responses transport completed the actual adapter → domain tools → validation → accepted brief path, recording its simulated model and usage. This is fixture verification.

Full permitted bytes use SHA-256-addressed files. Restricted issuer pages retain exact selected cells and a response hash. Schema migration 1 is checksummed. Earlier embedded full snapshots remain readable. Tests include failed migration rollback, missing/corrupt documents, failed file publication, and event replay from unknown date to tentative interval to confirmed instant. `sourced_company_review.v1` and `compare_financials.v1` are the pinned I2 methods.

| Scenario | Layer | Result |
|---|---|---|
| A02, A03 | Offline | Strict projections, rejected private rows, explicit completeness, destructive candidate review, collision/alias handling, stable file reads, unchanged memberships on failure and atomic commits |
| A06, A08 | Offline | Dated NVDA fixture question challenges the claimed decline. Three exact passages support a move from 100 to 120 USD million. The primary qualification attributes part of the increase to shipment timing and supplies no revised full-year outlook. One partial brief, one calculation, seven service receipts and two gaps. Reading alone leaves the revision unreviewed. |
| A07 | Offline and live issuer | Like-for-like financial comparisons, deliberate mismatch rejection and denominator checks. Historical cohorts and price/valuation work belong to I4. |
| A14 | Offline | Independent SQLite connections competed for one lease, expiry fenced the older writer, a changed replay conflicted and an identical replay returned the original brief. A new interpretation preserved the prior reviewed revision. |
| A17 | **Live public HTTPS** | On November 20, 2026 New York time, CLI capture of NVIDIA’s August 28, 2024 release retained Q2 FY25 GAAP revenue of **30,040 USD million** and Q1 FY25 **26,044 USD million**, a difference of **3,996 USD million (+15.3433%)**. Local receipt `check_370690298d48b86c4baa8bbe`, response SHA-256 `645aad1f57b7e7b06022fa1d9da36ee22fa8b854edaae89a0672b510d89cfe0e`. A repeated capture returned the same receipt as a cache hit. The release is historical. Its exact fetched version has a 2026 receipt time. [Original GAAP table](https://nvidianews.nvidia.com/news/nvidia-announces-financial-results-for-second-quarter-fiscal-2025) |
| A17, A18 | Offline contract and local enforcement | Scoped model input, named operations, origin/session/CSRF checks, no paid fallback. Unconfigured SEC contact, Fiscal entitlement and live model remain unverified. Subscription isolation and WSL interoperability did not pass a live preflight. |
| Normal use | Pending | No longitudinal research-quality or service uptime observation yet. |

## Remaining release scope

- **I2 live gate**. If separately authorized later, select an API model, reasoning effort and per-run budget with a dedicated project key and project spending limit. Verify one accepted run, actual usage, evidence and disabled out-of-scope operations. During this free review, the live adapter remains disabled. SEC requires an identified operator contact. Fiscal requires explicit included access, a dedicated key, and endpoint-specific probes. Broker auto-retrieval remains disabled.
- **I3 proactive awareness**. X05/X06, S01–S03. Materialize expected runs before dispatch, collect calendars, issuers and permitted news, generate preparation cases, and distinguish pending analysis, accepted results and notification delivery.
- **I4 analysis and continuity**. R01–R05, M01/M02. Dossiers, earnings and policy methods, dated expectations, historical cohorts/exclusions, price and valuation methods, conversation import and dependency-driven revisions.
- **I5 personal daily use**. U01/U02, O01. Complete Today, Upcoming, Companies & themes, Research, Journal and Status, user goals, review conditions and laptop interruption recovery.
- **I6 release/server readiness**. O01–O05. Backups with referenced evidence, restore/export, supervision, quotas, off-host health and notifications, and commissioning on a selected host. No automatic backup destination, off-device protection or 24/7 operation is configured.

The next action is independent review of the saved fixture brief, live issuer provenance, private interface and acceptance tests. The complete work-item definitions remain in the [integrated build plan](stock-insight-v3/delivery/BUILD_PLAN.md).
