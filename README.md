# Stockwatch

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
