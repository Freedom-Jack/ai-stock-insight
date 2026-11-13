# Project guidance

AI Stock Insight currently ships Stockwatch, a local Python 3.11+ and SQLite supplier monitor. Run commands from the repository root. The [README](README.md) contains the reproducible demo, live operation and acceptance checks.

- `python -m stockwatch configure` displays local watchlist and portfolio settings. `python -m stockwatch start --open` starts foreground collection and opens the local HTML inbox.
- `python -m stockwatch demo --monitor` verifies automatic issuer discovery offline. `python -m stockwatch demo` replays the reviewed historical case.
- `python -m unittest discover -s tests -v` runs the standard-library test suite.
- `stockwatch/` contains the source adapters, dated relevance rules, persistence, reports and CLI. `examples/` holds the public source packets, watchlist and hypothetical portfolio. Keep actual positions outside the repository.
- Keep the origin time, source version and local receipt distinct. Join exposures to dated evidence. Show the original source, important uncertainty and the next check.
- Treat retries, stale feeds, revisions, bad input and partial failures as part of ingestion. Keep source evidence, review decisions and collection checkpoints consistent. A discovered issuer statement requires review before it can change an operational assessment.
- Prefer documented public feeds when available. Consider browser-use for sources that actually require browser interaction and whose terms permit collection. AI-assisted analysis, broader news collection and visualization remain future work.

The [original design](design.md) records the longer-term architecture. The first implementation uses a single local writer and deterministic rules. Paid services and external deployment require separate approval.
