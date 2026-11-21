# I1/I2 remediation for independent re-review

**I2 acceptance and I3 are on hold.** All five high and three medium findings have corrective changes and regression coverage. The independent reviewer retains the acceptance decision. The only external acquisition in this pass was a free, unauthenticated NVIDIA issuer request.

## Checkout and preservation

The repair ran in the reviewer's checkout at `E:/OpenAI/ChatGPTDesktop/worktrees/2541/ai-stock-insight`, on `codex/stock-insight-i1-i2`. HEAD at entry was `bfb55d1bdda4527e0789935b6fbef9766a8aefce`. The sole working-tree entry was the supplied, untracked review. Its SHA-256 is `b913382b8b738a1e0c4d504751b3fe05f1008750f777c0411cebb25caf9682b6`. The review remained byte-identical. Test databases, browser profiles and the extracted reviewed code used for baseline checks were disposable. [Original review](implementation-review.md)

The local implementation and test commit is **`48bdb8e7e7936ce738aed8076b73d945f5f17c81`**. Its tracked tree was clean after commit, with only the original review untracked. The following documentation-only commit records this result and updates the release ledger. No changes were pushed.

## Findings and controls

### High · 1 · Financial support for the assessment

**Reproduced.** An ordinary Microsoft run could claim a $12.34 dividend per share with a quotation of `120000000` from an SEC revenue cell. The previous validator checked quote membership and accepted the surrounding conclusion as free text.

**Repair and controls.** The worker selects exact passages, calculation receipts, gaps and a disposition. The service renders the assessment, changes, qualifications and next steps. At acceptance it reads the financial fields again, checks the listing and issuer CIK, actual role, metric, finite decimal, reporting period, currency, units, share basis and accounting basis as applicable, and recomputes the selected comparisons. The frozen manifest includes structured support. The case displays financial metadata beside a numeric SEC citation. The unrelated payout and edits to each material prose field fail. The ordinary scripted MSFT control still accepts **USD 80 million to USD 120 million, +USD 40 million (+50%)**. With only revenue, a scoped dividend gap supports a partial answer. A synthetic USD 0.76 per-share observation for the correct issuer and period can subsequently support the dividend answer. A different issuer, wrong currency/units, a total value presented as per-share, and a nonfinite value cannot. The v2 method covers a bounded accounting vocabulary and source schema. Readers still assess interpretation and source quality. [Assessment tests](../tests/test_insight_assessment.py) · [Gap and financial proof tests](../tests/test_insight_gaps.py)

### High · 2 · Recording and resolving missing evidence

**Reproduced.** The reviewed worker lacked an operation to identify the missing dividend after finding revenue. Separately, an empty search followed by a successful scripted SEC capture and a matching search still left a permanent gap. The service rejected complete submissions both with and without that gap. Failed captures also shared a preset remedy.

**Repair and controls.** A missing metric and period must cite the latest search receipt from that run. Previously read, still-eligible observations count even if they fall off the latest search page. Failed attempts remain in the ledger. A scoped read of qualifying evidence, or a matching successful calculation for a comparison gap, records a resolution with its receipt and exact passage IDs. The final disposition uses the outstanding requirements. Configuration, entitlement, retry, unsupported source and response-semantics problems have distinct remedies. A successful transport alone leaves the gap open. In the MSFT tests, the wrong provider, role, quarter, accounting basis, currency or unit left the gap open. A correct read cleared it and admitted a complete brief. A fresh run could carry the partial forward. The first reviewed body and manifest remained identical after resolution. Price and historical consensus still lack verified sources. [Gap regression sequences](../tests/test_insight_gaps.py)

### High · 3 · Superseded figures at acceptance

**Reproduced.** A worker read 120 from a simulated Microsoft SEC edition. A correction to 95 arrived before submission. The reviewed service accepted 120 as current because the old passage ID and bytes still existed.

**Repair and controls.** Within the submission transaction, material references must still be supported by the source edition eligible at the investigation cutoff. The comparison uses the scoped source stream and financial dimensions. Unchanged observations can move within a revised document. The stale draft now fails before creating an inbox row. Rereading and recalculating in the same run accepts 95. The case shows the accepted calculation and retains the old receipt in its trace. An unrelated source update, an unchanged fact and an explicit cutoff before the correction all pass. The original passage and an earlier reviewed brief remain retrievable. A request for the latest saved quarter also checks newer eligible reporting periods. Coverage of the entire market remains unverified. [Freeze and as-of controls](../tests/test_insight_freeze.py) · [Latest saved quarter test](../tests/test_insight_assessment.py)

### High · 4 · Shared listing identity at confirmation

**Reproduced.** Source A staged a destructive NVDA replacement. B accepted MSFT under the same synthetic contract before A confirmed. The stale confirmation changed B's case subject from Microsoft CIK `0000789019` to NVIDIA CIK `0001045810`. The old confirmation reused import-time assumptions.

**Repair and controls.** The preview identifies its source and affected listings and records the bindings on which it depends. Confirmation recomputes them in the activation transaction. The stale candidate fails after reopening the database. Both accepted snapshots survive, and the existing case still names Microsoft. A compatible second source can share the same stored MSFT listing. A compatible change to a staged binding requires a fresh preview. Permitted single-source listing corrections require explicit confirmation and retain the before/after metadata with the snapshot and commit sequence. Pending schema-1 candidates require a new preview. [Two-source, migration and correction tests](../tests/test_insight_universe.py) · [Browser preview test](../tests/test_insight_web.py)

### High · 5 · Browser credentials on loopback

**Reproduced in Edge.** In one disposable browser profile the reviewed host-scoped cookie reached a third test-owned loopback port. The neutral endpoint reported only whether credentials were present. Both desk sign-ins used synthetic credentials. The check retained no credential values from incoming requests.

**Repair and controls.** The private desk uses an HTTP Basic challenge for its origin and realm, a fresh password per foreground process and username `research`. The browser authenticates requests to each scheme, host and port. The desk issues no cookies. IPv4 loopback binding, exact Host/Origin and CSRF checks still apply. A same-origin referrer policy lets the real browser send a valid Origin on form submissions. In the repaired browser regression, both desks stayed signed in, both accepted an ordinary watchlist form, the third origin received an anonymous request and the cookie jar was empty. Unauthenticated requests and invalid origins/tokens failed in the HTTP tests. This boundary assumes a trusted local OS and browser. The test covered native Windows Edge. [Real-browser regression](../tests/test_insight_browser.py) · [HTTP controls](../tests/test_insight_web.py) · [Operator instructions](../README.md#browser-authentication)

### Medium · 6 · Duplicate continuations

**Reproduced.** Two posts of one reviewed “Investigate again” form returned 303 and left three jobs, briefs and inbox rows including the initial investigation. Each POST generated a new request identity.

**Repair and controls.** The form carries a stable request key and expected case revision. The transaction looks up an existing request before checking the revision. Replaying the same form across a service restart, with renewed authentication and CSRF, returns the original job and leaves two jobs, two briefs and two inbox rows in total. A new key for a stale base fails. A freshly rendered form produces revision 3. [Continuation replay regression](../tests/test_insight_web.py)

### Medium · 7 · Question scope and required checks

**Reproduced.** The fixture answered FY26 Q3 operating margin with FY25 Q1/Q2 revenue. A question about a year-over-year revenue decline required price and consensus, while a share rally required neither. Broad keywords drove both decisions.

**Repair and controls.** The fixture checks its supported metric, issuer vocabulary, reporting horizon, units and available evidence. Ordinary completeness also checks the requested dimensions and calculation horizon. FY26 operating margin and an unsupported year-over-year comparison cannot be completed from the sample revenue pair. A revenue decline alone requires no price or Street check. A question about shares rallying requires price evidence. The dated NVIDIA decision question still reaches a partial brief with its primary qualification and its price and consensus gaps. The Microsoft accounting comparison still succeeds. Unsupported free-form objectives can remain unresolved. [Premise, period and positive controls](../tests/test_insight_assessment.py) · [Executor tests](../tests/test_insight_executor.py)

### Medium · 8 · Listing values and private labels

**Reproduced.** The reviewed parser rejected a fully qualified NASDAQ `CASH` and `MSFT` list. A synthetic account-like identifier embedded in a source label or an instrument field could pass the old whole-string check and be retained.

**Repair and controls.** Headers and instrument values now have separate validation. Qualified common-stock CASH and a recognized contract binding pass. Private report headers and unqualified ambiguous cash rows fail. Embedded account-like identifiers fail in source IDs, aliases and projected fields. Tests verify safe diagnostics, unchanged active membership and absence of synthetic identifiers from SQL dumps and database bytes. A benign source rename and an ordinary qualified MSFT import still succeed. Previously retained schema-1 input was left intact for audit. [Projection and privacy controls](../tests/test_insight_universe.py)

## Verification and integration limits

| Layer | Observed result |
|---|---|
| Existing suite and Stockwatch | 112 tests passed on the reviewed baseline. **136 tests passed with no skips** on the repair, including all 68 original Stockwatch tests and the real-browser test. Stockwatch source has no diff. The offline monitor demo added one issuer document and one linked alert, then zero of each on replay. |
| Local runtime | Native Windows, CPython 3.14.7, SQLite 3.53.1, FastAPI 0.165.0, Uvicorn 0.54.0, MCP 1.30.0, Playwright 1.65.2 and Edge 158.0.4370.33. A reviewed schema-1 fixture upgraded with its original accepted brief intact. A new continuation appended a v2 brief. SQLite integrity returned `ok`. |
| Deterministic fixture | In a separate fixture workspace the synthetic NVIDIA Q1/Q2 FY25 comparison gave 100 to 120 USD million (+20%), a shipment-timing qualification and two unresolved inputs. The saved v2 revision remained available on demo replay. |
| Scripted transport | MSFT used the ordinary adapter and application acceptance transaction with scripted Responses exchanges and synthetic SEC bytes. The Fiscal SDK discovery/probe used simulated transport. Model identifiers and usage in these tests are simulated. |
| Live public-source acquisition | On November 20, 2026 in New York, a fresh unauthenticated application request fetched NVIDIA's August 28, 2024 release. Receipt `check_60255a6ae5a23059bd0e8068` finished at `2026-11-21T03:57:50.184776Z`. Version `doc_986a3986d63f103835d3a12e`, response SHA-256 `645aad1f57b7e7b06022fa1d9da36ee22fa8b854edaae89a0672b510d89cfe0e`. The retained GAAP cells gave **26,044 to 30,040 USD million, +3,996 (+15.3433%)**. This supplies historical issuer data with a 2026 acquisition time. [Issuer table](https://nvidianews.nvidia.com/news/nvidia-announces-financial-results-for-second-quarter-fiscal-2025) |
| Live model and providers | Actual model execution, billing, SEC HTTPS, Fiscal entitlement, broker access and normal-use quality were not tested. Billing was disabled. No subscription, brokerage connection, outbound notification or deployment was activated. |
| Workspace privacy | The inspected local directories granted access to the owner, SYSTEM and Administrators. The checked custom public-test path had no reparse ancestor. Arbitrary custom directories have no automatic effective-ACL/ancestry preflight. WSL interoperability and other browsers remain unverified. |

## Reproduce the checks

From the checkout root on Windows with Edge installed, use the locked dependencies. The workspace-local temporary directory avoids the sandbox's virtual-temp file-replacement issue.

```powershell
uv sync --locked --python 3.14 --extra fiscal --group browser-test
New-Item -ItemType Directory -Force .stockinsight/tmp | Out-Null
$env:TEMP = (Resolve-Path .stockinsight/tmp).Path
$env:TMP = $env:TEMP
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -v
```

For a fresh v2 fixture, choose a new directory or use the example below. Repeating `demo` in an existing directory intentionally reopens the saved revision, including a historical v1 brief.

```powershell
.\.venv\Scripts\python.exe -m stockinsight --data-dir .stockinsight/review-fixture demo
.\.venv\Scripts\python.exe -m stockinsight --data-dir .stockinsight/review-fixture --fixture serve
```

Open `http://127.0.0.1:8765`. Enter `research` and the terminal password in the browser dialog. Open the NVIDIA case to inspect figures, citations, gap remedies and receipts. Ctrl+C stops the desk. The public-data walkthrough uses a separate ordinary directory and port. The next task is independent re-review of the eight findings. [Public-data walkthrough](../README.md#reproduce-the-public-data-check) · [Release ledger](implementation-status.md)

## Second repair pass at 6fbc121

The second pass started on the reviewed branch and commit with two untracked files, the original and independent re-review. I2 acceptance and I3 remain on hold. The following rules and observable closure conditions were recorded before implementation. [Independent re-review](implementation-rereview.md)

| Finding | Rule | Observable closure condition |
|---|---|---|
| High 2 | A gap describes an unmet requirement for this listing. A successful, matching observation or calculation must identify its proof, independently of how an earlier attempt failed. Evidence used to deny a declaration must be accessible to the worker. | A corrected trend closes the reversed attempt exactly once with a receipt and inputs. Another period or metric stays open. The worker can discover and read qualifying evidence at the previous projection boundary. |
| High 3 | An answered financial claim carries the material context of the source edition eligible at freeze. A latest-saved claim must cover its newest eligible period even in a partial brief. A global current claim needs separate freshness evidence. | An amendment adding a qualification forces a reread or visible limitation. An older quarter cannot stand in for the latest available one in a partial or complete answer. A fixed earlier cutoff still supports its original edition. |
| Medium 7 | Completion requires coverage of the original question's market premise and of each requested metric, period and unit. Supported components remain usable when others are missing. | A market-move question preserves a supported revenue comparison as partial with a price/event gap. The accounting-only counterpart can complete. Distinct fiscal years and total versus per-share dividends remain distinct through submission. |
| Medium 8 | Privacy and identity validation depend on the input field and record structure. A complete snapshot changes membership atomically only after every row passes projection. | Qualified PNL and CASH survive with their companion listings. Related valid symbols and unresolved instruments retain their identities. A prohibited account/portfolio field or mixed bad row leaves the accepted list intact and the rejected payload absent from storage and diagnostics. |

### High 2 · Recover the requirement after a failed attempt

At `6fbc121`, reversing the 80 and 120 USD Microsoft observations produced an invalid-input receipt. Correcting their order produced +40 USD (+50%) but left the comparison gap open, with zero resolution records. In a 17-result search the service saw the sole dividend in position 17, withheld it from the worker and denied the worker's missing-dividend declaration.

The gap ledger now identifies the financial series, two reporting intervals, operation and compatible dimensions independently of operand order. The case supplies the listing and information cutoff. A successful comparison must still satisfy the requirement with eligible observations. Its resolution points to the successful receipt and both exact passage IDs. Attempts stay in the trace. The new worker projection exposes every ID the host returns, with compact financial metadata, a 24-item bound and a truncation flag. Previously issued v1 search receipts are interpreted using their original 16-item worker projection. A complete comparison can select its supporting calculation while the manifest retains exploratory and repeated calls. The changes are in `gaps.py`, `bridge.py`, `executor.py` and `research.py`.

The corrected MSFT pair closed its gap once. Different periods, dividends and EUR revenue did not supply its proof. After restart, a reversed retry linked the prior still-eligible receipt without reopening the gap. A new run had to retrieve its own inputs to answer. An amendment from 80 to 85 invalidated the old proof and a fresh +35 calculation closed the reopened requirement. A separate disk check resumed an actual schema-2 partial brief created by the checkpoint binary, resolved the inherited gap and accepted a complete continuation. Its original body, manifest and review timestamp survived. [Comparison and retry controls](../tests/test_insight_gap_recovery.py)

A scripted ordinary worker read result 17 and committed the supported USD 0.61 per-share answer. A separate 25-result run recorded the first page's limitation and used `next_evidence_page` to read the missing datum, resolve its gap once and complete the brief. Each page in `evidence.py` and the bridge uses the original commit boundary and public-information cutoff. The cursor is the issuing page's receipt, scoped to the same investigation. Replays preserved the result and resolution count. An unrelated or terminal receipt failed as a cursor. The resolution record and the closing receipt identify contributing passages and receipts, including qualifying readings split across pages. An unfinished bounded search limits the absence claim to the reviewed passages. [Pagination and cross-page proofs](../tests/test_insight_gap_recovery.py) · [Earlier gap controls](../tests/test_insight_gaps.py)

### High 3 · Freeze the answered figure with its source context and time scope

At the checkpoint, a new edition retained Microsoft revenue of 120 and attributed the increase to an acquisition. The service accepted the earlier assessment without the qualification. With 80 and 120 in the store it also accepted 80 as the latest saved quarter alongside an unrelated price gap. Both the older and newer cells could support a complete answer to a global “last quarter” question. The old comparison checked only the financial fields, the qualifier lookup used one locator in the old edition, and the latest-period guard ran only for complete briefs.

`evidence.py` compares the scoped, cutoff-eligible edition, financial observation, retained cell text and accompanying narrative. `assessment.py` requires all eligible nonfinancial passages accompanying a selected financial document, quotes them and records their IDs on its assertions. The check treats a new footnote at another locator as potential material context. A source consisting of cells alone carries a visible limitation on interpreting causes. This rule applies to retained source content. Text outside the adapter's retained scope still requires source review.

The revised acquisition case rejects the stale draft and a reread that omits the second footnote. Reading and citing both accepts 120 with its qualification. The fixed cutoff before the amendment still accepts the original 120. Current saved-period checks now run for each relevant answered requirement in partial and complete submissions. Q1 alone failed for “latest saved quarterly revenue and price.” Q2 passed with the price gap visible. A separate dated clause cannot narrow the latest requirement to the older date. An unqualified “last quarter” lacks global freshness proof even when the newest saved cell is selected. Explicit historical periods and saved-data questions within the evidence boundary remain supported. [Freeze, time and reconstruction controls](../tests/test_insight_freeze.py)

### Medium 7 · Complete the question that was asked

The checkpoint's ordinary MSFT worker and NVDA fixture both completed a share-price question with a revenue comparison and zero price receipts. Two FY25 observations could also complete a Q1 FY25 / Q2 FY26 request, and a USD 0.61 per-share dividend could complete a question about total dividends. The starting code detected certain verbs, associated quarters with the nearest year, and converted several dividend objectives to one metric.

`assessment.py` now binds each supported metric to the period and units in its clause. It distinguishes tradable-share questions from accounting measures such as shares outstanding or earnings per share. Completion requires the requested coverage, eligible typed observations and any matching calculation. `gaps.py` checks the same requirements. `evidence.py` recognizes aggregate monetary dividends on a total basis. `executor.py` supplies paired requirements to the ordinary worker and preserves supported parts of mixed fixture questions.

With the same 80 and 120 USD inputs, the accounting-only question completed with +40 USD (+50%). A share-move question retained the calculation as partial and identified the missing price and event interval. A nominally successful price receipt with zero observations also failed to substantiate a complete brief. The NVIDIA fixture likewise retained its +20% analysis. Across alternative word orders, a requested FY26 quarter stayed visibly missing until its own observation (135 USD) arrived. The USD 0.61 per-share datum supports a per-share question. A separately sourced 12 USD million aggregate can support its own period and unit in a combined answer. Wording that shares the noun, such as “total and per-share dividends,” retains both requirements. The method remains bounded. Ambiguous objectives can require clarification or review, and sourced arithmetic alone cannot establish the cause of a market move. [Ordinary scripted and fixture controls](../tests/test_insight_question_coverage.py) · [Grounded assessment controls](../tests/test_insight_assessment.py)

### Medium 8 · Parse watchlist fields in context

On the checkpoint the full `PNL,XLON,STK,GBX` row alongside MSFT caused a complete instrument snapshot to be rejected with zero entries. Replacing only PNL with PCT admitted both. A label rule applied to field values included a CASH-specific bypass.

`universe.py` now validates the header/schema first and applies each instrument field's own grammar, including embedded account-ID checks. Explicit ticker-column values can be PNL, CASH or PCT. The native CLI imported the three-row PNL/CASH/MSFT snapshot. The suite verified a qualified UK listing in GBX, US listings in USD, distinct provisional identities from a ticker-only CSV, and unsupported asset types kept as unclassified. Ambiguous header-like input in an unlabeled first line gives a ticker-column remedy. Report-only columns, embedded private headers, formulas or an invalid trailing row rejected the entire snapshot. Active membership and its snapshot ID survived, with synthetic private values absent from SQLite and command output. These changes apply to incoming projections. Prior retained records remain intact. [Import, privacy and shared-identity controls](../tests/test_insight_universe.py)

### Verification boundaries for the second pass

The local repair commit is **`f081d9b236ff0584f9844dae8196e19fb10fece7`**, a direct child of `6fbc121ffbbfa0735cea76b67f116d6d109d8fe4` on `codex/stock-insight-i1-i2`. A documentation-only checkpoint follows it. The final working tree has no staged or tracked changes and contains the two untracked independent reviews. Nothing was pushed. The next decision is targeted independent re-review of High 2, High 3, Medium 7 and Medium 8.

| Layer | Actual evidence |
|---|---|
| Reviewed checkpoint | The locked environment passed all 136 original checkpoint tests in a separate Git archive before repair. Running five of the new assertions against that archive then produced five failures covering all four open findings. |
| Final suite | **151 tests passed, zero skips** with the locked environment, workspace-local TEMP/TMP, Fiscal SDK and native Edge. This included all 68 original Stockwatch tests, fabricated-prose rejection, cross-list issuer identity, the two signed-in desks and neutral third origin, and continuation replay across restart. All 11 changed Python files passed the Ruff formatter check at 110 columns and error checks E4/E7/E9/F. |
| Historical records and Stockwatch | An actual v2 fixture brief created and explicitly reviewed by `6fbc121` retained its entire SQL row and review timestamp across a v3 continuation. SHA-256 over the same serialized row before and after was `1099b11016453c1007417d489eff037c7a9e8b548140097902df9de554fcd045`. The appended revision used `sourced_company_review.v3`. Integrity was OK, and the foreign-key check returned zero rows. The separate offline Stockwatch monitor demo added one issuer document and one linked alert, then zero of each on replay. |
| Deterministic fixture | A fresh NVIDIA demo produced a v3 partial, 100 to 120 USD million (+20%), the issuer's shipment-timing qualification and two open gaps. It used the local fixture driver with zero model requests. |
| Scripted transport | Microsoft research exercised the ordinary worker, real application tools and SQLite acceptance transaction. Input observations and Responses exchanges were synthetic. The installed Fiscal SDK used its mock transport. |
| Live public acquisition | The first restricted DNS attempt reported unavailable. A fresh, unauthenticated NVIDIA issuer HTTPS request then succeeded on November 20 in New York. Receipt `check_329dd65ec00eb1a9a348b49e` completed at `2026-11-21T04:27:49.358934Z`, edition `doc_68b60b8d532e28f48bc975c6`, response SHA-256 `645aad1f57b7e7b06022fa1d9da36ee22fa8b854edaae89a0672b510d89cfe0e`. Q1/Q2 FY25 GAAP revenue was 26,044 and 30,040 USD million, a +3,996 (+15.3433%) change. A repeat returned the same receipt from cache. [Historical issuer table](https://nvidianews.nvidia.com/news/nvidia-announces-financial-results-for-second-quarter-fiscal-2025) |
| Actual model and paid providers | Zero paid calls. Authenticated model execution, live SEC acquisition, Fiscal entitlement, broker access and longitudinal research-quality evidence remain outside this verification. |

The Windows suite invocation and fixture startup commands in the first-pass reproduction section still apply. Use a fresh fixture directory for a new v3 brief, or **Investigate again** for an appended revision on an existing case. The original review and re-review remain untracked, with respective SHA-256 values `b913382b8b738a1e0c4d504751b3fe05f1008750f777c0411cebb25caf9682b6` and `d314f4061c4ba30c7ac67c2f98d75eb712a0ac80c5a796ede602774dac2375ab`.
