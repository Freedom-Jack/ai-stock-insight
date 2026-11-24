# Stock Insight：Codex 架构设计任务书

**v0.3｜2026-11-22｜具体架构设计与审阅文件交付任务**

配套审阅说明：`01-architecture-review-zh.md`。已研究的外部接口与接入依据：`03-interface-reuse-catalog.md`。三份文件应一起保留；02 是执行任务书，03 是事实与接入材料。

**任务性质：** 检查真实仓库，使用已研究接口，完成具体架构设计，并在仓库写出 `docs/architecture-review-v0.3/HARNESS_ARCHITECTURE_REVIEW.md`。具体功能实现仍是后续任务。本文件保持设计空间，你的交付必须作出推荐并解释关键机制，不能只重复需求。

**版本关系：** 本版本延续 v0.2 的产品方向，补齐现成接口与强制交付物。v0.1 的默认框架、预定内部接口契约和固定实施阶段不作为约束。旧材料可以用于查找研究线索，不能被当成已经接受的架构结论。

建议开发会话：`GPT-6.2 Astra / Extra High（xhigh）`，新对话、同一实际仓库。使用客户端实际可见配置；该建议不指定产品日常运行模型。可以用子代理并行调查和互相评审独立问题。

---

## 1. 先建立准确的项目上下文

项目：`https://github.com/Freedom-Jack/ai-stock-insight`，用户指定分支 `codex/stock-insight-i1-i2`。此前审查快照为 `ad86b95b7e71cdb81554a0684bbc43811de01a84`；请以实际 checkout、当前 HEAD 和用户工作区为准。

从 `docs/stock-insight-v3/START_HERE.md`、`design/PRODUCT.md`、`design/ARCHITECTURE.md`、`design/AGENT_WORKFLOWS.md` 和 `docs/implementation-status.md` 理解产品，再沿相关代码确认实际状态。`design/` 在上述 v3 文档目录内。按需检查数据契约、验收与研究背景；遵守适用的 `AGENTS.md`，保留用户现有工作。

明确区分：**已经实现、仅在文档规划、本次新增意图。** 现有文档的“方法修订”“自主研究议程”“重要变化后重新调查”值得延伸，不应因本文重新命名就被当作全新需求。

`delivery/CODEX_START_PROMPT.md`、`delivery/CODEX_RUNBOOK.md` 和旧 build plan 是历史与现状上下文。它们要求立即实施、按固定增量施工的部分，不适用于用户此次明确要求的设计审阅任务。其他适用规则和已有授权继续保留；不要把这种任务范围区分变成未来每一步都需要重复批准。

## 2. 我要得到怎样的系统

这是个人长期使用的股票研究系统。它应能主动跟踪新闻、公告、事件和研究问题，积累对公司及投资假设的理解，帮助我发现变化、安排研究、检验观点和回顾判断。聊天负责表达需求、解释与纠正，也可以产生新的研究工作。

继续保留原产品关于提前准备、日常监测、深入调查、持续跟进、研究议程、判断回顾和执行可见性的意图。财报例子用来检验机制，不能把范围收缩成单一财报工具。当前产品边界仍是研究与决策支持；不因本任务引入交易执行。

关键目标是：**一次研究可能形成以后可复用的观察方法；系统常态运行这些方法，并在值得深入时投入更多工具和模型资源。**

在个人维护成本可接受的前提下，优先复用专家数据、专业计算、公开方法和成熟执行部件。需要自行掌握的，是个人研究状态、方法适用性、任务路由、预算与授权、证据和反馈之间的业务规则。

## 3. 请用这些场景检验你的设计

### 场景 A：日常监测没有重要变化

无需我再发消息，系统能够按已设范围检查必要来源，识别重复和修订，更新覆盖记录。若可以通过确定性检查完成，就不应为每个 tick 启动完整 LLM 工具循环。需要语义判断的部分，可以比较规则、统计方法与有界模型调用。

安静运行也需要能区分“检查过，未见重要变化”和“来源故障、机器未运行或根本没有覆盖”。合并重复通知、重试交付和恢复任务应有解释。事件驱动的行为不预设消息总线、微服务或多个常驻 agent。

### 场景 B：财报研究形成条件式后续工作

我曾问：“这家公司财报不错，为什么股价仍可能下跌？”初次研究应明确预期口径、指引、关键业务指标、价格窗口、反证与数据缺口，并提出下一次值得观察的内容。

下一次财报到来，先判断旧方法哪些部分适用，获取本次必要的新数据，执行成本较低的检查，必要时给出有边界的初判。可以只重算变化相关的部分；遇到重要变化、矛盾、陌生情况或旧方法失效时，再按预算、时限和预授权决定补充数据、深入研究、等待或请求我决定。

区分三件事：**缓存同一输入下的结果；沿用方法处理新数据；用简化方法做近似筛选。** 不得把旧结论的复述当成新研究，也不得用事后取得的当前预期替代公告前预期。缺少输入时，更长的模型调用本身不能补足数据权益或历史数据。

### 场景 C：日常使用逐渐完善流程

我的提问、纠正、已完成研究、能力缺口和失败案例，可以产生候选方法或方法修订。请区分个人偏好、事实、研究假设、可执行检查方法与有验证支持的预测规则。

一次提问不自动等于永久监控授权，一次正确解释也不足以证明市场规律。已有持续目标和预授权范围内，应允许合理的自主推进；是否启用新流程、扩大频率或采用方法修订，应服从配置，而非统一要求逐次确认。

解释候选方法如何被采用、版本化、复查、失效和停用，以及方法遗漏新情况时如何被发现。给陌生事件、反证和有限的探索留入口。这里的改善可以发生在工具组合、检查条件和方法说明层；涉及新能力或代码改动时，需区分运行中的研究权限与开发权限。

## 4. 需要覆盖的逻辑职责

以下是讨论词汇。你可以合并、替换或重新组织，只需说明怎样覆盖相应行为；无需创建同名模块或独立服务。

| 逻辑职责 | 需要回答的设计问题 |
| --- | --- |
| **Event Intake / Source Health** | 什么触发工作？如何处理来源版本、重复、延迟、修订、覆盖空白与采集失败？ |
| **Research State** | 当前关注、证据、假设、反证和未决问题保存在哪里？如何接续，而非只回读聊天历史？ |
| **Method / Playbook Management** | 研究怎样形成可复用的方法？适用范围、依据、成本、采用状态和失效条件如何表达？ |
| **Lightweight Observation** | 哪些新数据必须获取？新信息影响哪些观察与结论？哪些计算可以复用、局部失效或增量更新？怎样表达有限初判与无法判断？ |
| **Scheduling / Policy / Budget** | 怎样选择工作深度、优先级和时机？如何使用已设授权？怎样避免重复工作和无限扩张？ |
| **Deep Research Worker** | 开放式调查如何动态选择专家工具，处理意外信息、反证、停止条件与资料缺口？ |
| **Delivery / Interaction** | 如何交付变化、解释提醒原因、保留纠正记录，并把反馈转回研究与方法？ |
| **Evaluation / Revision** | 如何发现漏报、无必要升级和失效方法？怎样判断修订是否改善质量与成本？ |

请具体划分 harness、LLM 和专业工具的责任。程序应承担可确定的调度、状态管理、缓存校验、计算路由、预算与恢复；LLM 更适合问题拆解、情境解释和方法候选生成。中间地带需要你比较，而非照抄这个初步分工。

针对每个代表性场景，说明哪些模型调用可以省掉、依据是什么、可能损失什么；也说明哪些判断不能可靠交给简单规则。不能通过缩小重要信息覆盖来制造“省 token”的成绩。

## 5. 个人项目的选型原则与设计自由

本轮以**不引入 LangChain / LangGraph**为方向，优先审查现有执行路径与可独立复用的部件。如果你认为这个偏好会造成明确问题，可以提出有证据的反建议，解释具体需要的能力和代价；不要默默把它们放回默认核心。

比较有实质差异的选择，例如扩展当前运行路径，或用薄适配层接入一个成熟研究 worker。不要为了满足“有备选”而列出几个几乎相同的框架名字。移除框架后，超时、取消、恢复、工具错误和计量仍需有人负责。

单机或少量进程是个人项目的重要现实约束。新组件、另一种语言运行时、服务和数据源都需要解释收益、维护面与替代成本。避免多套 agent 逐层包裹、重复调度、重复通知或维护两份权威研究状态。

以下内容由你调查后决定：组件物理边界、playbook 表示形式、模型与规则分工、缓存和失效粒度、工具适配方式、持久化与恢复设计、评估实现，以及现有代码的保留和重构边界。不要因这里出现了候选组件，就预设必须建立相应 registry、DSL 或平台。

金融数据的口径、来源版本、信息可得时点与假设要可追溯。保持现有产品对 live、固定截止时间和不同历史回放含义的区分；具体表示由你核查当前代码后决定。

## 6. 复用应当怎样研究和报告

先使用 `03-interface-reuse-catalog.md`。其中已经核实新闻、SEC 披露、财报日历、财务/KPI、预期、行情与 watchlist 的真实端点、SDK、参数、鉴权、时间与增量边界，以及当前代码的可接位置。不要从零重做相同市场调研，也不要重写供应商已提供的数据采集平台。

你需要补的是：实际 checkout 差异、已配置服务和账号权益、文档冲突、真实 schema 与字段映射，以及所选方案是否满足研究的时效和口径。公开规范、成功鉴权、获得特定数据和研究可用性分别报告。没有凭据时继续完成设计，具体缺口与降级方案写入审阅文件。

固定采集由程序使用 REST、官方 SDK 或 MCP 客户端执行即可；MCP 不要求调用 LLM。保留明确的重试、分页、补采和实际覆盖记录。当前 `providers.py` 的 Fiscal profile probe 与 `tools/list` 发现，并不意味着新闻/行情适配器或完整 `tools/call` 桥已经实现。

主候选是延伸现有公共来源与 Fiscal 接入基础；Alpaca/Finnhub 是有明确缺口时的条件替代。你可否定或替换该候选，但应说明什么覆盖、权限、时效、费用或维护证据支持改变。附录 A 的 agent/runtime 项目仍是选型线索，不是必须全部安装的依赖。

对确实推荐的每个复用项，给出：**来源项目与具体入口、核查版本、直接依赖／API 接入／少量代码适配／仅借鉴设计、依赖与许可证情况、我还需承担的工作，以及为什么比自建合适。** 未验证的地方明确标注，不报虚构的复用比例或性能收益。

闭源产品只能根据公开能力或工程说明判断，不能声称拿到了它的内部架构。专家工具也要核对实际语义：日线反应、盘后反应、同比变化和公告前市场预期差，不能因名称相近就互换。工具返回字段叫 `sources`，也不自动证明它包含可核对的原始证据。

尽量让本项目掌握研究状态与工作政策；外部部件提供可替换的能力。但如果现有边界本身不合适，应指出依据，而非为了保留代码而保留。

## 7. 我希望审阅的产出和证据

### 必须生成的文件

在仓库中新建：

`docs/architecture-review-v0.3/HARNESS_ARCHITECTURE_REVIEW.md`

如果同名文件已有用户工作，保留原内容并使用可追踪的新版本；不要覆盖 `AGENTS.md`、`RULES.md` 或旧架构依据。按仓库现行规则维护必要索引与设计记录。写入设计文件属于本轮交付，不需另设一轮文档写入审批。

开头一屏说明推荐方案、主要取舍和当前实现状态。后文按技术读者能快速审阅的方式组织，详细证据可放附录。必须区分：**已实现、拟议设计、隔离验证结果、未核实假设。**

### 审阅文件必须说明的机制

| 审阅内容 | 具体交付要求 |
| --- | --- |
| **运行拓扑与代码映射** | 推荐采用的模块/进程、责任与状态归属；实际现有文件的保留、修改、替换或新增映射。名称由你选择。 |
| **Harness 核心逻辑** | 事件进入、分流、模型调用、工具循环、停止与升级条件；用短伪代码或时序图显示关键分支，标出确定性代码、LLM 和专家工具。 |
| **上下文与工具** | 每类模型调用看到什么、可调用什么、按需读什么；原始证据怎样回读，怎样减少重复计划、调用和上下文。 |
| **真实接口接入** | 从 03 中选择实际 provider、endpoint/SDK/MCP 及适配位置；说明参数与身份映射、时间、分页、增量/修订、鉴权与数据权益；未实测单列。 |
| **持续方法** | 候选方法怎样采用、执行、局部更新、失效、修订和停用；如何避免把个人意见或一次研究结果变成永久市场规则。 |
| **恢复与费用** | 重复事件、来源失败、超时、重启、预算耗尽和交付失败怎样处理；什么记录证明运行过、覆盖了哪些内容。 |
| **完整场景** | 至少走通安静监测与财报条件研究，并覆盖提问形成候选方法的场景；每步读什么、调用什么、改什么状态，在哪里省去 LLM。 |
| **Eval 与取舍** | 如何检查漏报、无必要升级、证据、方法适用性与真实成本；推荐方向、有意义的备选、未知和会改变选择的证据。 |

你需要自行选择具体方案，不能仅复述候选组件。可提出关键接口草案和必要状态关系，让人能判断 harness 怎样编写；无需穷举数据库字段、所有阈值或完整施工步骤。

同时给出：

- 对真实需求和现有缺口的独立判断，注明哪些是代码事实、文档意图和你的建议。
- 一条推荐方向及有实质差异的备选；用简洁组件图和当前文件映射解释职责、控制流与状态归属。
- 场景 A、B、C 的运行说明。选择最相关的失败情况一起解释，例如来源中断、重复或修订公告、缺失历史预期、重启、方法失效。
- 一份具体复用清单，包含接入成本与尚未验证之处。
- 最可能改变设计选择的不确定性，以及足够判断这些取舍的验证办法。可以做必要的隔离验证；未经实际执行的验证只能列为建议。

评估至少能回答：重要事件有没有漏报；无必要升级有多少；发现延迟与真实总成本如何；数字和结论能否追到证据；方法是否仍适用；修订是否引入新问题。

**要检查被轻量路径跳过的样本。** 只给已升级的报告打分，无法观察筛选漏报。明确重要性判断、事实校验、用户价值反馈和市场结果各自承担什么作用；深度研究本身不是自动真值。历史比较使用当时可获得的资料，预测能力还需关注后续真实事件，避免事后信息和模型已知结局造成误判。

完成标准是：具体审阅文件已写好，我能看清 harness 的执行机制、接口接法、质量与成本取舍，并区分设想与已经实现的能力。不能以“以后再研究这些接口”或只列抽象组件结束。必要隔离验证只报告真实做过的结果；账号缺失不阻止完成可审阅设计。

请主动挑战本任务书的假设，修改缺乏证据的建议。交付后在回复中给出文件路径、重点阅读顺序和确实需要用户决定的少数问题。本轮止于上述具体设计交付；后续进入实现时，再将该文件更新为实际实现后的架构。

---

## 附录 A：已核实的代码与产品线索

**这是来源导航，不是必须全部采用的清单。** 固定 commit 是此前审查快照，公开页面核查于 2026-11-22；采用前仍要确认实际版本与接口。以下均不表示已完成本项目集成。

| 来源 | 具体入口与可复用内容 | 适合的复用方式及限制 |
| --- | --- | --- |
| **Stock Insight** | [当前审查快照](https://github.com/Freedom-Jack/ai-stock-insight/tree/ad86b95b7e71cdb81554a0684bbc43811de01a84)；`stockinsight/research.py`、`assistant.py`、`memory.py`、`monitor.py`、`proactive.py`、`executor.py` | 先核实已有研究、监控、证据和执行链。旧调查、goal/method、assistant 路径之间的上下文与记忆接续，是具体调查点；不预先指定合并方案。 |
| **DSA / daily_stock_analysis** | [MCP server](https://github.com/ZhuLinsen/daily_stock_analysis/blob/603a55e6ddac16aef96f4216847f87323c58d0cb/src/mcp_server.py)；同快照 `src/services/runtime_scheduler.py`、`alert_worker.py`、`analysis_context_builder.py`、`src/schemas/analysis_context_pack.py`；[轨迹 eval](https://github.com/ZhuLinsen/daily_stock_analysis/blob/603a55e6ddac16aef96f4216847f87323c58d0cb/docs/agent-trajectory-eval.md) | MIT。MCP 可作能力接入候选，调度和上下文部件可借鉴。分析接口内部仍可能调用模型；完整费用与来源质量需核实，避免再启用一套通知和调度。 |
| **Dexter** | [Agent](https://github.com/virattt/dexter/blob/534f6be455523c5926eba72bdaf4f914555be5c9/src/agent/agent.ts)；同快照 `src/agent/microcompact.ts`、`compact.ts`、`src/utils/tool-result-storage.ts`、`src/evals/` | 可参考工具循环、压缩和大结果管理，或论证是否适合作独立 worker。内部 Agent API 不视为稳定公共 SDK；TypeScript/Bun 增加运行成本。README 声明 MIT，该快照未见独立根 LICENSE，直接复制前需补核授权材料。 |
| **Pi** | [正式 SDK](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/sdk.md) 与同目录 CLI integration；[许可](https://github.com/earendil-works/pi/blob/main/LICENSE) | MIT。session、工具和模型循环可作为 runtime 候选；需解释对现有 Python 项目增加 Node/Bun 的收益。不要把通用编码工具权限默认交给研究任务。 |
| **Fiscal.ai** | [MCP Skills](https://docs.fiscal.ai/docs/guides/mcp-skills)；[MCP 接入](https://docs.fiscal.ai/docs/guides/mcp-integration) | 有权限时复用数据、工具和专家方法。可下载 skill 不等于已核实开放再分发许可；API/MCP 权益须单独核实。`earnings-reaction` 的口径不能直接视为公告前 Street consensus 与盘后事件研究。 |
| **Samaya** | [Research Platform](https://samaya.ai/product/platform)；[公开 harness 工程说明](https://samaya.ai/blog/rl-post-trained-agentic-model) | 产品公开支持报告转工作流、定时或来源事件触发研究、thesis 跟踪。这里只借行为模式和公开工程思路；生产 harness 未发现可直接复用源码。 |
| **QuantConnect / LEAN** | [Algorithm Performance](https://www.quantconnect.com/docs/v2/writing-algorithms/key-concepts/algorithm-performance)；[Scheduled Events](https://www.quantconnect.com/docs/v2/writing-algorithms/scheduled-events)；[Insight Manager](https://www.quantconnect.com/docs/v2/writing-algorithms/algorithm-framework/insight-manager) | 借轻量事件处理、按用途控制频率和判断失效的原则。Insight 是其量化接口对象，不能直接等同于本项目 thesis；此处不建议导入完整交易引擎。 |
| **FrontierFinance** | [独立 grader](https://github.com/samaya-ai/frontier-finance)；[数据集](https://huggingface.co/datasets/samaya-ai/FrontierFinance) | grader 代码 Apache-2.0，rubric 数据另为 CC-BY-4.0；当前数据页面有访问条件。可作报告质量 eval 候选，不能代替本项目的事件漏报、持续方法与恢复评估。 |
| **TradingAgents / ValueCell** | [TradingAgents 日期过滤](https://github.com/TauricResearch/TradingAgents/blob/9fa1196fffbcfd9de5146d2dd2869df84ab99838/tradingagents/dataflows/date_window.py)；[ValueCell ResearchAgent](https://github.com/ValueCell-ai/valuecell/blob/9793e9c0563fbf56fc096757d8bb80e209ac7aab/python/valuecell/agents/research_agent/core.py) | 两项目原创代码均为 Apache-2.0。用于审查局部机制和平台边界；不默认复用多角色交易流程。日期过滤不解决所有时点问题，对话持久化也不等于研究状态完整恢复。 |
| **AlphaSense** | [Custom and Scheduled Workflow Agents](https://help.alpha-sense.com/hc/en-us/articles/48564685232275-Custom-and-Scheduled-Workflow-Agents) | 闭源产品对照，借定期交付与异步工作流体验；定时调度和新资料实时触发须分别核实，不推断其内部实现。 |

## 附录 B：为什么把交接写成设计任务

[OpenAI 当前 Codex prompting 指南](https://learn.chatgpt.com/guides/prompting-gpt-6-2-astra)建议说明所需结果和审阅标准，并保持项目长期指令精简；[通用 prompting 指南](https://learn.chatgpt.com/docs/prompting)同样强调结果、相关上下文和边界。

因此，本文件提供产品行为、来源线索和可检验的问题，把未经验证的实现决定保留给 Codex。它不依赖某一种特殊提示词形式，也不保证某个模型自动给出最佳架构。模型与 effort 使用当前客户端实际配置，本任务书不虚构模型特有能力。

本轮推荐设置的依据：[OpenAI Model selection](https://learn.chatgpt.com/docs/model-selection)。新对话与 CLI 命令行为参见 [Developer commands](https://learn.chatgpt.com/docs/developer-commands?surface=cli)。不需要把这次开发用的模型和 effort 自动复制到常态新闻检查中。
