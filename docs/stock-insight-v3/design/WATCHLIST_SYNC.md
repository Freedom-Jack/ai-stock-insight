# Watchlist synchronization design

**Status:** Version 3.1 implementation specification. Initial authority: the user's selected external IBKR list in Client Portal/Mobile. Initial transport: manual instrument snapshot, with instrument-only file input supported. Automatic inbound broker API retrieval: conditional, disabled until verified.

## 1. Decision and scope

IBKR remains the source of truth for membership in each selected broker watchlist. Stock Insight maintains a local mirror of the latest accepted snapshot. Stock Insight owns research themes, company relationships, dossiers, methods, and local monitoring proposals. Authority is assigned per list; Stock Insight's canonical research database is not authority to edit an imported list's membership.

The user's actual list is maintained in **IBKR Client Portal and Mobile**. The initial trial offers **Paste a watchlist snapshot**: the user supplies only instrument symbols/identifiers from that selected external list, or a user-prepared instrument-only CSV. This is our input workflow, not a claimed native Portal/Mobile export or clipboard feature. Do not require installing TWS. Its documented financial-instruments export remains an optional convenience for existing TWS users.

The default has no IBKR credential, broker session, holdings import or account/portfolio connection. Manual/file refresh updates the mirror without changing authority. A file watcher can import replacements but cannot refresh the upstream list. Once a supported API path is verified, it can replace the transport while preserving the external authority and local research links. The supported direction is **external source → Stock Insight**, with no writeback.

The evidence, documented file formats, API constraints, and unresolved enumeration-endpoint mismatch are in [IBKR research findings](../research/IBKR_FINDINGS.md). Those findings explain why automatic brokerage access is a separate, conditional capability.

## 2. Ownership and research themes

| Information | Authority | Local behavior |
|---|---|---|
| Selected broker list membership | IBKR | Mirror accepted snapshots; edit membership in IBKR. |
| Local file source name | User configuration | Use a local alias; never invent a broker list ID. |
| Provider list name in API mode | IBKR | Follow its stable ID across renames. |
| Themes such as semiconductors | Stock Insight | Associate companies with several themes independently of broker membership. |
| Supplier/customer, policy, and earnings relationships | Stock Insight | Store evidence and uncertainty; never interpret a relationship as an investment position. |
| Agent-proposed monitoring additions | Stock Insight | Keep proposals distinguishable from accepted local monitoring and broker membership. |
| Dossiers and decision history | Stock Insight | Preserve when a source membership ends. |

Use one provider-neutral read contract, `read_snapshot(source, cursor)`, returning membership, identity metadata, completeness, observed time, optional provider version/cursor and typed errors. Implement only the selected routes now. It exposes no create/update/delete operation against an external provider. Client Portal and Mobile are two interfaces to IBKR's list library, not separate Stock Insight synchronization targets.

An agent may propose adding a company to semiconductor research without changing the IBKR watchlist. Adopting that proposal creates a local research relationship or monitoring choice. Broker writes remain outside this adapter.

## 3. Core records

All IDs are **strings**, including source IDs, provider list IDs, and normalized IBKR contract IDs. Preserve provider identifiers as opaque values. Times use UTC with explicit offsets.

| Record | Required contract |
|---|---|
| `WatchlistSource` | `id`, `alias`, `authority` (initially `external`), `mode` (`manual_snapshot`, `file`, or conditional `ibkr_web_api`), `provider`, optional `external_list_id`, private `file_path` only for file mode, `active_snapshot_id`, `last_success_at`, `status`. |
| `Instrument` | Immutable `id`; optional resolved `company_id`, `provider_namespace` and `conid`; `raw_label`; optional verified `ticker`, `security_type`, `listing_exchange`, `currency`; `aliases`; `resolution_status`. |
| `SourceMembership` | `source_id`, `instrument_id`, `first_seen_at`, `last_seen_at`, `snapshot_id`, optional `display_order`, `status` (`active` or `removed`). Unique active pair: source and instrument. |
| `ThemeMembership` | `theme_id`, `subject_type` (`company` or `instrument`), exactly one of `company_id` or `instrument_id`, `relation`, `reason`, `evidence_refs`, `author`, `status` (`proposed` or `accepted`). No implied broker membership. |
| `WatchlistSnapshot` | `id`, `source_id`, `observed_at`, `source_updated_at` when verified, `content_hash`, optional opaque `provider_version`, sanitized entries, `membership_complete`, `state` (`candidate`, `complete`, or `rejected`), validation outcomes and rejection/review reason. |

`WatchlistSource.status` can be `ready`, `stale`, `needs_review`, `unavailable`, or, for API mode, `reauth_required`. Staleness belongs to the source observation; it does not remove memberships.

Example provenance for the current user's manual snapshot:

```json
{
  "id": "watchlist_source_personal",
  "alias": "My IBKR Client Portal/Mobile watchlist",
  "authority": "external",
  "mode": "manual_snapshot",
  "provider": "ibkr",
  "external_list_id": null,
  "active_snapshot_id": null,
  "last_success_at": null,
  "status": "unavailable"
}
```

This alias records the user's description, not an independently verified broker list identity. An unknown `external_list_id` remains null; never infer it from the alias. A file-mode location belongs in private configuration and is omitted from model payloads and portable research exports. The prototype field name `broker_list_id` from V3 is replaced by `external_list_id` in this proposed schema; no implemented data migration is implied.

### Instrument identity

Prefer `(provider_namespace="ibkr", conid)` when available. Do not merge by ticker alone. Preserve ADRs, local shares, share classes, and derivatives as different contracts. A routing value such as `SMART` is not a verified primary listing.

Symbol-only rows remain provisional until resolution is unambiguous. Missing metadata must not erase a recognized contract ID. An unsupported or unclassified asset remains visible as unresolved/excluded from stock research until classified; never silently discard it and interpret its absence as a deletion. Identity enrichment must not request account data. Company-level theme membership enables company research without selecting every tradable listing; price work must identify an explicit instrument.

## 4. Import and snapshot lifecycle

1. **Acquire:** accept instrument-only text through the private UI, or read only the selected file after it stabilizes. Apply byte/row limits. Do not ask for an entire screen/table copy containing configured position or P&L columns. Do not scan brokerage settings, browser profiles, or unrelated folders.
2. **Validate:** recognize a supported instrument-only schema. Parse as data, with no formulas, executable content, or LLM-based interpretation of arbitrary rows. Reject account/position reports and unsupported schemas without persisting their contents.
3. **Normalize:** project allowed identifier fields, preserve unresolved entries, deduplicate exact identities, and compute a canonical content hash. Store only sanitized entries and safe diagnostics.
4. **Create candidate:** every new observation starts as a `candidate` `WatchlistSnapshot`. Valid bytes alone do not prove that the complete intended list was supplied. The user identifies a replacement as a full-list snapshot. An explicitly partial input remains a candidate for completion; it cannot replace active membership. Incremental add/remove commands against an external mirror are not part of this initial snapshot interface.
5. **Assess:** validate completeness and compare with the active snapshot. Unexpected empty lists or configured large-removal diffs remain candidates with a readable preview and reason. Ordinary changes can proceed automatically.
6. **Commit:** atomically mark the accepted snapshot `complete`, reconcile memberships, and update `active_snapshot_id` and successful-observation time. A malformed or disallowed observation becomes `rejected`, recording safe diagnostics only.

Only a `complete` snapshot can become active. Metadata completeness is separate from membership completeness: known contract IDs can be retained while ticker enrichment remains pending. Unsupported schemas, truncation, authentication failures, or partial responses cannot replace the active set.

An unexpected destructive diff requires explicit acceptance of that candidate or a separately validated complete source observation. Repeated reads of the same file are not independent confirmation. Rejected observations never clear existing membership. Duplicate snapshots are idempotent and do not generate repeated alerts.

## 5. Reconciliation and user experience

- Additions activate source membership. Removals deactivate only that source's membership; other sources, local monitoring, themes, and dossiers remain intact.
- A provider list rename preserves identity. A missing/deleted list becomes unavailable. A new list with the same name must not inherit the old source identity automatically.
- Manual/file sources retain their explicit local alias. Changing paths or submitting another snapshot is a transport update, not proof of a broker rename or a transfer of authority.
- There is no bidirectional conflict resolution: source membership is inbound; local research edits operate on separate records. Show why each instrument is monitored.
- Display the last accepted observation time and pending diff/error. A file's modification time is not proof of the broker list's last change time.
- Laptop sleep, offline periods, invalid files, and service restarts preserve the last good snapshot. On resume, read the latest source once and reconcile; do not replay every filesystem event as a new change.

On the planned server, accept a manual snapshot through the authenticated private UI or configure a supported read adapter. Do not assume the server can read a laptop-only path or reuse its brokerage session. Research can operate continuously on the last accepted membership while showing the source's last observation and stale state; server uptime does not establish watchlist freshness.

### Future Stock Insight authority

A later user may choose Stock Insight as the home of a list. Make that an explicit adoption/copy: create a native list from an accepted snapshot, retain lineage and instrument/research IDs, and decide whether to stop using the old external mirror. Do not silently change an external list's authority or reinterpret earlier membership history. Native list editing, outbound provider synchronization and conflict resolution are separate future features; none is required now. Local pins and themes already let research grow without changing external membership.

## 6. Conditional Web API adapter

This capability remains disabled until the following integration questions are resolved: the enumeration endpoint/parameter mismatch; exact account eligibility and granted permission; a supported initialization path consistent with the no-account-data contract; and competing-session behavior. These conditions do not delay the rest of Stock Insight.

Maintain four separately documented boundaries: **provider authorization**, **adapter request allowlist**, **payload projection**, and **local/model data visibility**. A locally restricted client must never be described as having a broker-enforced watchlist-only grant without evidence of that grant. If the provider credential has broader authority, activation requires the user to understand and choose that trust expansion.

Use a deterministic local bridge with exact allowed methods, paths, selected list IDs, and parameters. Initial list selection may enumerate lists; ordinary refreshes fetch the chosen list. Vetted authentication/status/heartbeat operations have their own explicit allowlist. No arbitrary URL, generalized HTTP proxy, portfolio/account lookup, order operation, or watchlist mutation is exposed to the agent.

Do not copy SDK startup helpers that fetch accounts or auto-load portfolio state. Do not automatically take over competing sessions, enter credentials, or automate 2FA. Expiry or conflict pauses refresh and retains the last good snapshot, with manual reconnect or file-import fallback.

Keep credentials and session payloads outside agent-visible files, logs, backups, and exports. Enforce isolation through OS/process permissions and narrow local interfaces; a separate process alone is not a security boundary. Sanitize responses before they cross into research storage. Quote-data acquisition remains a separate integration.

## 7. Acceptance criteria

The default is ready for normal use when:

- An instrument-only manual snapshot or supported file imports without any broker connection, credentials, account IDs, quantities, balances, or P&L entering application storage or model context; Client Portal/Mobile use does not require TWS.
- Snapshot provenance keeps external authority, a local alias and nullable external list ID; IDs survive normalization as strings.
- State-transition tests prove candidate/rejected snapshots cannot change active membership; valid commits are atomic and duplicate observations are idempotent.
- Truncated files, unexpected emptiness, unsupported rows, and large-removal candidates preserve the last good set.
- Symbol collisions, aliases, missing metadata, renames, and multiple-source membership preserve identity and history.
- Source removal does not delete dossiers or accepted theme memberships; local proposals never mutate the broker source.
- Changing manual/file/API transport does not transfer authority, trigger provider writeback or require separate Client Portal and Mobile adapters.
- Restart/sleep/offline recovery preserves timestamps and displays stale status accurately.

Before optional API activation, also require a request trace proving the exact allowlist, resolution of the documented endpoint mismatch, verified startup without prohibited data acquisition, no account/session payload leakage, enforced agent isolation, and expiry/competition tests demonstrating no automatic session takeover.
