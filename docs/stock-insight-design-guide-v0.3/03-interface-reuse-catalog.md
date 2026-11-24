# Stock Insight：现成接口与复用接入目录

**v0.3｜核查日期：2026-11-22｜给 Codex 的已完成研究输入**

配套任务书：`02-architecture-codex-technical-zh.md`。本文件记录外部接口的事实与建议接法，不预先固定内部 harness 架构。

**核查范围：** 官方文档、官方 OpenAPI / SDK 源码，以及 Stock Insight 审查快照 `ad86b95b7e71cdb81554a0684bbc43811de01a84` 的静态代码。没有使用用户凭据调用数据接口、验证套餐或登录 IBKR；文档可用不等于账号已接通。

## 1. 建议直接采用的接入方向

**延伸已有公共来源与 Fiscal 基础，优先只补薄适配器。**

| 需求 | 主候选 | 条件备选 |
| --- | --- | --- |
| 原始公司公告、监管申报 | 现有 issuer RSS + SEC EDGAR | 所选 provider 的 filings / IR 资源 |
| 公司新闻、财报日历、财务与 KPI | Fiscal REST；研究按需经实际 MCP catalog 调用 | 新闻可选 Alpaca；新闻/日历可选 Finnhub |
| 价格上下文 | 已有价格语义 + 能满足任务的 Fiscal 数据 | 盘前盘后、分钟线或流式需求用 Alpaca Data API |
| 宏观与政策事件 | 现有 Fed / BLS / CMA 来源 | Fed 官方 RSS、按需 FRED 日历补充 |
| 个人关注列表 | 继续保留现有完整文件快照；IBKR 为来源权威 | 账号条件满足后，只读拉取选定 IBKR watchlist |

没有必要默认同时接三家新闻商或重建通用行情平台。若已有合适订阅，优先复用实际已有权益；改变主候选时说明覆盖、时间精度、费用或维护依据。

**固定取数无需 LLM。** 普通程序可以调用 REST、官方 SDK，也可以使用 MCP 客户端。模型负责开放式调查和解释；供应商负责数据服务。本项目负责身份、时间、版本、去重、恢复补采、配额和研究接续。

## 2. 当前仓库已经有的接入基础

所有路径相对 repo 根目录；采用前检查实际 checkout。

| 真实代码位置 | 已有能力 | 尚不能当成已完成的能力 |
| --- | --- | --- |
| `stockinsight/providers.py` | 有界请求、来源检查记录、`probe_fiscal()` 公司资料预检、`discover_fiscal()` MCP 目录发现 | Fiscal 新闻/日历/价格采集，完整通用 `tools/call` 转发；profile 成功不证明其他数据权益 |
| `stockinsight/issuer_news.py` | NVIDIA 官方 RSS 元数据解析；`observe()` 将新增/修订送入事件记录 | 任意公司的通用新闻全文系统 |
| `stockinsight/monitor.py`、`evidence.py`、`events.py` | 来源检查、证据保存、事件接纳与监测链 | 不能仅因任务创建就认定来源已检查或提醒已交付 |
| `stockinsight/sources_calendar.py`、`bls_calendar.py` | Fed FOMC、BLS、CMA 和指定发行人来源；已有节奏与来源语义 | 不是所有公司的通用财报日历；新增 Fiscal 日历仍需适配 |
| `stockinsight/methods.py` | 预期快照、财务比较、价格导入及限定窗口分析等已有业务逻辑 | 自动实时价格流、完整历史 Street 数据并未因此获得 |
| `stockinsight/universe.py` | 文件/手工 watchlist 快照、身份、完整性与候选接纳 | 未发现已接通 IBKR 自动拉取 |

现有 SEC filing 入口只在受限最近记录中选最新合格 8-K，并提取有限段落；现有 issuer 入口也有指定公司范围。扩展时应说明覆盖变化，避免把局部实现当作全市场完成。

仓库对 Fiscal 预检有本地调用预算和显式配置门槛。新采集器应由 Codex 设计合理的总配额与调度，不应绕过现有控制，也不能把预检额度直接当成常驻运行设计。

## 3. Fiscal：连接与身份

### 协议已经明确

| 用途 | 官方入口 | 鉴权 / 复用方法 |
| --- | --- | --- |
| REST | `https://api.fiscal.ai` | 请求头 `X-Api-Key`。延伸现有 `STOCKINSIGHT_FISCAL_KEY` 等配置约定，密钥不进入日志 URL |
| MCP | `https://api.fiscal.ai/mcp` | Streamable HTTP；服务支持 OAuth 或 `Authorization: Bearer <key>`。现有代码使用 Bearer 路径 |
| API 规范 | `https://api.fiscal.ai/openapi.json` | 匿名可读；本次已下载并核对路径、查询参数和响应 schema |
| 人工浏览 | `https://api.fiscal.ai/docs` | 官方 Swagger UI；与文字文档交叉核对 |

MCP 具体操作名由 `initialize → tools/list` 读取，并在需要时继续目录分页，再按返回 schema 调用 `tools/call`。**不要把 REST operationId 直接当成 MCP 工具名。** MCP 本身不是新闻推送机制，也不会让一个执行环境自动继承另一个环境的账号授权。[F1] [F2]

### 公司与证券身份

先调用 `GET /v3/company/profile?companyKey=NASDAQ_NVDA`，或使用已解析的 ticker + exchange。保留响应的公司、security、listing 身份；后续公司查询可使用 `fscl=<companyFiscalIdentifier>`。

批量发现用 `GET /v3/companies-list?pageNumber=1&compact=true`。网页界面的 “company / companies” 是展示标签，**本次 OpenAPI 的实际标识参数是 `fscl`**；不要把 UI 标签当请求参数。公司数据和具体上市证券的行情身份应分开，尤其是次级上市与 ADR。[F3]

## 4. Fiscal：已经核实的能力入口

下表路由均相对 `https://api.fiscal.ai`，均为 GET，使用第 3 节鉴权。`<id>` 来自身份解析；日期和股票只是参数示意，不是要执行的实时请求。参数核查依据为官方 OpenAPI，研究语义补充见对应文档。[F4]

| 能力 | 具体路由和关键参数 | 接入要点 |
| --- | --- | --- |
| **公司新闻条目** | `/v1/company/news?fscl=<id>&startDate=<UTC日期>&endDate=<UTC日期>`；可选 `eventType`、`importance`、`directArticle` | 返回条目与来源链接；日期成对提供、含首尾、最多 31 天；省略为最近 14 天。本次 schema 未见稳定文章 ID 或该端点分页。 |
| **跨公司新闻发现** | `/v1/top-news?startDate=...&endDate=...&pageNumber=1&pageSize=100` | 最长 7 天，`pagination/data`；可按事件、重要性和市值筛选。默认市值筛选会影响覆盖，应明确所选条件。 |
| **新闻摘要** | `/v1/company/news-summary?fscl=<id>` | 每日生成的派生摘要，带生成与适用时间；不能用它替代及时的新闻入口。 |
| **财报日历** | `/v1/events-calendar?fscl=<逗号分隔ID>&startDate=...&endDate=...&page=1&pageSize=100` | 返回 `data/meta`；当前为 earnings。保留事件 ID、状态、日期窗口及可用的精确时刻。`page` 需要 `pageSize`；不能套用其他端点的 `pageNumber`。 |
| **IR 事件及电话会** | `/v1/company/ir-events?fscl=<id>`；`/v1/company/ir-events/transcript/<eventKey>?fscl=<id>` | 从 IR 列表选择 `resourceType=transcript` 的条目，以其 `resourceId` 作为转录路径的 `eventKey`；document 的 `resourceId` 是 filing ID。没有转录资源时保留未就绪状态。财务季度、电话会日期和资料到达时间分别处理。 |
| **财务报表与业务指标** | `/v1/company/financials/<statementType>/standardized?fscl=<id>&periodType=quarterly`；需要原口径时使用 `/as-reported`；`/v2/company/segments-and-kpis?fscl=<id>&periodType=quarterly` | statementType 为 income-statement、balance-sheet 或 cash-flow-statement。显式选择期间，默认 annual 不适用于所有问题；留意 YTD、重述、币种与原始来源。 |
| **Street / Agentic 预期** | `/v1/company/estimates/street?fscl=<id>&history=true`；另一类为 `/v1/company/estimates?fscl=<id>&includeReportedPeriods=true` | 两者含义不同；见第 5 节。保存实际与预期的期间、口径、币种和信息可得时间。 |
| **日线 / 日内价格** | `/v3/company/stock-prices?fscl=<id>&startDate=...&endDate=...`，可用 `latest=true`；`/v1/company/stock-prices/intraday?fscl=<id>&startDate=...&endDate=...` | 日线 v3 返回实际 listing 身份。日内示例的 `datetime/price` 尚不足以证明时区、延迟和盘前盘后覆盖；此处保留明确能力缺口。 |

### 新闻与事件的增量处理

以下是根据接口特点提出的本项目接入要求，具体实现由 Codex 选择：

- Fiscal 新闻的 `date` 是 UTC 文件日期，`collectedAt` 是采集时间，不能冒充原文发布时间。保留各自含义；发布时间未知就明确未知。
- `sourceUrl` 可能指向列表或报价页。无稳定文章 ID 时需要组合身份与内容版本处理，不能仅按 URL 去重；不能把每次重复采到都当新事件。
- 对按日期取数的接口，使用有重叠的窗口补采，并区分同一条目的修订。提交记录成功后再推进覆盖位置；长期离线超过可查询范围时记录缺口。
- 财报日历有 `eventId/eventGroupId`、`eventStatus`、`eventDate/dateWindow`、`eventDatetimeUtc/eventTimezone`。同一事件改期应更新既有观察；estimated/projected 不应被提升为精确发布承诺。
- 上游 `importance` 或 summary 可作为线索。是否对你的研究重要，仍由本项目结合目标判断；不要只保留供应商高分条目而丢失评估漏报的机会。

## 5. Fiscal：必须明确的权益与时效

**免费范围。** 官方当前列出 100 家限定公司、250 calls/day，包含 NVDA/MSFT，REST 与 MCP 共用该范围和限制；不是所有数据包与所有公司已授权的证明。[F5]

一个配额示例：2 家公司每 15 分钟全天轮询，单新闻就需要 `2 × 4 × 24 = 192` 次/日；5 家需要 480 次。这个算术说明关注范围、频率、时段和聚合入口应一起设计，不是在这里规定固定轮询频率。

**预期权限。** Street 文档一方面写无该数据包的 keys 可获得免费样本公司，另一方面明确排除 personal non-commercial API plans。不能从搜索摘要或免费样本说明推出个人账号拥有 Street 权限。以账号类别、数据协议和受控响应核实；当前仍按未验证处理。[F6]

**预期时间。** Street 历史描述为按日记录的共识变化，不能单凭一个 `asOf` 日期证明公告前某个盘中时刻可得。Agentic Consensus 含公司指引/模型估计等，不改名成华尔街一致预期。无法得到可靠历史时，可前向保存可用快照，同时继续能被证据支持的研究。[F6]

**推送。** Fiscal webhook 提供数据更新提示，news、filings、IR 等更新之后仍要调用相应 REST 获取内容。校验签名、快速接收并持久记录；按更新内容区分去重键。其公开重试窗口很短，不能保证 laptop 离线后补齐。因此默认先用出站轮询与补采；有稳定可接收环境时再决定 webhook。MCP 出站调用不要求把笔记本暴露为公网服务。[F7]

## 6. SEC 与发行人：保留现有原始来源

| 能力 | 官方入口 | 与现有项目连接 |
| --- | --- | --- |
| SEC 申报索引 | `https://data.sec.gov/submissions/CIK<10位补零CIK>.json` | 用 accession number 标识申报，读取 form、时间、primaryDocument；历史依 `filings.files` 给出的文件继续取 |
| SEC 结构化财务 | `https://data.sec.gov/api/xbrl/companyfacts/CIK<10位CIK>.json`；单指标使用 companyconcept | 现有 SEC 财务路径已可延伸；选期间、单位、表单与重述版本时保留可追溯依据 |
| NVIDIA 公告 RSS | `https://nvidianews.nvidia.com/cats/press_release.xml` | 现有 `issuer_news.py` 已接此入口；保留官方标题、URL、发布时间及修订 |

SEC 数据 API 不需 API key，使用带真实联系信息的 User-Agent；官方当前整体限制不超过 10 请求/秒。项目已有更保守限速，应保留统一控制，并按提醒时效审查原一小时成功缓存是否合适。SEC 是申报来源，不覆盖全部媒体消息。[S1] [S2]

RSS 是滚动列表，不能假定离线很久以后仍可完整补回。发行人来源可以确认原始公告，媒体和供应商摘要则提供发现线索；它们不应被无差别计为独立证据。

## 7. Alpaca：新闻与专用行情的条件备选

这是数据能力接入，不需要引入订单执行。正式 Python 包为 `alpaca-py`；采用前核查所用 release 与 LICENSE，数据权益与 SDK 许可分别确认。

### 新闻

`GET https://data.alpaca.markets/v1beta1/news`

请求头：`APCA-API-KEY-ID`、`APCA-API-SECRET-KEY`。常用参数：`symbols`、`start/end`、`sort`、`limit`（1–50）、`include_content`、`page_token`；继续读取返回的 `next_page_token`。官方 SDK 入口是 `alpaca.data.historical.NewsClient.get_news(NewsRequest(...))`。[A1] [A2]

有实时权益时可连接 `wss://stream.data.alpaca.markets/v1beta1/news`，用 `alpaca.data.live.NewsDataStream.subscribe_news(handler, *symbols)`。文章 ID、`created_at/updated_at` 支持识别修订；content 可能为空或含 HTML。重连后仍需 REST 补采。[A3]

普通接口可用不证明最近 15 分钟或全文权限可用。当前官方示例包含多个上游来源，不能把 Alpaca 与另一家提供商的同一稿件当成独立确认。[A1] [A3]

### 美股行情

| 用途 | 接口 / SDK | 关键参数与处理 |
| --- | --- | --- |
| 历史 bars | `GET https://data.alpaca.markets/v2/stocks/bars`；`StockHistoricalDataClient.get_stock_bars()` | `symbols`、`timeframe=1Min`、`start/end`、`feed`、`adjustment`、`page_token`；读取所有分页，首个响应可能只有第一只股票 |
| 快照 | `GET https://data.alpaca.markets/v2/stocks/snapshots`；`get_stock_snapshot()` | `symbols`、`feed`；逐项检查实际 trade/quote/bar 的时间 |
| 实时行情 | `wss://stream.data.alpaca.markets/v2/iex`；有权益时 `/v2/sip`；`StockDataStream` | 指定 feed；接收 bars 及迟到修订 updatedBars；断线后补采 |

IEX 单交易所数据与 SIP 汇总行情不同，不能互换为“全市场实时”。盘前盘后窗口保留交易时段、美东时区/DST、复权和延迟；收到第一版 minute bar 后仍可能有修订。按任务核实可用覆盖，再决定是否采用。[A4] [A5] [A6]

## 8. Finnhub：可替换的轻量入口

正式 Python SDK：`finnhub-python`，官方仓库为 Apache-2.0。可直接复用：[H1]

```python
client.company_news("NVDA", _from="2026-11-20", to="2026-11-22")
client.earnings_calendar(
    _from="2026-11-20", to="2026-12-20",
    symbol="NVDA", international=False
)
```

当前官方 Python SDK 使用 `https://api.finnhub.io/api/v1`，路径分别是 `/company-news` 和 `/calendar/earnings`。公司新闻返回 ID、时间、摘要和原文链接；不保证全文。该公司新闻接口未列 `minId` 参数，不能把一般新闻接口的游标移用到这里。采用重叠日期窗口与 ID/内容版本处理。[H2]

当前官方 SDK 以 token 查询参数传递 key，日志需脱敏。个人账号的免费配额、历史范围和每个 endpoint 权限未实测，不以 SDK 公开作为权益证明。

## 9. IBKR watchlist：限定为只读同步

单个已选择列表的接口明确：

`GET {baseUrl}/iserver/watchlist?id=<selected-list-id>`

返回列表 id/hash 与 instruments/conid；首次请求可能只有少量身份信息，不应把缺 ticker 误判为删除。将已验证的完整快照交给现有 `universe.py` 接纳；保持 IBKR 对成员关系的权威，本地研究标签与历史继续由本项目管理。[I1]

枚举列表的官方页面标题是 `GET /iserver/watchlists`，示例却使用 `/iserver/watchlist?SC=USER_WATCHLIST`。这是已发现的文档不一致，采用前按官方支持路径与实际会话核验；这里不静默猜选一个。个人账户认证、会话保持及权限也尚未实测。[I2] [I3]

同步失败保留最后完整快照并显示覆盖状态。现有手工/文件模式应可继续使用，IBKR 自动同步的缺口不应阻止研究系统设计完成。

## 10. 宏观与政策：延伸已有入口

当前 `sources_calendar.py` 已有 Fed FOMC 日历、BLS CPI/就业发布时间与 CMA 通告，优先沿用。Fiscal 财报日历不能替代它们。

可以补充的现成入口：

- Fed 货币政策公告 RSS：`https://www.federalreserve.gov/feeds/press_monetary.xml`，由官方 feeds 页面链接，无需 LLM 搜集。[M1]
- FRED 宏观发布日期：`GET https://api.stlouisfed.org/fred/releases/dates`；需 FRED API key，可用 `file_type=json`、`include_release_dates_with_no_data=true`、`limit/offset`。它提供发布日信息，不保证精确盘中时刻或等同数据在 FRED 实际可用时刻。[M2]

这两项是扩展候选，按现有来源是否有真实缺口决定。政治、监管和行业事件还需各自的来源覆盖，不能宣称一个公司新闻 API 已解决全部事件雷达。

## 11. 给 Codex 的接入检查与报告要求

**本轮设计交付要明确接法；有授权和凭据时才报告真实调用结果。** 后续实现采用所选接口时，至少保留以下证据：

| 检查 | 可接受的具体证据 |
| --- | --- |
| 身份和覆盖 | 已解析的公司/证券身份；该公司该数据集可用、无权限、缺失或尚未验证 |
| 请求真实完成 | 所选 endpoint/实际 MCP tool、参数摘要、时间、结果或错误；不记录秘密 |
| 增量正确 | 重复条目不重复触发，修订能更新，分页与离线补采的覆盖范围明确 |
| 财务语义 | 期间、口径、币种、来源；预期与实际的可得时间匹配 |
| 行情语义 | 具体 listing、feed、时间、时段、复权与延迟 |
| 失败与成本 | 429/权限不足/断线/空结果分别处理；费用与配额包括所有内部调用 |

本文件已完成供应商与协议研究。Codex 应把精力放在当前代码映射、实际可用性和 harness 设计；仅对会影响选择的缺口补查。不要把这些入口再次退化为“以后找一个新闻 API”，也不要宣称所有候选都已接通。

## 官方来源

- [F1] [Fiscal REST Authentication](https://docs.fiscal.ai/docs/authentication)。
- [F2] [Fiscal MCP Integration](https://docs.fiscal.ai/docs/guides/mcp-integration)。
- [F3] [Companies List & Profile](https://docs.fiscal.ai/docs/guides/companies-list)；[v2 → v3 迁移](https://docs.fiscal.ai/docs/migrations/companies-list-v2-to-v3)。
- [F4] [当前 OpenAPI JSON](https://api.fiscal.ai/openapi.json)；[Swagger UI](https://api.fiscal.ai/docs)。本次核查副本 SHA256：`c0cf7401f8e5f53bf0eee77644ae214c64844dc9575ee268fa3e74617bfec0a6`；这是审查快照，不是保证未来接口不变。
- [F5] [Fiscal Free Trial](https://docs.fiscal.ai/docs/guides/free-trial)。
- [F6] [Fiscal API Reference：Street 与 Agentic Consensus](https://docs.fiscal.ai/docs/api-reference)；[Agentic Consensus 定义](https://docs.fiscal.ai/docs/reference/estimates)。
- [F7] [Fiscal Webhooks](https://docs.fiscal.ai/docs/guides/webhooks)。
- [S1] [SEC EDGAR APIs](https://www.sec.gov/search-filings/edgar-application-programming-interfaces)。
- [S2] [SEC Developer Resources](https://www.sec.gov/about/developer-resources)；[请求身份说明](https://www.sec.gov/about/webmaster-frequently-asked-questions)。
- [A1] [Alpaca News REST](https://docs.alpaca.markets/us/reference/news-3)。
- [A2] [alpaca-py NewsClient 源码](https://github.com/alpacahq/alpaca-py/blob/master/alpaca/data/historical/news.py)；[NewsDataStream 源码](https://github.com/alpacahq/alpaca-py/blob/master/alpaca/data/live/news.py)。
- [A3] [Alpaca News Stream](https://docs.alpaca.markets/us/docs/streaming-real-time-news)。
- [A4] [Historical Bars](https://docs.alpaca.markets/us/reference/stockbars)；[Snapshots](https://docs.alpaca.markets/us/reference/stocksnapshots-1)。
- [A5] [Real-time Stock Data](https://docs.alpaca.markets/us/docs/real-time-stock-pricing-data)；[Market Data FAQ](https://docs.alpaca.markets/us/docs/market-data-faq)。
- [A6] [alpaca-py Historical Data](https://alpaca.markets/sdks/python/api_reference/data/stock/historical.html)；[Live Data](https://alpaca.markets/sdks/python/api_reference/data/stock/live.html)。
- [H1] [Finnhub Python SDK](https://github.com/Finnhub-Stock-API/finnhub-python)；[client.py](https://github.com/Finnhub-Stock-API/finnhub-python/blob/master/finnhub/client.py)。
- [H2] [Finnhub 官方 OpenAPI](https://github.com/Finnhub-Stock-API/finnhub-go/blob/master/api/openapi.yaml)。
- [I1] [IBKR Get Watchlist Information](https://www.interactivebrokers.com/docs/web-api/v1/endpoints/watchlists/get-watchlist-information)。
- [I2] [IBKR Get All Watchlists](https://www.interactivebrokers.com/docs/web-api/v1/endpoints/watchlists/get-all-watchlists)。
- [I3] [IBKR Authentication](https://www.interactivebrokers.com/docs/web-api/authentication/introduction)。
- [M1] [Federal Reserve RSS Feeds](https://www.federalreserve.gov/feeds/feeds.htm)。
- [M2] [FRED Releases / Dates](https://fred.stlouisfed.org/docs/api/fred/releases_dates.html)。

仓库事实依据为本次读取的审查快照中的上述文件及 `docs/stock-insight-v3/research/AGENT_AND_DATA_ACCESS.md`、`docs/stock-insight-v3/design/WATCHLIST_SYNC.md`。未来本地代码变化时，以实际 checkout 为准并记录差异。
