# Stock Insight on Windows

## Start, stop and restart

Open PowerShell in the main checkout and run the launcher. Double-clicking the same file also works.

```powershell
Set-Location 'E:\Project\ai-stock-insight'
.\Start-StockInsight.cmd
```

The launcher opens **http://127.0.0.1:8765/today**. Enter username `research` and the password printed in the terminal. For unattended collection, run `.\ops\windows\Enable-StockInsightAtSignIn.ps1` once. It starts the desk immediately and creates a Startup shortcut for the current user. Once the background listener is running, close the launcher or browser at any time. A foreground-only session needs its terminal to stay open. Use **Status → Stop this desk → Stop Stock Insight** for a graceful stop. Each new listener issues a fresh password. To select another port use `--port 8770`. Add `--no-browser` to print the address without opening a tab.

## First use

1. In **Companies & themes**, paste the instrument-only CSV below. Select **This is the complete selected list** and import. The form also accepts individual tickers. The qualified rows below establish the issuer identities used by the connected source routes. Symbol-only entries can be kept on a watchlist with provisional identity. For a later replacement, inspect the membership changes before accepting it.

   ```csv
   ticker,listing_exchange,security_type,currency
   NVDA,NASDAQ,STK,USD
   MSFT,NASDAQ,STK,USD
   ```

2. In **Goals**, adopt **Keep me prepared for important developments affecting my watchlist.** The desk selects sources for eligible listings, prepares for upcoming events and investigates relevant changes. Defaults are a weekday summary by 08:30 Toronto time and three event investigations per goal per UTC day. Goal edits preserve earlier versions. Set a specific listing or an accepted theme for narrower coverage. **Ranked research agenda** shows active questions, approaching events, and dossier work.
3. Keep the desk running in your signed-in Windows session. **Status → Send a test notice** checks the desktop route. A new report also queues a notice. Open its private link or return to **Today → report** to inspect the dated sources, rationale, alternatives and future observations. Marking it reviewed is a separate action. The desk runs while the computer is awake. On restart it records missed deadlines and groups catch-up work. The app's visible Windows notification requires an interactive desktop session.
4. For an immediate investigation, open **Research**. Ask **Compare Microsoft GAAP revenue for Q1 FY27 and Q1 FY26.** The issuer published 92,279 and 77,673 USD million respectively. Click a citation to inspect the original source and retained qualification. For a historical comparison ask **Compare NVIDIA revenue for Q2 FY25 and Q1 FY25.** For a dated newsroom lookup ask **Which NVIDIA press releases are in the saved feed?**
5. On a case, **Add a note** saves a judgment, intention, reported action or review. **Investigate again** creates a revision. **Plan a follow-up question** saves a linked question. A new eligible edition of cited financial evidence can reopen the case. For a primary transcript choose **Attach a qualifying or contrary primary passage**, select the claim and document, and supply the exact passage and reason. **Upcoming research** and **Journal** retain personal review conditions and authorship.
6. **Events & monitoring** shows expected, running, completed, failed and missed checks along with their actual receipts. A manual override takes precedence over goal-managed scheduling. **Research → Financial and event research methods** provides conditional valuations, dated expectations, peer comparisons, historical cohorts, closing-price windows and JSON reports. **Companies & themes → Review evidence** lets you approve or revoke a source-backed exposure. [Versioned methods and data-entry examples](local-research-methods-v1.md)

## Methods and access

The installed Qwen2.5-0.5B-Instruct model runs locally with a pinned Windows x64 llama.cpp binary. It chooses among application methods. Source tools perform retrieval and calculations, and the host verifies the saved assertions. The local financial-tool option uses the same evidence checks without model inference. A missing source, unverified price move or unsupported question can produce a partial or blocked case. No hosted model or brokerage connection is needed. [Executor verification](trial-executor.md)

Public routes include NVIDIA newsroom metadata, the dated NVIDIA and Microsoft financial releases, Microsoft's annual shareholder meeting, the Federal Reserve policy calendar and UK Competition and Markets Authority headlines naming a supported issuer. The Microsoft meeting and FAQ belong to the same publisher. Calendar dates and headlines establish only what their sources report. The free SEC quarterly-revenue and filed 8-K routes require an identifying contact email authorized for SEC fair access. Set it in the launcher's PowerShell session if you use those routes.

```powershell
$env:STOCKINSIGHT_SEC_CONTACT = 'your-authorized-contact@example.org'  # replace before use
.\Start-StockInsight.cmd
```

Issuer-specific automatic coverage currently centers on the qualified NVDA and MSFT listings. Additional tickers can retain memberships, notes and plans. Missing source coverage appears in reports. An operator-supplied market-only file can support exact same-basis closing-price windows. Automatic price feeds, verified pre-release Street consensus, Fiscal entitlements and brokerage integration are unavailable in the default configuration. BLS calendar acquisition returned HTTP 403 on this computer. [NVIDIA release](https://nvidianews.nvidia.com/news/nvidia-announces-financial-results-for-second-quarter-fiscal-2025) · [Microsoft investor relations](https://www.microsoft.com/en-us/investor/earnings/fy-2027-q1/press-release-webcast) · [SEC EDGAR access](https://www.sec.gov/search-filings/edgar-application-programming-interfaces)

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

To transfer selected research, open a case and select **Export this case and its citations**. Open its exact listing in the destination desk and use **Import a case or selected conversation**. An import is read-only research history. A native workspace backup preserves the live scheduler, delivery and revision records. For a selected conversation, supply a JSON list of objects with `role` (`user` or `assistant`), `content` and optional `timestamp` with UTC offset. Imported statements retain attribution. Fixed public-information cutoffs exclude private hindsight.

## Update or reinstall

Stop the desk, make the verified backup above, and select the intended local code revision. For a connected personal desk, run `uv sync --locked --extra fiscal` to install the locked MCP dependency. Add `--group browser-test` for browser tests. Restart the background desk with the sign-in script above. If the model assets need reinstalling, run the commands below. The install fetches the free, hash-pinned model and runtime on demand. It can reuse verified downloads. They live under the code checkout at `.stockinsight\models\qwen2.5-0.5b`, separate from personal data.

```powershell
.\.venv\Scripts\python.exe -m stockinsight.local_model install
.\.venv\Scripts\python.exe -m stockinsight.local_model verify
```

Run `.\Start-StockInsight.cmd --demo` for an offline synthetic loop. The opt-in live verification starts a personal workspace, reopens it after a graceful stop, then opens the separate demo. It uses the installed Edge browser and local weights, and writes its disposable workspaces, receipts and screenshots under an existing parent.

```powershell
.\.venv\Scripts\python.exe scripts\verify_windows_trial.py --output-parent "$env:TEMP"
.\.venv\Scripts\python.exe scripts\verify_proactive_release.py --output-parent "$env:TEMP"
```

The proactive check sends an actual generic Windows notice from a fresh disposable workspace after closing its dedicated Edge process. It checks the real window, reopens the cited report and verifies review persistence after restart. To check local configuration from the code directory use `.\.venv\Scripts\python.exe -m stockinsight --data-dir "$env:LOCALAPPDATA\StockInsight\personal" doctor`. The separate single-server profile and off-host commissioning steps are documented in the [commissioning guide](server-commissioning.md).
