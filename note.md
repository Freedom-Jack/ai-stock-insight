use different library to gather data like browser use
visualization of the trend data
folder seperation customization, by type/usage/group, whatever
rate limit difference handling

## 2026-11-23 晚间想法｜留待 11 月 24 日讨论

以下是三个探索方向。具体可行性、现有架构的支持程度和工具选型都待讨论。

### 1. 只维护 IBKR 里的 watchlist

希望把 IBKR watchlist 当作唯一权威来源（source of truth）。日常只在 IBKR 增删标的，助手只需要读取其中的 tickers，省去维护第二份名单的工作。

最关心的是授权边界。券商登录凭据由自己掌握，Agent 拿不到凭据，也没有读取持仓、余额或下单的权限。希望这条边界由 IBKR 或其官方 MCP／连接器强制执行。明天值得先问：即使 Agent 请求了其他操作，哪一层会拒绝它？另一个关于稳定性的问题是，读取失败时，助手能否区分「暂时读不到」和「名单确实为空」？

### 2. 第一个想试的工具是 portfolio analyzer

希望能直接问助手「帮我看看这个组合怎么样」，由它调用已有的 portfolio analyzer，再解释结果。可以先拿一个具体问题做例子，比如「我的持仓是否过于集中？」，再看现有工具需要哪些输入。

这里有个值得分开讨论的点：watchlist 表达我在关注什么，实际持仓和权重才说明我持有多少。若要分析真实组合，可以单独考虑由我提供持仓快照等输入方式。分析组合这件事本身不意味着要扩大上面那条 watchlist 连接的权限。

### 3. 让 AI 调用现成工具

希望分析能力尽量来自已有工具。开源项目和提供 connector 的闭源服务都可以考虑。理想的使用方式是我提出问题，AI 选择合适的工具、传入获准使用的数据，再帮我读懂输出。Portfolio analyzer 可以作为检验这个架构想法的第一个例子。

明天留两个问题：沿着当前项目的一次实际工具调用看，接入已有 analyzer 需要改哪些地方？现有生态里，有没有让 ChatGPT、Claude 或 Muse 这类个人助手直接访问同一工具的架构或方案可以借鉴？

## 2026-11-23｜第一轮调研

后续实测已完成，详见[三项验收记录、虚构组合与原始工具回执](docs/acceptance/2026-11-23-portfolio/README.md)。

### IBKR 的连接与授权

IBKR 已经运营官方 MCP。用户在 IBKR 页面登录，助手拿到授权，登录密码留在券商一侧。产品页列出了 watchlist 管理，FAQ 也说明数据访问限于获准工具。不过，公开资料里没有找到一份授权说明，能确认普通用户可以单独授予「只读一份已有名单的成分」，同时由 IBKR 拒绝读取持仓、余额、订单以及修改名单。助手端的工具开关不能证明券商端授予了同样窄的权限。官方还说明每个账户同时只能连接一个 AI 平台，授权另一平台会断开前一连接。[IBKR AI Integration](https://www.interactivebrokers.com/en/trading/ai-integrations.php) · [连接与权限 FAQ](https://www.interactivebrokers.com/support/faq/content/connecting-ibkr-account-ai-platform-1437187133)

现阶段可让 IBKR 继续作为唯一编辑入口，按需在 TWS 导出所选名单的金融工具，再把标的字段映射到项目已有的文件导入格式。这是按导出时间更新的快照。项目已能区分文件不可读与空名单，并会保留待确认的大幅删减。直接兼容 TWS 原始导出格式、授权到期后的自动恢复及无人值守同步都未实测。下一条值得核实的证据是 IBKR 的授权项目清单，或其对「能否只授权读取选定名单」的明确答复。[TWS 导出说明](https://www.interactivebrokers.com/support/faq/content/34485530) · [项目的快照导入逻辑](stockinsight/universe.py)

### 第一个 portfolio analyzer

| 想验证的事 | 现成工具 | 所需输入和取舍 |
| --- | --- | --- |
| 快速判断一份真实组合的集中度 | IBKR PortfolioAnalyst 的 Concentration 报告 | IBKR 负责计算。用户可仅分享日期、必要的权重和基金穿透结果，由助手解释。官方有可用于演练的公开样例。[报告字段](https://www.ibkrguides.com/portfolioanalyst/performanceandstatements/pa_reportpages.htm) · [持仓样例](https://www.ibkrguides.com/portfolioanalyst/performanceandstatements/holdings-report-sample.pdf) |
| 验证助手直接调用第三方 analyzer | Morningstar 官方 MCP 的 Portfolio X-Ray | 提交自定义标的和权重，可查行业敞口及 ETF 底层持股重叠。输入会交给 Morningstar；公开自助试用为 30 天且仅覆盖指定样本，个人账户的正式授权与价格待核实。[X-Ray 工作流](https://developer-beta.morningstar.com/morningstar-mcp-server/run-portfolio-xray) · [试用范围](https://developer-beta.morningstar.com/trial-access) |
| 以后在本地分析波动和风险贡献 | 开源 Python 库 skfolio | 输入各资产的历史收益与权重。项目若要提供 MCP 调用，需要接行情数据并封装一个入口。以当前权重回算得到的是假设组合历史，实际账户业绩还取决于历史仓位与现金流。[skfolio 组合模型](https://github.com/skfolio/skfolio/blob/main/docs/user_guide/portfolio.rst) |

建议第一个验证问题用「持有两只 ETF 再加一只个股，穿透后哪家公司权重最大？」。从供应商覆盖的证券中构造示例，只给标的和权重，要求工具返回日期、底层敞口和未覆盖部分。这样能观察到 analyzer 相比直接排列持仓权重提供的额外信息，也能独立检验它是否值得接入。

### Stock Insight 应该负责什么

项目已有面向助手的 MCP 服务。以 watchlist 为例，助手调用后，项目读取本地有效名单，返回上市标识及名单中的排序；这里的 position 是名单序号。反方向已有面向 Fiscal.ai 的 MCP 工具目录发现，当前预检只列工具。项目里的财务比较等方法仍由本地代码执行。目前检查的调用路径里没有通用的第三方组合分析执行器。[助手的工具入口](stockinsight/assistant_mcp.py) · [Fiscal.ai 预检](stockinsight/providers.py) · [本地研究方法](stockinsight/methods.py)

建议先让助手作为 MCP host，分别连接 Stock Insight 和一个获准使用的 analyzer。前者提供研究上下文；后者接收用户为这次分析选定的输入并计算。只有确实需要把结果留在项目的研究记录里，再定义回写哪些结果、日期和来源。Morningstar 已提供 ChatGPT 和 Claude 的接入说明。若 Muse 指 Meta Muse，官方支持 custom connector，但这次没有核实它与 Morningstar 的具体认证兼容性。[MCP 架构](https://modelcontextprotocol.io/docs/learn/architecture) · [Morningstar 客户端设置](https://developer-beta.morningstar.com/morningstar-mcp-server/set-up-morningstar-mcp) · [Meta Muse 连接器](https://www.meta.com/en-gb/help/superintelligence/1687253048996149/)
