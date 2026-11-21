# Source register and evidence status

Version 3.2 research updated 20 November 2026. This register preserves the prior research references and indexes the focused integration/deployment sources used in Version 3, its 3.1 clarification and the 3.2 Codex launch guidance. Ordinary URLs make the handoff portable outside ChatGPT.

## Evidence status

- **User context:** Current conversation and the repository's archived design chats establish goals and reported frustrations. A reported scheduling failure does not establish its technical cause.
- **Repository evidence:** The audited code is pinned to `835f06bdca2e7baea4ef1e652b46948d19ed4a74`; the preceding review ran its 68 tests offline. This is not a current-HEAD or live-feed certification. The repository README was checked again for this revision; Codex must inspect its actual checkout.
- **Public documentation:** Official vendor, framework and platform documentation establishes described interfaces and restrictions as reviewed. It does not establish the user's subscription, credentials, dataset entitlement, output quality or successful end-to-end integration.
- **Method evidence:** Primary research and professional frameworks inform method design. They do not prove this product has predictive value or establish a particular trade.
- **Design judgment:** Deployment choices, defaults, estimated engineering effort, priorities and acceptance targets are recommendations, not vendor guarantees or measured operating performance.
- **No live integration claim:** This revision did not connect a brokerage account, install financial integrations, create subscriptions, call authenticated financial endpoints or implement the product.

Current details and caveats in [agent/data access](AGENT_AND_DATA_ACCESS.md), [IBKR findings](IBKR_FINDINGS.md) and [laptop operations](../design/LAPTOP_OPERATIONS.md) take precedence over an older source-title summary. Recheck vendor plans and exact schemas during integration. Source dates, discovery dates and actual data availability are distinct.

## Prior research references retained

[S01] Freedom-Jack. AI Stock Insight repository, archived research and design discussions. Reviewed commit 835f06bdca2e7baea4ef1e652b46948d19ed4a74. https://github.com/Freedom-Jack/ai-stock-insight/tree/835f06bdca2e7baea4ef1e652b46948d19ed4a74

[S02] Freedom-Jack. Stockwatch source at the reviewed commit, particularly model.py, store.py, relevance.py, issuer.py, monitor.py and tests. https://github.com/Freedom-Jack/ai-stock-insight/tree/835f06bdca2e7baea4ef1e652b46948d19ed4a74/stockwatch

[S03] OpenAI. MCP Events for plugins. https://developers.openai.com/plugins/build/mcp-events

[S04] OpenAI. Dots tasks and memory. https://learn.chatgpt.com/docs/dots/tasks-and-memory

[S05] OpenAI. Scheduled tasks. https://learn.chatgpt.com/docs/automations

[S06] OpenAI. API credits benefit for eligible ChatGPT subscriptions. https://help.openai.com/en/articles/20001626-api-credits-benefit-for-eligible-chatgpt-subscriptions

[S07] Anthropic. Automate work with scheduled tasks. https://code.claude.com/docs/en/routines

[S08] Anthropic. Trigger a routine through the API. https://platform.claude.com/docs/en/api/claude-code/routines-fire

[S09] OpenAI. Codex SDK. https://learn.chatgpt.com/docs/codex-sdk

[S10] OpenAI. Non-interactive mode. https://learn.chatgpt.com/docs/non-interactive-mode

[S11] OpenAI. Codex App Server, authentication. https://learn.chatgpt.com/docs/app-server

[S12] OpenAI. Sign in with ChatGPT plan usage for open-source applications. https://developers.openai.com/siwc/token-sharing-open-source

[S13] OpenAI. Sign in with ChatGPT preview limitations. https://developers.openai.com/siwc/token-sharing-open-source/preview-limitations

[S14] Meta. Muse personal agent. https://ai.meta.com/muse/

[S15] Meta. Muse Code extending and automating. https://dev.meta.ai/docs/muse-code/extending

[S16] Meta. Muse Code subscriptions. https://dev.meta.ai/docs/muse-code/subscriptions

[S17] Meta. Model API and Muse Code overview. https://dev.meta.ai/docs/overview

[S18] Meta. Pricing and rate limits. https://dev.meta.ai/docs/pricing-rate-limits

[S19] OpenClaw. Automations and memory documentation. https://docs.openclaw.ai/automation/cron-jobs ; https://docs.openclaw.ai/concepts/memory

[S20] Anthropic. Financial-services reference agents and skills, Apache License 2.0. https://github.com/anthropics/financial-services

[S21] Quartr. Pro MCP overview and individual-research versus product integration. https://mcp.quartr.com/docs

[S22] Fiscal.ai. Help center, API/MCP access and subscriptions. https://fiscal.ai/help/

[S23] Koyfin. Plan comparison. https://www.koyfin.com/pricing/plans-comparison/

[S24] SEC. EDGAR Application Programming Interfaces. https://www.sec.gov/search-filings/edgar-application-programming-interfaces

[S25] SEC. Accessing EDGAR Data and fair-access requirements. https://www.sec.gov/search-filings/edgar-search-assistance/accessing-edgar-data

[S26] U.S. Bureau of Labor Statistics. Schedule of selected releases for 2026. https://www.bls.gov/schedule/2026/

[S27] Federal Reserve. FOMC meeting calendars and information. https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm

[S28] Federal Election Commission. 2026 congressional primary dates and general-election date. https://www.fec.gov/resources/cms-content/documents/2026pdates.pdf

[S29] Library of Congress. Congress.gov API. https://api.congress.gov/

[S30] Federal Reserve Bank of St. Louis. ALFRED vintage-data download help. https://alfred.stlouisfed.org/help/downloaddata

[S31] Financial Modeling Prep. API pricing plans and dataset tiers. https://site.financialmodelingprep.com/pricing-plans

[S32] Alpha Vantage. API support and free-usage limits. https://www.alphavantage.co/support/api-key/

[S33] Interactive Brokers. Market-data subscription requirements. https://www.interactivebrokers.com/docs/general/market-data-subscriptions/introduction

[S34] CFA Institute. Financial Analysis Techniques, 2026 curriculum. https://www.cfainstitute.org/insights/professional-learning/refresher-readings/2026/financial-analysis-techniques

[S35] Hand, Laurion, Lawrence and Martin. Explaining firms' earnings announcement stock returns using FactSet and I/B/E/S data feeds. Review of Accounting Studies 27, 1389–1420, 2022. DOI 10.1007/s11142-021-09597-6. Author-institution summary: https://www.colorado.edu/business/faculty-research/2021/03/23/explaining-firms-earnings-announcement-stock-using-factset-and-i/b/e/s-data-feeds

[S36] MacKinlay, A. Craig. Event Studies in Economics and Finance. Journal of Economic Literature 35(1), 13–39, 1997. https://www.bu.edu/econ/files/2011/01/MacKinlay-1996-Event-Studies-in-Economics-and-Finance.pdf

[S37] Gneiting and Raftery. Strictly Proper Scoring Rules, Prediction, and Estimation. Journal of the American Statistical Association 102(477), 359–378, 2007. https://sites.stat.washington.edu/raftery/Research/PDF/Gneiting2007jasa.pdf

[S38] Bailey, Borwein, Lopez de Prado and Zhu. The Probability of Backtest Overfitting. Journal of Computational Finance, 2017. DOI 10.21314/JCF.2016.322. https://scholarworks.wmich.edu/math_pubs/42/

[S39] NVIDIA. Financial results for the third quarter of fiscal 2027, released November 17, 2026. https://nvidianews.nvidia.com/news/nvidia-announces-financial-results-for-third-quarter-fiscal-2027

[S40] National Archives. FederalRegister.gov and API catalogue. https://catalog.data.gov/dataset/federalregister-gov-and-api

[S41] Finnhub. Official MCP integration and dataset access. https://finnhub.io/static/finnhub-how-to-connect-mcp-server.html

[S42] Anthropic. Agent Skills overview, instruction/resource packaging and explicit API integration. https://platform.claude.com/docs/en/agents-and-tools/agent-skills/overview

[S43] Anthropic. Building effective agents, distinction between workflows and dynamic agents. December 2024; consulted for architectural concepts rather than current product availability. https://www.anthropic.com/research/building-effective-agents

[S44] SQLite. Online Backup API. https://www.sqlite.org/backup.html

[S45] Anthropic. Demystifying evals for AI agents. January 2026. https://www.anthropic.com/research/demystifying-evals-for-ai-agents

[S46] OpenAI. Agents API overview, managed execution and pricing. https://developers.openai.com/api/docs/guides/agents-api/overview

[S47] OpenAI. Agents API observability and usage. https://developers.openai.com/api/docs/guides/agents-api/observability

[S48] Anthropic. Claude Managed Agents overview. https://platform.claude.com/docs/en/managed-agents/overview

[S49] OpenAI. Scheduled automations and invocation completion semantics. https://developers.openai.com/api/docs/guides/agents-api/sessions/automations

[S50] Anthropic. Monthly API credits for eligible Max, Ultra and Team plans. https://support.claude.com/en/articles/17154008-monthly-api-credits-for-max-ultra-and-team-plans

[S51] Anthropic. Platform pricing, including Managed Agents running-session charges. https://platform.claude.com/docs/en/about-claude/pricing

[S52] Anthropic. Managed Agents scheduled deployments, jitter and recovery semantics. https://platform.claude.com/docs/en/managed-agents/scheduled-deployments

## Additional Version 3 integration and deployment references

[S53] https://api.fiscal.ai/mcp — discussed in [AGENT_AND_DATA_ACCESS](../research/AGENT_AND_DATA_ACCESS.md).

[S54] https://developers.openai.com/api/docs/guides/agents-api/environments/self-hosted — discussed in [LAPTOP_OPERATIONS](../design/LAPTOP_OPERATIONS.md).

[S55] https://developers.openai.com/api/docs/guides/agents-api/tools/functions — discussed in [LAPTOP_OPERATIONS](../design/LAPTOP_OPERATIONS.md), [AGENT_AND_DATA_ACCESS](../research/AGENT_AND_DATA_ACCESS.md).

[S56] https://docs.fiscal.ai/docs/api-reference — discussed in [AGENT_AND_DATA_ACCESS](../research/AGENT_AND_DATA_ACCESS.md).

[S57] https://docs.fiscal.ai/docs/guides/free-trial — discussed in [AGENT_AND_DATA_ACCESS](../research/AGENT_AND_DATA_ACCESS.md).

[S58] https://docs.fiscal.ai/docs/guides/mcp-integration — discussed in [AGENT_AND_DATA_ACCESS](../research/AGENT_AND_DATA_ACCESS.md).

[S59] https://docs.fiscal.ai/docs/guides/mcp-skills — discussed in [AGENT_AND_DATA_ACCESS](../research/AGENT_AND_DATA_ACCESS.md).

[S60] https://docs.fiscal.ai/docs/guides/webhooks — discussed in [AGENT_AND_DATA_ACCESS](../research/AGENT_AND_DATA_ACCESS.md).

[S61] https://docs.fiscal.ai/docs/introduction — discussed in [AGENT_AND_DATA_ACCESS](../research/AGENT_AND_DATA_ACCESS.md).

[S62] https://docs.fiscal.ai/docs/reference/estimates — discussed in [AGENT_AND_DATA_ACCESS](../research/AGENT_AND_DATA_ACCESS.md).

[S63] https://docs.python.org/3.12/library/sqlite3.html — discussed in [LAPTOP_OPERATIONS](../design/LAPTOP_OPERATIONS.md).

[S64] https://financialmodelingprep.com/mcp — discussed in [AGENT_AND_DATA_ACCESS](../research/AGENT_AND_DATA_ACCESS.md).

[S65] https://github.com/Freedom-Jack/ai-stock-insight — discussed in Implementation specification.

[S66] https://github.com/anthropics/financial-services/blob/main/managed-agent-cookbooks/README.md — discussed in [AGENT_AND_DATA_ACCESS](../research/AGENT_AND_DATA_ACCESS.md).

[S67] https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/docs/specification/2026-07-28/basic/transports/streamable-http.mdx — discussed in [LAPTOP_OPERATIONS](../design/LAPTOP_OPERATIONS.md).

[S68] https://help.openai.com/en/articles/20001517-chatgpt-for-financial-services — discussed in [AGENT_AND_DATA_ACCESS](../research/AGENT_AND_DATA_ACCESS.md).

[S69] https://learn.chatgpt.com/docs/auth — discussed in [LAPTOP_OPERATIONS](../design/LAPTOP_OPERATIONS.md).

[S70] https://learn.chatgpt.com/docs/codex-sdk.md — discussed in [AGENT_AND_DATA_ACCESS](../research/AGENT_AND_DATA_ACCESS.md).

[S71] https://learn.chatgpt.com/docs/config-file/config-basic — discussed in [LAPTOP_OPERATIONS](../design/LAPTOP_OPERATIONS.md).

[S72] https://learn.chatgpt.com/docs/extend/mcp?surface=cli — discussed in [LAPTOP_OPERATIONS](../design/LAPTOP_OPERATIONS.md).

[S73] https://learn.chatgpt.com/docs/non-interactive-mode.md — discussed in [AGENT_AND_DATA_ACCESS](../research/AGENT_AND_DATA_ACCESS.md).

[S74] https://learn.microsoft.com/en-us/windows/win32/taskschd/taskschedulerschema-settings-tasktype-element — discussed in [LAPTOP_OPERATIONS](../design/LAPTOP_OPERATIONS.md).

[S75] https://learn.microsoft.com/en-us/windows/wsl/networking — discussed in [LAPTOP_OPERATIONS](../design/LAPTOP_OPERATIONS.md).

[S76] https://learn.microsoft.com/en-us/windows/wsl/setup/environment — discussed in [LAPTOP_OPERATIONS](../design/LAPTOP_OPERATIONS.md).

[S77] https://learn.microsoft.com/en-us/windows/wsl/systemd/ — discussed in [LAPTOP_OPERATIONS](../design/LAPTOP_OPERATIONS.md).

[S78] https://learn.microsoft.com/en-us/windows/wsl/wsl-config — discussed in [LAPTOP_OPERATIONS](../design/LAPTOP_OPERATIONS.md).

[S79] https://learn.microsoft.com/windows/apps/develop/notifications/app-notifications/app-notifications-console — discussed in [LAPTOP_OPERATIONS](../design/LAPTOP_OPERATIONS.md).

[S80] https://mcp.alphavantage.co/ — discussed in [AGENT_AND_DATA_ACCESS](../research/AGENT_AND_DATA_ACCESS.md).

[S81] https://mcp.alphavantage.co/mcp — discussed in [AGENT_AND_DATA_ACCESS](../research/AGENT_AND_DATA_ACCESS.md).

[S82] https://mcp.finnhub.io/mcp — discussed in [AGENT_AND_DATA_ACCESS](../research/AGENT_AND_DATA_ACCESS.md).

[S83] https://mcp.quartr.com/docs/tools — discussed in [AGENT_AND_DATA_ACCESS](../research/AGENT_AND_DATA_ACCESS.md).

[S84] https://mcp.quartr.com/mcp — discussed in [AGENT_AND_DATA_ACCESS](../research/AGENT_AND_DATA_ACCESS.md).

[S85] https://platform.claude.com/docs/en/managed-agents/mcp-connector — discussed in [AGENT_AND_DATA_ACCESS](../research/AGENT_AND_DATA_ACCESS.md).

[S86] https://platform.claude.com/docs/en/managed-agents/tools — discussed in [LAPTOP_OPERATIONS](../design/LAPTOP_OPERATIONS.md), [AGENT_AND_DATA_ACCESS](../research/AGENT_AND_DATA_ACCESS.md).

[S87] https://quartr.com/pricing — discussed in [AGENT_AND_DATA_ACCESS](../research/AGENT_AND_DATA_ACCESS.md).

[S88] https://site.financialmodelingprep.com/developer/docs/mcp-server — discussed in [AGENT_AND_DATA_ACCESS](../research/AGENT_AND_DATA_ACCESS.md).

[S89] https://sqlite.org/wal.html — discussed in [LAPTOP_OPERATIONS](../design/LAPTOP_OPERATIONS.md).

[S90] https://ubuntu.com/wsl/docs/latest/explanation/security-overview/ — discussed in [LAPTOP_OPERATIONS](../design/LAPTOP_OPERATIONS.md).

[S91] https://www.alphavantage.co/documentation/ — discussed in [AGENT_AND_DATA_ACCESS](../research/AGENT_AND_DATA_ACCESS.md).

[S92] https://www.alphavantage.co/premium/ — discussed in [AGENT_AND_DATA_ACCESS](../research/AGENT_AND_DATA_ACCESS.md).

[S93] https://www.freedesktop.org/software/systemd/man/latest/systemd.exec — discussed in [LAPTOP_OPERATIONS](../design/LAPTOP_OPERATIONS.md).

[S94] https://www.ibkrguides.com/traderworkstation/import-tickers-from-a-file.htm — discussed in [IBKR_FINDINGS](../research/IBKR_FINDINGS.md).

[S95] https://www.ibkrguides.com/traderworkstation/monitor-panel.htm — discussed in [IBKR_FINDINGS](../research/IBKR_FINDINGS.md).

[S96] https://www.interactivebrokers.com/campus/ibkr-api-page/webapi-doc/ — discussed in [IBKR_FINDINGS](../research/IBKR_FINDINGS.md).

[S97] https://www.interactivebrokers.com/docs/tws-api/doc/accounts/managed-accounts — discussed in [IBKR_FINDINGS](../research/IBKR_FINDINGS.md).

[S98] https://www.interactivebrokers.com/docs/tws-api/doc/md/streaming-data — discussed in [IBKR_FINDINGS](../research/IBKR_FINDINGS.md).

[S99] https://www.interactivebrokers.com/docs/web-api/authentication/cpgw/client-portal-gateway-faq — discussed in [IBKR_FINDINGS](../research/IBKR_FINDINGS.md).

[S100] https://www.interactivebrokers.com/docs/web-api/authentication/cpgw/installation-authentication — discussed in [IBKR_FINDINGS](../research/IBKR_FINDINGS.md).

[S101] https://www.interactivebrokers.com/docs/web-api/authentication/cpgw/limitations-of-the-client-portal-gateway — discussed in [IBKR_FINDINGS](../research/IBKR_FINDINGS.md).

[S102] https://www.interactivebrokers.com/docs/web-api/authentication/multiple-sessions — discussed in [IBKR_FINDINGS](../research/IBKR_FINDINGS.md).

[S103] https://www.interactivebrokers.com/docs/web-api/authentication/oauth-2/access-token — discussed in [IBKR_FINDINGS](../research/IBKR_FINDINGS.md).

[S104] https://www.interactivebrokers.com/docs/web-api/authentication/oauth-2/introduction — discussed in [IBKR_FINDINGS](../research/IBKR_FINDINGS.md).

[S105] https://www.interactivebrokers.com/docs/web-api/authentication/trading — discussed in [IBKR_FINDINGS](../research/IBKR_FINDINGS.md).

[S106] https://www.interactivebrokers.com/docs/web-api/v1/endpoints/watchlists/get-all-watchlists — discussed in [IBKR_FINDINGS](../research/IBKR_FINDINGS.md).

[S107] https://www.interactivebrokers.com/docs/web-api/v1/endpoints/watchlists/get-watchlist-information — discussed in [IBKR_FINDINGS](../research/IBKR_FINDINGS.md).

[S108] https://www.interactivebrokers.com/support/faq/content/34485530 — discussed in [IBKR_FINDINGS](../research/IBKR_FINDINGS.md).

[S109] https://www.interactivebrokers.com/support/faq/content/get-api-access-629299016 — discussed in [IBKR_FINDINGS](../research/IBKR_FINDINGS.md).

[S110] https://www.interactivebrokers.com/support/faq/content/long-web-api-session-last-629305657 — discussed in [IBKR_FINDINGS](../research/IBKR_FINDINGS.md).


## Version 3.1 model selection and Client Portal/Mobile clarification

The user clarified the local trial and planned server deployment, current Client Portal/Mobile use, and external-list authority. The new model choices are project recommendations grounded in current official model/effort documentation; actual account access was not tested. A read-only CLI help/version check in the research environment is not a check of the user’s machine.

[S111] https://developers.openai.com/api/docs/guides/model-selection — discussed in [MODEL_AND_EFFORT](../delivery/MODEL_AND_EFFORT.md).

[S112] https://help.openai.com/en/articles/20001275-chatgpt-work-and-codex — discussed in [MODEL_AND_EFFORT](../delivery/MODEL_AND_EFFORT.md).

[S113] https://learn.chatgpt.com/docs/config-file/config-reference — discussed in [MODEL_AND_EFFORT](../delivery/MODEL_AND_EFFORT.md).

[S114] https://learn.chatgpt.com/docs/models — discussed in [MODEL_AND_EFFORT](../delivery/MODEL_AND_EFFORT.md).

[S115] https://learn.chatgpt.com/docs/models#know-when-to-use-max-or-ultra — discussed in [MODEL_AND_EFFORT](../delivery/MODEL_AND_EFFORT.md).

[S116] https://learn.chatgpt.com/docs/pricing — discussed in [MODEL_AND_EFFORT](../delivery/MODEL_AND_EFFORT.md).

[S117] https://learn.chatgpt.com/guides/prompting-gpt-6-2-astra — discussed in [MODEL_AND_EFFORT](../delivery/MODEL_AND_EFFORT.md).

[S118] https://www.ibkrguides.com/clientportal/researchmenu/market-screener.htm — discussed in [IBKR_FINDINGS](../research/IBKR_FINDINGS.md).

[S119] https://www.ibkrguides.com/clientportal/researchmenu/watchlist.htm — discussed in [IBKR_FINDINGS](../research/IBKR_FINDINGS.md).

[S120] https://www.ibkrguides.com/iphone/watchlist.htm — discussed in [IBKR_FINDINGS](../research/IBKR_FINDINGS.md).

[S121] https://www.interactivebrokers.com/campus/trading-lessons/creating-watchlists-and-scanners-android/ — discussed in [IBKR_FINDINGS](../research/IBKR_FINDINGS.md).

[S122] https://www.interactivebrokers.com/support/faq/content/sync-watchlist-client-portal-109016343 — discussed in [IBKR_FINDINGS](../research/IBKR_FINDINGS.md).

## Version 3.2 Codex launch and reasoning guidance

[S123] https://learn.chatgpt.com/docs/agent-configuration/subagents — Ultra, explicit delegation at other effort levels, shared context and parallel-write tradeoffs; used in [MODEL_AND_EFFORT](../delivery/MODEL_AND_EFFORT.md) and [CODEX_RUNBOOK](../delivery/CODEX_RUNBOOK.md).

[S124] https://learn.chatgpt.com/guides/best-practices — Extra High for long agentic tasks, context and verification; used in [MODEL_AND_EFFORT](../delivery/MODEL_AND_EFFORT.md).

[S125] https://learn.chatgpt.com/docs/windows/windows-app — WSL agent selection, restart and separate terminal configuration; used in [CODEX_RUNBOOK](../delivery/CODEX_RUNBOOK.md).

[S126] https://learn.chatgpt.com/docs/quickstart — supported setup surfaces and selecting the project folder; used in [CODEX_RUNBOOK](../delivery/CODEX_RUNBOOK.md).

[S127] https://learn.chatgpt.com/docs/developer-commands?surface=cli — model/status and review controls; checked while preparing the launch sequence.

