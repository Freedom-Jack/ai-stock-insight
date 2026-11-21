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
