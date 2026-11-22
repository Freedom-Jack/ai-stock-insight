# Windows research model

The Windows trial can run Qwen2.5-0.5B-Instruct on the local CPU. The model selects a research method. Stock Insight then reads the listing’s permitted passages, records tool receipts and checks each reported figure before accepting a brief. A model selection alone does not establish a financial result.

From the checkout in PowerShell, install the pinned assets once and check the three research methods.

```powershell
.\.venv\Scripts\python.exe -m stockinsight.local_model install
.\.venv\Scripts\python.exe -m stockinsight.local_model verify
```

Installation requires Windows x64, the project's Python environment and internet access to download two public artifacts totaling 516,412,097 bytes. They are stored under `.stockinsight/models/qwen2.5-0.5b/`. Repeating the install command checks existing assets. The model archive is excluded from Git.

| Component | Pin | SHA-256 |
| --- | --- | --- |
| Qwen2.5-0.5B-Instruct, GGUF Q4_K_M | `9217f5db79a29953eb74d5343926648285ec7e67` | `74a4da8c9fdbcd15bd1f6d01d621410d31c6fc00986f5eb687824e7b93d7a9db` |
| llama.cpp Windows x64 CPU archive | `b12602` | `9957dab2f52e2599b85921ef3e2661287c1f3ad302bc0be07992e915cc6f7392` |

The model publisher and runtime project provide the pinned artifacts. [Qwen model revision](https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct-GGUF/tree/9217f5db79a29953eb74d5343926648285ec7e67) · [llama.cpp release](https://github.com/ggml-org/llama.cpp/releases/tag/b12602)

`verify` performs real offline inference with the installed weights. It asks one financial comparison question, one stock-price question and one issuer-disclosure question, and reports the selected method and elapsed time for each. Three correct choices exercise this small control set. Accuracy on arbitrary questions is unmeasured.

Each inference stages the verified model, CPU libraries, executable and prompt into its own scratch directory. Allow about 650 MB of free temporary storage in addition to the installed assets. The process starts suspended in a fresh Windows AppContainer. Stock Insight checks the actual process token and requires zero capability SIDs before resuming it. The Windows package receives read/execute access to its own scratch files and inherits only three standard input/output handles. The model runs offline with deterministic sampling, a 60-second timeout and a grammar restricted to the application's method IDs. It receives no provider credentials. The service collects public sources separately. A failed isolation check stops the model attempt.

From a normal Windows user session, run the following against the intended private workspace directory.

```powershell
.\.venv\Scripts\python.exe -m stockinsight.model_access --workspace .stockinsight
```

The check uses a signed Windows reader and disposable files. On the trial machine the reader could open the allowed input. The OS denied reads of the synthetic private SQLite database, provider credential marker and unrelated file, including the extended Windows path spelling. Their bytes were unchanged. The process token reported AppContainer membership and zero capabilities. A standard AppContainer may read machine resources deliberately made available to all Windows application packages. Workspace permissions remain relevant. No WSL distribution was available to verify WSL interoperability. [Windows AppContainer isolation](https://learn.microsoft.com/en-us/windows/win32/secauthz/implementing-an-appcontainer)

## Windows user-session notifications

A saved goal can generate a private generic Windows popup while the desk's browser is closed. The foreground desk must remain running in the signed-in user's unlocked session. The popup shows **Open report** and **Dismiss**. Its private URL uses the running desk's loopback port. The account and ticker stay out of the external message.

Workspace status lists the research report, delivery attempt, provider acceptance, confirmed Windows display when observable, and an explicit report-open request as separate records. Human reading and explicit brief review have their own evidence. A known failure retries with backoff. An ambiguous acknowledgement waits for explicit operator confirmation before a resend.

```powershell
.\.venv\Scripts\python.exe -m stockinsight.delivery_check
```

This opt-in check sends one generic popup from a disposable workspace. On November 22, 2026 at 02:30:35 UTC, a separate observer process confirmed the test window on the active input desktop in session 1. The native window measured 335 by 156 pixels and its centre was unobscured. No browser was launched and no open request was recorded. The test provides no evidence that the user read it. To check a recent report notice while its popup is still displayed, use `--workspace PATH --notice-id ID`. That mode sends nothing. [Windows desktop visibility](https://learn.microsoft.com/en-us/windows/win32/winstation/desktops) · [Window visibility API](https://learn.microsoft.com/en-us/windows/desktop/api/winuser/nf-winuser-iswindowvisible)

## ChatGPT subscription check

This optional command invokes the installed native Codex app-server over stdio and prints selected account and quota metadata. It requests no token refresh, never starts a model turn and does not print account identifiers, balances or reset-credit details.

```powershell
.\.venv\Scripts\python.exe -m stockinsight.codex_worker
```

On this trial machine, the native Desktop binary reported version `0.171.0-alpha.13`; the separately installed CLI reported `0.151.0`. The Desktop account and rate-limit calls succeeded under the signed-in account. The primary quota window was 93% used at the time of the probe. The reported credits flags were both false. These are observations at the time of the check.

The installed thread/turn protocols expose dynamic application tools, filesystem sandboxes and final-output schemas. We could not verify an exclusive application-function surface or a per-turn included-allowance-only billing control. Credit usage can follow included plan limits. Hosted Codex was left disabled for this trial. [Codex app-server protocol](https://developers.openai.com/codex/app-server/) · [ChatGPT credit usage](https://help.openai.com/en/articles/12642688-using-credits-for-flexible-usage-in-chatgpt-personal-plans)
