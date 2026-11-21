# Stock Insight on Windows

## Start, stop and restart

Open PowerShell in the implementation worktree and run the launcher. Double-clicking the same file also works.

```powershell
Set-Location 'E:\OpenAI\ChatGPTDesktop\worktrees\2541\ai-stock-insight'
.\Start-StockInsight.cmd
```

The launcher opens **http://127.0.0.1:8765/today**. Enter username `research` and the password printed in the terminal. Keep that terminal open for scheduled checks. Use **Ctrl+C** or **Status → Stop this desk → Stop Stock Insight** for a graceful stop. Restart with the same command. Each start issues a fresh password. To select another port use `--port 8770`. Add `--no-browser` to print the address without opening a tab.

## First use

1. In **Companies & themes**, paste the instrument-only CSV below. Select **This is the complete selected list** and import. The form also accepts individual tickers. The qualified rows below establish the issuer identities used by the connected source routes. Symbol-only entries can be kept on a watchlist with provisional identity. For a later replacement, inspect the membership changes before accepting it.

   ```csv
   ticker,listing_exchange,security_type,currency
   NVDA,NASDAQ,STK,USD
   MSFT,NASDAQ,STK,USD
   ```

2. In **Research**, choose NVDA, keep **On-device model and public-source tools**, and ask **Compare NVIDIA revenue for Q2 FY25 and Q1 FY25.** Open a citation to inspect the issuer's dated observations, source hash and accounting basis. The financial comparison was 26,044 to 30,040 USD million in this historical release. For issuer headlines, ask **Which NVIDIA press releases are in the saved feed?**
3. On a case, use **Add a note** for a judgment, intention, reported action or review. Attach a review date or request a flag when new source evidence is saved. **Investigate again** produces a revision of the same question. **Plan a follow-up question** preserves the relationship to the original case. Open the plan and run the queued investigation. **Mark this revision reviewed** records your review explicitly.
4. Open **Events & monitoring → Set a check schedule → NVIDIA Newsroom press releases**. Select the resolved NVDA listing, choose an interval, and enable checks. Refresh the page to see results. Published headlines link to their issuer source. **Add a dated event to your plan** records a personal calendar item and its watchlist relevance. Find planned questions and review conditions under **Upcoming research** and all note history under **Journal**.
5. Under **Today**, open unread briefs and watchlist events. Under **Status**, inspect the last source checks and investigation states. The monitor records expected times and outcomes in UTC. After the desk has been closed, it records missed occurrences and checks once to catch up.

## Methods and access

The installed Qwen2.5-0.5B-Instruct model runs locally with a pinned Windows x64 llama.cpp binary. It chooses among application methods. Source tools perform retrieval and calculations, and the host verifies the saved assertions. The local financial-tool option uses the same evidence checks without model inference. A missing source, unverified price move or unsupported question can produce a partial or blocked case. No hosted model or brokerage connection is needed. [Executor verification](trial-executor.md)

The NVIDIA newsroom feed provides current issuer announcements. A feed publication time establishes when the issuer published its headline. Future event dates can be entered as personal plans. The named financial release covers Q1/Q2 FY25. The separate SEC quarterly-revenue route supports resolved NVIDIA and Microsoft listings and requires an identifying contact email authorized for SEC fair access. Set it for the launcher's PowerShell session if you wish to use that route.

```powershell
$env:STOCKINSIGHT_SEC_CONTACT = 'your-authorized-contact@example.org'  # replace before use
.\Start-StockInsight.cmd
```

Ask about reported quarterly revenue using explicit date ranges or the **latest saved** observations. SEC periods use dates from the filing. Resolved filings and issuer data cover a subset of financial questions. Prices, pre-release Street consensus, trading and continuous off-device operation are outside the connected trial. [NVIDIA release](https://nvidianews.nvidia.com/news/nvidia-announces-financial-results-for-second-quarter-fiscal-2025) · [NVIDIA feeds](https://nvidianews.nvidia.com/rss) · [SEC EDGAR access](https://www.sec.gov/search-filings/edgar-application-programming-interfaces)

## Data, backup and restore

The launcher prints the active directory. Its default personal directory is `%LOCALAPPDATA%\StockInsight\personal`. Journals, questions, completions, receipts and source metadata are in `research.sqlite3`. Retained full documents are in its adjacent `documents` folder. The demo uses `%LOCALAPPDATA%\StockInsight\demo` and synthetic evidence. Use `--root D:\StockInsight` to put both profiles under another parent directory. Previous low-level CLI workspaces such as `.stockinsight` can still be opened with the CLI's original `--data-dir` option.

For a verified backup, supply a **new** directory name under an existing parent. The launcher takes a consistent SQLite snapshot, verifies database integrity and copies the referenced full-document bytes. Backups contain personal research in readable form. Choose a destination under your control. The launcher also saves a pre-upgrade backup before migrating an existing launcher workspace.

```powershell
$archive = Join-Path $env:USERPROFILE ('StockInsight-backup-' + (Get-Date -Format yyyyMMdd-HHmmss))
.\Start-StockInsight.cmd --backup "$archive"
.\Start-StockInsight.cmd --root "$env:USERPROFILE\StockInsight-restored" --restore "$archive"
.\Start-StockInsight.cmd --root "$env:USERPROFILE\StockInsight-restored"
```

Use a fresh restore root. Stop the original desk before running scheduled checks in a restored copy. The backup command excludes model weights and terminals' session passwords. To restore a fixture workspace, use `--demo` on both commands.

## Update or reinstall

Stop the desk, make the verified backup above, and select the intended local code revision. In this checkout run `uv sync --locked --group browser-test` and restart. If the model assets need reinstalling, run the commands below. The install fetches the free, hash-pinned model and runtime on demand. It can reuse verified downloads. They live under the code checkout at `.stockinsight\models\qwen2.5-0.5b`, separate from personal data.

```powershell
.\.venv\Scripts\python.exe -m stockinsight.local_model install
.\.venv\Scripts\python.exe -m stockinsight.local_model verify
```

Run `.\Start-StockInsight.cmd --demo` for an offline synthetic loop. The opt-in live verification starts a personal workspace, reopens it after a graceful stop, then opens the separate demo. It uses the installed Edge browser and local weights, and writes its disposable workspaces, receipts and screenshots under an existing parent.

```powershell
.\.venv\Scripts\python.exe scripts\verify_windows_trial.py --output-parent "$env:TEMP"
```
