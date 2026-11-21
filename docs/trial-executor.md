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

Inference checks the model and runtime digests again, extracts the local completion executable and its CPU libraries, and runs it in offline mode with deterministic sampling and a 60-second timeout. Its grammar permits only the supplied plan IDs. The prompt contains the question and worked examples. The subprocess receives a minimal Windows environment, and the model has no application credentials or operating-system tools. Temporary runtime and prompt files are removed after the subprocess exits. Stock Insight records the actual selected method, model revision, digests, runtime version and timing. Public-source acquisition runs in the host application and may require internet access.

## ChatGPT subscription check

This optional command invokes the installed native Codex app-server over stdio and prints selected account and quota metadata. It requests no token refresh, never starts a model turn and does not print account identifiers, balances or reset-credit details.

```powershell
.\.venv\Scripts\python.exe -m stockinsight.codex_worker
```

On this trial machine, the native Desktop binary reported version `0.171.0-alpha.13`; the separately installed CLI reported `0.151.0`. The Desktop account and rate-limit calls succeeded under the signed-in account. The primary quota window was 93% used at the time of the probe. The reported credits flags were both false. These are observations at the time of the check.

The installed thread/turn protocols expose dynamic application tools, filesystem sandboxes and final-output schemas. We could not verify an exclusive application-function surface or a per-turn included-allowance-only billing control. Credit usage can follow included plan limits. Hosted Codex was left disabled for this trial. [Codex app-server protocol](https://developers.openai.com/codex/app-server/) · [ChatGPT credit usage](https://help.openai.com/en/articles/12642688-using-credits-for-flexible-usage-in-chatgpt-personal-plans)
