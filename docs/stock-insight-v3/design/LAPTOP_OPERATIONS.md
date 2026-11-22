# Deployment profiles for local trial and continuous server operation

Status: V3.1 implementation specification. Application commands, services, interfaces and paths below are **targets to build**, not existing Stockwatch features. This document does not deploy a server, change laptop settings, create schedules or connect accounts.

## 1 Two profiles for the same product

Develop, test and begin using the complete research system on the laptop. Deploy the same application on one Linux server for normal 24/7 operation. The server profile is a planned delivery stage, not a speculative expansion dependent on proving a trading strategy.

Both profiles support the same research capabilities and preserve the same SQL records, evidence, methods, expected runs and result contracts. Local trial describes the operating environment; it does not reduce the product to one event type or create a separate validation prerequisite.

| Concern | `local_trial` | `server_single_node` |
|---|---|---|
| Purpose | Development, testing and initial personal use | Planned continuous personal operation |
| Launch | Foreground application and worker in WSL2 | Linux service supervisor with automatic startup/restart |
| Availability | While processes, laptop, network and authentication are available | Always-on host with observed failures and recovery; no claim of perfect availability |
| Storage | User-writable Linux data directory | Persistent local server volume |
| Reading/delivery | Private loopback UI, durable inbox and verified external delivery | Same UI/inbox plus a configured notification route |
| Health | Status view, foreground logs and recovery on restart | Independent external health observation and outage notification |
| Backups | Consistent local snapshots; configurable off-device copies | Scheduled verified snapshots and confirmed off-host copies |

Use one Python application, one controlled SQLite writer, immutable document files and one selected reasoning executor. Docker, Redis, a distributed queue and a database migration are unnecessary for either initial profile.

## 2 Local trial startup

Reuse a compatible existing Windows/WSL2 environment. Inspect actual distro, Python, SQLite, Codex and networking before changing anything. Do not require a new distro, Linux system services, administrative data directories or Windows application packaging before useful local work.

Provide a foreground target such as `stockinsight run --profile local_trial`, or documented `serve` and `worker` commands in separate terminals. Keep the foreground WSL session open while running. Microsoft documents that systemd services alone do not keep WSL alive; a custom keep-alive companion is unnecessary for this foreground profile. [1]

Use a configurable user-writable data directory, for example an expanded `~/.local/share/stock-insight`, outside Git. Acquire the single-instance/scheduler lock. The domain service uses one Uvicorn worker; development reload must not accidentally create a second scheduler.

Bind the UI/API to configurable loopback, initially `http://127.0.0.1:8765`, with MCP at `/mcp`. Windows browsers can reach WSL web applications through localhost under supported configurations. Verify the actual route; do not silently bind all interfaces to solve a failure. Mirrored networking and a public tunnel are not prerequisites. [2]

The durable inbox retains reports. The local release also requires a working external notification route, verified while the browser is closed. Windows native delivery is an acceptable first route. Autostart and a companion watchdog remain optional. Leave sleep, lid, wake-timer and battery policies unchanged. Closing the application or sleeping the laptop pauses local work; recovery must make that absence visible.

## 3 Planned server operation

Deploy the same release to one Linux host with a persistent local volume. Run the domain service and selected worker under a supervisor such as systemd, with automatic startup, bounded restart and a single scheduler owner. Use separate restricted runtime identities where required by the chosen executor. No Windows companion is involved.

A starting restart policy allows three retries in ten minutes, then exposes the failure rather than cycling indefinitely. Health includes scheduler progress, oldest eligible job, source freshness and delivery backlog, not merely HTTP responsiveness.

Before declaring the server commissioned, require an independent external heartbeat/dead-man monitor, a configured outage-notification destination and verified off-host backup. An outbound heartbeat every two minutes with notification after three consecutive misses is an initial configurable policy. Keep health payloads minimal. An observer inside the failed server cannot report its total outage.

Keep the application bound to loopback. Private reading can initially use authenticated SSH forwarding. Add an authenticated HTTPS reverse proxy when direct remote browser access is selected. Source access, model APIs and managed custom-tool bridges can remain outbound; remote MCP exposure is not necessary merely to run continuously.

Configure a notification channel that reaches the user independently of the reading session. Keep research completion, channel acceptance, confirmed delivery where observable and user review separate. The durable inbox remains canonical. Host, destination, credentials and spending are commissioning choices; none are activated by this specification.

## 4 Clocks and interruption recovery

Default reporting timezone is **America/Toronto**; U.S. market-session timezone is **America/New_York**. Both are configurable and stored explicitly. Do not substitute WSL's timezone for the user's preference or silently change goals when the laptop travels. Store UTC timestamps and source precision; use versioned exchange calendars for holidays and early closes.

Distinguish “report at six” from “start at six.” Give report deadlines preparation lead time. A schedule change creates a version. For repeated local times, default to the earlier occurrence; for nonexistent times, the next valid instant. Display the resolved schedule.

Materialize fourteen days of expected runs using unique `(goal_id, schedule_version, scheduled_at_utc)` keys. Persist the expansion cursor and reconstruct missed occurrences after longer absences. The application is the sole research scheduler; OS supervision starts processes, not duplicate research jobs.

On startup or a substantial observed availability gap:

1. Acquire ownership and identify the new application instance.
2. Record the observed gap and materialize missing obligations.
3. Fence expired leases and reconcile uncertain attempts and committed results.
4. Recover dispatch and notification outboxes independently.
5. Refresh sources and backfill only supported historical intervals.
6. Group obsolete work by goal and overlapping coverage into bounded useful catch-up, retaining links to every affected obligation.
7. Resume ordinary dispatch and present one recovery update instead of stale-summary bursts.

An expired lease cannot renew; recovery requires a new claim/generation. A late result cannot overwrite a newer interpretation. Record an interruption's cause as unknown unless observations establish it.

Keep timing, research and delivery outcomes separate. Catch-up does not erase the original miss. Acquisition time is when a document was actually obtained. Backfill cannot recreate absent live coverage, expired rolling-feed items or notifications never delivered. Historical reconstruction remains distinct from actual system-state replay. These rules apply equally to laptop sleep and server outages.

## 5 Executor, transport and permission boundaries

Default to one `CodexCliExecutor` after checking installed capabilities, account authentication, available model/tools and accepted-result round trip. Current documentation supports noninteractive execution, JSONL events and schema-constrained output; CLI exit is not research acceptance. A supported outbound managed API executor is the alternative when its permissions and configured economics fit. [3]

Use a dedicated configuration and per-run scratch, required domain tools, bounded execution and verified tool restrictions. Disable model shell execution and unrelated personal tools for ordinary research. Deterministic calculations run through domain tools. Cached web search does not establish a fresh check; use live acquisition where required and retain its actual provenance. [4]

Local trial still excludes holdings/account data, credential exposure, arbitrary SQL/HTTP proxy access, runtime installation and code modification. Confirm effective live permissions before enabling a research worker with real credentials. If the runtime cannot meet them, continue fixtures and independent development or select a supported API tool executor. “Trial” is not permission to waive these boundaries.

Do not require a Windows companion or elaborate OS setup when a supported restricted runtime meets the boundary. Conversely, a separate process, read-only CLI label or prompt is not proof of filesystem isolation. Production commissioning must verify the worker cannot directly access canonical SQL, service secrets or unrelated user files. Linux identities, filesystem namespaces and privilege controls can enforce this; test their actual effect. WSL's Windows mounts and interoperability need particular care. [5]

Use supported credential storage; headless environments may need protected files when keyrings are unavailable. Exclude authentication stores from Git, exports and ordinary logs. ChatGPT sign-in and API-key billing are distinct. Login or quota failure produces a visible blocked state, never a silent paid fallback. [6]

Authenticate MCP/browser operations, validate Host/Origin and protect browser writes against CSRF. Use execution-scoped capabilities tied to owner, assignment and fencing generation. Keep permanent secrets out of URLs and frontend bundles. [7]

Ordinary ChatGPT web does not inherit local Codex configuration. Managed APIs can use application-run function/custom tools; OpenAI also documents an outbound WebSocket executor. Such a bridge needs its local or server application available. Vendor-hosted financial MCP is a separate outbound connection. No adapter should assume a cloud process can directly reach the laptop's localhost. [8]

## 6 Watchlist commissioning on the server

The external provider initially owns its selected list membership; Stock Insight consumes one-way snapshots and owns research, themes and independent local pins. Implement the chosen route, not adapters for every platform or bidirectional synchronization. Future Stock Insight ownership is a separate explicit change.

A server must not depend on a laptop-only file path or an always-on laptop gateway. A manually produced instrument snapshot can be uploaded through the authenticated private server UI and validated/projected before persistence. Alternatively, activate the chosen supported read API after its access conditions are met. Preserve external identity/provenance where available.

The server may research the last good accepted membership continuously while showing its last-observed time and stale/unavailable source state. Continuous research availability does not establish automatic watchlist freshness. IBKR session expiry, competing sessions and any route-specific daily/manual reauthentication remain real even on an always-on host. Preserve the last good list when refresh is unavailable; do not take over sessions automatically. [9]

## 7 Storage, backup and handover

Keep active SQLite/files on the Linux filesystem, not a synchronized Windows folder or network filesystem. Local trial uses user-writable paths; server defaults can use `/etc/stock-insight` and `/var/lib/stock-insight`. Usernames and paths remain configuration, never exported domain identity. [10]

Use short transactions, foreign keys and one write/checkpoint owner. Enable WAL only with a linked SQLite containing its documented WAL-reset fix—3.51.3+ or a verified backport. Rollback journal is an acceptable initial fallback. Write blobs atomically before committing references. [11]

Back up through SQLite's online backup API, including every referenced permitted blob and a hash manifest. Protect retained backup blobs from garbage collection. Back up before migrations and perform one overdue backup after recovery. A same-disk archive is labeled `local only`; the server's off-host protection needs a confirmed copy and restore check. [12]

For handover, pause laptop dispatch, reconcile attempts and fence outstanding leases. Restore a verified final application backup on the server, validate SQL and hashes, reconfigure credentials and rebind the watchlist input. Enable server dispatch only after disabling the old scheduler. Preserve identifiers, misses, pending delivery and research history. Keep the old copy read-only; never dispatch from divergent active copies.

Build targets include `doctor`, `run`, `serve`, `worker`, `status`, `open`, `backup` and `restore`. Verify shared contracts locally; additionally verify supervision, isolation, independent health, notifications and off-host restoration before commissioning the continuous server profile. No actual deployment is performed by this handoff.

## Official references

1. https://learn.microsoft.com/en-us/windows/wsl/systemd/
2. https://learn.microsoft.com/en-us/windows/wsl/networking
3. https://learn.chatgpt.com/docs/non-interactive-mode
4. https://learn.chatgpt.com/docs/config-file/config-basic
5. https://www.freedesktop.org/software/systemd/man/latest/systemd.exec ; https://ubuntu.com/wsl/docs/latest/explanation/security-overview/
6. https://learn.chatgpt.com/docs/auth
7. https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/docs/specification/2026-07-28/basic/transports/streamable-http.mdx
8. https://learn.chatgpt.com/docs/extend/mcp?surface=cli ; https://developers.openai.com/api/docs/guides/agents-api/tools/functions ; https://developers.openai.com/api/docs/guides/agents-api/environments/self-hosted ; https://platform.claude.com/docs/en/managed-agents/tools
9. https://www.interactivebrokers.com/docs/web-api/authentication/trading ; https://www.interactivebrokers.com/docs/web-api/authentication/multiple-sessions
10. https://learn.microsoft.com/en-us/windows/wsl/setup/environment
11. https://sqlite.org/wal.html
12. https://docs.python.org/3.12/library/sqlite3.html
