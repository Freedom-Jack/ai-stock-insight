# Design Stock Insight’s future

User messages and assistant replies from the completed research and implementation turns on November 5, 2026. [Decision memo](../../decision-memo.md) · [Research desk design](../../research-desk-design.md)

## Turn 1

### User

Research and design what Stock Insight could become. That’s a working name. The product direction is open.

I follow companies and encounter more filings, news, emails, and outside analysis than I can absorb. What feels missing in the current Stockwatch design is what happens after an alert. It can tell me that an earthquake may matter to companies I follow and point me to a supplier’s filing. I value that evidence trail. But I still have to read the filing, compare it with what the company said before, and figure out whether five articles add independent evidence or repeat the same claim.

That reading, synthesis, and first pass of reasoning is the work I want to delegate. I want help noticing connections, understanding competing interpretations, and deciding what deserves a closer look. I want to form my own investment conclusions.

Read the existing project, its design documents, and the newer research at monitoring-research.md. Research beyond them and challenge my assumptions. I’m interested in an agent-driven experience that could draw on analysts or methods I trust. Use your judgment about the product, the role of agents, what to reuse, and whether to build or borrow the orchestration.

Give me a concise decision memo to read first, followed by the deeper design you think the idea warrants. I’m the lead AI architect. Show me what using your proposed product would feel like, why it’s worth pursuing, and which uncertainties matter enough to change your recommendation.

Stay in research and design. Stop for my review before building, spending money, or deploying anything.

### Assistant

I’ll read the project and the newer monitoring research, then check the assumptions behind a few possible directions. I’ll put the decision memo first and use a worked example in the deeper design so you can judge what the product would actually take off your plate. I’ll stop at design review.

### Assistant

I found the working Stockwatch implementation in a sibling worktree. It already does something worth preserving: it can match a TSMC filing to an earthquake watch while leaving the operational assessment open for review. I’m using that handoff as the starting point and checking what a research agent could add by reading the filings themselves.

### Assistant

The historical filings surfaced a useful test case. TSMC’s earthquake loss stayed at roughly NT$3 billion, but its status changed from an estimate to a booked loss. That settles one question while leaving NVIDIA delivery effects unresolved. I’ve used that distinction in the design, and I’m checking the proposed trial against what an existing research assistant could already do with the same sources.

### Assistant

[**Read the decision memo first**](../../decision-memo.md) · [**Read the deeper design and worked examples**](../../research-desk-design.md)

**I recommend a personal research desk organized around questions you’re still trying to answer.** Give it a Stockwatch alert, filing or selected email. It should tell you what changed since your last review, trace repeated claims to their origin, and point you to the passage most likely to change your interpretation.

The Taiwan earthquake shows what that could feel like. Two outlets carried the same Reuters dispatch about TSMC’s loss estimate. A later filing contributed something more valuable: TSMC had now *booked* roughly NT$3 billion, close to its estimate. That settles an accounting question. Whether NVIDIA shipments slipped still calls for different evidence. The desk should let you close one question and carry the other forward. [Reuters via MarketScreener](https://www.marketscreener.com/quote/stock/TSMC-TAIWAN-SEMICONDUCTOR-6492349/news/TSMC-estimates-losses-of-92-4-mln-due-to-Taiwan-earthquake-46470240/) · [Same dispatch via Radio USA](https://radiousa.com/2024/04/18/tsmc-estimates-losses-of-92-4-million-due-to-taiwan-earthquake/) · [TSMC’s Q2 accounts, note 34](https://investor.tsmc.com/sites/ir/financial-report/2024/TSMC%202024Q2%20Consolidated%20Financial%20Statements_E.pdf#page=51)

**Borrow the orchestration. Make custom software earn its place on the second disclosure.** Compare the desk with a well-prompted existing assistant and a saved research note. Count the time you spend checking sources and fixing mistakes. If the saved note works as well, keep it. If the desk reliably catches consequential changes you would miss, or gives you meaningful time back, that identifies which capability is worth owning.

I stopped at design review. The comparison, implementation, purchases and deployment are all pending your review.
