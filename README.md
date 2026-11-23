# Stock Insight

## Open your Windows personal desk

Double-click **Start-StockInsight.cmd** or run the following from this checkout.

```powershell
.\Start-StockInsight.cmd
```

Sign in as `research` using the password shown by the launcher. The **Today** page at [127.0.0.1:8765](http://127.0.0.1:8765/today) opens your saved personal workspace. Edit your watchlist under **Companies & themes** and your research instructions under **Goals**. Reports keep their sources and follow-ups in the same case.

To collect after each Windows sign-in, run the following once from this checkout. It starts the desk immediately and installs a current-user Startup shortcut. Opening the usual launcher again connects to the running desk.

```powershell
.\ops\windows\Enable-StockInsightAtSignIn.ps1
```

The green Stock Insight chart icon in the taskbar (often under **^**) belongs to the running desk. Click it to open the desk, or right-click for login details or **退出 Stock Insight** to stop the process and its collector. Closing the browser leaves collection running.

The computer checks eligible public sources and keeps the evidence and research queue in `%LOCALAPPDATA%\StockInsight\personal`. A connected dot can claim a queued case, read the saved sources, perform a comparison and write back a cited report. Its schedule and destination belong to the Work account. Keep the selected computer online and connected to Work. Use **Status → Stop this desk** to stop collection for the session. Removing **Stock Insight.lnk** from the current user's Startup folder disables automatic launch. [Live verification and account-specific delivery status](docs/acceptance/2026-11-23-live.md) · [Access, backup and restore](docs/windows-trial.md)

The same desk includes the TSMC supplier monitor under **Events & monitoring → TSMC supplier watch**. For a qualified instrument with a documented relationship, it checks USGS every five minutes and TWSE hourly. The case links the original evidence and any reviewed disclosure. [Supplier monitor and historical CLI reference](docs/stockwatch-operations.md)

## Open the historical company investigation

The isolated historical earnings replay compares two reported revenue cells and follows a subsequent filing in the same case. On the original workstation the saved replay is under `.stockinsight/replays/chat-acceptance-20261122`. [Historical interactive acceptance](docs/acceptance/2026-11-22-chat-work.md)

Run any one line to advance the corresponding replay by one step. Run it again after the pending assistant job is accepted. Each scenario creates its own workspace under `.stockinsight/replays`. The live check requires a fresh directory and access to the public Federal Reserve calendar.

```powershell
.\.venv\Scripts\python.exe -m stockinsight.replay policy
.\.venv\Scripts\python.exe -m stockinsight.replay company
.\.venv\Scripts\python.exe -m stockinsight.replay noise
.\.venv\Scripts\python.exe -m stockinsight.replay live
```

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

To verify this checkout, run `uv run --locked -m unittest discover -s tests -v`. For the optional Fiscal SDK contract test, use `uv run --locked --extra fiscal -m unittest discover -s tests -v`. To include the browser isolation regression on Windows, run `uv run --locked --extra fiscal --group browser-test -m unittest discover -s tests -v` with Edge installed. On Linux, install a Playwright-compatible Chromium before running that group. The tests use fixtures for external accounts. Update the worktree through your usual Git workflow, stop the desk first, then run `uv sync --locked --extra fiscal` before restarting the connected personal desk. Before updating a private workspace, stop its writers and copy the entire data directory, including retained source files.
