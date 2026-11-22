# Development plan

Status: implementation plan for the complete personal release. Read [START_HERE](../START_HERE.md), [architecture](../design/ARCHITECTURE.md) and [contracts](../design/DATA_AND_TOOL_CONTRACTS.md) before changing code.

## 1. Delivery strategy

Build in integrated increments that are useful during construction. The release goal remains all seven product capabilities: anticipation, monitoring, investigation, continuity, guided methods, decision review and execution visibility. Tests verify the growing implementation; they are not a separate narrow market-validation project or a reason to keep only one function.

Implement one executor, one selected financial provider, the public-source backbone and one private UI. Use `local_trial` for foreground laptop testing and prepare `server_single_node` for continuous operation of the same application. Verify one external notification route during local delivery. Windows autostart and a companion remain optional. A provider's absent dataset is a visible capability gap; it must not cause a placeholder value or block unrelated product work. Additional vendors and modeling depth follow observed need. For coding-agent model/effort, use [the development profile](MODEL_AND_EFFORT.md).

## 2. Inspect and preserve the existing repository

The audit baseline is commit `835f06bdca2e7baea4ef1e652b46948d19ed4a74`; 68 tests passed offline in the earlier review. Before implementation, inspect current HEAD, applicable instructions, branch/worktree status and local modifications. Rerun the existing test command that the actual repository documents. Do not assume this handoff includes a clean or unchanged checkout.

| Audited behavior | Reuse / migration action |
|---|---|
| Dated exposure evidence, source versions, duplicate handling, replay and health | Preserve semantics and regression fixtures; adapt into the general record |
| `relevance.load_watchlist` supports documented TSMC supplier exposure | Keep as a specialist adapter; implement a separate general company/instrument universe |
| `_quake_decision` and quake/withdrawal rule | Retain as one method/source family; remove it as the product's organizing assumption |
| `Observation` time ordering for already-occurred events | Introduce the new event/time envelope for future, tentative and unknown-time records |
| Network fetch inside a `BEGIN IMMEDIATE` transaction | Move remote work outside the write lock; keep commits short |
| Global receipt ordering restriction | Introduce durable ingest/commit sequence independent of source timestamp order |
| Issuer excerpt capped at 240 characters | Add full permitted document/passage retrieval with exact version references |
| Public HTML inbox | Keep public demonstrations separate; build authenticated private research routes |
| Optional old portfolio/example amounts | Do not activate, import or migrate them into the new watchlist-only product |
| No general LLM, SEC/earnings/MCP or external delivery layer in audit | Build explicit adapters and states; do not describe existing code as having them |

Create `stockinsight` alongside `stockwatch`. Preserve old CLI behavior until equivalent supported migration exists. Make a copy/backup before transforming any user's data. Fixtures are evidence about old behavior, not authority to import personal portfolio fields.

## 3. Integrated increments

Effort ranges are rough planning judgments for experienced development with AI assistance, not measured velocity or a delivery promise. Total is approximately **220–360 focused engineering hours**, including integration and recovery work. Access/authentication delays can add elapsed time. Re-estimate after the first two increments using actual work, while preserving the complete release goal.

| Increment | Work and useful outcome | Depends on | Planning range |
|---|---|---|---|
| I1 — Research workspace | New store/migrations, company/instrument/watchlist model, strict file import, local private UI, source snapshots, basic question/case creation. The user can maintain lists and inspect sourced cases. | Current-repo audit | 28–44 h |
| I2 — Working investigator | One executor, recorded domain/MCP tools, financial-provider discovery/preflight, deterministic comparison, structured result acceptance, readable cited brief, capability-gap record. On-demand questions work end to end. | I1 contracts | 36–56 h |
| I3 — Proactive awareness | Official calendar and issuer/filing intake, enabled news/discovery, goals/expected runs, preparation cases, leased dispatch, urgent facts and routine inbox. The system initiates useful research. | I1; I2 result contract | 44–68 h |
| I4 — Analysis and continuity | Earnings preview/review, policy/general-event methods, valuation sensitivity, descriptive historical comparison, dossiers, conversation import, claim dependencies and method versions. Research accumulates and improves. | I2; I3 sources | 48–80 h |
| I5 — Personal daily use | Today/upcoming/research/journal/status complete, natural-language goal editing, optional review conditions, inbound watchlist reconciliation, foreground laptop use and interruption recovery. Windows convenience integration is optional. | I2–I4 | 36–60 h |
| I6 — Release and server readiness | Backup/restore/export, runtime permission checks, quotas, recovery, setup/doctor, single-server configuration and supervision, notification/health/backup integration contracts, commissioning guide and acceptance evidence. | All increments; begins earlier where useful | 32–52 h |

UI, observability and failure handling begin with I1/I2; I5/I6 are completion passes, not permission to defer all usability or reliability until the end. After I2, use real authorized material alongside fixtures and preserve issues encountered. Partial development is labeled as such; the full release is not declared until the integrated acceptance evidence exists.

## 4. Implementable work items

| ID | Deliverable | Completion evidence |
|---|---|---|
| F01 | Repository baseline and decision record | Current HEAD/changes recorded; baseline tests; no loss of user work |
| F02 | Versioned schema, migrations, timestamps and commit sequence | Future/unknown-time records; atomic migration; retained historical provenance |
| F03 | Source/snapshot/passage and FTS storage | Exact source-version retrieval; safe failed-write recovery; entitlement-aware retention |
| F04 | Company, instrument, theme and exposure model | Listing ambiguity handled; theme membership does not imply holdings or every share class |
| W01 | Manual/file snapshots of the Client Portal/Mobile list | Zero broker connection or TWS prerequisite; external authority retained; strict projection before persistence; valid snapshot reconciliation |
| W02 | Membership lifecycle and identity resolution | Partial/empty/error candidates preserve last good set; source changes preserve dossiers |
| X01 | Authenticated local domain tools | Scoped reads/writes and typed errors; no arbitrary SQL/HTTP/broker operation |
| X02 | Selected executor adapter and preflight | Real supported execution reaches accepted result; authentication/budget mode visible |
| X03 | Capability discovery and recording bridge | Actual provider schemas retained; exact endpoint access/semantics observed; receipts captured |
| X04 | Leases, idempotency and submission | Duplicate/late/competing runs cannot duplicate or revert a result |
| X05 | Goals and expected-run ledger | A never-started job still produces a missed obligation; report-vs-start intent explicit |
| X06 | Distinct dispatch/notification outboxes | Trigger receipt, accepted result, notification and user review distinguishable |
| S01 | SEC/issuer sources | Relevant filings/releases retained with dates and passages; fair-access rate policy |
| S02 | Company/macro/policy calendars | Tentative and revised dates; upcoming events initiate preparation |
| S03 | Permitted news and bounded discovery | Origins, duplication and conflicting reports preserved; coverage limits visible |
| R01 | Company orientation and ongoing agenda | Sourced dossier plus ranked open questions and next observations |
| R02 | Earnings preview/review | Frozen expectation types; actuals/guidance/transcript changes; honest unavailable consensus |
| R03 | General-event and policy method | Mechanisms, alternatives, company relevance and follow-up |
| R04 | Price/financial/valuation calculations | Recorded inputs, compatible basis/period, reproducible arithmetic and uncertainty |
| R05 | Historical comparison | Declared cohort/windows; all exclusions; descriptive results and limitations |
| R06 | Dynamic tool choice and capability gaps | Appropriate existing tool selected; missing capability becomes actionable task without halting useful work |
| M01 | Conversation import and method registry | Authorship/provenance retained; assistant claims remain candidates; methods versioned |
| M02 | Research revisions and dependency updates | Contradiction reopens affected case; earlier as-of and reviewed state preserved |
| U01 | Private reading and questioning interface | Six product views share canonical state; answer/evidence/gaps readable |
| U02 | Decision journal and review conditions | Intentions, reported actions, assistant assessments and outcomes remain distinct |
| O01 | Local-trial and single-server profiles | Foreground WSL trial works without companion; server supervision/configuration prepared; duplicate launch, interruption and long absence recover honestly |
| O02 | Backup, restore, case export/import | Restored SQL and referenced blobs verify; retained IDs and source permissions |
| O03 | Cost/access/coverage status | Enabled provider quotas and gaps visible; no silent paid fallback |
| O04 | Runtime permission and local-interface checks | Effective worker/tool scope verified; prohibited paths/operations unavailable |
| O05 | Continuous-operation commissioning | On a chosen target, supervisor, independent health, notification delivery and off-host restore are verified; broker-session freshness remains separate |

Do not turn every row into a separate service, agent or milestone ceremony. Several items belong in the same cohesive change.

## 5. Source and integration sequence

**Public backbone:** SEC submissions/XBRL plus relevant filing passages; selected issuer IR feeds/releases; Federal Reserve/BLS calendars; official policy/election/regulatory sources when relevant; permitted attributable news/search. Implement caching and source-specific cadence. SEC data is valuable but does not supply historical Street consensus or all narrative guidance.

**Financial provider:** inspect the user's existing entitlements first. Fiscal.ai's documented free universe is a plausible seed for NVDA/MSFT, subject to the exact endpoints. Select one supported market-price route after verifying timeliness, adjusted history, session coverage and quota. An ordinary delayed/daily feed must be labeled accordingly. Quartr is optional if eligible access already exists; FMP, Alpha Vantage and Finnhub are alternatives, not simultaneous mandatory integrations.

**MCP implementation:** use the official SDK and actual discovered provider schemas. Start with selected read capabilities; do not implement a generic financial proxy from a marketing list. A catalog may group several endpoints under one tool. Validate endpoint-specific required parameters even where the umbrella JSON schema marks them optional. Preserve unknown access as unknown.

**Broker list:** implement instrument-only manual/file snapshots of the user's Client Portal/Mobile list now. Preserve external authority and inbound-only behavior across transports. Do not require TWS or claim a native Portal export that documentation has not established. The conditional IBKR Web API adapter is not a release blocker. Do not build against the unresolved enumeration example or use generic startup that fetches account data. Activation requires the conditions in [watchlist sync](../design/WATCHLIST_SYNC.md). Implement one provider-neutral read interface, not every platform or a two-way merge engine.

**Executor:** implement one selected route. Verify the installed Codex version, account mode and enforceable restrictions. If the local route cannot meet them, record that fact and select an authorized outbound API adapter; do not implement several speculative fallbacks. Public-source collection, local views and memory still work when the model is unavailable.

## 6. First coding session

1. Read the start prompt and current repository instructions; inspect status and baseline.
2. Record adopted decisions and a short implementation checklist under repository `docs/`; identify actual current-repo differences from this audit.
3. Add the new package/storage boundary and versioned record models, retaining the existing tests and CLI.
4. Implement strict manual/instrument-file import plus a private universe/case view using synthetic fixtures.
5. Add snapshot/passage persistence and the first public-source path; prove the UI can display an exact saved source.
6. Begin the executor/capability/result path. Complete the integrated on-demand loop before expanding optional providers.

The session should produce working code and a precise continuation record, not merely another architecture proposal. If credentials are unavailable, implement the adapter and fixtures, keep integration status explicit, and continue independent work. Do not label fixtures as live integration success.

## 7. From a runtime gap to a shipped capability

1. The research agent records a gap with question, impact, missing semantics, attempted alternatives and acceptance example.
2. Deduplicate it against the backlog and inspect existing official tools before proposing custom code.
3. Choose a remedy: configure existing access, add a thin adapter, implement a deterministic calculation, capture data prospectively, or decline because evidence/value is inadequate.
4. The coding agent implements the selected development scope separately, retaining the originating case as a regression example where permitted.
5. Validate semantics, permissions and data quality; version/register the capability through normal configuration/release.
6. Reopen affected research if the new capability can resolve it. Mark the gap resolved only after the required usable data/result exists.

No runtime self-modification or arbitrary package installation is required to achieve this growth loop.

## 8. Completion and evidence

Use [ACCEPTANCE.md](ACCEPTANCE.md). Map I1 to A02–A03/A18, I2 to A06–A08/A14/A17, I3 to A04–A05/A10/A12/A15, I4 to A07–A11/A13, I5 to A01/A11/A16, and I6 to the full applicable set including A19. These overlaps reflect integrated features, not separate test phases. Record three separate statuses: implemented/fixture-verified, enabled-provider integration-verified, and observed during normal use. A fully coded optional connector may remain disabled without blocking the rest of the release; a core user journey without any live functioning path cannot be described as ready for normal use.

The handoff from development should include startup/stop/update instructions, actual configured providers/quotas, enabled coverage, known gaps, backup destination/status, current limitations and next backlog items. Distinguish a usable local trial from a commissioned 24/7 deployment: prepare the server software/profile during the build; activate and verify it on an actually selected host. No claim of continuous readiness can come from laptop tests alone. Stop optional testing once a concrete risk or gate is resolved; prioritize the complete useful experience over ever-growing test counts.

## 9. Later expansion

Commission the planned server when 24/7 operation is requested; migrate the same app with one scheduler owner and an explicit server-side watchlist input. Expand data/method depth from recurring high-impact gaps. A future Stock Insight-owned list starts from an explicit adoption/copy with lineage and does not imply provider writeback. Add another executor only for a demonstrated capability, cost or recovery benefit. Multi-user hosting introduces separate authentication, tenant isolation, data licensing and operational requirements and needs its own design decision; a personal provider entitlement must not silently become a product license.
