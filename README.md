# Stock Insight and Stockwatch

## Start the Windows personal trial

Double-click **Start-StockInsight.cmd** or run the following from this checkout.

```powershell
.\Start-StockInsight.cmd
```

Open **http://127.0.0.1:8765/today**. Sign in as `research` with the password printed in the terminal. The launcher opens your personal workspace at `%LOCALAPPDATA%\StockInsight\personal`. Enter your instrument list under **Companies & themes**, then adopt a standing objective under **Goals**. Leave the launcher running. The desk checks eligible public sources, investigates relevant events and shows native Windows notifications even after you close the browser. Reopen the desk for reports, questions, journal notes or status.

Use **Ctrl+C** in the terminal or **Status → Stop this desk** to stop. The same command reopens your saved research and schedules. For the isolated synthetic demo run `.\Start-StockInsight.cmd --demo` (port 8766). [First use, access, updates, backup and restore](docs/windows-trial.md)

## Open the historical company investigation

This checkout contains a saved, isolated NVIDIA replay with its initial report and a later question about supply commitments. From the project directory, run

```powershell
.\.venv\Scripts\python.exe -m stockinsight --fixture --data-dir .stockinsight\tmp\next-stage-company serve --port 8766
```

Sign in as `research` with the password printed by the process. The case shows the two reported revenue cells, the comparison, the subsequent filing and the remaining gaps. The saved workspace lives on the handoff computer. A new checkout can reproduce the exercise with the replay commands below. [Open the saved case on this computer](http://127.0.0.1:8766/goals/reports/dispatch_e1663e76f83c2662daa04f22)

Run any one line to advance the corresponding replay by one step. Run it again after the pending assistant job is accepted. Each scenario creates its own workspace under `.stockinsight/replays`. The live check requires a fresh directory and access to the public Federal Reserve calendar.

```powershell
.\.venv\Scripts\python.exe -m stockinsight.replay policy
.\.venv\Scripts\python.exe -m stockinsight.replay company
.\.venv\Scripts\python.exe -m stockinsight.replay noise
.\.venv\Scripts\python.exe -m stockinsight.replay live
```

The private assistant connector uses an outbound Secure MCP Tunnel. This workstation has completed supervised desktop research and native Windows delivery. Work Cloud/dot subscription and visible delivery await private account authorization. The implementation record includes the verified receipts, connection procedure and billing limits. [Replay and assistant handoff](docs/implementation-status.md#historical-replay-and-private-assistant-handoff)

## Run the standalone fixture exercise

From this checkout, install the locked dependencies and run the offline investigation. These commands use the Python 3.14 runtime tested on Windows.

```powershell
uv sync --locked --python 3.14
uv run --locked -m stockinsight demo
uv run --locked -m stockinsight --fixture serve
```

Open **http://127.0.0.1:8765** and use the browser’s sign-in dialog. Enter username `research` and the password printed by the foreground process. Open the NVIDIA case under **Research**. Expand a citation to read the saved passage and source hash, then inspect the calculation, gaps and receipts. **Mark this revision reviewed** records an explicit review. To try another investigation, select the resolved NVDA listing and ask “Did the reported revenue growth establish stronger full-year demand?” The offline driver covers this dated example. **Ctrl+C** stops the desk. Running `demo` again reopens the same result. With the environment already installed, Windows can run `.\.venv\Scripts\python.exe -m stockinsight` in place of `uv run --locked -m stockinsight`.

### Reproduce the public-data check

Run these commands in a second terminal. They use the ordinary local workspace. The CSV is a sample instrument list. NVIDIA’s public issuer route needs internet access. Each successful check is cached for one hour.

```powershell
uv run --locked -m stockinsight --data-dir .stockinsight/public-example import-list examples/stockinsight/watchlist.csv --source example --complete
uv run --locked -m stockinsight --data-dir .stockinsight/public-example capture NVDA --provider issuer
uv run --locked -m stockinsight --data-dir .stockinsight/public-example compare NVDA "Q2 FY25" "Q1 FY25"
uv run --locked -m stockinsight --data-dir .stockinsight/public-example passages NVDA
uv run --locked -m stockinsight --data-dir .stockinsight/public-example serve --port 8766
```

Open **http://127.0.0.1:8766** with username `research` and the password from that terminal. Choose **Companies & themes → NVDA** for the two retained GAAP revenue cells. The source is NVIDIA’s August 2024 release. The CLI comparison gives **30,040 versus 26,044 USD million (+15.3433%)**. The separate synthetic fixture gives **120 versus 100 (+20%)**. Neither route provides a current price or historical Street consensus. [Issuer release](https://nvidianews.nvidia.com/news/nvidia-announces-financial-results-for-second-quarter-fiscal-2025)

### Browser authentication

Each foreground process generates a new password and binds to IPv4 loopback. HTTP authentication uses the origin (scheme, host and port) and realm to define its protection space. The desk issues no session cookies. Enter the password in the browser dialog at the printed address. Keep it out of URLs. Stopping the desk retires its password. POSTs also require the exact browser Origin and a CSRF token. This boundary assumes a trusted local operating system and browser. [HTTP protection spaces](https://www.rfc-editor.org/rfc/rfc9110#section-11.5)

### Use a private list

Start `uv run --locked -m stockinsight serve`. Under **Companies & themes**, paste one ticker per line or the instrument-only CSV form shown there. Check the full-list box only for a complete replacement. Symbol-only entries stay provisional. The application also accepts a selected file with `import-list PATH --complete`. Source membership stays external. Inspect destructive replacement candidates before accepting them. Keep the private workspace on a user-owned local disk. Use the global `--data-dir DIRECTORY` option before a command to change its location.

`doctor` reports runtime configuration and source access. The Windows trial uses local inference and public-source tools. An ordinary workspace saves the question and execution details even when evidence or model access is unavailable. The separate hosted Responses adapter requires explicit CLI selection and its own billing authorization. [Implementation record](docs/implementation-status.md)

To verify this checkout, run `uv run --locked -m unittest discover -s tests -v`. For the optional Fiscal SDK contract test, use `uv run --locked --extra fiscal -m unittest discover -s tests -v`. To include the browser isolation regression on Windows, run `uv run --locked --extra fiscal --group browser-test -m unittest discover -s tests -v` with Edge installed. On Linux, install a Playwright-compatible Chromium before running that group. The tests use fixtures for external accounts. Update the worktree through your usual Git workflow, stop the foreground desk first, then run `uv sync --locked` before restarting. Before updating a private workspace, stop its writers and copy the entire data directory, including retained source files.

## Stockwatch

Stockwatch is a local earthquake and issuer-disclosure monitor for companies with a documented TSMC exposure. It opens a watch when USGS reports a qualifying earthquake, then checks Taiwan Stock Exchange disclosures for TSMC statements about the event. The included watchlist covers AMD and NVIDIA.

## Project research and chats

Start with the [decision memo](decision-memo.md) for the proposed product direction. The three project chats and their deliverables are archived below. Chat transcripts contain the user messages and assistant replies from the completed project work. References to local files point to their repository equivalents.

| Chat | Research and deliverables |
|---|---|
| [Research monitoring system design](docs/chats/research-monitoring-system-design.md) | [Monitoring research, worked examples and evaluation plan](monitoring-research.md) · [Original design](design.md) |
| [Build the monitoring MVP](docs/chats/build-the-monitoring-mvp.md) | [Usage and offline replay](#verify-v1-offline) · [Implementation](stockwatch/) · [Evidence fixtures](examples/) · [Tests](tests/) |
| [Design Stock Insight’s future](docs/chats/design-stock-insights-future.md) | [Decision memo](decision-memo.md) · [Personal research desk design](research-desk-design.md) |

## Start the local monitor

From the project root, run this with Python 3.11 or later. The sample watchlist and hypothetical $100,000 portfolio work on first launch.

```sh
python -m stockwatch start --open
```

On this workstation the verified equivalent uses the installed uv-managed interpreter:

```powershell
uv run --offline --no-cache --python 3.14 -m stockwatch start --open
```

Here `--offline` applies to uv’s runtime resolution. Stockwatch uses the network to read the two public feeds.

Keep the foreground process running. New alerts appear in the terminal with sources, uncertainty, the next check and portfolio relevance. `--open` also opens a public, auto-refreshing HTML inbox on disk. The browser view contains public evidence only. A second terminal can run `python -m stockwatch status` or `python -m stockwatch inbox --history`. **Ctrl+C stops collection.**

### Configure the watchlist

```sh
python -m stockwatch configure
python -m stockwatch configure --tickers NVDA --min-magnitude 6 --radius-km 200
python -m stockwatch start --open
```

The first command displays the effective settings. The second saves a change under `.stockwatch/config.json`. Later edits preserve unspecified options. Restart the monitor to apply edits. Use `configure --all-tickers` to select all documented names again. To add a company, supply a dated TSMC relationship, facility, limitations and primary sources in the [watchlist format](examples/watchlist.json), then run `configure --watchlist <file> --tickers <symbols>`. An unsupported symbol produces an error.

The default [sample allocation](examples/sample-allocation.json) fixes $10,000 in NVDA, $5,000 in AMD, $25,000 in MSFT and $60,000 in cash. A two-name watch flags 15% of this illustrative account for review. You can select a private dated file with `configure --portfolio <file>`, omit amounts with `configure --watchlist-only`, or restore the default with `configure --sample-portfolio`. The live sample is a scenario and makes no claim about current market valuations.

### Verify v1 offline

```sh
python -m stockwatch demo --monitor
python -m stockwatch demo --monitor
python -m unittest discover -s tests -v
```

With the default watchlist, the first run produces one geographic watch, a visible simulated TWSE outage, a recovery message and one automatically matched TSMC follow-up. The second run adds zero issuer documents or alerts. Both use the live parsing, correlation, storage and terminal delivery functions. The SQLite and HTML outputs are isolated from live data. To read the watch before the filing, run `python -m stockwatch inbox --db .stockwatch/monitor-demo.sqlite3 --as-of 2024-04-03T12:00:00Z`.

The issuer fixture reconstructs a daily exchange row from TSMC’s April 5, 2024 statement. Its publication time was 21:23:03 in Taipei. The April 6 edition label, collector receipt, source failure and later quiet USGS response are simulated. The filing’s original-language excerpt and source remain inspectable. [Official April 5 statement](https://mopsov.twse.com.tw/mops/web/ajax_t05st01?firstin=true&step=2&TYPEK=sii&co_id=2330&spoke_date=20240405&spoke_time=212303&seq_no=1)

## Replay the reviewed operational history

Run these commands from the project root with Python 3.11 or later.

```sh
python -m stockwatch demo
python -m stockwatch inbox --db .stockwatch/demo.sqlite3 --as-of 2024-04-03T12:00:00Z --portfolio examples/portfolio.json
python -m unittest discover -s tests -v
```

With an existing uv-managed Python installation, the equivalent first command is `uv run --offline --no-cache --python 3.14 -m stockwatch demo`. The demo and tests run offline.

**Expected result.** A new demo ledger contains four source observations and four revisions of **one** watch. A second run adds zero. The April 3 view shows a magnitude 7.4 earthquake about 125 km from the Hsinchu screening point. The event title names neither chipmaker. Pre-event filings connect both to TSMC, while the share of their production at Fab 12A remains unknown. The sample account has $10,000 in NVDA and $5,000 in AMD. That puts 15% of its $100,000 total on the reading list.

| Replay cutoff (UTC) | What the inbox can show |
|---|---|
| April 3, 00:14:59 | Empty. The selected USGS version has yet to reach the simulated collector. |
| April 3, 00:15 | A conditional watch. Check for fab disruption or recovery. |
| April 4, 04:05 | TSMC reports partial tool damage and over 70% tool recovery within ten hours. |
| April 5, 13:14:11 | The watch narrows. Some lines are still affected and TSMC maintains guidance. |
| April 18, 11:31:54 | The operational watch closes when TSMC reports recovery. Scrapped wafers and a supplier margin impact remain part of the record. |

Use `demo --watchlist-only` for the public view, `demo --as-of <timestamp>` to replay through a cutoff, or `inbox --history --audit --db .stockwatch/demo.sqlite3` to inspect the trail. Historical receipt times are simulated. For the first operator statement the fixture uses a conservative end-of-filing-day bound. Later filings use SEC acceptance times. The sample includes selected disclosures. It illustrates the review process and provides no measurement of live lead or forecasting accuracy. [Dated USGS origin](https://earthquake.usgs.gov/product/origin/us7000m9g4/us/1712103250040/quakeml.xml) · [April 3 statement](https://www.sec.gov/Archives/edgar/data/1046179/000104617924000034/a20240403.htm) · [April 5 update](https://www.sec.gov/Archives/edgar/data/1046179/000104617924000038/a20240405.htm) · [April 18 assessment](https://www.sec.gov/Archives/edgar/data/1046179/000104617924000050/a20240418.htm)

## Collection and failure handling

```sh
python -m stockwatch start --once
python -m stockwatch status
python -m stockwatch inbox --audit
```

`start` checks the free USGS M4.5+ rolling day feed every five minutes and the TWSE daily material-announcement file hourly. The intervals can be changed with `--interval` and `--issuer-interval` in seconds. `--once` checks both sources and exits with a nonzero status for degraded coverage. `poll` remains available for a single USGS check. The adapters bound response size and timeout and verify HTTPS. On systems where Python rejects TWSE's legacy intermediate certificate, the adapter can use a certificate-verifying system curl. [USGS feed specification](https://earthquake.usgs.gov/earthquakes/feed/v1.0/geojson.php) · [TWSE OpenAPI](https://openapi.twse.com.tw/)

The two collectors fail independently. A bad response leaves the last valid checkpoint intact. A failing source is retried on the next collection cycle, respecting a supplied retry deadline. The terminal reports failure and recovery. The local HTML inbox refreshes every 30 seconds and warns when a running collector misses its heartbeat. `status` also reports expired watchlist evidence, source errors, stopped collection and possible missed source windows after downtime. The exchange file can lag publication by an edition. An empty, undated or stale daily file produces a warning. Stockwatch records possible gaps for later review. It does not automatically backfill missed editions. USGS preferred identifiers can change if events merge.

**Automatic discovery.** The adapter reads TSMC’s disclosures under exchange code 2330, extracts earthquake-related titles or passages and retains the issuer’s words. A unique Taiwan-local earthquake date, matching regional watch and publication after the event yield a linked reading item. Ambiguous or undated notices remain visible in the issuer review list. Unmatched recent documents are reconsidered for 30 days. The archive link identifies the issuer, filing day and title. Open the matching statement for the full text.

**Assessment.** Discovering a filing preserves the existing operational assessment. To narrow or close a watch after reading the evidence, use `python -m stockwatch import-update <reviewed-file.json>` with the live incident ID, source and clock basis, passage, assessment, uncertainty and next check. Its actual import time controls visibility in historical views. [Reviewed import format](examples/operator-taiwan-2024.json)

**Local persistence.** SQLite holds public observations, decisions, issuer documents, health and the terminal delivery cursor. A single scheduler owns each live database. Terminal output is acknowledged after flushing, so an interruption at that boundary can repeat a printed alert. The database deduplicates entries. The HTML inbox lives beside the database and needs no web server. Collection requires an awake computer, network access to the two sources and a running monitor.

## Review rules and local configuration

- **Geographic screen.** The default triage rule is magnitude 6 or greater within 200 km of the Hsinchu reference point. It uses great-circle distance to a documented weather station near the fab's city. The radius and 24-hour discovery window are pilot choices. Facility-specific damage, ground shaking and customer losses require separate evidence.
- **Relationships.** `poll --watchlist <file.json>` accepts a dated TSMC configuration. Each site edition names the facility, coordinate source, issuer filing passages, alternatives, check date and exclusive review deadline. A link must qualify at both event and receipt time. The 2024 window is reconstructed from documents already public then. The live example needs review by **February 1, 2027 UTC**. Expired evidence appears as unavailable coverage. [Example watchlist and original sources](examples/watchlist.json)
- **Portfolio.** `inbox --portfolio <local-file.json>` ranks linked direct holdings by value and shows their combined share of one USD account. Supply both the valuation time and when the snapshot became available. Use decimal strings for cash, each long-only common stock and the total. The amounts must reconcile. A future, over-seven-day-old or invalid snapshot falls back to the public watch. History evaluates holdings at each entry's receipt. The latest view uses the requested cutoff. Keep personal amounts in a private file outside the repository. Only the local report reads that file. [Hypothetical portfolio format](examples/portfolio.json)
- **Persistence.** One SQLite transaction commits a whole feed, its decision reasons, watch revisions and last-valid checkpoint. A writer lock orders live collection and imports. Identical versions retain their first receipt. Conflicting content under one source version fails the batch. Source corrections can withdraw a geographic match. Once a direct operator statement arrives, it governs operational status. Read `inbox --audit` to see suppressed versions, rule ID and watchlist fingerprint.

## Implementation milestones

| Milestone | Acceptance check |
|---|---|
| 1. Ingest real upstream evidence | Parse the dated USGS product fixture and check its identity, clocks and coordinates. Run a separate live poll. |
| 2. Explain relevance | Link one quake to two pre-event disclosures, reproduce the 15% calculation, and exercise a distant event and stale inputs. |
| 3. Demonstrate recovery and replay | Inspect all four historical states, restart, replay 50 duplicates plus three distinct incidents, and roll back a conflicting version without losing the last valid checkpoint. |
| 4. Configure and start v1 | Select NVDA through the CLI, verify its sample account share, and run recurring collection with distinct source schedules and one writer. |
| 5. Discover issuer follow-ups | Process the reconstructed April 5 exchange row through the production adapter. Link the issuer excerpt to the April 3 watch, withhold ambiguous matches, and repeat without duplicate alerts. |
| 6. Surface failures and recover | Interrupt a partial issuer write, reject a stale feed, exercise rate limiting, restart delivery, and verify the local warning, recovery and heartbeat behavior. |

The test suite exercises the normal CLI, source adapters, transaction and portfolio paths. The next decision is whether the watch earns attention in live use. Compare actual first-read times and useful reviews against the same operator statements and existing issuer alerts, including quiet polls and missed events, before expanding sources or enabling push.
