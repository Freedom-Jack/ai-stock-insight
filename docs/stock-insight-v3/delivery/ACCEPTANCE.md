# Integrated release acceptance

Status: Version 3.1 normative implementation acceptance. These scenarios validate the complete [product](../design/PRODUCT.md), [workflows](../design/AGENT_WORKFLOWS.md), [architecture](../design/ARCHITECTURE.md), [contracts](../design/DATA_AND_TOOL_CONTRACTS.md), [watchlist import](../design/WATCHLIST_SYNC.md) and [deployment profiles](../design/LAPTOP_OPERATIONS.md).

Build and exercise the system in integrated increments. These checks are not a separate market-validation study, narrow pilot or requirement to demonstrate profitable predictions before implementation. Acceptance concerns useful behavior and observable state, not an exact tool sequence or reproduction of an agent's private reasoning.

This document defines future checks. It does not claim that accounts were connected, authenticated calls were performed, money was spent or these scenarios already passed.

## Evidence and verification layers

Maintain an acceptance ledger with scenario ID, release/commit, environment, input versions, expected outcome, observed outcome, evidence links and status: `pass`, `fail`, `blocked` or `not_applicable`. Record why anything is blocked or inapplicable. Redact credentials, account information and private local paths. A screenshot alone cannot establish a durable state transition.

- **Offline fixtures:** Use synthetic or permitted sanitized documents, fixed clocks, injected failures and deterministic expected calculations. Exercise persistence, privacy, replay, concurrency and recovery without external accounts. Preserve relevant existing Stockwatch regressions.
- **Enabled-provider integration:** Under the configured access and budget, exercise the selected executor, public-source adapters and each enabled financial capability. Record actual authentication, schema, semantic and freshness evidence. An unconfigured optional provider is not a passed integration. Capability discovery alone is insufficient.
- **Real-use quality review:** During ordinary use, review a small weekly sample spanning useful briefs, missing/suppressed developments and incomplete cases. Assess relevance, supported interpretation, overlooked evidence and unnecessary work. Feed corrections into methods and the backlog. This continues after release; it is not a paper trial blocking the complete build.

## Product behavior

### A01 Complete research cycle and usable views

Exercise anticipation, monitoring, investigation, continuity, guided learning, decision review and execution visibility in one installation. Today, Upcoming, Companies & themes, Research, Journal and Status must expose the same underlying records. Reading and local notes remain usable during a network outage. Missing provider fields may limit analysis; no entire capability may be replaced by a placeholder.

**Evidence:** Linked scenario walkthrough, persisted records and rendered views.

### A02 Instrument import privacy and identity

Import an instrument-only manual snapshot from the existing Client Portal/Mobile list or a supported file, without a broker connection or TWS prerequisite. Keep `authority=external` and `external_list_id=null` unless an ID was actually obtained. Reject a position/account report without retaining its contents. Verify no account identifiers, quantities, balances, P&L or credentials enter research storage, model payloads, logs or exports. The selected file path may exist only in private application configuration; omit it from research/model payloads, ordinary logs and portable exports. Preserve string contract IDs, ambiguous symbols and distinct share classes; never infer holdings. A company theme must not activate every listing.

**Evidence:** Sanitized import records, model-input inspection and boundary assertions.

### A03 Partial snapshots and membership removal

Present partial, malformed, unexpectedly empty and large-removal manual/file snapshots. Only a complete accepted snapshot may change active source membership; partial input remains a candidate for completion. Duplicate observations are idempotent. An accepted removal affects only its source membership; other lists, local pins, adopted themes and dossiers survive. Repeated reads do not independently confirm a destructive diff. Changing manual/file/API transport does not transfer authority or invoke a provider write. A future native-list adoption remains a separate feature, not an automatic effect of import.

**Evidence:** Before/after memberships, snapshot states and preserved histories.

### A04 Future events and calendar revisions

Introduce a future tentative election, policy, macro or earnings event. Preparation appears without another user prompt. Revising its date updates the same event/case and cancels obsolete future reminders. Preserve tentative/date-only precision, timezone, calendar version and already missed obligations. Exercise a holiday/early close and an ambiguous or nonexistent local time.

**Evidence:** Event revisions, preparation brief and occurrence history.

### A05 Broad monitoring and honest quiet reports

Ingest an issuer development, unrelated policy/industry event, syndicated copies and an independent contradiction. Consolidate repeated origins without erasing disagreement. Record relevance reasons. Make one required source unavailable: the quiet report must distinguish checked sources from gaps. An important verified fact can reach the inbox while analysis is pending.

**Evidence:** Origin groups, source receipts, coverage interval and notices.

### A06 NVIDIA question with missing capabilities

Use a dated fixture for “NVIDIA has fallen; should I buy?” Verify the instrument, interval and price freshness. With pre-event Street consensus unavailable, provide useful supported guidance/prior-period analysis, name the missing comparison and create a deduplicated `CapabilityGap` with attempted alternatives and an implementable acceptance example. Do not substitute current estimates, agent-generated consensus or an unsupported intraday inference.

**Evidence:** Partial brief, receipts, gap and linked development proposal.

### A07 Financial and historical calculations

Compare actuals with expectations for matching periods, currency, units and accounting bases against independently derived expected values. Also exercise valid period-trend and peer comparisons with explicitly different periods/entities and appropriate normalization. Reject incompatible inputs; keep unknown distinct from zero and handle near-zero denominators. A historical comparison exports its declared cohort, unfavorable outcomes, missing observations and exclusions. Freeze definitions before later outcomes; state sample limitations and estimator assumptions rather than invent calibrated probabilities.

**Evidence:** Reproducible inputs, calculation artifacts and exclusion manifest.

### A08 Material claims and independent judgment

Supply a misleading headline, qualified primary passage and plausible alternative explanation. The brief must answer the question with a reasoned judgment, retain qualifications and distinguish fact from inference. Material claims must resolve to supporting passages. Reviewers assess whether support is adequate; schema validity or a second model's agreement cannot prove causal or financial correctness.

**Evidence:** Claim-to-passage review and documented corrections.

### A09 Continuity and consequential corrections

Import an earlier chat with distinct user and assistant statements. A fresh session retrieves relevant reasoning without promoting old assistant claims to facts. Add a transcript that contradicts a reviewed conclusion: append a revision, identify affected dependencies and notify the correction while preserving the original brief and its method version.

**Evidence:** Import attribution, retrieved context and revision/dependency history.

### A10 Proactive agenda and method learning

With an unresolved question, approaching event and stale dossier, generate a bounded ranked agenda without a new prompt. Each inquiry explains its relevance, method and next observation. One favorable analogy may create a hypothesis or method proposal; it cannot silently rewrite an adopted method, user preference or monitoring universe.

**Evidence:** Agenda reasons, follow-up jobs and versioned proposals.

### A11 Decision discipline and journal

Save the user's rationale and optional review condition. Surface that condition when relevant evidence arrives. Keep intentions, reported actions, agent suggestions and later assessment separate. Opening a brief does not imply agreement; neither an intention nor a price move establishes that a trade occurred. Preserve the original rationale after an override.

**Evidence:** Attributed journal and review history.

## Execution and operations

### A12 Expected work and actual check evidence

Save a report deadline and suppress dispatch. The expected run must still become visibly missed. Separately, submit a claim that required sources were checked without qualifying receipts: it cannot produce successful checked coverage. Valid unchanged results, failures and weak host-reported evidence remain distinguishable.

**Evidence:** Obligation ledger, coverage states and validation response.

### A13 Dynamic evidence and temporal boundaries

Acquire an eligible old filing after a run starts. It joins the frozen final read-set without invalidating that run's interpretation revision. A fixed-cutoff job excludes later-publication material. A live job can use a newly observed quote or release after job creation, preserving each timestamp and revisiting affected conclusions before final freeze; its pre-earnings expectation baseline stays immutable. A later-committed interpretation must be absent from earlier `system_state` replay even when its evidence was already received; label reconstruction separately.

**Evidence:** Manifests, commit boundaries and contrasting replay results.

### A14 Duplicate executions and stale interpretations

Retry a claim, race another claimant, expire/reassign a lease and submit an older result. An expired lease cannot renew; recovery requires a new claim. Only the current authorized generation may commit. Identical accepted resubmission returns the original result; changed payload conflicts. A competing interpretation causes revision conflict without losing a useful draft. Evidence acquisition alone causes no interpretation conflict.

**Evidence:** Concurrent outcomes, fencing records and exactly one accepted effect.

### A15 Research versus notification outcomes

For the local release, exercise a real adopted goal through discovery or preparation, research, relevance, an external notification and a retrievable follow-up. Close the browser before dispatch and verify the notice in the actual user-facing channel. Record the available delivery evidence and whatever remains unknown about human receipt. Exercise channel failure, retry and deduplication with the same frozen report.

Commit a brief, then fail the configured notification channel. The inbox and research remain complete; retry delivery without repeating research. Duplicate acknowledgments have one effect. Expired notices retain their history. Provider acceptance, confirmed delivery when observable, opening and explicit review remain distinct.

**Evidence:** Brief ID, separate outboxes and delivery attempts.

### A16 Trial interruption and continuous-server recovery

For `local_trial`, start in a foreground WSL session without a Windows companion, sleep/stop across a deadline, restart and test absence beyond source retention. Preserve every miss, group useful catch-up and never backdate checks. If optional Windows supervision is enabled, test it separately. For `server_single_node` commissioning, stop/crash the application and interrupt the host: verify supervisor recovery, an independent observer's outage evidence and the configured notification route. A local observer alone cannot prove detection of its own host's total outage.

**Evidence:** Availability episodes, recovery notices and receipt timestamps.

### A17 Enabled-provider and runtime integration

Exercise the selected authenticated executor and enabled provider operations. Check actual schemas, retained provenance, units, timing and entitlement. Verify the runtime's actual model/effort/billing mode is explicitly configured and recorded, not inherited from the development session. Inject quota expiry, authentication failure and malformed output. Preserve blocked/partial work and actionable errors; no silent paid fallback or unapproved tool installation. A successful transport response is not an accepted investigation.

**Evidence:** Redacted authenticated receipts and committed/blocked results.

### A18 Permission enforcement

Before live work in either profile, verify that the selected executor cannot read private SQL, source credentials or unrelated user files while authorized domain tools succeed. For a local CLI, include disallowed Windows-interoperability paths; for a managed custom-tool executor, verify its exposed tool boundaries. Development with sanitized fixtures may proceed before live permission setup, but is not a passed live-data check. Reject forged owner/lease inputs and hostile browser origins. A source containing instructions must not gain privileges or alter adopted preferences. Test actual permissions, not a promise in a prompt.

**Evidence:** Boundary results and unchanged protected state.

### A19 Backup restoration and server handover

Restore a consistent backup to an isolated location; verify SQL integrity, referenced blob hashes, cases, receipts and histories. Export no provider login secrets. Rehearse server handover with the old scheduler disabled before the new one starts. Preserve identifiers, misses and pending delivery without two active writers or duplicate dispatch. Rebind watchlist input to a server-side manual snapshot/upload or verified provider read route; no laptop-only path or daily-login session is assumed to become continuously available. Commissioning also verifies off-host backup restoration and reports watchlist freshness separately from server uptime.

**Evidence:** Restore manifest, reconciliation report and single-owner handover record.

## Release decision

Local-trial readiness requires the applicable local scenarios and all seven capabilities connected; one verified external delivery route is required. Windows autostart remains optional. Planned server software/configuration can be delivered before a host is chosen, but claiming 24/7 commissioning requires the server portions of A16/A18/A19 and configured health/notification/backup evidence. Optional financial providers may remain disabled with explicit gaps. Unresolved integrity, privacy, authorization or false-completion defects block live release; limited data depth does not if useful supported behavior and its limitations are demonstrated. Do not equate acceptance with proven investment returns.
