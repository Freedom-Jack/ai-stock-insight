# Project guidance

Stock Insight is a local personal research desk. Run commands from the repository root. Start the personal desk with `Start-StockInsight.cmd`. The [README](README.md) covers live operation and reproducible exercises.

- `stockinsight/` owns the personal watchlist, SQLite research cases, monitoring, assistant tools, delivery and web UI. Changes to shared behavior must work through the personal desk.
- `stockwatch/` provides the supplier source adapters and evidence rules used by the desk. Its original CLI can open historical ledgers. The [supplier reference](docs/stockwatch-operations.md) includes offline discovery and replay commands.
- `python -m unittest discover -s tests -v` runs the standard-library test suite.
- `examples/` holds public packets, example lists and a hypothetical portfolio. Keep private lists, positions, credentials and runtime databases outside Git.
- Keep the origin time, source version and local receipt distinct. Join exposures to dated evidence. Show the original source, important uncertainty and the next check.
- Treat retries, stale feeds, revisions, bad input and partial failures as part of ingestion. Keep source evidence, review decisions and collection checkpoints consistent. A discovered issuer statement requires review before it can change an operational assessment.
- Prefer documented public feeds when available. Consider browser-use for sources that require browser interaction and whose terms permit collection.

See the [harness review](docs/architecture-review-v0.3/HARNESS_ARCHITECTURE_REVIEW.md) for the research architecture and the [original design](design.md) for the supplier monitor. Paid services and external deployment require separate approval.
