# Build the monitoring MVP

User messages and assistant replies from the completed research and implementation turns on November 5, 2026. [Stockwatch implementation and replay](../../README.md#verify-v1-offline)

## Turn 1

### User

We are moving from research into implementation.

Read `monitoring-research.md` and the existing project instructions and documentation. Use the previous research as your starting point, but critically evaluate its assumptions and resolve any essential design gaps.

Your objective is to build the smallest useful, end-to-end version of the system that demonstrates its distinctive value.

Preserve the long-term goals: evidence-grounded analysis, meaningful early warnings, adaptive portfolio-aware relevance, reliability, and sustainable operating costs.

Make reasonable engineering decisions independently. Avoid premature complexity, but don't sacrifice foundational correctness or extensibility.

Establish a concise implementation plan with verifiable milestones, then begin building. Use real data where practical, test the actual behavior, and maintain project documentation.

Ask for my input only when a consequential decision genuinely requires it. Don't incur paid costs or deploy externally without approval.

I want working software and a reproducible demonstration, not another extended research report.

### Assistant

I’ll read the research and project guidance, then choose a small workflow that can be demonstrated end to end. I’ll define what counts as a passing demo before building it, and keep the work local and free of paid services.

### Assistant

I found `monitoring-research.md` in the main checkout. Its strongest candidate for a first build is the Taiwan supplier watch. A public earthquake report can prompt a review before a chipmaker comments, and a later operator update can narrow that watch. The software needs to keep those two kinds of evidence separate.

I’ll use three milestones: replay a real event from a dated source, connect it to a documented supplier relationship and an optional local portfolio, then verify that replay, restart, and later evidence produce the right history without duplicate alerts. The demo will run offline, with a separate command to check the public feed.

### Assistant

The replay now has a USGS origin report from 00:14 UTC on April 3, 2024, plus dated TSMC filings that distinguish partial recovery from confirmed recovery. The supplier filings support reviewing AMD and NVIDIA, but leave each customer’s allocation to the local fab unknown. The live adapter also fetched and parsed eight events from the free USGS feed. I’m connecting those inputs to the persistent inbox and testing what it shows at each cutoff.

### Assistant

The offline demo now produces four revisions of one watch. An April 3 cutoff shows only the earthquake evidence and the two supplier links. The watch narrows on the April 5 filing and closes on April 18. Replaying the case adds zero entries.

The completed live command also recorded eight earthquakes and correctly produced no watches. I’ve checked restart, conflicting revisions, stale feeds, and portfolio privacy, and I’m finishing the run instructions.

### Assistant

Built **Stockwatch**, a local monitor that connects earthquake reports to US companies through dated supplier disclosures.

The offline demo replays the April 2024 Taiwan earthquake. It opens one watch for AMD and NVIDIA through TSMC, identifies **$15,000 of a hypothetical $100,000 portfolio** for review, and shows why customer-specific losses remain unknown. Later TSMC filings narrow the watch and then close it. Each step links to its evidence. [TSMC’s recovery disclosure](https://www.sec.gov/Archives/edgar/data/1046179/000104617924000050/a20240418.htm)

**Run the demo** from the project root with the command verified on this machine:

```powershell
uv run --offline --no-cache --python 3.14 -m stockwatch demo
```

**Verification:** All 35 tests passed. Replaying the case added zero duplicate entries. A live USGS poll recorded eight earthquakes and correctly opened zero watches.

I kept the first release to one supplier, a SQLite inbox, and human-reviewed operator updates. Historical receipt times are simulated, so live warning lead remains unmeasured. Everything ran locally with $0 in service charges.

The implementation milestones, live commands, and portfolio format are in the [README](../../README.md).

## Turn 2

### User

Continue from the working Stockwatch demo and build the first complete local v1. I want to configure a watchlist, start the monitor with one command, and receive evidence-linked local alerts as events develop. Include scheduled collection, automatic discovery of issuer follow-ups, and a visible warning if coverage fails. Test each milestone and keep building through completion. Use the sample portfolio by default. Ask me only for a consequential decision, paid cost, or external deployment.

### Assistant

I’ll check how the demo collects evidence and stores watch revisions, then build and test the full local workflow: configure a watchlist, start one command, receive alerts and issuer follow-ups, and see when a source goes quiet or fails. I’ll use the sample portfolio by default.

### Assistant

The existing 35 tests pass. I’ll verify v1 in three steps: save a watchlist and apply the default sample allocation, run both sources on a recurring local schedule, then replay a real issuer statement through automatic discovery. I’ll also interrupt a source and restart the monitor to check that the coverage warning is visible and alerts survive without duplication.

### Assistant

Watchlist configuration now passes its tests, including ticker selection, unsupported symbols, partial edits and switching portfolios. The default is a labeled hypothetical allocation, so a live alert can show portfolio relevance without treating the 2024 sample as current holdings.

For issuer follow-ups, I found a working public source in the Taiwan Stock Exchange’s daily material announcements. The monitor will preserve TSMC’s original excerpt and link it to a watch only when the evidence identifies a matching earthquake. Ambiguous notices will go to a separate review list.

### Assistant

The monitor discovered the historical TSMC filing through the new exchange adapter and attached it to the existing watch. The live command also recovered from a rejected future-dated USGS response on its next run, with both sources then reporting healthy. I’m now testing repeated scheduled cycles, interruption during a database write, and what the local inbox shows after the collector stops.

### Assistant

The foreground monitor completed two real scheduled cycles and stopped on Ctrl+C. It checked USGS twice while leaving the hourly issuer check on its own schedule. I also verified the browser inbox in Edge at desktop and phone widths, including clickable evidence links and a warning that appears when the collector’s heartbeat becomes overdue.

### Assistant

**Stockwatch v1 is ready.** From the project root, start it and open the local alert inbox with one command:

```powershell
uv run --offline --no-cache --python 3.14 -m stockwatch start --open
```

It defaults to AMD, NVIDIA, and the hypothetical $100,000 sample portfolio. It checks USGS every five minutes and Taiwan Stock Exchange disclosures hourly. New alerts appear in the terminal and browser inbox with evidence links. Source failures, stale coverage, and a missed collector heartbeat produce visible warnings.

To select NVIDIA alone, run `python -m stockwatch configure --tickers NVDA`, then restart. Keep the monitor running while you want coverage. **Ctrl+C stops it.**

TSMC follow-ups are discovered automatically. Ambiguous filings go to a review list, and changing a watch’s operational assessment requires reviewing the issuer’s evidence. The exchange source publishes daily.

**Verified:** 68 tests passed, two real scheduled cycles completed, and the offline replay discovered a historical TSMC follow-up without duplicating it on restart. The verification session has stopped. Everything ran locally with $0 in service charges.

[Setup and replay instructions](../../README.md) · [Recreate the verified replay inbox](../../README.md#verify-v1-offline)
