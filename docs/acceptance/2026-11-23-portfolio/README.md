# Watchlist 与组合分析验收 · 2026-11-23

本轮使用一个真实的 Stock Insight 工具调用、一个临时快照数据库和一个虚构组合。两个外部分析器仅接触示例标的。股票和基金权重的来源日期见各份回执。

## 1. IBKR 授权与快照

对官方 MCP 发出未携带凭据的 `initialize` 请求，服务器返回 HTTP 401，并在 `WWW-Authenticate` 中指定元数据地址。该地址返回的资源是 `https://api.ibkr.com/v1/api/mcp-public`，授权服务器是 `https://api.ibkr.com`，公开的 `scopes_supported` 为 `mcp.read`、`mcp.write`、`mcp.orders.submit`。其中没有列出独立的 watchlist 读取范围。IBKR 官方 FAQ 说明数据访问取决于获准工具。两份资料合起来，仍不足以判断授权界面是否另有工具级或名单级授权。自动同步待解决，未连接券商账户。解除条件是券商证明可独立授予读取选定名单成分的权限，同时拒绝账户、持仓、余额、订单及修改操作。[服务端元数据](https://api.ibkr.com/v1/api/mcp-public/.well-known/oauth-protected-resource) · [官方 FAQ](https://www.interactivebrokers.com/support/faq/content/connecting-ibkr-account-ai-platform-1437187133)

在新的临时数据库中通过 Stock Insight CLI 的 `import-list` 入口加载仅含 `ticker` 列的 UTF-8 文件。每步都调用本地 watchlist 读取函数，检查实际生效的名单。以下测试使用同一个来源 `ibkr-sample`。

| 输入与顺序 | 退出码 | 导入状态 | 生效标的 |
| --- | ---: | --- | --- |
| 完整文件 VOO、QQQ | 0 | complete | QQQ、VOO |
| 重复同一完整文件 | 0 | complete，复用同一快照 ID | QQQ、VOO |
| 只含 AAPL 的部分文件 | 0 | candidate | QQQ、VOO |
| 文件不存在 | 1 | rejected | QQQ、VOO |
| 只有表头的完整文件 | 0 | candidate，空替换待复核 | QQQ、VOO |
| 完整文件追加 AAPL | 0 | complete | AAPL、QQQ、VOO |

首轮和重试均返回 `snapshot_000ba03afdaa5fe3274cdb0f`，最后一次成功返回 `snapshot_201ddcb3e41e0811c772409b`。过渡流程是在 IBKR 编辑名单，按需导出或整理为标的快照，再在 Stock Insight 导入。测试覆盖整理后的文件；具体 TWS 版本的原始导出格式仍需一份真实样本核对。[TWS 导出说明](https://www.interactivebrokers.com/support/faq/content/34485530)

## 2. 现成分析器与独立复算

用未修改的第三方 CLI `etf-lookthrough` 0.1.0 分析 SPY 50%、XLK 30%、AAPL 20%。工具下载了 State Street 的两份 2026-11-20 持仓文件，分别解析出 505 行和 79 行。它报告两只基金共有 76 个股票名称，加权重叠率 34.2982%。混合组合中 Apple 排名第一，占 29.678645%。按完整组合权重加总，前十项占 55.3427743%。原始回执中的 `summary.top10_share` 为 55.4043%，其分母是正股票敞口，两者口径不同。[运行的源码版本](https://github.com/LucasRibeiroCaetano/etf-lookthrough/tree/4dd161e40a27ec5570fd68d6f1d335f1f1605a54) · [虚构输入](hypothetical.csv) · [完整工具回执](lookthrough.json)

独立检查从本次下载缓存解压原始 XLSX，逐份校验 SHA-256，并读取 AAPL 行的 Weight 列。SPY 持有 Apple 8.377218%，XLK 持有 Apple 18.300120%。计算 `20% + 0.50 × 8.377218% + 0.30 × 18.300120% = 29.678645%`，与 CLI 输出一致。

| 基金 | 发行方文件 | 本次下载 SHA-256 |
| --- | --- | --- |
| SPY | [每日持仓 XLSX](https://www.ssga.com/us/en/intermediary/library-content/products/fund-data/etfs/us/holdings-daily-us-en-spy.xlsx) | `416c2ee060d40afa0b41a943a7537be0bb1ffc5f4af281c68212c00b2012f7ae` |
| XLK | [每日持仓 XLSX](https://www.ssga.com/us/en/intermediary/library-content/products/fund-data/etfs/us/holdings-daily-us-en-xlk.xlsx) | `ad69d6cd10dbd0fa6dc601f4d2cfbd71bb0b383ca9b5fd161320ced5080a1aa4` |

在已安装该版本的环境中，运行 `lookthrough refresh SPY XLK`，再运行 `lookthrough analyze hypothetical.csv --no-reference --json result.json`。每日文件会更新。上述数字对应回执中的日期。另一次对 IVV、IWF 的在线抓取因返回文件无法解析而失败，因此本次未采用那两份数据。Morningstar 在本次会话没有已授权的工具，未作实测。

## 3. 同一助手调用 Stock Insight 和第三方工具

同一 chat 先调用已连接的 `stock_insight.watchlist`，返回 61 个本地标的，分属 3 个名单。回执字段包括 ticker、交易所、币种、标识解析状态与所在名单的排序。为了保留名单隐私，此处只记录字段和计数。外部调用的输入是上面的虚构配置。

除本地运行的第三方 CLI 外，同一助手还通过 MCP SDK 对 TickerInside 的远程服务执行了 `initialize`、`tools/list`、`tools/call`。服务版本 1.14.0。调用 `get_etf_portfolio_lookthrough` 传入 SPY 50、XLK 30，正常返回。该工具接受 ETF，故只传了虚构组合中的 80 个单位。它按 2026-11-19 的基金成分返回 Apple 占 ETF 子组合 11.626%，前十家公司占 43.5%。这里的分母是 80；两份报告的基金成分日期也相差一天。涵盖直接持股的整组验收以第 2 节为准。[TickerInside 服务说明](https://tickerinside.com/agent/) · [MCP 调用参数与完整回执](tickerinside-mcp.json)

这次交互已经可以由助手协调两个服务。研究上下文留在 Stock Insight，组合计算由现成工具负责。本次仅将虚构输入和验收回执保存在项目文档中。后续若要跟踪同一真实组合跨期的变化，再决定是否将用户选定的结果、数据日期和来源保存到研究数据库。


## 等权名单的复验方法

在本地选择一个名单，去除重复的证券，核对股票类别和交易代码，再生成只用于分析的 CSV。每个直接持有的股票填写 `kind=stock`、`weight=1`。工具会按相对权重归一化；六项时每项为六分之一。报告中的金额字段随输入单位变化，使用等权输入时只解释比例。按行业统计前，可先核对同一日期的发行方行业基金成分，再填入 `sector`。

运行后检查标的数、各项权重、缺失项和行业权重之和。对照指数时要统一日期，并说明比较的是同一股票类别还是同一家公司全部入指类别。原始名单、对应关系和个人工具输出保存在本地目录。
