# Stock Insight implementation record

## Current decision after the second bounded repair

**I2 acceptance and I3 remain on hold for targeted independent re-review.** This pass started at `6fbc121ffbbfa0735cea76b67f116d6d109d8fe4` on the reported worktree and branch. The independent reviewer confirmed High 1, High 4, High 5 and Medium 6. The second pass addressed High 2, High 3, Medium 7 and Medium 8. [Independent dispositions](implementation-rereview.md) · [Second-pass rules and evidence](implementation-remediation.md#second-repair-pass-at-6fbc121)

| Work IDs | Second-pass state |
|---|---|
| R06, X01/X04 | Receipt-linked recovery for reversed comparison operands, compatible observations and discoverable worker search results. Retried calculations and earlier brief manifests retain their history. |
| F02/F03, R04, X04 | Source-edition and retained qualification checks at freeze. Current, latest-saved and fixed-cutoff questions have distinct acceptance conditions. Per-claim context IDs and the selected financial calculation are auditable. |
| R04/R06, X01/X02 | Market-move and accounting questions with the same revenue evidence can reach different dispositions. Fiscal-period and currency/unit requirements remain attached to each requested metric. New briefs use `sourced_company_review.v3` and `compare_financials.v1` on schema 2. |
| F04, W01/W02 | Whole-snapshot field validation accepts qualified PNL/CASH alongside other listings, preserves provisional symbols and rejects private reports before retention. |

The four previously confirmed fixes remain covered by the original fabricated-prose, cross-list identity, two-desk browser authentication and continuation-replay tests. No work on I3 was started.

**Repair checkpoint.** `f081d9b236ff0584f9844dae8196e19fb10fece7` contains the implementation and regression tests. The original checkpoint passed 136 tests. The repair passed **151 tests with zero skips**, including all 68 Stockwatch tests and native Edge. The verified schema-2 continuation retained its reviewed historical row, and the Stockwatch monitor replay added zero duplicate alerts. Both original review documents are byte-identical and remain the only untracked files after the documentation checkpoint. [Detailed verification and limits](implementation-remediation.md#verification-boundaries-for-the-second-pass)

**Integration boundaries.** The NVIDIA fixture returned 100 to 120 USD million (+20%) and two missing inputs. The ordinary scripted MSFT control returned 80 to 120 USD (+50%). A separate live, unauthenticated NVIDIA issuer request reproduced the historical 26,044 to 30,040 USD million comparison (+15.3433%), receipt `check_329dd65ec00eb1a9a348b49e`. Actual live model execution, live SEC acquisition and entitled Fiscal access remain unverified. The no-spend boundary remains in force.

## First repair checkpoint at 6fbc121

**Hold I2 acceptance and I3 for independent re-review.** On November 20, 2026 (New York), the repair pass addressed High · 1–5 and Medium · 6–8 from the independent review. The implementation commit is `48bdb8e7e7936ce738aed8076b73d945f5f17c81` on `codex/stock-insight-i1-i2`, directly following the reviewed commit `bfb55d1bdda4527e0789935b6fbef9766a8aefce`. The supplied review is the sole untracked file. The next commit records the repair evidence in documentation. [Per-finding reproductions, fixes and controls](implementation-remediation.md) · [Original review](implementation-review.md)

| Work IDs | Repair state and actual verification |
|---|---|
| F02/F03, R04/R06, X01/X04 | Schema 2 retains v1 editions, briefs and review history. New briefs use `sourced_company_review.v2` and `compare_financials.v1`. The service checks typed observations, calculation inputs, missing evidence and material pre-freeze revisions. Microsoft controls covered correct revenue, a false dividend, honest partials, a resolved gap, a corrected current figure and a valid historical figure. |
| F04, W01/W02, U01 | Rechecked shared contract and issuer bindings at confirmation. Stale previews failed across restart. Compatible lists shared their instrument, and explicit permitted corrections left an audit record. Qualified CASH and MSFT passed the strict instrument projection. |
| X01/X04, O04, U01/O01 | One Edge profile authenticated to both loopback desks and submitted a form to each. A third port received an anonymous request. Replaying the same continuation across restart produced one additional job, brief and inbox row. |
| X02/X03, O03, S01 | Actual unauthenticated NVIDIA issuer HTTPS is enabled and verified. The ordinary Microsoft investigation used scripted model transport and SEC packets. Fiscal used mock transport. Live model, SEC contact, entitled Fiscal operations and broker integrations remain unverified or disabled. |

**Verification.** The reviewed build passed 112 tests. The repaired tree passed **136 tests with zero skips**, including all 68 original Stockwatch regressions, the installed Fiscal SDK contract and headless native Edge. The offline Stockwatch monitor demo added one linked issuer follow-up and added zero on replay. A migration smoke test preserved an accepted v1 row and added a v2 continuation. Local fixtures produced synthetic NVIDIA revenue of 100 to 120 USD million (+20%). The ordinary MSFT scripted comparison produced 80 to 120 million USD (+50%). A separate live public acquisition of NVIDIA's historical GAAP table returned 26,044 to 30,040 USD million (+15.3433%), receipt `check_60255a6ae5a23059bd0e8068`. Actual live model executions and paid calls were zero. [Verification ledger and reproduction commands](implementation-remediation.md#verification-and-integration-limits)

**Outstanding.** Independent re-review is next. The financial method accepts a bounded set of supported observations and comparisons. Human assessment, live A17/A18 model/provider evidence, custom-directory permission preflight, WSL and longitudinal operation remain open. The original work-item history and full release scope follow.

## Original milestone at bfb55d1

The entries through the original verification ledger describe the build submitted for the first review. The operator selected a free fixture investigation and a separate live public-data check.

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

## Original verification ledger

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

The next action is targeted independent re-review of High 2, High 3, Medium 7 and Medium 8, with the four confirmed-fix controls available for regression. The authenticated I2 gate and I3 remain on hold. The remaining I3–I6 work-item definitions stay in the [integrated build plan](stock-insight-v3/delivery/BUILD_PLAN.md).
